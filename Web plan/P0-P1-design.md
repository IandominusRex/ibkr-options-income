# Design — P0 Web Foundation + P1 Stock Researcher

**Date:** 2026-09-02
**Status:** design, approved in outline, pending written review
**Context:** `OVERVIEW.md` in this folder holds the end-state vision, the research findings, and
the P0–P5 decomposition. This document designs the first two slices in detail.
**Prior art re-used, not redesigned:** `docs/superpowers/specs/2026-08-10-remediation-and-ios-app-design.md`
§9–10 (the control API, the intent queue, `universe_overrides`, the three client rules).

---

## 1. Scope

**P0 — Web foundation.** A FastAPI JSON API, a Next.js shell with a persistent left rail, auth
shaped for a future multi-user world, a second database for research data, and the provenance
conventions every later surface inherits.

**P1 — Stock Researcher.** Search any US ticker; a full analysis page covering fundamentals,
technicals, sentiment, news, a deterministic checks engine, and a pluggable AI summary. A
landing page with search, a watchlist dashboard, and sector cards. A recommendations view that
replaces the Telegram buy-list card.

**Out of scope, by phase:** the options console (P2), the portfolio screens (P3), the
profitability tracker (P4), mobile (P5). Their navbar entries exist from milestone 1 and render
an explicit placeholder, so the finished shape is visible from the start.

---

## 2. Decisions this design implements

| Decision | Value |
|---|---|
| Audience | Private now, public-ready later |
| Coverage | Any US ticker, full depth, lazily materialised |
| Buy-list | Site replaces it; both run in parallel through P1, `format_buy_list` removed after |
| Data | Free tiers + SEC EDGAR now, provider abstraction for a paid swap |
| AI summary | Pluggable: `claude_cli`, `anthropic`, `openai`, `ollama` |
| Stack | FastAPI JSON + OpenAPI-generated TS types + Next.js |
| Repo | Same repo, new packages, one-way import fence |
| Portfolio | Own navbar section (P3), not mixed into research |
| Freshness | Delayed intraday for watched names, EOD for the long tail |
| Options lens | Default for universe names, on-demand for any other ticker |

---

## 3. Inherited invariants

From `CLAUDE.md`, non-negotiable, and they constrain every line below.

1. **The Rules Engine is the only path to order execution.** The web layer may create intent;
   it must never gain a path to `placeOrder`. P0 and P1 write nothing to the trading database
   at all.
2. **The fence.** The AI summary is enrichment: it may read everything and influence nothing.
   It must not reach the checks engine, the recommendation ranking, `scoring_weights.yaml`,
   `risk_limits.yaml`, or sizing.
3. **Analytics tiers.** `sentiment.py`, `sector_context.py` and `market_conditions.py` stay on
   the enrichment side. The research layer sits on that side too and must not become a back
   door into the deterministic tier.
4. **Pydantic at every boundary.** No raw `ib_async` objects cross a module line, and the API
   is no exception.
5. **No direct `yfinance.*` calls** outside `src/data/`. New sources extend that provider
   layer.
6. **One clientId per process.** The two new processes hold no `ib_async` connection at all,
   so they need none and can never contend with the four trading processes.

---

## 4. P0 — Foundation

### 4.1 Repository layout

```
src/api/                 FastAPI. JSON only. No ib_async, no clientId.
  main.py                app factory, middleware, exception handlers
  deps.py                DB sessions, CurrentUser, settings
  auth.py                bearer-token validation, role model
  routers/               health, research, watchlist, universe, recommendations
  models/                response schemas (distinct from src/common/schemas.py)
src/research/
  providers/             edgar.py, stooq.py, directory.py (+ reuse of src/data backends)
  ingest/                symbols.py, fundamentals.py, concepts.py, prices.py, news.py, jobs.py
  checks/                engine.py, loader.py
  summary/               protocol.py, claude_cli.py, anthropic.py, openai.py, ollama.py
  store/                 models.py (research Base), repo.py, session.py
  CLAUDE.md              local conventions
web/                     Next.js. Own package.json, tsconfig, eslint, CLAUDE.md
config/
  research.yaml          tiers, cadence, budgets, summary backend
  research_checks.yaml   check definitions and thresholds
  research_concepts.yaml XBRL concept map
docs/web/                architecture, api.md, checks.md, openapi.json, runbook
scripts/
  run_api.py             uvicorn
  run_research_worker.py APScheduler ingestion worker
```

