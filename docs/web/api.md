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
    { "as_of": "2026-09-03T10:00:00Z", "key": "options", "label": "Options", "available": true, "note": null },
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

**Query params:** `status=pending` (default), `approved`, `rejected`, `expired`, or `all`; `limit` (1-200, default 50). An unknown `status` returns **422**, not a silent empty list. `status=all` is ordered newest-first by `created_at` (a pending row is not promoted above a newer decided one).

**Response — `ApprovalListResponse`:**

| Field | Type |
|---|---|
| `as_of` | datetime |
| `approvals` | `ApprovalSummary[]` |

`ApprovalSummary`: `{ as_of, id, candidate_id, status, underlying, strategy, right, strike, expiry, contracts, premium, blended_score, expires_at, decided_at, order_state, source }`.
`premium` is per share, always. `order_state` is `null` when no order exists.
`source` is `"scan"` or `"roll"`, derived from the candidate's `run_id` prefix.

### `GET /options/approvals/{id}`

One approval in full, including the ideal zone, the gate reasons (humanised), the
five Claude review fields (separately, never one blob), and the alternative strikes
assessed on the same run.

**Response — `ApprovalDetail`:** `ApprovalSummary` plus `{ snapshot, ideal, gate_reasons, review, alternatives }`.
`ideal` is `{ lo, hi, min_credit }` from `RiskVerdictRow`. `review` is the five
fields `{ why_attractive, risks, tradeoffs, assignment_considerations, rolling_considerations }` or `null`.
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

### `GET /options/orders`

Working orders by default. `state=working` means `queued`, `submitted` or
`partial`; `state=all` returns everything. `underlying`/`strategy`/`strike` come
from the order's `snapshot`, falling back to the joined `CandidateRow` so a pruned
candidate does not blank the row. `avg_fill_price` is `null` for an unfilled
order, never `0.0`.

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
`adjusted_cost_basis` is what the collected premium makes it (from
`campaigns.adjusted_cost_basis`, when the shares came from an assignment).
`unrealized_pnl` is against the former, `unrealized_pnl_adjusted` against the
latter. `adjusted_cost_basis` is `null` for shares that did not come from an
assignment, and `unrealized_pnl_adjusted` is `null` with it — not a copy of
`unrealized_pnl`, and not zero. The basis is read through the API's own
read-only engine (mirroring `storage.campaigns.adjusted_cost_basis_for`'s
newest-open-assigned-campaign rule exactly), never through the storage
engine's read-write session.

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
