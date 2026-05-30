# IBKR Options Income System — Build Plan

## Context

You sell cash-secured puts (CSPs) and covered calls (CCs) on your IBKR portfolio, but doing it
manually is slow and you miss opportunities. This plan designs a **semi-autonomous, modular,
agent-based Python system** that automates the deterministic work (scanning, option-chain
analysis, IV/Greeks, technicals, fundamentals, scoring, monitoring, execution) while keeping
**Claude as the strategic reasoning layer — invoked without the API**, via the Claude Code CLI in
headless mode (`claude -p`) under your existing subscription.

**Confirmed decisions (this session):**
1. **Interface:** Telegram approval loop for v1 (daily summary + inline Approve/Reject per trade). Streamlit dashboard later.
2. **Claude integration:** Headless subprocess (`claude -p`) with structured JSON in/out. Cron-driven, fully scriptable.
3. **Market data:** You have real-time US options (OPRA) data → trust IBKR live Greeks/IV via `reqMktData`; keep a Black-Scholes fallback for robustness.
4. **Execution:** Approve → auto-execute via `ib_async`. **Paper account first** to validate the full loop, then live cutover. Claude never places orders; a deterministic Rules Engine gates everything.

**Core principle:** Python owns all numbers and determinism. Claude owns judgment, prioritization, and narrative. A hallucinated Claude response or a scoring bug can never reach the broker — the Rules Engine is the circuit breaker between recommendation and order.

---

## Feasibility

**Verdict: Highly feasible. ~3–4 weeks to a solid paper-trading v1, then incremental hardening.**

- IBKR via `ib_async` (the maintained successor to `ib_insync`) natively provides everything: positions, account/margin, option chains (`reqSecDefOptParams`), live Greeks + IV (`reqMktData` tick types), and historical implied vol (`reqHistoricalData` with `whatToShow='OPTION_IMPLIED_VOLATILITY'`) — which lets us **bootstrap IV Rank/Percentile from 1 year of history immediately** instead of waiting months to accumulate it.
- The hard parts are operational, not algorithmic: connection reliability, market-data line limits (~100 concurrent for retail → batch chains), pacing violations, and the approval→execution timing gap. All are well-understood and handled in the plan below.

### Is `staskh/trading_skills` useful?

**Yes — as a Claude-side companion MCP, not as the data backbone.** (MIT licensed, Python 3.12+, `uv`.)
- **Use it for:** giving the headless Claude process ad-hoc lookup tools during roll/assignment reasoning — `ib_portfolio`, `ib_find_short_roll`, `ib_pmcc_advisor`, `ib_delta_exposure`, `ib_collar`, `option_chain`, `option_greeks`, `report_stock`. Configure it in the project `.mcp.json` so `claude -p` can call it.
- **Do NOT rely on it for the deterministic engine:** its market data is Yahoo Finance (~15-min delayed) and its IB option chain is marked "under development." Our scoring must use IBKR-direct real-time data.
- **Watch-out:** it opens its own TWS connection — give it a **different `clientId`** than our engine to avoid conflicts. Whale-hunting needs a paid Massive API key (skip for v1).

---

## Architecture

### Data flow (the desk pipeline)

