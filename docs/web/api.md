# Web API reference

Every endpoint the FastAPI app (`src/api/main.py`) exposes. Updated by every router task.

## Conventions

- **Auth:** every route except `GET /health` requires `Authorization: Bearer <WEB_API_TOKEN>`.
  The token is configured via `.env` (`WEB_API_TOKEN`). An unset token rejects everything.
- **Content type:** `application/json` for every response, including errors (404 returns JSON,
  never HTML).
- **Envelope:** every response body carries a top-level `as_of: <ISO 8601 UTC>` stamp. Headline
  numbers ship as `Sourced{value, source, as_of, stale}` (see `src/api/models/common.py`).
- **Errors:** `{ "detail": "<message>" }`. FastAPI's standard 422 validation errors keep their
  nested `detail` array shape.

---

## `GET /health`

Liveness + reachability of the two databases. **No auth required.**

**Response — `HealthResponse`:**

| Field | Type | Notes |
|---|---|---|
| `as_of` | datetime | |
| `status` | `"ok"` \| `"degraded"` | `degraded` when either DB is unreachable, or any provider circuit breaker is `open` |
| `research_db` | bool | research.db reachable |
| `trading_db` | bool | income_system.db reachable (read-only) |
| `worker_heartbeat` | datetime \| null | last successful research-worker job; `null` until the worker runs |
| `providers` | `dict[string, string]` | (M4) one entry per circuit breaker registered so far this process (`src/data/breaker.py`, lazily created on first use) — `"closed"` \| `"open"` \| `"half_open"` — keyed by provider name (`edgar`, `yfinance_prices`, `yfinance_news`) |

**Example:**

```json
{
  "as_of": "2026-09-03T10:00:00Z",
  "status": "ok",
  "research_db": true,
  "trading_db": true,
  "worker_heartbeat": null,
  "providers": { "edgar": "closed", "yfinance_prices": "closed", "yfinance_news": "closed" }
}
```

---

## `GET /me`

The authenticated user's identity and role.

**Response — `MeResponse`:**

| Field | Type |
|---|---|
| `as_of` | datetime |
| `id` | string |
| `role` | `"owner"` \| `"viewer"` |

**Example:**

```json
{ "as_of": "2026-09-03T10:00:00Z", "id": "owner", "role": "owner" }
```

---

## `GET /nav`

The navigation manifest that used to drive the web app's left rail. Lists every section with an
`available` flag; unavailable sections render disabled with their `note` as the reason.
**No longer read by the web** since web overhaul Part 1 (the rail and tab bar come from
`web/lib/nav.ts`); the route and its test are removed in Part 4.

**Response — `NavResponse`:**

| Field | Type |
|---|---|
| `as_of` | datetime |
| `sections` | `NavSection[]` |

`NavSection`: `{ as_of, key, label, available, note? }`

**Example:**

```json
{
  "as_of": "2026-09-03T10:00:00Z",
  "sections": [
    { "as_of": "2026-09-03T10:00:00Z", "key": "research", "label": "Research", "available": true, "note": null },
    { "as_of": "2026-09-03T10:00:00Z", "key": "options", "label": "Options", "available": true, "note": null },
    { "as_of": "2026-09-03T10:00:00Z", "key": "portfolio", "label": "Portfolio", "available": true, "note": null },
    { "as_of": "2026-09-03T10:00:00Z", "key": "pnl", "label": "P&L", "available": true, "note": null },
    { "as_of": "2026-09-03T10:00:00Z", "key": "universe", "label": "Universe", "available": true, "note": null }
  ]
}
```

---

## `GET /research/search`

Fuzzy-search the SEC filer symbol directory (~10,000 tickers). Ranking: exact ticker match
first, then ticker prefix, then name substring — each alphabetical within its band.

**Auth:** required.

**Query parameters:**

| Param | Type | Default | Constraint |
|---|---|---|---|
| `q` | string | `""` | max 64 chars; blank returns no results |
| `limit` | int | `20` | `1`–`50`; out of range returns `422` |

**Response — `SearchResponse`:**

| Field | Type |
|---|---|
| `as_of` | datetime |
| `query` | string (the raw `q` as submitted) |
| `results` | `SearchHit[]` |

`SearchHit`: `{ as_of, symbol, name, exchange?, is_etf }`

**Example — `GET /research/search?q=AAP`:**

```json
{
  "as_of": "2026-09-03T10:00:00Z",
  "query": "AAP",
  "results": [
    { "as_of": "2026-09-03T10:00:00Z", "symbol": "AAP",  "name": "Advance Auto Parts", "exchange": "NYSE",  "is_etf": false },
    { "as_of": "2026-09-03T10:00:00Z", "symbol": "AAPL", "name": "Apple Inc.",         "exchange": "Nasdaq", "is_etf": false }
  ]
}
```

---

## `GET /research/{symbol}`

The full analysis payload for one ticker. The contract every later section plugs into: the
response is an `AnalysisResponse` carrying one `Section` per region of the page, and a slow
or missing section **never fails the whole page** — it degrades per section.

**Auth:** required. **404** only when `symbol` is not a known SEC filer (no row in the
`symbols` table). Everything else is a 200 with per-section state.

**Path parameter:**

| Param | Type | Notes |
|---|---|---|
| `symbol` | string | case-insensitive; resolved via `symbol.upper()` |

**Response — `AnalysisResponse`:**

| Field | Type | Notes |
|---|---|---|
| `as_of` | datetime | |
| `symbol` | string | upper-cased |
| `name` | string | from the symbol directory |
| `exchange` | string \| null | |
| `is_etf` | bool | |
| `fundamentals` | `Section<NormalizedFinancials>` | see below |
| `technicals` | `Section<TechnicalStats>` | (M4) RSI 14, MACD, SMA 50/200, ATR, phase/regime — defaults `pending` |
| `sentiment` | `Section<SentimentDetail>` | (M4) composite score, label, 1-day delta, per-source sample counts — defaults `pending` |
| `news` | `Section<NewsItem[]>` | (M4) recent headlines, newest first, each carrying its own VADER `sentiment` — defaults `pending` |
| `checks` | `Section<ChecksPayload>` | (M5) the check ribbon + warnings, evaluated from `build_metrics()` + `evaluate()` + `warnings_for()` — see `docs/web/checks.md` for the full catalogue and thresholds — defaults `pending` |
| `quote` | `Sourced<float>` \| null | (M4) delayed last price; `as_of` is the warm-tier `QuoteRow`'s own capture time (not the request time), so `stale` (after 30 minutes, `fresh_for` on `Sourced.of`) reflects the quote's actual age; `null` when no quote has been fetched for this symbol |

`technicals`, `sentiment`, `news`, and `checks` each degrade **independently** — an outage in
one (e.g. StockTwits down) never blocks the others, and never touches `fundamentals`.

**`ChecksPayload`** (M5):

| Field | Type | Notes |
|---|---|---|
| `categories` | `CategoryPayload[]` | catalogue order; a stock never gets a `fund` entry, an ETF gets all seven with the five fundamental categories `not_applicable` |
| `warnings` | `Warning[]` | structural caveats (leveraged-ETF daily-reset decay) — never checks, never dilutes a category score |

**`CategoryPayload`:**

| Field | Type | Notes |
|---|---|---|
| `category` | string | `value` \| `growth` \| `past` \| `health` \| `dividend` \| `fund` \| `options` |
| `passed` / `failed` / `unknown` | int | |
| `evaluable` | int | `passed + failed` — the denominator the UI reports against, never `total` when `unknown > 0` |
| `total` | int | checks defined for this category |
| `not_applicable` | bool | true for a fundamental category on an ETF (files no XBRL) |
| `note` | string \| null | populated only when `not_applicable` |
| `checks` | `CheckResult[]` | every check in the category, for `ChecksSection`'s expand/collapse |

**`CheckResult`:** `id`, `category`, `statement` (a question), `state`
(`PASS`\|`FAIL`\|`UNKNOWN`\|`NOT_APPLICABLE`), `actual` (float \| null), `threshold` (float \|
`[low, high]` \| null), `note` (string \| null, set for `UNKNOWN`/`NOT_APPLICABLE`).

**`Warning`:** `level` (`"info"` \| `"caution"`), `title`, `detail`.

**Side effect:** every call upserts a `RecentlyViewedRow(user_id, symbol)` with the current
timestamp — this is the only signal the warm tier's `refresh_quotes` (Task 4.3,
`ingest/quotes.py`) has for which symbols were "recently viewed" in the last 7 days.

**`Section[T]`** — one region of the page, with its own state:

| Field | Type | Notes |
|---|---|---|
| `state` | `"ready"` \| `"pending"` \| `"unavailable"` | see `SectionState` |
| `data` | `T` \| null | present when `state == "ready"`; null otherwise |
| `reason` | string \| null | rendered to the user verbatim — reads as an explanation, not an exception |

**`SectionState`:**