### 4.2 Process model

The four existing trading processes are untouched. Two new ones join them, neither holding an
`ib_async` connection:

- **`run_api.py`** — uvicorn, bound to loopback today, Tailscale interface when it goes remote.
  Serves JSON. Performs bounded synchronous materialisation on a cache miss (§5.5).
- **`run_research_worker.py`** — APScheduler. Nightly warm-tier refresh, weekly symbol-directory
  refresh, continuous `ingest_jobs` drain.

Splitting the worker from the API is deliberate: a multi-thousand-row nightly ingest must not
sit in the same event loop as a page request.

### 4.3 Two databases

| Database | Owner | Access from API |
|---|---|---|
| `data/income_system.db` | the trading system | **read-only** (`?mode=ro` URI) |
| `data/research.db` | the research layer | read-write |

SQLite permits one writer per database. A nightly research ingest writing into the trading
database would serialise against `approval_service`'s writes, and the failure mode is a delayed
trade approval, which is not an acceptable cost for a research feature. The split also means
`research.db` can move to Postgres for a public deploy while the trading database does not move
at all.

`research.db` gets its own SQLAlchemy `Base` in `src/research/store/models.py`. It must not
import `src/storage/models.py`'s `Base`, so the two schemas can never be created against the
wrong engine.

### 4.4 Auth, shaped for public later

A `CurrentUser` FastAPI dependency is the single seam.

- **Today:** validates a bearer token from `.env` and returns `User(id="owner", role="owner")`.
- **Later:** the dependency's implementation is swapped for real sessions. Every route is
  already written against it and needs no change.

Two rules make that swap safe rather than hopeful:

1. Every user-owned row carries `user_id` from day one, defaulting to `"owner"` —
   `watchlists`, `watchlist_items`, `recently_viewed`, `notes`.
2. Every route that exposes the book is tagged `owner_only` and checked against role.
   Positions, account, fills and campaigns can therefore never leak when the site opens up,
   because the gate exists before the data does.

### 4.5 Provenance

Every headline number ships as `{value, source, as_of, stale}`, and every response carries a
top-level `as_of`. Sources are an enum: `edgar`, `yfinance`, `stooq`, `ibkr`, `computed`.

The three client rules from the iOS design carry over verbatim:

1. **Offline-first.** Cache the last good response and show its age. Never a spinner over a
   blank screen.
2. **Provenance on every number.** A delta derived from Black-Scholes must not look identical
   to one from IBKR.
3. **Never claim more than the backend did.** No UI affordance may imply a capability the
   system lacks.

### 4.6 API surface

```
GET    /health                      liveness, worker heartbeat, provider circuit state
GET    /me                          current user, role
GET    /nav                         sections visible to this user (drives the left rail)

GET    /research/search?q=          symbol directory, fuzzy
GET    /research/{symbol}           full analysis payload
GET    /research/{symbol}/options   on-demand CC/CSP suitability
GET    /research/{symbol}/summary   AI summary (separate route: slower, independently cacheable)
GET    /research/sectors            sector cards
GET    /research/recommendations    replaces the Telegram buy-list

GET    /watchlist
POST   /watchlist/{symbol}
DELETE /watchlist/{symbol}

GET    /universe                    effective universe (YAML + overrides), read-only in P1

reserved, unimplemented in P1: /positions /account /pnl /commands
```

The summary is its own route because it is the slowest and least reliable part of the page. A
model outage must not slow or fail the analysis payload.

