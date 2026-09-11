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
  technicals + regime + **Phase 3** `Phase` enum / `relative_strength` / `TechnicalStats.phase` (see below), fundamentals (yfinance),
  liquidity gates, **composite social + news sentiment** (StockTwits self-tags + yfinance news headlines, both keyless,
  VADER-scored, with optional Reddit; see `sentiment.py`), Black-Scholes **full Greeks** fallback
  (`black_scholes.py` — delta/gamma/theta/vega/rho) for quotes missing IBKR model Greeks, plus an
  **American-option pricer** (`american_option.py`, Cox-Ross-Rubinstein binomial tree) exposing `american_price`
  and `early_exercise_premium` (Phase 1).
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
- **Data abstraction layer** (`src/data/`) — a thin provider abstraction **(Phase 2, complete)** between the
  analytics layer and external market-data backends. `protocols.py` defines
  `PriceProvider`/`FundamentalsProvider`/`NewsProvider` interfaces; `factory.py` picks the active
  backend from `config/settings.yaml → data.*` and caches it process-wide; `yfinance_backend.py`
  is the active backend (the existing yfinance calls wrapped in a class — no behaviour change);
  `fmp_backend.py` is a stub raising `NotImplementedError` on use — the swap path is
  documented but not wired. Analytics, strategies, and the engine never call `yfinance.*` directly — they go through `src/data/`. A
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
- **Phase classification + relative strength** (`src/analytics/technicals.py::classify_phase`/
  `_annualized_slope`, `src/common/schemas.py::Phase`) — a Minervini/Weinstein 4-stage classifier
  (`BASE`/`UPTREND`/`DISTRIBUTION`/`DOWNTREND`) computed from price vs. 50/200-day SMA, each SMA's
  own 21-bar annualized slope, and RSI; populates `TechnicalStats.phase`. **Deviates from the
  `docs/modernization/phase-3-phase-rs.md` design in one respect worth flagging:** that plan
  specified relative strength as the stock's return *relative to SPY's* (`stock_return /
  spy_return`); what shipped, `TechnicalStats.relative_strength`, is the stock's own 21-bar
  annualized price slope with no SPY comparison at all — a momentum measure, not a relative-strength
  one, despite the name and the `ScoreCard.relative_strength` field it feeds via
  `_scoring.relative_strength_score`. Both the phase gate and the score are inert today: `cash_
  secured_put.py`'s optional reject (`REASON_PHASE_DOWNTREND`, on `DOWNTREND` phase) is off by
  default (`risk_limits.yaml → cash_secured_put.reject_downtrend: false`), and `relative_strength`
  ships at weight `0.0` in `scoring_weights.yaml` alongside `zone_fit` — so today this only
  populates a display field, it changes no ranking and rejects nothing. **No test coverage**: the
  phase doc calls for a new `tests/test_technicals_phase.py` (phase classification across synthetic
  price series, RS boundary values, `reject_downtrend` on/off) and `TEM`/CSP/buy-candidate test
  extensions; none of that landed — `classify_phase`, `_annualized_slope`, and
  `REASON_PHASE_DOWNTREND` currently have zero direct test references anywhere in `tests/`. Safe
  to leave in this state only as long as both gates stay off/zero; write the tests (and settle
  whether `relative_strength` should actually compare to SPY) before raising either.
