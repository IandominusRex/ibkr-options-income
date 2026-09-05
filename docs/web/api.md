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

The navigation manifest that drives the web app's left rail. Lists every section with an
`available` flag; unavailable sections render disabled with their `note` as the reason.

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
    { "as_of": "2026-09-03T10:00:00Z", "key": "options", "label": "Options", "available": false, "note": "Arrives in P2" },
    { "as_of": "2026-09-03T10:00:00Z", "key": "portfolio", "label": "Portfolio", "available": false, "note": "Arrives in P3" },
    { "as_of": "2026-09-03T10:00:00Z", "key": "pnl", "label": "P&L", "available": false, "note": "Arrives in P4" },
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

The effective scan universe, read-only in P1 (`editable: false`). Every list is returned
unmodified and in `universe.yaml` file order.

**Auth:** required.

**Response — `UniverseResponse`:**

| Field | Type | Notes |
|---|---|---|
| `as_of` | datetime | |
| `indexes` | `string[]` | in file order |
| `watchlist` | `string[]` | in file order |
| `would_own` | `string[]` | CSP allowlist |
| `actively_wheeling` | `string[]` | subset of `would_own` |
| `sectors` | `Record<string, string>` | symbol → sector tag |
| `strike_bands` | `Record<string, number>` | symbol → band fraction, only overrides |
| `editable` | bool | `false` in P1 — no write path exists |
