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
| `settings.yaml` | IBKR connection (host, ports, client IDs), scan timing, execution timeouts, logging |
| `risk_limits.yaml` | Per-ticker concentration limits, delta ranges, DTE windows, earnings blackout, minimum return |
| `universe.yaml` | Your watchlist (tickers to scan for CCs) and `would_own` list (stocks OK to be assigned via CSPs) |
| `scoring_weights.yaml` | How much weight IV rank, technicals, fundamentals, and liquidity each get when ranking candidates |

**Rule:** Secrets (passwords, tokens) never go in these files. They go in `.env`.

---

### `src/ibkr/` — The IBKR connection layer

Handles everything that talks directly to Interactive Brokers via the `ib_async` library.

| File | What it does |
|---|---|
| `connection.py` | Opens and manages the connection to TWS/Gateway; auto-reconnects on drops; enforces one connection per process |
| `market_data.py` | Fetches live quotes, option chains, Greeks (delta/theta/IV), and historical IV data |
| `portfolio.py` | Reads your current positions, account balance, buying power, and margin |
| `contracts.py` | Builds valid IBKR contract objects for stocks and options; runs `qualifyContracts` to validate them |

---

### `src/analytics/` — The analysis layer

Computes signals that determine whether a trade is worth taking.

| File | What it calculates |
|---|---|
| `iv.py` | **IV Rank** (how high is current implied volatility vs. the past year?) and **IV Percentile**; also term structure slope and put/call skew |
| `technicals.py` | RSI, MACD, moving averages, ATR (volatility), support/resistance levels, and a market regime classifier (trending up/down/sideways) |
| `fundamentals.py` | Free cash flow, debt levels, dividend safety, earnings quality, and next earnings date (via yfinance) |
| `liquidity.py` | Bid/ask spread quality, open interest, and volume — filters out options that are too thinly traded to sell |
| `sentiment.py` | Optional Reddit/social-media sentiment score (Phase 11 feature) |

---

### `src/strategies/` — Trade candidate generators

Each module takes the analytics data and generates specific trades you could place.

| File | What it generates |
|---|---|
| `covered_call.py` | Covered call candidates: for each stock you own, finds the best call strike to sell (target delta, expiry, annualized yield) |
| `cash_secured_put.py` | Cash-secured put candidates: for `would_own` stocks, finds put strikes that offer good yield without excessive assignment risk. Contract count is sized off **available cash** (`total_cash`), not margin buying power — a cash-secured put must be cash-secured; the Rules Engine then caps the *total* across all CSPs. |
| `rolling.py` | Roll candidates: for existing short options approaching expiry or breaching delta limits, suggests the best roll-forward trade |
| `buy_candidates.py` | Buy-to-own candidates: stocks from the watchlist worth buying specifically so you can sell covered calls against them |

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
| `runner.py` | Shells out to `claude -p` (the CLI), passes candidate data as JSON, and captures the response |
| `parser.py` | Validates and parses Claude's JSON response into a structured `ClaudeReview` object. On any failure, returns an empty result — the pipeline always continues. |
| `prompts/` | Prompt templates for different scenarios (morning review, roll alerts, EOD journal) |

**Important:** Claude is enrichment only. If it is unavailable or returns bad output, the system
sends the Rules-Engine-approved list to Telegram without Claude commentary. Claude never places,
sizes, or gates orders.

---

### `src/execution/` — Order placement

Handles everything between your Telegram approval and the order reaching IBKR.

| File | What it does |
|---|---|
| `order_builder.py` | Builds a mid-price limit order for an approved candidate (never market orders) |
| `executor.py` | Places the order via IBKR, monitors for a fill, handles timeouts and cancellations, records the fill |
| `approval.py` | Maps a Telegram approval event → re-validates against the Rules Engine with a fresh live quote → hands off to executor |

---

### `src/notify/` — Telegram messaging

| File | What it does |
|---|---|
| `sender.py` | One-shot message sender: sends text and formatted messages to your Telegram (used by morning scan and EOD report) |
| `approval_service.py` | The long-running daemon: runs the Telegram polling loop, handles Approve/Reject callbacks, drives order execution, and serves all interactive query commands (see table below) |
| `formatters.py` | Converts all data types into nicely formatted Telegram MarkdownV2 messages: trade candidates with full Claude reasoning, positions, account, health, status |

**Telegram commands served by `approval_service.py`:**

