# Project Status, Tech Stack & Known Limitations

The single source of truth for **what is built, what is intentionally not built, and what still
needs live verification**. Read this alongside `ARCHITECTURE.md` (how the system is built) before
making structural changes.

> **System status: paper-trading v1, feature-complete.** The full pipeline — market data →
> analytics → strategies → scoring → deterministic risk gate → Claude review → Telegram approval →
> execution → intraday monitor → EOD reporting — is implemented and covered by the test suite
> (IBKR mocked). The Streamlit dashboard has been archived to `Archive/dashboard/`.
> **Not yet validated on a live account.** Live cutover is gated behind
> `LIVE_TRADING=true` + the live port + a per-order second confirmation (see `SETUP.md` §11).

---

## What is built

Every stage of the desk pipeline exists in `src/` and is exercised by `tests/`:

- **Market data** (`src/ibkr/`) — connection manager with backoff + `AutoReconnect`, batched option
  chains within the line limit, live Greeks/IV, historical IV backfill, portfolio/account snapshots.
- **Analytics** (`src/analytics/`) — IV rank/percentile (from `iv_history`), term structure & skew,
  **VRP** (IV% − HV30%, computed in `iv.py`, displayed on every candidate), **VIX** (fetched from
  yfinance `^VIX` once per scan via `market_conditions.py`, shown in scan completion summary),
  technicals + regime, fundamentals (yfinance), liquidity gates, optional Reddit sentiment,
  Black-Scholes delta fallback (`black_scholes.py`) for quotes missing IBKR model Greeks.
  VIX (and each candidate's VRP) is also injected into the Claude review prompt as a macro-vol
  regime hint — enrichment only, never a deterministic gate. Fundamentals/HV are day-cached
  (`src/common/cache.py`) so the 15-min loop doesn't re-hit yfinance every cycle.
- **Strategies** (`src/strategies/`) — covered call, cash-secured put (would-own allowlist), rolling,
  buy-to-own.
- **Decision + safety** (`src/engine/`) — score normalization, weighted ranking, and the
  deterministic, portfolio-aware **Rules Engine** (cumulative concentration / sector / CSP-collateral /
  buying-power gates + per-candidate ROC/yield/IV-rank/DTE/delta/earnings-blackout) with a second
  live-quote gate at send time.
- **Claude** (`src/claude/`) — headless `claude -p` runner, resilient parser, prompt templates, and a
  persistent learning loop (`claude_memory`, all four outcomes recorded).
- **Verdict learning loop** (`src/claude/eval/`, `src/claude/skills/`) — an **outcome ledger**
  (`verdict_ledger`) records, per Claude-reviewed candidate, the signal vector Claude saw + its
  verdict + the deterministic baseline; a **reconciler** back-fills the realized outcome
  (expired / closed-early / assigned / not-filled, P&L) when the trade closes (runs at EOD +
  `scripts.reconcile_outcomes`). **Verdict scoring** (`scripts.evaluate_verdicts`) reports
  calibration (Brier) and EV of following Claude vs the baseline, on held-out windows and per
  month. A **skill loop** lets Claude draft reasoning playbooks from that labeled history
  (`scripts.propose_skill`), which a human promotes (`scripts.skills promote`) into
  `config/skills/active/` for injection into review prompts. **The fence:** skills shape verdict +
  ranking only — the risk engine, weights, and sizing stay human-edited config (enforced by
  `tests/test_eval_skills.py`).
- **Execution** (`src/execution/`) — mid-price limit-order builder (tick-aware), executor with fill
  monitoring + live second confirmation, approval→execution bridge.
- **Notify** (`src/notify/`) — stateless sender + long-running approval/command daemon (Telegram).
- **Monitor** (`src/monitor/`) — event-driven intraday watch; all four triggers (delta drift, DTE,
  IV spike, ex-div) wired end-to-end.
- **Orchestrators** (`src/orchestrator/`) — morning scan, EOD report, shared `/scan` pipeline with
  live in-chat progress updates (stage-by-stage message edits via `_Tracker`). VIX is fetched at
  scan start and shown in the completion message.
- **15-minute intraday loop** — runs inside the approval_service daemon every 15 minutes during
  RTH. Each cycle: (1) checks short option positions for 50% profit-take threshold, (2) runs a
  full scan — but new-entry scans stop after `scheduler.entry_cutoff` (default 15:00 ET); profit-take
  checks still run until the close. The whole cycle body is wrapped in a catch-all so one bad cycle
  cannot kill the loop. Behaviour depends on mode (see below). RTH is now determined by the shared,
  **holiday-aware** `src/common/market_hours.is_rth` (the single source of truth for both the
  intraday loop and the order-transmission gate) — full-day NYSE holidays and 13:00 ET early
  closes are respected, not just weekday + clock.
- **MANUAL / AUTOMATED mode toggle** (`/mode` Telegram command) — persisted in the `system_settings`
  SQLite table via `src/storage/system_settings.py`. In **MANUAL** mode (default): scan candidates
  get Approve/Reject buttons; profit takes send alerts only. In **AUTOMATED** mode: candidates are
  directly queued for execution (no human tap), profit-take targets trigger BUY-to-close orders
  automatically via `execution/position_manager.close_short_position` — which records an
  `OrderRow`/`FillRow`, cancels on timeout, and is idempotent at the contract level (SYSTEM_REVIEW
  F1). The deterministic risk gate still re-validates every new-exposure order before execution in
  both modes; buy-to-close (risk-reducing) skips the gate but is still recorded.
- **AUTOMATED-mode circuit breakers** (`src/execution/circuit_breakers.py`) — `max_auto_trades_per_day`
  and `daily_loss_halt_pct` bound activity and losses (the risk gate only bounds exposure). A persisted
  `/halt` kill switch (auto-engaged on a daily-loss breach) stops all transmission while still allowing
  profit-take closes. A cross-process scan lease prevents concurrent scans from breaching the
  market-data line cap. Nightly `data/backups/` snapshots protect the system of record.
- **Storage** (`src/storage/`) — SQLite + SQLAlchemy, WAL mode, lightweight column migration.
- **Dashboard** — read-only Streamlit views archived to `Archive/dashboard/` (optional `[dashboard]` extra; restore folder to `dashboard/` to reinstate).

---

## Tech stack

| Layer | Choice | Notes |
|---|---|---|
| Broker / data | **`ib_async`** | Maintained successor to `ib_insync`. Real-time + historical. Import as `from ib_async import ...` — never add the legacy `ib_insync`. |
| Numerics | `pandas`, `numpy`, `scipy` | Scoring and stats. Black-Scholes delta via `scipy.stats.norm` (`src/analytics/black_scholes.py`). |
| Fundamentals | `yfinance` | FCF, debt, earnings/ex-div dates (supplemental only). |
| Schemas | `pydantic` v2 | Typed contracts between modules (`src/common/schemas.py`). |
| Storage | **SQLite + SQLAlchemy** | Postgres is a config change away; not migrated. |
| Scheduling | system **`cron`** for one-shots; `asyncio` for the daemons | Never run a threaded scheduler in the same process as an `ib_async` loop. |
| Approval / notify | `python-telegram-bot` v21+ | Inline keyboards + callback handlers. |
| Claude | **Claude Code CLI (`claude -p`)** | Headless, subscription-based, JSON I/O — not the API. |
| Claude tools | `trading_skills` MCP via `.mcp.json` (opt-in) | Ad-hoc lookups during roll reasoning. clientId 20. |
| Config | `PyYAML` + `python-dotenv` | YAML for rules/weights, `.env` for secrets. |
| Dashboard | `Streamlit` | Read-only views off SQLite. Archived to `Archive/dashboard/`. |
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
| **Black-Scholes Greeks fallback** | **Built** (`src/analytics/black_scholes.py` + `_enrich_greeks_yf` in `market_data.py`). After each IBKR chain fetch, quotes with `delta=None` are enriched from yfinance IV via Black-Scholes. Enables paper-account scans without a live market-data subscription. Sets `greeks_source="black_scholes"` on enriched quotes. |
| **Multi-leg / roll execution** | Rolls are **alert-only**. The order builder is single-leg SELL; the executor refuses `ROLL` candidates. Acting on a roll is manual. |
| **Live limit-order repricing** | The executor places one mid-price limit and cancels on timeout — it does not chase an unfilled order. Adding an unverified `placeOrder` modification to the broker path was deferred until it can be validated on a live paper session. |
| **`max_correlated_exposure_pct`** | Configured in `risk_limits.yaml` but **not enforced** — needs a price-correlation engine. The per-ticker and per-sector caps *are* enforced. |
| **`option_quotes` table reads** | `option_quotes` is written every scan (one row per symbol/run) as an audit trail. No production code reads from it; it is write-only. The EOD run now prunes rows older than 14 days via `storage.maintenance.purge_old_option_quotes`, so it no longer grows unboundedly. |
| **`BuyCandidate.rationale`** | Always an empty string. Claude enrichment for buy-to-own recommendations is not yet implemented. |
| **yfinance caching** | **Built.** `get_fundamental_stats` and `_compute_hv30` are wrapped with `@daily_cached` (`src/common/cache.py`) — memoized per calendar day in-process, so the 15-min intraday loop fetches each symbol's fundamentals/HV at most once a day instead of every cycle. One-shot cron scripts get no benefit (process exits) and no harm. VIX is still fetched once per scan (it moves intraday and is cheap). |
| **Ledger assignment detection** | The reconciler classifies every past-expiry short with no closing buy as `expired_worthless` — the common income-desk case. True **assignment** must be flagged explicitly (`scripts.reconcile_outcomes --assigned <id>`), because reliable auto-detection needs position-history diffing that isn't built. The `assigned` realized P&L is the option-leg premium only; stock-leg P&L from assignment is not modelled in the ledger. |
| **Verdict-EV survivorship** | EV (`evaluate_verdicts`) is conditioned on **executed and settled** trades — candidates that were rejected or never filled have no realized counterfactual, so the comparison measures Claude as a filter/ranker over trades that happened, not over the full slate. Every report states this caveat. |
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

## Bugs fixed (2026-06-12 system review — SYSTEM_REVIEW.md Phase 1)

The independent review in `SYSTEM_REVIEW.md` found 8 new findings (F1–F8) not covered by
the 2026-06-02 remediation. Phase 1 (the AUTOMATED-mode safety gate) is fixed; the remaining
findings are sequenced in `IMPROVEMENT_PLAN.md`.

- **F1 Auto-close bypassed the order infrastructure (P0 the moment AUTOMATED mode runs):** the
  profit-take auto-close called `ib.placeOrder` directly — no `OrderRow`/`FillRow`, no
  cancel-on-timeout, no idempotency. A working DAY close that didn't fill in time stayed open while
  the next intraday cycle placed a *second* buy-to-close (risking a net-long position); EOD cashflow
  omitted the BUY debit; and the verdict-ledger reconciler mislabeled the close as
  `expired_worthless`, corrupting learning-loop labels. **Fixed:** new
  `src/execution/position_manager.py::close_short_position` routes the close through the same
  `OrderRow`/`FillRow` lifecycle + cancel-on-timeout as entries, and is idempotent at the contract
  level (deterministic `close:` candidate id + `has_active_order`). `_auto_close_position` is now a
  thin Telegram-notification wrapper. Buy-to-close still skips the income Rules Engine gate (it is
  risk-reducing) but always records the order/fill.
- **F3 Malformed `entry_cutoff` silently killed the intraday loop:** `SchedulerCfg.morning_scan`,
  `eod_report`, and `entry_cutoff` now have a Pydantic `HH:MM` validator (fail loud at config load),
  and the intraday-loop body is wrapped in a catch-all so a single bad cycle can never propagate out
  of `while True` and kill profit-takes/scans without an alert.
- **F4 entry-cutoff feature untested:** added `is_new_entry_window` boundary tests (15:00 exact,
  early-close day, holiday, custom cutoff, malformed string) and `SchedulerCfg` time-validation tests.

## Bugs fixed (2026-06-12 system review — SYSTEM_REVIEW.md Phase 2, pre-live cutover)

- **F2 No premium-collapse re-gate:** `validate_live_quote` now rejects a fill (`live_premium_collapse`)
  when the live mid drops below `risk_limits.yaml → live_execution.min_live_premium_ratio` (default
  0.80) of the approved premium — closing the IV-crush gap (approved at $2.50, filled at $0.60) the TTL
  only bounded.
- **F6 yfinance greeks could gate live trades:** in LIVE mode, `validate_live_quote` now requires
  IBKR-sourced live greeks (`live_greeks_required`) for income candidates — the paper Black-Scholes/
  yfinance delta fallback can no longer vet a real-money fill. Gated by
  `live_execution.require_ibkr_greeks_when_live` (default `true`). Paper mode keeps the degrade-on-
  missing-greeks behaviour.
- **AUTOMATED-mode circuit breakers + kill switch:** new `src/execution/circuit_breakers.py` enforces
  `automation.max_auto_trades_per_day` (cap on new-exposure entry orders per ET day, enforced in
  `process_queued_orders`) and `automation.daily_loss_halt_pct` (auto-engages the kill switch on a
  daily realized-loss breach). The `/halt` and `/resume` Telegram commands flip a persisted
  `execution_halted` switch checked by the order-poll loop, the auto-queue path, and the intraday loop;
  profit-take closes still run while halted (closing risk is always allowed).
- **F5 Cross-process concurrent scans:** a persisted scan lease (`system_settings.acquire_scan_lease`/
  `release_scan_lease`, wrapped around `run_scan`) serialises full scans across processes, so the
  morning cron and the 15-min daemon loop can no longer compete for the ~100 market-data line cap. The
  morning cron is now optional (the loop makes it redundant) — documented in SETUP.md.
- **No DB backup story:** the EOD run now calls `maintenance.backup_database()` — a consistent online
  SQLite snapshot into `data/backups/`, rotated to the last 7. The system of record (orders, fills,
  learning history) is no longer a single point of failure.

---

## Remaining known issues (not fixed — require live validation or design decision)

- **Overnight stale data:** `validate_live_quote` re-checks delta and price but not DTE or earnings
  date, which are loaded from the scan-time DB record. A Friday-approved trade executing Monday morning
  will not re-check if earnings were announced over the weekend. Mitigate: reduce `approval.ttl_minutes`.
- **Share ownership at execution:** CC candidates do not re-verify underlying share ownership at
  execution time. If shares are sold between scan and approval, a naked call could result. Mitigate:
  reconcile positions manually before going live. (Scan-time sizing *does* now net out calls already
  written against the underlying — see "Order idempotency" below — but the execution-time re-verify
  against a fresh position snapshot is still not implemented.)
- **Order idempotency (fixed):** `candidate_id` is a deterministic hash, so a re-scan — especially the
  15-min automated loop — regenerates the identical candidate. Both order-creation paths
  (`sender._auto_queue_candidates`, `approval_service._process_button`) now consult
  `storage.orders.has_active_order` and refuse to create a second order when one is already
  QUEUED/SUBMITTED/FILLED/PARTIAL for that candidate. Combined with covered-call sizing that nets out
  existing short calls (`generate_cc_candidates(existing_short_calls=…)`), this closes the path where
  the automated loop stacked duplicate writes into naked short calls. Residual: the
  `has_active_order` check is application-level, not atomic — two concurrent callbacks for two
  *different* approvals of the same candidate could still race. A partial unique index on
  `orders.candidate_id` (active states) would close it fully.
- **Unqualified contracts in monitor/greeks enrichment:** The intraday monitor and
  `enrich_positions_with_greeks_async` subscribe market data with unqualified contracts. `cancelMktData`
  may not match the subscription, leaking lines against the ~100-line cap over extended sessions.
  Needs a live session to verify actual impact.
- **Post-reconnect fill recovery (mostly addressed):** On service startup,
  `approval_service._reconcile_orphan_fills` queries `ib.reqExecutionsAsync()` and recovers any
  SUBMITTED order whose fill event was lost during a disconnect — matching by broker order id, then
  by contract — writing the missing FillRow, marking the order FILLED/PARTIAL, and notifying Telegram.
  It is strictly additive (only records proven fills; never cancels or resubmits), so it cannot cause
  a double trade. Residual gap: recovery runs only at **startup**, not continuously, and a fill that
  lands during a mid-session reconnect is recovered on the next restart rather than immediately —
  still monitor `/status` after a TWS restart during an active order.
- **`next_earnings=None` bypass:** When yfinance cannot provide an earnings date, the earnings
  blackout gate is skipped. ETFs never earn; individual stocks without calendar data pass silently.

**Partially-addressed / remaining SYSTEM_REVIEW.md findings (see `IMPROVEMENT_PLAN.md`):**
- **F7 (partially fixed):** `reconcile_orphan_fills` (now in `src/execution/reconciliation.py`) runs
  **periodically** from the intraday loop, not only at startup — so a SELL fill that lands during a
  mid-session reconnect is recovered on the next cycle. **Still open:** a *manual buy-to-close in TWS*
  writes no FillRow (the reconciler only recovers SELL-side executions tied to a SUBMITTED order), so
  the ledger can still mislabel a position closed outside the system. Extending the sweep to BUY-side
  executions matched against open ledger positions needs careful P&L attribution and is deferred.
- **F8 (fixed):** `_check_profit_takes` now derives the entry credit from `_net_entry_credit_per_share`
  — the qty-weighted average of *all* SELL fills for the contract, net of entry commission — instead of
  the last single fill.

**Deferred structural items (hygiene — see `IMPROVEMENT_PLAN.md` Phase 3):**
- The profit-take/auto-close *orchestration* (`_check_profit_takes`, `_auto_close_position`) stays in
  `approval_service` because it drives Telegram notification; the reusable *close mechanics* are already
  factored into `execution/position_manager.close_short_position`, and broker reconciliation now lives
  in `execution/reconciliation.py`.
- Sync/async market-data twins (`_batch_quotes`/`_batch_quotes_async`, etc.) are **not** consolidated:
  the sync `_batch_quotes` is the version the line-cap/cancel-discipline tests exercise, so collapsing
  it risks weakening that coverage without a live session to re-validate. Deferred deliberately.

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
back to Telegram. The full checklist is in `SETUP.md` §11. The three-layer guard
(`LIVE_TRADING=true` + live port + per-order `[CONFIRM LIVE]` second tap) and the loud startup banner
must both be verified on the first live run with a single small position.
