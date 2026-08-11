# IBKR Options Income System

A semi-autonomous options-income trading system for an Interactive Brokers account. It scans your
holdings and a watchlist every 15 minutes during market hours, scores and ranks covered-call and
cash-secured-put opportunities, gets a plain-English review from Claude, and sends the top candidates
to your phone via Telegram.

> **A four-rung autonomy ladder**, not a binary switch. `OBSERVE` (default, fresh install) proposes
> only — nothing opens, and Approve/Reject buttons are withheld. `MANUAL` requires your explicit
> Telegram tap on every trade. `WHITELIST` auto-opens listed symbols and sends everything else to
> you. `FULL` auto-opens anything that clears the deterministic gates. Change rungs with
> `/autonomy <level>` — promotion up a rung is refused until the account has demonstrated evidence
> (>=20 fills, >=60% fill rate, a risk-reducing close having fired); demotion is always allowed.
> Every order is re-validated by the deterministic risk engine before it executes at every rung.
> Auto-close (profit-take + loss-exit) is a **separate** switch, `automation.auto_close_enabled`,
> independent of the autonomy rung. At WHITELIST/FULL the system trades the **deterministic,
> gate-passing slate**; Claude's review is shown for the record but never filters or gates what
> executes (the fence). To raise the auto-open bar, raise `weights.min_candidate_score` — not via
> Claude.

---

## What it does

| Time | What happens |
|---|---|
| **Every 15 min (RTH)** | Intraday loop: checks profit-take/loss-exit targets, runs a fresh scan (full sweep on first cycle each session); candidates a symbol's autonomy rung clears (WHITELIST/FULL) auto-execute, everything else sends an approval request (buttons withheld at OBSERVE) |
| **During market hours** | Event-driven monitor watches open positions for delta drift, IV spikes, and early-assignment risk; alerts you to roll when needed |
| **4:15 PM ET (auto)** | End-of-day report: P&L summary, journal entry, tomorrow's watchlist |
| **Any time** | Telegram bot commands (see below) — query the system interactively from your phone |
| **When you approve** | Execution engine re-validates, builds a limit order at mid-price, places it, and confirms the fill back to Telegram |

### Telegram commands

| Command | What it does |
|---|---|
| `/scan` | Run a full on-demand pipeline scan (CC/CSP/buy opportunities) — full universe sweep, always reviews fresh. Each strategy thread also gets an **"Assessed — not approved"** block listing the contracts that were priced and set aside, with the gate each failed |
| `/scan AAPL` | Single-ticker deep-dive: fetch option chain for one symbol, run analytics, show best CC/CSP/buy result with a Claude/Ollama verdict. Holistic context: a **💬 Sentiment** line (composite StockTwits + news + optional Reddit, 0-100 with 1-day trend), a **🌐 Market & Sector** line (VIX regime + how the name's sector / the broad market are trading + relative strength) and a **🧠 Read** — a plain-English synthesis explaining what the IV/VRP/delta/RSI numbers mean together and the overall sentiment; a **🎯 ideal strike zone + minimum credit** beside the contract actually on offer (derived from support/resistance, expected move, earnings timing and Black-Scholes fair value at realised vol — the credit floor is priced at *that* contract's strike, so "clears fair value" compares like with like), the runner-up qualifying strikes, an **"Other contracts considered"** list naming every contract that didn't make it and why, and a **🎯 Levels** block with the share-entry price. When a strategy has no qualifying option it shows the closest failed contract and *why* — never silence |
| `/autonomy` | Show current autonomy rung (OBSERVE/MANUAL/WHITELIST/FULL) and promotion progress toward the next one |
| `/autonomy <level>` | Change rungs — promotion is refused until the evidence gate (>=20 fills, >=60% fill rate, one risk-reducing close) is met; demotion always succeeds |
| `/status` | Compact overview: account summary + all active short options sorted by expiry + pending approvals |
| `/positions` | Live portfolio: stocks and options with market value and unrealized P&L |
| `/account` | Account balances: net liquidation, buying power, margin, excess liquidity |
| `/pending` | List all pending approvals with score and time-to-expiry |
| `/fills` | Recent fills from the last 7 days with quantity, price, and credit received |
| `/calendar` | Per-day P&L calendar for the last 30 days (net premium cashflow per day) |
| `/campaigns` | Wheel campaigns per symbol: CSP→assignment→CC chain with cumulative net premium and adjusted cost basis |
| `/campaigns open` | Same as `/campaigns` but filtered to open (in-progress) campaigns only |
| `/expire` | Expire all pending approvals (clears the queue without executing) |
| `/health` | System health check: IBKR connections, database, time since last scan, pending/open counts |
| `/help` | List all commands |

