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
  regime hint — enrichment only, never a deterministic gate. Daily OHLCV (technicals + HV30) is
  served from an **incremental store** (`price_history` via `analytics/price_data.py`): scans read
  settled bars from SQLite and fetch only the missing tail from yfinance, instead of pulling a full
  1y/3mo history per symbol every run. Fundamentals are day-cached (`src/common/cache.py`); the live
  price is fetched fresh each call so it stays current.
- **Strategies** (`src/strategies/`) — covered call, cash-secured put (would-own allowlist), rolling,
  buy-to-own.
- **Decision + safety** (`src/engine/`) — score normalization, weighted ranking, and the
  deterministic, portfolio-aware **Rules Engine** (cumulative concentration / sector / CSP-collateral /
  buying-power gates + per-candidate ROC/yield/IV-rank/DTE/delta/earnings-blackout) with a second
  live-quote gate at send time.
- **Claude** (`src/claude/`) — headless `claude -p` runner, resilient parser, prompt templates, and a
  persistent learning loop (`claude_memory`, all four outcomes recorded). Local-LLM (Ollama)
  backend (`ollama_runner.py`, `config/settings.yaml → claude.backend`): `"cli"` (`claude -p`
  only), `"ollama"` (local model only), or `"cli_then_ollama"` (try `claude -p`, fall back to
  local on failure). **This deployment currently runs `backend: "ollama"`** — no `claude -p`
  access, so `review_candidates`/`review_roll`/`write_journal_narrative` all go to a local
  `qwen3:14b` via Ollama (`think: false`, `num_ctx: 8192`). Same `ClaudeReview`/`RollReview`
  validation and fail-soft contract regardless of backend; active skills inject identically. See
  SETUP.md §14. `scripts.propose_skill` (the skill-proposal loop, `proposer.py`) also dispatches
  on `claude.backend` — under `"ollama"` it drafts proposals via `ollama_runner.propose_skill`
  (`parse_ollama_skill_proposal`), so it works without CLI access too. The only thing that
  remains `claude -p`-only is the `trading_skills` MCP (ad-hoc tool lookups during `claude -p`'s
  agentic loop) — Ollama's integration is single-shot prompt→JSON with no tool-calling loop, so
  it's inactive in this deployment.
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
- **Orchestrators** (`src/orchestrator/`) — EOD report, shared `/scan` pipeline with
  live in-chat progress updates via `_Tracker`, which edits **two** messages: a stage-by-stage
  checklist and a dashboard (progress bar + ETA, current-activity line, and a 🔴-flagged running
  error log). Per-symbol dashboard edits are throttled to respect Telegram's edit-rate limits. VIX
  is fetched at scan start and shown in the completion message.