```
                          ┌─────────────────────────────────────────┐
   cron / scheduler  ───▶ │              ORCHESTRATOR                 │
                          │  morning_scan · intraday_loop · eod       │
                          └───────────────────┬───────────────────────┘
                                              │
                 ┌────────────────────────────┼────────────────────────────┐
                 ▼                            ▼                             ▼
        ┌─────────────────┐         ┌──────────────────┐          ┌──────────────────┐
        │ MARKET DATA AGENT│        │  ANALYTICS LAYER  │          │ PORTFOLIO/RISK    │
        │ ib_async:        │        │ IV rank/skew/term │          │ delta·theta·conc. │
        │ positions,acct,  │───────▶│ technicals/regime │─────────▶│ margin, exposure  │
        │ chains, greeks   │ enrich │ fundamentals      │  scores  │ limits            │
        └─────────────────┘         │ liquidity         │          └──────────────────┘
                 │                  └──────────────────┘                    │
                 │                                                          │
                 ▼                                                          ▼
        ┌────────────────────────────────────────────────────────────────────────┐
        │ STRATEGY MODULES:  covered_call · cash_secured_put · rolling             │
        │  → generate candidate trades, each carrying component scores             │
        └────────────────────────────────────┬───────────────────────────────────┘
                                              ▼
        ┌────────────────────────────────────────────────────────────────────────┐
        │ DECISION ENGINE:  weighted score (IV·technical·fundamental·liquidity·    │
        │  assignment-risk) → rank → confidence → top 5–20 candidates              │
        └────────────────────────────────────┬───────────────────────────────────┘
                                              ▼
        ┌────────────────────────────────────────────────────────────────────────┐
        │ RULES ENGINE (deterministic gate, NO LLM): hard limits, buying-power,    │
        │  earnings blackout, max ticker/sector/correlated exposure → PASS/REJECT  │
        └────────────────────────────────────┬───────────────────────────────────┘
                                              ▼
        ┌────────────────────────────────────────────────────────────────────────┐
        │ CLAUDE (headless `claude -p`, JSON in/out, optional trading_skills MCP): │
        │  reviews top candidates → ranks, explains why/risks/tradeoffs/assignment │
        │  /roll considerations. Returns structured JSON. Does NOT execute.        │
        └────────────────────────────────────┬───────────────────────────────────┘
                                              ▼
        ┌────────────────────────────────────────────────────────────────────────┐
        │ TELEGRAM: daily summary + inline Approve/Reject per trade                │
        └────────────────────────────────────┬───────────────────────────────────┘
                                  approval    ▼
        ┌────────────────────────────────────────────────────────────────────────┐
        │ EXECUTION ENGINE (ib_async): re-validate vs Rules Engine + live quote,   │
        │  build option LimitOrder, place, monitor fill, confirm back to Telegram  │
        └────────────────────────────────────────────────────────────────────────┘
        State persisted at every step → SQLite (candidates, approvals, orders, fills, iv_history)
```

### How the agents communicate

**Shared-context pipeline + typed schemas — not a message bus (avoid over-engineering for v1).**
- Every module exchanges **Pydantic models** defined once in `common/schemas.py` (e.g. `TradeCandidate`, `PositionSnapshot`, `MarketContext`, `ScoreCard`, `RiskVerdict`, `ClaudeReview`). These are the contracts; modules never reach into each other's internals.
- The orchestrator builds a `MarketContext`, passes it through analytics → strategy → decision → risk as an enrichment pipeline (each stage returns enriched objects).
- **Persistence is the integration backbone:** every stage writes to SQLite so any step is resumable/inspectable and the dashboard/Telegram read from one source of truth.
- **Intraday monitoring is event-driven**, not pipeline: subscribe to `ib_async` `pendingTickersEvent` / `positionEvent`, and only when a *trigger condition* fires (delta drift, IV spike, DTE threshold, assignment risk) do we call Claude with a narrow focused prompt.

### How Claude stays "in the loop" without the API

- `src/claude/runner.py` wraps `subprocess.run(["claude", "-p", prompt, "--output-format", "json"], ...)`. Context (candidates + portfolio summary + specific question) is written to a temp JSON file and referenced in the prompt.
- **Double-envelope parse (important):** `--output-format json` returns an *envelope* (`{"type":..., "result": "<assistant text>", "total_cost_usd":..., ...}`). The assistant's own JSON lives inside the `result` string. `parser.py` must: (1) parse the envelope, (2) extract `result`, (3) strip any markdown fences, (4) parse the inner JSON, (5) validate it against the `ClaudeReview` schema. Treat steps 4–5 failing as "Claude unavailable" → deterministic fallback.
- A project `.mcp.json` registers `trading_skills` (and optionally a thin custom MCP exposing our own SQLite/analytics) so the headless Claude can do ad-hoc lookups when reasoning about rolls.
- **Three invocation moments** (matches your mental model): morning review of top candidates; intraday only on trigger (roll/unusual-vol/conflicting-signal); end-of-day journaling.
- Resilience: every Claude call has a timeout, a retry, and a **deterministic fallback** — if Claude is unavailable or returns unparseable output, the system still presents the Rules-Engine-approved ranked list to Telegram (Claude enriches; it is never a single point of failure).