### 4.7 The import fence

A test mirroring `tests/test_eval_skills.py::test_skills_never_reach_the_engine`:

- `src/engine/`, `src/execution/` and `src/strategies/` may never import `src.api` or
  `src.research`.
- `src/research/checks/` may never import `src.research.summary`.

The dependency is one-way, always. The web layer knows about the trading system; the trading
system does not know the web layer exists.

---

## 5. P1a — Data ingestion and the provider layer

### 5.1 New Protocols

Added to `src/data/protocols.py`, following the pattern already established there:

- `SymbolDirectoryProvider.list_symbols() -> list[SymbolRecord]`
- `FilingsProvider.get_company_facts(cik: str) -> CompanyFacts`
- `BulkPriceProvider.get_daily_bars(symbol: str, lookback_days: int) -> pd.DataFrame`

`src/data/factory.py` gains three matching cached getters reading `settings.yaml → data.*`.

### 5.2 Backends

| Backend | Serves | Notes |
|---|---|---|
| `edgar_backend.py` | directory, filings | `company_tickers.json` + `companyfacts`. Declared User-Agent, 10 req/s limiter, ETag revalidation, backoff on 403/429, CIK zero-padded to 10 digits. |
| `stooq_backend.py` | cold-tier EOD bars | Free CSV. **Licensing verified before it becomes load-bearing**, with yfinance as the fallback if it does not check out. |
| `yfinance_backend.py` | warm-tier quotes, news | Exists. Unchanged. |
| `fmp_backend.py` | all of the above | Exists as a stub. Extended to satisfy the new Protocols so "swap to paid" is a real path rather than a theoretical one. |

### 5.3 Normalisation: what makes the data actually valid

EDGAR returns facts tagged with us-gaap concepts, and filers disagree about which concept means
"revenue" (`Revenues`, `RevenueFromContractWithCustomerExcludingAssessedTax`, `SalesRevenueNet`,
and others). Without a normalisation step, a comparison across two companies is meaningless.

- **Concept map** — `config/research_concepts.yaml` maps each canonical line item to an ordered
  list of candidate concepts, first match wins. A missing mapping is a config fix, not a code
  change, which matters because the long tail of filers is where this breaks.
- **Period selection** prefers the **most recently filed** value for a given period, which is
  how restatements are handled correctly, and records `accn` and `filed` so every figure traces
  to a specific filing.
- **Units are enforced** (`USD`, `USD/shares`, `shares`) and mismatches are rejected rather than
  coerced.
- **Every ratio is computed by us** from normalised statements. ROE, D/E, current ratio, FCF,
  margins and the Piotroski components are never taken from a vendor's precomputed field. This
  is the discipline `src/analytics/fundamentals.py` already follows.

Output shape: `NormalizedFinancials` — income statement, balance sheet and cash flow, five
annual periods and eight quarters, each line item carrying `{value, concept, accn, filed, form}`.

### 5.4 `research.db` schema

```
symbols(symbol PK, cik, name, exchange, sector, industry, is_etf, updated_at)
company_facts_raw(cik PK, payload_json, etag, fetched_at)
financials(symbol, period_end, period_type, line_item, value, concept, accn, filed)
daily_bars(symbol, date, open, high, low, close, volume, source)
quotes(symbol PK, price, change_pct, as_of, source)
news_items(symbol, published_at, title, url, source, sentiment)
analysis_cache(symbol PK, payload_json, computed_at, tier)
check_results(symbol, check_id, state, actual, threshold, computed_at)
summaries(symbol, model, prompt_hash, data_as_of, payload_json, generated_at)
watchlists(id, user_id, name)
watchlist_items(watchlist_id, symbol, added_at)
recently_viewed(user_id, symbol, viewed_at)
ingest_jobs(id, symbol, kind, status, attempts, last_error, enqueued_at)
```