| Value | Meaning | Client behaviour |
|---|---|---|
| `ready` | data is present | render |
| `pending` | queued; still building | poll (the page's `refetchInterval` re-fetches every 5s while any section is `pending`) |
| `unavailable` | will not resolve | render the `reason` inline; stop polling |

A slow section is a **200 with a `reason`**, not an error — the contract is "the page always
renders, the section explains itself." An ETF with no XBRL still gets a page; its
fundamentals section carries `state=unavailable` and a human-readable `reason`.

**Example — `GET /research/AAPL` (ready):**

```json
{
  "as_of": "2026-09-03T10:00:00Z",
  "symbol": "AAPL",
  "name": "Apple Inc.",
  "exchange": "Nasdaq",
  "is_etf": false,
  "fundamentals": {
    "state": "ready",
    "data": {
      "symbol": "AAPL",
      "cik": "0000320193",
      "entity_name": "Apple Inc.",
      "annual": [
        { "period_end": "2024-09-28", "period_type": "annual",
          "items": { "revenue": { "line_item": "revenue", "value": 391035000000,
            "concept": "Revenues", "accn": "0000320193-24-000123",
            "filed": "2024-11-01", "form": "10-K" } } }
      ],
      "quarterly": []
    },
    "reason": null
  }
}
```

**Example — `GET /research/SPY` (unavailable, ETF with no XBRL):**

```json
{
  "as_of": "2026-09-03T10:00:00Z",
  "symbol": "SPY",
  "name": "SPDR S&P 500 ETF Trust",
  "exchange": "Arca",
  "is_etf": true,
  "fundamentals": {
    "state": "unavailable",
    "data": null,
    "reason": "No XBRL financial statements filed for this symbol"
  }
}
```

**Example — first cold view of a slow symbol (pending):**

```json
{
  "as_of": "2026-09-03T10:00:00Z",
  "symbol": "XYZ",
  "name": "XYZ Holdings",
  "exchange": "Nasdaq",
  "is_etf": false,
  "fundamentals": {
    "state": "pending",
    "data": null,
    "reason": "Still building; refresh shortly"
  }
}
```

**Example — M4 enrichment sections, ready:**

```json
{
  "as_of": "2026-09-03T10:00:00Z",
  "symbol": "AAPL",
  "name": "Apple Inc.",
  "exchange": "Nasdaq",
  "is_etf": false,
  "fundamentals": { "state": "ready", "data": { "...": "..." }, "reason": null },
  "technicals": {
    "state": "ready",
    "data": { "rsi_14": 55.2, "macd": 1.3, "sma_50": 220.1, "sma_200": 205.4, "atr": 3.2 },
    "reason": null
  },
  "sentiment": {
    "state": "unavailable",
    "data": null,
    "reason": "StockTwits down"
  },
  "news": {
    "state": "ready",
    "data": [
      { "title": "Apple beats estimates", "url": "https://example.com/a", "published_at": "2026-09-03T09:00:00Z", "source": "Reuters", "sentiment": 0.62 }
    ],
    "reason": null
  },
  "quote": { "value": 221.4, "source": "yfinance", "as_of": "2026-09-03T09:45:00Z", "stale": false }
}
```

A `sentiment` outage above leaves `technicals` and `news` `ready` — sections degrade
independently, never cascading.

---

## `GET /research/{symbol}/bars`

Daily OHLCV for the price chart, with server-side SMA 50/200 overlays so the chart and the
`technicals` section can never disagree.

**Auth:** required. **404** when `symbol` is not a known SEC filer.

**Path parameter:** `symbol` (case-insensitive).

**Query parameters:**

| Param | Type | Default | Constraint |
|---|---|---|---|
| `range` | string | `"1y"` | one of `1mo`, `3mo`, `6mo`, `1y`, `2y`, `5y` |

**Response — `BarsResponse`:**

| Field | Type | Notes |
|---|---|---|
| `as_of` | datetime | |
| `bars` | `Bar[]` | ascending by date; empty (not an error) when no bars are ingested yet |
| `sma50` | `(float \| null)[]` | parallel to `bars`; `null` until 50 closes have accumulated |
| `sma200` | `(float \| null)[]` | parallel to `bars`; `null` until 200 closes have accumulated |

The endpoint fetches an extra `_SMA_SEED_BUFFER_DAYS=400`-day lookback beyond `range`'s
display window before computing the SMAs, then slices bars and SMAs back down together —
so `sma200` is populated from the *first* bar in `bars` whenever `daily_bars` actually holds
that much history, not just for the last ~50 days of a `range=1y` response. It still comes
back `null` for a genuinely short window (`range=1mo`) or a symbol whose ingested history
doesn't reach back far enough — that's an honest "not enough data yet", not a bug.

`Bar`: `{ time, open, high, low, close, volume }` — `time` is `YYYY-MM-DD`, lightweight-charts'
expected daily field name, so no client-side remapping is needed.

**Example — `GET /research/AAPL/bars?range=1y`:**

```json
{
  "as_of": "2026-09-03T10:00:00Z",
  "bars": [
    { "time": "2026-08-28", "open": 220.0, "high": 222.5, "low": 219.0, "close": 221.4, "volume": 50000000 },
    { "time": "2026-08-29", "open": 221.5, "high": 224.0, "low": 221.0, "close": 223.8, "volume": 48000000 }
  ],
  "sma50": [null, null],
  "sma200": [null, null]
}
```

---

## `GET /research/{symbol}/headlines`

The newest headlines for one symbol, for the position page's news section (web Home follow-ups,
2026-10-15). It calls the headline loader only, never `materialize()`, which can start an SEC
fundamentals ingest, so it is cheap enough to open from a Positions row. Enrichment tier: the
headlines (each VADER-scored) reach the page and never the engine. Nothing is stored.

| Param | Type | Notes |
|---|---|---|
| `limit` | int, 1 to 25 | default 8 |

`422` when the symbol is not a ticker (`^[A-Z][A-Z0-9.-]{0,9}$` after upper-casing). An
unreachable news source is an empty `items` list, never an error.

