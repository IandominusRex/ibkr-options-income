# System Architecture

A plain-English guide to how the system is built, what each part does, and how they connect.

---

## The big picture

Think of this system as a trading desk with several specialists who each do one job:

1. **Data Collector** — connects to Interactive Brokers and fetches live prices, option chains, and your account positions.
2. **Analysts** — calculate whether now is a good time to sell options on a stock (IV rank, technical trend, fundamentals, liquidity).
3. **Strategy Team** — generates specific trade candidates: "sell the AAPL July 200 call for $1.50".
4. **Risk Manager** — checks every candidate against hard rules before anything can proceed.
5. **Claude** — reviews the top candidates and writes a plain-English explanation of the tradeoffs.
6. **Telegram** — sends the candidates to your phone and collects your Approve/Reject response.
7. **Executor** — once you approve, re-checks the rules one more time with a live quote, then places the order.
8. **Intraday Watch** — monitors open positions during the day and alerts you when a roll is needed.

**You are the final decision-maker.** No order is ever placed without your explicit approval.

---

## How a trade happens (the pipeline)

```
IBKR live data
    ↓
Analytics (IV rank, technicals, fundamentals, liquidity)
    ↓
Strategy modules (generate candidate trades)
    ↓
Decision Engine (score + rank candidates)
    ↓
Rules Engine ← HARD STOP: enforces all risk limits, no AI involved
    ↓
Claude review (plain-English explanation, optional enrichment)
    ↓
Telegram → YOU approve or reject
    ↓
Rules Engine (re-checks with a fresh live quote) ← SECOND HARD STOP
    ↓
Order placed at IBKR (limit order at mid-price)
    ↓
Fill confirmation sent back to Telegram
```

Every step writes its results to the database. If any step fails, the system can resume from where
it left off. If Claude is unavailable, the pipeline continues without it — Claude enriches but
never blocks.

---

## Folder-by-folder guide

### `config/` — Tunable settings

These YAML files control how the system behaves. **You change behavior here, not in code.**

| File | What it controls |
|---|---|
| `settings.yaml` | IBKR connection (host, ports, client IDs), scan timing, execution timeouts, logging. The `claude` section also carries `skills_enabled` (default `true`) — whether promoted reasoning skills are injected into review prompts. The `scheduler.entry_cutoff` key (default `"15:00"`) sets the ET time after which the intraday loop stops surfacing new entries (profit-take checks still run until the close). The `automation` section holds the AUTOMATED-mode circuit breakers: `max_auto_trades_per_day` (cap on new-exposure entry orders per ET day) and `daily_loss_halt_pct` (auto-engage the kill switch on a daily realized-loss breach). |
| `risk_limits.yaml` | Per-ticker concentration limits, delta ranges, DTE windows, earnings blackout, minimum return. The `live_execution` section adds the send-time re-gate knobs: `min_live_premium_ratio` (reject a fill when the live mid has collapsed below this fraction of the approved premium — F2) and `require_ibkr_greeks_when_live` (in LIVE mode, require IBKR-sourced greeks for the delta gate — F6). |
| `universe.yaml` | Your watchlist (tickers to scan for CCs) and `would_own` list (stocks OK to be assigned via CSPs). Tickers are organised into three tiers: Tier 1 core (SPY/QQQ/AAPL/MSFT/NVDA/JPM/GLD), Tier 2 active (AMD/META/AMZN/PLTR/SOFI/HOOD/HIMS/BABA), Tier 3 speculative/high-IV (SOXL/LABU/TSLL/DPST/MARA/RGTI/CRCL). Leveraged ETFs are in `indexes` only — never `would_own`. |
| `scoring_weights.yaml` | How much weight IV rank, technicals, fundamentals, and liquidity each get when ranking candidates |
| `skills/` | Reasoning-skill playbooks: `active/` (injected into review prompts), `proposed/` (Claude-drafted, awaiting human review), `rejected/`. Promotion is a human-gated file move via `scripts.skills`. These shape Claude's verdict + ranking only — never the gates above. |

**Rule:** Secrets (passwords, tokens) never go in these files. They go in `.env`.