- **15-minute intraday loop** — runs inside the approval_service daemon every 15 minutes during
  RTH, **clock-aligned to ET quarter-hour marks** (9:30, 9:45, 10:00, ... via
  `src/common/market_hours.seconds_until_next_aligned_mark`) rather than process-start-relative,
  so cycle times are predictable and consistent across restarts. Each cycle starts by sending a
  short "🔄 Scan started · HH:MM ET" Telegram message (`src/common/market_hours.now_et_hhmm`) so an
  operator can see the schedule is firing on time even before any candidates/heartbeat are sent.
  Each cycle then: (1) checks short option positions for 50% profit-take threshold, (2) runs a
  full scan — but new-entry scans stop after `scheduler.entry_cutoff` (default 15:00 ET);
  profit-take checks still run until the close. The whole cycle body is wrapped in a catch-all so
  one bad cycle cannot kill the loop. Behaviour depends on mode (see below). RTH is now determined
  by the shared, **holiday-aware** `src/common/market_hours.is_rth` (the single source of truth
  for both the intraday loop and the order-transmission gate) — full-day NYSE holidays and 13:00
  ET early closes are respected, not just weekday + clock.
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
| Claude | **Claude Code CLI (`claude -p`)** | Headless. Since 2026-06-15, draws from a separate monthly Agent SDK credit pool (billed at API rates), not the interactive subscription. **Not used in this deployment** — `claude.backend: "ollama"` (no CLI access); both review and `scripts.propose_skill` dispatch to Ollama instead. |
| Claude tools | `trading_skills` MCP via `.mcp.json` (opt-in) | Ad-hoc lookups during roll reasoning. clientId 20. Requires `claude -p`; inactive in this deployment. |
| Local LLM (**active**) | **Ollama** (`httpx` → `localhost:11434`), model `qwen3:14b` | `claude.backend: "ollama"` — sole backend for `review_candidates`/`review_roll`/`write_journal_narrative` in this deployment (`think: false`, `num_ctx: 8192`). See SETUP.md §14. |
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
| **Black-Scholes Greeks fallback** | **Built, then layered IBKR-first (S2, Phase 3).** Greeks are resolved in three tiers: (1) `_ticker_to_quote` reads the first available IBKR per-contract computation (`modelGreeks` → `lastGreeks` → `askGreeks` → `bidGreeks` via `_pick_greeks`) so a lagging model tick still yields genuine IBKR greeks (`greeks_source="ibkr"`); (2) `_enrich_greeks_from_ibkr_iv` BS-fills delta locally from an IBKR IV with no network call; (3) only quotes IBKR could value neither greeks nor IV for fall through to the yfinance Black-Scholes download (`_enrich_greeks_yf`), now **instrumented** (logs how many quotes forced a Yahoo fetch + the elapsed time per symbol). Tiers 2/3 set `greeks_source="black_scholes"` so the F6 live gate still treats them as untrusted. The scan batch requests generic ticks `101,106` to capture the IBKR IV. |
| **Multi-leg / roll execution** | **Built (Phase 4).** A `Strategy.ROLL` candidate is executed as one atomic BAG combo — BUY-to-close the old short + SELL-to-open the new short, no legging risk — via `src/execution/roll_executor.py::execute_roll` (`executor.execute_candidate` delegates instead of refusing). `order_builder.build_combo_roll_order` builds the BAG + net LimitOrder (credit → negative net-debit limit). Re-gates the new leg (`validate_live_quote` delta/live-greeks) + a net-credit floor, LIVE-mode [CONFIRM LIVE] tap, cancel-on-timeout, and writes two FillRows (BUY under the original short's id → ledger `closed_early`; SELL under the new id → monitor tracks it). **Combo limit-price sign convention is mock-tested only — verify on live paper first** (see below). **Wired end-to-end (N20):** when `monitor.roll_execution_enabled` is set, a roll trigger generates a candidate (`execution.roll_pipeline.queue_roll_for_approval`) and sends it with Approve/Reject buttons → QUEUED ROLL order → `execute_roll`. Default OFF until the BAG sign is verified on live paper; until then rolls remain alert-only. |
| **Live limit-order repricing** | **Built (Phase 4), default OFF.** `order_builder.reprice_limit` + a chase loop in `executor.execute_candidate`: an unfilled SELL is repriced toward the bid every `reprice_interval_seconds` for up to `max_reprices` steps (never below `min_live_premium_ratio × approved premium`), then cancels on timeout. Gated by `execution.reprice_enabled` (false by default) because the `placeOrder` amend is unverified on a live account — see the live-verification list below. Only the single-leg entry path chases today; buy-to-close and roll combos reuse `reprice_limit` when wired later. |
| **`max_correlated_exposure_pct`** | Configured in `risk_limits.yaml` but **not enforced** — needs a price-correlation engine. The per-ticker and per-sector caps *are* enforced. |
| **`option_quotes` table reads** | `option_quotes` is written every scan (one row per symbol/run) as an audit trail. No production code reads from it; it is write-only. The EOD run now prunes rows older than 14 days via `storage.maintenance.purge_old_option_quotes`, so it no longer grows unboundedly. |
| **`BuyCandidate.rationale`** | A deterministic one-liner built from the screen's own signals (IV richness, VRP, regime, quality, earnings proximity) in `buy_candidates.py` — Claude does **not** review buy-to-own names (only option candidates), by design. The buy-to-own screen applies a score floor + count cap (`scoring_weights.yaml → buy_to_own`, currently 10 names max). The Telegram message (`format_buy_list`) groups candidates by sector (indexes, tech, semis, financials, healthcare, …) with each sector block wrapped in a Telegram spoiler (`||…||`) that collapses until tapped; sectors are sourced from `universe.yaml → sectors` via the `BuyCandidate.sector` field. |
| **yfinance caching** | **Built, then upgraded to an incremental store.** Daily OHLCV (the 1y history for RSI/MACD/SMAs/ATR/support-resistance/regime **and** HV30) is persisted in the `price_history` table and loaded by `analytics/price_data.get_ohlcv`, which fetches **only the missing tail** from yfinance (or a full year when the store is empty) and is itself `@daily_cached` per calendar day in-process. So scans no longer pull full per-symbol histories every run — steady state makes zero yfinance history calls (the store is current); the 15-min loop reuses the day cache; and a cold process reads settled bars from SQLite instead of re-downloading a year. Seeded by `scripts/backfill_prices.py`, kept fresh by the EOD daily-bar append (mirrors the `iv_history` N4 pattern). `get_fundamental_stats` remains `@daily_cached`. Reddit sentiment (`sentiment.fetch_sentiment`) is now `@daily_cached` too (S4): each symbol queries praw at most once per calendar day instead of ~26×/session. VIX is still fetched once per scan (cheap, moves intraday). `TechnicalStats.price` is NOT cached — `technicals._fetch_last_price` makes a separate, uncached `fast_info["lastPrice"]` lookup overlaid as today's bar so the scan-time spot price (N17) stays current; on error it falls back to the last settled close. |
| **Scan spot-snapshot + per-batch sleeps (S3/S7)** | **Optimized (Phase 1).** The async chain fetch no longer issues a dedicated `reqMktData(snapshot=True)` + 2s `quote_sleep_seconds` per symbol when a cached daily close exists: `_resolve_spot_async` centres the strike band on `price_data.get_ohlcv`'s latest close and only falls back to the live snapshot (the `46a21bf` no-tick chain, preserved) for symbols without one. Per-batch quote waits and the fallback spot wait are **event-driven** (`_await_ready`): they return as soon as bid/ask populate (~0.2–0.5s for a healthy batch), bounded by the old fixed wait as a *ceiling*. Greeks are not blocked on (absent on delayed/paper data; the Black-Scholes fallback fills them). Cancel-between-batches line-cap discipline is unchanged. The yfinance greeks double-fetch (S2) is a separate, later phase of `SCAN_EFFICIENCY_PLAN.md`. |
| **Intraday materiality gate (S1/S10)** | **Built (Phase 2).** The 15-min loop calls `run_scan(intraday=True)`, which gates the dominant per-symbol option-chain fetch via `_compute_material_symbols`: it fetches held stock positions, `would_own` names whose live `fast_info` spot drifted ≥ `market_data.intraday_rescan_move_pct` (default 0.5%) from the spot at their last fetch, and names that cleared the score floor last cycle; a `force_full_scan_minutes` timer (default 90) forces a periodic full sweep, and the very first cycle (no baselines) sweeps everything. Immaterial names skip the chain fetch (analytics still run, so the buy-to-own list stays complete); the `fast_info` price fetched by the materiality probe for each `would_own` symbol is also reused as `get_technical_stats`'s `cached_yf_price`, so an immaterial symbol's analytics don't pay for a second identical yfinance quote. The per-symbol baseline (`last_spot`/`last_scanned_at`/`cleared_floor`) lives in the new `scan_state` table (`storage/scan_state.py`), written for every fetched symbol — the first intraday cycle (no baselines) sweeps everything and seeds the gate; fetched chains are persisted via `persist_chain_quotes` (S10, the substrate for the later S6 diff). Manual `/scan` leaves `intraday=False` and always sweeps + sends in full. The store is best-effort: a read/write failure degrades to "treat as material" (full fetch), never a wrong decision. |
| **LLM-skip + output suppression (S5/S6)** | **Built (Phase 4).** Both apply only to `run_scan(intraday=True)` (the 15-min loop); manual `/scan` always reviews fresh and sends in full. **S5:** `_candidates_review_hash` hashes the top candidates' `candidate_id` + signal vectors; when unchanged from the prior cycle (`last_review_hash` system setting) the `claude -p` subprocess is skipped and the persisted `ClaudeReview`s are reused via `_load_prior_reviews`. Enrichment-only — the risk gate already ran, so it never affects gating (the fence; `test_skills_never_reach_the_engine` stays green). **S6:** `send_candidates` collapses a CC/CSP candidate that still has a live, same-score-band PENDING approval into one compact "unchanged" digest (its original card buttons stay actionable), and `send_buy_list` replaces an unchanged buy-to-own screen with a one-line "unchanged since HH:MM" digest — cutting ~26 near-identical card/buy-list blasts/day to one small digest on quiet cycles. Both now return a `bool` (did anything go out?); when an intraday cycle surfaces *nothing* (no candidate clears the gate and the buy list is unchanged/empty) `run_scan` sends a single `format_quiet_cycle` heartbeat (🟰 Quiet cycle · HH:MM ET — "N/M names moved <0.5%, chain re-fetch & Claude skipped") so a deliberately quiet market is distinguishable from a dead daemon. |
| **Scan observability + band cap (S8/S9)** | **Built (Phase 5).** **S9:** when the intraday loop loses a cycle to an overrun (prior scan still running) or scan-lease contention, `_note_intraday_skip` increments a per-session skipped counter and sends a throttled (≤ once/30 min) Telegram warning; successful cycles increment a run counter, and both are shown in `/status` (`format_status` `scans_run`/`scans_skipped`) so intended (~26) vs actual is visible. **S8:** the IV-scaled strike band is now clamped to `[strike_band_pct, strike_band_max_pct]` (default cap 0.40) in `_strike_band_pct`, so an extreme-IV ETF can't generate a runaway qualified-strike/batch count; an explicit per-symbol override is exempt. A config validator rejects a cap below the floor. |
| **Telegram multi-thread routing** | **In progress (`TELEGRAM_ROUTING_PLAN.md`).** Phases 1–6 ✅. Phase 1: five typed per-purpose thread IDs (`telegram_thread_scan/csp/cc/buy/account`, defaults `2/52/54/56/58`) and a shared `thread_id()` helper. Phase 2: `format_screen_unchanged`, `format_screen_empty`, and `format_account_snapshot` formatters. Phase 3: per-thread sender routing — `send_candidates` takes required kwargs `thread_id/label/icon/hash_key/time_key` and enforces the "always send something" rule (empty → `format_screen_empty`; hash-unchanged + all per-card suppressed → screen-level `format_screen_unchanged`; full send stores hash in the provided `hash_key`/`time_key` system settings); `send_buy_list` routes to `telegram_thread_buy` and also sends empty-state diagnostic; `send_account_snapshot` sends/edits-in-place on `telegram_thread_account` (new message each ET day via `account_snapshot_message_id`/`account_snapshot_date`). Phase 4: `seconds_until_time(hh, mm)` helper in `market_hours.py`. Phase 5 (scan split): CC candidates now route to `telegram_thread_cc` (hash key `last_cc_hash`/`last_cc_time`), CSP to `telegram_thread_csp` (`last_csp_hash`/`last_csp_time`); a new `_no_candidates_reason` helper produces per-strategy empty-state diagnostics; `send_account_snapshot` is called best-effort after every cycle (intraday + full sweep); quiet-cycle heartbeat and data-provenance summary both route to `telegram_thread_scan`. Phase 6 (approval-service routing): scan-started ping and overrun warnings now carry `message_thread_id=telegram_thread_scan` (topic 2); startup notification was already routed; `_premarket_snapshot_loop` background task fires at 09:00 ET daily on trading days to send the first account snapshot to topic 58 before market open (subsequent intraday edits come from the scan loop). Phase 7: new system_settings keys (`account_snapshot_message_id`, `account_snapshot_date`, `last_cc_hash`/`last_cc_time`, `last_csp_hash`/`last_csp_time`) documented in `ARCHITECTURE.md`. Phase 8: full doc sweep — topic-routing table in `README.md`, per-thread env-var instructions and troubleshooting rows in `SETUP.md`, formatter/sender entries in `ARCHITECTURE.md`. Phase 9: `send_account_snapshot` mock added to scan integration test stubs (`test_scan_materiality.py`, `test_scan_review_reuse.py`). All 9 phases ✅ complete. |
| **Ledger assignment detection** | **Auto-detected (Phase 4).** The EOD run diffs the prior day's position snapshot (`position_snapshots` table) against current positions: a vanished short whose underlying stock moved ~100×contracts in the assignment direction is flagged `assigned` and fed to `reconcile(assigned_candidate_ids=…)` (`src/claude/eval/assignment.py`). The manual `scripts.reconcile_outcomes --assigned <id>` override still exists for corrections. Two residuals remain: (a) the `assigned` realized P&L is the option-leg premium only — stock-leg P&L is still not modelled in the ledger; (b) covered-call assignment needs a prior snapshot showing the held shares, so it isn't detected on the very first EOD run before any snapshot exists. |
| **Verdict-EV survivorship** | EV (`evaluate_verdicts`) is conditioned on **executed and settled** trades — candidates that were rejected or never filled have no realized counterfactual, so the comparison measures Claude as a filter/ranker over trades that happened, not over the full slate. Every report states this caveat. |
| **Backtesting engine** | **Built (Phase 4); v2 added (N21).** `src/backtest/` simulates CC/CSP income over historical prices. **v1** synthesises premiums with Black-Scholes from trailing 30-day HV (a fair-value IV proxy → expected edge ≈ 0 by construction — it validates plumbing, not the edge). **v2** (`--use-stored-iv`) prices the entry premium from the symbol's stored daily IV (`iv_history`), so the run measures the variance-risk premium (IV−HV, reported as `mean_vrp_pct`); `--profit-take 0.5` simulates the 50% take rule and `--min-iv-rank` gates entries by IV rank, so the strategy hypothesis can be tested with/without gating. Reports premium, net P&L, win/assignment/profit-take rate, return on capital, annualized, buy-&-hold benchmark, and max drawdown via `scripts.backtest`. Still an approximation (no spread/slippage; daily marks for the profit-take walk) and fully isolated from the live broker/risk path. |
| **ML regime detection, vol forecasting, Postgres migration, local-LLM hybrid** | Future ideas, not started. |

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
- **P0-07 Stale spot price from `snapshot=True`:** `_get_spot` and `_get_spot_async` fall back to the snapshot's previous-close tick (`ticker.close`, no extra request) when `marketPrice()` is NaN/0, and only as a last resort to `reqHistoricalData` for the last daily close bar — bounded by `market_data.spot_history_timeout_seconds` (default 10s) instead of ib_async's 60s default, since this path was the dominant cost of `/scan` on weekends/no-subscription sessions (~60s × every symbol).
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
- **F3 Malformed `entry_cutoff` silently killed the intraday loop:** `SchedulerCfg.eod_report`
  and `entry_cutoff` now have a Pydantic `HH:MM` validator (fail loud at config load),
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
  `release_scan_lease`, wrapped around `run_scan`) serialises full scans across processes so concurrent
  `/scan` commands can't compete for the ~100 market-data line cap. The morning cron was removed — the
  15-min daemon loop's first cycle does a full sweep and is sufficient.