`company_facts_raw` keeps the raw EDGAR payload so ingestion is replayable. When the concept map
gains a mapping, every affected symbol can be re-normalised without re-fetching from SEC.

### 5.5 The three tiers, mechanically

- **Hot** — the ~46 names in `universe.yaml`. Precomputed on the existing scan cadence, with
  full IV history and option-chain data.
- **Warm** — anything watchlisted or recently viewed. Nightly refresh, delayed intraday quotes
  during the session.
- **Cold** — every other US ticker. Materialised in full on first view, then cached, and
  promoted to warm if watchlisted.

**Search always works across the whole market from day one**, because the symbol directory is
~10k rows and is refreshed weekly independent of any per-symbol materialisation.

**Cache miss path.** The API attempts bounded synchronous materialisation against a configured
budget (default 8s): EDGAR company facts, EOD bars, news. If it completes, the client gets a
full page. If it exceeds budget, the client gets a **partial payload with sections marked
`pending`** and an enqueued `ingest_job`, and polls. There is never a blank screen behind a
spinner.

### 5.6 Politeness and failure

Per-host token buckets sized to each provider's published limit. Disk cache with ETag
revalidation. A per-provider circuit breaker mirroring the existing
`max_consecutive_chain_timeouts` pattern: repeated failures open the circuit, the affected
sections render as `unavailable` with a reason, and the rest of the page still renders.

---

## 6. P1b — The checks engine

The digestibility mechanism, and the reason a page of forty numbers becomes an answer.

`config/research_checks.yaml` defines each check as
`{id, category, statement, expression, threshold, requires}`. Six categories:

1. **Value**
2. **Future / Growth**
3. **Past Performance**
4. **Financial Health**
5. **Dividend and Buybacks**
6. **Options-Income Suitability**

The first five follow the published Simply Wall St structure (five categories, six checks each,
every threshold stated). The sixth is ours and is the reason this is not a Simply Wall St clone:
IV rank ≥ 30, VRP positive (IV30 − HV30), ATM open interest and spread thresholds, estimated
monthly CC yield ≥ 1% (reusing `_est_monthly_cc_yield`), would-own fit, and no earnings inside a
typical 30–45 DTE window.

**Three evaluation states, never two** (plus `NOT_APPLICABLE`, see §6.1). Every check returns
`PASS`, `FAIL`, or `UNKNOWN`. `UNKNOWN` is
returned whenever a `requires` input is missing, and it is never silently coerced to a fail.
Category score is reported as `passed / evaluable` with the evaluable count visible, so "3 of 6"
and "3 of 4, 2 unknown" can never look alike. An off-universe ticker showing `UNKNOWN` for IV
rank until it is backfilled is the honest answer, and the UI says so.

**Fence.** The engine reads the deterministic analytics tier and the normalised financials. It
reads sentiment for display only, never into a check. It feeds no gate, no weight, and no
contract count.

### 6.1 ETFs need their own check set

**16 of the 46 universe names are ETFs, and 10 of those sit in `would_own`** (SPY, QQQ, IWM,
SMH, MAGS, HACK, IGV, and the three leveraged exceptions TQQQ, UPRO, SOXL). ETFs file N-CEN and
N-PORT, not 10-K, so they have **no XBRL financial statements at all**. Running the five
fundamental categories against them would report every serious ETF as failing almost every
check, which is worse than useless.

`src/analytics/fundamentals.py` already recognises this and passes ETFs on quality by default.
The checks engine follows the same logic, keyed on `symbols.is_etf`:

- The five fundamental categories are **not evaluated** and render as **not applicable**, which
  is a fourth state, distinct from `UNKNOWN`. `UNKNOWN` means "we could not get the data";
  not-applicable means "this question does not apply to this instrument". Conflating them would
  make an ETF look like a data failure.
- A **Fund category** replaces them: expense ratio, assets under management, holdings
  concentration, tracking behaviour, and average daily dollar volume.