### Process model & concurrency (review addendum — resolves the asyncio/scheduler trap)

`ib_async` owns an `asyncio` event loop and **all IB calls must run on the loop's thread**. Running
a threaded `APScheduler` in the same process as a live IB connection causes cross-thread loop
errors. So the system is split into **separate processes by lifetime**, each with its own clientId:

| Process | Lifetime | clientId | Owns | Triggered by |
|---|---|---|---|---|
| `morning_scan` | one-shot | 11 (engine) | full pipeline → Claude → sends Telegram messages | **system cron** |
| `eod_report` | one-shot | 11 (engine)\* | P&L + journal → Telegram | **system cron** |
| `approval_service` | long-running | 14 (exec) | Telegram **polling** (button callbacks) **and** order execution | runs as a daemon/service |
| `intraday_monitor` | long-running | 12 (monitor) | event-driven `asyncio` watch + roll triggers + focused Claude calls | runs during RTH |
| `backfill_iv` | one-shot | 13 | seed `iv_history` | manual / weekly cron |

\* one-shots never overlap in time, so they can share id 11; if you ever run them concurrently, give
`eod_report` its own id.

Key consequences (these drive Phases 6–8 and were under-specified before):
- **Two distinct Telegram entry points.** One-shot `morning_scan` only *sends* messages (a stateless
  Bot API HTTP call — it does NOT start polling). The persistent `approval_service` runs the
  polling app that *receives* the Approve/Reject button callbacks. They share a token; only the
  service has a running update loop.
- **Approval → execution is decoupled via the DB, not an in-memory call.** A button press writes
  `approvals.status` and enqueues an `orders` row as `QUEUED`. The `approval_service` (which holds
  the exec TWS connection) picks up `QUEUED` orders, **re-validates against the Rules Engine + a
  fresh live quote**, then transmits.
- **Off-hours approvals.** If approved when market is closed (or `transmit_only_in_rth: true`), the
  order stays `QUEUED`; the service transmits at the next RTH open. Approvals older than
  `approval.ttl_minutes` are marked `EXPIRED` and never sent.
- **One IB connection per process.** `morning_scan` connects, scans, disconnects before it spawns
  `claude -p`; the trading_skills MCP inside that subprocess uses clientId 20 — no overlap.

---

## Project structure