- **No DB backup story:** the EOD run now calls `maintenance.backup_database()` — a consistent online
  SQLite snapshot into `data/backups/`, rotated to the last 7. The system of record (orders, fills,
  learning history) is no longer a single point of failure.

## Bugs fixed (2026-06-13 — IMPROVEMENT_PLAN.md v2 Phase 1: signal & approval integrity)

The independent Fable-5 review (`IMPROVEMENT_PLAN.md`, N1–N23) targeted the signal layer and
approval integrity. Phase 1 — the two findings that change *what gets traded* — is fixed:

- **N1 Regime scoring was inverted for short premium:** `technical_score` rewarded selling calls
  into BULLISH regimes and puts into BEARISH — the alignment for *buying* options, backwards for a
  premium seller (weight ~0.20–0.25 of the blend, so it systematically mis-ranked toward the
  riskiest regime/right combinations). **Fixed** in `src/strategies/_scoring.py`: a short put (CSP)
  is favoured in BULLISH (+10) and penalised in BEARISH (−5); a short call (CC) is favoured in
  BEARISH/SIDEWAYS (+10) and penalised in BULLISH (−5). A full (regime × right) matrix test pins
  the direction (`tests/test_strategies.py::test_technical_score_regime_matrix`).
- **N2a Approved order ≠ executed order:** `candidate_id` is a deterministic, date-free hash and
  `_persist_candidates` delete+reinserts the payload every re-scan, so the 15-min loop could change
  `contracts`/`premium` between approval and execution — and `_load_candidate` read the *latest*
  payload, executing a size the human never approved. **Fixed:** `ApprovalRow` and `OrderRow` now
  carry a frozen `snapshot` (the `TradeCandidate` payload at the moment it was shown/approved).
  `_send_with_session` and `_auto_queue_candidates` freeze it; `_process_button` copies the
  approval's snapshot onto the order; `execution/approval.py::_load_candidate` executes the OrderRow
  snapshot (falling back to `CandidateRow` only for legacy rows). The lightweight migration in
  `db.py` adds the two columns to existing DBs.