- **Leverage carries an explicit warning**, not a check. Daily-reset decay is a structural
  property, not a pass or a fail, and it is the single most important thing to say about
  LABU, TSLL, DPST, TQQQ, UPRO and SOXL. The universe's own rules are surfaced here too: the
  CC-only names are marked as never assignment-eligible, and the three deliberate `would_own`
  exceptions are labelled as deliberate rather than looking like an oversight.
- The **Options-Income Suitability** category applies unchanged, and for an ETF it is doing most
  of the work, which is the honest picture for this system.

---

## 7. P1c — AI summary

`src/research/summary/` defines a `SummaryProvider` Protocol with four backends selected by
`research.summary.backend`: `claude_cli` (reuses `src/claude/runner.py`), `anthropic`, `openai`,
`ollama` (reuses `src/claude/ollama_runner.py`). The same abstraction shape the repo already
uses for `claude.backend`.

Five rules, all extensions of patterns already in this codebase:

1. The model receives a **fully-computed structured context**: check results with their actual
   values, normalised financials, technicals, sentiment, headlines. It writes narrative only.
   **Any number in its output must be one we passed in.** It never calculates.
2. Output is a Pydantic `Summary{thesis, bull_points, bear_points, watch_items, caveats}`.
   Structured, so the UI renders fields rather than prose, and a bad parse fails safely instead
   of printing garbage.
3. Failure renders the page **fully, without a summary**. Enrichment, never a dependency, which
   is exactly how `runner.py` behaves today.
4. Cached on `(symbol, prompt_hash, data_as_of)`, so browsing does not re-bill.
5. It influences nothing. The extended fence test covers it.

The summary carries the Simply Wall St caveat forward explicitly: the analysis behind it is
entirely quantitative and cannot account for one-time charges, M&A, spinoffs or restatements.
That caveat renders in the UI, not just in the prompt.

**When a summary is generated.** On explicit request or for watchlisted names, never
automatically for every cold-tier search. A first-time search on an obscure ticker must not
silently trigger a model call, and the page renders completely without one. The summary panel
shows an action until a summary exists.

### Recommendations, and a gap this design has to close

`/research/recommendations` renders the existing `generate_buy_candidates` output using the same
six-factor model, with **no re-scoring in the web layer**, so the site and Telegram can never
disagree about what the system thinks.

**`BuyCandidate` is not persisted today.** `scan.py` calls `generate_buy_candidates` and passes
the result straight to `format_buy_list`; nothing reaches SQLite, and there is no
`BuyCandidateRow` model. The API therefore has nothing to read. Recomputing in the API is not an
option, because the function needs live analytics and would turn a page load into a full scan.

The fix, in milestone 6:

- Add `BuyCandidateRow` to `src/storage/models.py` with a `computed_at` and one row per
  candidate per run.
- `src/orchestrator/scan.py` persists what it already computes, at both call sites (line 1403,
  the full scan, and line 1943, the single-ticker `/scan` path).
- The API reads that table **read-only**, preserving §4.3.

The writer is the orchestrator, which is an existing trading process, so this does not breach
"P0 and P1 write nothing to the trading database" — the API still writes nothing. Adding a
storage model triggers the `CLAUDE.md` doc rule for `ARCHITECTURE.md`'s `src/storage/` and
data-flow sections.

`format_buy_list` keeps running in parallel until the web version is trusted.

---

## 8. P1d — Visual design direction

Produced with the `frontend-design` skill (`.claude/skills/frontend-design/`, imported into this
repo 2026-09-02).

**Design read.** A private, data-dense research and trading console for one experienced
operator. Operate mode, web, dark, where the design's job is to make thirty numbers scannable at
a glance and never let an unknown look like a zero.

**Visitor mode: Operate**, with the ticker page's summary and news sections leaning **Read**.
The landing page is a dashboard, not a pitch, so Persuade never applies. Dials: `VARIANCE 3`,
`MOTION 2`, `DENSITY 6` — the top of Operate's density range, earned by financial tables.

### 8.1 The direction: Instrument