```
IBKR Investments/
├── config/
│   ├── settings.yaml          # TWS host/port, clientIds, account, scheduler times
│   ├── risk_limits.yaml       # max ticker/sector/correlated exposure, margin cap, CSP cap, min ROC, delta targets, earnings blackout days
│   ├── universe.yaml          # watchlist + index/ETF scan list (QQQ, SPY, SOXL, LABU…)
│   └── scoring_weights.yaml   # weights for IV/technical/fundamental/liquidity/assignment scores
├── .env                       # SECRETS: telegram token+chatid, IBKR account (gitignored)
├── .mcp.json                  # (opt-in) registers trading_skills MCP for `claude -p`; created
│                              #   from .mcp.json.example — auto-runs external code, enable manually
├── src/
│   ├── ibkr/                  # MARKET DATA AGENT
│   │   ├── connection.py      # connect/reconnect manager, clientId allocation, market-data-type
│   │   ├── market_data.py     # quotes, option chains (reqSecDefOptParams), live greeks/IV, hist data
│   │   ├── portfolio.py       # positions(), accountSummary(), margin, P&L
│   │   └── contracts.py       # Stock/Option contract builders + qualifyContracts
│   ├── analytics/
│   │   ├── iv.py              # IV Rank/Percentile (from hist OPTION_IMPLIED_VOLATILITY), term structure, skew
│   │   ├── greeks.py         # Black-Scholes fallback (scipy), portfolio Greek aggregation
│   │   ├── technicals.py     # RSI, ATR, MACD, MAs, support/resistance, regime classifier
│   │   ├── fundamentals.py   # yfinance: FCF, debt, dividend safety, earnings quality/dates
│   │   └── liquidity.py      # bid/ask spread %, open interest, volume gates
│   ├── strategies/
│   │   ├── covered_call.py   # CC candidates: strike/delta/expiry, annualized yield, upside-sacrifice
│   │   ├── cash_secured_put.py # CSP candidates: only "would-own" names, support-based strikes
│   │   └── rolling.py        # roll candidate detection for existing shorts
│   ├── engine/
│   │   ├── scoring.py        # normalize component scores → 0-100
│   │   ├── decision_engine.py# weighted combine, rank, confidence, top-N selection
│   │   └── risk_engine.py    # DETERMINISTIC hard-limit gate (circuit breaker)
│   ├── claude/
│   │   ├── runner.py         # subprocess wrapper for `claude -p --output-format json`
│   │   ├── parser.py         # validate/parse Claude JSON into ClaudeReview
│   │   └── prompts/          # role templates: strategist, cc, csp, roll, eod
│   ├── execution/
│   │   ├── order_builder.py  # build option LimitOrder (mid-price logic)
│   │   ├── executor.py       # place/monitor/cancel via ib_async, fill tracking
│   │   └── approval.py       # map Telegram approval → re-validate → execute
│   ├── notify/
│   │   ├── sender.py         # stateless Bot-API send (used by one-shot morning_scan)
│   │   ├── approval_service.py # LONG-RUNNING: polling bot (button callbacks) + holds exec conn
│   │   └── formatters.py     # candidate → human-readable Telegram message
│   ├── monitor/
│   │   ├── intraday.py       # event-driven watch: delta drift, IV spike, DTE, assignment
│   │   └── triggers.py       # trigger conditions → focused Claude call
│   ├── storage/
│   │   ├── db.py             # SQLAlchemy engine/session (SQLite v1)
│   │   └── models.py         # candidates, approvals, orders, fills, iv_history, journal
│   ├── orchestrator/
│   │   ├── morning_scan.py   # ONE-SHOT (cron): full pipeline → Claude review → send Telegram
│   │   └── eod_report.py     # ONE-SHOT (cron): P&L, what changed, tomorrow's watchlist, journal
│   └── common/
│       ├── schemas.py        # Pydantic contracts shared across all modules
│       ├── config.py         # load/validate YAML + .env
│       └── logging.py        # structured logging
├── dashboard/                 # Streamlit (Phase 10)
├── scripts/                   # entrypoints: healthcheck.py, run_morning.py, run_eod.py,
│                              #   backfill_iv.py, run_approval_service.py, run_monitor.py
├── tests/                     # pytest; mock ib_async for unit tests
├── data/                      # parquet cache, iv_history backfill
├── logs/
├── pyproject.toml             # uv/poetry managed
└── README.md
```

---

## Tech stack

| Layer | Choice | Notes |
|---|---|---|
| Broker / data | **`ib_async`** | Maintained fork of ib_insync; you already have the docs. Real-time + historical. |
| Numerics | `pandas`, `numpy`, `scipy` | Scoring, Black-Scholes fallback, stats. |
| Fundamentals | `yfinance` | FCF, debt, earnings dates (supplemental only). |
| Schemas | `pydantic` v2 | Typed contracts between modules. |
| Storage | **SQLite + SQLAlchemy** (v1) | Postgres migration path later; SQLAlchemy makes it a config change. |
| Scheduling | **system `cron`** for one-shots; `asyncio` for the monitor | See "Process model" below — do NOT run APScheduler in the same thread as an ib_async loop. |
| Approval/notify | `python-telegram-bot` v21+ | Inline keyboards + callback handlers. |
| Claude | **Claude Code CLI (`claude -p`)** | Headless, subscription-based, JSON I/O. |
| Claude tools | `trading_skills` MCP via `.mcp.json` | Ad-hoc lookups during reasoning. |
| Config | `PyYAML` + `python-dotenv` | YAML for rules/weights, .env for secrets. |
| Dashboard (later) | `Streamlit` | Read-only views off SQLite. |
| Quality | `pytest`, `ruff`, `mypy` | Mock IBKR in tests. |