- **N2b Ledger signal-vector noise:** `record_verdicts` refreshed the verdict-ledger `signals` on
  every re-scan, so the row that eventually received the realized outcome no longer carried the
  signal vector of the scan that produced the fill. **Fixed:** once any `OrderRow` exists for the
  candidate, the pre-outcome fields are frozen (`_candidate_is_committed`), mirroring the N2a
  snapshot freeze. Recorded outcomes were already preserved.
- **N2c `candidate_id` composition:** documented in `make_candidate_id` — the id is deliberately
  **date-free** (the property that lets the 15-min loop dedupe via `has_active_order`); payload
  drift is handled by the N2a snapshot freeze, not by encoding the date. No stale "+date" docstring
  remained in `models.py`.

## Bugs fixed (2026-06-13 — IMPROVEMENT_PLAN.md v2 Phase 2: AI-layer hardening)

- **N3 Unsandboxed `claude -p` subprocess:** the headless CLI ran ~26+×/day with only
  `--output-format json` — no turn cap, no tool restriction, no model pin. The fence isolates
  Claude's *output* from execution, but the subprocess itself had the user's default tool
  permissions. **Fixed:** `runner._build_cmd` now assembles every call site with `--max-turns`,
  `--disallowedTools`, and an optional `--model` pin, all config-driven
  (`claude.max_turns` / `disallowed_tools` / `model` in `settings.yaml`; shipped defaults:
  one turn, a full tool denylist, model pinned to `claude-sonnet-4-6`). The flags don't change
  the JSON envelope, so parsing is unaffected.
