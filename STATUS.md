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
>
> **2026-08 remediation (Phases 1–3) is complete in code.** The capital model now sizes and gates in
> risk units, the income gate is a variance-risk-premium floor, loss-side exits and mark-to-market
> kill switches exist, and the MANUAL/AUTOMATED toggle is a four-rung autonomy ladder — defects
> D1–D6 in `docs/superpowers/specs/2026-08-10-remediation-and-ios-app-design.md` §1. **D7 is still
> open:** nothing in the execution path has been exercised against a real broker, and
> `docs/live-validation-2026-08.md` is scaffolded but empty. It needs a human on a live paper
> session, not another code change.

---

## What is built

Every stage of the desk pipeline exists in `src/` and is exercised by `tests/`:

- **Market data** (`src/ibkr/`) — connection manager with backoff + `AutoReconnect`, batched option
  chains within the line limit, live Greeks/IV, historical IV backfill, portfolio/account snapshots.
- **Analytics** (`src/analytics/`) — IV rank/percentile (from `iv_history`). The live IV used for
  IV rank is interpolated to a constant 30-day maturity (`_atm_iv_at_30d`) so it matches the
  constant-maturity `OPTION_IMPLIED_VOLATILITY` series it is ranked against. Also: term structure
  & skew, **VRP** (IV% − HV30%, computed in `iv.py`, displayed on every candidate), **VIX** (fetched from
  yfinance `^VIX` once per scan via `market_conditions.py`, shown in scan completion summary),
  technicals + regime, fundamentals (yfinance), liquidity gates, **composite social + news
  sentiment** (StockTwits self-tags + yfinance news headlines, both keyless, VADER-scored, with
  optional Reddit; see `sentiment.py`),
  Black-Scholes **full Greeks** fallback (`black_scholes.py` — delta/gamma/theta/vega/rho) for quotes missing IBKR model Greeks, plus an **American-option pricer** (`american_option.py`, Cox-Ross-Rubinstein binomial tree) exposing `american_price` and `early_exercise_premium` (Phase 1).
  **C1 (IV/RV richness gate):** `realized_vol.compute_realized_vol` (configurable 20d window) feeds
  `IVStats.iv_rv_ratio` = current_iv / realized_vol; the risk engine gates on `min_iv_rv_ratio` (default
  1.05) and the ratio is displayed on every Telegram approval card. Missing ratio is treated as data
  unavailable and never blocks a scan.
  **C4 (assignment-risk alerts):** `monitor/triggers.py::check_assignment_risk` fires when a short's
  `|delta| ≥ monitor.assignment_alert_delta` (default 0.70) AND `DTE ≤ monitor.assignment_alert_dte`
  (default 21). `intraday.py::fire_alerts` dispatches to the new `format_assignment_alert` formatter
  (Telegram card framing the decision as roll / close / let-assign). Both config keys are tunable in
  `settings.yaml`. Missing delta is treated as data unavailable — never blocks the monitor.
  VIX (and each candidate's VRP) is also injected into the Claude review prompt as a macro-vol
  regime hint — enrichment only, never a deterministic gate. Daily OHLCV (technicals + HV30) is
  served from an **incremental store** (`price_history` via `analytics/price_data.py`): scans read
  settled bars from SQLite and fetch only the missing tail from yfinance, instead of pulling a full
  1y/3mo history per symbol every run. Fundamentals are day-cached (`src/common/cache.py`); the live
  price is fetched fresh each call so it stays current.
- **Data abstraction layer** (`src/data/`) — a thin provider abstraction (Phase 2) between the
  analytics layer and external market-data backends. `protocols.py` defines
  `PriceProvider`/`FundamentalsProvider`/`NewsProvider` interfaces; `factory.py` picks the active
  backend from `config/settings.yaml → data.*` and caches it process-wide; `yfinance_backend.py`
  is the active backend (the existing yfinance calls wrapped in a class — no behaviour change);
  `fmp_backend.py` is a stub raising `NotImplementedError` that documents the swap path. Analytics,
  strategies, and the engine never call `yfinance.*` directly — they go through `src/data/`. A
  future FMP/Polygon swap is a config change, not a rewrite of every analytics module. IBKR is
  *not* a provider — it's the broker + execution path and stays untouched.
- **Strategies** (`src/strategies/`) — covered call, cash-secured put (would-own allowlist), rolling,
  buy-to-own.
- **Decision + safety** (`src/engine/`) — score normalization, weighted ranking, and the
  deterministic, portfolio-aware **Rules Engine**. Cumulative limits resolve through the shared
  `engine/capital.py` helper (`resolve_caps` / `max_contracts` / `seed_budgets`), which both
  `cash_secured_put.screen_csp_candidates` and `risk_engine.validate_candidates` call so the
  generator and the gate can no longer disagree about how big a position may be (D1):
  deployable-cash feasibility, per-ticker and per-sector concentration measured in **risk units**
  (`collateral × IV × √(DTE/365)` — share price is not a risk measure; a stricter raw-collateral
  cap is the fallback when IV is unknown), an explicit **counted large-position slot**
  (`large_position_slot_full`), and total cash-secured-put collateral against the deployable-cash
  CSP budget. Per candidate it gates on the **variance-risk-premium floor** (D2 — the primary
  income gate: `income.require_vrp_edge`, reject when `premium < candidate.ideal.min_credit`,
  reason `premium_below_fair_value`), the ROC/yield **noise** floors (`min_roc_pct: 0.15` /
  `min_annualized_yield_pct: 0.0`, no longer the primary gate), IV rank, IV/RV ratio, DTE window,
  delta (sign and range), contract count, and the earnings blackout — with a second live-quote gate
  at send time.
- **Claude** (`src/claude/`) — headless `claude -p` runner, resilient parser, prompt templates, and a
  persistent learning loop (`claude_memory`, all four outcomes recorded). Local-LLM (Ollama)
  backend (`ollama_runner.py`, `config/settings.yaml → claude.backend`): `"cli"` (`claude -p`
  only), `"ollama"` (local model only), or `"cli_then_ollama"` (try `claude -p`, fall back to
  local on failure). **This deployment currently runs `backend: "ollama"`** — no `claude -p`
  access, so `review_candidates`/`review_roll`/`write_journal_narrative` all go to a local
  `qwen3:8b` via Ollama (`think: false`, `num_ctx: 16384`, `keep_alive: 10m`). Same `ClaudeReview`/`RollReview`
  validation and fail-soft contract regardless of backend. See
  SETUP.md §14. The launcher (`scripts.start`) and `scripts.healthcheck` call
  `ollama_runner.probe_ollama()` (a `GET /api/tags` reachability + configured-model check) on
  startup so a down server or unpulled model surfaces immediately — a WARN, never a hard failure,
  since the fail-soft path keeps the pipeline running deterministically without enrichment. Nothing
  in the system auto-starts Ollama; the Ollama.app (or `ollama serve`) must already be running.
  The only thing that remains `claude -p`-only is the `trading_skills` MCP (ad-hoc tool lookups
  during `claude -p`'s agentic loop) — Ollama's integration is single-shot prompt→JSON with no
  tool-calling loop, so it's inactive in this deployment.
- **Verdict learning loop** (`src/claude/eval/`) — an **outcome ledger**
  (`verdict_ledger`) records, per Claude-reviewed candidate, the signal vector Claude saw + its
  verdict + the deterministic baseline; a **reconciler** back-fills the realized outcome
  (expired / closed-early / assigned / not-filled, P&L) when the trade closes (runs at EOD +
  `scripts.reconcile_outcomes`). **Score-vs-outcome analysis** (`scripts.evaluate_scores`, N22)
  buckets `blended_score` (and each component) by realized win rate / mean P&L, plus a per-signal
  correlation, over closed ledger rows — read-only evidence for whether `scoring_weights.yaml` is
  earning its keep. **The fence:** none of this reaches the risk engine, weights, or sizing, which
  stay human-edited config (enforced by `tests/test_eval_skills.py`).
- **Execution** (`src/execution/`) — mid-price limit-order builder (tick-aware), executor with fill
  monitoring + live second confirmation, approval→execution bridge.
- **Notify** (`src/notify/`) — stateless sender + long-running approval/command daemon (Telegram).
- **Monitor** (`src/monitor/`) — event-driven intraday watch; all six triggers wired end-to-end:
  delta drift, the **mechanical management point** (`check_manage_at_dte`, `monitor.manage_at_dte`,
  default 21 — entries sit at 21–45 DTE and the roll trigger below fires at 7 days, deep into the
  gamma window with little extrinsic left; 21 DTE is the point where closing, rolling, or
  explicitly holding are all still available), the DTE threshold (`dte_threshold`, default 7),
  IV spike, ex-div, and **C4: assignment-risk**.
- **Orchestrators** (`src/orchestrator/`) — EOD report, plus the shared `/scan` pipeline split
  three ways: `scan.py` orchestrates (and stays the `run_scan`/`ScanResult` entry point),
  `scan_pipeline.py` produces the per-symbol data, and `scan_progress.py` owns all presentation —
  both the live progress messages and the end-of-run sends (`send_scan_results`).
  `scan_pipeline.py` imports nothing from `src/notify/` (enforced by a test), so a caller that
  only wants a `ScanResult` never acquires a Telegram dependency. `scan.py` still names three
  senders (`send_candidates`, `send_buy_list`, `send_account_snapshot`) and injects them into
  `send_scan_results` via `SendDeps` — a known, documented limit: the frozen scan tests
  monkeypatch those three as attributes of `src.orchestrator.scan`, so the references cannot move
  without editing them. Live in-chat progress comes from `_Tracker`, which edits **two** messages:
  a stage-by-stage checklist and a dashboard (progress bar + ETA, current-activity line, and a
  🔴-flagged running error log). Per-symbol dashboard edits are throttled to respect Telegram's
  edit-rate limits. VIX is fetched at scan start and shown in the completion message.
- **15-minute intraday loop** — runs inside the approval_service daemon every 15 minutes during
  RTH, **clock-aligned to ET quarter-hour marks** (9:30, 9:45, 10:00, ... via
  `src/common/market_hours.seconds_until_next_aligned_mark`) rather than process-start-relative,
  so cycle times are predictable and consistent across restarts. Each cycle starts by sending a
  short "🔄 Scan started · HH:MM ET" Telegram message (`src/common/market_hours.now_et_hhmm`) so an
  operator can see the schedule is firing on time even before any candidates/heartbeat are sent.
  Each cycle then: (1) checks short option positions for 50% profit-take threshold and
  loss-side exits (`max_loss_multiple` × entry credit), (2) runs a full scan — but new-entry scans
  stop after `scheduler.entry_cutoff` (default 15:00 ET); exit checks (profit + loss) run until
  the close. The whole cycle body is wrapped in a catch-all so
  one bad cycle cannot kill the loop. Behaviour depends on the autonomy rung (see below). RTH is now determined
  by the shared, **holiday-aware** `src/common/market_hours.is_rth` (the single source of truth
  for both the intraday loop and the order-transmission gate) — full-day NYSE holidays and 13:00
  ET early closes are respected, not just weekday + clock.
- **Four-rung autonomy ladder** (`/autonomy` Telegram command, Task 14) — replaces the old binary
  MANUAL/AUTOMATED toggle with `AutonomyLevel` (`OBSERVE < MANUAL < WHITELIST < FULL`), persisted
  in the `system_settings` SQLite table (`autonomy_level`/`autonomy_whitelist` keys) via
  `src/storage/system_settings.py`. The ladder governs **opening** new exposure only —
  `send_candidates` partitions each scan's candidates per-candidate: any candidate
  `may_auto_open(underlying)` clears (WHITELIST's listed symbols; anything at FULL) is queued
  directly for execution (no human tap); everything else gets an Approve/Reject card. At
  **OBSERVE** (the default for a fresh install) no candidate ever auto-opens and the
  Approve/Reject buttons are additionally withheld from every card — that rung proposes only, it
  never acts, not even on a human tap. **MANUAL** requires a tap on every trade, same as the old
  default. Promotion up a rung is refused by `system_settings.promotion_blockers()` until the
  account has demonstrated evidence (>=20 fills, >=60% fill rate, at least one risk-reducing close
  having fired) — autonomy is arrived at, not switched on; demotion is always permitted.
  **Loss-side exits (and profit-takes) are independent of autonomy level:** they fire
  automatically whenever the relevant threshold is reached — 50% premium captured for profit-takes,
  `max_loss_multiple` × entry credit for loss-exits — gated only by `automation.auto_close_enabled`
  (default true), not by the autonomy rung — closing risk should never wait for a human tap. Auto-close
  orders execute via `execution/position_manager.close_short_position` — which records an
  `OrderRow`/`FillRow`, cancels on timeout, and is idempotent at the contract level (SYSTEM_REVIEW
  F1). The deterministic risk gate still re-validates every new-exposure order before execution at
  every rung; buy-to-close (risk-reducing) skips the gate but is still recorded.
- **Automated-trading circuit breakers** (`src/execution/circuit_breakers.py`) — `max_auto_trades_per_day`
  bounds activity; two loss breakers bound *losses* (the risk gate only bounds exposure), and the
  intraday loop halts on whichever trips first (D3). `daily_loss_halt_pct` is enforced by
  `mark_based_loss`, which compares today's summed position `unrealized_pnl` against the prior day's
  snapshot — a genuine mark-to-market measure. It replaced the older `daily_loss_breached`, which
  summed FillRow credits/debits and so read a real drawdown as a *profit* on a day the system sold
  premium (that function and its tests are kept but no longer wired into `process_queued_orders`).
  `drawdown_halt_pct` is enforced by `drawdown_breached`, which trips when net liquidation falls below
  a trailing high-water mark (`system_settings.get_high_water_mark`/`set_high_water_mark`) — catching a
  slow bleed no single day's loss trips. A persisted `/halt` kill switch (auto-engaged on either breach)
  stops all transmission while still allowing profit-take closes. A cross-process scan lease prevents
  concurrent scans from breaching the market-data line cap. Nightly `data/backups/` snapshots protect
  the system of record.
- **Storage** (`src/storage/`) — SQLite + SQLAlchemy, WAL mode, lightweight column migration.
- **Ideal-price zones** (`src/analytics/fair_value.py`) — every contract now carries an `IdealZone`:
  the strike band the technicals + IV imply (expected move, snapped to the symbol's own
  support/resistance, anchored to a 50d/200d SMA, widened for earnings/quality risk, floored at cost
  basis for a CC), the **minimum credit** worth accepting (Black-Scholes fair value at *realised* vol
  plus `min_credit_edge_pct`, never below the ROC/yield gates), and the underlying **action levels**
  (the spot that puts the anchor mid-band, and the nearest actionable `buy_below` share-entry level). Rendered on the
  approval card and the `/scan TICKER` card, and injected into the reasoning prompt so the model
  reconciles the offered contract against a reference instead of judging it in a vacuum. This is the
  first consumer of `TechnicalStats.support_levels`/`resistance_levels`, which were computed on every
  scan and read by nothing. **Two fields, two jobs — do not conflate them.** The strike band and
  action levels are display + optional ranking only (`scoring_weights.yaml → zone_fit` still ships
  at `0.0`, so strike placement changes no ranking until a human raises it), but **`min_credit` is a
  real gate as of D2**: `risk_engine.validate_candidates` rejects a candidate priced below it
  (`income.require_vrp_edge`, reason `premium_below_fair_value`), and the CC/CSP generators run the
  same check so the operator sees the reason on the card. `fair_value.py` itself still never rejects
  anything — it computes numbers and the Rules Engine refuses the order, so the Rules Engine remains
  the sole path to an order. Tunables in `risk_limits.yaml → ideal_zone` / `income`.
- **Hypothetical fair value for off-list / not-held tickers** (`run_ticker_scan`,
  `format_ticker_scan_result`) — `/scan TICKER` used to go silent on fair value whenever a
  strategy never priced a single contract: a CSP on a symbol outside `would_own` (e.g. `SOXL`,
  excluded as a leveraged ETF) short-circuits before the quote loop, and a CC with no shares held
  never runs the generator at all, so neither the near-miss path nor the "🎯 Levels" block had
  anything to show. Both cases now compute a standalone `IdealZone` via
  `fair_value.compute_ideal_zone` straight from `tech_stats`/`iv_stats`/`fund_stats` — no option
  chain required — at the strategy's configured mid-DTE, and render it as "_Informational fair
  value — not a recommendation:_" (`cc_hypothetical`/`csp_hypothetical`, rendered by
  `_hypothetical_zone_lines`). A `not_in_would_own` skip is additionally named on the card so the
  absence of a live CSP recommendation reads as a deliberate policy exclusion, not a gap. Purely
  display — never scored, gated, or fed back into the allowlist. **Escaping bug fixed same day
  (2026-08-14):** the "Ideal strike ... at ~Nd" line emitted a bare, unescaped `~` — MarkdownV2
  reads a lone `~` as an unpaired strikethrough delimiter and Telegram rejects the whole message
  with `BadRequest`, which `_ticker_edit_msg` swallows into a warning log — so `/scan TICKER`
  silently froze on its "Scanning…" placeholder for every off-`would_own` or not-held symbol
  (any leveraged ETF, or anything not currently owned). Now escaped (`\\~`); covered by
  `test_hypothetical_zone_has_no_unescaped_markdownv2_chars` in `test_ticker_scan_format.py` —
  the pre-existing `test_card_has_no_unescaped_markdownv2_parens` regression check existed but
  was never exercised against this code path. Along the way, `_near_miss_lines`
  was also fixed to render `_ideal_lines` for a real near-miss candidate: previously a contract
  rejected with `premium_below_fair_value` never showed what fair value actually was.
- **Every scan returns assessed candidates** — the strategy generators (`screen_cc_candidates` /
  `screen_csp_candidates`) now return the contracts they *rejected* alongside the ones they passed,
  each tagged with **every** gate it failed rather than just the first, ranked closest-to-passing.
  `decision_engine.select_top_candidates_detailed` reports dedupe/top-N losers that previously
  vanished. `ScanResult.assessed` collects all of it as `AssessedContract`s stamped with the stage
  they stopped at. Manual `/scan` and full sweeps render the full "🔎 Assessed — not approved" block
  (`format_assessed_contracts`); `/scan TICKER` renders it as "Other contracts considered". The
  15-min intraday loop is unchanged — it keeps the compact one-line near-miss digest, so this does
  not reintroduce the message flood S6 removed. **Closes the largest gap:** generator-stage
  rejections were the numerically dominant reason a scan surfaced nothing (e.g. `delta_range=74` on
  a 122-quote chain) and left no trace beyond one aggregate log line, so a symbol whose whole chain
  failed produced no candidate, no near-miss, and no explanation.
- **Assessment audit trail** (`src/storage/risk_verdicts.py`) — the long-dormant `risk_verdicts`
  table is now written: one row per assessed contract per run, with stage, reasons, and a
  denormalized ideal zone, pruned to 14 days at EOD. Write-only forensics; nothing reads it back.
- **Macro backdrop** (`src/analytics/market_conditions.py`) — extended beyond the single VIX number
  to the **VIX term ratio** (`^VIX/^VIX3M`; above 1 = backwardation), the **10-year yield** and its
  5-session change in bp, the **SPY 5-session return**, and **broad-market headline tone** (VADER over
  SPY/QQQ headlines, reusing `sentiment._fetch_news`). All keyless, day-cached except VIX/VIX3M, and
  independently fail-soft. Rendered on the `/scan TICKER` card and injected into the single-ticker
  prompt as a `MACRO BACKDROP` block. Enrichment only (asserted by
  `tests/test_eval_skills.py::test_macro_never_reaches_the_engine`).
- **Skipped-symbol transparency** (`src/notify/formatters.format_skip_reasons`) — full scans append a per-symbol breakdown of why each universe name produced no approved candidate (delta, DTE, IV rank, score floor, etc.) to the scan thread. Sent once per full sweep (not per intraday cycle).
- **P&L calendar** (`/calendar` command) — per-day realized cashflow view for the last 30 days, derived from `FillRow` records (SELL = credit, BUY = debit), with fill count and running total.
- **Richer order notification cards** (`format_order_notification`) — `action` parameter distinguishes BUY (close) vs SELL (open); fills display "Opened" / "Closed" wording with emoji; placed orders show "Close Order Placed" header for buy-to-close entries.
- **Dashboard** — read-only Streamlit views archived to `Archive/dashboard/` (optional `[dashboard]` extra; restore folder to `dashboard/` to reinstate).

---

## Tech stack

| Layer | Choice | Notes |
|---|---|---|
| Broker / data | **`ib_async`** | Maintained successor to `ib_insync`. Real-time + historical. Import as `from ib_async import ...` — never add the legacy `ib_insync`. |
| Numerics | `pandas`, `numpy`, `scipy` | Scoring and stats. Black-Scholes full Greeks (delta/gamma/theta/vega/rho) via `scipy.stats.norm` (`src/analytics/black_scholes.py`); American-option pricer via a Cox-Ross-Rubinstein binomial tree (`src/analytics/american_option.py`, Phase 1). |
| Fundamentals | `yfinance` | FCF, debt, earnings/ex-div dates (supplemental only). |
| Schemas | `pydantic` v2 | Typed contracts between modules (`src/common/schemas.py`). |
| Storage | **SQLite + SQLAlchemy** | Postgres is a config change away; not migrated. |
| Scheduling | **`scripts.start`** spawns the EOD one-shot at the configured ET time (last-run persisted to `data/eod_scheduler_state.json`); `asyncio` for the daemons | The launcher is a plain process supervisor with no `ib_async` loop and runs the EOD job as a subprocess — so the "never run a threaded scheduler in the same process as an `ib_async` loop" invariant holds. No cron job required. |
| Approval / notify | `python-telegram-bot` v21+ | Inline keyboards + callback handlers. |
| Claude | **Claude Code CLI (`claude -p`)** | Headless. Since 2026-06-15, draws from a separate monthly Agent SDK credit pool (billed at API rates), not the interactive subscription. **Not used in this deployment** — `claude.backend: "ollama"` (no CLI access); review dispatches to Ollama instead. |
| Claude tools | `trading_skills` MCP via `.mcp.json` (opt-in) | Ad-hoc lookups during roll reasoning. clientId 20. Requires `claude -p`; inactive in this deployment. |
| Local LLM (**active**) | **Ollama** (`httpx` → `localhost:11434`), model `qwen3:8b` | `claude.backend: "ollama"` — sole backend for `review_candidates`/`review_roll`/`write_journal_narrative` in this deployment (`think: false`, `num_ctx: 16384`, `keep_alive: 10m`). See SETUP.md §14. |
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
| **Black-Scholes Greeks fallback** | **Built, then layered IBKR-first (S2, Phase 3); full Greeks added (Phase 1).** Greeks are resolved in three tiers: (1) `_ticker_to_quote` reads the first available IBKR per-contract computation (`modelGreeks` → `lastGreeks` → `askGreeks` → `bidGreeks` via `_pick_greeks`) so a lagging model tick still yields genuine IBKR greeks (`greeks_source="ibkr"`); (2) `_enrich_greeks_from_ibkr_iv` BS-fills delta locally from an IBKR IV with no network call — Phase 1 extended this to fill **gamma/theta/vega** alongside delta (skipping only when all four greeks are already present); (3) only quotes IBKR could value neither greeks nor IV for fall through to the yfinance Black-Scholes download (`_enrich_greeks_yf`), now **instrumented** (logs how many quotes forced a Yahoo fetch + the elapsed time per symbol) and also filling gamma/theta/vega. Tiers 2/3 set `greeks_source="black_scholes"` so the F6 live gate still treats them as untrusted. The scan batch requests generic ticks `101,106` to capture the IBKR IV. **Phase 1 also added** `src/analytics/american_option.py` (Cox-Ross-Rubinstein binomial-tree American pricer + `early_exercise_premium`) and `bs_gamma`/`bs_theta`/`bs_vega`/`bs_rho` to `black_scholes.py` — the foundation for economic (non-heuristic) assignment triggers. |
| **Multi-leg / roll execution** | **Built (Phase 4).** A `Strategy.ROLL` candidate is executed as one atomic BAG combo — BUY-to-close the old short + SELL-to-open the new short, no legging risk — via `src/execution/roll_executor.py::execute_roll` (`executor.execute_candidate` delegates instead of refusing). `order_builder.build_combo_roll_order` builds the BAG + net LimitOrder (credit → negative net-debit limit). Re-gates the new leg (`validate_live_quote` delta/live-greeks) + a net-credit floor, LIVE-mode [CONFIRM LIVE] tap, cancel-on-timeout, and writes two FillRows (BUY under the original short's id → ledger `closed_early`; SELL under the new id → monitor tracks it). **Combo limit-price sign convention is mock-tested only — verify on live paper first** (see below). **Wired end-to-end (N20):** when `monitor.roll_execution_enabled` is set, a roll trigger generates a candidate (`execution.roll_pipeline.queue_roll_for_approval`) and sends it with Approve/Reject buttons → QUEUED ROLL order → `execute_roll`. Default OFF until the BAG sign is verified on live paper (D7 — Q3 of `docs/live-validation-2026-08.md`, not yet run); until then rolls remain alert-only. **Defensive rolls are now judged on risk, not yield (D4, Task 12):** `roll_pipeline.queue_roll_for_approval` passes `defensive=True`, which skips the ROC/annualized-yield tests and instead requires a `monitor.roll_defensive.min_delta_reduction` cut in \|delta\| within a bounded `max_debit`. |
| **Live limit-order repricing** | **Built (Phase 4 + C5), default OFF.** `order_builder.reprice_limit` + chase loops in all three execution paths: (1) entry SELL in `executor.execute_candidate` steps toward the bid (floor: `min_live_premium_ratio × approved premium`); (2) buy-to-close BUY in `position_manager.close_short_position` steps toward the ask; (3) roll BAG combo in `roll_executor.execute_roll` re-fetches per-leg bid/ask, recomputes the live net credit, and steps the BAG net-limit toward market (ceiling: `min_live_premium_ratio × approved credit`). All three gated by `execution.reprice_enabled` (false by default) — the `placeOrder` amend is unverified on a live account (D7 — Q2 of `docs/live-validation-2026-08.md`, not yet run); see the live-verification list below. |
| **Unreachable quiet-cycle heartbeat (removed)** | `format_quiet_cycle` / `_send_quiet_heartbeat` could never fire in production: `send_candidates` and `send_buy_list` both return `True` on their *empty* path, so `if not cand_sent and not buy_sent` was never true. Only the mocked tests (which stubbed the return to `False`) ever exercised it. Rather than resurrect it — which would mean two messages per quiet cycle, exactly the flood S6 removed — the heartbeat, `ScanResult.quiet_cycle`, and the likewise orphaned `format_screen_empty` were deleted, and the materiality detail it carried ("N/M names moved <0.5%") now rides on the empty-screen diagnostic that is actually appended. |
| **`BuyCandidate.rationale`** | A deterministic one-liner built from the screen's own signals (IV richness, VRP, regime, quality, earnings proximity) in `buy_candidates.py` — Claude does **not** review buy-to-own names (only option candidates), by design. The buy-to-own screen applies a score floor + count cap (`scoring_weights.yaml → buy_to_own`, currently 10 names max). The Telegram message (`format_buy_list`) groups candidates by sector (indexes, tech, semis, financials, healthcare, …); all candidate cards are shown inline — the Telegram spoiler wrapping that previously hid each sector behind a "tap to reveal" toggle has been removed. Sectors are sourced from `universe.yaml → sectors` via the `BuyCandidate.sector` field. |
| **yfinance caching** | **Built, then upgraded to an incremental store.** Daily OHLCV (the 1y history for RSI/MACD/SMAs/ATR/support-resistance/regime **and** HV30) is persisted in the `price_history` table and loaded by `analytics/price_data.get_ohlcv`, which fetches **only the missing tail** from yfinance (or a full year when the store is empty) and is itself `@daily_cached` per calendar day in-process. So scans no longer pull full per-symbol histories every run — steady state makes zero yfinance history calls (the store is current); the 15-min loop reuses the day cache; and a cold process reads settled bars from SQLite instead of re-downloading a year. Seeded by `scripts/backfill_prices.py`, kept fresh by the EOD daily-bar append (mirrors the `iv_history` N4 pattern). `get_fundamental_stats` remains `@daily_cached`. Composite sentiment sources (`sentiment._fetch_stocktwits`, `_fetch_news`, `fetch_sentiment`) are each `@daily_cached` too (S4): each API is hit at most once per calendar day per symbol instead of ~26×/session. VIX is still fetched once per scan (cheap, moves intraday). `TechnicalStats.price` is NOT cached — `technicals._fetch_last_price` makes a separate, uncached `fast_info["lastPrice"]` lookup overlaid as today's bar so the scan-time spot price (N17) stays current; on error it falls back to the last settled close. |
| **Scan spot-snapshot + per-batch sleeps (S3/S7)** | **Optimized (Phase 1); OI-wait bug fixed 2026-08-14.** The async chain fetch no longer issues a dedicated `reqMktData(snapshot=True)` + 2s `quote_sleep_seconds` per symbol when a cached daily close exists: `_resolve_spot_async` centres the strike band on `price_data.get_ohlcv`'s latest close and only falls back to the live snapshot (the `46a21bf` no-tick chain, preserved) for symbols without one. Per-batch quote waits and the fallback spot wait are **event-driven** (`_await_ready`), bounded by the old fixed wait as a *ceiling*. **`_quote_ready` originally only waited for bid/ask** — since the batch also requests generic tick `101` (open interest), which typically streams in *after* bid/ask, this let a batch cancel its line before OI ever arrived, leaving `open_interest` `None` on most quotes; `passes_liquidity_gates` treats a missing OI as an automatic fail, so this was silently rejecting ~97% of quotes as "illiquid" universe-wide (even AAPL/SPY/META) — see the 2026-08-14 session investigation. Fixed: `_quote_ready(ticker, right=...)` now also waits for that side's OI tick, still bounded by the same ceiling — a well-behaved batch still returns early once both bid/ask and OI arrive, otherwise it uses the full ceiling instead of racing ahead at ~0.2–0.5s. Greeks are still not blocked on (absent on delayed/paper data; the Black-Scholes fallback fills them). Cancel-between-batches line-cap discipline is unchanged. The yfinance greeks double-fetch (S2) is a separate, later phase of `SCAN_EFFICIENCY_PLAN.md`. |
| **Intraday materiality gate (S1/S10)** | **Built (Phase 2).** The 15-min loop calls `run_scan(intraday=True)`, which gates the dominant per-symbol option-chain fetch via `_compute_material_symbols`: it fetches held stock positions, `would_own` names whose live `fast_info` spot drifted ≥ `market_data.intraday_rescan_move_pct` (default 0.5%) from the spot at their last fetch, and names that cleared the score floor last cycle; a `force_full_scan_minutes` timer (default 90) forces a periodic full sweep, and the very first cycle (no baselines) sweeps everything. Immaterial names skip the chain fetch (analytics still run, so the buy-to-own list stays complete); the `fast_info` price fetched by the materiality probe for each `would_own` symbol is also reused as `get_technical_stats`'s `cached_yf_price`, so an immaterial symbol's analytics don't pay for a second identical yfinance quote. The per-symbol baseline (`last_spot`/`last_scanned_at`/`cleared_floor`) lives in the new `scan_state` table (`storage/scan_state.py`), written for every fetched symbol — the first intraday cycle (no baselines) sweeps everything and seeds the gate. Manual `/scan` leaves `intraday=False` and always sweeps + sends in full. The store is best-effort: a read/write failure degrades to "treat as material" (full fetch), never a wrong decision. |
| **LLM-skip + output suppression (S5/S6)** | **Built (Phase 4).** Both apply only to `run_scan(intraday=True)` (the 15-min loop); manual `/scan` always reviews fresh and sends in full. **S5:** `_candidates_review_hash` hashes the top candidates' `candidate_id` + signal vectors; when unchanged from the prior cycle (`last_review_hash` system setting) the `claude -p` subprocess is skipped and the persisted `ClaudeReview`s are reused via `_load_prior_reviews`. Enrichment-only — the risk gate already ran, so it never affects gating (the fence; `test_skills_never_reach_the_engine` stays green). **S6:** `send_candidates` collapses a CC/CSP candidate that still has a live, same-score-band PENDING approval into one compact "unchanged" digest (its original card buttons stay actionable), and `send_buy_list` replaces an unchanged buy-to-own screen with a one-line "unchanged since HH:MM" digest — cutting ~26 near-identical card/buy-list blasts/day to one small digest on quiet cycles. An intraday cycle that surfaces *nothing* is still not silent: `send_candidates` appends a timestamped `[HH:MM] … no candidates this cycle <reason>` line plus the closest near-miss to the thread's persisted status message, and the reason now carries the materiality clause ("N/M names moved <0.5% (chain re-fetch skipped)"). A separate `format_quiet_cycle` heartbeat existed for this but could never fire — both send functions return `True` on their empty path — and has been removed rather than resurrected (see "Unreachable quiet-cycle heartbeat" above). |
| **Scan observability + band cap (S8/S9)** | **Built (Phase 5).** **S9:** when the intraday loop loses a cycle to an overrun (prior scan still running) or scan-lease contention, `_note_intraday_skip` increments a per-session skipped counter and sends a throttled (≤ once/30 min) Telegram warning; successful cycles increment a run counter, and both are shown in `/status` (`format_status` `scans_run`/`scans_skipped`) so intended (~26) vs actual is visible. **S8:** the IV-scaled strike band is now clamped to `[strike_band_pct, strike_band_max_pct]` (default cap 0.40) in `_strike_band_pct`, so an extreme-IV ETF can't generate a runaway qualified-strike/batch count; an explicit per-symbol override is exempt. A config validator rejects a cap below the floor. |
| **Telegram multi-thread routing** | **Complete. Phases 1–11 ✅.** Phases 1–9 (thread IDs, formatters, per-thread routing, LLM-skip integration, S6 suppression, premarket snapshot, system_settings keys, doc sweep, test stubs) are complete as previously documented. **Phase 10 (accumulated status messages):** "no candidates" and "unchanged" quiet cycles now *append* a `[HH:MM] …` timestamped line to a single persisted Telegram message (edited in-place via `_append_status`) instead of replacing it — so 4 quiet cycles in a row build a tidy timestamped log in one message rather than 4 separate messages. Body text is stored alongside the message-id in a `{key}_body` system_settings key; when the body exceeds 3800 chars the slate is wiped. A real candidate/buy-list send clears both keys so the next quiet cycle starts a fresh message. The old `_edit_or_send` is replaced by `_append_status`. **Phase 11 (order notifications to topic 58):** `send_order_notification` in `sender.py` and `format_order_notification` in `formatters.py` send/edit plain-text order-status messages to `telegram_thread_account` (topic 58); each order gets one persistent message keyed by `order_notification_{order_id}_msg_id`. `executor.py` calls it on order placed, filled, live re-gate failure, IB rejection, and timeout; `approval.py` calls it for TTL-expiry, re-validation failure, and daily-trade-cap cancellations. The intraday scan loop calls `_update_pending_order_notifications` after each scan to push live underlying-price and option-mid updates to every SUBMITTED order's thread-58 message. |
| **Ledger assignment detection** | **Auto-detected (Phase 4).** The EOD run diffs the prior day's position snapshot (`position_snapshots` table) against current positions: a vanished short whose underlying stock moved ~100×contracts in the assignment direction is flagged `assigned` and fed to `reconcile(assigned_candidate_ids=…)` (`src/claude/eval/assignment.py`). The manual `scripts.reconcile_outcomes --assigned <id>` override still exists for corrections. Two residuals remain: (a) the `assigned` realized P&L is the option-leg premium only — stock-leg P&L is still not modelled in the ledger; (b) covered-call assignment needs a prior snapshot showing the held shares, so it isn't detected on the very first EOD run before any snapshot exists. |
| **Backtesting engine** | **Built (Phase 4); v2 added (N21); C10/C11 added (Competitive Phase 5).** `src/backtest/` simulates CC/CSP income over historical prices. **v1** synthesises premiums with Black-Scholes from trailing 30-day HV (a fair-value IV proxy → expected edge ≈ 0 by construction — it validates plumbing, not the edge). **v2** (`--use-stored-iv`) prices the entry premium from the symbol's stored daily IV (`iv_history`), so the run measures the variance-risk premium (IV−HV, reported as `mean_vrp_pct`); `--profit-take 0.5` simulates the 50% take rule and `--min-iv-rank` gates entries by IV rank, so the strategy hypothesis can be tested with/without gating. Reports premium, net P&L, win/assignment/profit-take rate, return on capital, annualized, buy-&-hold benchmark, and max drawdown via `scripts.backtest`. **C10** `src/backtest/earnings.py` adds earnings-cycle segmentation: `simulate_earnings_cycles` segments the price series by historical earnings dates (loaded via `data.load_earnings_dates` from yfinance), evaluates the strategy across each inter-earnings window (gating when the window is too narrow for the DTE), and optionally adds a vol-crush follow-on entry right after earnings. **C11** `scripts/backtest_candidate.py` adds an on-demand per-candidate CLI: `--compact` outputs a 4-line summary suitable for Claude injection; `--earnings` enables the earnings-cycle mode. **Phase 6** extracted the reusable core into `src/backtest/on_demand.py` (`params_from_candidate`, `run_backtest`, `summarize`, `backtest_candidate`) — the CLI is now a thin wrapper, and the **Claude-invocable action** is delivered: `strategist.build_prompt` injects a per-candidate backtest line when `claude.backtest_in_prompt` is enabled (default OFF). `report.compact_report` and `report.format_earnings_cycle_report` are the matching renderers. All still an approximation (no spread/slippage; daily marks for the profit-take walk) and fully isolated from the live broker/risk path (the fence — `on_demand.py` is never imported by `engine/`, `execution/`, or sizing). |
| **Campaign chaining (C6)** | **Built (Competitive Phase 4); cost-basis wired live in Phase 6.** `src/storage/campaigns.py` links each CSP→assignment→CC→roll→close sequence for a symbol into one P&L thread (`CampaignRow`). The executor calls `attach_fill_to_campaign` after every fill, which opens a campaign on the first SELL, appends subsequent fills as legs, and auto-closes when buy quantity equals sell quantity (unless assigned). `mark_campaign_assigned(symbol, assignment_price, right)` sets `assigned=True` and computes `adjusted_cost_basis = assignment_price − net_premium/100` per share for share-acquiring (put) assignments. **Phase 6 closed a gap:** `mark_campaign_assigned` was previously only called in tests, so adjusted cost basis was never populated in production — the EOD reconciler now calls it for each detected assignment (`eval/assignment.assigned_shorts` surfaces the strike). `adjusted_cost_basis` now also feeds the covered-call gate directly (D5, remediation Task 6): `strategies/covered_call.py` reads it via `campaigns.adjusted_cost_basis_for(symbol)` and uses it — falling back to IBKR's raw `avg_cost` when no open assigned campaign exists — for the `min_strike_vs_basis` comparison, collateral, ROC, breakeven, and the ideal-zone cost basis, so the wheel's already-collected premium affects which strikes are writable rather than being visible only on the `/campaigns` and `/campaigns open` Telegram commands, which still display the wheel P&L thread for each symbol. |
| **ML regime detection, vol forecasting, Postgres migration, local-LLM hybrid** | Future ideas, not started. The FMP/Polygon provider swap is now a config change (Phase 2's `src/data/` abstraction), so the data-backend half of any future migration is a `config/settings.yaml → data.*` edit plus a new backend implementing the Protocols — not a rewrite of every analytics module. |

---

## Removed 2026-08-10

Task 16 of the Phase 1–3 remediation plan
(`docs/superpowers/plans/2026-08-10-remediation-phases-1-3.md`) deleted four subsystems that had
accumulated but were not earning their keep. Each is gone from `src/`, `scripts/`, `config/`, and
the test suite — nothing in this list is "not built," it was built, used briefly or never, and
removed.

| Removed | Why |
|---|---|
| **Skill-proposal loop** (`src/claude/skills/`, `src/claude/eval/metrics.py`, `scripts/propose_skill.py`, `scripts/skills.py`, `scripts/evaluate_verdicts.py`, `config/skills/`, `ClaudeCfg.skills_enabled`) | Verdict scoring (calibration + EV vs the deterministic baseline) measured the calibration of a model whose verdict is deliberately inert in auto mode — the Rules Engine gates and sizes every trade; Claude only enriches — and needed years of closed trades to produce a meaningful held-out score. The skill loop that drafted reasoning playbooks from that scoring was accordingly unfounded. The **outcome ledger** and **close reconciler** (`src/claude/eval/ledger.py`, `reconcile.py`) are kept — they are cheap, and **score-vs-outcome analysis** (`score_metrics.py`, N22) still reads them to check whether `scoring_weights.yaml` is earning its keep. |
| **Named trading profiles** (`src/common/profile.py`, `config/profiles/`, the `/profile` Telegram command, `get_effective_risk()`/`get_effective_weights()`) | Four parameter overlays (`default`/`conservative`/`balanced`/`aggressive`) on a system that has not validated even one parameter set live. Every call site now reads `get_config().risk`/`get_config().weights` directly — mechanically identical to the `default` profile's behavior, since a profile was always just a deep-merge overlay on the same base config. |
| **`option_quotes` table** (`OptionQuoteRow`, `persist_chain_quotes`, `purge_old_option_quotes`) | Write-only: one row per symbol per scan, with a pruning job and zero readers. The S1/S10 intraday-materiality gate this was once thought to feed is served entirely by the separate `scan_state` table. |
| **`annualized_roc` scoring weight** (`ScoreCard.annualized_roc_score`, `strategies/_scoring.annualized_roc_score()`, the `annualized_roc` key in `scoring_weights.yaml`) | Shipped at `0.0` (off) since introduction and never raised — superseded by the VRP floor (D2, `income.require_vrp_edge`), which gates on the same "is this premium worth selling" question where the risk engine already checks it, rather than as an optional ranking dimension nobody enabled. |

Behavior is unchanged for every account currently running the `default` profile (i.e. all of
them) — this cleanup removes dead code paths, not live functionality.

---

## Bugs fixed (2026-08-13 — intraday scan loop: scheduling and notification gaps)

- **Every 🛑 *Scan blocked* Telegram message since the 2026-06-24 fix (above) failed to send,
  swallowed by its own `except Exception` — the operator only ever saw the terser, throttled
  "cycle skipped" nuisance warning, never the detailed explanation.** `_notify_scan_blocked`
  interpolates its `reason` argument straight into a `parse_mode="MarkdownV2"` message
  (`f"*{reason}*\n{detail}\n\n..."`) without escaping it, but both real call sites in
  `_intraday_scan_loop` pass a plain-English reason containing literal parentheses —
  `"IBKR data farm not responding (half-dead socket)"` and `"IBKR data farm stopped responding
  mid-scan (half-dead socket)"`. Telegram's MarkdownV2 parser rejects unescaped `(`/`)` with
  `telegram.error.BadRequest: Can't parse entities: character '(' is reserved and must be escaped
  with the preceding '\'`, so `bot.send_message` raised on every call, was caught, and logged only
  as `Intraday loop: failed to send scan-blocked notice` — never surfaced to Telegram. Observed
  2026-08-13 00:00 ET: the SPY health probe correctly detected the half-dead socket and forced a
  reconnect, but the operator's only notification was `⚠️ Intraday scan cycle skipped:
  data-farm health probe failed (half-dead socket)...`, with no mention of *why* or that a
  reconnect was already in flight. The existing regression tests
  (`test_notify_scan_blocked_always_sends_with_detail`) used a mocked `bot.send_message` that
  doesn't validate MarkdownV2 syntax, so the bug shipped silently for seven weeks. **Fixed:**
  `_notify_scan_blocked` now escapes `reason` with the file's existing `_md_escape` helper (already
  used for `/scan TICKER` error text and the `/status` halt banner) before interpolating it.
  `detail` was already hand-escaped at both call sites and is unaffected.
  - Regression test: `tests/test_notify.py::test_notify_scan_blocked_escapes_reason_for_markdownv2`
    — asserts the real `"(half-dead socket)"` reason text is escaped in the outgoing text, not
    merely that `send_message` was called.

- **A manual `/scan` truncated mid-run by the half-dead-socket circuit breaker (`aborted_unhealthy`)
  looked identical to a normal, complete sweep — the operator had no way to tell, short of reading
  logs, that only part of the universe was actually fetched.** Unlike `_intraday_scan_loop`, which
  reads `ScanResult.aborted_unhealthy` and tells the operator (the fix above), `handle_scan_command`
  only ever checked `result.lease_skipped` — `run_scan` still sends whatever candidates it found
  regardless of how the run ended, so an early circuit-breaker abort produced a normal-looking
  results screen with no indication anything was cut short. Observed 2026-08-13 00:31–00:59 ET: a
  manual `/scan` hit three consecutive full `symbol_timeout_seconds` (150s) timeouts on SPY, TLT,
  and TSLA with zero IBKR response (no error code logged, unlike the Error-10197
  competing-live-session blocks earlier that session) — the circuit breaker correctly aborted after
  processing 35/46 symbols, but the operator only saw an ordinary "0 CC / 0 CSP / 10 buy candidates"
  result. **Fixed:** `_notify_manual_scan_outcome` (mirrors `_notify_scan_blocked`) now edits the
  `/scan` progress message on `aborted_unhealthy` with the processed/total symbol count and forces
  the same reconnect (`_force_scan_reconnect`) the intraday loop uses; the existing `lease_skipped`
  edit was folded into the same helper.
  - `src/notify/approval_service.py`: new `_notify_manual_scan_outcome`, called from
    `handle_scan_command`'s `_run_and_notify` in place of the old inline `lease_skipped` check.
  - Regression tests: `tests/test_notify.py::test_notify_manual_scan_outcome_*` (normal completion
    is a no-op, lease-skip still edits the message, an aborted run reports the partial count and
    reconnects, and a Telegram send failure doesn't block the reconnect).

- **A legitimately slow full sweep (not a dead socket) silently starved every later 15-min cycle —
  no log line, no skip notice, nothing.** `_intraday_scan_loop` `await`ed `run_scan(...)` directly
  inline, so it could not return to `while True`'s top to check the *next* aligned mark until the
  current scan finished. This is distinct from the 2026-06-24 half-dead-socket stall (above): that
  one only happens when the connection is actually dead, and the circuit breaker bails after 3
  consecutive timeouts specifically so this can't happen. A *healthy* connection fetching real data
  slowly trips no circuit breaker and previously blocked just the same. Observed 2026-08-13
  01:15–01:34+ ET: right after a service restart, no symbol had a `scan_state` baseline yet, so the
  S1 materiality gate saw the entire 46-symbol universe as material (`intraday materiality gate —
  46/46 symbols material`) instead of the usual filtered subset; several large chains (SMH, SNOW,
  RGTI, RKLB, TLT, TSLA, UBER) each took 50–60s fetching real quotes (Yahoo Greeks-fallback
  downloads), and the cumulative sweep was still processing symbol 39/46 at `01:34` — the `01:30`
  ET-13:30 cycle was never even attempted; no `RTH cycle starting` log line exists for it. **Fixed:**
  the scan is now spawned as its own task (`asyncio.create_task`) from a new `_run_intraday_scan`
  helper instead of being awaited inline, guarded by the same `bot_data["scan_running"]` lease
  manual `/scan` already uses (so the two still can't run concurrently) — the loop itself keeps
  running its per-mark checks (profit-takes, loss-exits, reconciliation, the health probe)
  synchronously and quickly every 15 minutes regardless of how long a previously-spawned scan is
  still taking; a still-running scan now correctly logs/notifies "previous scan still running" on
  the next mark instead of vanishing.
  - `src/notify/approval_service.py`: new `_run_intraday_scan` (extracted from the old inline block
    — `run_scan` call, `lease_skipped`/`aborted_unhealthy`/success handling, and the post-scan
    pending-order-notification update); `_intraday_scan_loop` now sets the lease and calls
    `asyncio.create_task(_run_intraday_scan(...))` instead of awaiting the equivalent block inline.
  - Regression tests: `tests/test_notify.py::test_run_intraday_scan_*` (the extracted helper's
    success/exception paths) and
    `test_intraday_loop_reaches_next_aligned_mark_while_scan_still_running` — drives the real loop
    with a `run_scan` that blocks on an `asyncio.Event` and asserts the profit-take check fires
    again on a later mark while that scan is still in flight (fails against the old inline-`await`
    code, which never reaches a second mark until the fake scan is released).

---

## Bugs fixed (2026-08-12 — final whole-branch review of the remediation branch)

The last pass over `remediation-phases-1-3` before merge, reviewing the branch as a whole rather
than task by task. Five defects and one dead constant; the first is a regression the branch itself
introduced.

- **Existing positions counted as ZERO against the risk-unit concentration caps.** D1 replaced the
  raw-collateral concentration cap with risk units (`collateral x IV x sqrt(DTE/365)`), but
  `capital.seed_budgets` only ever filled `ticker_collateral`: `ticker_risk` was never populated at
  all and `sector_risk` was only `setdefault`-ed to `0.0`. Both `capital._fits` and
  `risk_engine.validate_candidates` measure a candidate against those risk-unit tallies whenever
  the candidate's own `current_iv` is known — the normal path since Task 2 — so the per-ticker and
  per-sector caps only ever constrained a batch's candidates *against each other*, never against
  the book the account already held. `main`'s pre-branch `_seed_exposures` had seeded and checked
  both `ticker_exposure` and `sector_exposure` cumulatively, so this was a weakening of an existing
  control. **Fixed** by giving `seed_budgets` an optional `iv_of` lookup (default `None` = the old
  behaviour exactly): supplied, option positions charge `ticker_risk`/`sector_risk` at their own
  DTE; stock positions never do (no natural DTE), and neither does an expired or IV-less option.
  `validate_candidates` takes a matching optional `iv_by_symbol`, passed by the full scan sweep
  (from the analytics map it already built) and by `scripts/capacity_report.py` (from the IV map
  already in scope) — no new fetches on either. **Deliberately not threaded:** the order-approval
  re-validation gate (`execution/approval.py`), the single-ticker `/scan SYM` deep-dive and the CSP
  generator's own sizer, all of which would need a new network round-trip on a latency-sensitive
  path. Those three are covered instead by the **cumulative raw-collateral backstop** below.
- **The large-position slot compared the candidate's marginal collateral, not the account's
  cumulative exposure in that ticker.** `_fits` and `validate_candidates` both tested
  `cand.collateral > max_collateral_per_ticker_pct`, so a name already sitting at the ceiling
  looked empty to every new candidate — the same blindness as the risk-unit bug above, in the one
  check that was supposed to be the raw-collateral brake. (This was parked during Task 1 as a
  separate finding; it is closed here.) **Fixed** by comparing
  `budgets.ticker_collateral[symbol] + collateral` in both the IV-missing fallback and the
  large-slot/large-ceiling checks, in `capital._fits` and in `validate_candidates`'s inline copy.
  Cumulative is what makes this pair the backstop for the three un-threaded callers above:
  whatever they know about a candidate's own IV, one ticker can never exceed
  `max_pct_per_ticker_large` (25% of NLV) in raw collateral, and anything past
  `max_collateral_per_ticker_pct` (10%) is refused unless a slot is free. (`capital.charge`'s own
  slot-*consumption* bookkeeping is still marginal, not cumulative — a known, non-blocking gap;
  see "Remaining known issues" below.) **What it deliberately does NOT do** is make the 10% cap
  unconditional: a first large lot in an empty name
  (a $65k META put at $300k NLV) still reaches the slot and still trades, so D1's headline result
  is untouched — verified by re-running `scripts/capacity_report.py`, which is unchanged at 46/46
  with an identical binding distribution. An unconditional 10% check, measured on the same live
  snapshot, would have cut that to 33/46 with 13 symbols at zero lots and `large_ceiling`/
  `large_slot` never firing again. Regression tests: `tests/test_capital.py` (6 new),
  `tests/test_engine.py::TestConcentrationInRiskUnits` (3 new, including the no-`iv_by_symbol`
  order-approval shape).
- **Every ROLL was structurally rejected at the approval-queue re-gate.** The ROC floor, the
  annualized-yield floor and the D2 variance-risk-premium floor applied to all strategies. A
  defensive roll books `roc_pct = 0.0` by construction and pays a premium deliberately below the
  new strike's fair value — that is what a repair costs — so `validate_candidates` rejected every
  one of them on the second pass, *after* the operator had approved the card. **Fixed** by scoping
  those three gates to `_INCOME_STRATEGIES`. A roll's economics stay bounded by
  `strategies/rolling.py`'s own `monitor.roll_defensive` knobs (`max_debit`,
  `min_delta_reduction`, `require_breakeven_improvement`), which are untouched; `cand.ideal`
  remains populated on roll cards as display/audit.
- **`monitor.manage_at_dte` was configured but never read.** The key existed in `MonitorCfg` and
  `settings.yaml`, and `triggers.check_all` read `limits["manage_at_dte"]`, but `intraday.py`'s
  `limits` dict never carried it — so editing the key had zero effect and every management-point
  alert used the hardcoded 21-day fallback. **Fixed** (one line), with a test that fails without it.
- **The fence test had stopped covering the engine path.** `tests/test_eval_skills.py` checked a
  hand-maintained list of six modules that never gained `engine/capital.py` (position sizing and the
  concentration caps), `execution/circuit_breakers.py`, `profit_take.py` or `roll_pipeline.py`. It
  now globs `src/engine`, `src/execution` and `src/strategies` — the pattern the strategies
  directory already used — covering 19 modules, so the fence cannot silently stop covering new code.
- **`IVStats.current_iv` had no test with real quotes.** Every `get_iv_stats` test omitted `quotes`
  and every scan-pipeline test monkeypatched it wholesale, so `_atm_iv_at_30d`'s constant-maturity
  interpolation — which feeds position sizing, the concentration caps, `IdealZone.min_credit` and
  the IV/RV gate — had no coverage of its real code path. **Added** a three-expiry chain with
  distinct IVs (40/60/80% around a parity-recoverable $100 spot) asserting the 30-day interpolation
  lands at 47.5%, then feeding that `IVStats` into `capital.max_contracts`.
- **Dead duplicate constant.** `orchestrator/scan.py`'s `_ASSESSED_LIMIT` was left behind by the
  Task 17 orchestrator split; the live copy is `orchestrator/scan_progress.py:53`. Deleted.

## Bugs fixed (2026-08-10/11 — remediation Phases 1–3: capital, income, and loss management)

The 2026-08-10 full-system review (`docs/superpowers/specs/2026-08-10-remediation-and-ios-app-design.md`
§1) found that the deterministic layer could not trade the universe it was designed for, at the
account's actual size, for economically correct reasons — defects in the capital model (D1), the
income gate (D2), and loss management (D3), plus three narrower correctness bugs (D4, D5, D6)
discovered alongside them and one open measurement gap (D7). The remediation plan
(`docs/superpowers/plans/2026-08-10-remediation-phases-1-3.md`) closed **D1–D6** across Phase 1
(Tasks 1–9) and Phase 2 (Tasks 10–14); **D7 remains open** and is the one item on this list an
agent could not close — see its entry below. Regression tests: `tests/test_capital.py`,
`tests/test_account_sizing.py`, `tests/test_engine.py`, `tests/test_covered_call.py`,
`tests/test_iv.py`, `tests/test_loss_exits.py`, `tests/test_circuit_breakers.py`,
`tests/test_roll_pipeline.py`, `tests/test_monitor.py`, `tests/test_autonomy.py`.

- **D1 — CSP sizing and the concentration gate were never reconciled.** `screen_csp_candidates`
  sized to the *maximum affordable* lot (cash, the old 60% CSP budget, `max_contracts: 10`),
  knowing nothing about `max_pct_per_ticker: 5.0`; `validate_candidates` then **rejected rather
  than trimmed**. A single 1-lot CSP required `NLV >= 2000 x strike`, so at $300k NLV every strike
  above $150 was unreachable — excluding META, GOOGL, MSFT, and most of the Tier-1 core book.
  **Fixed:** `max_pct_per_ticker` was split into three constraints in their proper units —
  feasibility in cash, concentration in **risk units** (`collateral x IV x sqrt(DTE/365)`, so share
  price is no longer a risk measure), and deliberateness via an explicit counted large-position
  slot — behind one shared `engine/capital.py` helper (`resolve_caps` / `max_contracts` /
  `seed_budgets`) that both `cash_secured_put.screen_csp_candidates` and
  `risk_engine.validate_candidates` call, so the generator and the gate can no longer disagree
  about how big a position may be. **Measured:** `scripts/capacity_report.py` (Task 8, re-verified
  after this task's config change) shows **46/46 `would_own` symbols tradeable** at $300k NLV /
  $100k cash, including META (1 lot), MSFT, QQQ, and SPY, none of which could clear the old gate at
  that account size. `max_risk_units_per_ticker_pct` ships at `5.0`; the capacity report's
  per-symbol collateral column shows AMD's single lot alone consumes 3.06% of NLV in risk units
  (SMH 2.85%, NBIS 1.89%, QQQ 1.78%, META 1.77%) — the floor below which AMD becomes unreachable
  again, leaving only a 3.1–5.0 viable band. `5.0` is therefore a deliberate, human-reviewed choice
  at the *permissive* end of that band, not an inherited or arbitrary number — see
  `config/risk_limits.yaml`'s `CALIBRATION WARNING` comment.
- **D2 — the income floor was a hidden IV floor of roughly 25–30%.** `min_roc_pct: 1.0` combined
  with `min_annualized_yield_pct: 12.0` produced a binding floor of `max(1.0%, 12% x DTE/365)`.
  Verified with Black-Scholes at 30 DTE: SPY at 13.5% IV yielded 0.33% ROC at 0.20Δ and 0.66% at
  0.30Δ — rejected at every admissible delta; AAPL at 28% IV was rejected at 0.20Δ (0.71%) and
  passed only at 0.30Δ (1.62%). Every defensive diversifier deliberately added to `universe.yaml`
  (GLD, TLT, XLP, XLU, XLV, XLI, SPY, V, MA, WMT, COST) could never produce a CSP, and composed with
  D1 the emergent strategy was short puts on cheap, high-IV, speculative names only — the opposite
  of the documented Tier-1 core-income intent. **Fixed:** the variance-risk-premium floor already
  computed in `analytics/fair_value.py` (Black-Scholes fair value at *realised* vol HV30, plus
  `ideal_zone.min_credit_edge_pct`) was promoted from display to a real gate
  (`income.require_vrp_edge: true`, reason `premium_below_fair_value`); `min_roc_pct` dropped to
  `0.15` and `min_annualized_yield_pct` to `0.0`, both now noise floors only. The gate asks "am I
  being paid more than this risk is worth?" instead of "is the yield big enough?" — the hidden delta
  floor disappears as a side effect.
- **D3 (2026-08-11, Remediation Phase 2, Tasks 10, 11, 13, 14) — there was no loss management, and
  the one circuit breaker meant to catch a bad day could not see losses.** The only exits were the
  50% profit take, expiry, assignment, and *alert-only* roll triggers firing at DTE ≤ 7;
  `grep -i "stop_loss\|max_loss"` over `src/` and `config/` returned nothing. Short premium's whole
  risk lives in the left tail, so an unattended 15-minute loop that could only add exposure and
  harvest winners was the one configuration able to genuinely hurt the account. Compounding it,
  `circuit_breakers.daily_loss_breached` measured *realized cashflow* (summed `FillRow` credits and
  debits), so a day that sold premium into a 15% drawdown registered as a **profit** and the kill
  switch stayed open while the loop opened more shorts into the same move. **Fixed in four parts:**
  (a) `execution/profit_take.check_loss_exits` (Task 10) buys to close any short whose cost-to-close
  reaches `automation.max_loss_multiple` × the net entry credit (default `2.0`), running each
  intraday cycle through `position_manager.close_short_position` and notifying Telegram — including
  on the failure/partial/no-fill paths, so a close that did not actually happen is never reported as
  one; (b) `mark_based_loss` (Task 11) replaces the cashflow measure with a genuine mark-to-market
  one — today's summed position `unrealized_pnl` against the prior day's `position_snapshots` row,
  tripping at `automation.daily_loss_halt_pct` (3.0) — and the new `drawdown_breached` trips at
  `automation.drawdown_halt_pct` (10.0) below a trailing net-liquidation high-water mark, catching a
  slow bleed no single day trips; both are wired into `execution/approval.process_queued_orders`,
  which auto-engages the persisted `/halt` kill switch on whichever fires first (`daily_loss_breached`
  and its tests are kept for reference but are no longer called); (c) `check_manage_at_dte` (Task 13)
  adds the mechanical 21-DTE management point (`monitor.manage_at_dte`) so a position is reviewed
  while closing, rolling, and holding are all still viable, rather than first at `dte_threshold: 7`;
  (d) the **four-rung autonomy ladder** (Task 14) replaces the old binary MANUAL/AUTOMATED toggle so
  unattended *opening* is arrived at through evidence (`OBSERVE < MANUAL < WHITELIST < FULL`,
  promotion gated by `system_settings.promotion_blockers`), while risk-*reducing* closes run
  independently of the rung under `automation.auto_close_enabled` — closing risk never waits for a
  tap. See "What is built" above for the full behaviour of each.
- **D5 — the wheel's already-collected premium was invisible to the covered-call gate.**
  `campaigns.mark_campaign_assigned` computed `adjusted_cost_basis` (assignment price minus net
  premium per share) on a put assignment, but only the `/campaigns` Telegram formatter read it;
  `screen_cc_candidates` used IBKR's raw `avg_cost`, so `min_strike_vs_basis: 1.00` compared against
  the assignment price rather than the true, premium-reduced basis. **Fixed:** `covered_call.py`
  resolves cost basis via `campaigns.adjusted_cost_basis_for(symbol)` (falling back to IBKR's raw
  `avg_cost` when no open assigned campaign exists) and uses it for the `min_strike_vs_basis` gate,
  ROC, breakeven, and the ideal-zone cost basis — a wheel that collected premium on assignment can
  now write strikes below the assignment price without the gate reading that as locking in a loss.
- **D6 — IV rank compared two different measurements against each other.** `iv_history` stores
  IBKR's `OPTION_IMPLIED_VOLATILITY` daily bar (a ~30-day constant-maturity ATM index) while
  `current_iv` was overridden intraday by `_live_atm_iv` — the mean IV of the four strikes nearest
  spot in the nearest *scanned* expiry (~21–25 DTE). In contango this biased IV rank down; in
  backwardation, up — loosening `iv.min_iv_rank: 30` (a hard gate) exactly when the term structure
  inverted. **Fixed:** the live chain IV is now interpolated to a constant 30-day maturity
  (`_atm_iv_at_30d`, reusing the term-structure slope already computed by
  `_term_structure_slope`) before ranking, so numerator and denominator are the same measurement;
  when the chain carries fewer than two expiries it falls back to the stored daily observation
  rather than the nearest-expiry value.
- **D4 (2026-08-11, Remediation Phase 2, Task 12) — a defensive roll needed economics it could
  never produce, so the candidate list was empty exactly when the monitor fired.**
  `generate_roll_candidates` had one economics path — net credit required, plus
  `income.min_roc_pct`/`min_annualized_yield_pct` — appropriate for an *income* roll (rolling an
  unchallenged position forward for more premium) but wrong for a *defensive* roll (rescuing a
  challenged, deep-delta short from an adverse move): a 0.60-delta short usually cannot be rolled
  to a safer delta for a credit at all, so the roll-candidate list was empty precisely when
  `should_roll` fired. **Fixed:** the function takes a keyword-only `defensive: bool = False`.
  `defensive=True` skips the ROC/annualized-yield tests entirely and instead requires the new leg
  to cut `|delta|` by at least `monitor.roll_defensive.min_delta_reduction` (default `0.10`),
  permits a bounded net debit up to `max_debit` (default `$0.50`/share), and — when
  `require_breakeven_improvement` (default `true`) — requires the new strike to improve the
  breakeven whenever the roll isn't itself a credit. `roll_pipeline.queue_roll_for_approval`
  (the sole production caller of `generate_roll_candidates`, reached by both the Telegram roll
  flow and the intraday monitor's `_try_queue_roll`) now passes `defensive=True` unconditionally
  — every roll it generates originates from a monitor trigger, so income economics never applied
  there. Income rolls (`defensive=False`, the default) are unchanged and still require a net
  credit clearing the ROC/yield floor. Both paths already populate `TradeCandidate.ideal`
  (D2 follow-up, Task 5), so the VRP gate reaches ROLL candidates of either kind unchanged by this
  task. **Also fixed in the same task:** `rolling.py`'s DTE computation used local
  `datetime.date.today()` instead of `market_hours.today_et()` — a residual instance of the class
  of bug the 2026-08-06 output-fidelity audit fixed everywhere else it found it, missed here
  because `rolling.py` was out of that audit's scope. For an operator running east of US/Eastern
  (e.g. UTC+8), local `date.today()` can read a calendar day ahead of the exchange, so
  `should_roll`'s `pos_dte <= 21` trigger could fire a day early. Regression tests:
  `tests/test_roll_pipeline.py` (`test_defensive_roll_allows_a_bounded_debit`,
  `test_defensive_roll_rejects_a_debit_above_the_cap`,
  `test_defensive_roll_requires_delta_reduction`,
  `test_income_roll_still_requires_a_credit_and_roc`, `test_roll_dte_uses_et_not_local_date`).
  **Not in scope for this task:** `monitor.manage_at_dte` (added to `MonitorCfg`/`settings.yaml`
  by this task) is not yet read anywhere — wiring a mechanical close/roll/hold decision point at
  21 DTE is Task 13. (Task 13 added the trigger; the config key itself only became load-bearing in
  the 2026-08-12 final-review fix wave, which threaded it through `intraday.py`'s limits dict — see
  that section above.) **Correction (2026-08-11, code review, fix-round-1):** the delta-reduction
  check as first written (`if pos_delta_abs is not None and (pos_delta_abs - delta_abs) <
  min_reduction: continue`) silently skipped the whole safety check when the position snapshot
  carried no delta reading (`PositionSnapshot.delta` is `float | None`), letting a defensive roll
  through with zero verified delta reduction — a fail-*open* bug directly contradicting this
  task's own "must reduce \|delta\| by at least `min_delta_reduction`" spec. Changed to fail
  closed: `if pos_delta_abs is None or (pos_delta_abs - delta_abs) < min_reduction: continue` —
  an unknown starting delta now rejects the candidate instead of silently passing it. Covered by
  `test_defensive_roll_rejects_when_position_delta_is_unknown`.
- **D7 — OPEN, not fixed. Every genuinely uncertain execution behaviour still sits behind a
  default-off flag and has never been exercised against a real broker.** `execution.reprice_enabled`
  and `monitor.roll_execution_enabled` are both `false`, and
  `live_execution.require_ibkr_greeks_when_live` is `true` on a data subscription that has never
  been observed populating `greeks_source == "ibkr"`. Closing this is **measurement, not code**: it
  needs a live TWS/IB Gateway paper session on port 4002 during regular trading hours, a human
  tapping Approve/Reject in Telegram, and ≥ 20 approved orders gathered across multiple sessions —
  none of which an agent can produce, which is why remediation Task 15 is the one task of the
  eighteen that is scaffolded rather than done. The record file exists and is empty:
  **`docs/live-validation-2026-08.md`**, carrying the spec's five questions (mid-limit fill rate by
  liquidity tier; whether the `reprice_enabled` amend modifies rather than duplicates an order;
  whether the BAG combo sign convention is right on a real roll; whether `greeks_source == "ibkr"`
  ever populates; whether Tier 3 names produce candidates end-to-end). **Hard gate, unchanged:** if
  Question 4 comes back 0%, `require_ibkr_greeks_when_live: true` will silently block 100% of live
  income trades — do not proceed toward live trading until that is resolved, or the flag is
  deliberately set `false` with the justification written into that file. Everything below under
  "Validated by mocked tests only" is the same gap seen from the other direction.

### Tradeable capacity at $300k (2026-08)

`scripts/capacity_report.py` is the regression check the unit suite structurally cannot be: the
1,129 tests ask "does the gate reject what it says it rejects" and never "what can this system
trade today," which is why D1 and D2 both passed CI for as long as they did. One row per `would_own`
symbol: how many contracts the account can support right now, and which constraint stops the next
one. Raw output of `python -m scripts.capacity_report --net-liq 300000 --cash 100000`, re-run
2026-08-12 after the final-review fix wave against the committed `risk_limits.yaml` (spot prices
come from live quotes, so the exact figures drift run to run; the binding reasons do not):

```
SYMBOL        SPOT  LOTS   COLLATERAL  BINDING
----------------------------------------------
HIMS         30.51    10       27,460  none (hit hard_max)
MARA          9.68    10        8,710  none (hit hard_max)
RGTI         18.09    10       16,280  none (hit hard_max)
SLV          58.55    10       52,690  none (hit hard_max)
SOFI         17.98    10       16,180  none (hit hard_max)
TLT          82.19    10       73,970  none (hit hard_max)
TTD          13.56    10       12,200  none (hit hard_max)
UBER         78.54    10       70,690  none (hit hard_max)
XLE          60.93    10       54,840  none (hit hard_max)
XLF          57.80    10       52,020  none (hit hard_max)
XLU          43.63    10       39,270  none (hit hard_max)
XLP          84.69     9       68,598  large_ceiling
HOOD         94.38     8       67,952  large_ceiling
IGV         103.92     8       74,824  cash
HACK        118.80     7       74,844  cash
RKLB         80.01     7       50,407  ticker_risk
WMT         113.26     7       71,351  cash
BABA        127.85     6       69,036  cash
COIN        148.58     5       66,860  cash
CRM         197.47     4       71,088  cash
PLTR        174.94     4       62,980  large_ceiling
XLI         185.70     4       66,852  cash
XLK         186.09     4       66,992  cash
XLV         168.01     4       60,484  large_ceiling
AMZN        272.27     3       73,512  cash
CRWD        221.90     3       59,913  large_ceiling
DDOG        246.78     3       66,630  cash
NVDA        217.50     3       58,725  large_ceiling
AAPL        304.91     2       54,884  cash
GLD         400.96     2       72,172  cash
GOOGL       343.80     2       61,884  cash
HD          354.48     2       63,806  cash
IWM         300.99     2       54,178  cash
JPM         362.04     2       65,168  cash
NBIS        193.23     2       34,782  ticker_risk
NET         306.97     2       55,254  cash
SNOW        334.14     2       60,146  cash
TSLA        332.81     2       59,906  cash
V           362.82     2       65,308  cash
AMD         474.32     1       42,689  cash
MA          561.44     1       50,530  cash
META        599.12     1       53,921  cash
MSFT        503.81     1       45,343  cash
QQQ         718.45     1       64,661  cash
SMH         572.93     1       51,564  cash
SPY         770.56     1       69,350  cash

46/46 symbols tradeable at this account size.
Coverage: 46/46 requested symbols had usable price/IV data (0 skipped for missing data).
```

**Read it as the D1/D2 evidence, distinct from the tests passing.** Every one of the 46 `would_own`
symbols gets at least one lot — including SPY at $770, META at $599, QQQ at $718 and MSFT at $503,
none of which could clear the old `max_pct_per_ticker: 5.0` gate at this account size (a 1-lot CSP
used to require `NLV ≥ 2000 × strike`). The `Coverage:` line is load-bearing: it is computed from
the pre-filter requested population, so a data outage that silently dropped symbols would show up
as a shrinking numerator instead of a still-100%-looking fraction. Binding distribution: `cash` 27,
`none (hit hard_max)` 11, `large_ceiling` 6, `ticker_risk` 2 (RKLB, NBIS — the two high-IV names
where risk units bind before raw collateral, exactly the D2-shaped signal), `ticker_collateral` 0,
`sector_risk` 0, `csp_budget` 0, `large_slot` 0. Low-IV names being cash-bound rather than
concentration-bound is the model working as designed. The shift versus the 2026-08-11 run
(`cash` 26 -> 27, `large_ceiling` 7 -> 6) is spot drift, not a rule change — IGV, HACK and CRWD
moved across the 25%-of-NLV ceiling as their prices moved — and the 2026-08-12 fix wave's
risk-unit seeding cannot move this table at all, because the hypothetical `--net-liq/--cash`
branch runs with an empty position list. Re-run this after any change to
`risk_limits.yaml → portfolio` or `income`.

## Bugs fixed (2026-08-06 — output-fidelity audit: every user-facing surface rendered and reviewed)

Every formatter was rendered with realistic data and the output read as an operator would see it.
The notification layer itself held up well — quiet 15-min cycles emit **zero** new messages (the
per-thread status message is edited in place), empty states are all specific, and the source
footers are honest. The defects were concentrated in the **ideal-zone analytics** feeding the most
prominent block on every card, plus raw internals leaking into two alerts that fire on live
positions. None of them could reach an order **at that time**: `zone_fit` shipped (and still ships)
at `0.0`, so all four were display-only. That is no longer the whole story — D2 (2026-08-10) later
promoted the zone's `min_credit` to a real risk-engine gate, so an ideal-zone defect of this kind
*would* now be able to reject a trade. Regression tests: `tests/test_output_fidelity.py`.

- **Ideal credit compared the wrong two numbers (P0):** `compute_ideal_zone` priced `min_credit` at
  the band's **anchor** strike, and the card then rendered it against the **offered** contract's
  premium. Option value falls steeply with moneyness, so every strike above the anchor was
  systematically mislabelled — measured on AAPL (spot 232.40, 29 DTE, HV30 22.2%, anchor 240.32): a
  $250C at $2.31 read "below fair value" while trading at **2.0× its own $1.13 floor**, and a $255C
  at $1.42 at 2.4× its own. Since a typical 0.25–0.30Δ covered call sits *above* the anchor, the
  common case was a false warning against a good trade. **Fixed:** new
  `fair_value.zone_for_contract(zone, strike, iv, *, cost_basis)` re-prices the floor at the strike
  actually on offer; both generators call it per candidate. The band stays memoized per DTE.
- **ROC/yield floor used the wrong denominator for covered calls (P0, found while fixing the
  above):** `min_credit_for` (then private, `_min_credit`) divided by *strike* for both
  strategies, but a CC's gate is `premium/avg_cost` (only a CSP's is `premium/strike`). On a
  strike above basis — the normal case for a CC — this inflated the floor and made it **rise**
  with strike while fair value fell, so the floor was non-monotonic. **Fixed:** `min_credit_for`
  takes a `roc_basis`; CC passes cost basis, CSP passes strike.
- **"✓ in zone" endorsed at-the-money covered calls (P0):** `_snap_to_level` translated the whole
  band onto a nearby support/resistance level, preserving dollar width. Moneyness is non-linear, so
  that does **not** preserve the delta profile the width encodes. Same AAPL case: resistance at
  248.10 sat 2.0% inside `support_pull_pct: 3.0`, shifting the band from 237.59–253.15 (Δ0.44–0.16)
  to 232.54–248.10 (**Δ0.53**–0.22) — an inner edge $0.14 from spot. A 53-delta covered call
  rendered "✓ in zone", and the verdict was near-unfalsifiable (anything ATM to +7% passed).
  **Fixed:** the inner edge is clamped back to `em_lo_mult` after snapping, so the band stretches to
  reach the level instead of sliding through spot. Inner edge is now Δ0.42.
- **Two definitions of "today" (P0):** `date.today()` (server-local) was used in 16 modules while
  `OptionQuote.dte` used ET. For an operator in UTC+8 these disagree for most of the working day —
  visible *inside a single roll alert* as "`DTE=12 <= threshold=14`" beside "`DTE 13`", and reaching
  `risk_engine.py`'s earnings/DTE windows, `triggers.check_dte_threshold` (firing a day early), and
  `price_data`'s settled-bar check. This is the same class of bug as the 2026-06-24 EOD Δ-baseline
  skew, which was fixed locally rather than generally. **Fixed:** `market_hours.today_et()` is now
  the single definition of a market date; the two ad-hoc local `_today_et()` helpers
  (`eod_report`, `eval/reconcile`) delegate to it. `date.today()` remains only for genuinely local
  concerns (backtest fallbacks).
- **Raw debug text in roll / assignment alerts (P1):** `RollAlert.detail` rendered as
  `delta=0.46 > ceiling=0.45` and `DTE=12 <= threshold=14`, and trigger names as
  `delta_drift + dte` — a jarring contrast with the 22-entry `_REJECT_REASON_LABELS` table used
  elsewhere. **Fixed:** all five `check_*` functions write prose ("Delta 0.46 has drifted past the
  0.45 roll line — the short is tracking the underlying more closely than intended"), and
  `_TRIGGER_LABELS`/`_humanize_trigger` renders "Triggers: delta drift + nearing expiry".
- **OCC symbol leaked into the two position alerts (P1):** `format_profit_alert` and
  `format_auto_close_result` printed `AAPL  260818C00245000` (double space and all) while every
  other card rendered `AAPL $245C Sep 04` — the same contract was unrecognisable between messages.
  **Fixed:** both take the contract's parts and render via the new shared
  `formatters.contract_label()`; `profit_take.py`'s inline auto-close **error** message was leaking
  it too and now uses the same helper.

## Bugs fixed (2026-06-24 — EOD report quality & unrealized-Δ baseline)

After two live EOD reports surfaced a redundant, hard-to-read summary, the report was reworked and
a real bug was found:

- **Unrealized Δ baseline silently broken (date skew):** `_build_eod_summary` keyed the JournalRow
  on local `date.today()` while `_load_yesterday_unrealized` / `_compute_realized_pnl` read by the
  **ET** trading day. In UTC+8 the EOD run fires next-morning local, so the write date and read date
  differed — yesterday's row was never found and the unrealized Δ collapsed to the *full* unrealized
  value every day (visible in the first two reports: Δ exactly equalled the total). **Fixed:** a
  single `_today_et()` anchors the summary date so write and read align.
- **Narrative was ~70% redundant:** the Claude journal paragraph restated the figures already shown
  in the stats block (prompt literally said "Be specific about numbers"). **Fixed:** `prompts/eod.py`
  now instructs interpretation only — explain *why* it moved + one action for tomorrow, one sentence
  on a quiet day — and forbids restating the numbers.
- **Drivers line was always empty:** `top_movers` was built from option positions only, so a
  stock-only book (e.g. a wheeled/assigned holding) showed no driver. **Fixed:** movers now aggregate
  unrealized P&L by underlying across **all** sec_types; `EODSummary.mover_pnl` carries each one's
  P&L so the report renders "Drivers: NVDA -$7,673".
- **Formatting:** the metric block is now a ``` code fence ``` (columns actually align in Telegram's
  proportional font — the old manual space-padding did not), adds an **NLV/BP** line and the day's Δ
  as **% of NLV**; the "excludes assignment P&L" disclaimer is shown only when there was cashflow or
  fills (suppressed on flat days); and the static 30+ ticker watchlist collapses to "N names
  (unchanged)" unless it actually changed (`EODSummary.watchlist_changed`).

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
  `process_queued_orders`), `automation.daily_loss_halt_pct` (auto-engages the kill switch when today's
  mark-to-market P&L, via `mark_based_loss`, drops this % of net liquidation vs. the prior position
  snapshot), and `automation.drawdown_halt_pct` (auto-engages when net liquidation, via
  `drawdown_breached`, falls this % below its trailing high-water mark). The `/halt` and `/resume`
  Telegram commands flip a persisted `execution_halted` switch checked by the order-poll loop, the
  auto-queue path, and the intraday loop; profit-take closes still run while halted (closing risk is
  always allowed). **Correction (2026-08-11, D3):** the loss breaker originally measured *realized
  cashflow* (`daily_loss_breached`/`realized_cashflow_today`, summed FillRow credits/debits), which
  reads a day the system sold premium into a real drawdown as a profit — the kill switch never tripped
  while new short positions kept opening into the same adverse move. `mark_based_loss` (and the new
  `drawdown_breached` slow-bleed catch) replace it in the wiring; the old function and its tests remain
  for reference but are no longer called from `process_queued_orders`.
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
- **N12 auto-open semantics documented (design decision):** whenever the system opens a position
  without a human tap, it trades the **deterministic, gate-passing slate**; Claude's review is
  enrichment shown for the record but does **not** filter, gate, or reorder what executes — a
  "skip / confidence 0.9" verdict changes nothing. This is required by the fence (Claude must never
  gate an order). To raise the auto-open bar, raise `weights.min_candidate_score` (which applies at
  every rung) — never route it through Claude's verdict. `_auto_queue_candidates` queues the slate;
  the execution-time Rules-Engine re-gate and circuit breakers remain the only deterministic guards.
  *(Written when auto-open was the binary AUTOMATED half of a MANUAL/AUTOMATED toggle; Task 14
  replaced that with the four-rung ladder, so "auto-open" now means WHITELIST's listed symbols and
  anything at FULL. The semantics above are unchanged by that — only the name of the state is.)*
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
  **Hardened (2026-06-24):** `_append_daily_iv` no longer hangs the whole EOD report when IBKR's
  historical-data farm (HMDS) is down for the session. Each `reqHistoricalData` call is bounded by
  `_IV_REQUEST_TIMEOUT_S` (8s) via `asyncio.wait_for` instead of ib_async's 60s default, and a
  circuit breaker (`_IV_MAX_CONSECUTIVE_FAILURES`, 5) aborts the loop once a run of symbols all
  fail — a dead farm fails identically for every symbol, so grinding the full universe just delayed
  the (IV-independent) P&L summary and Telegram send by ~1 hour. On a dead farm the run now bails in
  ~40s, sends the summary on time, and lets `iv_history` age one day (it back-fills on the next
  healthy run). This mirrors the scan loop's half-dead-socket guard.
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

## Built (2026-06-24 — raw analytics surfaced to the AI layer + deep-dive hardening)

- **Raw technical / fundamental / IV-microstructure signals now reach the reasoning layer.**
  Previously the prompt only carried the opaque ScoreCard composites (`Tech=`/`Fund=`/`IV=`),
  while RSI, regime, SMA position, ATR/price, P/E, D/E, FCF, dividend/ex-div, IV-percentile,
  IV/RV, term-structure slope, and put/call skew were computed every scan and discarded before
  reaching Claude/Ollama (and `term_structure_slope`/`put_call_skew`/`iv_percentile` were dead —
  computed, some at chain-fetch cost, but consumed nowhere). `strategist.build_prompt` now takes an
  `analytics` map and annotates each candidate with a compact Technicals / Fundamentals / IV-structure
  block (`_analytics_lines`); `run_scan` and `run_ticker_scan` thread their `analytics_map` through
  `review_candidates` → `runner`/`ollama_runner` → `build_prompt`. This also fixes a latent
  mismatch where the single-ticker SUMMARY GUIDE asked the model to interpret "RSI/trend" that the
  prompt never supplied. Enrichment only — never reaches the engine (the fence). New prompt tests.
- **Single-ticker deep-dive no longer goes silent when nothing qualifies.** `run_ticker_scan`
  previously gated the macro/sector backdrop **and** the LLM Read behind a passing candidate, so a
  name with no gate-clearing contract lost both the "🌐 Market & Sector" line and the "🧠 Read".
  The backdrop is now always fetched, and the Read falls back to reviewing the closest near-miss per
  strategy (surfaced only as the overall `summary`, never as a per-candidate verdict). The prompt
  intro is gate-neutral for single-ticker so the framing stays honest when reviewing near-misses.

## Built (2026-06-24 — holistic single-ticker `/scan TICKER` deep-dive)

- **Educational, context-aware single-ticker scan:** `/scan TICKER` now produces a holistic read
  rather than just a verdict. New `src/analytics/sector_context.py` builds a `SectorContext`
  (yfinance GICS sector/industry → SPDR sector-ETF proxy, plus 1-month/5-day sector, SPY, and
  ticker returns and a relative-strength figure from the day-cached OHLCV store; fully fail-soft).
  `run_ticker_scan` gathers the ticker's prior-recommendation memory, `MarketConditions` (VIX), and
  the `SectorContext` off-thread (in parallel) and passes them to `review_candidates(...,
  single_ticker=True)`. The `single_ticker` flag switches `strategist.build_prompt` to inject the
  sector backdrop and request a new `ClaudeReview.summary` field — a plain-English synthesis that
  *explains what each metric (IV rank, VRP, delta, RSI, earnings) means*, reads the VIX regime and
  sector performance, and gives an overall sentiment. The card renders a deterministic
  "🌐 Market & Sector" line and a "🧠 Read" block, plus a `📌` assignment-considerations line under
  each contract verdict. Full-universe `/scan` is unchanged (the prompt omits `summary` to keep the
  buy-list concise). Enrichment only — none of this reaches the deterministic engine (the fence).
  Backed by `tests/test_sector_context.py` + new prompt/formatter tests (14 new tests).

## Built (2026-06-21 — C5: reprice extended to close and roll legs)

- **SmartPricing fill-walking extended to all three execution paths (C5):** `reprice_limit` chase
  loops now run in `position_manager.close_short_position` (BUY-to-close, steps toward ask) and
  `roll_executor.execute_roll` (BAG combo, re-fetches per-leg quotes, steps net-credit limit
  toward market with a floor of `min_live_premium_ratio × approved credit`), in addition to the
  existing entry-SELL path in `executor.execute_candidate`. All three gated by
  `execution.reprice_enabled` (default false) — live-paper verification of the `placeOrder` amend
  still required before enabling (see "Remaining known issues" below). 3 new tests cover the close
  and roll reprice paths.

## Bugs fixed (2026-06-18 — Ollama circuit breaker)

- **Ollama parse failures logged every cycle:** `qwen3` with `format: "json"` leaks `<think>`
  traces that produce malformed JSON, generating a WARNING on every scan cycle even when the model
  is persistently unhealthy. Added a module-level circuit breaker in `src/claude/ollama_runner.py`:
  after `_CIRCUIT_THRESHOLD` (3) consecutive connection errors or unparseable outputs the circuit
  opens, subsequent calls return empty immediately with only a DEBUG trace, and a single WARNING is
  logged when it opens. The circuit resets (with a recovery WARNING) on the first successful parse.
  All four public functions (`review_candidates`, `review_roll`, `write_journal_narrative`,
  `propose_skill`) participate.

## Bugs fixed (2026-06-24 — clientId collision on fast restart left /account & /status dark)

- **A quick stop→start cycle disabled the scan connection for the whole session:** the approval
  service's exec and scan connections (and the monitor) each did a single one-shot
  `connectAsync` with no retry. On a fast restart, IB Gateway still held the previous process's
  client IDs for a few seconds, so the new connect raced the old sockets' teardown and hit
  `Error 326` ("client id is already in use") → `Peer closed connection` → a connect
  `TimeoutError`. With no retry, that one failed attempt disabled the connection permanently:
  `/account`, `/status`, `/scan`, `/positions` (all served by the scan connection, clientId 15)
  reported "IBKR account unavailable" until the next manual restart. Observed 2026-06-24 03:42 —
  clientId 15 was the prior **half-dead** scan socket, which lingered longest on Gateway's side,
  so it specifically lost the race while the healthy exec/monitor ids reconnected. Fixed:
  - `src/ibkr/connection.py`: new shared `connect_with_retry(...)` — `connectAsync` with bounded
    exponential backoff (reuses `ibkr.reconnect.max_retries` / `backoff_base_seconds`), giving
    Gateway time to release a lingering clientId. Re-raises only after all attempts fail, so the
    caller's existing degrade-and-log path is unchanged.
  - `src/notify/approval_service._run_service` (exec + scan) and `src/monitor/intraday.py`
    (monitor) now connect through it.
  - `scripts/start.py`: a `STARTUP_GRACE_SECONDS` (default 4s, `0` disables) pause before
    launching daemons so a fast restart is unlikely to collide in the first place — the
    connect-retry is the backstop.
  - Regression tests: `tests/test_connection.py::test_connect_with_retry_*`.

## Bugs fixed (2026-06-24 — half-dead socket timed out every symbol and starved the intraday loop)

- **A mid-session half-dead socket made the intraday scan grind for ~2h and blocked every
  subsequent cycle:** sibling failure to the 2026-06-23 fix, but on the *scan* connection during
  a running session. After an evening of `Error 1100/1102` flapping, the scan socket settled into
  a state where `ib.isConnected()` returned `True` and account summary still resolved (cached/quick
  path), but every option-chain request silently never ticked. The 02:00 SGT cycle then timed out
  on **every** one of the 46 symbols at `symbol_timeout_seconds` (150s each ≈ 115 min). Because
  `_intraday_scan_loop` is a single sequential task that does not return to its top until
  `run_scan` finishes, the 02:15/02:30/.../03:45 aligned marks were all swallowed — nothing fired
  and every later cycle was blocked. The pre-existing `ib_scan.isConnected()` guard passed (TCP
  handshake intact) and the per-symbol timeout "worked" but had no circuit breaker. Fixed:
  - `src/orchestrator/scan.py`: a **circuit breaker** counts consecutive chain-fetch timeouts and,
    after `market_data.max_consecutive_chain_timeouts` (default 3) in a row, aborts the run
    (`ScanResult.aborted_unhealthy = True`) instead of grinding the rest of the universe. The
    counter resets on any fetch that returns (success or a non-timeout error — the farm answered).
  - `src/ibkr/market_data.py`: `probe_market_data_health(ib)` — a fully-bounded pre-scan liveness
    check (one snapshot quote on `market_data.health_probe_symbol`, default `SPY`, within
    `health_probe_timeout_seconds`, default 15s). `isConnected()` alone can't see a half-dead farm.
  - `src/notify/approval_service._intraday_scan_loop`: runs the health probe before each cycle; on
    failure (or on a mid-scan circuit-breaker abort) it **notifies the operator on Telegram with the
    exact reason** (`_notify_scan_blocked`), forces a reconnect (`_force_scan_reconnect` →
    `ib_scan.disconnect()`, which fires `disconnectedEvent` so `AutoReconnect` rebuilds the socket),
    and skips the cycle so the loop stays free for the next mark.
  - Regression tests: `tests/test_scan_timeout.py::test_consecutive_timeouts_abort_the_scan`,
    `tests/test_market_data.py::test_probe_*`, `tests/test_notify.py::test_notify_scan_blocked_*` /
    `test_force_scan_reconnect_disconnects_and_swallows`.

## Bugs fixed (2026-06-23 — half-dead socket hung the intraday scan loop)

- **15-min intraday scan never armed after a restart during a TWS connectivity drop:** when the
  approval service was (re)started while TWS had lost its upstream link to IBKR (Error 1100), the
  exec connection's socket handshake to TWS still succeeded, so `connectAsync` returned and `ib`
  was non-`None` — but every data request to TWS timed out (a *half-dead* socket). Startup
  fill-reconciliation (`reconcile_orphan_fills` → `reconcile_external_closes`) then called
  `await ib.reqExecutionsAsync()`, which resolves only on the broker's `execDetailsEnd` event.
  That event never arrived, so the bare `await` **hung forever**, blocking the rest of
  `_run_service` — including the `asyncio.create_task(_intraday_scan_loop(...))` that arms the
  15-minute scan. Observed 2026-06-22: the service hung from 23:33 until 00:48 (≈75 min, every
  scan from 23:45–00:30 missed), unblocking only when TWS fully dropped the socket and forced
  `reqExecutionsAsync` to raise. Fixed:
  - `src/execution/reconciliation.py`: both `reqExecutionsAsync()` calls now go through
    `_req_executions_bounded()`, which wraps them in `asyncio.wait_for(..., 30s)`; a timeout is
    logged and the reconciliation pass is skipped (returns `None`) instead of hanging.
  - `src/notify/approval_service._run_service`: the scan-only background loops (intraday +
    premarket) are now created **before** the startup reconciliation, so no IBKR-touching
    recovery step can ever gate the scan loop's creation.
  - Regression test: `tests/test_notify.py::test_reconcile_orphan_fills_does_not_hang_on_dead_socket`.

## Bugs fixed (2026-06-18 — account summary reconnect leak)

- **Error 322 / account summary never populated after reconnect:** `ib_async.IB._onError`
  fires `reqAccountSummaryAsync()` on **every** connected IB object that receives Error 1102
  (connectivity restored). With two concurrent objects — exec (clientId 14) and scan
  (clientId 15) — both reacted to 1102, generating two simultaneous `reqAccountSummary`
  subscriptions. IBKR allows only one per account; the second (and any subsequent) was
  rejected with Error 322, leaving `wrapper.acctSummary` empty for the entire session.
  Fixed in `src/ibkr/connection.py`:
  - `suppress_account_summary_on_reconnect(ib)` — patches the exec IB object so its
    `_onError` handler skips 1102; the exec connection never calls `accountSummaryAsync`.
  - `debounce_account_summary_on_reconnect(ib)` — patches the scan IB object so rapid
    1100/1102 flaps don't stack concurrent resubscription requests before the first resolves.
  Both helpers are applied in `_run_service` immediately after each IB object is created.

## Bugs fixed (2026-06-18 — scan diagnostics)

- **GOOGL/IWM/MA/PLTR silently skipped by scan:** `reqSecDefOptParams` for some symbols returns
  a SMART OptionChain with an empty `expirations` set (the real listings sit on an exchange-specific
  chain). The code was selecting the SMART chain unconditionally, producing `expirations=[]`, an empty
  raw-contract list, and the misleading "No qualified option contracts" warning. Fixed: both
  `get_option_chain_quotes` and `get_option_chain_quotes_async` now require a non-empty `expirations`
  field when selecting the SMART chain, falling back to any chain that carries expirations before
  giving up. These symbols now contribute to every scan.
- **SPY/QQQ always timed out:** Both have large, fully-liquid chains where nearly all 600+ contracts
  qualify and need live quotes — pushing past the previous 90s ceiling. `symbol_timeout_seconds`
  raised to 150 to accommodate them without risking indefinite hangs on truly stuck symbols.
- **CSP rejections fully silent:** `generate_csp_candidates` returned `[]` with no log output,
  making it impossible to diagnose why no CSPs were surfaced. Added the same per-filter rejection
  counters and `WARNING` log that the CC generator already emits (no_delta / delta_range / dte /
  no_bid_ask / liquidity / no_cash / roc / yield).

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
- **Large-position slot: the check is cumulative, `charge`'s consumption of it is not.** Found by
  the 2026-08-12 final-review re-review, after the fix above shipped. `capital._fits` and
  `validate_candidates` now correctly *require* a free slot whenever a ticker's cumulative
  collateral (existing book + the new lot) crosses `max_collateral_per_ticker_pct` — but
  `capital.charge` still marks a slot **used** only when the accepted candidate's own *marginal*
  collateral crosses that same threshold. A candidate admitted purely because of cumulative
  exposure does not itself consume a slot, so more than `max_large_positions` tickers can end up
  cumulatively over the 10%-of-NLV line. No dollar cap is breached by this on any dimension — the
  25%-of-NLV `max_pct_per_ticker_large` ceiling, cash, the CSP budget and the risk-unit caps are
  all still enforced cumulatively per candidate — and it is strictly safer than the pre-2026-08-12
  behaviour, which was marginal on both the check and the charge. Fixing it properly needs a
  below-to-above-threshold transition check in `charge`, not a one-line change; deferred rather
  than rushed into the same commit. See `capital.charge`'s docstring.

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
not been exercised against a live TWS/Gateway. **This list is D7 (see the remediation section
above), and it is still open.** The remediation plan's Task 15 scaffolded the record file —
**`docs/live-validation-2026-08.md`** — with the five questions and the method for each, but the
measurement itself is a human operator's job: it needs paper TWS/Gateway on port 4002 during regular
trading hours, real Telegram Approve/Reject taps, and ≥ 20 approved orders across several sessions.
Four items below map straight onto that file's questions — **approve → fill → confirm** is Q1 (fill
rate by liquidity tier), **limit-order repricing** is Q2, the **roll combo (BAG) sign convention** is
Q3, and **layered IBKR-first greeks** is Q4 (the hard gate) — so record the raw observation there
and then clear the corresponding item here. Nothing in this list has been cleared yet.

- **The Phase 2 unattended-action paths (D3), all of which fire without a human tap.** A **loss exit**
  actually firing on paper at `max_loss_multiple × entry credit` and the Telegram notice being
  observed — including the failure branches, since a close that partially fills or is rejected must
  not report as a completed stop. A **circuit breaker** tripped deliberately (`daily_loss_halt_pct`
  or `drawdown_halt_pct`) auto-engaging the kill switch, and `/resume` clearing it. The **autonomy
  ladder** sitting at `manual` with `/autonomy` reporting honest progress toward `whitelist` against
  real fill counts. All three are covered by unit tests with IBKR and Telegram mocked; none has been
  seen against a live paper account.
- **`AutoReconnect`** actually recovering a dropped socket and the monitor re-subscribing market data.
- The executor's **greeks-wait** capturing `entry_iv` / a live delta on real OPRA tick timing (if
  greeks consistently lag past the window, `entry_iv` stays `None` and the IV-spike baseline is absent).
- The **async on-loop** market-data and monitor paths under a real event loop (no cross-thread errors).
- A full **approve → fill → confirm** cycle on paper, including the new cumulative send-time re-gate
  and the CSP-budget sizing actually producing fills (tighten `max_csp_allocation_pct_of_deployable` to confirm a
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
  against a mocked hang and the scan continuing to the next symbol. **This failure mode was hit live on
  2026-06-22:** SMH built a 768-contract qualification cartesian (128 in-band strikes × 3 expirations × 2
  rights) of mostly-nonexistent weekly strikes; the resulting `Error 200` / `reqContractDetails` storm
  tripped an IBKR pacing lockout, and when `symbol_timeout` cancelled the hung `qualifyContractsAsync`
  mid-flight the ib_async session was left unable to service any subsequent symbol — every name from SMH
  onward then timed out (no market-data activity at all) and was skipped, so the scan produced nothing.
  **Guards added:** `max_strikes_per_symbol` (caps the cartesian at the N nearest-spot strikes),
  chunked + paced + per-chunk-timeout qualification (`qualify_timeout_seconds`, so a stuck chunk yields
  partial results instead of being killed mid-flight), and a `_OPEN_LINES` registry + `drain_market_data_lines`
  called on every symbol timeout/error to reclaim leaked lines. Still to confirm on paper: that a real
  pacing lockout now recovers — a stuck symbol is skipped cleanly and the next symbol's `reqMktData`
  calls succeed without a process restart.
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

**Additionally, as of the 2026-08 remediation, D7 gates this.** `docs/live-validation-2026-08.md`
must be filled in from a real paper session before live cutover, and its Question 4 is a hard stop:
if `greeks_source == "ibkr"` never populates on this data subscription, `require_ibkr_greeks_when_live:
true` will silently block 100% of live income trades. Resolve it, or set that flag `false`
deliberately with the justification written into that file — do not discover it in production.
Autonomy should be at `manual` (not `whitelist`/`full`) through the whole paper-validation period;
the ladder's own promotion gate will refuse to move until the fill evidence exists.
