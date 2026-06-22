# IBKR Options Income System

A semi-autonomous options-income trading system for an Interactive Brokers account. It scans your
holdings and a watchlist every 15 minutes during market hours, scores and ranks covered-call and
cash-secured-put opportunities, gets a plain-English review from Claude, and sends the top candidates
to your phone via Telegram.

> **Two operating modes.** In **MANUAL** mode (default) every trade requires your explicit Telegram
> approval before touching the broker. In **AUTOMATED** mode the system executes trades
> autonomously during RTH and auto-closes positions at 50% profit — toggle with `/mode`.
> Every order is re-validated by the deterministic risk engine before it executes regardless of mode.
> In AUTOMATED mode the system trades the **deterministic, gate-passing slate**; Claude's review is
> shown for the record but never filters or gates what executes (the fence). To raise the AUTO bar,
> raise `weights.min_candidate_score` — not via Claude.

---

## What it does

| Time | What happens |
|---|---|
| **Every 15 min (RTH)** | Intraday loop: checks profit-take targets (50% rule), runs a fresh scan (full sweep on first cycle each session); in AUTOMATED mode executes autonomously, in MANUAL mode sends approval requests |
| **During market hours** | Event-driven monitor watches open positions for delta drift, IV spikes, and early-assignment risk; alerts you to roll when needed |
| **4:15 PM ET (auto)** | End-of-day report: P&L summary, journal entry, tomorrow's watchlist |
| **Any time** | Telegram bot commands (see below) — query the system interactively from your phone |
| **When you approve** | Execution engine re-validates, builds a limit order at mid-price, places it, and confirms the fill back to Telegram |

### Telegram commands

| Command | What it does |
|---|---|
| `/scan` | Run a full on-demand pipeline scan (CC/CSP/buy opportunities) — full universe sweep, always reviews fresh |
| `/scan AAPL` | Single-ticker scan: fetch option chain for one symbol, run analytics, show best CC/CSP/buy result with a Claude/Ollama verdict and a plain-English premium read; when a strategy has no qualifying option, shows the closest failed contract and *why* it was rejected |
| `/mode` | Show current trading mode (MANUAL / AUTOMATED) and toggle between them |
| `/status` | Compact overview: account summary + all active short options sorted by expiry + pending approvals |
| `/positions` | Live portfolio: stocks and options with market value and unrealized P&L |
| `/account` | Account balances: net liquidation, buying power, margin, excess liquidity |
| `/pending` | List all pending approvals with score and time-to-expiry |
| `/fills` | Recent fills from the last 7 days with quantity, price, and credit received |
| `/calendar` | Per-day P&L calendar for the last 30 days (net premium cashflow per day) |
| `/campaigns` | Wheel campaigns per symbol: CSP→assignment→CC chain with cumulative net premium and adjusted cost basis |
| `/campaigns open` | Same as `/campaigns` but filtered to open (in-progress) campaigns only |
| `/expire` | Expire all pending approvals (clears the queue without executing) |
| `/profile` | Show the active trading profile (conservative / balanced / aggressive / default) |
| `/profile conservative` | Switch to the named profile — overlays delta/DTE/IV/score-floor onto base config |
| `/health` | System health check: IBKR connections, database, time since last scan, pending/open counts |
| `/help` | List all commands |

### Telegram topic routing

Messages are routed to separate forum topics so each thread stays focused. Defaults match
the IDs listed below; override any `TELEGRAM_THREAD_*` variable in `.env` to match your group.

| Topic (thread ID) | Env var | Content |
|---|---|---|
| **2** (`TELEGRAM_THREAD_SCAN`) | `TELEGRAM_THREAD_SCAN` | Scan-started pings, startup notification, overrun warnings, quiet-cycle heartbeat — general ops/system messages |
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
| `config/skills/` | Human-promoted reasoning skills (active/proposed/rejected) injected into review prompts |
| `src/ibkr/` | IBKR connection, live market data, option chains, portfolio |
| `src/analytics/` | IV rank, technicals, fundamentals, liquidity scoring; `realized_vol.py` for the IV/RV richness gate (C1) |
| `src/strategies/` | Covered-call, cash-secured-put, rolling candidate generation |
| `src/engine/` | Scoring, decision ranking, deterministic risk gate |
| `src/claude/` | Headless `claude -p` runner + local-LLM Ollama backend (`backend: "ollama"` is active by default — see SETUP.md §14), output parser, and learning-loop outcome recorder |
| `src/claude/eval/` | Outcome ledger, close reconciler, and verdict scoring (calibration + EV vs baseline) |
| `src/claude/skills/` | Skill loop: propose from labeled history, human-gated promotion, prompt injection |
| `src/execution/` | Order building and execution via IBKR |
| `src/notify/` | Telegram messaging and approval service |
| `src/monitor/` | Event-driven intraday position monitoring |
| `src/backtest/` | Offline CC/CSP income backtest (Black-Scholes-synthesised premiums over historical prices) |
| `src/orchestrator/` | EOD report and on-demand scan pipeline |
| `src/storage/` | SQLite database models, session management, and order-creation idempotency |
| `Archive/dashboard/` | Streamlit read-only dashboard (archived; restore to `dashboard/` to reinstate) |
| `scripts/` | Command-line entrypoints |
| `tests/` | pytest suite (IBKR mocked; no TWS needed) |

---

*This software is for personal use. Trading options involves substantial risk of loss.*
