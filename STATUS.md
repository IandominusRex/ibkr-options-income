# Project Status, Tech Stack & Known Limitations

The single source of truth for **what is built, what is intentionally not built, and what still
needs live verification**. Read this alongside `ARCHITECTURE.md` (how the system is built) before
making structural changes.

> **System status: paper-trading v1, feature-complete.** The full pipeline — market data →
> analytics → strategies → scoring → deterministic risk gate → Claude review → Telegram approval →
> execution → intraday monitor → EOD reporting → Streamlit dashboard — is implemented and covered by
> the test suite (IBKR mocked). **Not yet validated on a live account.** Live cutover is gated behind
> `LIVE_TRADING=true` + the live port + a per-order second confirmation (see `SETUP.md` §12).

---

## What is built

Every stage of the desk pipeline exists in `src/` and is exercised by `tests/`:

- **Market data** (`src/ibkr/`) — connection manager with backoff + `AutoReconnect`, batched option
  chains within the line limit, live Greeks/IV, historical IV backfill, portfolio/account snapshots.
- **Analytics** (`src/analytics/`) — IV rank/percentile (from `iv_history`), term structure & skew,
  technicals + regime, fundamentals (yfinance), liquidity gates, optional Reddit sentiment.
- **Strategies** (`src/strategies/`) — covered call, cash-secured put (would-own allowlist), rolling,
  buy-to-own.
- **Decision + safety** (`src/engine/`) — score normalization, weighted ranking, and the
  deterministic, portfolio-aware **Rules Engine** (cumulative concentration / sector / CSP-collateral /
  buying-power gates + per-candidate ROC/yield/IV-rank/DTE/delta/earnings-blackout) with a second
  live-quote gate at send time.
- **Claude** (`src/claude/`) — headless `claude -p` runner, resilient parser, prompt templates, and a
  persistent learning loop (`claude_memory`, all four outcomes recorded).
- **Execution** (`src/execution/`) — mid-price limit-order builder (tick-aware), executor with fill
  monitoring + live second confirmation, approval→execution bridge.
- **Notify** (`src/notify/`) — stateless sender + long-running approval/command daemon (Telegram).
- **Monitor** (`src/monitor/`) — event-driven intraday watch; all four triggers (delta drift, DTE,
  IV spike, ex-div) wired end-to-end.
- **Orchestrators** (`src/orchestrator/`) — morning scan, EOD report, shared `/scan` pipeline.
- **Storage** (`src/storage/`) — SQLite + SQLAlchemy, WAL mode, lightweight column migration.
- **Dashboard** (`dashboard/`) — read-only Streamlit views (optional `[dashboard]` extra).

---

## Tech stack

| Layer | Choice | Notes |
|---|---|---|
| Broker / data | **`ib_async`** | Maintained successor to `ib_insync`. Real-time + historical. Import as `from ib_async import ...` — never add the legacy `ib_insync`. |
| Numerics | `pandas`, `numpy`, `scipy` | Scoring and stats. (No Black-Scholes module — see "Not built".) |
| Fundamentals | `yfinance` | FCF, debt, earnings/ex-div dates (supplemental only). |
| Schemas | `pydantic` v2 | Typed contracts between modules (`src/common/schemas.py`). |
| Storage | **SQLite + SQLAlchemy** | Postgres is a config change away; not migrated. |
| Scheduling | system **`cron`** for one-shots; `asyncio` for the daemons | Never run a threaded scheduler in the same process as an `ib_async` loop. |
| Approval / notify | `python-telegram-bot` v21+ | Inline keyboards + callback handlers. |
| Claude | **Claude Code CLI (`claude -p`)** | Headless, subscription-based, JSON I/O — not the API. |
| Claude tools | `trading_skills` MCP via `.mcp.json` (opt-in) | Ad-hoc lookups during roll reasoning. clientId 20. |
| Config | `PyYAML` + `python-dotenv` | YAML for rules/weights, `.env` for secrets. |
| Dashboard | `Streamlit` | Read-only views off SQLite. |
| Quality | `pytest`, `ruff`, `mypy` | IBKR mocked in tests. |

### Optional: the `trading_skills` MCP