The reference screenshot (Puthouse) supplies the **structure**: dark ground, persistent left
rail, a stat block pinned to the rail footer, rounded surfaces, segmented toggles. We take that
structure and give it a different identity, because Puthouse reads as consumer fintech and this
is an instrument.

| | Puthouse | This |
|---|---|---|
| Radius | Large, soft, friendly | Tighter: 8px surfaces, 6px controls |
| Numerals | Proportional | **Tabular everywhere**, columns align like a ledger |
| Color | Green as brand *and* as "up" | Achromatic chrome; color is reserved for state |
| Empty states | Icon circle above a heading | One line of text plus the action |
| Elevation | Rounded cards with soft chrome | Lightness only, one technique, never stacked |

**The specific insight behind the colour rule:** Puthouse uses green as both its brand accent and
its gain colour. In a financial UI that is a real legibility bug, because "our brand" and "this
number went up" then look identical. Our chrome is achromatic, and the two or three colours that
do appear therefore always mean something.

**Differentiation, the thing you would describe an hour later: the check ribbon.** Rather than a
radar polygon, each category renders as a six-segment horizontal meter where one segment is one
check, and the states are distinguished by **fill and texture, not colour alone**:

```
Financial Health   ████████░░▒▒      4 pass · 1 fail · 1 unknown
                   filled  hollow  hatched

Past Performance   ┈┈┈┈┈┈┈┈┈┈┈┈      not applicable to an ETF
                   dimmed track
```

It reads at every density: full width in the ticker-page header, compact in a watchlist row,
miniature in a sector card. It encodes exact counts rather than a misleading area. It gives
`UNKNOWN` its own visual identity. And it satisfies the craft floor's requirement that state is
never colour-only. One component, one visual language, three densities.

### 8.2 Typography

- **IBM Plex Sans** for UI and body. Designed for technical interfaces, considerably less
  reached-for than Inter or Geist, and it has genuine tabular figures.
- **IBM Plex Mono** for tickers, prices, and every financial table cell. The matched pairing
  gives coherence without a third voice.
- **No separate display face.** In Operate mode a third family is noise; hierarchy comes from
  weight, size and spacing within Plex.

### 8.3 Colour

Dark surfaces, soft black rather than true black, because a shadow cannot read against a
background already at maximum darkness and true black produces harsher edge contrast than
intended:

| Token | Value | Use |
|---|---|---|
| `--bg-background` | `#121212` | page |
| `--bg-surface` | `#181818` | cards, panels, table bodies |
| `--bg-elevated` | `#282828` | modals, dropdowns, popovers, toasts |
| `--text-content` | `#F5F5F5` | primary text |
| `--text-muted` | `#A7A7A7` | secondary text |

Elevation is communicated by **lightness, never shadow**. Semantic colour only:

| Meaning | Use |
|---|---|
| gain / pass | green, distinct from any chrome |
| loss / fail | red |
| unknown | achromatic plus hatch texture, so it never competes with gain and loss |
| interactive / focus / selected | a single slate-blue, deliberately not cyan and deliberately not the gain green, so "selected" can never read as "up" |

### 8.4 Layout and rhythm

- Left rail, 260px, collapsible to icons. Footer stat block: NLV, day change, options P&L, open
  position count, all `owner_only`.
- Prose and summary sections hold a 65–75 character measure. Tables run full width.
- Spacing has rhythm: tight within a data block, generous between sections. Uniform gaps
  everywhere is a generated-page tell.
- **One framing move per section.** No card inside a card inside a padded bordered section,
  which is the failure mode financial UIs fall into most often.

### 8.5 Motion

Dial 2. One orchestrated content reveal per route change at 150–200ms. State transitions only
after that: hover, press, expand. **Charts do not animate their data in**, because an animation
delays reading a number. All of it disabled under `prefers-reduced-motion`.

### 8.6 Craft floor