| Command | What it does |
|---|---|
| `/scan` | Run a full on-demand pipeline scan (CC/CSP/buy opportunities) |
| `/positions` | Show live portfolio positions (stocks + options) with P&L |
| `/account` | Show account balances: net liquidation, buying power, margin, excess liquidity |
| `/health` | System health check: IBKR connection status, DB, last scan time, open orders |
| `/status` | Compact overview: account + active short options + pending approvals |
| `/help` | List all available commands |

---

### `src/monitor/` — Intraday position watching

Watches your open positions during market hours and fires alerts when action may be needed.

| File | What it does |
|---|---|
| `intraday.py` | Subscribes to live IBKR price feeds for each open position; runs checks every tick |
| `triggers.py` | Defines trigger conditions: delta too high (roll needed), DTE too short, IV spike, ex-dividend risk. Each trigger calls Claude for a roll recommendation and sends a Telegram alert. |

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
| `db.py` | Database connection and session management via SQLAlchemy |
| `models.py` | Defines the database tables: `candidates`, `approvals`, `orders`, `fills`, `iv_history`, `journal`, `claude_memory` |

Every stage of the pipeline writes its results here. This means:
- If a scan crashes halfway through, the next run can pick up where it left off.
- The dashboard reads from this database — no IBKR connection needed.
- You can inspect any trade decision by querying the database.

---

### `src/common/` — Shared building blocks

| File | What it does |
|---|---|
| `schemas.py` | Pydantic data models that all modules use to pass data between each other (`TradeCandidate`, `PositionSnapshot`, `ScoreCard`, `RiskVerdict`, `ClaudeReview`, etc.) |
| `config.py` | Loads and validates `config/*.yaml` and `.env` |
| `logging.py` | Structured logging setup |

**Rule:** Modules never pass raw IBKR objects to each other — they always convert to these shared
schemas first. This keeps modules independent and testable.

---

### `dashboard/` — The Streamlit web dashboard

A read-only web interface for monitoring the system. Start it with
`streamlit run dashboard/app.py` and open `http://localhost:8501`.

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
| `run_morning.py` | `python -m scripts.run_morning` | Runs the morning scan (also called by cron) |
| `run_eod.py` | `python -m scripts.run_eod` | Runs the EOD report (also called by cron) |
| `run_approval_service.py` | `python -m scripts.run_approval_service` | Starts the long-running approval + execution daemon |
| `run_monitor.py` | `python -m scripts.run_monitor` | Starts the intraday position monitor |
| `backfill_iv.py` | `python -m scripts.backfill_iv` | One-time: seeds one year of IV history for the universe |

---

### `tests/` — The test suite

Unit tests for every module. IBKR is mocked, so tests run without a live TWS connection.

Run with: `python -m pytest`

---

## Process architecture (what runs where)

The system splits into separate processes, each with its own IBKR connection ID, to avoid
conflicts:

| Process | When it runs | Client ID | What it owns |
|---|---|---|---|
| `morning_scan` | One-shot at 9:45 AM (cron) | 11 | Full pipeline → Claude → Telegram send |
| `eod_report` | One-shot at 4:15 PM (cron) | 11 | P&L + journal → Telegram |
| `approval_service` | Always-on daemon | 14 | Telegram button callbacks + order execution |
| `intraday_monitor` | Always-on during market hours | 12 | Live position watching + roll alerts |
| `backfill_iv` | One-time manual | 13 | Historical IV data seeding |

One-shots connect to IBKR, do their work, and disconnect. The daemons run continuously.

---

## Data flow between modules

All modules exchange data through the Pydantic schemas in `src/common/schemas.py`. The key objects:

| Schema | What it represents |
|---|---|
| `PositionSnapshot` | A current open position (symbol, quantity, cost basis, Greeks) |
| `MarketContext` | The full market context for a scan (positions, quotes, IV history) |
| `ScoreCard` | All analytics scores for a symbol (IV rank, RSI, fundamentals, liquidity) |
| `TradeCandidate` | A specific trade proposal (symbol, strategy, strike, expiry, premium, scores, and `next_earnings` for the earnings-blackout gate) |
| `RiskVerdict` | The Rules Engine's decision: PASS or REJECT, with reasons |
| `ClaudeReview` | Claude's structured review of a candidate (recommendation, rationale, risks) |

---

## Key invariants (things that must never change)

1. **The Rules Engine is the only path to execution.** Nothing bypasses it.
2. **Claude never places, sizes, or blocks orders.** It enriches; it does not control.
3. **One IBKR client ID per process.** Sharing IDs causes connection conflicts.
4. **Secrets live only in `.env`.** Never in code, logs, or YAML.
5. **All option orders use LimitOrder at mid-price.** Never market orders.
6. **`qualifyContracts` runs before every order submission.**
