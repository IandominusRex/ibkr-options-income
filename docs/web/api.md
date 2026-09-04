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