- **N9 Unbounded memory injection:** `_load_memory` had no limit, so 30 days × every scan's
  surfaced candidates grew into thousands of history lines per prompt (cost, latency, and an
  echo chamber of Claude's own prose). **Fixed:** `_load_memory` keeps ≤3 rows per symbol
  (outcomes first); `_persist_memory` upserts one `claude_memory` row per (symbol, strategy,
  day) — refreshed with the best-ranked candidate's verdict — instead of one row per candidate
  per 15-min cycle. A recorded outcome is never clobbered.
- **N12 AUTOMATED-mode semantics documented (design decision):** in AUTOMATED mode the system
  trades the **deterministic, gate-passing slate**; Claude's review is enrichment shown for the
  record but does **not** filter, gate, or reorder what executes — a "skip / confidence 0.9"
  verdict changes nothing. This is required by the fence (Claude must never gate an order). To
  raise the AUTO bar, raise `weights.min_candidate_score` (applies to both modes) — never route
  it through Claude's verdict. `_auto_queue_candidates` queues the slate; the execution-time
  Rules-Engine re-gate and circuit breakers remain the only deterministic guards.
- **N17 Hardcoded universe prices would rot:** `strategist._UNIVERSE_CONTEXT` carries Jun-2026
  prices/IV ranks; over months Claude would anchor on wrong levels with high confidence.
  **Fixed:** the static block now opens with a STALE banner (figures are coarse qualitative
  anchors only), and the scan injects a **scan-time spot-price block** (from the technicals
  computed each scan) marked authoritative, so Claude reasons from current levels.

## Bugs fixed (2026-06-13 — IMPROVEMENT_PLAN.md v2 Phase 3: data integrity & risk-engine accuracy)

- **N4 IV history was bootstrap-only:** the only writer to `iv_history` was the one-shot
  `scripts/backfill_iv.py`, so the IV-rank window aged silently — and IV rank is both the largest
  score weight (0.30) and a hard gate (`min_iv_rank`). **Fixed:** a new `src/storage/iv_history.py`
  centralises access; the EOD run appends one IV observation per universe symbol each day
  (`_append_daily_iv`, idempotent on `(symbol, date)`); and `/health` warns (with a new "IV history"
  status line) when any universe symbol's latest observation is older than 5 days or missing.
- **N5 Inconsistent exposure seeding:** `_seed_exposures` counted existing short puts at |option
  market value| (~1% of notional) for per-ticker/sector concentration but at strike×100 for the
  CSP-collateral tally, so a ticker with several working short puts looked nearly unexposed to the
  5%-per-ticker cap. **Fixed:** short puts now contribute strike×100×|contracts| to ticker/sector
  exposure too, matching exactly how a new CSP candidate is charged.
- **N6 ±15% strike band excluded the high-IV tier:** at IV≈100%/30 DTE a 0.25-delta strike sits
  20–30% OTM — outside a fixed ±15% band — so SOXL/LABU/TSLL/MARA/RGTI etc. rarely produced
  candidates. **Fixed:** `_strike_band_pct` scales the band with the symbol's stored IV
  (`max(strike_band_pct, strike_band_iv_mult · IV · √(DTE/365))`), with optional per-symbol
  `universe.yaml → strike_bands` overrides for the extreme-IV leveraged ETFs (so they work before
  their IV history is backfilled). *Live note:* confirm these Tier-3 names actually produce
  candidates on a real paper scan — the band math is unit-tested, but end-to-end chain coverage
  needs a live session.
- **N10 Premium could be priced off a stale `last`:** `OptionQuote.mid` falls back to `last`, so a
  candidate's premium/ROC/yield/score could be computed from a prior-session print when the snapshot
  had no two-sided market. **Fixed:** added `OptionQuote.strict_mid` (no `last` fallback; accepts
  bid=0 with a positive ask) and the CC/CSP generators now price off it. The order builder already
  refused `last` at send time; the strategy layer now matches.

## Bugs fixed (2026-06-13 — IMPROVEMENT_PLAN.md v2 Phase 4: operational robustness)

- **N7 Scan-lease TTL race:** a full ~60-symbol scan can exceed the 600 s lease TTL, so the lease
  could expire mid-scan and let a second scan start — the exact line-cap poisoning the lease
  prevents — and `release_scan_lease` unconditionally zeroed the key, possibly releasing a lease
  another process had since claimed. **Fixed:** the lease value is now `"<expiry>|<owner-token>"`;
  `acquire_scan_lease` returns a stable owner token, the scan loop calls `renew_scan_lease(token)`
  each symbol (heartbeat that extends the TTL), and both `renew` and `release` are compare-and-swap
  on the owner — a scan that overran and was re-claimed can neither renew nor clobber the new holder.
- **N8 A REJECTED order could have a real fill:** if the executor's monitor loop throws (e.g.
  `cancelOrder` on a dropped socket) the except path marks the order REJECTED, but the SELL may
  already have filled at the broker — leaving a live short with no FillRow (invisible to profit-take,
  no entry IV, mislabelled ledger). **Fixed:** `reconcile_orphan_fills` now sweeps REJECTED/CANCELLED
  orders that carry an `ib_order_id` in addition to SUBMITTED ones, so a fill that landed during the
  failure window is recovered. Pre-placement cancels (TTL/re-validation) have no `ib_order_id` and
  are correctly ignored.
