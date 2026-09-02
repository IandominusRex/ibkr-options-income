# Web Platform P0 + P1 — Implementation Plan (Index)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a private, dark, data-dense web console whose first section is a Stock Researcher
that can analyse any US ticker in full depth, and which replaces the Telegram buy-list card.

**Architecture:** A FastAPI JSON API (`src/api/`) and an ingestion worker (`src/research/`) run
as two new processes holding no `ib_async` connection. They read the trading SQLite read-only
and own a second database, `data/research.db`. A Next.js client consumes the API through
OpenAPI-generated TypeScript types. Fundamentals come from SEC EDGAR XBRL, normalised through a
config-driven concept map; a deterministic checks engine collapses them into pass/fail/unknown
checks; a pluggable AI backend writes narrative only.

**Tech Stack:** Python 3.12, FastAPI, uvicorn, SQLAlchemy 2.0, Pydantic 2, APScheduler, httpx ·
Next.js App Router, TypeScript, Tailwind, shadcn/ui, TanStack Query, lightweight-charts,
Recharts · pytest, ruff, mypy, Vitest, Playwright.

**Spec:** `Web plan/P0-P1-design.md` (read it first). Context: `Web plan/OVERVIEW.md`.

---

## Global Constraints

Every task's requirements implicitly include this section. Values are copied verbatim from the
spec.

**Repo-wide (from `CLAUDE.md`)**
- Python ≥ 3.12. Type-hint everything. Ruff line length 100.
- Quality gate before any task is complete: `python -m pytest -q` · `ruff check .` · `mypy src`
- Config in `config/*.yaml`; secrets only in `.env`, never logged or committed.
- Modules communicate only through Pydantic schemas. No raw `ib_async` objects across a boundary.
- `analytics/strategies/engine` never call `yfinance.*` directly. Everything goes through
  `src/data/`.
- Money is explicit; option premiums are per share.

**New invariants this plan introduces**
- The API opens `data/income_system.db` **read-only** (`?mode=ro` URI) and writes to it never.
- `data/research.db` has its own SQLAlchemy `Base` in `src/research/store/models.py`. It must
  **not** import `src/storage/models.py`'s `Base`.
- **One-way import fence:** `src/engine/`, `src/execution/` and `src/strategies/` may never
  import `src.api` or `src.research`. `src/research/checks/` may never import
  `src.research.summary`.
- Neither new process constructs an `ib_async` connection or holds a clientId.

**Data-source rules**
- EDGAR: declared `User-Agent` header from config, ≤ 10 requests/second, CIK zero-padded to 10
  digits, ETag revalidation, backoff on 403/429.
- Provenance envelope on every headline number: `{value, source, as_of, stale}` with
  `source ∈ {edgar, yfinance, stooq, ibkr, computed}`. Every response carries a top-level
  `as_of`.
- Check states are exactly four: `PASS`, `FAIL`, `UNKNOWN`, `NOT_APPLICABLE`. `UNKNOWN` means
  the data was unavailable; `NOT_APPLICABLE` means the question does not apply to this
  instrument. They are never conflated.

**Frontend rules (from spec §8)**
- Dark only in P1. Every colour is consumed through a semantic token (`bg-background`,
  `bg-surface`, `bg-elevated`, `text-content`, `text-muted`, `border-border`). **No raw
  `bg-white`, `bg-gray-*`, or hex literals in components.**
- Tokens: `--bg-background #121212` · `--bg-surface #181818` · `--bg-elevated #282828` ·
  `--text-content #F5F5F5` · `--text-muted #A7A7A7`.
- Elevation is communicated by **lightness, never shadow**. Never stack a border and a shadow on
  the same surface.
- Fonts: **IBM Plex Sans** for UI, **IBM Plex Mono** for tickers, prices, and financial table
  cells. Tabular figures everywhere numbers align in columns.
- Semantic colour only: gain/pass green, loss/fail red, unknown achromatic plus hatch texture,
  and a single slate-blue for focus/selection that is deliberately neither cyan nor the gain
  green.
- State is never encoded by colour alone. Fill and texture carry it too.
- Body text ≥ 4.5:1 contrast, large text ≥ 3:1, checked against the actual dark tokens.
- Every interactive element has hover, focus-visible, disabled, loading and empty states.
- `prefers-reduced-motion` disables all motion. Charts never animate their data in.
- **Zero em dashes in shipped UI copy.** Not sparingly. Restructure the sentence instead.
- No fabricated precision, no decorative status dots, no section-number eyebrows, no fake
  version chrome, no icon-in-a-rounded-square above a heading as a card template.