`.mcp.json.example` registers the [`staskh/trading_skills`](https://github.com/staskh/trading_skills)
MCP so the headless `claude -p` subprocess can do ad-hoc lookups (`ib_portfolio`,
`ib_find_short_roll`, `option_greeks`, …) while reasoning about rolls. It is **opt-in**: copy it to
`.mcp.json` to enable (it auto-runs external code). It opens its own TWS connection on **clientId 20**
— never reuse that id. The deterministic engine never depends on it; its market data is delayed.

---

## Not built (deliberately deferred)

| Item | Status & reason |
|---|---|
| **Black-Scholes Greeks fallback** | Planned (`analytics/greeks.py`) but never built. The system trusts IBKR live `modelGreeks`; if they're absent, the affected quote degrades (candidate dropped / `entry_iv` left `None`). The `OptionQuote.greeks_source = "black_scholes"` branch is therefore currently unreachable. |
| **Multi-leg / roll execution** | Rolls are **alert-only**. The order builder is single-leg SELL; the executor refuses `ROLL` candidates. Acting on a roll is manual. |
| **Live limit-order repricing** | The executor places one mid-price limit and cancels on timeout — it does not chase an unfilled order. Adding an unverified `placeOrder` modification to the broker path was deferred until it can be validated on a live paper session. |
| **`max_correlated_exposure_pct`** | Configured in `risk_limits.yaml` but **not enforced** — needs a price-correlation engine. The per-ticker and per-sector caps *are* enforced. |
| **`option_quotes` table reads** | `option_quotes` is written every scan (one row per symbol/run) as an audit trail. No production code reads from it; it is write-only and will grow unboundedly. Schedule periodic cleanup if disk space is a concern. |
| **`BuyCandidate.rationale`** | Always an empty string. Claude enrichment for buy-to-own recommendations is not yet implemented. |
| **yfinance caching** | Fundamentals/HV are re-fetched every scan (failures are logged, not cached). |
| **Backtesting engine, ML regime detection, vol forecasting, Postgres migration, local-LLM hybrid** | Future ideas, not started. |

---

## Bugs fixed (2026-06-02 full-system audit — P0/P1 remediation)

All P0 and P1 bugs from the 2026-06-02 audit have been fixed:

**P0 (real-money risk — fixed):**
- **P0-01 TOCTOU double-order:** `OrderRow` now has `UniqueConstraint("approval_id")`; `_process_button` wraps the insert in `try/except IntegrityError` so concurrent Telegram callbacks produce exactly one order.
- **P0-02 Orphan SUBMITTED orders:** On startup, `_recover_orphan_orders()` resets SUBMITTED rows with no `ib_order_id` back to QUEUED.
- **P0-03 Stale candidate data on re-scan:** `_persist_candidates` deletes the existing row before inserting fresh data; `CandidateRow` has `UniqueConstraint("candidate_id")`.
- **P0-04 DB session held across IBKR I/O:** `process_queued_orders` fetches account/positions before opening the session, not inside it.
- **P0-05 Double-subscribe on AutoReconnect:** `_on_reconnect()` clears `_subscriptions` and `_entry_iv` before calling `_refresh_subscriptions`, preventing duplicate market-data lines.
- **P0-06 `cancelMktData` silent no-op:** `_subscriptions` now stores `(PositionSnapshot, Contract)` tuples; the original subscribed Contract object is used for cancellation.
- **P0-07 Stale spot price from `snapshot=True`:** `_get_spot` and `_get_spot_async` fall back to `reqHistoricalData` for the last daily close bar when the snapshot returns NaN or 0.
- **P0-08 CONFIRM LIVE uses pre-wait quote:** In live mode, `_fetch_quote`, `validate_live_quote`, and `build_limit_order` now execute *after* the CONFIRM LIVE event fires, not before.
- **P0-09/10/11 Test gaps:** Added `tests/test_buy_candidates.py` (full coverage), `test_connection.py` (AutoReconnect), and concurrent double-execution test in `test_execution.py`.

**P1 (should-fix — fixed):**
- **P1-01/02 Rolling ROC/collateral fiction:** ROC now uses `roll_credit / new_strike` (not entry premium); collateral is `strike × contracts × 100`.
- **P1-03 IBKR negative bid sentinel:** `_clean_bid()` in `market_data.py` converts −1.0 to `None`; `validate_live_quote` rejects `bid < 0` with `negative_bid_sentinel`.
- **P1-04 `bid=0` inconsistency:** `build_limit_order` now accepts `bid=0` with a valid ask; uses `ask/2` as effective mid for far-OTM options.
- **P1-05 Delta sign not validated:** `validate_candidates` rejects PUT candidates with positive delta and CALL candidates with negative delta (`delta_sign_mismatch`).
- **P1-06 `max_contracts` not enforced:** The `max_contracts` config key is now checked in `validate_candidates` (`contracts_exceeds_max` reason).
- **P1-07 Stale DTE in re-validation:** `process_queued_orders` recomputes DTE from `cand.expiry` before Phase 1 re-validation.
- **P1-08/19 Wrong buying power field:** `get_account_snapshot` populates `buying_power` from `AvailableFunds` (not the 2–4× leveraged `BuyingPower` tag); CSP sizing uses `excess_liquidity`.
- **P1-09 `_reconnecting` flag race:** `AutoReconnect._on_disconnect` sets `_reconnecting = True` synchronously before `create_task`.
- **P1-10 Infinite AutoReconnect loop:** `AutoReconnect` accepts `max_reconnect_attempts` (default 20); logs CRITICAL after exhaustion.
- **P1-11 Per-candidate TTL:** `expires_at` is computed inside the candidate loop so each candidate has a fresh TTL window.
- **P1-12 Send failure leaves phantom PENDING:** On `bot.send_message` failure, the approval row is immediately marked EXPIRED so it never blocks execution.
- **P1-13 No Telegram on TTL-null cancel:** `process_queued_orders` now sends a Telegram notification when it cancels an order for missing TTL.
- **P1-14 Journal duplicate rows:** `JournalRow` has `UniqueConstraint("entry_date")`.
- **P1-15 ARG_MAX risk in Claude runner:** All three `subprocess.run` calls in `runner.py` now pass the prompt via `stdin` instead of `-p`, bypassing the 128 KB ARG_MAX limit.
- **P1-16 HV simple vs log returns:** `_compute_hv30` now uses log returns (`np.log(close / close.shift(1))`) matching IBKR's log-normal IV model.
- **P1-17 IV percentile with tiny history:** `iv_percentile` returns `None` when fewer than 30 observations are available.
- **P1-18 ATR score backwards:** The ATR contribution that penalised high-ATR stocks has been removed from `technical_score` in `_scoring.py`.
- **P1-20/21 Cron timezone and supervisor:** SETUP.md updated with `TZ=America/New_York` cron prefix and process supervisor examples.

**Previously fixed (2026-06-01 audit):**
- Double-execution poll loop, rolling collateral 10× undercount, DTE zero-division, live re-gate stale quotes, `expires_at=None` bypass, market-data line leak, AutoReconnect silent failure, IV percentile off-by-one, EOD net delta, DTE timezone, RTH boundary, migration concurrency, IV history uniqueness, ClaudeReview recommendation validation, bid=0 `_fetch_quote` acceptance, config drift.

---

## Remaining known issues (not fixed — require live validation or design decision)

- **Overnight stale data:** `validate_live_quote` re-checks delta and price but not DTE or earnings
  date, which are loaded from the scan-time DB record. A Friday-approved trade executing Monday morning
  will not re-check if earnings were announced over the weekend. Mitigate: reduce `approval.ttl_minutes`.
- **Share ownership at execution:** CC candidates do not re-verify underlying share ownership at
  execution time. If shares are sold between scan and approval, a naked call could result. Mitigate:
  reconcile positions manually before going live.
- **Unqualified contracts in monitor/greeks enrichment:** The intraday monitor and
  `enrich_positions_with_greeks_async` subscribe market data with unqualified contracts. `cancelMktData`
  may not match the subscription, leaking lines against the ~100-line cap over extended sessions.
  Needs a live session to verify actual impact.
- **Post-reconnect fill recovery:** If IBKR disconnects between `placeOrder` and fill, the fill event
  is lost. No startup reconciliation against `ib.reqExecutions()` exists. Monitor order status via
  `/status` and IBKR's own app after any TWS restart during an active order.
- **`next_earnings=None` bypass:** When yfinance cannot provide an earnings date, the earnings
  blackout gate is skipped. ETFs never earn; individual stocks without calendar data pass silently.

---

## Validated by mocked tests only — verify on a live paper session before live cutover

These behaviours are correct in unit tests (IBKR mocked) but their real-world timing/recovery has
not been exercised against a live TWS/Gateway:

- **`AutoReconnect`** actually recovering a dropped socket and the monitor re-subscribing market data.
- The executor's **greeks-wait** capturing `entry_iv` / a live delta on real OPRA tick timing (if
  greeks consistently lag past the window, `entry_iv` stays `None` and the IV-spike baseline is absent).
- The **async on-loop** market-data and monitor paths under a real event loop (no cross-thread errors).
- A full **approve → fill → confirm** cycle on paper, including the new cumulative send-time re-gate
  and the CSP-budget sizing actually producing fills (tighten `max_csp_allocation_pct` to confirm a
  rejection fires).

---

## Live cutover gate

Do not flip `LIVE_TRADING=true` until **≥ 10–20 successful paper cycles** have filled and confirmed
back to Telegram. The full checklist is in `SETUP.md` §12. The three-layer guard
(`LIVE_TRADING=true` + live port + per-order `[CONFIRM LIVE]` second tap) and the loud startup banner
must both be verified on the first live run with a single small position.
