# Web Platform — Overall Context

**Status:** context document. Written 2026-09-02.
**Scope of this file:** the end-state vision, the decisions taken so far, the research that
informs them, and how the work decomposes. It is deliberately *not* a design document — the
detailed design for the first slice lives in `P0-P1-design.md` alongside this file.

---

## 1. What we are building

One web application (and later a mobile app) that becomes the primary human surface for the
IBKR options-income system. Today that surface is Telegram, which renders a rich analytical
system through a chat window — it works, but it is the wrong shape for research, for
tabular P&L, and for anything a person wants to browse rather than react to.

The end state is a single site with a left navbar and five sections:

1. **Stock Researcher** — search any US ticker; a comprehensible, digestible full analysis:
   fundamentals, technicals, sentiment, news, an AI-written summary, and an options-income
   lens. A landing page with a search bar, a watchlist dashboard with price movement, and
   cards organised by sector. Replaces the Telegram stock-recommendation card.
2. **Options console** — the system's option recommendations, with approve / reject /
   manual execute / manual roll.
3. **IBKR portfolio** — positions, account, campaigns, assignment risk.
4. **Profitability tracker** — an Excel-shaped ledger of every position opened and closed,
   with realised/unrealised P&L, an equity curve, and system performance over time.
5. **Universe** — view and edit `would_own` / `watchlist` / `actively_wheeling`.

Reference points: Simply Wall St for digestibility, Finviz for sector overviews, brokerage
research tabs for the per-ticker page, TradingView for charting feel.

---

## 2. Decisions recorded

| Question | Decision |
|---|---|
| Audience | **Private now, public-ready later.** Build for one operator; keep provider, auth and licensing boundaries clean so opening it up is a config + deploy change, not a rewrite. |
| Ticker coverage | **Any US ticker, full depth** — materialised lazily (see §4). |
| Telegram buy-list | **Site replaces it**, but both run in parallel during P1; `format_buy_list` is removed only once the web version is trusted. |
| Data budget | **Free tiers + SEC EDGAR now**, with a provider abstraction so a paid API (FMP / EODHD / Polygon) is a config swap. |
| AI summary | **Pluggable backend** — the existing `claude -p` CLI, an Anthropic API key, OpenAI, or a local Ollama model. Same abstraction shape as `claude.backend` today. |
| Portfolio visibility | **Yes, as its own navbar section** — separate from the researcher, not mixed into it. |
| Price freshness | **Delayed intraday, 15–30 min**, for watched names; end-of-day for the long tail. |
| Options lens | **Universe names are the core priority.** Any other ticker can be pulled into a CC/CSP suitability read on explicit request, clearly labelled as best-effort. |

---

## 3. Invariants inherited from the trading system

These are not negotiable and they constrain every surface below. They come from `CLAUDE.md`.

- **The Rules Engine is the only path to order execution**, and it is deterministic Python
  with no LLM involvement. The web layer may create *intent*; it must never gain a path to
  `placeOrder`. A "manual execute" button in P2 means an `app_commands` row drained by
  `approval_service`, performing exactly the `ApprovalRow` mutation `_process_button`
  performs today — same code path, same snapshot freeze, same execution-time re-gate.
- **The fence.** Nothing in the enrichment learning loop reaches the engine, scoring
  weights, risk limits, or sizing. The AI summary in P1 is enrichment: it may read
  everything and influence nothing.
- **Analytics tiers.** `sentiment.py`, `sector_context.py`, `market_conditions.py` are
  enrichment and must never be imported by `engine/`, `execution/`, or `strategies/`. The
  research layer sits on the enrichment side of that line and must not become a back door.
- **Modules communicate only through Pydantic schemas.** No raw `ib_async` objects across
  boundaries; the web API is no exception.
- **Analytics never call `yfinance.*` directly** — everything goes through `src/data/`.
  New research data sources extend that provider layer rather than bypassing it.
- **One clientId per process.** The API process holds **no** `ib_async` connection at all,
  so it needs no clientId and can never contend with the four trading processes.

---

## 4. How "any US ticker, full depth" works on free tiers

Precomputing everything nightly for ~6,000 names is not reachable on free-tier price APIs.
The resolution is **lazy materialisation at equal depth**, not reduced depth:

- **Hot tier** — the ~46 names in `universe.yaml`. Fully precomputed, refreshed on the
  existing scan cadence, complete IV history and option-chain data.
- **Warm tier** — anything on a watchlist or viewed recently. Refreshed nightly; delayed
  intraday quotes during the session.
- **Cold tier** — every other US ticker. Computed *in full* on first search, then cached and
  promoted to warm if anyone watches it. First view costs a few seconds; every later view is
  a cache read.

The symbol directory itself (ticker ↔ CIK for every SEC filer, ~10k names) is free and
static enough to hold in full, so search works across the whole market from day one even
before a name has ever been materialised.

---

## 5. Research findings that shape the design

### 5.1 Architecture worth copying — OpenBB