- Banned words in UI copy: "seamless", "robust", "unlock", "elevate".

---

## Model routing

Tasks are tagged **`[GLM]`** or **`[SONNET]`**. The split is by task property, not by guesswork.

### Route to GLM 5.2 when *all* of these hold

1. The interface is fully specified in the task's `Interfaces` block (exact signatures and types).
2. Success is verifiable by test code the task already contains.
3. It touches at most three files and **no trading-system code**.
4. No `CLAUDE.md` invariant is in scope.
5. External data shapes are known and fixed, not variable across sources.

### Route to Sonnet when *any* of these hold

1. **It touches trading-system code** — `src/engine/`, `src/execution/`, `src/strategies/`,
   `src/orchestrator/`, `src/storage/models.py`, `src/claude/`.
2. **It enforces or tests an invariant** — the fence, the import fence, `owner_only`, read-only
   DB access.
3. **It handles unpredictable external data** — EDGAR concept variance across filers, partial
   payloads, provider failure modes.
4. **It requires a judgment call about degradation** — what a page shows when a source is down.
5. **It sets a pattern later tasks copy** — the first router, the first provider, the first
   component. Getting the first one wrong multiplies.
6. **GLM has failed the task twice.** Escalate rather than iterating a third time.

### Escalation protocol

If a `[GLM]` task's tests still fail after two honest attempts, stop and re-run it on Sonnet.
Do not weaken the test to make it pass; the test is the specification. Record the escalation in
the task checkbox line so the routing rules can be tuned from evidence.

---

## Routing summary

| Milestone | Task | Model | Why |
|---|---|---|---|
| M1 | 1.1 Research configuration (`research.yaml`) | GLM | Mechanical, mirrors existing loader |
| M1 | 1.2 Research DB models + session | GLM | Fixed schema, given verbatim |
| M1 | 1.3 Provenance envelope (`Sourced[T]`) | SONNET | Sets the pattern every later payload copies |
| M1 | 1.4 Auth boundary (`CurrentUser`, `require_owner`) | SONNET | Security boundary; fails closed |
| M1 | 1.5 Read-only trading DB access | SONNET | Invariant: must be provably read-only |
| M1 | 1.6 App factory + `/health` `/me` `/nav` | SONNET | First router; sets the pattern |
| M1 | 1.7 Import fence test | SONNET | Enforces a `CLAUDE.md` invariant |
| M1 | 1.8 Entrypoint + docs | GLM | Thin entrypoint |
| M2 | 2.1 `SymbolDirectoryProvider` protocol + factory | GLM | Mirrors existing protocol pattern |
| M2 | 2.2 EDGAR directory backend | SONNET | First EDGAR client: rate limiting, UA, ETag |
| M2 | 2.3 Symbol ingest job | GLM | Straight transform into a known schema |
| M2 | 2.4 `/research/search` | GLM | Simple query endpoint, pattern set by 1.5 |
| M2 | 2.5 Worker process + scheduler | SONNET | Process model; failure modes |
| M2 | 2.6 Next.js scaffold + tokens + fonts | SONNET | Sets every frontend convention |
| M2 | 2.7 Left rail + shell | GLM | Tokens and conventions already fixed |
| M2 | 2.8 Command-palette search | GLM | Self-contained component |
| M3 | 3.1 `FilingsProvider` protocol + companyfacts | SONNET | External data variance |
| M3 | 3.2 Concept map config + resolver | SONNET | The hardest correctness surface in P1 |
| M3 | 3.3 Period selection + restatements | SONNET | Subtle correctness, silent-wrongness risk |
| M3 | 3.4 Unit enforcement | GLM | Narrow, fully specified |
| M3 | 3.5 `NormalizedFinancials` + persistence | GLM | Schema given verbatim |
| M3 | 3.6 Bounded materialisation + `ingest_jobs` | SONNET | Degradation judgment; partial payloads |
| M3 | 3.7 `/research/{symbol}` | SONNET | Assembles the partial-payload contract |
| M3 | 3.8 Ticker page + statements table | GLM | Conventions fixed by 2.6 |
| M4 | 4.1 `BulkPriceProvider` + stooq backend | SONNET | Licence verification; fallback logic |
| M4 | 4.2 Daily bars ingest | GLM | Mechanical |
| M4 | 4.3 Delayed quote refresh (warm tier) | GLM | Mechanical |
| M4 | 4.4 Technicals + news + sentiment wiring | SONNET | Crosses the analytics tier boundary |
| M4 | 4.5 Price chart | GLM | Self-contained, library-driven |
| M4 | 4.6 Technicals + news panels | GLM | Self-contained |
| M4 | 4.7 Per-provider circuit breaker | SONNET | Degradation judgment |
| M5 | 5.1 Check definition schema + loader | GLM | Fixed shape |
| M5 | 5.2 Checks engine, four states | SONNET | The `UNKNOWN`/`NOT_APPLICABLE` distinction |
| M5 | 5.3 The 30 fundamental check definitions | SONNET | Threshold judgment; wrong = misleading |
| M5 | 5.4 ETF fund category + leverage warning | SONNET | Instrument-type judgment |
| M5 | 5.5 Options-income category | SONNET | Reads deterministic analytics tier |
| M5 | 5.6 Check ribbon component | SONNET | The signature component; accessibility |
| M5 | 5.7 Category expansion UI | GLM | Pattern set by 5.6 |
| M6 | 6.1 `BuyCandidateRow` + `scan.py` persistence | SONNET | **Trading-system code** |
| M6 | 6.2 `/research/recommendations` | GLM | Read-only query |
| M6 | 6.3 `/research/{symbol}/options` | SONNET | Best-effort degradation for off-universe |
| M6 | 6.4 Sector cards + aggregate IV rank | GLM | Aggregation over known data |
| M6 | 6.5 Watchlist CRUD + dashboard | GLM | Standard CRUD |
| M6 | 6.6 `GET /universe` (read-only) | GLM | Config passthrough |
| M7 | 7.1 `SummaryProvider` protocol + context builder | SONNET | Fence-critical |
| M7 | 7.2 `claude_cli` backend | SONNET | Touches `src/claude/` |
| M7 | 7.3 `anthropic` / `openai` / `ollama` backends | GLM | Pattern fixed by 7.2 |
| M7 | 7.4 Summary caching + on-demand trigger | GLM | Mechanical |
| M7 | 7.5 Fence test extension | SONNET | Enforces an invariant |
| M7 | 7.6 Summary panel UI | GLM | Self-contained |
| M7 | 7.7 Close out P1 (docs, regen, final gate) | GLM | Mechanical |