### Telegram topic routing

Messages are routed to separate forum topics so each thread stays focused. Defaults match
the IDs listed below; override any `TELEGRAM_THREAD_*` variable in `.env` to match your group.

| Topic (thread ID) | Env var | Content |
|---|---|---|
| **2** (`TELEGRAM_THREAD_SCAN`) | `TELEGRAM_THREAD_SCAN` | Scan-started pings, startup notification, overrun warnings, skipped-symbol card, data-provenance summary — general ops/system messages |
| **52** (`TELEGRAM_THREAD_CSP`) | `TELEGRAM_THREAD_CSP` | Cash-secured put candidates (or "unchanged" digest / "no candidates" diagnostic each cycle) |
| **54** (`TELEGRAM_THREAD_CC`) | `TELEGRAM_THREAD_CC` | Covered-call candidates on currently-held underlyings |
| **56** (`TELEGRAM_THREAD_BUY`) | `TELEGRAM_THREAD_BUY` | Buy-to-own recommendations (stocks worth owning to sell CCs against) |
| **58** (`TELEGRAM_THREAD_ACCOUNT`) | `TELEGRAM_THREAD_ACCOUNT` | Account snapshot: net liq, holdings with nested CCs/CSPs, per-position unrealized P&L % — sent fresh at 09:00 ET then edited in-place each cycle |

## Prerequisites