- **N11 Chase repriced against a stale quote:** the reprice loop consumed `quote.bid/ask` captured
  before `placeOrder`, so 45–90 s later it chased a stale bid. **Fixed:** each chase step re-fetches
  the live bid/ask (`_refetch_bid_ask`) before computing the next limit. (Repricing remains default
  OFF pending live-paper verification — see the live-verification list.)
- **N14 Profit-take burned a fixed sleep per position:** `_check_profit_takes` slept the full
  `quote_timeout_seconds` for every short position each 15-min cycle. **Fixed:** it now polls for the
  bid/ask in 0.1 s steps and returns as soon as a two-sided market arrives (same pattern as
  `_fetch_quote`), bounded by the same timeout.
- **N13 EOD figure mislabelled "realized P&L":** the EOD figure is daily option premium *cashflow*
  (credits − debits), not a paired realized P&L, yet it flowed into the Telegram summary and Claude's
  narrative under the wrong name. **Fixed:** both boundaries now label it "premium cashflow" with a
  note that assignment stock-leg P&L is excluded; the `JournalRow.realized_pnl` column and
  `EODSummary.realized_pnl` field are retained (with clarifying comments) for back-compat.

## Bugs fixed (2026-06-13 — IMPROVEMENT_PLAN.md v2 Phase 5: validation & strategy evidence)