[OpenBB's Open Data Platform](https://github.com/OpenBB-finance/OpenBB) separates
*providers* (one class per data source), *extensions* (route definitions) and *core*
(orchestration), on FastAPI + Pydantic. The load-bearing idea is the **standardised model**:
a caller asks for "income statement" and gets the same Pydantic shape regardless of which
vendor served it. `src/data/protocols.py` is already a small version of this. The research
layer extends that pattern rather than inventing a second one.

### 5.2 Digestibility worth copying — Simply Wall St

Simply Wall St publishes its actual analysis model:
[SimplyWallSt/Company-Analysis-Model](https://github.com/SimplyWallSt/Company-Analysis-Model).
It is **5 categories × 6 binary checks = 30 checks**, each with a published threshold —
"Is the debt-to-equity ratio under 40%?", "Is ROE above 20%?", "Are dividends covered by net
profit (payout 0–90%)?", "Is the DCF value at least 20% above the share price?".

The comprehensibility does not come from the visual. It comes from **collapsing continuous
financials into a fixed set of pass/fail checks with stated thresholds**, and only then
drawing a shape. That is a few hundred lines of deterministic Python, it is auditable, and
it degrades honestly — a check with missing data is *unknown*, never a silent fail.

The model is also explicit about its own limits: it is entirely quantitative and cannot
adjust for one-time charges, M&A, spinoffs or restatements. That caveat has to survive into
our UI, because it is exactly what the AI summary will be tempted to paper over.

### 5.3 Where valid financial data actually comes from

- **SEC EDGAR XBRL** — `data.sec.gov/api/xbrl/companyfacts/CIK##########.json` returns every
  XBRL fact a company has filed, grouped by taxonomy, concept, unit, period and form. Free,
  no key, official, ~10 requests/second with a declared User-Agent, CIK zero-padded to 10
  digits. The `frames` endpoint flips the axis — one concept across every filer for a period
  — which is how sector percentile rankings get built. `edgartools` normalises it to pandas.
  This is the ground truth for US fundamentals and it is the single most important source
  in the whole design.
- **yfinance is a web scraper**, not an API. Rate limits, IP blocks and silent schema changes
  are normal behaviour, and its terms are a genuine problem for anything public-facing. It
  stays as a fallback and for delayed quotes on a small watched set; it must not be the
  backbone of a site.
- **Keyed alternatives**, all behind the same provider abstraction: FMP (250 req/day free,
  strongest fundamentals coverage), Finnhub (60/min free, good news and quotes), Tiingo
  (1,000/day, clean EOD history), Alpha Vantage (25/day now), Polygon, EODHD (~$20/mo).
- **Free bulk EOD prices** for the cold tier — stooq's CSV endpoint is the usual choice and
  needs its licensing verified before it becomes load-bearing.
- **News and sentiment** already exist in `src/analytics/sentiment.py` (StockTwits + Reddit +
  VADER, with a disk cache).

### 5.4 How the good AI-research projects are built

FinRobot, `financial-research-analyst-agent`, `equity-research-generator` and the CrewAI
report generators all follow the same pattern: **deterministic collection → a structured
context object → an LLM that writes narrative only and never computes numbers.** That is the
fence this repo already enforces in `src/claude/`, so the AI summary is a small extension of
an existing pattern rather than a new capability with new risks.

### 5.5 Frontend

TradingView's [lightweight-charts](https://github.com/tradingview/lightweight-charts)
(Apache-2.0, canvas, comfortable at thousands of bars) for price and volume; a React-idiomatic
library such as Recharts or visx for the small stat panels, where data density is low and
developer ergonomics matter more than frame rate.

### 5.6 Prior art already in this repo

- `docs/superpowers/specs/2026-08-10-remediation-and-ios-app-design.md` §9–10 already
  designs the control API: a `src/api/` FastAPI process with **no `ib_async` connection**,
  reads served from SQLite with an explicit `as_of`, writes as an `app_commands` intent queue
  drained by `approval_service`, `universe_overrides` composed onto the YAML at config load,
  and three client rules (offline-first, provenance on every number, never claim more than
  the backend did). P0 re-targets that design at web instead of iOS; it does not redesign it.
- `Archive/dashboard/` holds the retired Streamlit dashboard — useful as a record of which
  views mattered, not as a base to build on.

---

## 6. Decomposition

| | Surface | Depends on | Notes |
|---|---|---|---|
| **P0** | Web foundation | — | FastAPI read-API, Next.js shell, navbar, auth, provenance conventions. Substrate for everything else. |
| **P1** | Stock Researcher | P0 | The largest single build: a data pipeline that does not exist yet (EDGAR ingestion, checks engine, AI-summary provider, ~6,000 tickers). |
| **P2** | Options console | P0 | The one with teeth — touches the execution path. Gets its own spec precisely so its safety questions never block research work. |
| **P3** | Portfolio | P0 | Largely a rendering of data `approval_service` already persists. |
| **P4** | Profitability tracker | P0, P3 | Needs closed-position accounting; `fills`, `campaigns` and `verdict_ledger` provide most of the raw material. |
| **P5** | Mobile app | P0–P4 | Consumes the same API. Deliberately last. |

Each phase gets its own design → plan → implementation cycle. **P0 + P1 are designed
together** in `P0-P1-design.md`, because P1 cannot ship without a shell and designing the
navbar with P2–P4 stubbed is what stops the later sections forcing a rewrite.

---

## 7. Risks carried into the design

1. **Repo surface.** This roughly doubles the size of a repo whose documentation rules
   already require five files to stay in sync. The doc-update table in `CLAUDE.md` needs new
   rows for the web layer, or the docs go stale immediately.
2. **A JavaScript toolchain enters a pure-Python repo.** Real cost in CI, tooling and
   review, accepted because P5 (mobile) and the public-ready goal both need a real client.
3. **Free-tier fragility.** yfinance will break at some point. The provider abstraction is
   the mitigation, and it only works if nothing bypasses it — the same discipline
   `src/data/` already enforces for the trading path.
4. **Database contention.** The research corpus is a different data domain from the
   operational trading DB, and a heavy nightly research write must not block
   `approval_service`. Addressed in the design with a separate research database.
5. **AI summaries that sound more certain than the data.** The Simply Wall St caveat applies
   doubly to generated prose. Provenance and "unknown" states have to be visible in the UI,
   not buried.
