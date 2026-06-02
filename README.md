# IBKR Options Income System

A semi-autonomous options-income trading system for an Interactive Brokers account. It scans your
holdings and a watchlist every morning, scores and ranks covered-call and cash-secured-put
opportunities, gets a plain-English review from Claude, and sends the top candidates to your
phone via Telegram — where **you approve every trade** before anything touches the broker.

> **You are always in control.** No order is ever placed without your explicit Telegram approval,
> and every approved order is re-validated by a deterministic safety engine before it executes.

---

## What it does

| Time | What happens |
|---|---|
| **9:45 AM ET (auto)** | Morning scan: fetches live data, scores candidates, Claude reviews the top picks (full reasoning included), sends a Telegram summary |
| **During market hours** | Intraday monitor watches open positions for delta drift, IV spikes, and early-assignment risk; alerts you to roll when needed |
| **4:15 PM ET (auto)** | End-of-day report: P&L summary, journal entry, tomorrow's watchlist |
| **Any time** | Telegram bot commands (see below) — query the system interactively from your phone |
| **When you approve** | Execution engine re-validates, builds a limit order at mid-price, places it, and confirms the fill back to Telegram |

### Telegram commands

| Command | What it does |
|---|---|
| `/scan` | Run a full on-demand pipeline scan (CC/CSP/buy opportunities) — same pipeline as the morning cron |
| `/positions` | Live portfolio: stocks and options with market value and unrealized P&L |
| `/account` | Account balances: net liquidation, buying power, margin, excess liquidity |
| `/health` | System health check: IBKR connections, database, time since last scan, pending/open counts |
| `/status` | Compact overview: account summary + all active short options sorted by expiry + pending approvals |
| `/help` | List all commands |

## Prerequisites

- Interactive Brokers account with TWS or IB Gateway installed
- Python 3.12+
- A Telegram bot token and your chat ID
- The Claude Code CLI installed and authenticated (`claude --version`)

See **[SETUP.md](SETUP.md)** for the full step-by-step setup guide.

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env          # fill in Telegram token/chat-id and IBKR account
# Start TWS or IB Gateway (paper account, API enabled, port 7497)

python -m scripts.healthcheck  # verifies connection, prints account summary
python -m pytest               # all tests pass without TWS
```

## Documentation

| File | What it covers |
|---|---|
| **[SETUP.md](SETUP.md)** | Complete setup from scratch to first live trade |
| **[ARCHITECTURE.md](ARCHITECTURE.md)** | What every folder does, how the system fits together, the process/clientId model, and operational risk handling |
| **[STATUS.md](STATUS.md)** | What's built, what's deliberately not built, tech stack, known limitations, and the live-cutover gate |
| **[CLAUDE.md](CLAUDE.md)** | Contributor and AI-assistant guidance |
| **[ib_async_documentation.md](ib_async_documentation.md)** | IBKR API reference (ib_async library) |

## Safety

- **Paper first.** Live execution is blocked unless `LIVE_TRADING=true` in `.env` *and* the live
  port is configured. The system prints a prominent banner on every start showing which mode is active.
- The **Rules Engine** (`src/engine/risk_engine.py`) is the only path to order execution. It runs
  twice — once when ranking candidates, once again at the moment of execution against a fresh live
  quote. It contains no AI and cannot be bypassed.
- All secrets (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `TELEGRAM_THREAD_ID`, `IBKR_ACCOUNT`) live only in `.env`, which is gitignored.

## Layout

| Path | Purpose |
|---|---|
| `config/` | Tunable YAML: connection settings, risk limits, watchlist, scoring weights |
| `src/ibkr/` | IBKR connection, live market data, option chains, portfolio |
| `src/analytics/` | IV rank, technicals, fundamentals, liquidity scoring |
| `src/strategies/` | Covered-call, cash-secured-put, rolling candidate generation |
| `src/engine/` | Scoring, decision ranking, deterministic risk gate |
| `src/claude/` | Headless `claude -p` runner, output parser, and learning-loop outcome recorder |
| `src/execution/` | Order building and execution via IBKR |
| `src/notify/` | Telegram messaging and approval service |
| `src/monitor/` | Event-driven intraday position monitoring |
| `src/orchestrator/` | Morning scan, EOD report, and on-demand scan pipeline |
| `src/storage/` | SQLite database models and session management |
| `dashboard/` | Streamlit read-only dashboard (portfolio, candidates, IV) |
| `scripts/` | Command-line entrypoints |
| `tests/` | pytest suite (IBKR mocked; no TWS needed) |

---

*This software is for personal use. Trading options involves substantial risk of loss.*