Body text ≥ 4.5:1, large text ≥ 3:1, checked against the actual dark tokens above. Secondary
text is a tint of its surface hue, never a flat grey dropped on top. Every interactive element
gets hover, focus-visible, disabled, loading and empty states designed, not just the happy path.
Scrollbar, focus ring and `::selection` get dark treatments too.

### 8.7 Banned in shipped UI copy

- **Zero em dashes.** Not sparingly. If a sentence structurally wants one, restructure it.
- No fabricated precision. A number renders at the precision its source actually provides.
- No decorative status dots implying liveness. The staleness indicator is legitimate because
  it is genuinely live, and it must show the actual age as text, not just a dot.
- No section-number eyebrows, no fake version chrome, no icon-in-a-rounded-square above a
  heading as a card template.
- No "seamless", "robust", "unlock", "elevate".

### 8.8 Theming

**Dark only in P1**, as a deliberate commitment rather than an omission. Every colour is
consumed through a semantic token (`bg-background`, `bg-surface`, `text-content`,
`border-border`) from day one, never a raw palette class, so adding a light theme later is a
token file rather than a refactor.

---

## 9. P1e — Frontend architecture

**Stack.** Next.js App Router, TypeScript, Tailwind with the semantic tokens above, shadcn/ui as
a primitive base, `lightweight-charts` for price and volume, Recharts for small stat panels,
TanStack Query for caching and for polling `pending` sections, `openapi-typescript` generating
client types from the exported schema so client and server drift becomes a CI failure.

**Shell.** Persistent left rail: **Research · Options · Portfolio · P&L · Universe**. The last
four render an explicit "arrives in P2 / P3 / P4" panel rather than being hidden, so the finished
shape is legible from milestone 1. Rail footer carries the account stat block. Top right carries
connection state and data age.

**Routes.** `/` · `/stock/[symbol]` · `/recommendations` · `/watchlist`.

### 9.1 Landing

In the order requested: a command-palette search pinned at the top (⌘K, fuzzy across the full
symbol directory), then the watchlist dashboard as compact rows carrying price, change, IV rank,
check ribbon and next earnings, then the sector card grid.

Each sector card shows aggregate change, best and worst mover, constituent count, and
**aggregate IV rank**. That last field is the options-income lens applied at sector level, and no
consumer research site shows it: it answers "where is premium rich today" in one glance.

### 9.2 Ticker page

1. **Header** — price, change, sparkline, key-stats strip, check ribbon, provenance chips, `as_of`.
2. **Checks** — the six category ribbons. Clicking a category expands to its individual checks,
   each showing the statement, the actual value, the threshold, and its state.
3. **AI summary** — thesis, bulls, bears, watch items, caveats, labelled with the model that
   wrote it and the data `as_of` it saw.
4. **Price and technicals** — candles and volume, SMA 50/200, RSI and MACD panels, support and
   resistance bands from `technicals.py`, phase and regime badge.
5. **Fundamentals** — normalised statements, five annual and eight quarterly, plus ratios. Every
   cell traceable on hover to its accession number and filing date.
6. **Options-income lens** — rendered by default for universe names. For any other ticker, an
   explicit "Analyse for CC/CSP" action calls `/research/{symbol}/options` on demand.
7. **Sentiment and news** — headlines with per-item sentiment, StockTwits and Reddit scores with
   their sample counts, and velocity.

---

## 10. P1f — Testing

**Python.**

- Concept mapping and period selection against recorded EDGAR payloads from filers with awkward
  tags, including a restatement case and a unit-mismatch rejection.
- The checks engine, table-driven: every check gets a pass case, a fail case, and a
  missing-data case asserting `UNKNOWN`. This is the highest-value test surface in P1.
- Providers against recorded HTTP fixtures. No live network in CI.
- API via FastAPI `TestClient` against temporary databases, plus contract tests pinning every
  response to its schema. OpenAPI exported to `docs/web/openapi.json`; TS type generation runs
  in CI so drift fails the build.