---

### `src/ibkr/` — The IBKR connection layer

Handles everything that talks directly to Interactive Brokers via the `ib_async` library.

| File | What it does |
|---|---|
| `connection.py` | Opens and manages the connection to TWS/Gateway; enforces one connection per process. Provides a sync (`connect`) and async (`connect_async` / `async with`) connect with backoff, plus `AutoReconnect` — attached to the long-running daemons (approval service, monitor) it listens on `disconnectedEvent` and reconnects with capped backoff (re-subscribing market data on the monitor) so a TWS drop doesn't silently kill them. |
| `market_data.py` | Fetches live quotes, option chains, Greeks (delta/theta/IV), and historical IV data. Provides both a sync API and an `async` chain fetcher (`get_option_chain_quotes_async`) — the orchestrator uses the async one so every IBKR call runs on the `ib_async` event-loop thread (never a worker thread), respecting the line-limit batching. |
| `portfolio.py` | Reads your current positions, account balance, buying power, and margin. `enrich_positions_with_greeks_async` populates option-position deltas from live model greeks (used by the EOD net-delta-exposure metric, which would otherwise read 0). |
| `contracts.py` | Builds valid IBKR contract objects for stocks and options; runs `qualifyContracts` to validate them |

---

### `src/analytics/` — The analysis layer

Computes signals that determine whether a trade is worth taking.