---

## Development phases

Each phase is independently testable against the **paper account** before moving on.

- ✅ **Phase 0 — Foundation.** Repo scaffold, `pyproject.toml`, config loader, `.env`/`.gitignore`, SQLite + SQLAlchemy models, Pydantic schemas, logging. Connect to TWS paper, print account summary. *Done when:* `scripts/healthcheck.py` connects and prints positions.
- ✅ **Phase 1 — Market Data Agent.** `ibkr/` module: positions, account/margin, option chains (batched within line limits), live Greeks/IV, historical IV. `scripts/backfill_iv.py` pulls 1y of `whatToShow='OPTION_IMPLIED_VOLATILITY'` daily bars **on the underlying stock/ETF contract** (this is IBKR's ~30-day constant-maturity IV index for the name — a single series per symbol, *not* per option contract). That series is what `iv_history` stores and IV Rank/Percentile are computed from. Per-contract IV (from `ticker.modelGreeks.impliedVol`) is used only for live strike selection, not for the rank. *Done when:* full chain + Greeks for a watchlist name land in SQLite and `iv_history` is seeded.
- ✅ **Phase 2 — Analytics.** `iv.py` (Rank/Percentile/term/skew), `technicals.py` (RSI/ATR/MACD/MA/S-R + regime classifier), `fundamentals.py`, `liquidity.py`. *Done when:* a symbol gets a complete `ScoreCard`.
- ✅ **Phase 3 — Strategy modules.** `covered_call.py`, `cash_secured_put.py`, `rolling.py` generate `TradeCandidate`s with delta-targeted strikes, annualized yield, breakeven, PoP. CSP restricted to a "would-own" allowlist. *Done when:* candidate lists generate for watchlist + your real positions.
- ✅ **Phase 4 — Decision + Rules Engine.** `scoring.py` normalization, `decision_engine.py` weighted rank + confidence + top-N, `risk_engine.py` deterministic hard-limit gate. *Done when:* top 5–20 PASS/REJECT verdicts produced with reasons.
- ✅ **Phase 5 — Claude integration.** `runner.py`/`parser.py`, prompt templates, `.mcp.json` with trading_skills (separate clientId). Fallback path when Claude unavailable. *Done when:* top candidates round-trip through `claude -p` into structured `ClaudeReview`.
- ✅ **Phase 6 — Telegram approval loop.** `notify/sender.py` (stateless send from `morning_scan`) + `notify/approval_service.py` (long-running polling daemon). Inline Approve/Reject writes `approvals.status` to SQLite and enqueues a `QUEUED` order row. Chat-id allowlist so only you can approve. *Done when:* you approve/reject from your phone and DB state updates.
- ✅ **Phase 7 — Execution engine (paper).** The `approval_service` (clientId 14, holds the exec TWS connection) polls for `QUEUED` orders, re-validates each against the Rules Engine + a fresh live quote, builds a mid-price `LimitOrder` (`order_builder.py`), `qualifyContracts`, transmits, monitors fill (`executor.py`), and confirms back to Telegram. Off-hours/`transmit_only_in_rth` orders stay `QUEUED` until the open; stale ones expire. *Done when:* an approved CSP/CC fills on paper and confirms back to Telegram.
- ✅ **Phase 8 — Intraday monitor + assignment/rolling.** Event-driven `intraday.py` + `triggers.py`; delta-drift / IV-spike / DTE / dividend-assignment detection → focused Claude roll prompt → Telegram roll alert. *Done when:* a simulated drift fires a roll recommendation.
- ✅ **Phase 9 — EOD reporting + journaling.** `eod_report.py`: P&L delta, what changed, tomorrow's watchlist, Claude-written narrative to a `journal` table + Telegram. *Done when:* nightly summary delivered.
- ✅ **Phase 10 — Streamlit dashboard.** Read-only views: portfolio, Greeks, exposure, top CC/CSP candidates, roll alerts, IV conditions, performance analytics.
- ✅ **Phase 11 — Live cutover + optional sentiment.** Flip execution to live account behind an explicit config flag + extra confirmation; optional Reddit/YouTube sentiment as a low-weight score input. Future: ML regime detection, vol forecasting, backtesting, local-LLM hybrid.

---

## Major risks & failure points (and mitigations)

1. **TWS/Gateway disconnects mid-run** → `connection.py` auto-reconnect with backoff; orchestrator checkpoints to SQLite so a run is resumable; abort execution if not connected.
2. **Market-data line limit (~100)** → batch option-chain requests, cache to SQLite/parquet, throttle to avoid pacing violations (`reqMktData` then `cancelMktData`).
3. **clientId conflicts** (engine + trading_skills MCP + dashboard all hit TWS) → central clientId registry in `settings.yaml`; one id per process.
4. **Claude output unparseable / unavailable** → strict JSON schema validation + retry + deterministic fallback (Rules-Engine list still ships). Claude never blocks the pipeline.
5. **Approval→execution timing gap** (approve at night, market closed) → executor re-validates live quote + Rules Engine at send time; orders queued and only transmitted in RTH unless explicitly overridden; stale approvals (> configurable TTL) auto-expire.
6. **Order rejects / partial fills / wrong contract** → always `qualifyContracts` before sending; use LimitOrder (never market) at mid; monitor `orderStatus`; reconcile fills to SQLite; alert on reject.
7. **Early assignment (esp. dividends/ITM)** → `monitor` flags ex-div + ITM short calls; assignment-risk score; Claude roll/close prompt before the date.
8. **Risk-limit bypass / runaway** → Rules Engine is the *only* path to execution and runs deterministically twice (decision time + send time); hard buying-power buffer; kill-switch config flag.
9. **Secrets leakage** → `.env` gitignored, never logged; Telegram chat-id allowlist so only you can approve.
10. **Paper↔live config mistakes** → live execution behind an explicit `LIVE_TRADING=true` flag + port check + startup banner confirming which account.

---

## Verification (end-to-end)

1. **Paper-account dry run:** start TWS paper (port 7497, API enabled), run `scripts/healthcheck.py` → confirms connection + positions.
2. **Pipeline run:** `python -m src.orchestrator.morning_scan` → SQLite populated with candidates, scores, Rules-Engine verdicts, and a `ClaudeReview`; inspect the top-N table.
3. **Approval loop:** receive Telegram summary, tap Approve on one paper CSP → `executor` places the limit order → fill confirmation returns to Telegram → `fills` table updated.
4. **Intraday trigger:** simulate a delta-drift event → confirm a focused roll recommendation is produced and a Telegram alert fires.
5. **EOD:** `python -m src.orchestrator.eod_report` → journal entry + summary delivered.
6. **Tests:** `pytest` (IBKR mocked) green; `ruff` + `mypy` clean.
7. **Live cutover gate:** only after ≥ N successful paper cycles, flip `LIVE_TRADING=true` and re-verify steps 1–3 with a single small position.

---

## Open items to decide before/at Phase 0 (sensible defaults assumed)
- **Risk limits & scoring weights** — I'll seed `risk_limits.yaml` / `scoring_weights.yaml` with conservative theta-gang defaults (e.g. CSP delta 0.15–0.30, CC delta 0.20–0.35, max 5%/ticker, 14-day earnings blackout, min ~1% ROC). You tune in config; no code change.
- **CSP "would-own" allowlist** — you provide the names you're happy to be assigned; lives in `universe.yaml`.
- **Postgres vs SQLite** — SQLite for v1 (SQLAlchemy keeps migration trivial).
- **First task on approval:** copy this plan to the project root as `PLAN.md` for in-repo reference.