**Totals: 51 tasks, 25 GLM and 26 Sonnet.** Sonnet concentrates in M3 (data correctness) and M5
(check semantics), which is where silent wrongness is most expensive and least visible. Only one
task in the entire plan (6.1) modifies trading-system code.

---

## Milestone files

| File | Ends with |
|---|---|
| `milestones/M1-foundation.md` | API process, auth, research DB, fences. Nothing user-visible. |
| `milestones/M2-directory-search.md` | Search across the whole market; shell and rail on screen. |
| `milestones/M3-fundamentals.md` | Normalised statements rendering on a ticker page. |
| `milestones/M4-prices-technicals.md` | Chart, technicals, news, sentiment. Page is useful. |
| `milestones/M5-checks.md` | Check ribbons and expandable checks. The digestibility payoff. |
| `milestones/M6-options-recommendations.md` | Sector cards, watchlist, buy-list replacement. |
| `milestones/M7-ai-summary.md` | Four AI backends, caching, rendering. |

Milestones are strictly sequential. Each ends green on the full quality gate and is shippable on
its own.

---

## Cutover

`format_buy_list` and its scheduled send are **not** removed by this plan. After M6 has run in
parallel for two weeks and the web recommendations are trusted, removing it is a separate
one-task change that also updates `README.md`, `SETUP.md` and `ARCHITECTURE.md`'s Telegram
command tables.

---

## Documentation obligations

Per `CLAUDE.md`'s mandatory doc-update rule, these are **not optional** and each is folded into
the task whose deliverable creates the obligation:

| Trigger in this plan | Task | Files |
|---|---|---|
| New packages `src/api/`, `src/research/` | 1.5, 2.5 | `README.md` layout table, `ARCHITECTURE.md` folder guide |
| New scripts `run_api.py`, `run_research_worker.py` | 1.8, 2.5 | `SETUP.md` scripts table, `README.md` layout table |
| New config `research.yaml`, `research_checks.yaml`, `research_concepts.yaml` | 1.2, 5.1, 3.2 | `ARCHITECTURE.md` config section, `SETUP.md` |
| New storage model `BuyCandidateRow` | 6.1 | `ARCHITECTURE.md` `src/storage/` + data-flow sections |
| New API endpoints | each router task | `docs/web/api.md`, regenerate `docs/web/openapi.json` |
| New or changed check | 5.3, 5.4, 5.5 | `docs/web/checks.md` |
| Features built or deferred | M1 and M7 | `STATUS.md` |