| File | What it calculates |
|---|---|
| `iv.py` | **IV Rank** (how high is current implied volatility vs. the past year?), **IV Percentile**, term structure slope, put/call skew, and **VRP** (Volatility Risk Premium = current IV% − HV30%; positive means options are pricing in more vol than realized, which is the premium seller's edge) |
| `market_conditions.py` | Fetches market-level signals once per scan (not per symbol). Currently provides **VIX** via yfinance `^VIX`. Returned as a `MarketConditions` schema and attached to `ScanResult`. VIX is shown in the scan completion message. |
| `technicals.py` | RSI, MACD, moving averages, ATR (volatility), support/resistance levels, and a market regime classifier (trending up/down/sideways) |
| `fundamentals.py` | Free cash flow, debt levels, dividend safety, earnings quality, and next earnings date (via yfinance) |
| `liquidity.py` | Bid/ask spread quality, open interest, and volume — filters out options that are too thinly traded to sell |
| `sentiment.py` | Reddit/social-media sentiment scorer; returns a neutral score (50) when Reddit API credentials are absent in `.env`; integrated into the scan pipeline with a 5% weight in `scoring_weights.yaml`. |
| `black_scholes.py` | Black-Scholes delta computation (`bs_delta`). Pure math — no IBKR connection. Used as a fallback by `src/ibkr/market_data.py` when IBKR returns no `modelGreeks` (delayed-data paper accounts). |

---

### `src/strategies/` — Trade candidate generators

Each module takes the analytics data and generates specific trades you could place.

| File | What it generates |
|---|---|
| `covered_call.py` | Covered call candidates: for each stock you own, finds the best call strike to sell (target delta, expiry, annualized yield) |
| `cash_secured_put.py` | Cash-secured put candidates: for `would_own` stocks, finds put strikes that offer good yield without excessive assignment risk. Contract count is sized off **available cash** (`total_cash`), not margin buying power — a cash-secured put must be cash-secured; the Rules Engine then caps the *total* across all CSPs. |
| `rolling.py` | Roll candidates: for existing short options approaching expiry or breaching delta limits, suggests the best roll-forward trade. Roll credit uses a **live quote** for the current contract; if no live quote is found the candidate is skipped. |
| `buy_candidates.py` | Buy-to-own candidates: stocks from the watchlist worth buying specifically so you can sell covered calls against them |
| `_scoring.py` | Shared scoring helpers (`technical_score`, `fundamental_score`, `make_candidate_id`) used by all strategy modules |

---

### `src/engine/` — The decision and safety layer

This is where candidates get ranked and filtered.

| File | What it does |
|---|---|
| `scoring.py` | Normalizes raw analytics scores (IV rank, RSI, etc.) into a 0–100 scale |
| `decision_engine.py` | Combines scores with the configured weights, ranks candidates by total score, and selects the top N |
| `risk_engine.py` | **The safety gate.** Checks hard limits and returns PASS/REJECT with reasons. No AI. `validate_candidates` is **portfolio-aware**: it walks the ranked batch in priority order and enforces *cumulative* limits — per-ticker concentration, per-sector concentration (via the `sectors:` map in `universe.yaml`), total cash-secured-put collateral (`max_csp_allocation_pct`), and the buying-power buffer — so multiple candidates can't each claim the whole account. It also gates per candidate: ROC/yield minimums, IV-rank floor (when known), DTE window, delta (required for income strategies), and the earnings blackout. `validate_live_quote` is the second pass at execution time, re-checking a single candidate against the fresh live quote (delta drift / collapsed mid). |

---

### `src/claude/` — The AI review layer

Invokes Claude to add plain-English reasoning to the top candidates.

| File | What it does |
|---|---|
| `runner.py` | Shells out to `claude -p` (the CLI), passes candidate data as JSON, and captures the response. `review_candidates` also forwards the scan's `MarketConditions` (VIX) so the prompt carries the macro-vol regime — enrichment only, never a deterministic gate. |
| `parser.py` | Validates and parses Claude's JSON response into a structured `ClaudeReview` object. On any failure, returns an empty result — the pipeline always continues. |
| `memory.py` | The learning-loop outcome recorder. Back-fills each `claude_memory` row with what actually happened — `filled` (executor), `user_rejected` (Telegram reject), `risk_rejected` (re-validation), `expired` (TTL) — so later scans inject real outcomes (not just rejections) into the strategist prompt. |
| `prompts/` | Prompt templates: `strategist.py` (morning review — injects `_UNIVERSE_CONTEXT`, a compact tier/IV/assignment reference for every ticker in the universe; also renders a VIX regime line, each candidate's VRP, and any **active reasoning skills**), `roll.py` (roll alerts — also injects active skills), `eod.py` (EOD journal) |

**Important:** Claude is enrichment only. If it is unavailable or returns bad output, the system
sends the Rules-Engine-approved list to Telegram without Claude commentary. Claude never places,
sizes, or gates orders.

---

### `src/claude/eval/` — The verdict learning loop

Turns Claude's reviews into labeled history and scores them. Read-only with respect to trading:
nothing here can place, size, or gate an order — it only observes and measures.

| File | What it does |
|---|---|
| `ledger.py` | The **outcome ledger**. Maps `VerdictLedgerRow` ↔ `VerdictRecord` so the rest of the loop works in schemas, not ORM. At scan time it stores one row per surfaced candidate: the full signal vector Claude saw, its verdict, and the deterministic baseline. Upserts on `candidate_id` and never clobbers a recorded outcome. |
| `baseline.py` | The **deterministic counterfactual** — what the engine would do without Claude. Pure Python over the engine's own slate: every surfaced candidate is a `sell` ranked by `blended_score`; anything not surfaced is `skip`. No LLM, no new tunables. |
| `reconcile.py` | The **close reconciler**. Deterministic, DB-only: joins the ledger against fills/orders/approvals to set the terminal outcome (`expired_worthless` / `closed_early` / `assigned` / `not_filled` / `user_rejected` / `risk_rejected`) and realized P&L. Runs automatically at EOD and via `scripts.reconcile_outcomes`. |
| `metrics.py` | **Verdict scoring**: calibration (reliability buckets + Brier score) and EV of *following Claude* vs *the baseline*, on a held-out window and per month — so the score reflects skill, not the last trade's luck. |

### `src/claude/skills/` — The skill loop

Claude proposes reasoning playbooks from the labeled ledger; a human promotes them; promoted
skills are injected into the strategist/roll prompts. Skills shape **verdict and ranking only** —
never gates, weights, or sizing (see *Key invariants → the fence*).

| File | What it does |
|---|---|
| `registry.py` | Loads/saves/promotes/rejects skill files under `config/skills/{active,proposed,rejected}` and renders the active set for prompt injection. `render_active_skills()` is the **single, auditable path** a skill reaches Claude — imported only by the prompt builders. |
| `proposer.py` | Builds a prompt from the labeled ledger + current evaluation + active skills and shells `claude -p` to draft one new/refined skill into `proposed/`. Fail-soft like the runner. Never auto-promotes. |

---

### `src/execution/` — Order placement

Handles everything between your Telegram approval and the order reaching IBKR.

| File | What it does |
|---|---|
| `order_builder.py` | Builds a mid-price limit order for an approved candidate (never market orders), rounded to the correct tick size ($0.01 below $3.00, $0.05 at/above — penny-pilot rule) |
| `executor.py` | Places the order via IBKR, monitors for a fill, handles timeouts and cancellations, records the fill (with entry IV) and the `filled` learning-loop outcome. Refuses `ROLL` candidates (alert-only; the single-leg builder can't place a two-leg roll). |
| `approval.py` | Maps a Telegram approval event → re-validates against the Rules Engine with a fresh live quote → hands off to executor |
| `position_manager.py` | Buy-to-close execution for short option positions (profit-take auto-closes). Routes the close through the same `OrderRow`/`FillRow` lifecycle and cancel-on-timeout discipline as entries, and is idempotent at the contract level (a deterministic `close:` candidate id + `has_active_order`) so the next intraday cycle can't stack a second buy-to-close. Buy-to-close is risk-reducing, so it deliberately skips the income Rules Engine gate but still records the order/fill. `_auto_close_position` in `notify/` is now just the Telegram-notification wrapper around `close_short_position`. |
| `circuit_breakers.py` | AUTOMATED-mode safety breakers (the risk gate bounds *exposure*; these bound *activity + losses*). `remaining_entry_allowance` enforces `max_auto_trades_per_day`; `daily_loss_breached` auto-engages the kill switch on a daily realized-loss breach. Read-only except for tripping the persisted halt — never feeds the risk engine, scoring, or sizing. Consumed by `process_queued_orders`. |

---

### `src/notify/` — Telegram messaging

| File | What it does |
|---|---|
| `sender.py` | One-shot message sender: sends text and formatted messages to your Telegram (used by morning scan and EOD report) |
| `approval_service.py` | The long-running daemon: runs the Telegram polling loop, handles Approve/Reject callbacks, drives order execution, serves all interactive commands, and runs the 15-minute intraday scan + profit-take loop during RTH |
| `formatters.py` | Converts all data types into MarkdownV2 messages. Covers: trade candidates (with VRP displayed), positions, account, health, status, startup, EOD report, fill confirmations (`format_fill_confirm`), live-order confirmation requests (`format_live_confirm_request`), roll alerts (`format_roll_alert`), pending approvals list (`format_pending_approvals`), fills history (`format_fills_history`), trading mode status (`format_mode_status`), auto-trade summary (`format_auto_trade_notification`), profit alerts (`format_profit_alert`), auto-close results (`format_auto_close_result`) |

**Telegram commands served by `approval_service.py`:**

| Command | What it does |
|---|---|
| `/scan` | Run a full on-demand pipeline scan (CC/CSP/buy opportunities) |
| `/mode` | Show current trading mode (👤 MANUAL / 🤖 AUTOMATED) and toggle. Confirmation prompt appears before enabling AUTOMATED. Mode persists across restarts in SQLite. |
| `/halt` | 🛑 Master kill switch: immediately stop queuing/transmitting all orders. Profit-take *closes* still run (risk-reducing). Persisted in SQLite, so it survives a restart and must be lifted with `/resume`. Optional free-text reason. |
| `/resume` | Release the kill switch; QUEUED orders resume on the next poll cycle. |
| `/status` | Compact overview: account + active short options + pending approvals. Shows a 🛑 HALTED banner when the kill switch is engaged. |
| `/positions` | Show live portfolio positions (stocks + options) with P&L |
| `/account` | Show account balances: net liquidation, buying power, margin, excess liquidity |
| `/pending` | List all pending approvals with score and time-to-expiry |
| `/fills` | Recent fills from the last 7 days with quantity, price, and credit received |
| `/expire` | Expire all pending approvals (clears the queue without acting on them) |
| `/health` | System health check: IBKR connection status, DB, last scan time, open orders |
| `/help` | List all available commands |
| `✅ Approve` / `❌ Reject` inline buttons | Tap to approve or reject each trade candidate (MANUAL mode only; AUTOMATED mode skips these) |
| `[CONFIRM LIVE]` inline button | Second-confirmation tap required for each order when `LIVE_TRADING=true`. Appears as an inline keyboard button on the pre-execution message; times out after `fill_timeout_minutes` if not tapped. |

---

### `src/monitor/` — Intraday position watching

Watches your open positions during market hours and fires alerts when action may be needed.

| File | What it does |
|---|---|
| `intraday.py` | Subscribes to live IBKR price feeds for each open position; runs checks every tick. On subscribe it loads each position's **entry IV** (from the originating fill's `FillRow.entry_iv`, matched by contract) as the IV-spike baseline, and caches the underlying's **fundamentals** (ex-dividend date) — so all four triggers can actually fire. |
| `triggers.py` | Defines stateless trigger-check functions: delta drift, DTE threshold, IV spike, ex-dividend risk. These are pure functions — they do **not** call Claude or Telegram. Claude review and Telegram delivery are handled by `intraday.py::fire_alerts` after triggers fire. |

---

### `src/orchestrator/` — Daily workflows

Ties everything together into the daily automated routines.

| File | What it does |
|---|---|
| `morning_scan.py` | Run by cron at 9:45 AM ET. Connects to IBKR, runs the full pipeline once, sends a Telegram summary, disconnects. |
| `eod_report.py` | Run by cron at 4:15 PM ET. Pulls P&L, generates a journal entry via Claude, sends an end-of-day summary. |
| `scan.py` | The canonical scan pipeline shared by both the morning cron and the on-demand `/scan` Telegram command. |

---

### `src/storage/` — The database

All data is stored in a SQLite database at `data/income_system.db`.

| File | What it does |
|---|---|
| `db.py` | Database connection and session management via SQLAlchemy. For SQLite it enables WAL mode + a 30 s busy-timeout (so the concurrent processes don't hit "database is locked"), applies a lightweight ALTER-in for columns added after the original schema, and creates partial indexes that the model metadata can't express portably (e.g. `uq_orders_active_candidate` — one working order per candidate). |
| `models.py` | Defines the database tables: `candidates`, `risk_verdicts`, `claude_reviews`, `approvals`, `orders`, `fills`, `iv_history`, `option_quotes`, `roll_alerts`, `claude_memory`, `verdict_ledger`, `journal`, `system_settings`. The `fills` row records `action` (SELL credit / BUY debit) and `entry_iv`. `verdict_ledger` (the **outcome ledger**) stores, per Claude-reviewed candidate, the signal vector Claude saw + its verdict + the deterministic baseline, with the realized trade outcome back-filled on close (unique on `candidate_id`, upserted per scan). `system_settings` is a key-value table for runtime toggles (`automated_mode`, the `execution_halted` kill switch + its reason, and the `scan_lease_expiry` cross-process scan lease). `candidates`, `orders`, and `journal` carry unique constraints to prevent duplicate rows. |
| `system_settings.py` | Helper functions for the `system_settings` table: `is_automated_mode()`/`set_automated_mode()`, the kill switch (`is_halted()`/`set_halted()`/`get_halt_reason()`), the cross-process scan lease (`acquire_scan_lease()`/`release_scan_lease()` — serialises full scans so the morning cron and the daemon loop can't compete for the market-data line cap, F5), and `get_setting()`/`set_setting()`. All persist across restarts. |
| `orders.py` | Order-creation idempotency: `has_active_order(session, candidate_id)`. Because `candidate_id` is a deterministic hash, a re-scan (especially the 15-min automated loop) regenerates the same candidate; both order-creation paths (`sender._auto_queue_candidates`, `approval_service._process_button`) consult this guard so a candidate with an order already QUEUED/SUBMITTED/FILLED/PARTIAL is not re-queued — preventing stacked duplicate positions (naked short calls for CCs, which bypass the cumulative exposure gates). A partial unique index `uq_orders_active_candidate` (created in `db.py`) is the DB-level backstop: at most one order in a *working* state (queued/submitted) per candidate. |
| `maintenance.py` | Periodic DB upkeep, both called from the EOD run. `purge_old_option_quotes(retention_days=14)` deletes stale rows from the write-only `option_quotes` audit table so SQLite stays bounded under the 15-min loop's write volume. `backup_database(keep=7)` takes a consistent online snapshot (SQLite backup API) into `data/backups/` and rotates to the last 7 — the system of record (orders, fills, learning history) is no longer a single point of failure. |

Every stage of the pipeline writes its results here. This means:
- If a scan crashes halfway through, the next run can pick up where it left off.
- The dashboard reads from this database — no IBKR connection needed.
- You can inspect any trade decision by querying the database.

---

### `src/common/` — Shared building blocks

| File | What it does |
|---|---|
| `schemas.py` | Pydantic data models that all modules use to pass data between each other (`TradeCandidate`, `PositionSnapshot`, `ScoreCard`, `RiskVerdict`, `ClaudeReview`, etc.). The enrichment-evaluation shapes also live here: `VerdictOutcome`, `BaselineDecision`, `VerdictRecord` (one ledger entry), `CalibrationBucket`/`PolicyStats`/`VerdictEvaluation` (verdict scoring), and `SkillProposal`. |
| `config.py` | Loads and validates `config/*.yaml` and `.env` |
| `logging.py` | Structured logging setup — colourised console output (green INFO, yellow WARNING, red ERROR) and a plain rotating file log; `setup_logging()` is the single call-site used by all entry points |
| `market_hours.py` | Self-contained US equity-market calendar + RTH gate (`is_rth`, `is_new_entry_window`, `session_close`, `is_market_holiday`, `is_early_close`). Computes NYSE full-day holidays and the 13:00 ET early-close sessions for any year — no external calendar dependency. The single source of truth for "is the market open"; both the execution bridge and the intraday loop call it instead of keeping their own weekday-only check. `is_new_entry_window` additionally enforces the configurable `entry_cutoff` time (default 15:00 ET) so no new positions are surfaced in the last hour. |
| `cache.py` | `@daily_cached` — a thread-safe, process-local memoizer keyed by `(args, today)`. Wraps the yfinance hot paths (`get_fundamental_stats`, `_compute_hv30`) so the 15-min intraday loop fetches each symbol at most once per calendar day. `clear_all()` is called by the test harness between cases. |

**Rule:** Modules never pass raw IBKR objects to each other — they always convert to these shared
schemas first. This keeps modules independent and testable.

---

### `Archive/dashboard/` — The Streamlit web dashboard (archived)

The Streamlit dashboard has been moved to `Archive/dashboard/`. To reinstate it, move the
folder back to `dashboard/` at the project root and run `streamlit run dashboard/app.py`.

| Page | What it shows |
|---|---|
| `01_portfolio.py` | Current positions, Greeks, P&L |
| `02_candidates.py` | Today's top trade candidates and their scores |
| `03_orders.py` | Order history, pending orders, fill records |
| `04_journal.py` | Claude-written daily journal entries |
| `05_iv_conditions.py` | IV rank/percentile charts for your universe |

The dashboard never connects to IBKR directly — it reads entirely from the SQLite database.

---

### `scripts/` — Command-line entrypoints

These are the scripts you run directly:

| Script | How to run | What it does |
|---|---|---|
| `healthcheck.py` | `python -m scripts.healthcheck` | Verifies IBKR connection and prints account summary |
| `start.py` | `python -m scripts.start` | **Single-command launcher**: starts both always-on daemons (approval service + monitor) as supervised subprocesses with auto-restart on crash. Accepts `--no-monitor` / `--no-approval` flags. Does NOT start the cron jobs. |
| `run_morning.py` | `python -m scripts.run_morning` | Runs the morning scan (also called by cron) |
| `run_eod.py` | `python -m scripts.run_eod` | Runs the EOD report (also called by cron) |
| `run_approval_service.py` | `python -m scripts.run_approval_service` | Starts the long-running approval + execution daemon |
| `run_monitor.py` | `python -m scripts.run_monitor` | Starts the intraday position monitor |
| `backfill_iv.py` | `python -m scripts.backfill_iv` | One-time: seeds one year of IV history for the universe |
| `reconcile_outcomes.py` | `python -m scripts.reconcile_outcomes` | Reconcile the outcome ledger (deterministic, DB-only). `--assigned <id…>` flags past-expiry shorts that were assigned. Also runs automatically at EOD. |
| `evaluate_verdicts.py` | `python -m scripts.evaluate_verdicts` | Score Claude's verdicts: calibration + EV vs the baseline, held-out + per month. Read-only. `--since`, `--until`, `--json`. |
| `propose_skill.py` | `python -m scripts.propose_skill` | Draft a reasoning skill from the labeled ledger via `claude -p` into `config/skills/proposed/`. Not promoted. |
| `skills.py` | `python -m scripts.skills <list\|show\|promote\|reject\|retire> [name]` | The human gate: review proposed skills and promote them into `active/`. |

---

### `tests/` — The test suite

Unit tests for every module. IBKR is mocked, so tests run without a live TWS connection.

Run with: `python -m pytest`

---

## Process architecture (what runs where)

The system splits into separate processes, each with its own IBKR client ID, to avoid conflicts.
The full registry lives in `config/settings.yaml → ibkr.client_ids`; **never reuse an id across two
processes that run at the same time.**

| Process | When it runs | Client ID | What it owns |
|---|---|---|---|
| `morning_scan` | One-shot at 9:45 AM (cron) | 11 (`engine`) | Full pipeline → Claude → Telegram send |
| `eod_report` | One-shot at 4:15 PM (cron) | 16 (`eod`)\* | P&L + journal → Telegram |
| `intraday_monitor` | Always-on during market hours | 12 (`monitor`) | Live position watching + roll alerts |
| `backfill_iv` | One-time manual | 13 (`backfill`) | Historical IV data seeding |
| `approval_service` | Always-on daemon | **14 (`exec`) + 15 (`scan`)** | Telegram callbacks + order execution (14) and a second connection for `/scan`, `/positions`, `/account`, `/status` (15) |
| `healthcheck` | Manual | 19 | Connection check / account print |
| `trading_skills` MCP | Inside `claude -p` (opt-in) | 20 | Ad-hoc Claude lookups (see `STATUS.md`) |
| dashboard | Optional Streamlit (archived to `Archive/dashboard/`) | 21 | Read-only views (reads SQLite; rarely hits TWS) |

\* `eod_report` uses clientId 16 to avoid conflicts if `morning_scan` (id 11) runs late or is
re-run manually. One-shots connect, work, and disconnect; the daemons run continuously and
self-heal on a dropped socket via `AutoReconnect`.

---

## Data flow between modules

All modules exchange data through the Pydantic schemas in `src/common/schemas.py`. The key objects:

| Schema | What it represents |
|---|---|
| `PositionSnapshot` | A current open position (symbol, quantity, cost basis, and `delta` when enriched) |
| `AccountSnapshot` | Account totals: net liquidation, cash, buying power, margin, excess liquidity |
| `OptionQuote` | A single option contract's live snapshot (bid/ask/last, Greeks, IV). Computed fields: `mid` (bid+ask)/2, falling back to `last`; `spread_pct` as a percentage of mid; `dte` as days-to-expiry in ET timezone. |
| `IVStats` / `TechnicalStats` / `FundamentalStats` | Per-symbol analytics outputs. `IVStats` now includes `vrp` (IV% − HV30%) computed in `iv.py`. |
| `MarketConditions` | Market-level signals fetched once per scan: `vix` (CBOE VIX from yfinance). Attached to `ScanResult`. |
| `ScoreCard` | All analytics scores for a symbol (IV rank, technicals, fundamentals, liquidity, assignment safety) |
| `TradeCandidate` | A specific trade proposal (symbol, strategy, strike, expiry, premium, scores, and `next_earnings` for the earnings-blackout gate) |
| `BuyCandidate` | A buy-to-own stock recommendation. The `rationale` field is currently always an empty string — Claude enrichment for buy candidates is not yet implemented (see `STATUS.md`). |
| `RiskVerdict` | The Rules Engine's decision: PASS or REJECT, with reasons |
| `ClaudeReview` / `RollReview` | Claude's structured review of a candidate / a live position roll |
| `RollAlert` | A fired intraday trigger (delta drift, DTE, IV spike, ex-div) |
| `EODSummary` | End-of-day metrics handed to Claude and stored in the journal |
| `VerdictRecord` | One outcome-ledger entry: the signals Claude saw + its verdict + the deterministic `BaselineDecision` + the back-filled realized `VerdictOutcome`/P&L |
| `VerdictEvaluation` | Held-out scoring of verdicts: Brier calibration + `PolicyStats` for follow-Claude vs baseline |
| `SkillProposal` | A Claude-drafted reasoning skill awaiting human promotion |

(The complete, authoritative list is the set of classes in `src/common/schemas.py`.)

---

## Key invariants (things that must never change)

1. **The Rules Engine is the only path to execution.** Nothing bypasses it.
2. **Claude never places, sizes, or blocks orders.** It enriches; it does not control.
3. **One IBKR client ID per process.** Sharing IDs causes connection conflicts.
4. **Secrets live only in `.env`.** Never in code, logs, or YAML.
5. **All option orders use LimitOrder at mid-price.** Never market orders.
6. **`qualifyContracts` runs before every order submission.**
7. **The fence: skills influence verdict + ranking only.** Promoted reasoning skills reach Claude
   solely through the strategist/roll prompt builders (`render_active_skills`). The risk engine,
   scoring, and sizing never import or see them — gates/weights/limits stay human-edited config.
   Enforced by `tests/test_eval_skills.py::test_skills_never_reach_the_engine`.

---

## Operational risks & how they're handled

The hard parts of this system are operational, not algorithmic. The main failure modes and their
mitigations:

| Risk | Mitigation |
|---|---|
| **TWS/Gateway disconnects mid-session** | `AutoReconnect` on the daemons (backoff + re-subscribe); the monitor self-heals on the next poll; one-shots simply abort and retry next cron. |
| **Market-data line limit (~100)** | Option chains are requested in batches and cancelled between batches; only one symbol's chain is fetched at a time. |
| **clientId conflicts** | Central registry in `settings.yaml`; one id per concurrent process (see the process table above). |
| **Claude unavailable / unparseable** | Strict JSON validation + graceful fallback — the Rules-Engine-approved list still ships to Telegram. Claude never blocks the pipeline. |
| **Approval→execution timing gap** | Orders queue in the DB; the executor re-validates against a fresh live quote + the Rules Engine at send time; off-hours orders wait for RTH; stale approvals expire (TTL). |
| **Order rejects / partial fills / wrong contract** | `qualifyContracts` before every order; LimitOrder at mid (never market); fill monitoring with timeout/cancel; rejects alert back to Telegram. |
| **Early assignment (dividends/ITM)** | The monitor flags ITM-ish short calls near ex-dividend and short options breaching delta/DTE, prompting a roll alert. |
| **Risk-limit bypass / runaway** | The deterministic Rules Engine runs twice (decision time + send time); a buying-power buffer is always reserved; live trading is triple-gated. |
| **Secrets leakage** | `.env` is gitignored and never logged; a Telegram chat-id allowlist means only you can approve. |
| **Paper↔live confusion** | Live execution requires `LIVE_TRADING=true` **and** the live port; a loud startup banner states the active mode and account; each live order needs a second `[CONFIRM LIVE]` tap. |

Database concurrency (multiple processes on one SQLite file) is handled with WAL mode + a 30 s busy
timeout, and no process holds a write transaction open across network I/O.