- **N22 Scoring model was unvalidated:** nothing linked `blended_score` to realized outcomes,
  even though the verdict ledger stores exactly that. **Added** `src/claude/eval/score_metrics.py`
  + `scripts/evaluate_scores.py`: over closed ledger rows, it buckets `blended_score` (and each
  scorecard component) by realized win rate / mean P&L and reports a per-signal Pearson
  correlation. Read-only evidence to re-derive `scoring_weights.yaml` **by hand** — the fence
  forbids any automatic feedback into the engine. (This is the analysis tool; an actual
  weight change still awaits enough closed paper fills.)
- **N21 Backtest couldn't measure the edge:** v1 priced premiums at trailing HV (fair value ⇒
  edge ≈ 0). **Added** a v2 path — `simulate(..., iv_series=…)` prices entries from stored daily
  IV (`iv_history`, via `data.load_iv_series`), so the variance-risk premium is actually measured
  (`mean_vrp_pct`); `params.profit_take_pct` simulates the 50% take and `params.min_iv_rank` gates
  by IV rank. v1 behaviour is unchanged when no `iv_series` is supplied.
- **N20 Roll pipeline not wired:** `generate_roll_candidates` had no production caller and
  `execute_roll` was unreachable. **Wired** end-to-end: `execution/roll_pipeline.py::
  queue_roll_for_approval` (monitor `fire_alerts` → chain fetch → candidate → PENDING approval) →
  Telegram Approve → QUEUED ROLL order → `process_queued_orders` → `execute_roll`. Gated by
  `monitor.roll_execution_enabled` (default OFF) until the BAG sign convention is verified on live
  paper. `validate_candidates` now treats ROLL as exposure-neutral so the queue re-gate doesn't
  double-count the replaced leg.

## Bugs fixed (2026-06-13 — IMPROVEMENT_PLAN.md v2 Phase 6: hygiene / clarity)

- **N15 Silent gaps:** (a) universe symbols missing from `universe.yaml → sectors:` silently
  escaped the per-sector cap — the scan now warns at start, listing the unmapped symbols; (b)
  `market_data.max_concurrent_lines` was read by nothing — a `MarketDataCfg` validator now enforces
  `chain_batch_size ≤ max_concurrent_lines` (fail loud at config load); (c) the unenforced-config-key
  guard test now also covers `settings.yaml` (every leaf key must be referenced in `src/`).