- Interactive Brokers account with **IB Gateway** installed (recommended over TWS — lighter weight, no UI overhead, same API)
- Python 3.12+
- A Telegram bot token and your chat ID
- The Claude Code CLI installed and authenticated (`claude --version`) — **or**, if you don't have
  `claude -p` access, [Ollama](https://ollama.com) running locally with a model pulled
  (`claude.backend: "ollama"`, see SETUP.md §14)

See **[SETUP.md](SETUP.md)** for the full step-by-step setup guide.

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env          # fill in Telegram token/chat-id and IBKR account
# Start IB Gateway (paper account, API enabled, port 4002)

python -m scripts.healthcheck  # verifies connection, prints account summary
python -m pytest               # all tests pass without IB Gateway
```

## Documentation

| File | What it covers |
|---|---|
| **[SETUP.md](SETUP.md)** | Complete setup from scratch to first live trade |
| **[ARCHITECTURE.md](ARCHITECTURE.md)** | What every folder does, how the system fits together, the process/clientId model, and operational risk handling |
| **[STATUS.md](STATUS.md)** | What's built, what's deliberately not built, tech stack, known limitations, and the live-cutover gate |
| **[UNIVERSE_RESEARCH.md](UNIVERSE_RESEARCH.md)** | Deep-research findings for every ticker in the universe: tier classification, verified prices/IV ranks (Jun 2026), CC vs CSP appropriateness, leveraged-ETF rules, and data-quality notes. Injected into Claude trade reviews. |
| **[COMPETITIVE_RESEARCH_PLAN.md](COMPETITIVE_RESEARCH_PLAN.md)** | Competitive research findings (Puthouse and peer landscape) and phased implementation tracker for borrowed features C1–C11; all 5 phases complete as of 2026-06-22 |
| **`Archive/Improvement_Plans/`** | Historical: REMEDIATION.md, IMPROVEMENT_PLAN.md (N1–N23), IMPROVEMENT_PLAN_2.md, SCAN_EFFICIENCY_PLAN.md, SYSTEM_REVIEW.md, TELEGRAM_ROUTING_PLAN.md — all complete and archived |
| **[CLAUDE.md](CLAUDE.md)** | Contributor and AI-assistant guidance |
| **[ib_async_documentation.md](ib_async_documentation.md)** | IBKR API reference (ib_async library) |

## Safety

- **Paper first.** Live execution is blocked unless `LIVE_TRADING=true` in `.env` *and* the live
  port is configured. The system prints a prominent banner on every start showing which mode is active.
- The **Rules Engine** (`src/engine/risk_engine.py`) is the only path to order execution. It runs
  twice — once when ranking candidates, once again at the moment of execution against a fresh live
  quote. It contains no AI and cannot be bypassed.
- All secrets (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `TELEGRAM_THREAD_SCAN`/`_CSP`/`_CC`/`_BUY`/`_ACCOUNT`, `IBKR_ACCOUNT`) live only in `.env`, which is gitignored.

## Layout

| Path | Purpose |
|---|---|
| `config/` | Tunable YAML: connection settings, risk limits, watchlist, scoring weights |
| `src/ibkr/` | IBKR connection, live market data, option chains, portfolio |
| `src/analytics/` | IV rank, technicals, fundamentals, liquidity scoring; `realized_vol.py` for the IV/RV richness gate (C1); `fair_value.py` computes the **ideal strike zone / minimum credit / action levels** shown beside every contract; `market_conditions.py` (macro backdrop — VIX + VIX term structure, 10y rates, SPY tape, broad-market headline tone) and `sector_context.py` (sector/market backdrop for the single-ticker deep-dive) |
| `src/strategies/` | Covered-call, cash-secured-put, rolling candidate generation. The CC/CSP screens return the contracts they **rejected** alongside those they passed (`_evaluation.py`), each tagged with every gate it failed — so a scan that approves nothing still shows what it looked at and why |
| `src/engine/` | Scoring, decision ranking, deterministic risk gate |
| `src/claude/` | Headless `claude -p` runner + local-LLM Ollama backend (`backend: "ollama"` is active by default — see SETUP.md §14), output parser, and learning-loop outcome recorder |
| `src/claude/eval/` | Outcome ledger, close reconciler, and score-vs-outcome analysis (does `blended_score` predict realized P&L) |
| `src/execution/` | Order building and execution via IBKR |
| `src/notify/` | Telegram messaging and approval service |
| `src/monitor/` | Event-driven intraday position monitoring |
| `src/backtest/` | Offline CC/CSP income backtest (Black-Scholes-synthesised premiums over historical prices) |
| `src/orchestrator/` | EOD report, plus the scan split three ways: `scan.py` (the `run_scan`/`ScanResult` entry point — orchestration, gating, persistence), `scan_pipeline.py` (per-symbol data production: chain fetch, analytics, sentiment, CC/CSP screens — imports nothing from `src/notify/`, so a non-Telegram caller can run a scan), `scan_progress.py` (all presentation: the checklist + progress-bar messages a `/scan` edits in place, and the end-of-run candidate/buy/snapshot/provenance sends) |
| `src/storage/` | SQLite database models, session management, order-creation idempotency, and the `risk_verdicts.py` assessment audit trail (every contract a scan priced and why it was set aside, pruned to 14 days) |
| `Archive/dashboard/` | Streamlit read-only dashboard (archived; restore to `dashboard/` to reinstate) |
| `scripts/` | Command-line entrypoints, including `capacity_report.py` — a read-only account-sizing diagnostic: one row per `would_own` symbol showing how many contracts the account can actually support right now and which constraint would stop the next one |
| `tests/` | pytest suite (IBKR mocked; no TWS needed) |

---

*This software is for personal use. Trading options involves substantial risk of loss.*
