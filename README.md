# IBKR Options Income System

A semi-autonomous options-income trading system for an Interactive Brokers account. It scans your
holdings and a watchlist every 15 minutes during market hours, scores and ranks covered-call and
cash-secured-put opportunities, gets a plain-English review from Claude, and sends the top candidates
to your phone via Telegram.

**Trade ledger:** every IBKR execution, per-ticker P&L and wheel cost basis, CSV/Flex/live
ingestion, mirrored to Google Sheets — with a `/ledger` web dashboard (overview, trades, per-ticker drill-down, import).

> ⚠️ **Not financial advice.** This is a personal automation project for one IBKR account, shared
> for educational/portfolio purposes. Trading options involves substantial risk of loss — read the
> code and run it on paper before risking real capital. MIT-licensed; see [LICENSE](LICENSE).

**This README is the quick tour.** For the full technical walkthrough of how every part is built,
see **[ARCHITECTURE.md](ARCHITECTURE.md)**; for what's built vs. deliberately not (and the
live-cutover checklist), **[STATUS.md](STATUS.md)**; to fork and run it yourself, jump to
[Quick start](#quick-start) below or the full **[SETUP.md](SETUP.md)** guide.

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
| **During market hours** | Event-driven monitor watches open positions for delta drift, IV spikes, ex-dividend and early-assignment risk, and the mechanical **21-DTE management point** (while closing, rolling, or holding are all still viable — not first at 7 days, deep in the gamma window); alerts you to roll when needed |
| **4:15 PM ET (auto)** | End-of-day report: P&L summary, journal entry, tomorrow's watchlist |
| **Any time** | Telegram bot commands (see below) — query the system interactively from your phone |
| **When you approve** | Execution engine re-validates, builds a limit order at mid-price, places it, and confirms the fill back to Telegram |

### Telegram commands

| Command | What it does |
|---|---|
| `/scan` | Run a full on-demand pipeline scan (CC/CSP/buy opportunities) — full universe sweep, always reviews fresh. Each strategy thread also gets an **"Assessed — not approved"** block listing the contracts that were priced and set aside, with the gate each failed |
| `/scan AAPL` | Single-ticker deep-dive: fetch option chain for one symbol, run analytics, show best CC/CSP/buy result with a Claude/Ollama verdict. Holistic context: a **💬 Sentiment** line (composite StockTwits + news + optional Reddit, 0-100 with 1-day trend), a **🌐 Market & Sector** line (VIX regime + how the name's sector / the broad market are trading + relative strength) and a **🧠 Read** — a plain-English synthesis explaining what the IV/VRP/delta/RSI numbers mean together and the overall sentiment; a **🎯 ideal strike zone + minimum credit** beside the contract actually on offer (derived from support/resistance, expected move, earnings timing and Black-Scholes fair value at realised vol — the credit floor is priced at *that* contract's strike, so "clears fair value" compares like with like), the runner-up qualifying strikes, an **"Other contracts considered"** list naming every contract that didn't make it and why, and a **🎯 Levels** block with the share-entry price. When a strategy has no qualifying option it shows the closest failed contract and *why* — never silence. When it never even priced a contract (e.g. shares not held for a CC, or a CSP on a symbol outside `would_own` like a leveraged ETF) it instead shows an **informational fair-value zone** computed straight from technicals/IV/fundamentals, clearly labeled as not a recommendation |
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
| **4308** (`TELEGRAM_THREAD_SPREADS`) | `TELEGRAM_THREAD_SPREADS` | The daily credit-spread book (SPY 0DTE, `src/spreads/`): the 09:31 ET GEX map, every entry and exit, alerts (spreads still open past the time stop, a Gateway drop with spreads open, broker/DB mismatches) and the 16:10 ET summary |

## How it works, in short

Each stage links to its full technical writeup in **[ARCHITECTURE.md](ARCHITECTURE.md)**.

- **[The universe](ARCHITECTURE.md#the-universe--what-it-watches)** — a three-tier ticker list
  (watchlist / would-own / actively-wheeling), plus a dip-watch tier that's only checked after a
  real drop.
- **[Scanning](ARCHITECTURE.md#scanning--gathering-fresh-data-every-15-minutes)** — a 15-minute
  loop that only re-fetches an option chain when something material changed, to stay under IBKR's
  market-data-line limit.
- **[The analyst bench](ARCHITECTURE.md#the-analyst-bench--iv-technicals-fundamentals-liquidity-sentiment-and-the-macro-backdrop)**
  — IV rank/VRP, technicals, fundamentals, liquidity, sentiment, and a macro backdrop computed for
  every candidate.
- **[Fair value](ARCHITECTURE.md#fair-value--the-ideal-zone)** — a Black-Scholes-derived "ideal
  zone" and minimum credit every contract is compared against before it counts as a good deal.
- **[Generating trade ideas](ARCHITECTURE.md#generating-trade-ideas)** — four generators (covered
  calls, cash-secured puts, rolls, buy-to-own) that keep a record of what they rejected and why.
- **[Scoring](ARCHITECTURE.md#scoring-and-ranking)** — candidates ranked 0–100 by configurable
  weights; the runner-up and why it lost are kept, not discarded.
- **[The rulebook](ARCHITECTURE.md#position-sizing-and-risk--the-rulebook)** — pure deterministic
  Python, zero AI, the only path to an order; checks cash, concentration, and the income floor,
  twice.
- **[Claude's second opinion](ARCHITECTURE.md#claudes-second-opinion)** — a plain-English review of
  the survivors; advisory only, can never open or block a trade.
- **[Telegram + the autonomy ladder](ARCHITECTURE.md#telegram-and-the-autonomy-ladder)** —
  candidates land on your phone; how much executes automatically depends on a four-rung ladder that
  only promotes on proven fill history.
- **[Execution](ARCHITECTURE.md#placing-the-order--execution)** — a limit order at mid-price,
  re-validated against a live quote immediately before sending.
- **[Intraday monitoring](ARCHITECTURE.md#watching-positions-all-day--the-intraday-monitor)** — an
  event-driven watcher for delta drift, IV spikes, ex-dividend risk, and the 21-DTE management
  point.
- **[Rolling](ARCHITECTURE.md#rolling-a-position)** — income rolls must still clear normal
  economics; defensive rolls are judged on risk reduction instead.
- **[Loss management](ARCHITECTURE.md#managing-losses-and-circuit-breakers)** — automatic
  profit-take per position; at the loss line, leveraged ETFs are closed and everything else gets a
  defensive roll proposal; plus daily-loss and drawdown circuit breakers at the account level.
- **[The wheel](ARCHITECTURE.md#the-wheel--campaigns)** — CSP→assignment→CC chains tracked as one
  campaign with a real adjusted cost basis.
- **[End of day](ARCHITECTURE.md#end-of-day--the-daily-report)** — a written P&L narrative,
  IV-history update, and outcome reconciliation, every trading day.
- **[Learning from outcomes](ARCHITECTURE.md#learning-from-outcomes--the-fence)** — an outcome
  ledger and score-vs-outcome analysis a human reads by hand; walled off from ever touching the risk
  engine or config.
- **[Backtesting](ARCHITECTURE.md#backtesting)** — an offline simulator, fully isolated from the
  live trading path.

## Safety net

- **Paper trading by default.** Live orders are blocked unless `LIVE_TRADING=true` is explicitly set
  *and* the account is pointed at the live port — with a loud on-screen banner either way.
- **The Rules Engine is the only door to an order**, runs with zero AI involvement, and checks twice
  — once when ranking, once again with a fresh quote right before sending.
- **Claude (or the local model) can never place, size, or gate a trade** — if it's unavailable, the
  system trades the deterministic, rule-approved list anyway.
- **A second human tap is required for every order in live mode**, on top of whatever the autonomy
  rung already required.
- **Secrets never touch git** — tokens and account IDs live only in a local, gitignored `.env` file.

For current build status, known limitations, and the live-cutover checklist, see
**[STATUS.md](STATUS.md)**.

## Prerequisites

**To try it on paper — free, and the recommended starting point:**

- An Interactive Brokers account (even unfunded) with **IB Gateway** installed (recommended over
  TWS — lighter weight, no UI overhead, same API), API enabled, pointed at the paper port
- Python 3.12+
- A Telegram bot token and your chat ID (free, via @BotFather)
- The Claude Code CLI, installed and authenticated (`claude --version`) — **or**, with no `claude -p`
  subscription, a free local **[Ollama](https://ollama.com)** model instead
  (`claude.backend: "ollama"`, see [SETUP.md §14](SETUP.md))

No market-data subscription is needed for paper trading — IBKR's free 15-minute-delayed data covers
every symbol.

**To go live (optional, real money):** a funded IBKR account, plus an active real-time market-data
subscription for options (IBKR's equity + options streaming add-on) — without it, live orders never
get real IBKR greeks. See **[SETUP.md §11](SETUP.md)** for exactly what to subscribe to and how to
verify it's active before switching `market_data_type` to live.

See **[SETUP.md](SETUP.md)** for the full step-by-step setup guide.

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env          # fill in Telegram token/chat-id and IBKR account
for f in settings risk_limits scoring_weights universe; do cp config/$f.example.yaml config/$f.yaml; done
                              # your own config: git-ignored, edit freely
# Start IB Gateway (paper account, API enabled, port 4002)

python -m scripts.healthcheck  # verifies connection, prints account summary
python -m pytest               # all tests pass without IB Gateway

./ibkr install                 # macOS: runs the whole stack (+ watchdog) under launchd — see SETUP.md §6c
```

## Running the system day to day (macOS)

**The system runs as a background service — there is no terminal window to watch or Ctrl-C.**
Use `./ibkr` from the repo root; it replaces `python -m scripts.start` for normal use.

| I want to… | Run |
|---|---|
| Start it (or start it after a stop) | `./ibkr start` |
| Restart it (after a code or config change) | `./ibkr restart` |
| **Stop it** (the Ctrl-C replacement) | `./ibkr stop` |
| Check that it is running | `./ibkr status` — shows `running pid=…` plus health checks |
| Watch what it is doing, live | `./ibkr logs approval` (also `monitor`, `api`, `research`, `eod`, `spreads`, `supervisor`) — Ctrl-C ends the *tail* only, never the system |
| First-time setup / re-register the background jobs | `./ibkr install` |

- **`stop` vs `uninstall`:** `stop` halts trading/scanning but leaves the watchdog alarm loaded, so
  you will get Telegram "supervisor is not running" alerts while stopped — expected. `./ibkr
  uninstall` removes everything, watchdog included.
- **Other places to see it running:** Telegram `/status`; the web console at
  `http://localhost:3000` (needs `npm run dev` in `web/`); `launchctl list | grep ibkr`.
  In **Activity Monitor**, search `python` (the daemons) or `caffeinate` (see below) — the
  processes are not labelled "ibkr".
- **Sleep prevention (`caffeinate`):** the background service wraps the stack in `caffeinate -i -s`
  so the Mac does not sleep mid-session (on AC power). It lives and dies with the stack, so it is
  **not** left running when the system is stopped: `./ibkr stop` turns it off, `./ibkr start` turns
  it back on. Confirm with `pmset -g assertions | grep -A2 caffeinate`.
- `python -m scripts.start` still works but is now only a foreground/debug alternative — never run
  it alongside `./ibkr` (two supervisors fight over IBKR clientIds; `./ibkr install` refuses to).

Full details: [SETUP.md §6c](SETUP.md).

## Running the web app

The web console is a FastAPI JSON API + a Next.js frontend. Full setup lives in
[SETUP.md](SETUP.md); the short version:

```bash
pip install -e ".[web,dev]"        # fastapi, uvicorn, and the dev tools
# .env needs WEB_API_TOKEN (any random string) and SEC_CONTACT_EMAIL (SEC EDGAR requires it)
./ibkr start                       # API + research worker + the IBKR daemons, all supervised (background service)
cd web && npm install && npm run dev    # Next.js on port 3000 (separate — not a Python script)
```

`./ibkr start` (which runs `scripts.start` under launchd) is the single command for everything on the Python side — see
[SETUP.md §6](SETUP.md) for the full daemon setup; `--no-api`/`--no-research` opt out of the
two web-tier services if you only want the trading daemons.

The AI summary panel is pluggable: set `research.summary.backend` in
`config/research.yaml` to `claude_cli` (default, reuses `src/claude/runner.py`),
`anthropic` (set `ANTHROPIC_API_KEY`), `openai` (set `OPENAI_API_KEY`), or `ollama`
(reuses the local `ollama serve` daemon). A missing key or a failed generation fails
soft to a page with no summary — enrichment, never a dependency.

## Documentation

| File | What it covers |
|---|---|
| **[ARCHITECTURE.md](ARCHITECTURE.md)** | The full technical deep dive: the pipeline stage by stage, what every folder does, the process/clientId model, data-flow schemas, and operational risk handling |
| **[STATUS.md](STATUS.md)** | What's built, what's deliberately not built, tech stack, known limitations, and the live-cutover gate |
| **[SETUP.md](SETUP.md)** | Complete setup from scratch to first live trade |
| **[How the scan works.md](How%20the%20scan%20works.md)** | Which tickers get scanned, how hard, and when: the three clocks (15-min loop, 120-min per-symbol staleness net, event-driven position monitor), the actively_wheeling / dip-watch / held-position split and their 0.5% / 3% / 2% gates, with a worked day-long scenario |
| **[UNIVERSE_RESEARCH.md](UNIVERSE_RESEARCH.md)** | Deep-research findings for every ticker in the universe: tier classification, verified prices/IV ranks (Jun 2026), CC vs CSP appropriateness, leveraged-ETF rules, and data-quality notes. Injected into Claude trade reviews. |
| **[COMPETITIVE_RESEARCH_PLAN.md](COMPETITIVE_RESEARCH_PLAN.md)** | Competitive research findings and phased implementation tracker for borrowed features C1–C11; all 5 phases complete as of 2026-06-22 |
| **[docs/modernization/README.md](docs/modernization/README.md)** | Internal modernization plan (Phases 1–5): extended Greeks, provider abstraction, phase/RS scoring, recommendation overhaul, disk cache — all complete in code |
| **`Archive/Improvement_Plans/`** | Historical: REMEDIATION.md, IMPROVEMENT_PLAN.md (N1–N23), IMPROVEMENT_PLAN_2.md, SCAN_EFFICIENCY_PLAN.md, SYSTEM_REVIEW.md, TELEGRAM_ROUTING_PLAN.md — all complete and archived |
| **[CLAUDE.md](CLAUDE.md)** | Contributor and AI-assistant guidance |
| **[ib_async_documentation.md](ib_async_documentation.md)** | IBKR API reference (ib_async library) |

## Layout

| Path | Purpose |
|---|---|
| `config/` | Tunable YAML: connection settings, risk limits, watchlist, scoring weights |
| `src/` | All application code — analytics, strategies, the risk engine, execution, Telegram, the web API, research pipeline, and more. Full folder-by-folder breakdown: **[ARCHITECTURE.md](ARCHITECTURE.md#folder-by-folder-guide)** |
| `web/` | Next.js research/portfolio/P&L console (optional; see "Running the web app" above) |
| `scripts/` | Command-line entrypoints: healthcheck, watchdog, backfills, the EOD report, and more |
| `ibkr` | Single control script for the background service: `install`/`start`/`stop`/`restart`/`status`/`logs` |
| `tests/` | pytest suite (IBKR mocked; no TWS needed) |
| `docs/` | Internal planning specs and modernization notes |
| `Archive/` | Superseded/completed improvement plans, plus the archived Streamlit dashboard |

## License

MIT — see [LICENSE](LICENSE).

---

*This software is for personal use and provided as-is with no warranty. Trading options involves
substantial risk of loss.*