**Response - `HeadlinesResponse`:** `{ as_of, symbol, items: NewsItem[] }`, newest first (undated last);
`NewsItem`: `{ title, url, published_at, source, sentiment }` (the same shape as the analysis
route's news section; an item with no title is dropped).

## `GET /research/{symbol}/options`

The on-demand options-income lens (Task 6.3). Registered directly ahead of
`GET /research/{symbol}` so the path route can't swallow it — `/research/search` and
`/research/NVDA/options` both resolve correctly.

Honest degradation is the point: a universe symbol (one of `universe.yaml`'s
`indexes`/`watchlist`/`would_own`/`actively_wheeling` lists — the "hot" tier) gets real
`iv_rank`/`vrp_points`, read through the **read-only** trading engine (§4.3). An
off-universe ("cold") symbol with no `iv_history` gets the same response shape with those
checks `UNKNOWN` rather than a rank invented from a short series. `coverage.option_chain`
is always `false` in P1 — the API process holds no IBKR connection, so
`atm_open_interest`/`atm_spread_pct` stay `UNKNOWN` too, and the response says so rather
than the UI quietly showing blanks. Leverage warnings (Task 5.4) are included for
leveraged names via the shared `warnings_for` catalogue.

**Auth:** required. **404** when `symbol` is not a known SEC filer.

**Path parameter:** `symbol` (case-insensitive).

**Response — `OptionsLensResponse`:**

| Field | Type | Notes |
|---|---|---|
| `as_of` | datetime | |
| `symbol` | string | |
| `in_universe` | bool | true iff `symbol` is in one of `universe.yaml`'s four lists |
| `tier` | `"hot" \| "cold"` | mirrors `in_universe` |
| `checks` | `CheckResult[]` | the `research_checks.yaml` catalogue's `options` category only (`iv_rank`, `vrp_positive`, `chain_open_interest`, `spread_tight`, `cc_yield`, `earnings_clear`) |
| `warnings` | `Warning[]` | leveraged-ETF daily-reset-decay caveats (Task 5.4), empty for an ordinary name |
| `coverage` | `{ iv_history: bool, option_chain: bool }` | `option_chain` is always `false` in P1 |

`CheckResult`: `{ id, category, statement, state: "PASS"|"FAIL"|"UNKNOWN"|"NOT_APPLICABLE", actual (float\|null), threshold, note (string\|null) }` — full catalogue: `docs/web/checks.md`.

**Example — `GET /research/NVDA/options` (universe symbol):**

```json
{
  "as_of": "2026-09-05T10:00:00Z",
  "symbol": "NVDA",
  "in_universe": true,
  "tier": "hot",
  "checks": [
    { "id": "options.iv_rank", "category": "options", "statement": "Is implied volatility rank above 30?", "state": "PASS", "actual": 62.5, "threshold": 30.0, "note": null }
  ],
  "warnings": [],
  "coverage": { "iv_history": true, "option_chain": false }
}
```

**Example — `GET /research/RIVN/options` (off-universe symbol, no iv_history):**

```json
{
  "as_of": "2026-09-05T10:00:00Z",
  "symbol": "RIVN",
  "in_universe": false,
  "tier": "cold",
  "checks": [
    { "id": "options.iv_rank", "category": "options", "statement": "Is implied volatility rank above 30?", "state": "UNKNOWN", "actual": null, "threshold": 30.0, "note": "Input data unavailable" }
  ],
  "warnings": [],
  "coverage": { "iv_history": false, "option_chain": false }
}
```

---

## `GET /research/recommendations`

The scan's buy-to-own list, rendered exactly as `generate_buy_candidates` scored it. The
web layer does **no re-scoring** — every field is the value the scan produced at scan
time, persisted in `BuyCandidateRow` and read back unmodified so the site and the
Telegram card can never disagree about what the system thinks.

**Auth:** required. Reads through the **read-only** trading engine (§4.3 — the API
writes nothing).

**Query parameters:**

| Param | Type | Default | Constraint |
|---|---|---|---|
| `limit` | int | `25` | `1`–`100` |

**Response — `RecommendationsResponse`:**

| Field | Type | Notes |
|---|---|---|
| `as_of` | datetime | request time |
| `computed_at` | datetime \| null | the run the displayed candidates came from; `null` when no scan has run |
| `candidates` | `BuyCandidateOut[]` | ranked by score descending; empty (not an error) when no full scan has run |

`BuyCandidateOut` carries the full `BuyCandidate` shape (`symbol`, `score`, `sector`,
`iv_rank`, `quality_flag`, `technical_regime`, `rationale`, `price`, `current_iv`,
`hv_30`, `vrp`, `rsi_14`, `sma_50`, `sma_200`, `next_earnings`, `dividend_yield`,
`est_monthly_cc_yield`, `iv_score`, `fundamental_score`, `technical_score`). An empty
table returns an empty list with a 200, not a 404. Single-ticker `/scan TICKER` runs are
excluded — a `/scan NVDA` cannot replace the whole list with one name.

---

## `GET /research/sectors`

The sector card grid for the landing page. Sector membership comes from
`universe.yaml`'s `sectors` map. `change_pct` is the warm-tier quote's daily change; a
sector with no priced members reports `null`, never `0`. `avg_iv_rank` averages only
members with IV history (read-only from the trading DB), and `iv_rank_count` carries
the contributing count so a one-name average is visible. Cards are ordered by
`avg_iv_rank` descending.

**Auth:** required.

**Response — `SectorsResponse`:**

| Field | Type |
|---|---|
| `as_of` | datetime |
| `sectors` | `SectorCard[]` |

`SectorCard`: `{ sector, count, change_pct (float\|null), best: SectorMover, worst: SectorMover, avg_iv_rank (float\|null), iv_rank_count }`.
`SectorMover`: `{ symbol, change_pct (float\|null) }`. `best`/`worst` use `{ symbol: "-", change_pct: null }` when the sector has no priced members.

---

## `GET /watchlist`

The user's tracked symbols, scoped to their `user_id` (defaulting to `"owner"`). A
second user's items are not returned.

**Auth:** required.

**Response — `WatchlistResponse`:**

| Field | Type |
|---|---|
| `as_of` | datetime |
| `items` | `WatchlistItem[]` |

`WatchlistItem`: `{ symbol, name, price: Sourced<float> \| null, change_pct (float\|null), iv_rank (float\|null), checks: {passed, evaluable, unknown}, next_earnings (date\|null) }`. `price` is the warm-tier quote as a `Sourced` envelope (stale after 30 min). `checks` is the aggregate count — the full per-check payload lives on the ticker page.

---

## `POST /watchlist/{symbol}`

Add a symbol to the current user's watchlist. **Idempotent:** a first add returns 201; a
repeat returns 200 with `{added: false}` (not an error). Adding a symbol promotes it to
the warm tier immediately (`warm_symbols()` reads `WatchlistItemRow`).

**Auth:** required.

| Status | When |
|---|---|
| 201 | first add |
| 200 | repeat add (idempotent) |
| 404 | symbol is not a known SEC filer |

**Response (201/200):** `{ symbol, added }` where `added` is `true` on first add, `false` on repeat.

---

## `DELETE /watchlist/{symbol}`

Remove a symbol from the current user's watchlist. **Idempotent:** a repeat delete is
still 204.

**Auth:** required. **204** on success or already-absent.

---

## `GET /universe`

The effective scan universe (`config/universe.yaml` composed with any
`universe_overrides` rows — M7 Task 7.3's `effective_universe()`), reported as four
per-list entries so the client can render override provenance and offer a revert
(`editable: true` since Task 7.4).

**Auth:** required.

**Response — `UniverseResponse`:**

| Field | Type | Notes |
|---|---|---|
| `as_of` | datetime | |
| `lists` | `UniverseListOut[]` | exactly four, in this order: `indexes`, `watchlist`, `would_own`, `actively_wheeling` |
| `sectors` | `Record<string, string>` | symbol → sector tag |
| `strike_bands` | `Record<string, number>` | symbol → band fraction, only overrides |
| `editable` | bool | `true` — Task 7.4 shipped the write path |

`UniverseListOut`: `{ name: string, overridable: bool, entries: UniverseEntry[] }`.
`overridable` is `true` only for `would_own`/`watchlist`; `indexes` and
`actively_wheeling` are always `overridable: false` and their `entries` never carry
override metadata (not even when a stray `universe_overrides` row names a symbol in one
of those lists — defence in depth, mirroring the composer's own discipline).

`UniverseEntry`: `{ symbol: string, overridden: bool, removed: bool, created_by: string
| null, created_at: datetime | null }`. For `would_own`/`watchlist`, `entries` is the
**union** of the YAML base membership (file order) and any override row for that list —
not just the composed (already-filtered) list — so a `remove`-overridden YAML-base
symbol is still visible with `removed: true` and its provenance, letting the UI grey it
out and offer a revert (`POST` the same symbol back). A symbol added purely via override
(not in the YAML base) is appended after the base entries, in `created_at` order, with
`overridden: true`. A `remove` override on a symbol the `actively_wheeling` guard kept in
`would_own` (see `POST`/`DELETE` below) shows `overridden: true, removed: false` — the row
exists but had no practical effect.

---

## `POST /universe/{list_name}/{symbol}`

Add a symbol to a universe list. A thin wrapper over `POST /commands`
(`kind: "universe_add"`): validates, then enqueues the intent and returns the same
`CommandStatus` shape — the actual mutation happens later, in the drain, so poll the
returned `id` (or `GET /commands/{id}`) to see it move to `applied`.

**Auth:** owner only (unlike `POST /watchlist/{symbol}`, which allows any authenticated
role — a universe edit moves CSP eligibility, so it follows every other P2 write route's
owner gate instead of the P1 watchlist precedent).

`list_name` is a path parameter typed `Literal["would_own", "watchlist"]` — FastAPI/
Pydantic rejects any other value with `422` **before an `app_commands` row can exist**,
so `sectors`, `leveraged_etfs`, `strike_bands`, and `actively_wheeling` can never be
edited from the web, with zero side effects on a rejected request.

| Status | When |
|---|---|
| 201 | command enqueued — always, even on a repeat request. `universe_add`/`universe_remove` carry no `dedupe_key` (M7 final-review fix): `set_override` is an idempotent upsert, so a stable key could match an already-`applied` command from an earlier, semantically different request and silently no-op instead of re-applying. |
| 404 | `symbol` is not a known SEC filer (checked against the research symbol directory) |
| 422 | `list_name` is not `would_own`/`watchlist` |

**Response (201):** `CommandStatus` (see `docs/web/commands.md`), `kind: "universe_add"`.

See `docs/web/commands.md`'s `universe_add` section for what the drain does with the
enqueued intent.

---

## `DELETE /universe/{list_name}/{symbol}`

Remove a symbol from a universe list. A thin wrapper over `POST /commands`
(`kind: "universe_remove"`) — same enqueue-and-poll shape as the `POST` route above, not
a synchronous mutation.

**Auth:** owner only (same reasoning as `POST` above).

Same `422`/`404` as `POST` above, plus one more check specific to removal: removing a
symbol that is in `actively_wheeling` **from `would_own`** is `409` with
`{"reason": "actively_wheeling", "symbol": ...}` — you cannot stop being willing to own
something you are actively wheeling. This guard is scoped to `would_own` only, mirroring
`effective_universe()`'s own remove-guard: removing the same symbol from `watchlist` is
harmless and is **not** blocked.

| Status | When |
|---|---|
| 201 | command enqueued — always, even on a repeat request (no `dedupe_key`, same reasoning as `POST` above) |
| 404 | `symbol` is not a known SEC filer |
| 409 | `list_name == "would_own"` and `symbol` is in `actively_wheeling` |
| 422 | `list_name` is not `would_own`/`watchlist` |

**Response (201):** `CommandStatus`, `kind: "universe_remove"`.

---

## `GET /research/{symbol}/summary`

The AI summary (M7). **Enrichment only — influences nothing.** The summary records
narrative over numbers the deterministic layer already computed; it never calculates a
figure, and the fence tests in `tests/test_web_fence.py` keep it that way.

**GET makes no model call.** A first-time search on an obscure ticker must not silently
trigger a model call (design §7). When nothing is cached, the response is `unavailable`
with a reason; the client renders a **Generate summary** action rather than a spinner.
A cached summary past `research.summary.cache_ttl_hours` is returned as `stale` so the
client can prompt a regeneration.

**Auth:** required. **404** when `symbol` is not a known SEC filer.

**Response — `SummaryResponse`:**

| Field | Type | Notes |
|---|---|---|
| `as_of` | datetime | request time |
| `symbol` | string | uppercased |
| `state` | `"ready" \| "stale" \| "unavailable" \| "pending"` | `unavailable` = no cache, no model call; `pending` = generation attempted but failed soft |
| `summary` | `SummaryOut \| null` | present when `state` is `ready` or `stale` |
| `reason` | string \| null | explains `unavailable` / `pending` |

`SummaryOut`: `{ thesis, bull_points[], bear_points[], watch_items[], caveats[], model, data_as_of }`.
`caveats` always carries the quantitative limit (cannot account for one-time charges,
M&A, spinoffs, restatements). `model` and `data_as_of` make a stale summary visibly stale.

---

## `POST /research/{symbol}/summary`

Generate and cache a summary on demand. Fail-soft: a failed generation returns `pending`
with a reason (not an error), so the rest of the page is untouched. The cache key is
`(symbol, model, prompt_hash, data_as_of)`; a changed `data_as_of` misses.

**Auth:** required. **404** when `symbol` is not a known SEC filer.

**Response (200):** `SummaryResponse` (same shape as GET), with `state` = `ready` on
success or `pending` on fail-soft.

---

## Commands

The first write routes in the web layer. See `docs/web/commands.md` for the full
runbook (every kind, its payload, dedupe key, what applies it, and failure modes).

### `POST /commands`

Enqueue an intent. **Owner-only** (403 for viewers, 401 for missing token).

**Body:** `{ kind: CommandKind, payload: object }`

**Response:**
- `201` — a new command was enqueued. Body: `CommandResponse` (`{id, kind, status, ..., created: true}`).
- `200` — a duplicate `dedupe_key` returned the existing command. Body: `CommandResponse` with `created: false` and the existing `id`.
- `422` — the payload does not validate against the schema for `kind`.
- `409` — (future) the intent is refused on its merits.

In **live mode**, `approve`, `promote`, and `roll_request` are created with a
`confirm_token` and `needs_confirmation: true`. The drain skips them until
`POST /commands/{id}/confirm` supplies the token. In paper mode, no token is issued.

### `GET /commands/{id}`

Read one command's status through the **read-only** engine. **Owner-only.**

**Response:** `CommandStatus` (`{id, kind, status, result, needs_confirmation, confirm_token, created_at, applied_at, as_of}`).
`confirm_token` is present only while a live-mode token is outstanding (the owner
supplies it back through the confirm route; it is cleared on confirm and absent in
paper mode). **404** for an unknown id.

### `POST /commands/{id}/confirm`

Supply the `confirm_token` for a live-mode order-reaching intent. **Owner-only.**

**Body:** `{ confirm_token: string }`

**Response:**
- `204` — the token matched and was cleared; the next drain cycle applies the command.
- `403` — the token is wrong or missing. **The token is NOT cleared**; the command
  stays `pending` awaiting confirmation (fail closed).
- `409` — the command is not awaiting confirmation (paper mode, already confirmed,
  or not an order-reaching kind).
- `404` — unknown command id.

---

## Options console (P2)

The options console read surfaces. Every route is **owner-only** (403 for viewers,
401 for missing token) and reads through the `mode=ro` trading engine. No route
reaches IBKR; every number is as fresh as the last write by a trading process and
says so via the top-level `as_of`.

### `GET /options/approvals`

Pending and recently decided approvals. Each carries the frozen `snapshot` (the
exact payload the human was shown), joined to the `CandidateRow`, `RiskVerdictRow`
and `ClaudeReviewRow` when present. A pruned candidate renders from `snapshot`
alone — the joined rows are enrichment whose absence never 500s.

**Query params:** `status=pending` (default), `approved`, `rejected`, `expired`, or `all`; `symbol` (filters to one underlying, case-insensitive, matched via the joined `CandidateRow` — an approval whose candidate has since been pruned by the 14-day purge will not match even if its own `snapshot` still carries the symbol); `since`/`until` (UTC calendar dates, inclusive, filtered against `created_at`); `limit` (1-200, default 50). An unknown `status` returns **422**, not a silent empty list. `status=all` is ordered newest-first by `created_at` (a pending row is not promoted above a newer decided one).

**Response — `ApprovalListResponse`:**

| Field | Type |
|---|---|
| `as_of` | datetime |
| `approvals` | `ApprovalSummary[]` |

`ApprovalSummary`: `{ as_of, id, candidate_id, status, underlying, strategy, right, strike, expiry, contracts, premium, blended_score, created_at, expires_at, decided_at, order_state, source, review, rationale_tags, decided_by, roll_from, fill_price }`.
`rationale_tags` is the frozen snapshot's tag list (`[]` when absent). The one the console
renders specially is `iv_rank_unavailable` (scan-loop Task 9): the name had no IV history, so
its IV score is the neutral `missing_iv_rank_score` placeholder, shown with the hatch/unknown
styling rather than as real data. Display only.
`premium` is per share, always. `order_state` is `null` when no order exists.
`source` is `"scan"` or `"roll"`: `"roll"` whenever the frozen snapshot's strategy is `roll`
(so a roll whose candidate the 14-day purge has pruned still reads as a roll, never a scan),
else derived from the candidate's `run_id` prefix.
`decided_by` (web overhaul Part 2, 2026-10-19) is who decided the approval: `"system"` (the
entry auto-queue on the WHITELIST or FULL rung, and the roll pipeline's auto-approve on FULL),
`"web"` (the command drain's approve or reject) or `"telegram"` (a button tap), or `null`.
`null` means not recorded and is never inferred: an approval decided before the column
existed, or before the trading service was restarted onto it, an expiry, and a pending
approval all read `null`. It is a record for the console only; nothing in `src/engine/`,
`src/strategies/` or `src/execution/` reads it. The column is added by `init_db`, which the
trading service, the monitor and the scripts run and the API process never does: an API started
onto this code before one of them has migrated `data/income_system.db` answers 500 on the
approvals reads and on `/pnl/day` until the column exists, so restart the trading service first
(or run `python -m scripts.healthcheck`), then the API.
`roll_from` is a roll's buy-back leg from the frozen snapshot: `{ strike, expiry, right,
contracts, old_mid, new_mid }`, the mids per share at which the roll was priced when it was
proposed (a quote, never a fill; either may be `null`). `null` for an entry and for a roll
frozen before the 2026-10-11 redesign.
`fill_price` is the order's average fill per share, `null` until it fills (or when no order
exists). For a **roll** (the snapshot's strategy is `roll`, the rule `source` uses) it is the
roll's **net per share in `premium`'s convention**: a credit is positive and a debit negative.
IBKR's combo average, which `OrderRow.avg_fill_price` stores, has the opposite sign (a credit is
negative), so the API flips it; a single-leg order keeps its own price.
`created_at` is the approval's actual raise time (`ApprovalRow.created_at`) — never
confuse it with the envelope's `as_of`, which is `datetime.now(UTC)` at response-build
time and therefore always "now" no matter how old the approval is. The web renders
`created_at` as an exact date/time, not a relative age, for exactly this reason.
`review` is the newest `ClaudeReviewRow` for the candidate (same shape as the detail
route's, below) or `null` — carried on the **list** route, not just the detail one, so
the card can show a why/risks preview without a click-through for every candidate;
batch-fetched (one query for the whole page, not one per row).

### `GET /options/approvals/{id}`

One approval in full, including the ideal zone, the gate reasons (humanised), the
five Claude review fields (separately, never one blob), the alternative strikes
assessed on the same run, and the approval-to-fill lineage.

**Response — `ApprovalDetail`:** `ApprovalSummary` plus `{ snapshot, ideal, gate_reasons, alternatives, order_id, fills }`.
`ideal` is `{ lo, hi, min_credit }` from `RiskVerdictRow`. `review` (inherited from
`ApprovalSummary`) is the five fields `{ why_attractive, risks, tradeoffs, assignment_considerations, rolling_considerations }`
plus `{ recommendation, priority, confidence, summary, evidence }`, or `null`. `summary` (scan-loop Task 10)
is the 2-3 sentence plain-English verdict and `evidence` the `F#` (computed fact) / `N#` (news headline)
ids it cited; both are empty on reviews stored before Task 10. The FACTS/NEWS text those ids point
into lived only in that scan's prompt, so the console labels each id by kind rather than linking it.
`order_id` is the id of the order this approval produced, `null` when none exists yet.
`fills` is every fill against that order (oldest first), `FillSummary[]` — carried here
so tracing one candidate to its fill price needs no second/third request to
`GET /options/orders` and `GET /options/fills`.
**404** for an unknown id.

### `GET /options/assessed`

Every contract the scan priced, grouped by symbol, with its `AssessmentStage`,
reason codes (raw and humanised), score, premium, denormalised ideal zone, and a
`promotable` / `promote_note` pair. The promotable table (spec §5.2):
`generator` and `risk_gate` are never promotable; `score_floor` is promotable with
a note carrying the configured `min_candidate_score`; `dedupe` and `top_n` are
promotable with a null note; `passed` is not promotable (already surfaced).

**Query params:** `run=latest` (default) | a specific run_id; `symbol`; `stage` (one of `generator`, `risk_gate`, `score_floor`, `dedupe`, `top_n`, `passed` — unknown returns **422**); `limit` (1-1000, default 200). `run=latest` resolves to the newest non-`scan-`-prefixed `run_id`, matching `latest_buy_candidates`'s single-ticker filter. `limit` caps the **total** number of contracts returned across all groups (not a per-symbol cap); `counts` in each group header still reflects the full per-stage tally for that symbol, not the truncated subset. Within each group and across groups, contracts are ranked the same way `scan.py::_rank_assessed` ranks them: `passed` first, then rejects by stage progression (got further ranks higher), then blended score descending.

**Response — `AssessedResponse`:** `{ as_of, run_id, computed_at, groups: AssessedGroup[] }`.
`AssessedGroup`: `{ as_of, symbol, contracts: AssessedContract[], counts: Record<string, int> }`.

### `GET /options/assessed/runs`

Past full-scan run ids, newest first, for browsing history in the Assessed tab
(`run=latest`/a specific `run_id` above always required already knowing that id —
this lists what to pick from). Excludes single-ticker runs the same way
`run=latest` does (`scan-`/`ticker-` prefixes are not "a run" in this sense).

**Query params:** `limit` (1-100, default 20).

**Response — `AssessedRunsResponse`:** `{ as_of, runs: AssessedRunSummary[] }`.
`AssessedRunSummary`: `{ as_of, run_id, computed_at, candidate_count }`.

### `GET /options/orders`

Working orders by default. `state=working` means `queued`, `submitted` or
`partial`; `state=all` returns everything. `underlying`/`strategy`/`strike` come
from the order's `snapshot`, falling back to the joined `CandidateRow` so a pruned
candidate does not blank the row. `avg_fill_price` is `null` for an unfilled
order, never `0.0`. `detail` carries the humanised reason for a `rejected`/`cancelled`
order (e.g. a live-mode order-send-time re-gate rejection) — never a raw Python list
repr of the gate codes.

**Query params:** `state=working` (default), `all`, or a specific state (`queued`, `submitted`, `filled`, `partial`, `cancelled`, `rejected` — unknown returns **422**); `limit` (1-200, default 50).

**Response — `OrderListResponse`:** `{ as_of, orders: OrderSummary[] }`.

### `GET /options/fills`

Recent fills within the last `days` days.

**Query params:** `days` (1-90, default 7); `limit` (1-500, default 100).

**Response — `FillListResponse`:** `{ as_of, fills: FillSummary[] }`.

### `GET /options/shorts`

Open short option positions from the most recent `position_snapshots` row. `as_of`
is the snapshot's capture time, **not** request time. Long options and stock are
excluded. `delta` carries its source through `Sourced` (IBKR vs computed/BS). A
position with no snapshot data returns `null` for `mark`, `unrealized_pnl`,
`expiry` and `dte`, never `0.0` or a fabricated `date.today()`. `assignment_risk`
is `false` when `expiry` or `delta` is unknown — a missing field must not fabricate
the signal. `assignment_risk` is computed from the monitor's configured thresholds
(`monitor.assignment_alert_delta` / `assignment_alert_dte`, currently 0.70 delta / 21
DTE, from `config/settings.yaml`) via `src/common/assignment_risk.py`, not a fixed
value baked into the endpoint. `pnl_pct` is `unrealized_pnl / (|avg_cost| * contracts)`,
i.e. total P&L over the position's total cost (not per-share cost). `alerts` is empty,
not `null`, when nothing has fired.

**Response — `ShortListResponse`:** `{ as_of, shorts: ShortPosition[] }`.
`ShortPosition`: `{ as_of, position_symbol, underlying, right, strike, expiry: date | null, dte: int | null, contracts, avg_cost, mark, unrealized_pnl, pnl_pct, delta: Sourced<float> | null, assignment_risk, alerts: RollAlertSummary[] }`.

### `GET /options/controls`

The autonomy rung, halt state, mode, and command-drain health.

**Response — `ControlsResponse`:** `{ as_of, autonomy: { level, label }, rungs: { level, label }[], halted, halt_reason, halted_at, mode, drain_healthy, drain_last_seen, pending_commands }`.

`halted_at` (M6) is when the current halt was engaged: the most recent applied
`halt` command's `applied_at`, derived from the command queue (no separate
settings key). A halt tripped by a circuit breaker has no command row, so
`halted_at` is `null` there — the console's banner then says "at an unknown time"
rather than fabricating one. Only meaningful while `halted` is true.

`drain_healthy` reads the `command_drain_heartbeat` system_settings key (written
by the command drain after every cycle) and compares it against twice
`execution.poll_interval_seconds`. A drain that has never run is `false` with
`drain_last_seen: null` — it must never default to `true`. **Do not reuse
`/health`'s `worker_heartbeat`**: that reports the research worker and would show
green while the command drain is dead.

---

## Portfolio (P3 Milestone 2)

Four owner-only read routes that answer "what do I hold, what is it worth, what
is at risk, and what happens next". All four serve from the snapshot spine M1
built — `read_portfolio` (`src/api/portfolio_source.py`) resolves the freshest
portfolio state through its three-rung chain (newest `portfolio_snapshots` row →
`position_snapshots` + the journal's account block → an explicit empty reading)
and these routes render what it found, adding nothing to it. None reaches IBKR.

Shared conventions, set by `GET /portfolio/summary`:

- **`source` / `degraded` / `note`** ride on every snapshot-derived response:
  `source` is which rung served (`"monitor"`, `"refresh"`, `"eod"`, `"none"`),
  `degraded` is true on the `eod` and `none` rungs, and `note` states the
  degradation in plain words. A missing `note` means the data is fresh.
- **`as_of` is the reading's capture time**, not request time. On the `none`
  rung (nothing captured yet) request time is used with `degraded: true` — the
  envelope needs a valid stamp, but nothing in the body claims to be a
  measurement.
- **Sourced values use `Source.IBKR`** — that is where the numbers came from,
  even though a database served them; `as_of` and `stale` carry the age.
  `fresh_for` is twice `market_data.portfolio_snapshot_interval_minutes`
  (default 15 → stale after 30 minutes), so a portfolio that has missed one
  capture reads stale.
- **The `none` rung is a `200`, never a `404` and never zeros.** "Nothing
  captured yet" is not an error, and zeros would be a claim about the account.
- **`assignment_risk` comes from `src/common/assignment_risk.py`** with the
  monitor's configured thresholds (`monitor.assignment_alert_delta` /
  `assignment_alert_dte`, 0.70 / 21) — the same single definition
  `GET /options/shorts` and the Telegram alerts use. No route defines a
  threshold of its own.

### `GET /portfolio/summary`

The account block — net liquidation, total cash, buying power, maintenance
margin, excess liquidity — each as a `Sourced` value so a stale figure is
visibly stale rather than merely old. Beside it, the exposure the operator
needs before deciding anything.

Degradation behaviour: a fresh snapshot yields `source="monitor"`,
`degraded=false`, no `note`. The `eod` rung yields `source="eod"`,
`degraded=true` and a `note` saying so. Nothing captured yields `200` with
`source="none"`, `account: null`, `exposure: null` and the note
"No portfolio snapshot has been captured yet." — never zeros.

Exposure semantics:

- `open_positions` counts every position in the reading (stock and options).
- `open_shorts` counts short option positions only.
- `open_campaigns` counts open rows in `campaigns`.
- `net_delta_exposure` is `Σ delta × position × 100` over options plus the
  share count over stock — the same formula the EOD summary computes.
- `cash_secured_against_puts` counts **short puts only**, at
  `strike × contracts × 100`. Long options and stock are not cash-secured
  obligations.
- `buying_power_utilisation_pct` is `null` when buying power is zero or
  unknown — never `0.0`, which would read as "nothing committed".
- `shorts_at_assignment_risk` counts positions passing the shared predicate
  (`is_assignment_risk`).

**Response — `PortfolioSummaryResponse`:**
`{ as_of, source, degraded, account: AccountBlock | null, exposure: ExposureBlock | null, note: string | null }`.
`AccountBlock`: `{ as_of, net_liquidation: Sourced<float>, total_cash: Sourced<float>, buying_power: Sourced<float>, maintenance_margin: Sourced<float>, excess_liquidity: Sourced<float> }`.
`ExposureBlock`: `{ as_of, open_positions, open_shorts, open_campaigns, net_delta_exposure, cash_secured_against_puts, buying_power_utilisation_pct: float | null, shorts_at_assignment_risk }`.

### `GET /portfolio/positions`

Every position, **grouped by underlying** — the stock leg beside its option
legs, because that is the unit the operator thinks in. An option whose
`underlying` is `null` groups under its own symbol rather than being dropped.

Adjusted-basis semantics — **both cost bases are reported, never one
substituted for the other**: `avg_cost` is what IBKR says;
`adjusted_cost_basis` is what the collected premium makes it: IBKR's
`avg_cost` less the premium of legs before each assignment, over every open
assigned campaign on the symbol, spread across all shares held (when any of
the shares came from an assignment).
`unrealized_pnl` is against the former, `unrealized_pnl_adjusted` against the
latter. `adjusted_cost_basis` is `null` for shares that did not come from an
assignment, and `unrealized_pnl_adjusted` is `null` with it — not a copy of
`unrealized_pnl`, and not zero. The basis is read through the API's own
read-only engine through the same pure
`storage.campaigns.whole_position_basis` the covered-call gate uses (since
2026-10-13; before, the newest open assigned campaign's basis), never through
the storage engine's read-write session.

`moneyness` (`itm`/`atm`/`otm`) needs the underlying's price: the group's own
stock leg first, else the latest settled close in `price_history` — both from
the reading and the read-only engine, never a second live path. `moneyness` is
`null` when no price is known; there is no guessing from the strike alone.
`dte` is `null` when expiry is unknown, never `0` (which would read as
"expires today").

Degradation behaviour: the `none` rung returns `groups: []` with
`source="none"` — an empty list plus `source="monitor"` would be a claim that
the account holds nothing.

**Response — `PositionsResponse`:**
`{ as_of, source, degraded, groups: PositionGroup[] }`.
`PositionGroup`: `{ as_of, underlying, stock: StockLeg | null, options: OptionLeg[] }`.
`StockLeg`: `{ as_of, shares, avg_cost, adjusted_cost_basis: float | null, market_price: float | null, market_value: float | null, unrealized_pnl: float | null, unrealized_pnl_adjusted: float | null }`.
`OptionLeg`: `{ as_of, symbol, right: "C"|"P"|null, strike: float | null, expiry: date | null, dte: int | null, contracts, short, delta: float | null, delta_source: string | null, market_price: float | null, market_value: float | null, unrealized_pnl: float | null, moneyness: "itm"|"atm"|"otm"|null, assignment_risk }`. `right`/`strike` are `null` when the snapshot carried none — never a fabricated `"C"`/`0.0` pair, and `moneyness` is `null` with them (all three of spot/right/strike are needed; no guessing against a fabricated strike).

### `GET /portfolio/campaigns`

The wheel threads — what Telegram's `/campaigns` renders as text and renders
badly. Query parameters: `status` (`open` | `closed`; omit for both), `symbol`,
and `limit` (default 50, maximum 200 — campaigns are never pruned, so the read
is capped rather than materialising every row ever written). Ordered by
`opened_date` descending, open campaigns before closed
ones at the same date. `as_of` is **request time** here, not a snapshot time:
campaigns are written on fill, not captured, so there is no capture time to
read.

**`total_premium_collected` / `total_debit_paid` / `net_premium` are gross of
commissions** (pinned by `tests/test_campaign_rollup_semantics.py` and M0 Task
0.4): `_rollup` (`src/storage/campaigns.py`) sums `avg_price × filled_qty × 100`
per fill and never reads `FillRow.commission` — it is deliberately not
subtracted. `src/reporting/` reports the same trades net of commissions, so a
campaign's `net_premium` and the net P&L of its legs differ by exactly the
commission total; readers comparing the two must account for that gap.

A leg whose `CandidateRow` has been pruned (candidates are pruned; campaigns
are not) still renders with `known: false` and null contract fields — the
campaign's financials are rolled up from `FillRow` and survive pruning, so the
leg count must not silently disagree with them.

**Response — `CampaignsResponse`:** `{ as_of, campaigns: CampaignSummary[] }`.
`CampaignSummary`: `{ as_of, campaign_id, symbol, status, opened_date, closed_date: date | null, legs: CampaignLeg[], total_premium_collected, total_debit_paid, net_premium, assigned, adjusted_cost_basis: float | null, realized_stock_pnl: float | null }`.
`CampaignLeg`: `{ as_of, candidate_id, strategy, right: "C"|"P"|null, strike: float | null, expiry: date | null, known }`.

### `GET /portfolio/calendar`

Option expiries grouped by date over a horizon — "what happens next". Query
parameter `horizon_days` (default 45, maximum 365). Days are ordered nearest
first; an expiry outside the horizon is excluded; an already-expired position
is not "what happens next" and is skipped. Both `dte` and the horizon gate are
measured on the **exchange calendar (ET)** — the same single clock, so the dte
a rendered entry carries always agrees with the gate that let it in.

The `consequence` column — what expiry would mean if nothing changes:

| Position | Moneyness | `consequence` |
|---|---|---|
| Short put | `itm` | `assigned` |
| Short call, stock held | `itm` | `called_away` |
| Short call, no stock held | `itm` | `assigned` — a naked short call assignment is a short stock position, not a call-away |
| Any short | `otm` or `atm` | `expires_worthless` |
| Any | unknown | `unknown` |
| Long option | `otm` | `expires_worthless`; else `unknown` |

**`unknown` is a real value and renders as such** — "we do not know what
happens on Friday" is materially different from "nothing happens on Friday",
so it is never defaulted to `expires_worthless`.

Degradation behaviour: the `none` rung returns `days: []` with
`source="none"`.

**Response — `CalendarResponse`:**
`{ as_of, source, degraded, horizon_days, days: CalendarDay[] }`.
`CalendarDay`: `{ as_of, expiry, dte, entries: CalendarEntry[] }`.
`CalendarEntry`: `{ as_of, symbol, underlying, right, strike, contracts, short, moneyness: "itm"|"atm"|"otm"|null, consequence: "assigned"|"called_away"|"expires_worthless"|"unknown", assignment_risk }`.

### `GET /portfolio/value` (web overhaul Part 1)

Account value (net liquidation) over a range, for the Home hero's number and scrubbable chart.
A thin render over `src/reporting/account_value.py::account_value_series`: the route computes
nothing itself. Owner-only; reads through the `mode=ro` trading engine; never reaches IBKR.

| Param | Type | Notes |
|---|---|---|
| `range` | `1d` \| `1w` \| `1m` \| `3m` \| `ytd` \| `all` | default `1m` |

Two sources, one shape: `1d`/`1w` plot the intraday `portfolio_snapshots` rows (every ~15
minutes, 30-day retention) inside the window; `1m`/`3m`/`ytd`/`all` plot one point per EOD
journal close, at that day's 16:00 New York time. The rules:

- **Unknown is `null`, never `0`.** A net liquidation of `0` or less (IBKR's account summary
  can come back without its NetLiquidation tag, and `0.0` is what gets stored then) is
  unknown: it is never a point, never `latest`, never `previous_close` and never a month-start
  value. With no known value at all, `latest` is `null` and `points` is `[]`.
- **A journal close counts only once its 16:00 ET is past.** A row for today written early is
  not yet a close: it neither plots nor competes with a live snapshot.
- **`latest` is the newer of the newest known snapshot and the newest close, compared as
  instants.** After the close the official close leads; a monitor that stopped days ago never
  does. `1m`/`3m`/`ytd`/`all` end on `latest` whenever it is newer than their last close;
  `1d`/`1w` end on it only when `latest_at` also falls inside the window (on a Monday before the
  first snapshot, `1d` has no points and does not reach back to Friday's close).
- **`previous_close` is the close before the New York day `latest` belongs to**, and
  **`change_today` / `change_today_pct` are `null` unless that day is today** (a weekend,
  or before today's first snapshot): the day's change is unknown then, never `0`.

**Response — `AccountValueResponse`:** `{ as_of, series: AccountValueSeries }`.
`AccountValueSeries`: `{ range, points: AccountValuePoint[], latest: float | null, latest_at: datetime | null, previous_close: float | null, change_today: float | null, change_today_pct: float | null }`.
`AccountValuePoint`: `{ at, value }`, in ascending time order but not strictly: two snapshot rows
captured at the same `captured_at` both appear, so the web client folds points that share a second
into one (the later row wins) before charting.

---

### `GET /portfolio/positions/{underlying}/{slug}` (web Home follow-ups, 2026-10-15)

One position's page, behind a Positions row on Home: where it stands now and the trade that
opened it. Owner-only; read-only; never reaches IBKR. The live figures come from the same snapshot
reading `GET /portfolio/positions` renders (`_option_legs`, `_stock_leg`), so the two never
disagree; the initial trade comes from the system's own fills through the builders `GET /pnl/day`
uses (`src/reporting/day.py::build_position_story`), so the figures on Home's "Done today" and on
this page are one computation.

| Slug | Meaning |
|---|---|
| `2026-11-21_P180` | an option contract: expiry, right (`C` or `P`), strike |
| `shares` | the shares held in the underlying |
| `spread-<id>` | one credit spread of the book (read through `data/spreads.db`) |

- `kind` follows the slug. `held` is whether the latest snapshot still has it (a spread: whether it
  is not closed). A contract that is no longer held but was traded by the system still answers,
  with `closed` saying how it ended; one that is held but was never traded by the system answers
  with `opened: null`.
- `opened` is the initial trade (premium, commission, capital held, return, a year, days to expiry
  at the sale, Claude's stored review, the approval id) and `closed` how it ended (a buy-back with
  its reason, an expiry, an assignment, a roll). Both are `DayTrade` (see `GET /pnl/day`).
- `shares` adds `campaign`, the open wheel thread (the assigned one if there are several): its
  adjusted cost basis, premium collected and net premium.
- `404` when neither the snapshot nor the fills know the position, or the slug is malformed; `503`
  for a `spread-` slug when the spreads book could not be read (not the same as "no such spread").

**Response - `PositionDetailResponse`:** `{ as_of, underlying, slug, kind, held, source, degraded, option: OptionLeg | null, stock: StockLeg | null, campaign: CampaignSummary | null, spread: SpreadPositionOut | null, opened: DayTrade | null, closed: DayTrade | null, spreads_available }`.

## P&L (P4 Milestone 5)

The P&L read surfaces. Every route is a thin renderer over `src/reporting/pnl.py` (M4):
`build_legs` → `build_campaigns` / `build_summary` / `equity_curve`. **No route computes a
P&L figure of its own** — the ledger's rows, the summary's totals, and the curve's
cumulative line all read one accounting rule, so they can never disagree. All routes are
**owner-only** (403 for viewers, 401 for missing token) and read through the `mode=ro`
trading engine. None reaches IBKR.

Shared conventions, set by `GET /pnl/ledger`:

- **`as_of` is request time** on every P&L route, because the ledger is computed on read.
  **`marks_as_of` is a different field**: the capture time of the portfolio snapshot
  backing every unrealised figure, coerced through `as_utc_opt` like every other stored
  timestamp. Two fields, both present, deliberately different — do not merge them to match
  the portfolio routes (which read the capture time alone and carry no computed figures).
- **Marks come from `read_portfolio`, never a second query.** `marks_as_of` is that
  reading's `as_of`, so the ledger's unrealised figures and the portfolio page's agree by
  construction. When no snapshot exists (`source="none"`), the route passes `snapshot=None`
  into `build_campaigns` and returns `marks_as_of: null` with every unrealised field
  `null` — an unmarked position is not worth zero.
- **`book` defaults to `"all"` on the ledger and CSV; the summary refuses a mixed total.**
  A `book=all` summary with both paper and live fills present returns **`422`** with
  `{"detail": {"reason": "mixed_book", ...}}` — never a mixed total and never a 500. The
  ledger and the CSV may list both books; only the headline total is refused (a CSV has
  no headline total, and each row carries a `book` column so paper rows are identifiable
  after export).
- **Filters are echoed back verbatim** on every response (`filters`), so a client that sent
  `since` and got a full history can see its own bug.
- **`n_legs` is the sum of every campaign's leg count.** M4 Task 4.4 guarantees every leg
  lands in exactly one thread (campaign-less legs land in a synthetic per-symbol thread);
  this field is where the client checks that guarantee at the boundary it actually reads.

Shared query parameters (all optional, all echoed back):

| Param | Type | Notes |
|---|---|---|
| `symbol` | string | upper-cased; matched against the leg's underlying |
| `strategy` | string | `covered_call` \| `cash_secured_put` \| `roll` |
| `outcome` | string | one of the `VerdictOutcome` values (`still_open`, `expired_worthless`, `assigned`, `closed_early`, ...) |
| `since` | date | legs opened on or after it (UTC calendar day) |
| `until` | date | legs opened on or before it |
| `book` | `paper` \| `live` \| `all` | default `all`; see the mixed-book rule above |

### `GET /pnl/ledger`

Leg rows grouped under their campaign threads — the "Excel-shaped ledger of every
position opened and closed", readable in a browser. The grouping is what stops an
assignment reading as a leg that ended for no reason.

**Response — `LedgerResponse`:** `{ as_of, filters, campaigns: CampaignPnl[], marks_as_of, n_legs }`.
`CampaignPnl`: `{ campaign_id, symbol, status, opened_date, closed_date, legs: PnlLeg[], option_realized, option_unrealized, stock_realized, stock_unrealized, assigned, adjusted_cost_basis, total_net }`.
`PnlLeg`: `{ candidate_id, campaign_id, symbol, underlying, strategy, right, strike, expiry, contracts, opened_at, closed_at, credit, debit, commissions, commissions_complete, open_commissions?, net_pnl, unrealized_pnl, days_held, roc_pct, annualized_pct, outcome, is_live }`.
`open_commissions` (web overhaul Part 1, additive and optional) is the part of `commissions`
paid on the leg's SELL fills, so `GET /pnl/month` can charge each side in the month it was
paid; `null` when no split is known. Every other `PnlLeg` field, and the reconciler's
`fill_economics` / `classify_outcome`, are unchanged by it.

`net_pnl` is `null` while a leg is open — never `0.0`. An open leg has a mark, not a
result. `unrealized_pnl` is filled from the snapshot only for open legs; a closed leg's
stays `null` forever. `commissions_complete: false` marks a figure gross of commissions.
A campaign-less leg lands in a synthetic thread with `campaign_id: "synthetic:SYMBOL"`.

### `GET /pnl/summary`

The totals and breakdowns — realised total, unrealised total, open/closed counts, win
rate, by-strategy and by-symbol buckets, best and worst closed legs — computed from the
same `PnlLeg` list the ledger renders, so a total can never disagree with the rows above
it.

**Response — `SummaryResponse`:** `{ as_of, filters, summary: PnlSummary, marks_as_of }`.
`PnlSummary`: `{ realized_total, unrealized_total, commissions_complete, n_open, n_closed, win_rate, by_strategy: PnlBucket[], by_symbol: PnlBucket[], best, worst }`.
`PnlBucket`: `{ label, n_closed, realized, win_rate, mean_days_held, mean_roc_pct }`.

`win_rate` is `null` when nothing is closed — never `0.0`. `commissions_complete` is the
AND of every leg's flag. A single-book summary over an empty list is a valid empty
summary (a 200), not an error. `book=all` with both kinds of fill present is the **`422`
`mixed_book`** refusal described above.

### `GET /pnl/equity`

The equity curve — one point per journal day, plus the trading days between them that
have no point (`gaps`), so the chart can render a gap rather than a fabricated straight
line. `book=all` is fine **here**, deliberately unlike `/pnl/summary`: the curve's
`cumulative_realized` sums `net_pnl` per point, and mixing books in a *curve* is a display
choice the client makes, not a headline total. Do not "fix" one to match the other.

**Response — `EquityResponse`:** `{ as_of, filters, curve: EquityCurve }`.
`EquityCurve`: `{ points: EquityPoint[], gaps: date[], starts_at: date | null }`.
`EquityPoint`: `{ entry_date, net_liquidation, unrealized_pnl, cumulative_realized, premium_cashflow }`.

`premium_cashflow` is the journal day's premium cash movement (`journal.realized_pnl`) —
**not paired realised P&L**, and named so it cannot be confused with
`cumulative_realized`, which sums only legs closed on or before each point. The two will
disagree, by design. `starts_at` is the first point's date (`null` with no points), and
`gaps` lists missed **trading days** only — weekends and holidays are not gaps.

### `GET /pnl/ledger.csv`

The same rows `/pnl/ledger` returns, under the same filters, as CSV — built from the same
`build_legs` call, so the two cannot drift. There is no mixed-book refusal here (no
headline total; the `book` column identifies each row after export).

**Response:** `text/csv; charset=utf-8` with
`Content-Disposition: attachment; filename="pnl-ledger-YYYY-MM-DD.csv"`.

Column contract: the header row names the units — `credit_usd`, `debit_usd`,
`commissions_usd`, `net_pnl_usd`, `unrealized_usd`, `roc_pct`, `annualized_pct`,
`days_held` — beside `candidate_id`, `campaign_id`, `underlying`, `symbol`, `strategy`,
`right`, `strike`, `expiry`, `book` (`paper` \| `live`), `opened_at`, `closed_at`,
`contracts`, `outcome`. **`None` serialises as an empty cell, never `0`**: a spreadsheet
zero where the value was unknown is the same lie as `$0.00` on the page, and harder to
spot. The web proxy (`web/app/api/[...path]/route.ts`) forwards exactly two response
headers, `Content-Type` and `Content-Disposition`, per its explicit allowlist — a CSV
download keeps its dated filename, and nothing about the upstream server leaks.

### `GET /pnl/system` (P4 Milestone 6)

The score-vs-outcome evidence's human reader — the one P&L route that reads behind the
`src/claude/eval/` fence, and the reason is written down here because `CLAUDE.md` requires
it: everything `eval/` produces "is read by a human, never auto-applied," and a browser page
is exactly that human reader, a better one than `scripts/evaluate_scores.py`. Nothing here
closes the loop — the route is a `GET`, the API's only writable table is `app_commands`, and
no command kind touches a scoring weight (`tests/test_web_fence.py`, Task 6.3).

The route calls `score_outcome_report(since=since, until=until)` and returns exactly what it
gets — no bucket recomputed, no correlation re-derived, no note filtered or truncated. Its
own `notes` carry, verbatim, "Read-only: re-derive `scoring_weights.yaml` from this evidence
by hand (the fence forbids any automatic feedback into the engine)" — the most important
sentence on the page, and not the UI's to paraphrase.

**Response — `SystemPerformanceResponse`:** `{ as_of, report: ScoreOutcomeReport, agreement: VerdictAgreement, since, until }`.
`ScoreOutcomeReport`: `{ n_closed, period_start, period_end, blended_score_buckets: ScoreBucket[], component_buckets: ScoreBucket[], signal_correlations: SignalCorrelation[], notes: string[] }`.
`ScoreBucket`: `{ label, n, win_rate, mean_pnl, total_pnl }`. `SignalCorrelation`: `{ signal, n, pearson_r, low_half_mean_pnl, high_half_mean_pnl }`.
`VerdictAgreement`: `{ n_closed, n_agreed, agreement_rate, claude_win_rate, baseline_win_rate }`.

`agreement` is computed here, beside the report, from
`src/claude/eval/ledger.py::load_records(closed_only=True)`, windowed by the same
`since`/`until` on `outcome_date` the report uses — `agreement_rate` is `null` with zero
closed rows in the window, never `0.0`, matching every other rate in this phase. With no
closed trades, the response is the report's own empty case (`n_closed: 0` plus its own
"nothing to correlate yet" note) — never a `404` or a hand-written empty message. Owner-only.

### `GET /pnl/month` (web overhaul Part 1)

One month's options income as a pay stub, for Home's collapsible "October pay" card. A thin
render over `src/reporting/pay.py::build_month_pay`, from the same `PnlLeg` list every P&L route
reads, plus the book's own spread positions from `data/spreads.db` (read through
`src/api/spreads_db.py`, never `src.spreads`). Owner-only; never reaches IBKR.

| Param | Type | Notes |
|---|---|---|
| `month` | `YYYY-MM` | default: the current New York month |
| `strategy` | `all` \| `csp` \| `cc` \| `spread` | default `all`; a roll counts under the side it rolls (put roll = `csp`) |
| `book` | `paper` \| `live` | default: the running mode (a pay figure across paper and live means nothing, as with `/pnl/summary`) |

The attribution rule, every date read in New York time:

- **Premium counts in the month the leg was SOLD** (opened); **buybacks count in the month they
  were BOUGHT** (closed). An expired or assigned leg closes on its expiry date.
- **Commissions are charged by side, once each:** the sell-side commission
  (`PnlLeg.open_commissions`) in the month the leg opened, the rest in the month it closed, so
  no commission is counted in two months. A leg with no known split (`open_commissions` null)
  would charge all of its commissions to the open month, which means a closing commission
  recorded later would land in that past month; `build_legs` always sets the split today. A
  past month's stub can still change when a commission is recorded after the month ends.
- Spreads count only positions whose `mode` equals the book (shadow and baseline are
  simulations): entry credit and entry commission in the month opened; the exit debit and exit
  commission of every closed contract in the month the spread finally closed (a partial close
  waits for the final close).
- `net = premium_collected − bought_back − commissions`.
- **`target` comes from the income target in force** (`GET /pnl/target` below): a fixed
  `target_amount`; `target_pct` of `month_start_value` (the last known journal close before the
  month's first day) for `pct_of_account`; or `target_pct` of `target_base` for `pct_of_amount`.
  `target_mode` echoes which (`off` means no target). When the inputs are unknown (a
  `pct_of_account` target with no `month_start_value`), `target` and `progress_pct` are `null`,
  never `0`. The card tells the cases apart: `off` says "No target set"; a percent-of-account
  target with no `month_start_value` (the first month after install, a journal gap) says
  "Target n/a · needs the month's opening account value".
- `commissions_complete` is `false` when any counted leg lacks a commission (the figure is a
  lower bound).
- **`spreads_available`** is `false` only when a spreads book is in scope (`strategy` `all` or
  `spread`) and `data/spreads.db` could not be read (absent, not a database, locked, or no
  `spread_positions` table): the response's spread figures are then missing, not zero, and the
  card says so instead of showing `$0` or the wheel's total as the whole month. A wheel-only
  strategy never reads the file and is always `true`.

**Response — `MonthPayResponse`:** `{ as_of, book, pay: MonthPay, spreads_available }`.
`MonthPay`: `{ month, strategy, premium_collected, bought_back, commissions, commissions_complete, net, n_opened, n_closed, month_start_value: float | null, target_pct: float | null, target_mode: "off" | "fixed" | "pct_of_account" | "pct_of_amount", target_amount: float | null, target_base: float | null, target: float | null, progress_pct: float | null, days_left }`.

### `GET /pnl/target` (web Home follow-ups, 2026-10-15)

The monthly income target in force, for the More page's control. Owner-only; read-only (it is
changed only by the `set_income_target` command, `docs/web/commands.md`).

**Response — `IncomeTargetResponse`:** `{ as_of, target: IncomeTarget, source }` where
`IncomeTarget` is `{ mode: "off" | "fixed" | "pct_of_account" | "pct_of_amount", amount, pct, base }`
(fields that do not belong to the mode are `null`) and `source` is `web` (the operator's setting,
`system_settings.income_target`, including an explicit `off`), `config` (no web row, so the legacy
`web.monthly_income_target_pct` applies as `pct_of_account`) or `none`.

### `GET /pnl/day` (web Home follow-ups, 2026-10-15)

What was opened, closed or rolled on one New York day, as the cards under Home's "Done today".
A thin render of `src/reporting/day.py::build_day_trades` over the same `PnlLeg` list every P&L
route reads, plus the book's spread rows (through `src/api/spreads_db.py`). Owner-only; never
reaches IBKR; nothing is generated: every sentence is worked out from stored fills, the close
reason stamped on the buy-back fill, the roll policy's decision log, and (for an opened trade
and a rolled position) Claude's stored view, which carries `source: "claude"`.

| Param | Type | Notes |
|---|---|---|
| `date` | `YYYY-MM-DD` | default: today in New York. Any date works (the calendar reuses it for a tapped day) |
| `strategy` | `all` \| `csp` \| `cc` \| `spread` | default `all`; a roll counts under the side it rolls |
| `book` | `paper` \| `live` | default: the running mode |

- **Opened:** a leg whose first SELL fill is on the day. The new short a roll opens is *not*
  listed here; it is part of the roll's card.
- **Closed:** a buy-back on the day (`how: "bought_back"`, reason from `CloseReason`; a close
  that predates the stamp says so), or an expiry or assignment whose date is the day
  (`how: "expired" | "assigned" | "called_away"`, `at` is 16:00 New York on that date).
  An expiry is not an execution, but the position leaves the book and would otherwise vanish.
- **Rolled:** a buy-back with `close_reason: roll`. The buy-back and the new short share one
  combo order, so they are paired on that order id (`rolled_to`); an unpaired roll still shows
  the buy-back and says the new leg is not on record. `facts` carry the logged trigger and
  decision (matched on the roll approval's id, else the newest decision for that contract), the
  roll terms per share, and Claude's stored recommendation if one was recorded.
- **Money** is USD for the whole position and positive (`premium`, `bought_back`,
  `commissions`); the card signs it. `net_pnl` is the realised result after every commission and
  is `null` until the trade closes - never `0`. `pct_kept` is the share of the premium kept
  before commissions (negative when the buy-back cost more than was collected). `capital` is the
  cash held aside (a put), the shares' strike value (a call) or the most a spread can lose.
- `spreads_available` is `false` only when a spreads book is in scope and `data/spreads.db`
  could not be read: the spreads cards are then missing, not absent.

**Response - `DayTradesResponse`:** `{ as_of, date, book, strategy, trades: DayTrade[], spreads_available }`, newest first.
`DayTrade`: `{ key, action: "opened" | "closed" | "rolled", how, kind: "csp" | "cc" | "spread" | "other", source: "wheel" | "spreads", underlying, right, strike, long_strike, expiry, contracts, at, is_live, premium, bought_back, commissions, commissions_complete, net_pnl, capital, roc_pct, annualized_pct, pct_kept, dte_at_open, days_held, reason, facts: DayFact[], approval_id, review: DayReview | null, rolled_to: DayRolledTo | null, decided_by }`.

**Who approved it (web overhaul Part 2).** `decided_by` (`"system"` | `"web"` | `"telegram"` | `null`) is on
the opened and the rolled cards only, read from the approval the card links to (`approval_id`); a
closed card, a spreads card, and any approval decided before the record existed carry `null`,
which means not recorded, never guessed.

**History's days.** `DayTradesResponse` also carries `previous_day` and `next_day`: the nearest
New York days before and after `date` with a wheel trade (opened, closed or rolled) or a wheel
proposal raised, in the requested `strategy`'s scope, or `null` at either end. Spreads are not
counted (the Spreads view navigates over `GET /spreads/picks`).

### `GET /pnl/calendar` (web Home follow-ups, 2026-10-15)

A month of daily realised P&L, for the calendar behind the chart on Home. Each day is the net
result, after every commission, of the option legs and the book's credit spreads that closed
that day (an expired or assigned leg closes on its expiry date). A day nothing closed is absent,
which is not the same as a day known to be flat. An open leg has a mark, not a result, and
contributes nothing. Share sales and trades made outside the system are not in it (they live in
the ledger). Owner-only.

| Param | Type | Notes |
|---|---|---|
| `month` | `YYYY-MM` | default: the current New York month |
| `strategy` | `all` \| `csp` \| `cc` \| `spread` | default `all` |
| `book` | `paper` \| `live` | default: the running mode |

**Response - `RealisedCalendarResponse`:** `{ as_of, book, calendar: MonthCalendar, spreads_available }`.
`MonthCalendar`: `{ month, strategy, days: { date, realized, n_closed, complete }[], total, n_closed, complete }`;
`complete` is `false` when a closed leg that day has no commission recorded (the figure is a
lower bound on the cost, an upper bound on the result).

## Spreads (web overhaul Part 1)

### `GET /spreads/positions`

The daily credit-spreads book, read-only, for Home's positions card. `src/api/` may not import
`src.spreads` (the spreads fence), so `src/api/spreads_db.py` opens `data/spreads.db` itself
with SQLite `mode=ro` and plain SQL. Owner-only; writes nothing; never reaches IBKR.

| Param | Type | Notes |
|---|---|---|
| `status` | `open` \| `closed` \| `all` | default `open`; `open` includes `expiring` (still held, settling today) |
| `mode` | `paper` \| `shadow` \| `baseline` | default `paper` |
| `limit` | int | default 50, 1 to 500; newest first by `opened_at` |

- **`available: false` with no positions** when the file does not exist yet (a fresh install)
  or cannot be read (not a SQLite database, unopenable): a `200`, never a `500`, and never an
  "empty book" claim. An old file without the `spread_positions` table reads as an empty book.
- `realized_pnl_usd` is `null` until the spread is closed, never `0`. A spread that is still open
  can already carry `exit_debit` (the qty-weighted debit of the contracts closed so far, `null`
  only until the first close) and a non-zero `exit_commission` (which starts at `0`) after a
  partial close; `contracts` below `contracts_opened` is what marks the partial close.
- `opened_at` / `closed_at` are served as UTC with an offset.

**Response — `SpreadPositionsResponse`:** `{ as_of, available, underlying, mode, positions: SpreadPositionOut[] }`.
`SpreadPositionOut`: `{ as_of, spread_id, mode, side: "put"|"call", expiry, short_strike, long_strike, width, contracts_opened, contracts, entry_credit, entry_commission, opened_at, status, exit_debit, exit_commission, exit_reason, closed_at, realized_pnl_usd }`
(`contracts` is what is still open; credits and debits are per share).

### `GET /spreads/picks` (web overhaul Part 2)

One New York day of the spreads picker for Trades, Credit spreads: each menu Claude was shown,
its choice and what the service did with it, beside every spread any book opened that day. Same
access path as `GET /spreads/positions` (`src/api/spreads_db.py`, `mode=ro`, plain SQL; the API
never imports `src.spreads`). Owner-only; writes nothing; never reaches IBKR.

| Param | Type | Notes |
|---|---|---|
| `day` | `YYYY-MM-DD` | default: today in New York. A malformed date is **422** |

- **`available`** is `false` only when `data/spreads.db` does not exist or cannot be read, or its
  `spread_positions` table cannot be read: a `200`, never a `500`, and never an empty-day claim.
  A file with no `spread_picks` table (the picker never ran) is `available: true` with no
  `picks`. An older `spread_positions` table with no `pick_id` column still lists the day's
  spreads; none of them is then tied to a pick.
- **`picks`** are the day's `spread_picks`, newest first. A stored menu that no longer parses
  (schema drift, a damaged row) comes back `menu_readable: false` with an empty `menu`, and
  every other pick on the day still renders.
- **`positions`** are every spread any book (`paper`, `shadow`, `baseline`) opened that New York
  day, oldest first, in the `GET /spreads/positions` shape. A pick's `spread_id` is the position
  it opened, when one did.
- **`previous_day` / `next_day`** are the nearest New York days with a pick or an opened spread.

**Response - `SpreadPicksResponse`:** `{ as_of, available, underlying, mode, ai_enabled, day, previous_day, next_day, picks: SpreadPickOut[], positions: SpreadPositionOut[] }`.

| `SpreadPicksResponse` field | Meaning |
|---|---|
| `underlying` | the spreads book's underlying (SPY) |
| `mode` | the spreads service's configured book mode (`shadow` or `paper`) |
| `ai_enabled` | `config spreads.ai.enabled`: whether menus are offered at all |
| `day` | the New York day shown |

`SpreadPickOut`: `{ pick_id, created_at, book_mode, choice, reason, fallback_reason, executed_letter, send_rejected, send_reasons, filled, model, regime, side, plan_bias, event_flag, menu_readable, menu: SpreadMenuItemOut[], spread_id }`.

| `SpreadPickOut` field | Meaning |
|---|---|
| `choice` | the menu letter Claude picked, or `skip` |
| `reason` | Claude's stated reason (Claude's view; the console labels it as such), `""` when it gave none |
| `fallback_reason` | set when Claude's answer could not be used (`timeout`, `off_menu`, `unparseable` or `picker_error`); the service then took the baseline item when there was one |
| `executed_letter` | the item the service tried to send; `null` when nothing was sent |
| `send_rejected` | `true` when it did not trade: refused before sending (the gate, stale quotes) **or** an order that did not fill |
| `send_reasons` | the refusal reasons, as codes |
| `filled` | the order filled |
| `model`, `regime`, `side`, `plan_bias`, `event_flag` | what Claude was asked, the gamma regime and side it saw, the day's plan bias, and whether an event day was flagged |
| `menu_readable` | `false` when the stored menu no longer parses; `menu` is then empty |
| `spread_id` | the position this pick opened, `null` when none did |

`SpreadMenuItemOut`: `{ letter, position: "inside" | "baseline" | "outer", side: "put" | "call", short_strike, long_strike, width, contracts, credit_mid, credit_after_costs, max_loss_per_contract_usd, short_delta, spot, dist_spot_pts, dist_em_multiple, be_nominal_exits }`.
Every figure was computed by `src/spreads/menu.py` when the menu was built; credits are per share.
`contracts` is set by the spreads gate, never by Claude; `dist_spot_pts` is the short strike's
distance from spot (positive is out of the money), `dist_em_multiple` the same in expected
moves, `be_nominal_exits` the break-even win rate (0 to 1) under the configured exits;
`short_delta`, `dist_em_multiple` and `be_nominal_exits` may be `null`. `dist_spot_pts` never is.

## News (news thread, spec §7.6)

Read-only views over `data/news.db`, the news process's own SQLite file
(`docs/superpowers/specs/2026-10-09-news-thread-design.md`). The router
(`src/api/routers/news.py`) opens it through `src/api/news_db.py` with SQLite `mode=ro` and
never imports the news process's read-write engine (`src.news.store.session`), directly or
transitively (`tests/test_news_fence.py::test_api_process_never_loads_the_rw_engine`). The one
web write is the `news_brief` command (`POST /commands`, see `docs/web/commands.md`), which the
drain turns into a `news_requests` row the news process picks up.

Every response carries `available: bool`. **A missing or unopenable `news.db`** (fresh
install, news service never started) **answers `200` with `available: false`** and empty
lists, never a `500`; only `GET /news/posts/{id}` answers `404` instead, since there is no
post to return. Owner-only.

| Route | Query | Response model |
|---|---|---|
| `GET /news/feed` | `group?` (`macro` \| `market` \| `tickers` \| `earnings` \| `briefs`, anything else `422`), `symbol?` (case-insensitive), `limit` (1-100, default 30), `before?` (post id, for paging) | `NewsFeedResponse` |
| `GET /news/posts/{id}` | | `NewsPostDetailResponse` |
| `GET /news/calendar` | `days` (1-21, default 7) | `NewsCalendarResponse` |
| `GET /news/ticker/{symbol}` | | `NewsTickerResponse` |
| `GET /news/status` | | `NewsStatusResponse` |

### `GET /news/feed`

Posts newest first (`id` descending). `group` maps to post kinds through
`src/news/store/queries.py::KIND_GROUPS`: `macro` = `macro_print`, `breaking`; `market` =
`market_move`, `vix_spike`, `digest_premarket`, `digest_close`, `digest_week`; `tickers` =
`ticker_move`; `earnings` = `earnings`; `briefs` = `brief`. Page with `before=<smallest id
seen>`.

**Response — `NewsFeedResponse`:** `{ as_of, available, posts: NewsPostOut[] }`.
`NewsPostOut`: `{ id, kind, subject, posted_at, stage, critical, silent, has_chart, payload }`,
where `payload` is the post's stored `CardPayload` (`src/news/schemas.py`) as JSON and `stage`
is `facts` \| `explained` \| `fallback`.

### `GET /news/posts/{id}`

**Response — `NewsPostDetailResponse`:** `{ as_of, available, post: NewsPostOut, chart_data_uri }`.
`chart_data_uri` is the post's PNG inlined as `data:image/png;base64,…`, or `null` when the
post has no chart, the file is gone, or its stored path resolves **outside
`news.charts_dir`** (a stored path is never trusted to read an arbitrary file).

### `GET /news/calendar`

Economic events from 12 hours ago to `days` ahead, and earnings from today (ET) to `days`
ahead. `held` is `true` when the symbol is a held underlying in the trading DB's freshest
portfolio reading (`read_portfolio`, the same chain as `/portfolio/*`).

**Response — `NewsCalendarResponse`:** `{ as_of, available, econ: EconEventOut[], earnings: EarningsOut[] }`.
`EconEventOut`: `{ title, scheduled_at, impact, forecast, previous, actual, surprise_dir }`.
`EarningsOut`: `{ symbol, report_date, timing, eps_est, eps_actual, status, held }`.

### `GET /news/ticker/{symbol}`

Everything the web `/news/[symbol]` page needs: the latest `brief` post, story clusters tagged
with the symbol over the last 72 hours (at most 10, each with its ranked source links), the
next earnings date (yesterday to 60 days ahead), and the newest `news_requests` row so the page
can show a requested brief as pending, running, done or failed.

**Response — `NewsTickerResponse`:** `{ as_of, available, symbol, latest_brief: NewsPostOut | null, clusters: ClusterOut[], next_earnings: EarningsOut | null, request: NewsRequestOut | null }`.
`ClusterOut`: `{ id, headline, source_count, last_seen, links: {name, url}[] }`.
`NewsRequestOut`: `{ id, status, requested_at, post_id, error }`.

### `GET /news/status`

The news service's health, from `news_state`: the heartbeat every loop iteration that completes
without raising writes, the news process's circuit-breaker states stored beside it (as of that
heartbeat), each source's last *successful* answer (a poll where every request failed records
nothing), and today's (ET) LLM call count against `news.llm.max_calls_per_day`. A corrupt stored
value reads as missing, never a 500.

**Response — `NewsStatusResponse`:** `{ as_of, available, heartbeat_at, heartbeat_age_s, sources_ok: {source: datetime}, breakers: {name: "closed" | "open" | "half_open"}, llm_calls_today, llm_cap }`.

## What Claude knows (market picture, spec section 11)

### `GET /claude/context`

Everything the web `/more/claude` page shows: the market picture, the regime and its CSP limits,
what each Claude call is given, the stories the news triage dropped, and the per-name notes.
Read-only and owner-only (`src/api/routers/claude_context.py`). The regime state and its
`/regime off` suspension are read from the trading DB's `system_settings` through
`src/api/settings_read.py::read_setting`; the picture, the triage rows and the dossiers from
`data/news.db` through `src/api/news_db.py` (`mode=ro`) and the Session-parameterised readers in
`src/news/store/queries.py`. The limits are read from the same typed `risk_limits.yaml` blocks the
sizer reads (`regime:`, `leveraged_sizing:`, `claude_cut:`), so the page cannot disagree with what
the gate applies. No write of any kind.

**Degrades, never 500s.** No `news.db` (news service never started): `available: false`, no picture,
empty `dropped` and `dossiers`; the regime, the limits and the tiles still answer. A `news.db` from
before the picture, triage or dossier tables existed: `available: true` with the same empty
sections (the read-only engine cannot create tables). No stored regime state, or one that no
longer validates: `regime: null` and `limits: []`. An invalid `regime:` or `leveraged_sizing:`
block shows no limits for it.

**Response — `ClaudeContextResponse`:**

| Field | Meaning |
|---|---|
| `as_of`, `available` | the envelope; `available` is "`news.db` is present" |
| `picture` | the newest `MarketPicture` (`src/common/schemas.py`), or `null`. `stale` is true when the last rebuild failed and only the numbers are fresh; the story descriptions are Claude's words, grounded before they were saved |
| `regime` | the trading process's persisted `RegimeState` (both indices: base, effective regime, why it was raised, the inputs), or `null` |
| `regime_enabled` | `regime.enabled` in `risk_limits.yaml`; false means no regime limit applies at all |
| `suspended_today` | `/regime off` was sent today (ET); the limits below are then not in force until the next trading day |
| `limits` | `RegimeLimitOut[]`, one per index: `{ index, regime, budget_pct, per_trade_pct, max_new_per_day (null: no daily limit), floor_new_per_day }`, the CSP limits of that index's current regime |
| `leveraged_enabled`, `leveraged` | `leveraged_sizing.enabled`; `LeveragedLimitOut[]` `{ symbol, leverage, calm_fraction, stressed_fraction }` for every name in `universe.leveraged_etfs` (a name missing from the operator's `leverage` map reads as 3x) |
| `claude_cut_mode`, `account_mode` | `applied` or `record_only` for the account the API runs against (`LIVE_TRADING` picks `claude_cut.apply_live` or `apply_in_paper`), and `paper` or `live`. The daily breaker can still stop a cut on the day; that is not a mode (see the next field) |
| `claude_cut_breaker_tripped_today` | true when today's (ET) daily cut breaker has tripped: Claude zeroed at least `claude_cut.breaker_min` of the day's auto CSPs and more than `breaker_pct` percent of those reviewed, so further cuts today are recorded but not applied. Read through `read_setting` from the sender's day state, the `system_settings` key `claude_cut_state` (`{"day": ET date, "reviewed": [...], "breaker_alerted": bool}`): true only when its `day` is today in ET and `breaker_alerted` is true; a missing, stale or malformed setting is false. Answered even when `available` is false |
| `calls` | `CallContextOut[]` `{ kind, label, blocks: string[] }`, static (`src/api/claude_calls.py::CALLS`): which prompt blocks each of the seven Claude calls carries. `tests/test_api_claude_context.py` checks every block's header text occurs in the file that builds it |
| `dropped`, `dropped_total` | `DroppedOut[]` `{ cluster_id, headline, reason, judged_at, promoted, promoted_move_pct }`: stories judged noise in the last 7 days, plus any the market-reaction check promoted later, newest judgement first, at most 100 (`dropped_total` is how many there were). `reason` is the dismissal reason; a promoted row's `promoted_move_pct` is the signed move that promoted it |
| `not_reviewed_7d` | stories nobody judged (outside the ranked batch) in the last 7 days |
| `dossiers` | `DossierOut[]` for every covered name that has notes, held names first then alphabetical: `{ symbol, kind, health, health_why, held, story, story_evidence, reported: {text, cluster_id}[], events: {id, title, on, evidence, quote}[], profile, facts: {id, label, display}[], facts_at, prose_at, stale }`. Python wrote the facts and health; Claude wrote the story and profile; the events carry the news text their date was found in. `reported` is the figures Claude quoted from the cited news (at most three, each at most 120 characters with the `C<id>` of the cluster that states it); Python kept an item only when every number in it is written in that cluster's text, and the story never carries them. Empty for a name with none, and for a row stored before the field existed |
| `without_notes` | covered names with no dossier yet (empty when `available` is false) |

"Covered" is `would_own` + `actively_wheeling` from the effective universe (web overrides
included) + every held underlying from the portfolio reading, spreads-book underlyings out: the
same set the news process builds notes for.

### `GET /claude/sizing?day=YYYY-MM-DD`

The sizing record for one New York day (default today), newest first, capped at 200 rows: the cash-secured puts
the market regime, the scale-in ladder, the leveraged-ETF ceiling, the bottoming rule or Claude's reduce-only
cut trimmed or held back, and the covered calls the breakout rule pushed out. Read-only and owner-only
(`src/api/routers/claude_context.py`), straight from the trading DB's `sizing_actions` table (written only by
`src/regime/actions.py`; nothing in the engine, execution or sizing path reads it back). The web Trades History
view shows it as "Held back or trimmed".

**Response — `SizingActionsResponse`:** `as_of`, `day`, and `actions: SizingActionOut[]`, each `{ id,
created_at, underlying, right, strike, expiry, premium, kind (regime_budget | regime_ceiling |
leveraged_ceiling | regime_daily_limit | regime_floor_lot | escalation_trim | scale_in_zone |
loss_exit_cooldown | bottoming_lot | claude_cut | claude_cut_unapplied | cc_breakout_floor), regime,
deterministic_contracts (what the rules alone would have sent), sent_contracts (0 when held back), reason, order_id }`.
For a `claude_cut` row the `reason` carries Claude's stated reason. An empty day answers `actions: []`.