- **N16 Mislabelled signals:** `prob_profit` (which is P(expire OTM) ≈ 1−|delta|, not P(profit))
  renamed to `prob_otm` across the schema, generators, prompt, ledger signal vector, and score
  report; the prompt line now reads "Prob. OTM (≈1−|Δ|)". `_adx_proxy`/`TechnicalStats.trend_strength`
  (ATR/price — a volatility measure, never ADX) renamed to `_atr_ratio`/`atr_ratio`.
- **N18 Drawdown-CC policy (explicit decision):** kept `min_strike_vs_basis: 1.00` — an underwater
  holding generates no covered calls (writing below basis would lock in a loss on assignment).
  Documented in code + `risk_limits.yaml`: lower the knob (e.g. 0.95) to allow below-basis writes.
- **N19 Morning volume gate:** the day-volume liquidity gate is now time-aware — before
  `liquidity.morning_volume_cutoff_et` (default 10:30 ET) it is skipped so a 9:45 scan doesn't reject
  liquid chains whose volume hasn't printed yet (OI + spread still apply). `volume_gate_active()` is
  injectable for deterministic tests.
- **N23 Trading logic in the notify layer:** the profit-take orchestration
  (`check_profit_takes` + `net_entry_credit_per_share` + the auto-close/alert glue) moved from
  `notify/approval_service.py` to `execution/profit_take.py`; the daemon re-exports it and the
  Telegram sends go through the passed bot. The intraday-loop *driver* stays in the daemon (its
  lifecycle), but the trading control flow no longer lives in `notify/`.

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

**Addressed SYSTEM_REVIEW.md findings (see `IMPROVEMENT_PLAN.md`):**
- **F7 (fixed):** `src/execution/reconciliation.py` runs **periodically** from the intraday loop (not
  only at startup). `reconcile_orphan_fills` recovers SELL entry fills missed during a mid-session
  reconnect; `reconcile_external_closes` records a *manual buy-to-close in TWS* as a BUY FillRow
  attributed to the original short's `candidate_id` (idempotent on IBKR `execId`), so the verdict
  ledger labels it `closed_early` rather than `expired_worthless` and EOD cashflow includes the debit.
  (Note: a *system AUTOMATED auto-close* still records its BUY fill under the synthetic `close:`
  candidate id for contract-level idempotency — its EOD cashflow is correct, but its ledger row is not
  re-attributed; this is a narrower, separate item from the manual-close gap F7 raised.)
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
- The **roll combo (BAG) pricing convention** in `order_builder.build_combo_roll_order`: a credit roll
  is sent as a single combo BUYing the bag at a *negative* net-debit limit (`lmtPrice = -net_credit`).
  This sign convention and atomic two-leg fill must be confirmed on a live paper session — fill one
  small roll and verify both legs execute and the net credit lands as expected — before any real-money roll.
- **Limit-order repricing (chase)** in `executor.execute_candidate`: amending a resting order's limit via
  `ib.placeOrder` with the same `orderId` must be confirmed to actually modify (not duplicate) the order
  on a live session, and that an amended order fills at the new price. Enable `execution.reprice_enabled`
  on paper and watch one order step toward the bid and fill before trusting it with real money.
- **`market_data.symbol_timeout_seconds` (per-symbol `/scan` watchdog):** tests cover the timeout firing
  against a mocked hang and the scan continuing to the next symbol. Not yet exercised against a real
  IBKR pacing violation / error 10197 (competing live session) lockout — confirm on paper that a stuck
  symbol is skipped cleanly (no leaked market-data lines) and the next symbol's `reqMktData` calls still
  succeed.
- **Layered IBKR-first greeks (S2):** the per-contract fallback (`lastGreeks`/`askGreeks`/`bidGreeks`) and
  the generic-tick-`106` IBKR IV → Black-Scholes path are unit-tested with mocked tickers, but it is
  **unverified which of these a real paper/delayed account actually populates**. Run one real paper scan
  and read the new `greeks_fallback: Yahoo enriched … in …s` logs to measure how often the Yahoo download
  still fires; if IBKR supplies greeks or IV, the cheaper tiers should short-circuit it. Tick `106` on
  option contracts in particular needs confirmation that it returns a usable IV (it may be ignored for
  options) — if not, the path is a harmless no-op and Yahoo still covers it.

---

## Live cutover gate

Do not flip `LIVE_TRADING=true` until **≥ 10–20 successful paper cycles** have filled and confirmed
back to Telegram. The full checklist is in `SETUP.md` §11. The three-layer guard
(`LIVE_TRADING=true` + live port + per-order `[CONFIRM LIVE]` second tap) and the loud startup banner
must both be verified on the first live run with a single small position.