- **Buy-to-own recommendations** (`src/strategies/buy_candidates.py`) — still the pre-Phase-4 3-factor model (IV rank 40% / fundamental quality 30% / technical regime 30%); surfaced with score floor + count cap so only the strongest few names are shown, each carrying a deterministic rationale. **Phase 4 (the planned 6-factor rewrite adding Piotroski score, analyst-target upside, growth, beta, and the Phase 3 `relative_strength`/`phase` inputs — see `docs/modernization/phase-4-buy-recommendations.md`) has not been started**: none of those fields exist on `FundamentalStats`/`BuyCandidate` yet, despite `docs/modernization/README.md`'s phase index having briefly marked it complete.
- **Monitor** (`src/monitor/`) — event-driven intraday watch; all six triggers wired end-to-end:
  delta drift, the **mechanical management point** (`check_manage_at_dte`, `monitor.manage_at_dte`,
  default 21 — entries now sit at 7–28 DTE (tightened from 21–45), so a fresh entry can open as
  close as 7 DTE and be immediately past this management point; the roll trigger below fires at
  7 days, deep into the gamma window with little extrinsic left; 21 DTE is nominally the point
  where closing, rolling, or explicitly holding are all still available, though a short-dated
  entry now skips straight past it), the DTE threshold (`dte_threshold`, default 7),
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
- **Storage** (`src/storage/`) — SQLite + SQLAlchemy, WAL mode, lightweight column migration. Also hosts the Phase 5 disk cache tables (`fundamental_cache`, `sentiment_cache`) and the assessment audit trail (`risk_verdicts`).
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
| Fundamentals | `yfinance` | FCF, debt, earnings/ex-div dates (supplemental only). Cached to SQLite via `FundamentalCacheRow` (Phase 5) with earnings-aware invalidation. |
| Sentiment | `vaderSentiment` + `curl_cffi` + optional `praw` | Composite social/news sentiment; cached to SQLite via `SentimentCacheRow` (Phase 5). |
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
| **Phase 1 extended Greeks + American pricer** | **Built.** Greeks are resolved in three tiers: (1) `_ticker_to_quote` reads the first available IBKR per-contract computation (`modelGreeks` → `lastGreeks` → `askGreeks` → `bidGreeks` via `_pick_greeks`) so a lagging model tick still yields genuine IBKR greeks (`greeks_source="ibkr"`); (2) `_enrich_greeks_from_ibkr_iv` BS-fills delta locally from an IBKR IV with no network call — Phase 1 extended this to fill **gamma/theta/vega** alongside delta (skipping only when all four greeks are already present); (3) only quotes IBKR could value neither greeks nor IV for fall through to the yfinance Black-Scholes download (`_enrich_greeks_yf`), now **instrumented** (logs how many quotes forced a Yahoo fetch + the elapsed time per symbol) and also filling gamma/theta/vega. Tiers 2/3 set `greeks_source="black_scholes"` so the F6 live gate still treats them as untrusted. The scan batch requests generic ticks `101,106` to capture the IBKR IV. **Phase 1 also added** `src/analytics/american_option.py` (Cox-Ross-Rubinstein binomial-tree American pricer + `early_exercise_premium`) and `bs_gamma`/`bs_theta`/`bs_vega`/`bs_rho` to `black_scholes.py` — the foundation for economic (non-heuristic) assignment triggers. |
| **Multi-leg / roll execution** | **Built (Phase 4).** A `Strategy.ROLL` candidate is executed as one atomic BAG combo — BUY-to-close the old short + SELL-to-open the new short, no legging risk — via `src/execution/roll_executor.py::execute_roll` (`executor.execute_candidate` delegates instead of refusing). `order_builder.build_combo_roll_order` builds the BAG + net LimitOrder (credit → negative net-debit limit). Re-gates the new leg (`validate_live_quote` delta/live-greeks) + a net-credit floor, LIVE-mode [CONFIRM LIVE] tap, cancel-on-timeout, and writes two FillRows (BUY under the original short's id → ledger `closed_early`; SELL under the new id → monitor tracks it). **Combo limit-price sign convention is mock-tested only — verify on live paper first** (see below). **Wired end-to-end (N20):** when `monitor.roll_execution_enabled` is set, a roll trigger generates a candidate (`execution.roll_pipeline.queue_roll_for_approval`) and sends it with Approve/Reject buttons → QUEUED ROLL order → `execute_roll`. Default OFF until the BAG sign is verified on live paper (D7 — Q3 of `docs/live-validation-2026-08.md`, not yet run); until then rolls remain alert-only. **Defensive rolls are now judged on risk, not yield (D4, Task 12):** `roll_pipeline.queue_roll_for_approval` passes `defensive=True`, which skips the ROC/annualized-yield tests and instead requires a `monitor.roll_defensive.min_delta_reduction` cut in \|delta\| within a bounded `max_debit`. |
| **Live limit-order repricing** | **Built (Phase 4 + C5), default OFF.** `order_builder.reprice_limit` + chase loops in all three execution paths: (1) entry SELL in `executor.execute_candidate` steps toward the bid (floor: `min_live_premium_ratio × approved premium`); (2) buy-to-close BUY in `position_manager.close_short_position` steps toward the ask; (3) roll BAG combo in `roll_executor.execute_roll` re-fetches per-leg bid/ask, recomputes the live net credit, and steps the BAG net-limit toward market (ceiling: `min_live_premium_ratio × approved credit`). All three gated by `execution.reprice_enabled` (false by default) — the `placeOrder` amend is unverified on a live account (D7 — Q2 of `docs/live-validation-2026-08.md`, not yet run); see the live-verification list below. |
| **Unreachable quiet-cycle heartbeat (removed)** | `format_quiet_cycle` / `_send_quiet_heartbeat` could never fire in production: `send_candidates` and `send_buy_list` both return `True` on their *empty* path, so `if not cand_sent and not buy_sent` was never true. Only the mocked tests (which stubbed the return to `False`) ever exercised it. Rather than resurrect it — which would mean two messages per quiet cycle, exactly the flood S6 removed — the heartbeat, `ScanResult.quiet_cycle`, and the likewise orphaned `format_screen_empty` were deleted, and the materiality detail it carried (originally "N/M names moved <0.5%"; reworded 2026-08-27 to "N/M names moved too little" once three different thresholds applied — see the S1 row) now rides on the empty-screen diagnostic that is actually appended. |
| **`BuyCandidate.rationale`** | A deterministic one-liner built from the screen's own signals (IV richness, VRP, regime, quality, earnings proximity) in `buy_candidates.py` — Claude does **not** review buy-to-own names (only option candidates), by design. The buy-to-own screen applies a score floor + count cap (`scoring_weights.yaml → buy_to_own`, currently 10 names max). The Telegram message (`format_buy_list`) groups candidates by sector (indexes, tech, semis, financials, healthcare, …); all candidate cards are shown inline — the Telegram spoiler wrapping that previously hid each sector behind a "tap to reveal" toggle has been removed. Sectors are sourced from `universe.yaml → sectors` via the `BuyCandidate.sector` field. |
| **yfinance caching** | **Built, then upgraded to an incremental store.** Daily OHLCV (the 1y history for RSI/MACD/SMAs/ATR/support-resistance/regime **and** HV30) is persisted in the `price_history` table and loaded by `analytics/price_data.get_ohlcv`, which fetches **only the missing tail** from yfinance (or a full year when the store is empty) and is itself `@daily_cached` per calendar day in-process. So scans no longer pull full per-symbol histories every run — steady state makes zero yfinance history calls (the store is current); the 15-min loop reuses the day cache; and a cold process reads settled bars from SQLite instead of re-downloading a year. Seeded by `scripts/backfill_prices.py`, kept fresh by the EOD daily-bar append (mirrors the `iv_history` N4 pattern). `get_fundamental_stats` remains `@daily_cached`. Composite sentiment sources (`sentiment._fetch_stocktwits`, `_fetch_news`, `fetch_sentiment`) are each `@daily_cached` too (S4): each API is hit at most once per calendar day per symbol instead of ~26×/session. VIX is still fetched once per scan (cheap, moves intraday). `TechnicalStats.price` is NOT cached — `technicals._fetch_last_price` makes a separate, uncached `fast_info["lastPrice"]` lookup overlaid as today's bar so the scan-time spot price (N17) stays current; on error it falls back to the last settled close. |
| **Scan spot-snapshot + per-batch sleeps (S3/S7)** | **Optimized (Phase 1); OI-wait bug fixed 2026-08-14.** The async chain fetch no longer issues a dedicated `reqMktData(snapshot=True)` + 2s `quote_sleep_seconds` per symbol when a cached daily close exists: `_resolve_spot_async` centres the strike band on `price_data.get_ohlcv`'s latest close and only falls back to the live snapshot (the `46a21bf` no-tick chain, preserved) for symbols without one. Per-batch quote waits and the fallback spot wait are **event-driven** (`_await_ready`), bounded by the old fixed wait as a *ceiling*. **`_quote_ready` originally only waited for bid/ask** — since the batch also requests generic tick `101` (open interest), which typically streams in *after* bid/ask, this let a batch cancel its line before OI ever arrived, leaving `open_interest` `None` on most quotes; `passes_liquidity_gates` treats a missing OI as an automatic fail, so this was silently rejecting ~97% of quotes as "illiquid" universe-wide (even AAPL/SPY/META) — see the 2026-08-14 session investigation. Fixed: `_quote_ready(ticker, right=...)` now also waits for that side's OI tick, still bounded by the same ceiling — a well-behaved batch still returns early once both bid/ask and OI arrive, otherwise it uses the full ceiling instead of racing ahead at ~0.2–0.5s. Greeks are still not blocked on (absent on delayed/paper data; the Black-Scholes fallback fills them). Cancel-between-batches line-cap discipline is unchanged. The yfinance greeks double-fetch (S2) is a separate, later phase of `SCAN_EFFICIENCY_PLAN.md`. |
| **Intraday materiality gate (S1/S10)** | **Built (Phase 2); extended 2026-08-27, corrected 2026-08-28.** The 15-min loop calls `run_scan(intraday=True)`, which gates the dominant per-symbol option-chain fetch via `_compute_material_symbols`. As of 2026-08-27, three separate thresholds apply instead of one: **held stock positions** are fetched only once their live `fast_info` spot has *risen* ≥ `market_data.held_position_move_pct` (default 2%, **directional — up only**) from their last-fetch baseline — previously unconditional every cycle regardless of direction, which was the single biggest fixed IBKR chain-fetch cost in the loop; up-only because a new CC candidate needs the room a rally creates (a drop doesn't open one), and existing-position risk (delta drift, assignment, rolls) is handled continuously by the separate event-driven monitor (`src/monitor/intraday.py`), not this gate — a dropping held name is still caught by the per-symbol staleness check below; **`actively_wheeling`** names (`universe.yaml`, the core rotation) are fetched once they drift ≥ `market_data.intraday_rescan_move_pct` (default 0.5%), same as before; **`would_own`-but-not-`actively_wheeling`** ("dip-watch") names are fetched only once their spot *drops* ≥ `market_data.dip_pull_in_pct` (default 3%, directional — a rally never counts, since it's never a CSP entry signal for a name outside the core rotation) — and dip-watch names are excluded from the periodic full-sweep safety net entirely. **The bucket rules are UNIONed, not selected between (2026-08-28):** a symbol in more than one bucket is tested against every rule that applies to it and any one firing is enough, so holding shares can never *reduce* a name's coverage — it only adds the rally trigger. (The old `if held / elif dip_watch / else` chain let `held` win outright, which silently demoted every held `actively_wheeling` name from the 0.5% either-way gate to 2%-up-only, shrinking the core rotation to just the names the operator didn't hold; the CSP screen runs for every `would_own` name regardless of holding, so a held wheel name has a live CSP reason to refetch on a dip that the CC-oriented held rule cannot see.) Each fetched symbol also records **its own** fetch timestamp rather than one shared run-level stamp, so a long sweep's cohort goes stale spread over the span the sweep took instead of all inside one later cycle — a burst longer than `intraday_loop_minutes` overruns the cycle and costs the next one. A per-cycle ceiling, `market_data.chain_fetch_budget_seconds` (600s, 2026-08-28), caps how long one cycle may spend fetching chains: the gate's filtering collapses when correlation goes to 1 (a broad sell-off makes every `would_own` name material at once, ~23 min of fetching inside a 15-min cycle), and an overrun sets `scan_running`, skipping the NEXT cycle's scan outright. Over-budget symbols are demoted to immaterial (analytics still run) and carried in `ScanResult.unreached_symbols` to the next cycle's `must_include_symbols`, where `_fetch_priority` ranks them first — so a cluster drains over consecutive on-time cycles. Spending order is retry > cleared-floor > movers by multiple of their own bar (`_move_ratio`, the same function the gate uses as its boolean, so the two cannot drift) > staleness-only. Sized from a measured fit, `duration = 56s + 29.9s x fetches`: 900 - 56 - 150 (`symbol_timeout_seconds` of un-preemptable overshoot) = 694, rounded down to 600. Never applies to a manual /scan. **Spot-baseline guard (2026-08-28):** the OTM-only chain builder removed every both-rights strike, making put-call parity structurally impossible, so `infer_spot_from_quotes` silently fell back to a strike-quantized value (~0.8% error on a $150/$2.50-increment name) that flowed into `TechnicalStats.price` and became the materiality baseline — larger than the 0.5% gate it feeds. `require_parity=True` at the two `spot_override` call sites now returns None instead, falling through to the yfinance probe so baseline and probe share one source; `iv.py`'s own distance-ranking callers keep the loose fallback. Names that cleared the score floor last cycle are always material. A `force_full_scan_minutes` timer (default 120, raised from 90 on 2026-08-21) force-fetches an `actively_wheeling`/held name once **its own** last fetch exceeds that many minutes — checked **per symbol** (2026-08-27), not "sweep the whole core together the instant the single stalest name crosses the line": that old rule let one quiet name (e.g. MSFT on a slow week) drag every other `actively_wheeling` name into a synchronized burst together each time. Per-symbol staleness means a name's clock runs from its own last fetch, so frequently-moving names (already refreshing via the move gate) and rarely-moving ones naturally desynchronize — periodic refreshes spread out over time on their own, with no explicit batch/rotation schedule needed to get that effect. Dip-watch is never covered by this timer. The very first cycle (no baselines) sweeps everything; separately, `_intraday_scan_loop` also forces an unconditional full sweep on the first cycle it spawns after every process start (`bot_data["startup_full_sweep_done"]`), regardless of that timer — see "Bugs fixed (2026-08-21…)" below. Immaterial names skip the chain fetch (analytics still run for every name in `would_own` ∪ holdings, so the buy-to-own list stays complete); the `fast_info` price fetched by the materiality probe is also reused as `get_technical_stats`'s `cached_yf_price`, so an immaterial symbol's analytics don't pay for a second identical yfinance quote. The per-symbol baseline (`last_spot`/`last_scanned_at`/`cleared_floor`) lives in the `scan_state` table (`storage/scan_state.py`), written for every fetched symbol — the first intraday cycle (no baselines) sweeps actively_wheeling ∪ held names and seeds the gate. **Dip_watch seed-only at startup / manual /scan (2026-08-28):** the full-sweep path (the first cycle since process start, and manual `/scan`) no longer unconditionally chain-fetches dip_watch names. Each gets a yfinance probe; names that gapped ≥3% overnight (bidirectional — a gap-up is a legitimate CSP setup at the open via IV expansion / news; a gap-down is the dip rule) are fetched; quiet names and names with no persisted baseline (first-ever run) are seed-only — the probe price is persisted as `last_spot` with `last_scanned_at=NULL`, so the per-cycle rule (c) drop gate works from cycle 1 onward against a yfinance-sourced baseline, with no IBKR/yfinance mismatch. Manual `/scan` leaves `intraday=False` and runs the same full-sweep path; `/scan TICKER` still force-fetches a single named ticker on demand. The store is best-effort: a read/write failure degrades to "treat as material" (full fetch), never a wrong decision. |
| **LLM-skip + output suppression (S5/S6)** | **Built (Phase 4).** Both apply only to `run_scan(intraday=True)` (the 15-min loop); manual `/scan` always reviews fresh and sends in full. **S5:** `_candidates_review_hash` hashes the top candidates' `candidate_id` + signal vectors; when unchanged from the prior cycle (`last_review_hash` system setting) the `claude -p` subprocess is skipped and the persisted `ClaudeReview`s are reused via `_load_prior_reviews`. Enrichment-only — the risk gate already ran, so it never affects gating (the fence; `test_skills_never_reach_the_engine` stays green). **S6:** `send_candidates` collapses a CC/CSP candidate that still has a live, same-score-band PENDING approval into one compact "unchanged" digest (its original card buttons stay actionable), and `send_buy_list` replaces an unchanged buy-to-own screen with a one-line "unchanged since HH:MM" digest — cutting ~26 near-identical card/buy-list blasts/day to one small digest on quiet cycles. **Buy-to-own sent once per day (2026-08-28):** on top of S6, `_intraday_scan_loop` now forwards `include_buy_list=True` into `run_scan` only on the first cycle each ET calendar day that completes cleanly — `send_scan_results` skips the `send_buy_list` call entirely on every other cycle that day (the screen is still scored every cycle; only the Telegram send is gated). A cycle that errors, aborts, or loses the scan lease doesn't mark the day "done," so the gate retries next cycle rather than silently skipping the day. Manual `/scan` is unaffected (`include_buy_list` defaults `True`). An intraday cycle that surfaces *nothing* is still not silent: `send_candidates` appends a timestamped `[HH:MM] … no candidates this cycle <reason>` line plus the closest near-miss to the thread's persisted status message, and the reason now carries the materiality clause ("N/M names moved too little (chain re-fetch skipped)" — reworded 2026-08-27, see the S1 row above for why no single percentage applies any more). A separate `format_quiet_cycle` heartbeat existed for this but could never fire — both send functions return `True` on their empty path — and has been removed rather than resurrected (see "Unreachable quiet-cycle heartbeat" above). |
| **Scan observability + band cap (S8/S9)** | **Built (Phase 5).** **S9:** when the intraday loop loses a cycle to an overrun (prior scan still running) or scan-lease contention, `_note_intraday_skip` increments a per-session skipped counter and sends a throttled (≤ once/30 min) Telegram warning; successful cycles increment a run counter, and both are shown in `/status` (`format_status` `scans_run`/`scans_skipped`) so intended (~26) vs actual is visible. **S8:** the IV-scaled strike band is now clamped to `[strike_band_pct, strike_band_max_pct]` (default cap 0.40) in `_strike_band_pct`, so an extreme-IV ETF can't generate a runaway qualified-strike/batch count; an explicit per-symbol override is exempt. A config validator rejects a cap below the floor. |
| **Telegram multi-thread routing** | **Complete. Phases 1–11 ✅.** Phases 1–9 (thread IDs, formatters, per-thread routing, LLM-skip integration, S6 suppression, premarket snapshot, system_settings keys, doc sweep, test stubs) are complete as previously documented. **Phase 10 (accumulated status messages):** "no candidates" and "unchanged" quiet cycles now *append* a `[HH:MM] …` timestamped line to a single persisted Telegram message (edited in-place via `_append_status`) instead of replacing it — so 4 quiet cycles in a row build a tidy timestamped log in one message rather than 4 separate messages. Body text is stored alongside the message-id in a `{key}_body` system_settings key; when the body exceeds 3800 chars the slate is wiped. A real candidate/buy-list send clears both keys so the next quiet cycle starts a fresh message. The old `_edit_or_send` is replaced by `_append_status`. **New-day rollover (2026-08-28):** the same wipe-and-resend now also triggers on the first quiet cycle of a new ET calendar day (tracked in a `{key}_date` system_settings key), regardless of body length, so a quiet cycle on a new trading day always starts its own message rather than appending to a message left over from a previous day — applies to all three screens (CC, CSP, buy-to-own) since they share `_append_status`. **Phase 11 (order notifications to topic 58):** `send_order_notification` in `sender.py` and `format_order_notification` in `formatters.py` send/edit plain-text order-status messages to `telegram_thread_account` (topic 58); each order gets one persistent message keyed by `order_notification_{order_id}_msg_id`. `executor.py` calls it on order placed, filled, live re-gate failure, IB rejection, and timeout; `approval.py` calls it for TTL-expiry, re-validation failure, and daily-trade-cap cancellations. The intraday scan loop calls `_update_pending_order_notifications` after each scan to push live underlying-price and option-mid updates to every SUBMITTED order's thread-58 message. |
| **Ledger assignment detection** | **Auto-detected (Phase 4).** The EOD run diffs the prior day's position snapshot (`position_snapshots` table) against current positions: a vanished short whose underlying stock moved ~100×contracts in the assignment direction is flagged `assigned` and fed to `reconcile(assigned_candidate_ids=…)` (`src/claude/eval/assignment.py`). The manual `scripts.reconcile_outcomes --assigned <id>` override still exists for corrections. Two residuals remain: (a) the `assigned` realized P&L is the option-leg premium only — stock-leg P&L is still not modelled in the ledger; (b) covered-call assignment needs a prior snapshot showing the held shares, so it isn't detected on the very first EOD run before any snapshot exists. |
| **Backtesting engine** | **Built (Phase 4); v2 added (N21); C10/C11 added (Competitive Phase 5).** `src/backtest/` simulates CC/CSP income over historical prices. **v1** synthesises premiums with Black-Scholes from trailing 30-day HV (a fair-value IV proxy → expected edge ≈ 0 by construction — it validates plumbing, not the edge). **v2** (`--use-stored-iv`) prices the entry premium from the symbol's stored daily IV (`iv_history`), so the run measures the variance-risk premium (IV−HV, reported as `mean_vrp_pct`); `--profit-take 0.5` simulates the 50% take rule and `--min-iv-rank` gates entries by IV rank, so the strategy hypothesis can be tested with/without gating. Reports premium, net P&L, win/assignment/profit-take rate, return on capital, annualized, buy-&-hold benchmark, and max drawdown via `scripts.backtest`. **C10** `src/backtest/earnings.py` adds earnings-cycle segmentation: `simulate_earnings_cycles` segments the price series by historical earnings dates (loaded via `data.load_earnings_dates` from yfinance), evaluates the strategy across each inter-earnings window (gating when the window is too narrow for the DTE), and optionally adds a vol-crush follow-on entry right after earnings. **C11** `scripts/backtest_candidate.py` adds an on-demand per-candidate CLI: `--compact` outputs a 4-line summary suitable for Claude injection; `--earnings` enables the earnings-cycle mode. **Phase 6** extracted the reusable core into `src/backtest/on_demand.py` (`params_from_candidate`, `run_backtest`, `summarize`, `backtest_candidate`) — the CLI is now a thin wrapper, and the **Claude-invocable action** is delivered: `strategist.build_prompt` injects a per-candidate backtest line when `claude.backtest_in_prompt` is enabled (default OFF). `report.compact_report` and `report.format_earnings_cycle_report` are the matching renderers. All still an approximation (no spread/slippage; daily marks for the profit-take walk) and fully isolated from the live broker/risk path (the fence — `on_demand.py` is never imported by `engine/`, `execution/`, or sizing). |
| **Campaign chaining (C6)** | **Built (Competitive Phase 4); cost-basis wired live in Phase 6.** `src/storage/campaigns.py` links each CSP→assignment→CC→roll→close sequence for a symbol into one P&L thread (`CampaignRow`). The executor calls `attach_fill_to_campaign` after every fill, which opens a campaign on the first SELL, appends subsequent fills as legs, and auto-closes when buy quantity equals sell quantity (unless assigned). `mark_campaign_assigned(symbol, assignment_price, right)` sets `assigned=True` and computes `adjusted_cost_basis = assignment_price − net_premium/100` per share for share-acquiring (put) assignments. **Phase 6 closed a gap:** `mark_campaign_assigned` was previously only called in tests, so adjusted cost basis was never populated in production — the EOD reconciler now calls it for each detected assignment (`eval/assignment.assigned_shorts` surfaces the strike). `adjusted_cost_basis` now also feeds the covered-call gate directly (D5, remediation Task 6): `strategies/covered_call.py` reads it via `campaigns.adjusted_cost_basis_for(symbol)` and uses it — falling back to IBKR's raw `avg_cost` when no open assigned campaign exists — for the `min_strike_vs_basis` comparison, collateral, ROC, breakeven, and the ideal-zone cost basis, so the wheel's already-collected premium affects which strikes are writable rather than being visible only on the `/campaigns` and `/campaigns open` Telegram commands, which still display the wheel P&L thread for each symbol. |
| **Phase 5 disk cache** | **Built.** Fundamentals (`src/analytics/fundamentals.py`) and sentiment (`src/analytics/sentiment.py`) are persisted to SQLite via `FundamentalCacheRow` and `SentimentCacheRow` (`src/storage/models.py`) with an earnings-aware TTL. The cache invalidates daily and on proximity to earnings so stale fundamentals do not leak through a blackout. |
| **ML regime detection, vol forecasting, Postgres migration, local-LLM hybrid** | Future ideas, not started. The FMP/Polygon provider swap is now a config change (Phase 2's `src/data/` abstraction), so the data-backend half of any future migration is a `config/settings.yaml → data.*` edit plus a new backend implementing the Protocols — not a rewrite of every analytics module. |

---

## Web platform

A read-only research/investing web UI on top of the trading system. Roadmap:
`Web plan/OVERVIEW.md`; design: `Web plan/P0-P1-design.md`.

| Phase | Status |
|---|---|
| **P0 — Foundation** | **Built (M1 complete).** Research config (`config/research.yaml` + `ResearchCfg`), the research database schema (`src/research/store/`, 13 tables, a separate `Base` from the trading DB), the `scripts/run_api.py` entrypoint, the FastAPI app factory, the bearer-auth boundary (`src/api/auth.py`/`deps.py`), the `Sourced`/`Envelope` provenance primitives (`src/api/models/common.py`), the read-only trading-DB engine (SQLite `mode=ro`, `src/api/trading_db.py`), the meta routes (`/health`, `/me`, `/nav`), and the one-way web/trading import-fence test (`tests/test_web_fence.py`, 4 assertions green) are all built and verified end-to-end (`python -m scripts.run_api` serves all three routes; `data/research.db` created with all 13 tables). |
| **P1 — Research tier** | **Built (M2 complete).** The `SymbolDirectoryProvider` Protocol + factory (`src/data/protocols.py`, `src/data/factory.py`), the rate-limited/ETag-aware EDGAR client and directory backend (`src/data/edgar_backend.py`), the symbol-directory ingest (`src/research/ingest/symbols.py` — upserts, preserves enriched columns, never truncates on a failed fetch), `GET /research/search` (`src/api/routers/research.py` — exact/prefix/name-substring ranking), and the research worker process (`scripts/run_research_worker.py`, APScheduler, no IBKR connection/clientId, honest `worker_heartbeat` written only on a successful job and surfaced at `GET /health`) are all built and verified end-to-end — the worker's first run pulled 10,391 real symbols from SEC EDGAR and `GET /research/search` served correct results against them. The Next.js scaffold, dark token system, left rail, and `⌘K` command palette are landed (`web/`; `npm run build`/`lint`/`vitest run` all green, no raw palette class or hex literal outside `globals.css`'s token definitions). |
| **P1 — Fundamentals pipeline** | **Built (M3 complete).** The `FilingsProvider` Protocol + `EdgarFilingsProvider` + `get_filings_provider()` factory (`src/data/protocols.py`, `src/data/edgar_backend.py`, `src/data/factory.py` — `get_company_facts(cik, *, etag=None) -> (dict, str | None)`, ETag-aware so a 304 reuses the cached payload; `EdgarClient` retries 403/429/5xx with `Retry-After`-aware backoff); the canonical line-item → us-gaap concept map and fact parsing (`config/research_concepts.yaml`, `src/research/schemas.py`, `src/research/ingest/concepts.py` — `LineItemSpec`, `load_concept_map`, `parse_facts` (skips malformed entries individually), `resolve_line_item` (pools facts across every alias concept a filer might use for the same
line item, None when no alias matches — see the 2026-09-11 fix note below for why stopping at
the first alias with any facts was wrong), `select_periods` (enforces `kind`, latest-`filed`-wins on ties for restatement precedence), `assert_units_supported` (rejects unsupported units, never coerces)); normalisation + persistence + cache read (`src/research/ingest/fundamentals.py` — `normalize` assembles annual + quarterly `PeriodStatement`s newest-first, unmapped items absent-not-zero; `load_cached_financials` rebuilds from the `financials` table alone — the warm path, no SEC fetch; `ingest_fundamentals` is the cold path, ETag-aware, caches the raw payload with its etag, persists `FinancialRow`s carrying `form` for full cache reconstruction, idempotent on re-ingest); bounded materialisation (`src/research/ingest/materialize.py` — `SectionState`/`MaterializeResult`/`materialize` is **cache-first** (warm view serves from rows, never SEC), a finished ingest is always `READY` with data even on budget overrun (`PENDING` never carries data), `reason` is a fixed user-facing string never `str(exc)`, `enqueue` dedup, `drain_ingest_jobs` with 3-attempt give-up, registered on a 30s `IntervalTrigger` in `jobs.py`); the per-section analysis endpoint (`GET /research/{symbol}` returning `AnalysisResponse` with `Section[NormalizedFinancials]` — 404 only for unknown symbols, slow sections degrade to 200+`reason`); and the ticker page (`web/app/stock/[symbol]/page.tsx`, `web/components/stock/{SectionShell,StatementsTable}.tsx`, `web/lib/format.ts` — `formatMoney`/`formatPeriod`, filing traceability in a `title` attribute (hyphen, not em dash, per web/CLAUDE.md), react-query polling while `pending`, unknown cells carry `.hatch` texture not colour alone, quarterly statements rendered alongside annual). `init_research_db()` (`src/research/store/session.py`) backfills columns a later milestone added to an existing table via `ALTER TABLE ... ADD COLUMN` — `create_all()` alone only creates missing tables, so a `data/research.db` left over from M1/M2 (missing `financials.form` and `company_facts_raw.etag`) 500'd on `GET /research/{symbol}` until this was added; covered by `tests/test_research_store.py::test_init_backfills_a_column_a_later_milestone_added`. All green: `python -m pytest -q` (1378 passed), `ruff check .`, `mypy src`, `cd web && npx vitest run && npm run build && npm run lint`. **End-to-end live-SEC verification done**: `GET /research/AAPL` served real EDGAR data (5 annual + 8 quarterly periods, latest revenue $416.2B FY2025) and `/stock/AAPL` rendered it with working hover traceability; `GET /research/SPY` / `/stock/SPY` correctly rendered `unavailable` with "No XBRL financial statements filed for this symbol" (ETFs have no XBRL). |
| **P1 — Prices, technicals, news, sentiment** | **Built (M4 complete).** The `BulkPriceProvider` Protocol + `YFinanceBulkPriceProvider` + `get_bulk_price_provider()` factory (`src/data/protocols.py`, `src/data/yfinance_backend.py`, `src/data/factory.py` — the 4.1 licence check ruled stooq out — its CSV endpoint now sits behind a JS bot-verification challenge and a CAPTCHA-gated API key, unusable for unattended access, see `docs/web/data-sources.md`, checked 2026-09-04 — so yfinance is the cold tier's only backend). Daily-bars ingest (`src/research/ingest/prices.py` — upserts on `(symbol, date)`, never truncates on a failed fetch). Delayed intraday quotes for the warm tier (`src/research/ingest/quotes.py` — `warm_symbols()` = watchlisted + recently viewed (7d), `refresh_quotes()` guarded by `is_rth`, registered on a 15-min `IntervalTrigger` in `jobs.py`). News ingest (`src/research/ingest/news.py` — handles both yfinance shapes, VADER-scored, upserts on `(symbol, url)`). **Nightly warm-tier refresh wired 2026-09-08 (a P0-P1 audit finding):** the M4 build registered only the 15-min quote job — `ingest_daily_bars` and `ingest_news` had no production caller, so `daily_bars` held only manually seeded AAPL rows and every other ticker's chart was empty. `refresh_warm_tier` (in `quotes.py`) now runs both nightly at `research.tiers.warm_refresh_hour_et` (default 04:00 ET) for every warm symbol, per-symbol failure isolation; `directory_refresh_days` is consumed too (the default 7 maps to the Sunday 03:00 cron, any other value becomes an interval). Enrichment sections in `materialize.py` (`_technicals`/`_sentiment`/`_news`/`_quote` each guarded by `_section()` so one outage cannot cascade; sentiment is enrichment-tier and never an input to deterministic sections — a structural test guards this). The bars endpoint (`GET /research/{symbol}/bars?range=1y` — `BarsResponse` with `time`/`open`/`high`/`low`/`close`/`volume` in lightweight-charts' field names, server-side SMA 50/200). `AnalysisResponse` extended with `technicals`/`sentiment`/`news`/`quote` (`Sourced[float]`, stale after 30 min). Per-provider circuit breakers (`src/data/breaker.py` — consecutive-failure, `CircuitBreaker`/`get_breaker`/`breaker_states`, wired into `EdgarClient` and both yfinance providers; an open breaker returns the documented empty value without a network call, the affected section renders `UNAVAILABLE`, and `/health` reports `degraded` with `providers: {edgar: "closed", ...}`). Web: `PriceChart` (lightweight-charts candlestick + volume histogram, SMA 50/200 overlays, semantic colour tokens read from CSS, no entry animation), `TechnicalsPanel` (RSI/MACD/SMA/ATR + phase/regime badges, `null` renders `n/a` never `0`), `NewsPanel` (newest-first — enforced by an explicit sort in `ingest/news.py`, since the provider's own ordering isn't a documented contract; relative age via `lib/format.ts`'s `relativeAge`, `rel="noopener noreferrer"`, per-item sentiment chip with label+tint not colour-only), `SentimentPanel` (composite score, label, 1d delta, per-source sample counts — a source with no tracked count, e.g. Reddit, renders `n/a samples`, never a fabricated `0`). All panels wrapped in `SectionShell`; `<PriceChart/>` is not gated behind any section's state (it fetches `/bars` independently, so a technicals outage can't hide it). `page.tsx` shows the delayed quote (price, age, a `text-unknown` "delayed" tag once stale) beside the header and polls while *any* of fundamentals/technicals/sentiment/news is pending, not just fundamentals. **Post-implementation review** (of an earlier pass that covered Tasks 4.2–4.7 without 4.1) found and fixed: the `/bars` SMA200 was computed only from bars inside the display window, leaving most of a 1y chart's SMA200 null — fixed with a 400-day seed-buffer fetch computed-then-sliced (`src/api/routers/research.py`), which also needed `yfinance_backend.py`'s `_period_for_lookback` extended past its former 365-day/`"1y"` ceiling so `BulkPriceProvider`'s documented 400-day default lookback is actually honoured, not silently truncated; the quote's `Sourced.as_of` was stamped with request time instead of the `QuoteRow`'s own capture time, making `stale` always `False` — fixed by threading `quote_as_of` through `MaterializeResult`; naive `as_of` datetimes were normalised for the staleness *comparison* but not the *stored* value, so a browser's `Date` parser silently misread a delayed quote's age by the viewer's UTC offset — fixed in `Sourced.of` (`src/api/models/common.py`); nothing ever wrote `RecentlyViewedRow`, so the warm tier's "recently viewed" half was permanently empty — fixed by recording a view on every `GET /research/{symbol}`. All green: `python -m pytest -q` (1423 passed), `ruff check .`, `mypy src`, `cd web && npx vitest run` (38 passed) `&& npm run build && npm run lint`. `web/lib/api-types.ts` generated from the live `/openapi.json`. **Live end-to-end browser verification done** (Playwright, `/stock/AAPL` against the real API + a real ingested `daily_bars`/fundamentals/news/sentiment payload): candlesticks render with SMA 50/200 visible across nearly the full year, technicals/fundamentals/sentiment/news all populate with real data, a manually-seeded 45-minute-old quote correctly displayed "$228.90 · 46m ago · delayed". |
| **P1 — Checks engine (M5, complete 2026-09-05)** | The check catalogue (`config/research_checks.yaml`, 40 checks across 7 categories — value/growth/past/health/dividend for stocks, fund for ETFs, options for both) loaded by `src/research/checks/definitions.py` (`CheckOp`, `CheckDef`, `load_checks`, `checks_for`). The engine (`src/research/checks/engine.py` — `CheckState` PASS/FAIL/UNKNOWN/NOT_APPLICABLE, `CheckResult`, `CategoryScore`, `evaluate`, `summarize`) — `UNKNOWN` is never coerced to `FAIL`, `NOT_APPLICABLE` means the question does not apply (fundamental categories against an ETF), and category scores carry `evaluable` alongside `total` so the UI never reports "3 of 6" when two were unknown. Metric functions (`src/research/checks/metrics.py` — `METRICS` registry + `build_metrics` assembling the flat dict from `NormalizedFinancials` + quote + IV stats + fundamentals; percentage points not fractions; EDGAR-positive capex/dividends; None on zero/negative-sign denominators). ETF leverage warnings (`src/research/checks/warnings.py` — `Warning` model, `warnings_for`; derives the CC-only and deliberate-exception sets from `config/universe.yaml → leveraged_etfs` + `would_own`, no second hard-coded copy). **Task 5.5 (options-income + ETF fund-data sourcing):** `build_metrics` wires `get_iv_stats`/`get_fundamental_stats` (`src/analytics/iv.py`/`fundamentals.py`) into `iv_rank`/`current_iv`/`hv_30`/`vrp_points`; an off-universe symbol with no `iv_history` row gets an all-`None` `IVStats`, so these report `UNKNOWN` honestly rather than a fabricated percentile. `est_monthly_cc_yield_pct` reuses `src.strategies.buy_candidates._est_monthly_cc_yield` (scaled ×100 to percentage points), never reimplements the heuristic. `days_to_earnings` fixed a bug found independently by two review passes: `build_metrics` was reading `FundamentalStats.next_earnings_date`, a field that doesn't exist — the real field is `next_earnings` — so the check could never populate even with real data. ETF fund-metric sourcing (`expense_ratio`/`total_assets`/`avg_volume`/`inception_date`, new fields on `FundamentalStats`, populated in `get_fundamental_stats`'s ETF branch from the same yfinance `info` dict already fetched) was bundled into 5.5 per the Task 5.4 handoff note, since no other task owned it — **needs live verification against a real ETF yfinance pull**: which key (`netExpenseRatio` vs `annualReportExpenseRatio`) and unit (percent vs fraction) the installed yfinance version actually returns has not been confirmed, only handled defensively (see `src/analytics/fundamentals.py::_etf_expense_ratio`). `atm_open_interest`/`atm_spread_pct` remain passthrough-`None` by design — Milestone 6's on-demand options route (`GET /research/{symbol}/options`) still reports these `UNKNOWN` (via `coverage.option_chain: false`), since supplying real values needs a live IBKR option-chain connection in the API process, out of scope for P1. **Task 5.7 (category expansion + wire-up):** `src/research/checks/payload.py` (`ChecksPayload`, `CategoryPayload`, `build_checks_payload`) assembles `evaluate()` + `warnings_for()` into the payload the API and page use — a stock never gets a `fund` category (not even `NOT_APPLICABLE`: the question shouldn't be posed), an ETF gets all seven with the five fundamental categories `NOT_APPLICABLE` and their `note` explaining why. `MaterializeResult.checks`/`checks_state`/`checks_reason` (`src/research/ingest/materialize.py`) follow the same `_section()`-guarded (data, state, reason) contract as technicals/sentiment/news. `checks: Section[ChecksPayload]` on `AnalysisResponse`, populated in `GET /research/{symbol}` (`src/api/routers/research.py`). Web: `CheckRibbon` (`web/components/checks/CheckRibbon.tsx` — segments carry `data-state` not colour alone, `role="img"` + `aria-label`, score line reads "X of {evaluable}" never "X of {total}", `notApplicable` renders a dimmed track), `ChecksSection` (click-to-expand `<button aria-expanded>` per category ribbon, renders `Warning`s), `CheckRow` (statement + actual + threshold + state; `UNKNOWN` renders `actual` as `n/a` in `text-unknown`, never `0`), wired into `/stock/[symbol]` as the first section below the price chart. Full catalogue with every threshold and its rationale: `docs/web/checks.md`. All gates green: `python -m pytest -q` (1523 passed), `ruff check .`, `mypy src`, `cd web && npx vitest run` (56 passed) `&& npm run build && npm run lint`. See `Web plan/milestones/P0-P1/M5-checks.md` for the full implementation log. |
| **P1 — Options lens, recommendations, sector cards, watchlist (M6, complete 2026-09-05)** | The site starts doing the Telegram buy-list card's job. **Persistence (Task 6.1):** `BuyCandidateRow` (`src/storage/models.py`) + `src/storage/buy_candidates.py` (`save_buy_candidates`/`latest_buy_candidates`/`latest_buy_candidates_from`) — the orchestrator persists `generate_buy_candidates`'s output at both call sites (`src/orchestrator/scan.py:1403` full scan, under `result.run_id`; `:1943` single-ticker `/scan TICKER`, under a `scan-{ticker}-{timestamp}` run id that `latest_buy_candidates`/`latest_buy_candidates_from` filter out — a `/scan NVDA` cannot displace the full-scan list). Display-only: nothing reads a row back into a gate, score, or sizing decision. **`GET /research/recommendations`** (Task 6.2) reads it back through the read-only trading engine (§4.3) with no re-scoring — a test asserts the returned scores equal the stored scores exactly, so the site and Telegram can never disagree. **`GET /research/{symbol}/options`** (Task 6.3) is the on-demand options-income lens: a universe symbol (one of `universe.yaml`'s four lists, the ~40-name "hot" tier) gets real `iv_rank`/`vrp_points` from read-only replicas of `analytics/iv.py`'s rank and HV30 formulas against `iv_history`/`price_history`; an off-universe ("cold") symbol with no history gets the same shape `UNKNOWN` rather than a percentile invented from a short series. Reuses the existing `checks/metrics.py::build_metrics` + `checks/payload.py::build_checks_payload` unmodified — only new, read-only inputs, not new metric/check code — and returns just the `options` category's checks plus leverage warnings (Task 5.4). `coverage.option_chain` is always `false` in P1 (no IBKR connection in the API process). **`GET /research/sectors`** (Task 6.4) aggregates `universe.yaml → sectors` membership: `change_pct` is `null` (never `0`) for a sector with no priced members, `avg_iv_rank` averages only members with real IV history and carries the contributing count, cards order by `avg_iv_rank` descending. **`GET /watchlist` + POST/DELETE** (Task 6.5) is user-scoped (`user_id`, default `"owner"`; a second user's items are never returned), idempotent (repeat POST is 200 not 201, repeat DELETE is 204), 404s an unknown symbol rather than creating an unresolvable row, and promotes an added symbol to the warm tier immediately. **`GET /universe`** (Task 6.6, §4.6) is read-only in P1 (`editable: false` — the client cannot render an edit affordance with no write path behind it); every `universe.yaml` list returns unmodified, in file order. Web: `web/components/home/{SectorGrid,SectorCard,WatchlistTable}.tsx`, `web/app/universe/page.tsx`, landing page (`web/app/page.tsx`) composes search → watchlist → sector grid. A verification pass (Sonnet) over the GLM-implemented tasks (6.2/6.4/6.5/6.6) found and fixed three real defects: `computed_at` on `/recommendations` could be re-stamped by a single-ticker scan (fixed by filtering `scan-`-prefixed runs out of that query too, matching the candidates-list filter); the watchlist's `next_earnings` was hardcoded `None` instead of reading `FundamentalCacheRow`; and a sector-ordering test was vacuously true (its assertion body was guarded by a condition that never fired). All six gates green: `python -m pytest -q` (1580 passed), `ruff check .`, `mypy src`, `cd web && npx vitest run` (62 passed) `&& npm run build && npm run lint`. **Not built:** a frontend surface for the options lens (Task 6.3 is backend-only per the milestone plan — no ticker-page "options" tab wired up yet); the `universe_overrides` write path (P2). `format_buy_list` is untouched — the site runs in parallel with the Telegram card for two weeks before any cutover. See `Web plan/milestones/P0-P1/M6-options-recommendations.md` for the full implementation log and every ruling made along the way. |
| **P1 — AI summary (M7, complete 2026-09-05)** | A pluggable AI backend writes narrative over the numbers the deterministic layer already computed, and influences nothing. Built jointly: GLM took 7.3/7.4/7.6/7.7 plus a minimal 7.1/7.2 interface those tasks import; Sonnet hardened 7.1/7.2 to the full spec, fixed a real gap where 7.2's `claude_cli` backend had grown a second CLI invoker, and landed the spec's exact fence tests (7.5). **Provider protocol + context builder (Task 7.1):** `src/research/summary/protocol.py` (`Summary` Pydantic model + `SummaryProvider` Protocol), `src/research/summary/context.py` (`ResearchContext` + `build_context` — carries computed values only, never asks the model to calculate; `UNKNOWN` checks preserved as `UNKNOWN`; `caveats` always carries the quantitative limit). Tests in `tests/test_summary_context.py` (5 spec assertions, dedicated fixtures). **Claude CLI backend + shared prompt (Task 7.2):** `src/research/summary/prompt.py` (`build_prompt` — the contract: every number must appear in the context, never calculate, never recommend a trade, output strict JSON) and `src/research/summary/claude_cli.py` (`parse_summary` — shared across every backend, tolerates JSON wrapped in prose/fenced blocks, returns `None` on any failure). `ClaudeCliSummaryProvider` reuses `src/claude/runner.py`'s `_build_cmd`/`_run_cli` directly (generalised to accept an explicit `cmd`/`timeout_seconds`/`max_retries` so a caller with its own budget — `research.summary.timeout_seconds`, single attempt — need not duplicate the subprocess/retry/cost-logging loop; the two existing callers, roll review and the EOD journal, are unaffected since the new parameters default to the prior `claude.*`-config behaviour). Tests in `tests/test_summary_claude_cli.py` (6 spec assertions + 3 regression tests pinning the runner reuse, cost logging, and no-retry behaviour). **Three transport backends (Task 7.3):** `src/research/summary/anthropic.py` (Anthropic Messages API via `httpx`, no SDK dependency), `src/research/summary/openai.py` (OpenAI Chat Completions via `httpx`, `response_format: json_object`), `src/research/summary/ollama.py` (reuses the same `claude.ollama_*` config as `src/claude/ollama_runner.py`, not a second copy). Each fails soft: missing API key logs once and returns `None`; timeout/malformed response returns `None` (code-verified for all three backends; test coverage of the timeout/malformed case is uneven across backends — anthropic has no timeout test, openai has no timeout/malformed test, ollama has no malformed test — a minor gap, not a behaviour gap). The prompt and parser are genuinely shared — identical model output yields identical `Summary` across backends. New secrets `ANTHROPIC_API_KEY`/`OPENAI_API_KEY` added to `Secrets` (`src/common/config.py`) and `.env.example`. **Caching + on-demand trigger (Task 7.4):** `src/research/summary/service.py` (`summary_for` + `cached_summary_for` + `is_watchlisted`) — cache key `(symbol, model, prompt_hash, data_as_of)`, a changed `data_as_of` misses, a row older than `research.summary.cache_ttl_hours` is `stale`. `GET /research/{symbol}/summary` calls `cached_summary_for` first: on a hit or stale row it returns the cached summary with **no `materialize` call, no model call, no fetch**; on a miss it returns `unavailable` with a reason (still no fetch). `POST /research/{symbol}/summary` generates and caches on demand, fail-soft to `pending`. The provider's self-reported `Summary.model` (e.g. ollama's `qwen3:8b`) is preserved in the cached payload for attribution even though the cache **key**'s `model` is config-derived. **Summary panel (Task 7.6):** `web/components/stock/SummaryPanel.tsx` — no cached summary shows one line of text + a Generate button (no decorative icon circle, per the banned template); while generating the button is disabled with a loading state; a rendered summary shows thesis/bulls/bears/watch/caveats as distinct labelled regions (not one prose blob); an attribution line names the model and `data_as_of` so a stale summary is visibly stale; the caveats region is always rendered when present, never collapsed by default (the quantitative limit is the thing most likely to be papered over by fluent prose); a failed generation shows the reason and leaves the rest of the page untouched. Wired into `/stock/[symbol]` as the last section. **Fence extended (Task 7.5):** the spec's exact four fence tests landed in `tests/test_web_fence.py` — the checks engine and every `engine/`/`execution/`/`strategies` module never import `src.research.summary`, the summary layer never writes to any database but its own, and the recommendations route does not call `generate_buy_candidates`. (The reachability checks use the `src.research.summary` import-path substring rather than the plan's original bare `"summary"` substring — "summary" is already an ordinary word elsewhere in this codebase, e.g. `EODSummary`, `execution/roll_executor.py`'s `_leg_fill_summary` — so the bare form false-positived on code that never touches the AI summary layer.) All gates green: `python -m pytest -q` (1620 passed), `ruff check .`, `mypy src`, `cd web && npx vitest run` (67 passed) `&& npm run build && npm run lint`. `docs/web/openapi.json` and `web/lib/api-types.ts` unchanged by the hardening pass (no public schema or route changed). |
| **P2 — Options console (M1+M2+M3 built 2026-09-06, reviewed; M4 Tasks 4.1+4.2+4.3+4.4 built 2026-09-06; M5 Tasks 5.1+5.2+5.3+5.4 built 2026-09-07; M6 Tasks 6.1+6.2+6.3+6.4 built 2026-09-07; M7 Tasks 7.1-7.7 built 2026-09-07 — P2 complete)** | **M1 — Write foundation:** the intent queue exists, the drain runs with no registered handlers, and no web action can reach an order until M3. `AppCommandRow` (`src/storage/models.py`) + `src/storage/app_commands.py` (enqueue/dedupe/mark/expire helpers); `src/api/models/commands.py` (`CommandKind` enum, typed payloads per kind, `validate_payload`, `dedupe_key_for`, `CommandStatus` — `UniversePayload.list_name` is `Literal["would_own", "watchlist"]` so `sectors`/`leveraged_etfs` fail parsing); `src/api/trading_db.py` gains a write-scoped `get_command_engine` + `command_session` with a `before_flush` listener (`WriteFenceViolation`) that rejects any flush targeting a non-`app_commands` table; `src/api/commands.py` is the only module allowed to import `get_command_engine`/`command_session` (`submit` enqueues, `get_status` reads through the read-only engine, `clear_confirm_token` clears a live-mode token after confirmation); `src/api/routers/commands.py` adds `POST /commands`, `GET /commands/{id}`, `POST /commands/{id}/confirm` (owner-only, dedupe returns 200 not 201, live-mode order-reaching intents get a `confirm_token`); `src/notify/command_drain.py` + `_command_drain_loop` in `approval_service` (fails unknown kinds loudly, isolates throwing handlers, skips commands awaiting confirmation, runs with `ib is None`, writes `command_drain_heartbeat` to `system_settings` after every cycle so `/options/controls` can tell a live drain from a dead one); `tests/test_web_fence.py` gains three P2 fence tests (write-handle leak — greps for both `get_command_engine` and `command_session`, command writer names no other table, trading path still never imports the web layer); the token proxy (`web/app/api/[...path]/route.ts`) moves `API_TOKEN` server-side — `NEXT_PUBLIC_API_TOKEN` is purged from the repo, the built bundle no longer contains the token. **M2 — Read surfaces:** the console exists and is worth opening, still unable to do anything. `GET /options/approvals` + `/approvals/{id}` (`src/api/routers/options.py`, `src/api/models/options.py`) — a four-table join (approval/candidate/risk-verdict/claude-review) through the read-only engine, snapshot-first when the candidate has been pruned, the five review fields rendered separately never as one blob. `GET /options/assessed` implements the promotable table from spec §5.2 exactly (`risk_gate`/`generator` never promotable), ranked like `scan.py::_rank_assessed`, `limit` caps the total across groups not per symbol. `GET /options/orders`, `/fills`, `/shorts` (nulls stay null — `avg_fill_price`/`mark`/`unrealized_pnl` never fabricate `0`; `shorts.as_of` is the snapshot's capture time, not request time). `GET /options/controls` reads `command_drain_heartbeat` against twice the poll interval — never reuses `/health`'s research-worker heartbeat, defaults to unhealthy, never `true` on a drain that has never run. Web: `web/app/options/page.tsx` + `[approvalId]/page.tsx`, `web/components/options/*` (`ApprovalsList`/`ApprovalCard`, `AssessedBrowser` with stage badges that are never colour-alone, `OrdersTable`/`FillsTable`/`ShortsTable`, `ControlsStrip`, `ApprovalDetail`/`ReviewPanel`/`IdealZoneBar`/`AlternativesTable`) — no approve/reject/promote/roll control anywhere, asserted by a frontend test. The rail flip (`src/api/routers/meta.py`) makes `/options` available. A Sonnet verification pass (2026-09-06) live-browser-tested every tab and the detail page against the real dev stack and found the console **completely unreachable** for reasons outside M1/M2's own code: `web/.env.local` still carried the pre-M1 `NEXT_PUBLIC_API_URL`/`NEXT_PUBLIC_API_TOKEN` names instead of the migrated `API_URL`/`API_TOKEN`, so every proxied request 500'd; and `app_commands` (M1 Task 1.1) had never been created in the real `data/income_system.db` because table creation only runs via the trading daemon's own `init_db()` startup path, which nobody had triggered since the model was added. Both are environment/ops gaps, not code defects, and are now fixed locally (`.env.local` corrected, `init_db()` run once). The pass also found and fixed two real code defects: `GET /options/approvals/{id}` raised `MultipleResultsFound` (500) whenever a candidate had been assessed across more than one scan run — completely ordinary, since `risk_verdicts` stores one row per assessed contract *per run* — fixed by ordering both the verdict and review lookups by `created_at` descending and taking the newest; and `web/app/options/[approvalId]/page.tsx` was missing `"use client"`, crashing on every real navigation to it (masked in tests by the component-level test harness). **None of M1 or M2 had ever been `git commit`ed** despite every task's checklist saying so — this is almost certainly why a later M3 session, working from git-tracked state, concluded the console UI "never landed" even though it existed on disk and worked once the environment gaps above were fixed; see `Web plan/milestones/P2/M3-approve-reject.md`'s correction note. All gates green after the fixes: `python -m pytest -q` (1755 passed), `ruff check .`, `mypy src`, `cd web && npx vitest run` (100 passed) `&& npm run lint && npm run build`, plus a live click-through of every `/options` tab and an approval detail page with zero console errors. **M3 — Approve and reject (built 2026-09-06, opencode/glm-5.3):** the first web action that can cause an order to exist, through the exact Telegram code path. `src/notify/command_drain.py` registers `approve`/`reject` handlers that call `approval_service._process_button` **unchanged** (a monkeypatch test fails if a refactor forks the mutation); an already-decided approval is `applied` neutrally ("Already {status}" in `result.decision`), a replayed drain creates no second order (all four §4.5 idempotency layers hold, asserted in `tests/test_drain_approve_reject.py`), and neither handler needs `ib` — TWS down still queues the order. The drain stores a handler's result dict verbatim and gains `CommandFailed(reason, detail)` for machine-readable failures. The live-mode second confirmation now fails closed exactly per spec §4.6: a wrong/missing token is **403 and does not clear the field** (`tests/test_live_confirmation.py` covers token creation by kind, the drain's skip, the confirm-then-apply round-trip, the 403/409 split, and the TTL sweep), the outstanding `confirm_token` is surfaced through the owner-only `CommandStatus` so the frontend can complete the round-trip, and confirming a not-awaiting command is 409. `tests/test_write_path_invariants.py` asserts the phase invariants in one place: every `/options`+`/commands` route is owner-gated (globbed via route introspection), no route module imports the write handle, Telegram and the console cannot double-decide an approval into two orders, a crashed drain re-applies exactly once, and the API still holds no `ib_async` import. Web: `web/lib/receipt.ts` (`receiptState` — pending never renders as applied, `submitted` only when an order is working, `filled` only when a fill exists, stalled stated in words), `CommandReceipt` (the §9.2 signature component — intent id always visible, humanised failure reasons, no spinner when stalled), `ConfirmAction` (confirm dialog: exact contract/count, case-sensitive typed-word gate for M6's halt, focus trap + Escape + focus return, aria-modal, reduced-motion entry), `web/lib/commands.ts` (`submitCommand`/`confirmCommand`/`useCommandStatus` polling every 2s while pending, stopping at a terminal state), and `DecideControls` — the shared decide flow on both the approval card and the detail page: confirm dialog before any request, one `POST /commands`, controls disabled while in flight, a decided approval renders its decision not controls, 403 renders a permission message, and in live mode a distinct clearly-labelled second LIVE confirmation (cancelling it leaves the intent queued and unconfirmed, stated in the receipt). The M2 no-action-buttons guards evolved with the milestone: the controls now exist and are asserted wired through the confirm gate. **The existing execution-time `[CONFIRM LIVE]` path is untouched and still fires after a web live approve.** All gates green: `python -m pytest -q` (1776 passed), `ruff check .`, `mypy src`, `cd web && npx vitest run` (130 passed) `&& npm run lint && npm run build`. **M4 — Promote, Tasks 4.1+4.2+4.3+4.4 (built 2026-09-06):** promote is now a real gated action, belt and braces. **Task 4.1 — the API-boundary promotable-stage guard:** `src/api/routers/commands.py`'s `assert_promotable` refuses `POST /commands` for a `promote` before any `app_commands` row exists unless the candidate's most recent `risk_verdicts` row is at `score_floor`/`dedupe`/`top_n` (spec §5.2's promotable table) — `risk_gate`/`generator` are never promotable, `passed` already has an approval, an unknown `candidate_id` is `404`, a non-promotable stage is `409 {"reason": "stage_not_promotable", "stage": ...}`. **Task 4.2 — the drain handler re-prices and re-gates for real:** `src/notify/command_drain.py`'s `promote` handler does not trust the stored row it was asked to promote — it re-runs the single-ticker pricing path (`src.orchestrator.scan._price_and_gate_ticker`, extracted from `run_ticker_scan` as a pure refactor — same chain fetch, analytics, CC/CSP screens, scoring, `validate_candidates` gate, and `record_assessments` audit write, zero behavior change to `run_ticker_scan` itself) for the requested symbol, searches the gate-passed output for the exact `(strategy, strike, expiry)`, and only then calls the new `src/execution/promote_pipeline.py::queue_promoted_for_approval` (mirrors `roll_pipeline.queue_roll_for_approval`'s `has_active_order` guard and `CandidateRow`/`ApprovalRow` upsert, minus the generation half — it takes the fresh `TradeCandidate` directly) to raise a PENDING approval. Nothing from the stored `RiskVerdictRow` reaches the approval except the tuple used to find the fresh match; every number on the approval — including a re-gate that now rejects (`gate_rejected`, reasons surfaced verbatim, by design) — comes from this run. Failure reasons (`broker_unavailable`, `chain_unavailable`, `contract_not_priced`, `gate_rejected`, `score_below_minimum`) are documented verbatim in `docs/web/commands.md`. `drain_once` now awaits a handler's result when it returns one (coroutine handlers, needed for promote's re-scan; every earlier sync handler is unaffected). All gates green: `python -m pytest -q` (1804 passed), `ruff check .`, `mypy src`. **Task 4.3 — the promote control and its receipt in the frontend (built 2026-09-06):** `AssessedBrowser`'s per-contract `<li>` was extracted into its own `web/components/options/AssessedRow.tsx` component (a pure, behavior-preserving extraction — every existing `AssessedBrowser.test.tsx` test kept passing unmodified), which now carries a Promote button rendered only when `promotable` is true and `strike`/`expiry` are both non-null (a promotable row with either unexpectedly null falls through to the non-promotable rendering rather than send `null` to the API). Promoting reuses the M3 decide flow exactly: `ConfirmAction` first (explaining in one sentence that the contract is priced and gated again and an approval appears only if it still passes; a `score_floor` row's dialog additionally shows the blended score and `promote_note`'s configured-minimum text verbatim), then `submitCommand("promote", {candidate_id, symbol, strategy, strike, expiry})` fires once, `useCommandStatus` polls to a terminal state, and `<CommandReceipt/>` renders the outcome unmodified (`order` is always `null` — a promote never has approve/reject's working-order lifecycle) — a live-mode response routes through the same second LIVE confirmation `DecideControls` uses. On `applied`, a "View approval" link to `/options/{approval_id}` renders when `result.approval_id` is non-null. `AssessedBrowser` now also fetches `GET /options/controls` itself (same pattern as `ApprovalsList`) so a promoted row's receipt can state a dead drain in words. All gates green: `python -m pytest -q` (1805 passed), `ruff check .`, `mypy src`, `cd web && npx vitest run` (150 passed) `&& npm run lint && npm run build`. **Task 4.4 — the promote refusal tests (built 2026-09-06):** `tests/test_write_path_invariants.py` gains the belt-and-braces coverage for the whole milestone: `test_no_promote_path_exists_for_a_gate_rejected_contract` enqueues a promote command directly (bypassing Task 4.1's API-boundary guard entirely, the way a malformed or bypassed request would) for a `risk_gate`-staged contract and asserts the drain handler's own re-gate still refuses it; `test_the_promote_handler_runs_the_real_rules_engine` wraps (not mocks) `validate_candidates` with a spy to prove the real Rules Engine is what's called, not a stand-in; `test_promotable_stages_match_the_spec_exactly` pins `PROMOTABLE_STAGES == {"score_floor", "dedupe", "top_n"}` so a future edit that widens it fails here first. **M5 — Roll on demand, Tasks 5.1+5.2+5.3+5.4 (built 2026-09-07, opencode/glm-5.2):** the operator can ask the system to propose a roll for any open short, without waiting for the intraday monitor to fire an alert. Two steps, never one: the console proposes; the operator approves that proposal through M3's path. **Task 5.1 — the `roll_request` drain handler:** `src/notify/command_drain.py`'s `_roll_request` resolves the position from a live `get_positions(ib)` read, fetches a fresh chain + IV/technical stats through `src.execution.roll_pipeline.fetch_roll_inputs` (the shared chain-fetch path extracted from the monitor's `_try_queue_roll`, which was refactored to call it — behavior unchanged; the same three helpers composed inline are now one function two callers share, so the web and the monitor cannot drift on how a roll is priced), and calls `queue_roll_for_approval` **unchanged**. The handler disambiguates the pipeline's `None` **before** calling it: it runs `generate_roll_candidates(..., defensive=True)` itself to derive the same candidates the pipeline will choose from (same function, same inputs, same deterministic ids), and checks `_existing_roll_in_flight` against **every** one of them, not just the top-ranked one (post-M5 verification fix, 2026-09-07 — see "Bug fixed" note below) — covering both an active order (`active_order_for`, the new row-level companion to `has_active_order` in `src/storage/orders.py`) and an existing PENDING approval. Either → `roll_already_working` with `detail.approval_id` so the receipt links to the in-flight proposal; empty/failed chain → `chain_unavailable` with the provider message; no candidates → `no_qualifying_roll`; non-short or absent position → `not_an_open_short` / `position_not_found`; `ib is None` → `broker_unavailable`. The PENDING-approval check is what closes the monitor-vs-web race `has_active_order` alone would miss (the monitor's roll raises a PENDING `ApprovalRow`, no `OrderRow` until approved) — the milestone's headline acceptance criterion ("a monitor alert and a web request produce exactly one approval") requires it. `tests/test_drain_roll.py` carries the nine specified tests (seven from the plan + `position_not_found` + `chain_unavailable`), mocking only the IBKR/network boundary so the real `generate_roll_candidates` economics run. Failure reasons documented verbatim in `docs/web/commands.md`'s roll_request section. **Task 5.4 — roll degradation tests (built 2026-09-07):** `tests/test_write_path_invariants.py` gains three invariants: a behavioral tripwire + source scan proving the handler never reaches `execute_roll` directly (no `roll_executor` import, no `execute_roll(` call in `command_drain.py` or `roll_pipeline.py`); the verbatim token grep proving no `max_debit`/`min_delta_reduction`/`roc_pct` leaked into `command_drain.py`; and a `wraps`-spy on `generate_roll_candidates` at both call sites proving `defensive=True` flows through the handler's pre-check and the pipeline's internal call (the web roll is the monitor's roll). Reuses the `drain_env`/`fake_chain` fixtures from `tests/test_drain_roll.py` the same sanctioned way the file already imports the promote fixtures. **Task 5.2 — the roll control on the shorts list (built 2026-09-07):** `web/components/options/ShortsRow.tsx` extracted from `ShortsTable` (the same extraction `AssessedRow` got from `AssessedBrowser`), carrying the row's cells plus the confirm-then-submit-then-receipt flow that mirrors `AssessedRow`'s promote control exactly. The control is labelled "Propose a roll" (not "Roll" — the button does not roll the position, and the copy says so); `ConfirmAction` states plainly that the system will price a roll, raise it for approval, and nothing executes until that proposal is approved; `submitCommand("roll_request", {position_symbol})` fires once; `useCommandStatus` polls to terminal. `no_qualifying_roll` renders as a plain sentence in a `data-state="answered"` box (no `text-loss` chrome) — special-cased in `ShortsRow` so `CommandReceipt` stays untouched and every existing receipt test stays green. `roll_already_working` renders the failed receipt plus a "View the roll already in flight" link to `result.detail.approval_id`; success renders a "View approval" link to `result.approval_id`. The control is disabled while in flight and wired through the live-mode second confirmation (roll_request is in `_LIVE_CONFIRM_KINDS`). `ShortsTable` now fetches `GET /options/controls` (same pattern as `ApprovalsList`) so a roll receipt can state a dead drain in words; defaults healthy while loading. The M2 "asserts no roll button exists" guard evolved into the roll-control suite (17 tests in `ShortsTable.test.tsx`). **Task 5.3 — roll alerts on the shorts list (built 2026-09-07):** `_TRIGGER_LABELS` + `humanize_trigger` moved from `src/notify/formatters.py` to `src/monitor/triggers.py` (beside the codes they name); `formatters._humanize_trigger` is now an alias import, so every existing formatter caller works unchanged and the identity `formatters._humanize_trigger is triggers.humanize_trigger` is asserted in `tests/test_api_shorts.py`. `RollAlertSummary` gains `trigger_label` (humanised server-side via the shared mapping) and `claude_recommendation` (passed through from `RollAlertRow`, nullable). The API router imports `humanize_trigger` from `src.monitor.triggers` — not the notify layer — so the "API must not pull in the notify layer" fence holds. The web renders `trigger_label` verbatim, the alert age as text via `relativeAge`, and Claude's view labelled "Model opinion (Claude): ..." — distinct from any deterministic number on the row. A position with no alerts renders nothing extra (not "No alerts"). **A Sonnet verification pass (2026-09-07)** checked the opencode/glm-5.2 build against this plan and the live gate (test count, ruff, mypy, vitest, lint, build all reproduced exactly as claimed) and found one real defect in Task 5.1's own new code: `_roll_request` derived the same candidate `queue_roll_for_approval` would pick and checked only that single, top-ranked candidate for an in-flight roll. Under `defensive=True` every candidate's `roc_pct` is hardcoded `0.0` (rolls are judged on risk reduction, not yield, per D4), so `generate_roll_candidates`'s ROC-desc sort is a no-op tie and "the top-ranked candidate" is really just whichever qualifying quote the chain happened to list first — a property of chain order, not economics. Two fetches taken minutes apart (the monitor's, then the web's) can list the same qualifying strikes in a different order, so the monitor's already-PENDING candidate can silently drop to second-or-later without ceasing to qualify — and the handler would then fail to recognise it as in flight, racing the monitor into a second approval for the same position, exactly the case the milestone's headline acceptance criterion exists to prevent. Fixed by checking every one of `generate_roll_candidates`'s qualifying candidates against `_existing_roll_in_flight`, not just `candidates[0]` — bounded to the handful of strikes/expiries one chain fetch returns, so the cost is negligible. Regression test: `tests/test_drain_roll.py::test_an_in_flight_roll_is_caught_even_when_no_longer_top_ranked` (constructs two qualifying candidates whose chain order flips between the monitor's fetch and the web's, and confirms it reproduces the double-approval against the pre-fix code). Also flagged, not fixed (pre-dates M5, lives in `rolling.py`'s N20-era economics, out of scope for a drain-handler fix): the same `roc_pct = 0.0` fact means the monitor's own roll selection has never actually picked the "best" defensive roll by any economic measure, only the first one the chain lists — worth a human look at whether defensive rolls should rank by delta-reduction, liquidity, or credit instead of an always-tied ROC. All gates green after the fix: `python -m pytest -q` (1827 passed), `ruff check .`, `mypy src`, `cd web && npx vitest run` (163 passed) `&& npm run lint && npm run build`. **M6 — Controls, Tasks 6.1+6.2+6.3+6.4 (built 2026-09-07, opencode/glm-5.3):** halt, resume and the autonomy rung are reachable from the browser, with the confirmation weights deliberately asymmetric. **Task 6.1 — the drain handlers:** `src/notify/command_drain.py` registers `halt`/`resume`/`set_autonomy`, thin resolvers over the same `system_settings` helpers Telegram's `/halt`, `/resume`, `/autonomy` use (`set_halted`/`set_autonomy_level` — one halt flag, read through `HALT_KEY`; a token-grep test pins that the literal `execution_halted` never appears in the drain). All three apply with `ib is None`: halting matters most exactly when something is wrong, and "TWS is unreachable" is a common shape of wrong. Halt/resume are idempotent (`applied`, never `failed` — halting an already-halted system satisfies the intent; so does resuming an un-halted one, resolving the M1 doc's `not_halted` failure mode as a satisfied intent instead); an empty halt reason is stored as `"halted from the web console"` so `/status` and the console always say something; `resume` records who released the switch in the command's `result` (`released_by`); each handler sends a Telegram notification — the one place a handler notifies, because control-plane changes have no order-poll loop to report them later, and a halt raised from the browser must be visible wherever the operator is. `set_autonomy` enforces the same promotion evidence gate Telegram does (`promotion_blockers` must be empty, else the command fails with `promotion_refused` + `detail.blockers`) so the web is not the rung ladder's back door; demotion always applies. `tests/test_drain_controls.py` carries 13 tests including the six specified verbatim. **Task 6.2 — payload validation:** `HaltPayload.reason` is capped at 200 chars (`422` past it — the reason is rendered by `/status` and the halt banner, an unbounded string there is a rendering bug waiting to happen), and the empty-payload kinds (`halt`/`resume`/`set_autonomy`/`refresh`) are `extra="forbid"` so a client typo is caught rather than ignored — all at parse time, before a command row exists (asserted). Control kinds carry no `dedupe_key` (M1's convention, pinned) and are never in `_LIVE_CONFIRM_KINDS` — the deliberate asymmetry, stated in a comment at the set so it does not look like an oversight: the live token is for intents that can reach an order, and a halt must never be slowed by a second step (asserted for halt with `cfg.is_live` true). **Task 6.3 — the controls panel:** `web/components/options/HaltControl.tsx` (halt is ONE CLICK, no dialog — speed is the feature, and a test name says so; resume requires the typed word RESUME, disabled until it matches exactly case-sensitively) and `AutonomyControl.tsx` (four rungs rendered from the API's `rungs` array, never hardcoded; a rung change click-through confirms showing current and target rungs; a refused promotion renders `promotion refused` with the blockers through the receipt). `ControlsStrip` now hosts both plus an unmissable halted banner at the top of the console (reason and time as text, fill and text never colour alone; honest "unknown time" when no halt command row exists, e.g. a breaker trip) and a `drain_healthy: false` line stating "the trading service is not draining commands" beside the controls — a queued-but-undraining halt is this milestone's worst case. Both controls disable while their own command is in flight, render `CommandReceipt`, invalidate the controls query on terminal so the strip moves on the next poll, and route a live-mode response through the same second LIVE confirmation (unreachable in practice for these kinds, but the shape is shared). `ConfirmAction`'s docstring corrected: the typed word is used by `resume` in M6, not `halt` (the milestone refined design §9.3's first draft). `GET /options/controls` gains `halted_at`, derived from the most recent applied `halt` command's `applied_at` — the "no new setting keys" rule and the banner's "time it was halted" are reconciled without a new key, and a breaker-tripped halt honestly renders no time rather than a fabricated one. 22 new frontend tests across `HaltControl.test.tsx`, `AutonomyControl.test.tsx`, `ControlsStrip.test.tsx`. **Task 6.4 — controls invariants:** `tests/test_write_path_invariants.py` gains the three specified tests (parametrised every-control-kind-applies-without-a-broker over the reused `drain_env` fixture; `test_control_kinds_never_require_live_confirmation` pinning `_LIVE_CONFIRM_KINDS`; `test_the_halt_key_is_the_same_one_telegram_uses` with the verbatim token grep). All gates green: `python -m pytest -q` (1856 passed), `ruff check .`, `mypy src`, `cd web && npx vitest run` (185 passed) `&& npm run lint && npm run build`. **A Sonnet verification pass (2026-09-07)** checked the opencode/glm-5.3 build against this plan and the live gate (all six commands reproduced exactly as claimed) and found one real defect: `GET /options/controls`' `halted_at` derivation had no lower bound, so a resumed web halt followed by a later, command-row-less halt (a circuit-breaker trip, or a Telegram `/halt` — neither writes an `AppCommandRow`) surfaced the *earlier* halt's timestamp instead of the honest `null` design decision 1 promised for exactly that case; the one existing null-case test only covered a fresh DB with no prior halt rows and never exercised the halt→resume→halt sequence. Fixed by bounding the halt lookup (`routers/options.py::controls`) to applied strictly after the most recent applied `resume` row. Regression test: `tests/test_api_controls.py::test_halted_at_does_not_leak_a_stale_timestamp_from_a_prior_halt_cycle`. All gates green after the fix: `python -m pytest -q` (1857 passed), `ruff check .`, `mypy src` (web gate unaffected, not re-run). **M7 — Universe editing (Tasks 7.1-7.7 built 2026-09-07):** the two soft universe lists — `would_own` and `watchlist` — become editable from the browser, without `sectors` or the risk engine ever becoming reachable from the web. **Task 7.1 — the override store:** `UniverseOverrideRow` (`src/storage/models.py`, unique on `(symbol, list_name)`) holds one row per operator add/remove — upper-cased `symbol`, `action: "add"|"remove"`, `created_by`/`created_at` audit trail; `src/storage/universe_overrides.py`'s `set_override`/`clear_override`/`all_overrides` each take an explicit `session`, and `set_override` is a total-replace upsert — a later call for the same pair overwrites `action`/`created_by`/`created_at` in place, so an add followed by a remove is one row, never two to reconcile at read time. **Task 7.2 — the composer:** `src/common/universe.py::effective_universe()` composes `universe_overrides` onto `config/universe.yaml`, returning a dict shaped exactly like `get_config().universe`. Only `would_own`/`watchlist` are overridable (`OVERRIDABLE_LISTS = frozenset({"would_own", "watchlist"})`); every other key — `sectors`, `strike_bands`, `indexes`, `actively_wheeling`, `leveraged_etfs` — passes through byte-identical, proven even against a stray override row inserted directly under `list_name="sectors"`. A `remove` override on a symbol currently in `actively_wheeling` is ignored when composing `would_own` — you cannot stop being willing to own something you are actively wheeling. An unreadable overrides table falls back to the YAML base untouched and logs a warning; it never raises and never empties the universe. A 60-second TTL cache (a plain `(dict, time.monotonic())` tuple) avoids a DB round-trip on every read; `invalidate_universe_cache()` forces recompute so a web edit is visible immediately in the process that applied it, not up to 60s later. Ordering is deterministic: YAML file order, then added symbols in `created_at` order. **Task 7.3 — six consumers migrated** from `get_config().universe` to `effective_universe()`: `src/strategies/cash_secured_put.py` (the CSP eligibility check — the single most consequential edit in the milestone, proven end-to-end by a test that adds an override and confirms `generate_csp_candidates` actually changes its output), `src/orchestrator/scan.py` (symbol selection), `src/orchestrator/eod_report.py` (two sites — the daily IV-history refresh set and the EOD watchlist report), and `src/api/routers/universe.py` / `routers/research.py` (three read sites across the two files). `src/engine/risk_engine.py`, `src/ibkr/market_data.py`'s `strike_bands`, and every `actively_wheeling`/`sectors` read elsewhere are deliberately untouched — not overridable. An autouse `tests/conftest.py` fixture resets the TTL cache around every test. **Task 7.4 — the write path:** `GET /universe` gains `lists: [{name, overridable, entries: [{symbol, overridden, removed, created_by, created_at}]}]` (four lists, `indexes`/`watchlist`/`would_own`/`actively_wheeling`, only the latter two `overridable`) and flips `editable` to `true`; `would_own`/`watchlist` entries are the union of the YAML base and every override row for that list, not just the filtered effective list, so a removed YAML-base symbol stays visible (greyed out) with a revert path. New routes `POST`/`DELETE /universe/{list_name}/{symbol}` (owner-only, thin wrappers over the same command-queue path `POST /commands` uses) narrow `list_name` to `Literal["would_own", "watchlist"]` so any other value is `422` before a command row can exist; an unknown symbol (checked against the research symbol directory) is `404`; removing an `actively_wheeling` symbol specifically from `would_own` is `409`. The drain handlers `_universe_add`/`_universe_remove` (`src/notify/command_drain.py`) call `set_override` — never `clear_override`, since a remove must always record an explicit suppressing row, even for a YAML-base symbol, because deleting the row would silently do nothing for one — then `invalidate_universe_cache()`. Neither handler can fail (all validation already happened at the API boundary) and neither sends a Telegram notification, deliberately — a universe edit is reversible, non-urgent config, unlike halt/resume/set_autonomy. **One fix-loop round, the only one across the whole milestone:** the initial `GET /universe` entries-union silently dropped a genuinely reachable state — a symbol added via override then removed again, leaving a non-base `action="remove"` row — fixed so every override row for a non-base symbol appears in `entries`, tagged `removed = (action == "remove")`. **Task 7.5 — the frontend:** `web/components/universe/{UniverseList,OverrideBadge,AddSymbol}.tsx` and a rewritten `web/app/universe/page.tsx` consume the new shape (`web/lib/commands.ts` gains `submitUniverseCommand`); add/remove controls render only on `would_own`/`watchlist`, with `indexes`/`actively_wheeling` rendered read-only and noted as YAML-managed. Adding to `would_own` opens a confirmation naming the actual consequence — the system may sell cash-secured puts on the symbol and the operator may be assigned its shares; adding to `watchlist` fires immediately with no dialog (a reporting list, never reaches an order). An overridden entry renders `OverrideBadge` (author, timestamp, a revert control that fires the opposite action of the entry's current state). The symbol picker is a typeahead over `GET /research/search`, so a typo cannot become a `404`. Every mutation renders `CommandReceipt` and stops polling at a terminal command status. The wheeling-vs-dip-watch tag the pre-M7 page showed within `would_own` was preserved. **Task 7.6 — the fence:** `tests/test_web_fence.py` gains three tests: no module under `src/claude/eval/` or `src/research/` can write a universe override; `src/engine/risk_engine.py` never mentions `effective_universe`/`universe_overrides` anywhere in its text; `OVERRIDABLE_LISTS == frozenset({"would_own", "watchlist"})` exactly, pinned so a future widening fails here first. All gates green: `python -m pytest -q` (1920 passed), `ruff check .` (clean), `mypy src` (clean), `cd web && npx vitest run` (203 passed) `&& npm run lint && npm run build` (both clean). **Final whole-branch review fix round (2026-09-07), one commit, seven findings:** `universe_add`/`universe_remove` lost their dedupe key in `dedupe_key_for` — a stable `f"{kind}:{list_name}:{symbol}"` key let a later, semantically different request (e.g. the second `remove` in remove→add→remove) dedupe to an earlier request's already-`applied` command row, so the API returned `200`/`applied` while the override table never actually changed; both kinds now join halt/resume/set_autonomy/refresh under `dedupe_key_for(...) is None`, so a repeat POST/DELETE always creates a fresh command (idempotent in effect via the upsert-only handlers, not via dedupe). The generic `POST /commands` route gained the same unknown-symbol `404` check (`src/api/deps.py::assert_known_symbol`, shared with the thin wrappers) the `POST`/`DELETE /universe/{list_name}/{symbol}` routes already had, closing a path that let an owner smuggle an override for a non-existent symbol straight past those wrappers. `GET /universe`'s `removed` field is now derived directly from the override row's `action` plus the `actively_wheeling` guard (matching `_compose_list`'s own guard condition) instead of from `effective_universe()`'s cached composed list — that cache is invalidated only in the exec process that runs the drain, so the API process's own cache instance could read up to 60s stale right after a removal, showing a just-removed symbol as still present with a revert badge that fired the wrong action. `created_at` is now normalized through `routers/options.py`'s `_as_utc` before serializing, so a naive SQLite timestamp doesn't silently render at the wrong relative age in a non-UTC browser. `effective_universe()` now copies (not aliases) every passthrough container one level deep, so its return value can never share object identity with the `lru_cache`-shared `sectors`/`indexes`/`actively_wheeling` config the risk engine reads. `test_the_overridable_set_matches_the_spec_exactly` now pins all four independent declarations of `{"would_own", "watchlist"}` (`OVERRIDABLE_LISTS`, `routers/universe.py::_OVERRIDABLE`, `UniversePayload.list_name`, and both route functions' `list_name` parameters), not just the first. `ARCHITECTURE.md` now notes `effective_universe()`'s `session_scope()` read (and `checks/warnings.py`'s transitive dependency on it) as a deliberate, documented exception to the API's read-only-trading-DB invariant. All gates green again: `python -m pytest -q`, `ruff check .`, `mypy src`, `cd web && npx vitest run`. **Not built, plainly:** no order ticket (spec §4.3, a standing P2 scope decision from M1, not new to this milestone); no Tailscale (same, standing since earlier milestones); and — the one limitation unique to this milestone, by deliberate design — **no override for `sectors`**: it feeds `risk_engine.py`'s concentration limits and stays file-only, unreachable from the web at every layer (API `422` via the `Literal` path-parameter type, the composer's byte-identical passthrough, and the fence test above). `clear_override` (Task 7.1) is built and independently tested but unused by any handler — revert is achieved through the opposite command (`POST`/`DELETE`), not a dedicated hard-revert route; it remains available for a future feature. No Telegram notification fires for a universe edit, deliberately. ~~`refresh`'s command kind (spec §6.6) still has no registered handler anywhere in the codebase~~ **Registered 2026-09-09** — P3/P4 M1 Task 1.4 (`src/notify/command_drain.py::_refresh`) gave it its handler: it captures positions + account values and writes one `portfolio_snapshots` row (`source="refresh"`), creating no approval and no order; `docs/web/commands.md` documents it. P3 (Portfolio), P4 (Profitability tracker), and P5 (Mobile) remain deferred — see the rows immediately below. |
| **P3 — Portfolio (M1 — the portfolio spine — built 2026-09-09, opencode/glm-5.3; M2 — the portfolio read API — built 2026-09-10, opencode/glm-5.3; M3 — the portfolio UI — built 2026-09-10)** | **M1:** nothing user-visible — no route, no component, no nav change. The API cannot ask IBKR anything, so the two processes that already hold an IB connection now write down what IBKR said, into a table the API reads. **The new table:** `PortfolioSnapshotRow` (`portfolio_snapshots`, `src/storage/models.py`) + `src/storage/portfolio_snapshots.py` — append-only, **no unique constraint** (two rows may share a `captured_at`: a refresh moments after a monitor write must not fail; newest `id` wins a tie), deliberately separate from `position_snapshots` (whose one-row-per-ET-day contract assignment auto-detection diffs — never written by anything new, pinned by a row-count test), pruned by the EOD run to `storage.portfolio_snapshot_retention_days` (default 30) beside `purge_old_risk_verdicts`; `save/load_latest/latest_capture_time/prune` never raise (the monitor calls save from a live event loop). **The two writers:** (1) the intraday monitor's `_maybe_write_snapshot` (`src/monitor/intraday.py`) — called at the *end* of `_refresh_subscriptions` with the positions that pass already fetched (never a second `get_positions`), rate-limited by `market_data.portfolio_snapshot_interval_minutes` (default 15) through a gate that reads the table's newest `captured_at` from the DB (a restart can't burst snapshots; a refresh's row counts toward the interval), RTH-only, account fetch under `asyncio.wait_for`, and wrapped so no exception can escape into `_refresh_loop` — a dead refresh task would silently stop roll alerts for every position opened after that moment, and that failure mode has its own test (`tests/test_monitor_snapshot.py`); (2) the `refresh` drain handler (`src/notify/command_drain.py::_refresh`, the command kind P2 left unregistered — now registered): captures positions + account now, writes one `source="refresh"` row, ignores the monitor's gate, fails `broker_unavailable` without a broker (never writes stale data as fresh), fails `snapshot_failed` on a bad write, sends no Telegram, and creates no approval and no order — the phase's no-new-order-path assertion lives in `tests/test_drain_refresh.py`. **The fallback chain:** `src/api/portfolio_source.py::read_portfolio` → `PortfolioReading` — three rungs (newest `portfolio_snapshots` row; else newest `position_snapshots` + the account block out of `journal.payload["eod_summary"]["account"]` (optional there, validated whole through `AccountSnapshot.model_validate`); else `source="none"`, `snapshot=None` — never a zeroed-out snapshot, because a portfolio page rendering zeros is indistinguishable from an account that's genuinely empty). A corrupt row on any rung falls through rather than failing; `as_of` is the capture time everywhere (via `as_utc_opt`), never request time. **Config keys:** `market_data.portfolio_snapshot_interval_minutes`, `storage.portfolio_snapshot_retention_days` (both documented in `ARCHITECTURE.md`/`SETUP.md`). **The read-side schema:** `PortfolioSnapshot` (`src/common/schemas.py`; `account` optional only on the API's eod rung). **M2:** four owner-only read routes (`src/api/routers/portfolio.py` + `src/api/models/portfolio.py`, mounted under `/portfolio`), all rendering what `read_portfolio` found — no second data path. `GET /summary`: account values as `Sourced` (`Source.IBKR`, `fresh_for` twice the snapshot interval — one missed capture reads stale) beside the exposure block (open positions/shorts/campaigns, net delta per the EOD formula, cash secured against short puts only at `strike × contracts × 100`, buying-power utilisation `null` not `0.0` when buying power is zero, assignment-risk count through the shared M0 predicate). `GET /positions`: grouped by underlying (a `null` `underlying` groups under its own symbol, never dropped), **both cost bases reported** — `avg_cost` from IBKR, `adjusted_cost_basis` from campaigns for assignment shares (both adjusted fields `null` otherwise), `unrealized_pnl` against the former and `unrealized_pnl_adjusted` against the latter so a profitable assigned position can't look like a loss; `moneyness` from the group's stock price else the latest `price_history` close (read-only, the same table `routers/research.py::_hv30_for` reads), `null` when unknown; `dte` `null` never `0`. `GET /campaigns`: the wheel threads with `status`/`symbol` filters, `opened_date` desc with open before closed at the same date, `as_of` request time (written on fill, not captured — documented in the route so nobody "fixes" it), financials gross of commissions (M0 Task 0.4), a pruned candidate still rendering as a leg with `known: false`; `load_campaigns`'s dicts now carry `leg_candidate_ids` for the join. `GET /calendar`: expiries grouped by date over `horizon_days` (default 45, max 365), the `consequence` table exactly as specified (ITM short put `assigned`; ITM short call `called_away` only with stock held, else `assigned`; short OTM/ATM `expires_worthless`; unknown moneyness `unknown` — a real value, never defaulted). Every route's `none` rung is a **200 with explicit emptiness** (`account: null` / `groups: []` / `days: []` + `source="none"` + a plain-words `note`), never a 404 and never zeros. 47 new tests across `tests/test_api_portfolio_{summary,positions,campaigns,calendar}.py`, plus shared fixtures in `tests/conftest.py` (`seed_portfolio_snapshot`, `seed_position_snapshot`, `seed_journal`, `seed_campaign`, `seed_assigned_campaign`, and the `short_put`/`short_call`/`long_put`/`stock` builders) that M4 reuses. `docs/web/openapi.json` and `web/lib/api-types.ts` regenerated (M0 Task 0.5's freshness test green). Gate: `python -m pytest -q` (2043 passed), `ruff check .`, `mypy src` all green. **A verification pass (2026-09-10, independent audit post-build) reproduced the full gate exactly as claimed and confirmed every artifact, then found and fixed four defects in the built code** (each with its own regression test, 47 → 53 across the four files, suite 2049): (1) `GET /positions`' `_stock_leg` called `storage.campaigns.adjusted_cost_basis_for` — which opens the storage engine's read-write `session_scope` from inside the API process — as its *primary* path, inverting the read-only-engine invariant the route itself documented; the read-only query is now primary (mirroring `adjusted_cost_basis_for`'s newest-open-assigned-campaign rule, also fixing a latent `MultipleResultsFound` on two assigned campaigns for one symbol); (2) `OptionLeg.right`/`strike` fabricated `"C"`/`0.0` for snapshots that carried neither and computed `moneyness` against the fabricated pair — both now `null` and `moneyness` requires all three of spot/right/strike; (3) the calendar's horizon gate used a UTC cutoff while its `dte` measured ET — two clocks in one route; both now ET; (4) `GET /campaigns` read the never-pruned `campaigns` table unbounded — now capped by a `limit` query param (default 50, max 200), the same discipline `load_campaigns` and the other list routes follow. **M3 (Tasks 3.1-3.6):** the `/portfolio` console itself — `Money` (`.hatch` unknown, signed figures, `kind`/`complete` rendered as words, never colour alone) and `FreshnessLabel` (Task 3.1); `PortfolioShell` mounting `SummaryPanel` once above a Positions/Campaigns/Calendar tab bar that never remounts it (Task 3.2); `PositionsPanel`/`PositionGroup` grouping stock and option legs by underlying, both cost bases reported (Task 3.3); `CampaignsPanel`/`CampaignThread` — collapsible wheel threads with a real backend-filtered `status`/`symbol` query, gross-of-commissions financials (Task 3.4); `CalendarPanel` and `RefreshControl` — the expiry grid with consequence text per entry, and the one write this page offers, a one-click `POST /commands{kind:"refresh"}` with no confirmation dialog (Task 3.5); the nav flip (`portfolio.available: true`) plus doc updates (Task 3.6). Every panel self-fetches its own route; what each reads from its response differs (`SummaryPanel` alone reads both `source` and `degraded`, `CampaignsPanel` reads neither — `CampaignsResponse` carries only `{as_of, campaigns}`). A whole-branch cross-cutting fix pass (2026-09-10) then closed six Important findings the six tasks' individual reviews couldn't see: `RefreshControl` now self-fetches `GET /options/controls` for the real `drain_healthy` instead of a hardcoded `true`; all four panels poll every 30s so the freshness label doesn't freeze at mount; `CampaignThread`'s `net_premium`/`adjusted_cost_basis`/`realized_stock_pnl` now pass `Money`'s `complete={false}`, since `/portfolio/campaigns` is documented gross of commissions. |
| **P4 — Profitability tracker (M4 — the P&L engine — built 2026-09-10, opencode/glm-5.3; M5 — the P&L surfaces — built 2026-09-11, opencode/glm-5.3; M6 — system performance and close-out — built 2026-09-11)** | **M4:** the paired realised-P&L accounting rule now exists once, in `src/reporting/` — a package the web layer may read and the trading path may not import (third, read-only analytics tier, both fence directions asserted in `tests/test_web_fence.py`). **Task 4.1 — the dependency inversion:** `fill_economics` and `classify_outcome` moved **verbatim** out of `src/claude/eval/reconcile.py` into `src/reporting/legs.py` (frozen dataclasses replace the tuples; the one addition is `commissions_complete`, which no existing caller reads). `reconcile.py` imports them from there — the fenced reconciler depends on the neutral read-only module, which the fence allows (`eval/` may import a read-only module; the fence stops it reaching the engine). The four reconcile test files pass **unchanged** at the recorded baseline (150). **Tasks 4.2–4.6 — the builders:** the six P&L schemas (`PnlLeg`/`CampaignPnl`/`PnlBucket`/`PnlSummary`/`EquityPoint`/`EquityCurve`, `src/common/schemas.py` — `PnlLeg.outcome` reuses `VerdictOutcome` so the reporting layer and the outcome ledger share one outcome vocabulary); `build_legs` (one `PnlLeg` per filled candidate, newest first; pruned candidates still produce legs with nulls; paper/live filterable and never silently mixed; assignment read from `CampaignRow.assigned`; `roc_pct` credit-over-collateral, `None` when collateral is unknown; `annualized_pct` `None` at `days_held=0`); `build_campaigns` (wheel threads; stock leg read from `CampaignRow`, never recomputed; `snapshot=None` means every unrealised field `None`, never zero; campaign-less legs land in synthetic per-symbol threads so thread legs always sum to the leg count; marks come from the same `PortfolioSnapshot` the portfolio page renders, and a closed leg's `unrealized_pnl` stays `None` forever); `build_summary` (pure; **raises `ValueError` on a mixed paper/live leg list** — the one raise in `src/reporting/`; `win_rate` `None` with nothing closed; `commissions_complete` is the AND of every leg's flag; best/worst chosen among closed legs only; buckets ordered realised-descending, ties by label); `equity_curve` (one point per `JournalRow`; `gaps` lists missed **trading days** — weekends/holidays are not gaps — never interpolated; `net_liquidation` read through `AccountSnapshot.model_validate` so payload drift surfaces as `None`, never a KeyError; `journal.realized_pnl` surfaces as `premium_cashflow` under its true name; `cumulative_realized` sums legs closed on or before each point). **Task 4.7 — the wheel-scenario suite:** five end-to-end scenarios (CSP expiring worthless, the full wheel with called-away stock, a roll chain, missing commission data, paper-vs-live side by side) with hand-written expected literals, plus the three cross-checks: the ledger and the reporting layer agree on every closed trade (one accounting rule — Task 4.1's whole point), the campaign rollup and the leg sum agree gross-vs-gross, and the gross and net views differ by exactly the commission total. **No routes and no UI** — the `/pnl/*` surfaces are M5. **Its numbers have not been reconciled against a broker statement** — the engine is built and tested against seeded data; a live-verification pass comparing `build_legs` output against IBKR's own fills/P&L report remains outstanding, as it does for the rest of the web platform. Gate at close: `python -m pytest -q` (2141 passed), `ruff check .`, `mypy src` all green. **M5 (Tasks 5.1-5.7, built 2026-09-11, opencode/glm-5.3):** the `/pnl` surfaces — every route a thin renderer over `src/reporting/` (the single accounting rule holds at the API boundary too). **Task 5.1 — `GET /pnl/ledger` + `GET /pnl/summary`** (`src/api/routers/pnl.py` + `src/api/models/pnl.py`): `as_of` is request time (the ledger is computed on read) while `marks_as_of` is the snapshot time behind every unrealised figure, from the same single `read_portfolio` call the portfolio page reads (proven by a test comparing the two responses' stamps); filters echo back verbatim; `build_summary`'s mixed-book `ValueError` becomes a `422 {"reason": "mixed_book"}` answer, never a 500 and never a mixed total, while the ledger may still list both books; `n_legs` is checked at the client boundary against the sum of every campaign thread's leg count (synthetic threads included). **Task 5.2 — `GET /pnl/equity`:** `build_legs` feeds `equity_curve` unchanged; `book=all` allowed here deliberately (a curve is a display choice, not a headline total — the asymmetry with the summary is documented in three places so nobody "fixes" it); `premium_cashflow` never named `realized_pnl` anywhere in the response. **Task 5.3 — `GET /pnl/ledger.csv` + the proxy allowlist:** the CSV is built from the same `build_legs`/`build_campaigns` calls the JSON route uses, with unit-suffixed headers (`credit_usd`, `net_pnl_usd`, `roc_pct`, `days_held`), a `book` column, `None` as an empty cell (never `0`), and a dated `Content-Disposition` filename; the proxy (`web/app/api/[...path]/route.ts`) gains an explicit two-name `FORWARDED_RESPONSE_HEADERS` allowlist (`Content-Type`, `Content-Disposition`) — not a passthrough, with its own pinning test so a copy-all regression fails. **Tasks 5.4-5.6 — the UI** (`web/app/pnl/page.tsx` + `web/components/pnl/{PnlShell,LedgerTable,CampaignRow,LegRow,LedgerFilters,SummaryPanel,BreakdownTable,EquityChart}.tsx`): the ledger grouped by campaign with `<button aria-expanded>` threads; no unknown renders as a zero anywhere (open leg's realised is `n/a`, `win_rate: null` is `n/a`, `marks_as_of: null` renders "no marks available" and every unrealised cell `n/a`, gross qualifier on incomplete commissions); a `422 mixed_book` renders a labelled book-choice group in plain words — a normal situation, not an error state; the equity chart renders gaps as gaps (`connectNulls={false}`), never animates (`isAnimationActive={false}`), reads colours from CSS custom properties at mount, labels `premium_cashflow` under that name, states the start date in words, and mirrors its real props onto `data-series` wrapper elements because Recharts does not expose them as DOM attributes; filters drive the query string so the CSV export link carries the same filters (one composition in `PnlShell`, never two); `Money` reused from `components/portfolio/` in every leg/campaign/summary figure — no second money component; `FreshnessLabel`/`DegradedNotice` are not used on this page (the ledger and summary carry their own `marks_as_of`/`mixed_book` renderings instead). Best/worst legs in the summary link into the ledger tab (filtered to that leg's symbol, the closest cross-reference the ledger's filters expose). **Task 5.7 — nav flip + docs + regen:** `pnl` flipped `available: true` in `_SECTIONS` (every section now available, no note), `tests/test_api_meta.py` updated, `docs/web/api.md` documents all four routes with the `as_of` vs `marks_as_of` distinction and the `mixed_book` refusal, `web/CLAUDE.md` gains the `app/pnl/`+`components/pnl/` layout entries and the proxy-allowlist section, `README.md`/`ARCHITECTURE.md` rows updated, `docs/web/openapi.json` + `web/lib/api-types.ts` regenerated (freshness test green). **Conftest:** the M4 `db` fixture pointed the storage engine at a private `t.db` while the API client read `income_system.db` — invisible while builders were called directly, exposed the moment a route test crossed the boundary — so tests/conftest.py gained a `db` override that rebinds the storage engine to the client's file (via the `client` fixture) plus a shared `seed_wheel` fixture; M4's own suite passes unchanged at its recorded baseline. **The M4 broker-statement caveat still stands:** the engine and now the surfaces are built and tested against seeded data; a live-verification pass comparing the ledger against IBKR's own fills/P&L report remains outstanding. Gate at close: `python -m pytest -q` (2175 passed), `ruff check .`, `mypy src`, `cd web && npx vitest run` (334 passed, 42 files) `&& npm run lint && npm run build` — all six green. **Also fixed in passing (pre-existing flake, exposed at this timezone):** the portfolio calendar tests and the conftest position builders seeded expiries from the local clock while `routers/portfolio.py` measures dte and its horizon gate on the ET exchange calendar — whenever the two calendars straddle midnight (any evening after 8pm ET, or running the suite from a non-ET machine) every default-dte position lands one day past the 45-day horizon and the calendar tests fail on `days[0]`. The builders (`short_put`/`short_call`/`long_put`) and the calendar tests' `_day()`/boundary assertions now derive from `_et_today()` (tests/conftest.py), the same clock the route itself reads. **M6 (Tasks 6.1-6.4, built 2026-09-11):** the score-vs-outcome evidence `src/claude/eval/score_metrics.py` already produced gets its reader, and the two fences this phase leans on are enforced by tests rather than by intention. **Task 6.1 — `GET /pnl/system`:** the one P&L route that reads behind the `src/claude/eval/` fence, and the reason is written down in its own docstring and in `docs/web/api.md` — `CLAUDE.md` already says everything `eval/` produces "is read by a human, never auto-applied," and this route is that human's reader, not a breach of it. It calls `score_outcome_report(since, until)` and returns exactly what it gets (a test spies on the call and asserts exactly one), adds a new `VerdictAgreement` figure computed here from `ledger.load_records(closed_only=True)` (Claude-vs-baseline agreement rate plus each side's win rate, windowed on `outcome_date` the same way the report is), and answers the empty case with the report's own "nothing to correlate yet" note rather than a `404`. `agreement_rate`/`claude_win_rate`/`baseline_win_rate` are `null` with zero closed rows, never `0.0`. **Task 6.2 — the System tab:** `SystemPanel`/`ScoreBucketTable`/`CorrelationTable` (`web/components/pnl/`), wired into `PnlShell` as a third tab with its own since/until window state, independent of the ledger's filters. `SystemPanel` is presentational (a `data` prop, like `EquityChart`) since the shell owns the fetch. Every note in the report renders in full and in order — the read-only "re-derive the scoring config by hand" sentence is why the surface is allowed to exist, and it is not the UI's to paraphrase; a bucket with `n` under 5 is labelled "small sample" in words; `n_closed: 0` renders the note and no tables at all, never empty tables with `n/a` rows; the only controls anywhere on the tab are the two date inputs, asserted by a test that counts every button/input/select in the panel. **Task 6.3 — five new fence tests** (`tests/test_web_fence.py`): no module under `src/api/` can write the verdict ledger or reference the scoring config by filename; the API still writes exactly one table (re-asserting the P2 guarantee, with the same `trading_db.py` exception the existing P2 test already carries, since that module *defines* the write handle rather than using it); `src/reporting/` never touches a DB session; `save_portfolio_snapshot` still has exactly its two intended callers (the monitor and the drain). One real trip surfaced and was fixed during this task: `pnl_system`'s own docstring named the scoring config by its literal filename in prose, tripping the new check even though it was never a code reference — reworded, not weakened, since the fence's point is that the name should be unreachable from `src/api/` by grep. **Task 6.4 — close-out:** re-derived rather than re-asserted — every command failure reason in `src/notify/command_drain.py` (extracted correctly this time, accounting for the multi-line `CommandFailed(...)` calls the milestone's own literal grep missed, same class of gap the P2 close-out log already flagged) appears in `docs/web/commands.md`; `docs/web/openapi.json` and `web/lib/api-types.ts` both regenerate to an empty diff (generated directly from the checked-in `openapi.json` file rather than via `npm run gen:api` against `:8787`, since a live API instance was already running there for other purposes and was left untouched); `README.md`'s layout table and `ARCHITECTURE.md`'s folder guide were already accurate for every P3/P4 module before this pass (confirmed, not re-written). **P3 and P4 are both complete. Not built:** P5 (mobile/responsive shell), operator notes on legs and campaigns, a materialised P&L table, intraday equity history beyond the snapshot retention window, and any Tailscale or remote hosting. **The ledger's numbers have not been reconciled against a broker statement** — every P&L figure across P3 and P4 is built and tested against seeded data; a live-verification pass comparing `build_legs`/`build_campaigns` output against IBKR's own fills/P&L report remains outstanding. Gate at close: see the implementation log in `Web plan/P3-P4-IMPLEMENTATION-PLAN.md` for the exact numbers. |
| **P5 — Mobile** | Deliberately not built. Responsive/mobile shell. |

Invariants (see `CLAUDE.md` and `Web plan/P0-P1-design.md` §4.3/§4.7 and `Web plan/P2-design.md` §4.2): the API process holds no
IBKR connection and no clientId; it reads the trading database through a read-only engine (SQLite `mode=ro`,
enforced at the engine, not by convention) and writes exactly one table — `app_commands` — through a separate
write-scoped engine guarded by a runtime `before_flush` listener (`tests/test_web_fence.py` asserts no module
outside `src/api/commands.py` imports `get_command_engine`); the trading system never imports `src.api` or
`src.research` (one-way import fence, `tests/test_web_fence.py`); the research and trading
databases are separate `Base`/engine pairs so `create_all()` can never cross-build.

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

## Bugs fixed (2026-09-11 — permanent promote/roll_request dedupe keys; order-idempotency doc correction; large-position slot accounting; phantom near-miss ranking; fill-recovery doc correction; share-ownership re-check at execution; unqualified-contract subscriptions; fresh earnings re-check at execution)

Worked through the "Remaining known issues" list end to end. Two items closed:

- **`promote`/`roll_request` permanently dedupe against their first `applied` command.**
  `dedupe_key_for` keys `promote` on `candidate_id` and `roll_request` on the bare
  `position_symbol` — both stable for the life of a contract/position, unlike `approve`'s
  per-decision `approval_id`. `enqueue_command` matched a `dedupe_key` regardless of the
  existing row's status, so a *second* `roll_request` for a symbol — days or months later, on
  an entirely different position — deduped to the first, already-`applied` command:
  `200`/`created: false`/`status: "applied"`, no new command, the drain never ran, and
  `<ShortsRow/>` rendered the OLD command's result as this request's answer. `promote` had the
  identical shape: re-promoting after the first approval expired silently no-op'd with a stale
  "Applied" receipt. **Fix:** `enqueue_command` (`src/storage/app_commands.py`) now scopes its
  dedupe lookup to `status == "pending"` rows only — two clicks while one is in flight still
  collapse to one command, but once that command is applied/failed/expired the key is live
  again. This required a schema change: `AppCommandRow.dedupe_key` carried a **global** `UNIQUE`
  constraint, which would have rejected the second insert outright once the app layer allowed
  it through. Replaced with `uq_app_commands_dedupe_key_pending`, a partial unique index scoped
  to `status = 'pending'` (`src/storage/db.py`'s `_PARTIAL_INDEXES`, the same shape as
  `uq_orders_active_candidate`). SQLite has no `ALTER TABLE ... DROP CONSTRAINT`, so
  `db._ensure_app_commands_pending_only_dedupe` rebuilds any table still carrying the old
  constraint (copy rows into a fresh table, drop the old one, rename) — idempotent, runs once
  per DB on `init_db()`, a no-op on a table already migrated or created fresh.
  `approve`/`reject` are unaffected in practice: `_apply_approval_decision` already treats
  re-deciding an already-decided approval as a safe no-op ("Already approved"/"Already
  rejected"), so a fresh command row created after the first applied just replays that no-op
  instead of reusing the old row's response.
  **Tests:** `tests/test_storage_app_commands.py::test_a_dedupe_key_only_matches_a_pending_row`;
  `tests/test_storage_db_migrations.py` (4 new tests covering the rebuild itself — the old
  constraint is gone, pre-existing rows survive untouched, a re-promote after the migration
  gets a fresh row, and running `init_db()` twice is a no-op). Full suite green (2220 passed).
  Docs: `docs/web/commands.md`'s `promote`/`roll_request` sections, `ARCHITECTURE.md`'s
  `app_commands`/`app_commands.py`/`db.py` entries.
  **Operational note:** the migration runs the next time any process calls `init_db()` — it
  was not run against the live `data/income_system.db` in this session because
  `scripts.run_approval_service` had it open; restart that process to pick up the fix (the
  rebuild is transactional and safe, but not designed to race a concurrent writer on the table
  it is rebuilding).
- **"Order idempotency" bullet corrected — the residual race it described was already closed.**
  The bullet claimed the cross-approval race (two different approvals of the same candidate
  both slipping past the application-level `has_active_order` check) was still open, needing "a
  partial unique index on `orders.candidate_id`." That index (`uq_orders_active_candidate`) was
  already shipped, along with the `except IntegrityError` handling that turns a genuine race
  into a safe no-op, in an earlier "Harden automated-mode safety" commit — and both are covered
  by existing tests (`test_partial_index_blocks_two_working_orders`,
  `test_manual_approve_skips_duplicate_when_active_order_exists`). No code change; the bullet
  above is corrected in place rather than left to mislead the next reader.
- **Large-position slot: the check was cumulative, `charge`'s consumption of it was not — and
  neither was the seed.** `capital._fits`/`validate_candidates` correctly *require* a free
  slot whenever a ticker's cumulative collateral (existing book + the new lot) crosses
  `max_collateral_per_ticker_pct`, but `capital.charge` only marked a slot **used** when the
  accepted candidate's own *marginal* collateral crossed that threshold — so a chain of
  individually-small candidates on one ticker could cumulatively cross the cap without ever
  registering as large, letting more than `max_large_positions` tickers end up cumulatively
  over the 10%-of-NLV line. A second, previously-undocumented gap: `seed_budgets` never
  registered a ticker as large from EXISTING positions either, so a name already over the cap
  purely from the current book (no candidate had touched it yet this scan) didn't occupy a
  slot at all. **Fix:** `Budgets.large_slots_used: int` is now `Budgets.large_tickers: set[str]`
  — a slot belongs to a ticker, not to a candidate, so adding an already-large symbol is a
  no-op rather than a second slot consumed. `charge` adds the symbol whenever cumulative
  collateral (not marginal) exceeds the cap; `seed_budgets` takes an optional keyword-only
  `caps` and does the same for existing positions up front; both `_fits` and
  `validate_candidates`'s inline mirror now check `symbol not in budgets.large_tickers` before
  requiring a free slot, so a ticker that already holds one never needs a second. No dollar cap
  was ever breached by the old gap — the 25%-of-NLV `max_pct_per_ticker_large` ceiling, cash,
  the CSP budget, and the risk-unit caps are all still enforced cumulatively per candidate
  regardless — this closes the slot-counting gap itself.
  **Tests:** `tests/test_capital.py` —
  `test_charge_marks_the_large_slot_used_on_a_cumulative_not_marginal_crossing`,
  `test_seed_budgets_marks_a_ticker_already_over_cap_from_existing_positions_as_slotted`,
  `test_seed_budgets_without_caps_leaves_large_tickers_empty`. Full suite green (2223 passed).
- **"Closest near-miss" ranking could surface a phantom, unpriced contract instead of a genuine
  near-miss.** `_rank_assessed` (`src/orchestrator/scan.py`) sorted a cycle's rejected
  candidates by `AssessmentStage` first, then broke ties within a stage purely by
  `blended_score` — and `blended_score` (`engine/scoring.py`) is a weighted blend of
  iv/technical/fundamental/liquidity/assignment-safety scores with **no dependency on whether
  the contract has a live bid/ask or a nonzero premium**. When every candidate reaching a
  cycle's "closest" slot failed at the same early stage, a contract whose quote never priced
  (forced to $0.00, tagged `no_two_sided_market`) could still score in the normal range on the
  other four components and outrank a contract with a real, priced (if insufficient) premium —
  displacing a genuine near-miss with a phantom one on the Telegram card. **Fix:** the sort key
  now carries an extra tie-break — a contract tagged `REASON_NO_MARKET` always sorts below every
  priced peer in the same stage, however it scored; priced-vs-priced and unpriced-vs-unpriced
  ties still break by score exactly as before. Contracts are never excluded from
  `result.assessed` or the audit trail — only de-prioritized as the surfaced "closest miss".
  **Tests:** `tests/test_scan_near_misses.py` —
  `test_an_unpriced_phantom_does_not_outrank_a_genuine_priced_near_miss`,
  `test_two_unpriced_phantoms_still_break_ties_by_score`. Full suite green (2225 passed).
- **"Post-reconnect fill recovery" bullet corrected — the "startup only" residual it described
  was already closed.** The bullet claimed fill recovery ran only at process startup, so a fill
  landing during a mid-session reconnect would wait for the next restart. SYSTEM_REVIEW F7 (see
  below) already wired the same `reconcile_orphan_fills`/`reconcile_external_closes` into every
  intraday RTH cycle, not just startup — recovery now happens within one
  `intraday_loop_minutes` interval. Added
  `test_intraday_loop_runs_periodic_fill_reconciliation_when_exec_is_connected` as a direct
  regression guard on that wiring (previously only the recovery logic itself was tested, not
  the loop calling it every cycle). No code change; the bullet is corrected in place.
- **Share ownership at execution: CC candidates never re-verified underlying share ownership
  before sending the order.** If shares were sold (manually, or by an assignment the
  reconciler hadn't caught yet) between scan and execution, a naked call could result. **Fix:**
  a new `strategies.covered_call.uncovered_call_capacity(positions, underlying) -> int` helper
  (the same `floor(shares/100) - existing short calls` formula `screen_cc_candidates` sizes
  with, extracted so a read-only caller doesn't re-derive it) is checked in
  `execution/approval.py::process_queued_orders`'s Phase 1 re-validation — the same pass that
  already re-checks cumulative risk/concentration budgets — against the **fresh** position
  snapshot it already fetches for that pass (no new IBKR round-trip). Covered calls are never
  grouped/deduped by the risk gate, so two QUEUED calls on the same underlying from different
  scan cycles can both reach this loop; a per-underlying `cc_shares_committed` running tally
  (mirroring `capital.py`'s greedy budget-consumption model) makes the second one see what the
  first already claimed, not just the static snapshot, closing a batch-level gap the naive
  per-candidate version of this check would have missed. A rejection cancels the order with
  `insufficient_shares_at_execution` — additive only, same as every other send-time re-gate;
  never places a smaller order on the caller's behalf.
  **Tests:** `tests/test_strategies.py` — `test_uncovered_call_capacity_matches_the_screen`,
  `test_uncovered_call_capacity_ignores_other_underlyings`,
  `test_uncovered_call_capacity_zero_without_shares`; `tests/test_execution.py` —
  `test_process_queued_orders_rejects_covered_call_without_enough_shares`,
  `test_process_queued_orders_allows_covered_call_with_enough_shares`,
  `test_process_queued_orders_two_covered_calls_same_underlying_second_rejected`. Full suite
  green (2232 passed).
- **Unqualified contracts in monitor/greeks enrichment — worse than documented, and provably
  so without a live session.** The former bullet here said `cancelMktData` "may not match the
  subscription, leaking lines" and that it "needs a live session to verify actual impact." It
  didn't need one: `build_option` returns an unqualified `Option` (`conId=0`), and ib_async's
  own `Contract.__hash__` **raises `ValueError`** for a contract with no `conId` —
  `IB.reqMktData` hashes the contract internally (`Wrapper.startTicker`) before any network
  call, so the crash is 100% local and reproducible with no TWS/Gateway connection at all (a
  three-line script instantiating a real `ib_async.Option` and calling `hash()` on it
  demonstrates it). Both `IntradayMonitor._refresh_subscriptions` and
  `enrich_positions_with_greeks_async` built exactly this unqualified contract and passed it
  straight to `reqMktData`, wrapped in a bare `except Exception: log.exception(...)` that
  silently swallowed the crash — meaning **every** short-option market-data subscription in
  the intraday monitor, and **every** call to the greeks-enrichment helper, has always failed
  silently. Not a line leak: a complete, silent no-op. The monitor's `pendingTickersEvent`-driven
  roll/assignment triggers were never actually receiving live ticks for options through this
  path, and `enrich_positions_with_greeks_async`'s `.delta` output (feeding the EOD report's
  net-delta exposure) was always `None`. **Fix:** both call sites now qualify before
  subscribing — `enrich_positions_with_greeks_async` batches the whole request through
  `contracts.qualify_options_async` (mutates contracts in place, so the already-qualified
  object is reused for `reqMktData` and later `cancelMktData`, matching the pattern already
  used correctly elsewhere — `executor._fetch_quote`, `roll_executor._fetch_leg`,
  `profit_take._quote_short`); the monitor qualifies each newly-opened position's contract
  individually right before subscribing (new positions per refresh cycle are typically 0–2,
  so no batching/chunking concern the way a chain-fetch cartesian has). The monitor's own
  comment claiming "ib_async matches by reqId... a freshly-built unqualified Contract silently
  no-ops" was itself wrong and is corrected in place. **Tests:**
  `tests/test_ibkr_portfolio.py` (new file) —
  `test_enrich_positions_with_greeks_qualifies_before_subscribing`; `tests/test_monitor.py` —
  `test_refresh_subscriptions_qualifies_before_reqmktdata`. Both use a small `_RealishIB` test
  double that delegates to ib_async's REAL `Wrapper.startTicker`/`endTicker` instead of a
  generic `MagicMock` — a `MagicMock`'s `reqMktData` never raises regardless of whether the
  contract passed to it is qualified, which is exactly why this bug was invisible to every
  existing test that mocks `ib` generically (`test_double_subscribe_prevention_on_repeated_refresh`
  patches `build_option` to return a `MagicMock` outright). Two shared test fixtures
  (`test_monitor.py::_make_monitor`, `test_monitor_snapshot.py::_make_monitor_env`) needed
  `qualifyContractsAsync` added to their mock `ib` for the new `await` to resolve. Full suite
  green (2234 passed).
- **Overnight stale data: the send-time re-gate never re-checked earnings.**
  `validate_live_quote` (the executor's fresh-quote re-gate) checks delta and price but not
  DTE or earnings; those came from the scan-time DB record. A Friday-approved trade executing
  Monday morning never re-checked whether earnings had been announced over the weekend —
  `execution/approval.py`'s Phase 1 already recomputed a fresh `dte` from the stored expiry,
  but `next_earnings` stayed frozen at whatever the scan saw, so the earnings-blackout check
  inside `validate_candidates` (which Phase 1 already re-runs) judged a stale date. **Fix:**
  Phase 1 now also re-fetches `next_earnings` via `analytics.fundamentals.get_fundamental_stats`
  alongside the existing fresh-DTE recompute, before `validate_candidates` runs — no change to
  `risk_engine.py` itself, since the blackout check already reads whatever `next_earnings` the
  candidate carries. Kept cheap deliberately: `get_fundamental_stats` is TTL-cached (1 day when
  a known earnings date is within ±2 weeks of today, else 30), so this is a DB read in the
  common case, not a fresh yfinance call on every ~30s poll cycle for every queued order — a
  real yfinance round-trip during this work measured ~2.7s, which at even a handful of QUEUED
  orders per poll would have made the loop unacceptably slow if it fired unconditionally.
  Explicitly out of scope (see the `next_earnings=None` bypass entry below, reviewed the same
  day and left as-is by design): a candidate whose earnings date was *unknown* at scan time and
  only gets announced over the weekend is not caught by this fix, because the persistent cache's
  own TTL only drops to 1 day once a date is already known and imminent — `next_earnings=None`
  stays cached for up to 30 days. That is a narrower, accepted gap, not a regression from today.
  **Tests:** `tests/test_execution.py` —
  `test_process_queued_orders_uses_a_fresh_earnings_date_not_the_frozen_one` (uses the REAL risk
  engine, not a mocked verdict, so the blackout check actually runs); a new autouse
  `_no_network_fundamentals` fixture in the same file defaults every other test's
  `get_fundamental_stats` to a fast "no known earnings" stand-in, so the 14 pre-existing
  `process_queued_orders` tests don't silently start making real network calls now that Phase 1
  calls a new I/O boundary unconditionally. Full suite green (2235 passed).

## Bugs fixed (2026-09-11 — risk gate: a symbol's own candidates were competing against each other for its own shared budget)

Two weeks of paper-scan rejects showed 95 of 96 `concentration_limit` rejects were TQQQ — a
symbol the account held **zero** position in. `validate_candidates` (`src/engine/risk_engine.py`)
walked *every* pass-1 survivor through the cumulative, shared-budget checks (per-ticker/sector
risk units, the large-position slot, total CSP collateral, the cash buffer) individually, in
score order, exactly as designed for cross-symbol competition — but a single busy scan cycle can
produce a dozen-plus strikes/expiries for one active name, and nothing kept those siblings from
walking the same per-ticker budget one after another until it was gone, rejecting the rest of its
own name's candidates as "concentrated" against exposure that was never real.

- **Two-pass split.** Pass 1 (independent per-candidate gates: ROC/yield/VRP, IV rank/RV, DTE,
  delta, contracts, earnings, margin) is unchanged. Before pass 2, a new
  `_select_budget_representatives` helper groups pass-1 survivors by `(underlying, strategy)` and
  keeps only the single highest-scoring one per group — candidates are pre-sorted by
  `blended_score` desc, so the first survivor seen per group wins. Every other survivor in the
  group is rejected with a new reason, `dedupe_pre_gate`, *before* it ever touches `budgets`/
  `caps` — it never had a chance to compete for the shared budget at all, unlike before.
- **Covered calls and rolls are excluded from grouping entirely** — they never reached the shared
  budget checks before this fix either, so there's nothing on them to dedupe.
- **Cross-symbol competition is untouched.** Representatives from different symbols still walk
  pass 2 in the same score-sorted order as before, competing for the shared sector/CSP/cash caps
  exactly as D1/Phase B intended — this fix only stops a name from competing against itself.
- **New reason code labelled.** `dedupe_pre_gate` → "a better strike on this name already claimed
  the shared risk budget" in both `src/notify/formatters.py`'s `_REJECT_REASON_LABELS` and
  `src/api/routers/options.py`'s `_REASON_LABELS`, so the Telegram card and the web options view
  read it the same way instead of falling back to a de-snake-cased reject code.
- **Tests:** `tests/test_engine.py::TestBudgetDedupeAcrossSameSymbol` (4 new tests — only the
  best-scoring sibling reaches the budget, a representative that fails the cumulative gate is not
  replaced by a sibling, covered calls are never grouped, different symbols still compete by
  score) plus a rewritten `test_cumulative_concentration_across_same_ticker`;
  `tests/test_ticker_scan_format.py::test_dedupe_pre_gate_has_a_readable_label`. Full suite:
  `python -m pytest -q` — 2191 passed, 1 failed
  (`tests/test_write_path_invariants.py::test_every_options_route_requires_owner`, a pre-existing
  FastAPI internal `Dependant`-attribute break unrelated to this change).

### Follow-up, same day: where the dedupe applies, and where it deliberately does not

A whole-branch review of the change above found that putting the dedupe *inside*
`validate_candidates` applied it to every caller, including one that must never have it. Fixed,
plus two behaviour notes worth recording as accepted rather than rediscovered later.

- **The single-ticker deep-dive opts out.** `validate_candidates` now takes a keyword-only
  `dedupe_same_symbol: bool = True`. The default is what every batch caller wants. With `False`,
  every pass-1 survivor is its own budget representative, nothing is ever given
  `dedupe_pre_gate`, and the cumulative budgets are consumed greedily in score order exactly as
  before the two-pass split. `scan._price_and_gate_ticker` — the `/scan TICKER` deep-dive, and the
  `promote` handler that reuses its pricing path — passes `False`: it hands the gate every CC+CSP
  strike of **one** ticker, so the dedupe collapsed the whole view to a single "winning" strike and
  hid exactly the alternatives an operator opens it to compare. It also made the runner-up strike
  unpromotable (a `RISK_GATE` reject is not in `PROMOTABLE_STAGES`). That view is a browse/compare
  surface, not an execution-committing one — the real gate for anything promoted out of it is the
  order-approval re-validation below.
- **The order-approval re-gate deliberately keeps the dedupe ON.** `execution/approval.py` batches
  the whole pending-order queue through `validate_candidates` with the default. That queue can
  hold two approved-but-unexecuted orders on one underlying, approved in different scan cycles
  (`has_active_order` dedupes per `candidate_id`, not per name); only one of them should reach the
  shared budget, so collapsing them here is an extra safety property and fails closed. `dedupe_
  pre_gate` means something narrower at that gate than on a scan card, so the cancellation detail
  and the thread-58 failure notification now append "another approved order on the same underlying
  outranked this one" for that one reason — message only, no new reason code.
- **Accepted behaviour change: a full-scan dedupe loser is now REJECTED, not PASS-but-unpicked.**
  Before this fix, a same-symbol CSP runner-up that cleared the gate could be dropped from the
  final slate later, at the post-gate `"dedupe"` stage (`AssessmentStage.DEDUPE`,
  `dedupe_not_surfaced`) — a promotable stage. Moving the dedupe *before* the budget gate
  necessarily means the non-representative is now a `RISK_GATE` reject with reason
  `dedupe_pre_gate` instead, and is no longer promotable the way a pre-fix runner-up was. This is
  intended, not a regression: the runner-up is being set aside for the same reason it always was,
  just earlier and honestly. `AssessmentStage.DEDUPE` is now effectively unreachable for CSPs in
  the full-scan pipeline (`select_top_candidates_detailed` still emits it, but the gate no longer
  hands it two survivors from one group to choose between); it remains reachable for covered
  calls, which are never grouped. Nothing about the stage, the schema, or `PROMOTABLE_STAGES`
  changed.
- **`dedupe_pre_gate` is kept out of the "why did this scan find nothing" surfaces.** A contract
  whose only reason is `dedupe_pre_gate` cleared every economic gate and lost to a sibling — a
  useless "closest miss". `scan._lost_only_to_a_sibling` excludes it from `_near_misses` (the
  digest shows exactly one contract, so one busy name could otherwise take the slot from a genuine
  economic near-miss) and from both per-strategy/per-symbol rejection tallies. It stays in
  `result.assessed` and the persisted audit trail in full.
- **Tests:** `tests/test_engine.py::TestDedupeOptOut` (3) and
  `::TestBudgetDedupeAcrossSameSymbol::test_rolls_are_not_grouped_or_deduped`;
  `tests/test_drain_promote.py::test_the_deep_dive_shows_every_qualifying_strike_for_one_ticker`
  and `::test_promoting_the_lower_scored_sibling_still_succeeds` (both fail against the pre-fix
  code); `tests/test_scan_near_misses.py` (3); `tests/test_execution.py`'s two re-gate message
  tests; `tests/test_reason_label_parity.py` (4 — the two duplicated reason-label dicts can no
  longer drift apart silently). Full suite: `python -m pytest -q` — **2206 passed, 1 failed**. The
  one failure is the same pre-existing `test_write_path_invariants.py::test_every_options_route_requires_owner`
  break recorded above (a FastAPI internal `Dependant`-attribute error) — confirmed still
  reproducing on the current environment; it was never related to this work.

---

## Bugs fixed (2026-09-09 — M0 "Baseline and pre-existing defects": idempotent EOD, one assignment-risk predicate, P2 deferred findings closed)

`Web plan/milestones/P3-P4/M0-baseline-and-fixes.md`'s nine sub-tasks (0.2–0.10), all landed on
`main`. No new capability — this milestone exists to fix defects the P2 close-out review found
and record a baseline before P3/P4 build on top of it.

- **The EOD run is now idempotent on a same-day re-run** (Task 0.2, `src/orchestrator/eod_report.py`):
  a repeated run for the same day now upserts the journal row instead of inserting a duplicate, so
  reconciliation still works if the job is re-triggered (retry, manual re-run) after it already
  wrote once.
- **`/options/shorts`'s `assignment_risk` flag now uses the monitor's real 0.70/21 thresholds**
  (Task 0.3, `src/common/assignment_risk.py` — the one `is_assignment_risk`/
  `assignment_risk_thresholds` definition both `src/monitor/triggers.py` and
  `src/api/routers/options.py` read now) — **widened** from the API's previous hardcoded, wrong
  `0.70`/`7` (under a comment incorrectly calling `7` "the monitor's default"). A short between 8
  and 21 DTE that the monitor was already alerting on now also flips `assignment_risk` to `true`
  in the API response — a user-visible behavior change for anything reading that endpoint.
- **P2 M7's close-out log recorded seven minor findings as "deferred, not fixed"; four are now
  closed** (Task 0.7): a dead `log` logger and unused `import logging` removed from
  `src/storage/universe_overrides.py`; the unused, untyped `cfg` parameter dropped from
  `_universe_symbols` in `src/orchestrator/eod_report.py`; the redundant local
  `_reset_universe_cache` fixture removed from `tests/test_universe_consumers.py` (made
  redundant by the global `_clear_effective_universe_cache` autouse fixture); a `web/CLAUDE.md`
  doc misattribution corrected (submitUniverseCommand/CommandReceipt usage belongs to
  `AddSymbol`/`UniverseList`, not `OverrideBadge`). The remaining three (config-relative test path
  with no CWD guard, a config lookup called per-iteration instead of hoisted, a test pinning
  literal config values) were reviewed and parked as low-severity/stylistic, not fixed here.
- **The Next.js proxy (`web/app/api/[...path]/route.ts`) now fails soft on a body-read failure
  too, not just a connect failure** (final-review fix — the fetch() call was already wrapped in
  try/catch returning JSON 502/504, but the subsequent `await upstream.text()` was unprotected;
  a mid-response connection drop or a timeout firing while the body is still streaming now also
  returns the same JSON 502/504 shape instead of an uncaught exception that Next.js would render
  as its own HTML 500).
- Also: one shared `as_utc` helper (was duplicated between `src/api/trading_db.py` and
  `src/api/routers/options.py`); `docs/web/commands.md`'s `refresh` runbook entry corrected;
  `docs/web/openapi.json` pinned against the live app with a freshness test; the campaign
  rollup's gross-of-commissions semantics documented at the source
  (`src/storage/campaigns.py::_rollup`, `CampaignRow`).

---

## Bugs fixed (2026-09-09 — health-probe diagnosis: the "half-dead socket" block mislabelled its root cause)

The pre-scan health probe (`probe_market_data_health`) returned a bare `bool`, and the
intraday loop's 🛑 *Scan blocked* Telegram message hardcoded the explanation — *"This is the
Error 1100 (lost connectivity to IBKR) state"* — regardless of what actually failed. On
2026-09-08 22:30 ET the probe correctly detected an unhealthy farm, but the real cause was
`Error 10197` ("No market data during competing live session": another login on the same
account held the live-data entitlement), visible in the log 10s before the block. The message
told the operator a reconnect would recover it — advice that does nothing for 10197, where
the fix is closing the competing session (or a second username for the bot). The same
hardcoded label sat in the mid-scan circuit-breaker message and the manual-`/scan` mid-run
abort message.

- **`probe_market_data_health` now returns a `ProbeHealth` record** (`healthy`, `diagnosis`,
  `action_hint`, `error_codes`, `probe_symbol`, `probe_timeout`; `__bool__` keeps every legacy
  boolean call site working). While the probe runs it hooks `ib.errorEvent` — IBKR error
  codes arrive as events, not exceptions, so listening during the window is the only way to
  see *why* the farm is silent — and `_diagnose_probe_failure` classifies the failure:
  **1100** → Gateway lost its upstream link (the original half-dead case; reconnect usually
  recovers), **10197** → competing live session (reconnect will NOT fix; close the other
  login / use a second username), **354/10089–10091** → no market-data subscription (config/
  entitlement problem, not connectivity), **1101/1102** → the link is flapping right now
  (transient; next cycle), **no codes** → generic unreachable-farm. The listener is always
  unhooked in a `finally` so it can't leak for the process lifetime.
- **The block messages now carry diagnosis + observed codes + action hint.** The pre-scan
  block names the diagnosed root cause, echoes the observed IBKR error codes, and states the
  fix that actually helps (e.g. "A reconnect will NOT fix this. Close the other logged-in
  session…"). The mid-scan circuit-breaker block and the manual-`/scan` mid-run abort —
  which have no single observable code — stopped asserting "half-dead socket (Error 1100)"
  and instead point at the log to distinguish 10197 vs 1100. The ⚠️ throttled skip warning
  carries the diagnosis too.
- **Not changed:** the recovery mechanics. A failed probe still forces a reconnect (10197 is
  sometimes a transient post-Gateway-restart race, so best-effort reconnect remains
  correct), skips the cycle, and queues any unreached symbols. Diagnosis is purely
  operator-facing observability — it reaches nothing in `engine/`/`execution/` (the fence is
  untouched).
- Tests: `tests/test_market_data.py` grew per-cause probe tests (1100 / 10197 / 354 /
  1102-flap / hung qualify / codeless, plus listener-unhook assertions);
  `tests/test_notify.py` grew the intraday-loop regression — a 10197 probe must produce a
  block message naming 10197, must NOT contain the "Error 1100" label, must carry the
  action hint, and must still fire the forced reconnect and skip counter.

---

## Bugs fixed & wired (2026-09-08 — P0/P1/P2 final audit: token proxy + missing nightly warm refresh)

A whole-stack verification pass before P3 planning (every entrypoint imported, all 24 API
paths live-diffed against the committed OpenAPI spec, the frontend fetch surface checked
field-by-field against the Pydantic models, both DBs inspected). The trading pipeline, the
fences, and the backend wiring all checked out; three real defects were found and fixed,
plus one unbuilt wiring promised by the P0-P1 design.

- **The token proxy dropped the query string — ⌘K search, the universe-add typeahead, and
  the assessed filters were dead end to end.** `web/app/api/[...path]/route.ts` rebuilt the
  upstream target from the catch-all `params.path` alone; in Next.js 15 those params carry
  only path segments, so `?q=…` lived solely on `req.url` and never reached the backend.
  `GET /research/search` with no `q` hits its blank-query rule and returns `[]`, so the
  command palette showed "No match" forever and `AddSymbol`'s typeahead never rendered a
  pickable row — the M7 universe-add feature was unusable from a browser. The Assessed
  tab's `stage`/`symbol` filters silently did nothing; `?status=pending`, `?state=working`,
  `?days=7`, `?range=1y` survived only because each dropped value happened to equal the
  backend's default. **Fixed:** the proxy appends `new URL(req.url).search` to the target.
  Covered by `route.test.ts` ("forwards the query string").
- **The proxy threw on 204 responses — a successful live-mode LIVE confirmation reported
  "Nothing was sent", and watchlist remove looked broken in paper mode.** The proxy passed
  `await upstream.text()` (`""`) as the body of a `new Response(..., { status: 204 })`, which
  throws per the WHATWG spec (204 requires a null body) — the route handler crashed and the
  browser got a 500. Two backend routes return 204: `POST /commands/{id}/confirm` (the
  live-mode second confirmation for `approve`/`promote`/`roll_request`) and
  `DELETE /watchlist/{symbol}`. For the confirm route the token *was* cleared and the next
  drain cycle released the order — while the UI rendered "The command could not be created.
  Nothing was sent." **Fixed:** 204/304 and empty bodies pass a null body through.
  **`web/lib/api.ts` had the client-side half of the same bug** — an unconditional
  `res.json()` throws `SyntaxError` on a 204 — so `apiFetch` now returns `undefined` for
  204. Both covered by new tests (`route.test.ts` 204/304 cases, `lib/api.test.ts`).
  Live-verified end to end against a real `next start` + `scripts.run_api`: search with a
  query returns real EDGAR results through the proxy, and the watchlist DELETE comes back
  204 at the browser.
- **The nightly warm-tier refresh promised by the P0-P1 design was never built** —
  `ingest_daily_bars` and `ingest_news` had no production caller (only tests called them),
  `research.yaml`'s `warm_refresh_hour_et`/`directory_refresh_days` were read by nothing,
  and `data/research.db`'s `daily_bars` held only manually seeded AAPL rows, so every
  ticker page's price chart was empty except AAPL. **Wired:**
  `src/research/ingest/quotes.py` gains `refresh_warm_bars`/`refresh_warm_news`/
  `refresh_warm_tier` (per-symbol isolation; never raises; `ingest_daily_bars`' own
  never-delete-history guarantee applies), `jobs.py` registers the nightly `warm_refresh`
  job on a `CronTrigger(hour=warm_refresh_hour_et)` and derives the directory cadence from
  `directory_refresh_days` (7 → the Sunday 03:00 cron; otherwise an interval). Covered by
  seven new tests in `tests/test_ingest_quotes.py` including two scheduler-registration
  regressions and two end-to-end row-write integrations.

**Known gaps accepted and left as documented deferrals** (not fixed here): the watchlist
row's `checks` placeholder still returns zeros (the wiring was never planned for P1 —
see `watchlist.py::_checks_summary`); `ApprovalCard`'s `review` read is dead (the list
route never carried it); a refused autonomy promotion does not render its `blockers`
through `CommandReceipt`; `GET /research/recommendations` and `GET /research/{symbol}/options`
have no frontend consumer (the latter documented; the former is M6's "replaces the Telegram
buy card" surface that P3+ must wire); ~~`CommandKind.REFRESH` remains accepted-but-failing
(`unknown_kind` at the drain)~~ **registered 2026-09-09** (P3/P4 M1 Task 1.4 — it now writes a
`portfolio_snapshots` row; see `docs/web/commands.md`). None blocks P3.

*(Corrected 2026-09-09, M0 final-review pass: this entry previously also flagged
`docs/web/architecture.md:43` as overstating `refresh` as triggering a scan. That was fixed
before M0 began — the diagram there now reads "refresh → no handler — accepted then failed
(unknown_kind); not built yet", matching `docs/web/commands.md` exactly — so the line was
removed rather than left to describe a gap that no longer exists. Updated again 2026-09-09
by P3/P4 M1 Task 1.4: the handler now exists and the diagram reads "refresh → get_positions +
account → portfolio_snapshots".)

---

## Bugs fixed (2026-09-11 — IV-history circuit breaker starved the whole universe for a month; illiquid/data-outage conflation)

Prompted by a deep-dive into two weeks of real scan history (`risk_verdicts`, 38,858 evaluated
CSP/CC contracts, 2026-08-27→09-10) after CSP/CC output quality looked poor against a 0.5%/week
premium target. The headline read ("mostly low IV rank / market regime, not a bug") did not
survive the data: of the 185 candidates that cleared **every** generator screen (delta band,
DTE, liquidity, ROC, the 10%-over-fair-value VRP edge), 78 (42%) were still rejected at the Rules
Engine for `iv_rank_below_minimum`/`iv_rv_below_minimum` — RKLB, NVDA, ASTS — despite those exact
rows showing 0.6%–3%+ weekly premium; TQQQ CSPs with 0.67%–1.82% weekly premium repeatedly missed
`min_candidate_score: 55` by a few points. Two root causes, two fixes:

- **`_append_daily_iv`'s circuit breaker aborted the entire remaining alphabet, forever, on a
  cluster of unrelated per-symbol failures.** The breaker (`_IV_MAX_CONSECUTIVE_FAILURES = 5`,
  `src/orchestrator/eod_report.py`) was designed for a whole-farm HMDS outage, where every symbol
  fails identically and bailing early saves ~1 hour of dead requests. In production, a chronic
  failure in one or a few symbols (somewhere between AMZN and ARKK in the alphabetically-sorted
  universe) tripped the same breaker every day, and the unconditional `break` then killed IV
  history for every symbol after it — confirmed directly in `iv_history`: only AAPL/AMZN (first
  in sort order) stayed current to 2026-09-09; RKLB, NVDA, ASTS, TQQQ, MARA, HOOD and nearly the
  rest of the universe froze at 2026-08-12, with `eod.log` showing repeated "aborting IV append
  after 5 consecutive failures" on Aug 15/22/28 and Sep 9. Since `min_iv_rank: 30` is a hard gate
  and `iv` is the largest single scoring weight (0.30) in both strategies, this made iv_rank
  silently wrong for ~95% of the universe for a month. Fix: the failure run now calls the
  existing `probe_market_data_health` (already used by `approval_service`'s `/refresh` path)
  instead of assuming the worst — a confirmed-unhealthy probe still bails fast (old behaviour
  preserved for a genuine outage), but a healthy probe means the failures are isolated to a
  few bad symbols, so they're logged (now at WARNING with the symbol name and exception, not
  silent DEBUG) and skipped, and every symbol after them still gets attempted. Covered by
  `tests/test_eod.py::test_append_daily_iv_skips_isolated_bad_symbols_and_keeps_going` (17
  symbols, 7 chronically bad — asserts all 17 are still attempted and all 10 good ones get their
  observation) plus the two existing dead-farm tests, updated to mock the probe as unhealthy so
  they still assert the fast-bail path.
- **A symbol-wide IBKR data-feed outage was indistinguishable from genuine illiquidity.** Several
  scan cycles showed `illiquid`/`no_two_sided_market` on 100% of a symbol's *entire* chain —
  including TQQQ, UPRO, AMZN, and RKLB (e.g. 2026-09-11 02:16 SGT: 102/102 TQQQ puts, all with no
  live bid/ask) — correlated with 650 `Error 1100` events and thousands of `Error 200` events
  across the same two weeks. `passes_liquidity_gates` correctly fails a quote with no market (a
  missing spread can't clear the liquidity gate), but the per-symbol reject tally folded that in
  with ordinary thin-liquidity rejects, making a data outage look identical to a market genuinely
  short on premium. `ScreenResult.market_data_outage()` (`src/strategies/_evaluation.py`) now
  flags the case where every evaluated quote in a symbol's chain carried `no_two_sided_market`;
  both `screen_csp_candidates` and `screen_covered_call` (`src/strategies/cash_secured_put.py`,
  `covered_call.py`) log a distinct "data-feed outage suspected" warning ahead of the existing
  reject-tally line when it fires. This is a diagnostic signal only — it changes no gate, no
  score, and no ranking — so it does not touch the pre-existing "closest near-miss" ranking bug
  (an unpriced $0.00 contract can still out-rank a genuinely-priced near-miss via `blended_score`,
  which has no dependency on premium) — see "Remaining known issues" below; that fix is separate
  and still open. Covered by two new tests in `tests/test_strategies.py::TestCashSecuredPut`
  (a fully-unpriced chain logs the outage warning; a real-but-thin market does not).

Separately, whether to raise TQQQ's per-ticker concentration cap (96 `concentration_limit`
rejects in the same window, 95 of them TQQQ — its IV inflates risk-unit consumption fast) or
lower the `min_iv_rank`/`min_iv_rv_ratio` floors is a risk-tolerance policy call, not a bug —
deliberately left to the account owner rather than changed here.

All green: `python -m pytest -q` (2194 passed; the one pre-existing failure,
`test_write_path_invariants.py::test_every_options_route_requires_owner`, is an unrelated FastAPI
internal-API break — `Dependant` has no `.dependant` attribute on the installed FastAPI version —
reproduced identically on a clean checkout before these changes), `ruff check .`, `mypy src`.

---

## Bugs fixed (2026-09-11 — research worker sleep/wake resilience, cold-chart backfill, revenue tag pooling)

Prompted by a live incident: the research worker (`scripts.run_research_worker`) sat frozen
through a macOS sleep from 2026-09-08 to 2026-09-11 with no error logged, `/stock/META` and
`/stock/NVDA` rendered blank price charts, and NVDA's checks ribbon showed several UNKNOWN
value/growth metrics despite being one of the most-covered filers on EDGAR. Three separate
root causes, three separate fixes:

- **Scheduler silently dropped every job discovered late.** APScheduler's own default
  (`misfire_grace_time=1` second) treats a job whose due time is found more than a second in
  the past as "missed" and skips it rather than running it — after a multi-day macOS sleep (no
  `caffeinate`, no supervision) every job is always late, so nothing ran again until a human
  noticed and restarted the process by hand. `build_scheduler()` (`src/research/ingest/jobs.py`)
  now sets `job_defaults={"misfire_grace_time": None}`: a job is never considered missed, so
  whenever the process next gets CPU time (immediately on wake) it runs — `coalesce` (already
  the default) still collapses a multi-day backlog into one run rather than replaying every
  missed occurrence. Covered by
  `tests/test_ingest_quotes.py::test_a_job_discovered_days_late_still_runs_instead_of_misfiring`,
  which backdates a job's run time three days and asserts it executes rather than misfiring.
  Deliberately not a fix: this makes the worker *recover* from sleep, not immune to it — it
  still does nothing while the Mac is actually asleep, and can only run once the machine gets
  CPU time again (opening the lid, a scheduled wake). Running it under `caffeinate -s` (or a
  launchd job with the machine's sleep disabled) is the belt-and-suspenders fix if the gap
  itself — not just the silent non-recovery — needs to go away too.
- **`daily_bars` had no cold path.** The nightly `refresh_warm_tier` cron (04:00 ET) is the
  *only* thing that ever populated a symbol's price history, and it only covers symbols already
  "warm" (watchlisted, or viewed on a *prior* day) — a symbol viewed for the first time today
  rendered a permanently blank chart until tomorrow night's run, unlike fundamentals, which
  already had a synchronous cold-path fetch inside `materialize()`. `GET /research/{symbol}/bars`
  (`src/api/routers/research.py`) now does a one-time, best-effort `ingest_daily_bars` backfill
  when a symbol has zero rows, before serving the request — degrades to the existing "no bars →
  empty lists" contract on a provider failure, never a 500. Covered by four new tests in
  `tests/test_api_bars.py` (backfill triggers on a cold symbol, degrades cleanly when the
  backfill finds nothing or raises, and is skipped entirely for a symbol that already has bars).
  Live-verified: `GET /research/NVDA/bars` and `GET /research/META/bars` went from 0 rows to 251
  real bars through the actual proxy + API.
- **`resolve_line_item` stopped at the first XBRL tag alias with any facts.** A filer can switch
  which us-gaap concept it tags a line item under between fiscal years — NVIDIA tags revenue
  `RevenueFromContractWithCustomerExcludingAssessedTax` for FY19-22 and switches to `Revenues`
  for FY23-26 — and the old resolver locked onto whichever alias it checked first that had *any*
  data, silently dropping every other alias's periods. For NVDA specifically that meant `revenue`
  was populated for exactly one fiscal year (2022) and `UNKNOWN` for the four most recent ones,
  which cascaded into `price_to_sales`, `revenue_growth_yoy_pct`, `revenue_cagr_3y_pct`, and
  `net_margin_change_3y_pts` all reading UNKNOWN despite NVDA being fully covered by EDGAR.
  `resolve_line_item` (`src/research/ingest/concepts.py`) now pools facts across every alias
  concept instead of stopping at the first one; `Fact` gained a `concept` field so a pooled
  period still records which tag it actually came from, and `select_periods`'s existing
  "latest filed wins" rule arbitrates the rare case where two aliases both report the same
  period (no new precedence logic needed). Covered by two new tests in
  `tests/test_research_concepts.py` (disjoint periods across aliases both survive; a genuine
  same-period/same-filed-date tie still resolves the same way the old code did). Live-verified
  against the real EDGAR payload: NVDA now has revenue for all 5 annual periods (FY2022 $26.9B
  → FY2026 $215.9B) and none of the affected metrics resolve UNKNOWN. The remaining UNKNOWNs
  observed for NVDA (`atm_open_interest`, `atm_spread_pct`) are the documented, unrelated P1
  limitation that `coverage.option_chain` is always false — the API holds no live IBKR
  connection.

All green: `python -m pytest -q` (2192 passed), `ruff check .`, `mypy src`.

---

## Built (2026-08-28 — option-chain fetch: tightened DTE window + OTM-only cartesian)

Prompted by a "why does fetching a symbol take so long" investigation into
`src/ibkr/market_data.py`. Two independent changes:

- **`covered_call`/`cash_secured_put` `dte_min`/`dte_max` tightened from 21/45 to 7/28**
  (`config/risk_limits.yaml`). These keys are shared by the strategy screens' entry window and
  `risk_engine.validate_candidates`'s `dte_out_of_range` gate, so both narrow to the same
  shorter-dated focus. **Interacts with the monitor's `manage_at_dte` (default 21, see the
  Monitor bullet in "What is built" above):** a fresh entry can now open as close as 7 DTE,
  already past that 21-DTE management checkpoint on day one — worth a human look at whether
  `manage_at_dte` should come down too, not changed here since it's a separate, deliberate
  monitor-alert threshold.
- **`_build_chain_contracts` (`src/ibkr/market_data.py`)** replaces the inline
  `expirations × strikes × ("C", "P")` cartesian in `get_option_chain_quotes`/
  `get_option_chain_quotes_async` with an OTM-side-only cartesian: calls only at strikes ≥ spot,
  puts only at strikes ≤ spot. `covered_call.py`/`cash_secured_put.py` only ever keep OTM
  contracts (delta 0.20–0.35 / |delta| 0.15–0.30), so the ITM half of every (expiration, strike)
  pair was always qualified, quoted, and discarded downstream regardless. This is lossless —
  nothing that used to survive the strategy filters is dropped — and roughly halves the
  qualify/quote batch count (and therefore wall-clock fetch time, since `_batch_quotes`/
  `_batch_quotes_async` cost is linear in contract count) per symbol. **Does not address** the
  larger, already-known qualification waste from `reqSecDefOptParams`'s per-symbol strike union
  (see "Bugs fixed 2026-08-21" below) — that still needs a per-expiration `reqContractDetails`
  lookup to fix properly.

---

## Bugs fixed (2026-08-28 — quiet-cycle seed-only persistence clobbered real fetch timestamps)

Found in review before this branch of work was declared done. `_run_scan_body` called
`_persist_seed_only_baselines(probed_spots, material_symbols)` unconditionally, right after
computing `material_symbols` — outside the `if intraday: / else:` split. That helper was written
for the full-sweep dip_watch case only ("names that didn't gap overnight get seed-only, no chain
fetch"), but the unconditional call site meant a normal 15-min gated cycle (`force_full_sweep`
false) hit it too, for *every* probed-but-immaterial symbol regardless of bucket — not just
dip_watch. On any quiet cycle (the common case — that's the point of the gate), a probed
`actively_wheeling`/held symbol that didn't cross its move threshold had its real
`last_scanned_at` overwritten to `NULL` and `last_spot` rebased to that cycle's probe price.

Two consequences, both the opposite of what S1 exists to do:

- **Sticky-`last_spot` drift accumulation broke.** The gate's whole premise is that a small
  per-cycle move (e.g. −0.2%) accumulates against the *last real fetch* until it crosses the
  threshold. Rebasing to the current probe every quiet cycle meant each comparison was only ever
  against the immediately-prior cycle, so slow drift never accumulated to a fire.
- **The 120-min staleness net (rule f) fired every other cycle instead.** With `last_scanned_at`
  nulled, the *next* cycle's per-symbol staleness check saw `stamp is None` and force-refetched
  immediately — confirmed by tracing a quiet `actively_wheeling` name through repeated cycles:
  real fetch → probed-quiet (nulled) → forced refetch next cycle (stale) → probed-quiet (nulled)
  → forced refetch → … roughly a real chain fetch every ~30 min instead of every 120 min, a ~4x
  amplification of exactly the fixed cost this whole S1/dip-watch effort was cutting.

No existing test caught it: the only coverage of `_persist_seed_only_baselines` was unit-level
with hand-picked args, and nothing ran two consecutive `run_scan(intraday=True)` cycles checking
`scan_state` afterward. Reproduced directly against a real sqlite `scan_state` row before the fix,
then fixed by scoping the call site to an actual full sweep:
`if probed_spots and (force_full_sweep or not intraday):`. Regression test added:
`test_quiet_gated_cycle_does_not_null_a_real_fetch_timestamp`
(`tests/test_scan_materiality.py`) — seeds a real `last_scanned_at` via `bulk_upsert_scan_state`,
runs one gated `run_scan(intraday=True)` cycle with the symbol probed-but-unmoved, and asserts
the timestamp and `last_spot` are unchanged afterward (reading real persisted state, not a
mocked `get_scan_state`).

---

## Built (2026-08-28 — scan-abort retry queue + intraday live progress)

Direct follow-up to the 2026-08-27 half-dead-socket incident below: when the circuit breaker
aborted the 09:30 forced full sweep at 38/46 symbols, the 8 never-reached names (all dip-watch —
no `actively_wheeling`/held 120-min staleness net covers them) had no path back into the scan set
short of a 3% drop or another process restart. Two changes close that gap and make a slow/aborted
run visible while it's happening, instead of just after:

- **`ScanResult.unreached_symbols`** (`src/orchestrator/scan.py`): populated at the circuit
  breaker's abort point as `all_symbols[run_start:]`, where `run_start` backs up to the first
  symbol of the consecutive-timeout run that tripped the breaker — every symbol that failed for
  the shared root cause (dead socket), not just the one that happened to cross the threshold,
  plus everything genuinely never attempted after it.
- **`_compute_material_symbols(..., must_include=...)`** and `run_scan(...,
  must_include_symbols=...)`: force specific named symbols through the S1 materiality gate
  regardless of movement, without widening the fetch to anything else — cheaper than
  `force_full_sweep`, since everything else that cycle is already fresh in `scan_state`.
- **`_run_intraday_scan`** carries `bot_data["pending_retry_symbols"]` forward each cycle:
  passed as `must_include_symbols`, then fully replaced (not merged) from the new
  `result.unreached_symbols` afterward — symbols that get through drop out, newly-missed ones
  take their place. A `lease_skipped` cycle (another process held the scan lease) leaves the
  queue untouched rather than clearing it, since it produced no real result. Scoped to the
  intraday loop only — a manual `/scan` doesn't read or clear it (see `How the scan works.md`
  §4, "The retry queue," for the full mechanics and the known edge case this leaves).
- **🛑 *Scan blocked* now names the queued symbols** (`_notify_scan_blocked`'s new
  `retry_symbols` param) instead of just reporting that a block happened.
- **Live progress for the intraday loop**: `_run_intraday_scan` now sends its own
  "🔍 Scanning…" dashboard message and wires it as `run_scan`'s `dashboard_callback` — the same
  progress-bar-plus-current-symbol renderer (`_Tracker`) manual `/scan` already used, previously
  never wired up for the 15-min loop, which ran it with `dashboard_callback=None` (silent) by
  design. `_make_editor` (the message-editing closure) is now a shared module-level helper in
  `src/notify/approval_service.py` instead of duplicated per call site.

**Known limitation, not addressed here:** a symbol that individually times out *without*
tripping the 3-in-a-row breaker is not added to the retry queue — that's the older, separate
per-symbol-timeout behavior (the run continues normally), out of scope for this fix.

---

## Bugs fixed & operational mitigation (2026-08-27 — Gateway connectivity investigation)

Investigated a "data always feels stale/slow" report. A live diagnostic probe ruled out market
data entitlements — real-time stock quotes, IBKR-computed option greeks/IV/open-interest, and
zero subscription-error codes (354/10090/10091/10167/10197) came back cleanly. The real cause,
found by filtering `logs/system.log` down to one cleanly-bounded real process window: genuine
`Error 1100` ("half-dead socket") incidents during actual Friday RTH, plus a 5+ hour disconnected
stretch after Gateway's nightly forced restart, consistent with nobody being available (SGT
daytime = US pre-market/overnight for this account) to re-authenticate.

- **`pytest` runs were writing into the same `logs/system.log` as production**, discovered when a
  burst of ~200 near-simultaneous "RTH cycle starting" lines was initially mistaken for a crash
  loop before a `unittest/mock.py` frame in the traceback gave away that it was test
  failure-injection (`RuntimeError("boom")`, `RuntimeError("telegram down")`), not a real
  incident. **Fixed:** `src/common/logging.py`'s `setup_logging()` now routes the file handler to
  `logs/test.log` whenever `"pytest" in sys.modules` — pytest imports itself before collecting
  any test module, so this reliably separates the two before any module-level `get_logger()` call
  fires. Console output is unaffected.
- **Operational mitigation (not a code change): IBC-automated Gateway login.** The half-dead-socket
  detection/recovery already built into the intraday loop (see the 2026-06-23/06-24 entries below)
  is a complementary, later-stage layer — it recovers *during* a scan once Gateway is reachable
  again, but can't help while Gateway is sitting fully logged out for hours. `scripts/ibc/
  start_gateway.sh` (new) wraps [IBC](https://github.com/IbcAlpha/IBC) to automate the login
  screen and, once `AutoRestartTime` is set in Gateway's own Lock-and-Exit config, the daily
  restart without a fresh login/2FA. It cannot auto-approve an IBKR Mobile push-notification 2FA
  prompt — a human tap is still needed at minimum once a week (the mandatory Sunday cold restart).
  See `SETUP.md` §4 "Automating Gateway login with IBC".
- **Follow-up incident, same day:** a genuine `Error 1100` half-dead-socket episode hit during
  the 09:30 ET forced full sweep (3 consecutive symbol-level chain timeouts on TSLA/TTD/UBER
  aborted the run at 38/46 symbols, correctly producing the 🛑 *Scan blocked* Telegram message —
  see the 2026-06-24 half-dead-socket entry below; this was the circuit breaker working as
  designed, not a bug). Two real gaps surfaced while investigating it:
  - **`_NoiseFilter`'s consecutive-repeat suppression didn't fire for chain-probe noise.**
    `reqSecDefOptParams` returns strikes as the union across *all* expirations, so the
    expiration × strike × right cross-product in `get_option_chain_quotes[_async]` inevitably
    fires "Unknown contract" / "No security definition" for many combos that don't exist —
    expected noise the filter exists to collapse. But those "Unknown contract" lines alternate
    `right='C'`/`right='P'` every other line, and that token sat inside the filter's 120-char
    dedup key untouched by digit-normalisation, so consecutive lines never shared a key and the
    run-length suppression never engaged — a single symbol's chain fetch could emit hundreds of
    un-suppressed lines. **Fixed:** `_NoiseFilter` now normalises `right='[CP]'` before keying,
    same as it already does for digits.
  - **`/status` could hang forever with no reply during a half-dead socket.**
    `isConnected()` only reflects the TCP/exec-socket handshake, which the half-dead state
    leaves up — so `handle_status_command` took the "IBKR connected" branch and awaited
    `get_account_snapshot_async` (`accountSummaryAsync`) with no timeout, unlike every other
    live IBKR call site (`probe_market_data_health`, fill reconciliation, chain fetch) which
    already guards against exactly this state. **Fixed:** bounded by
    `market_data.health_probe_timeout_seconds`; on timeout it logs a warning and still replies
    with positions/pending-approvals/open-orders, just without the account-totals line. See the
    new `SETUP.md` troubleshooting row.
  - Also observed 3× `Error 10197` ("No market data during competing live session") during this
    incident — the existing `SETUP.md` troubleshooting row already covers it (check for another
    logged-in IBKR session/device on the same account); not a new gap, just confirmed live.
- **Second follow-up incident, same day: a stop/restart left an orphaned `run_approval_service`
  that starved the new session of both its clientIds and its Telegram polling.** `scripts/
  start.py`'s `_stop_all` sent `SIGTERM` to each child and called `sys.exit(0)` immediately, with
  no check that the child actually exited — a hung shutdown (mechanism not fully diagnosed;
  didn't respond to a manual `SIGTERM` either 30+ minutes later, only `SIGKILL`) left a survivor
  that kept polling Telegram (`telegram.error.Conflict: terminated by other getUpdates request`)
  and, transiently, held clientIds 14/15. The next `scripts.start` invocation's exec/scan
  connections lost the clientId race, exhausted `connect_with_retry`'s bounded attempts (~30s),
  and gave up — critically, **`AutoReconnect` is only ever attached after a connection succeeds
  once**, so a startup-connect failure has no retry path at all for the rest of that process's
  life. Symptom: `/status` → "IBKR connection unavailable" and `🔁 0 intraday scans run`
  indefinitely, even long after IB Gateway itself was healthy again (confirmed by the
  **monitor's** independent connection, which reconnected fine via its own persistent
  `AutoReconnect` loop) — because the intraday loop's `if not ib_scan.isConnected(): continue`
  guard silently skipped every cycle, including the forced full sweep that's supposed to fire on
  the first cycle after a restart. **Fixed:** `_stop_all` now waits up to `STOP_GRACE_SECONDS`
  (10s) for each child and SIGKILLs any that don't exit; `scripts.start` also now scans for and
  kills any *other* process running one of this project's own daemon modules before launching new
  ones, so a stray survivor — however it was orphaned — can no longer contest the new session.
  Live-validated the same day: on the very next restart the new startup scan caught and killed a
  leftover process before the daemons launched, and exec/scan/monitor all connected cleanly. See
  the new `SETUP.md` "Clean stop, guaranteed" note and troubleshooting row.
  - **Known limitation, not addressed by this fix:** the underlying startup-connect-failure gap
    (no retry once `connect_with_retry` exhausts its bounded attempts) is still there in
    principle — this fix prevents the clientId collision that triggers it in the stop/restart
    case, but a `/status` that fails to connect for some *other* reason at startup (e.g. Gateway
    still mid-restart) would still need a manual restart to recover. Worth a follow-up: retry the
    initial connect in the background instead of giving up permanently.

---

## Bugs fixed (2026-08-21 — intraday full-sweep guarantee + overrun frequency)

- **A full 46-symbol intraday sweep routinely takes 15–25 minutes — longer than the 15-min
  cadence itself — because per-symbol option-chain qualification wastes most of its round trips
  on (strike, expiration, right) combinations that don't exist.** Investigated after a repeat of
  the "previous scan still running (overran the interval)" warning (first fixed structurally
  2026-08-13, above — this is about *why* full sweeps are slow enough to trigger it in the first
  place, not the scheduling bug itself). `reqSecDefOptParams` returns strikes as a union across
  *all* expirations for the underlying, not per-expiration, so `get_option_chain_quotes_async`'s
  `strikes × expirations × 2 rights` cartesian submits many contracts to `qualifyContractsAsync`
  that IBKR reports back as `Error 200: No security definition has been found`. Traced one
  instance: AAPL alone submitted ~300 candidate contracts and took ~24s of wall-clock qualify time
  before a single quote returned, almost entirely spent on doomed round trips. Across a 46-symbol
  universe that's 15–25 minutes for a full sweep — already at or past `scheduler.intraday_loop_minutes`
  (15) before profit-take/loss-exit/reconciliation are even counted. This qualification waste is
  not fixed here (would mean replacing the blind cartesian with a per-expiration
  `reqContractDetails` lookup in `src/ibkr/market_data.py` — a larger change; the "Built
  2026-08-28 — option-chain fetch" entry above trims the same cartesian's OTM-vs-ITM waste, a
  smaller, complementary cut that leaves this per-expiration-existence waste untouched); what
  changed here is when and how often the full sweep that pays this cost gets triggered:
  - `market_data.force_full_scan_minutes` raised from 90 to 120 minutes — fewer full sweeps per
    session means fewer chances to collide with the 15-min cadence, at the cost of a slightly
    longer staleness ceiling for quiet-but-drifting symbols.
  - **The full sweep at process start was previously incidental, not guaranteed:** it only
    happened because the overnight (or, as observed 2026-08-21, a 6-day idle) gap since the last
    fetch always happens to exceed the staleness timer — nothing enforced it directly, so a
    same-day restart shortly after a full sweep could fall straight into a narrow
    materiality-gated cycle with a stale full picture. `_compute_material_symbols` now accepts
    `force_full_sweep: bool`, which bypasses the staleness/materiality logic entirely.
    `_intraday_scan_loop` tracks `bot_data["startup_full_sweep_done"]` (in-memory — unset on every
    process restart) and passes `force_full_sweep=True` into the first cycle it actually gets to
    spawn a scan; a cycle that `continue`s earlier for an unrelated reason (halted, past
    `entry_cutoff`, unhealthy data-farm probe, or a still-running previous scan) leaves the flag
    unset, so the next eligible cycle forces it instead — the flag is only set at the point a scan
    is actually spawned, mirroring the existing `scan_running` lease pattern. A manual `/scan`
    already sweeps everything, so `handle_scan_command` sets the same flag to spare the next
    intraday cycle a redundant forced sweep.
  - `src/orchestrator/scan.py`: `_compute_material_symbols`, `run_scan`, `_run_scan_body` all gain
    a `force_full_sweep` parameter.
  - `src/notify/approval_service.py`: `_run_intraday_scan` gains `force_full_sweep`; the
    `startup_full_sweep_done` decision lives in `_intraday_scan_loop`; `handle_scan_command` sets
    the flag after a successful manual sweep.
  - `config/settings.yaml`: `market_data.force_full_scan_minutes: 120` (previously an unset code
    default of 90 in `src/common/config.py`, now explicit).
  - Regression tests: `tests/test_scan_materiality.py::test_force_full_sweep_bypasses_gate_entirely`,
    `tests/test_notify.py::test_run_intraday_scan_forwards_force_full_sweep` and
    `::test_intraday_loop_forces_full_sweep_only_on_first_spawned_cycle`.
  - **Known limitation, unchanged by this fix:** a full sweep can still overrun 15 minutes and
    cost one skipped cycle — this only guarantees *when* the mandatory full sweep happens
    (session start) and reduces *how often* it recurs (120 vs 90 min), it does not make any single
    full sweep faster. The qualification-waste root cause above remains open.

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
come from live quotes, so the exact figures drift run to run; the binding reasons do not).

**Stale as of 2026-08-27:** the `would_own` list below is the *pre-restructure* one. The
2026-08-27 universe restructure kept the count at 46 but changed the composition — CRM/COIN/XLV/
XLP/TLT dropped out, TQQQ/UPRO/SOXL/MAGS were added — so this run does not cover the new names,
none of which have been through `capacity_report.py`. Re-run it before treating any of MAGS/TQQQ/
UPRO's collateral/risk-unit sizing as verified; nothing about the sizing *logic* changed, only
which symbols feed it.

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
- **Order idempotency (fixed, including the race — this bullet was stale):** `candidate_id` is a
  deterministic hash, so a re-scan — especially the 15-min automated loop — regenerates the
  identical candidate. Both order-creation paths (`sender._auto_queue_candidates`,
  `approval_service._process_button`) consult `storage.orders.has_active_order` and refuse to
  create a second order when one is already QUEUED/SUBMITTED/FILLED/PARTIAL for that candidate.
  Combined with covered-call sizing that nets out existing short calls
  (`generate_cc_candidates(existing_short_calls=…)`), this closes the path where the automated
  loop stacked duplicate writes into naked short calls. The concurrent-race residual this bullet
  used to describe ("two concurrent callbacks for two different approvals of the same candidate
  could still race") was **already closed** by the time this line was last edited: `db.py`'s
  `_PARTIAL_INDEXES` has carried `uq_orders_active_candidate` — a DB-level partial unique index
  on `orders(candidate_id) WHERE state IN ('queued','submitted')` — since the "Harden
  automated-mode safety" commit, and `_process_button`'s `except IntegrityError` (turning the
  race into a safe "Already processing" no-op rather than a duplicate order or a crash) has
  covered it since the same commit. `tests/test_notify.py::test_partial_index_blocks_two_working_orders`
  exercises the DB constraint directly; `test_manual_approve_skips_duplicate_when_active_order_exists`
  exercises the full two-approvals-one-candidate path. Found stale during the 2026-09-11
  known-issues review — no code change needed here, only this correction.
- **Post-reconnect fill recovery (fixed, including the "continuously" residual — this bullet
  was stale).** `execution/reconciliation.py::reconcile_orphan_fills` queries
  `ib.reqExecutionsAsync()` and recovers any SUBMITTED order whose fill event was lost during a
  disconnect — matching by broker order id, then by contract — writing the missing FillRow,
  marking the order FILLED/PARTIAL, and notifying Telegram. It is strictly additive (only
  records proven fills; never cancels or resubmits), so it cannot cause a double trade. The
  "runs only at startup" residual this bullet used to describe was **already closed** by the
  time this line was last edited: SYSTEM_REVIEW F7 (see "Addressed SYSTEM_REVIEW.md findings"
  below) wired `reconcile_orphan_fills`/`reconcile_external_closes` into step 1b of every
  intraday RTH cycle (`approval_service._intraday_scan_loop`), not just the startup call — a
  fill that lands during a mid-session reconnect is recovered within one `intraday_loop_minutes`
  interval, not only on the next restart. Found stale during the 2026-09-11 known-issues review;
  `tests/test_notify.py::test_intraday_loop_runs_periodic_fill_reconciliation_when_exec_is_connected`
  added as a regression guard on the wiring itself (the recovery logic was already covered by
  `test_reconcile_recovers_missed_fill` and friends). No code change, only this correction.
- **`next_earnings=None` bypass (reviewed 2026-09-11, kept as-is by design):** When yfinance
  cannot provide an earnings date, the earnings blackout gate is skipped. ETFs never earn;
  individual stocks without calendar data pass silently — the two cases are indistinguishable
  from `FundamentalStats.next_earnings` alone (both are `None`), so there is no cheap way to
  warn on one and not the other. Considered and deliberately not changed: an opt-in
  `events.block_when_earnings_unknown` config flag (default off) would let an operator reject
  non-ETF candidates with no resolvable earnings date, but the decision was to leave today's
  permissive behavior in place rather than ship a new, off-by-default knob nobody asked to
  turn on. The related staleness gap — a *known* earnings date going stale between scan and
  execution — is fixed; see the "Overnight stale data" entry in the 2026-09-11 "Bugs fixed"
  section above.

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