- The extended fence test, both directions.
- `owner_only` routes reject a non-owner role.

**Frontend.** Vitest for lib and formatting. React Testing Library for the check-expansion and
search components. Playwright for the two flows worth guarding: search to ticker page rendering
correctly with **partial** data, and watchlist add/remove persisting.

---

## 11. P1g — Documentation

New: `docs/web/` (architecture, `api.md`, `checks.md`, `openapi.json`, runbook),
`web/CLAUDE.md`, `src/research/CLAUDE.md`.

Root `CLAUDE.md` gains exactly three things, to keep it from doubling: the one-way import fence,
the two-database rule, and new doc-update trigger rows —

| What changed | Files to update |
|---|---|
| New API endpoint | `docs/web/api.md`, regenerate `openapi.json` |
| New or changed check | `docs/web/checks.md`, `config/research_checks.yaml` comment |
| New data provider or Protocol | `ARCHITECTURE.md` config section, `docs/web/architecture.md` |
| New research config key | `docs/web/architecture.md`, `SETUP.md` if it affects setup |

`README.md` layout table and `SETUP.md` scripts table gain the two new entrypoints. `STATUS.md`
records P2–P5 as deliberately not built.

---

## 12. P1h — Sequencing

| # | Milestone | Ends with |
|---|---|---|
| 1 | Foundation | `src/api/`, auth, `/health` `/me` `/nav`, research.db models, fence test. Nothing user-visible. |
| 2 | Directory and search | EDGAR directory ingest, ⌘K search across the whole market, Next.js shell and rail. |
| 3 | Fundamentals pipeline | company facts, concept map, normalisation, statements rendering. Largest single chunk. |
| 4 | Prices, technicals, news, sentiment | The ticker page becomes genuinely useful. |
| 5 | Checks engine | Check ribbons and expandable check lists. The digestibility payoff. |
| 6 | Options lens and recommendations | `BuyCandidateRow` + `scan.py` persistence (§7), sector cards, watchlist dashboard, buy-list replacement. The site now does the Telegram card's job. |
| 7 | AI summary | Provider abstraction, four backends, caching, rendering. |

`format_buy_list` is removed only after milestone 6 has run in parallel for a couple of weeks.

---

## 13. Risks

1. **Repo growth.** Roughly 8.5k lines on 47k of Python, plus a new TypeScript tree. Mitigated
   by `docs/web/` owning web documentation so `ARCHITECTURE.md` (152KB) and `STATUS.md` (164KB)
   do not absorb it, and by scoped `CLAUDE.md` files keeping the root file lean.
2. **A JavaScript toolchain enters a pure-Python repo.** A real cost in CI and review, accepted
   because P5 and the public-ready goal both need a versioned JSON API with generated client
   types regardless.
3. **Free-tier fragility.** yfinance will break. The provider abstraction is the mitigation and
   only works if nothing bypasses it.
4. **stooq licensing is unverified.** Milestone 4 verifies it before it becomes load-bearing;
   yfinance is the documented fallback.
5. **Cold-tier first-view latency.** An 8s budget is generous for a page load. The partial
   payload plus polling path is what keeps it acceptable, and it must be built in milestone 3
   rather than retrofitted.
6. **AI summaries that sound more certain than the data.** Structured output, passed-in numbers
   only, and a rendered caveat are the mitigations.

---

## 14. Deferred to later phases

- **P2** — the options console, manual execute and roll. Requires the `app_commands` intent
  queue from the 2026-08-10 spec §9.3 and a full safety review, which is why it is not here.
- **P3** — portfolio screens.
- **P4** — profitability tracker, including closed-position accounting on top of `fills`,
  `campaigns` and `verdict_ledger`.
- **P5** — mobile, consuming this API unchanged.
- **Universe editing** from the web. P1 renders `/universe` read-only; editing needs the
  `universe_overrides` mechanism from the 2026-08-10 spec §9.4, which belongs with P2's write
  path.
