# Milestone 4 — Prices, Technicals, News, Sentiment

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or
> superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** The ticker page becomes genuinely useful: a price chart, technical panels, news with
per-item sentiment, and delayed intraday quotes on watched names.

**Spec:** `Web plan/P0-P1-design.md` §5.2, §5.5, §9.2. **Depends on:** Milestone 3 complete.

---

## Task 4.1 — `BulkPriceProvider` and the stooq backend `[SONNET]`

Sonnet: **this task contains a licence gate.** stooq is only used if its terms permit
programmatic access; otherwise the fallback path ships instead. That is a judgment call with a
real consequence, and it must not be waved through.

**Files:**
- Modify: `src/data/protocols.py`, `src/data/factory.py`
- Create: `src/data/stooq_backend.py`
- Create: `docs/web/data-sources.md`
- Test: `tests/test_stooq_backend.py`

**Interfaces:**
- Produces:
  - `BulkPriceProvider` Protocol: `get_daily_bars(symbol: str, lookback_days: int = 400) -> pd.DataFrame`
    with columns `Open, High, Low, Close, Volume`, a `DatetimeIndex`, ascending, empty on failure
  - `StooqBulkPriceProvider`, `YFinanceBulkPriceProvider`
  - `get_bulk_price_provider() -> BulkPriceProvider`

- [ ] **Step 1: Verify the licence before writing code**

Read stooq's terms of use. Record the finding in `docs/web/data-sources.md` with the date
checked, the URL, and a verdict of `permitted` or `not permitted`.

**If not permitted:** set `data.bulk_price_provider: yfinance` in `config/settings.yaml`, skip
Step 4 (the stooq backend), and implement only `YFinanceBulkPriceProvider`. Every other step
proceeds unchanged, because the Protocol is what the rest of the system depends on.

- [ ] **Step 2: Write the failing test**

Create `tests/test_stooq_backend.py`:

```python
"""Bulk daily bars: CSV parsing, ordering, and fail-soft behaviour."""

from __future__ import annotations

import httpx
import pandas as pd

from src.data.stooq_backend import StooqBulkPriceProvider

_CSV = (
    "Date,Open,High,Low,Close,Volume\n"
    "2026-08-28,220.0,222.5,219.0,221.4,50000000\n"
    "2026-08-29,221.5,224.0,221.0,223.8,48000000\n"
)


def _provider(response: httpx.Response) -> StooqBulkPriceProvider:
    return StooqBulkPriceProvider(
        transport=httpx.MockTransport(lambda _r: response)
    )


def test_parses_csv_into_an_ohlcv_frame() -> None:
    df = _provider(httpx.Response(200, text=_CSV)).get_daily_bars("AAPL")
    assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert len(df) == 2
    assert df["Close"].iloc[-1] == 223.8


def test_index_is_ascending_dates() -> None:
    df = _provider(httpx.Response(200, text=_CSV)).get_daily_bars("AAPL")
    assert isinstance(df.index, pd.DatetimeIndex)
    assert df.index.is_monotonic_increasing


def test_symbol_is_suffixed_for_us_listings() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, text=_CSV)

    StooqBulkPriceProvider(transport=httpx.MockTransport(handler)).get_daily_bars("AAPL")
    assert "s=aapl.us" in seen[0]


def test_http_failure_returns_an_empty_frame() -> None:
    df = _provider(httpx.Response(500)).get_daily_bars("AAPL")
    assert df.empty


def test_an_error_body_returns_an_empty_frame() -> None:
    """stooq answers an unknown symbol with 200 and a text body, not a 404."""
    df = _provider(httpx.Response(200, text="No data")).get_daily_bars("ZZZZ")
    assert df.empty
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_stooq_backend.py -v`
Expected: FAIL, module not found.

- [ ] **Step 4: Add the Protocol**

Append to `src/data/protocols.py`:

```python
@runtime_checkable
class BulkPriceProvider(Protocol):
    """Daily OHLCV for the cold tier, where a keyed per-symbol API would be too expensive."""

    def get_daily_bars(self, symbol: str, lookback_days: int = 400) -> pd.DataFrame:
        """Ascending daily OHLCV with a DatetimeIndex. Empty frame when unavailable."""
        ...
```

- [ ] **Step 5: Implement `src/data/stooq_backend.py`**

```python
"""Free bulk daily bars for the cold tier.

Licence status is recorded in docs/web/data-sources.md. If stooq is not permitted, set
data.bulk_price_provider to "yfinance" and only YFinanceBulkPriceProvider is used; the
Protocol is what the rest of the system depends on, so nothing else changes.
"""

from __future__ import annotations

import io
import logging

import httpx
import pandas as pd

log = logging.getLogger(__name__)

STOOQ_URL = "https://stooq.com/q/d/l/"
_COLUMNS = ["Open", "High", "Low", "Close", "Volume"]


def _empty() -> pd.DataFrame:
    return pd.DataFrame(columns=_COLUMNS, index=pd.DatetimeIndex([], name="Date"))


class StooqBulkPriceProvider:
    def __init__(self, *, transport: httpx.BaseTransport | None = None) -> None:
        self._client = httpx.Client(timeout=20.0, transport=transport)

    def get_daily_bars(self, symbol: str, lookback_days: int = 400) -> pd.DataFrame:
        try:
            resp = self._client.get(
                STOOQ_URL, params={"s": f"{symbol.lower()}.us", "i": "d"}
            )
        except httpx.HTTPError as exc:
            log.warning("stooq request failed for %s: %s", symbol, exc)
            return _empty()

        if resp.status_code != 200 or not resp.text.startswith("Date,"):
            # An unknown symbol answers 200 with a plain-text message, not a 404.
            return _empty()

        try:
            df = pd.read_csv(io.StringIO(resp.text), parse_dates=["Date"])
            df = df.set_index("Date").sort_index()
            df = df[_COLUMNS].astype(float)
        except (ValueError, KeyError) as exc:
            log.warning("stooq CSV for %s had an unexpected shape: %s", symbol, exc)
            return _empty()

        return df.tail(lookback_days)


class YFinanceBulkPriceProvider:
    """Fallback. Wraps the existing price provider so the Protocol is satisfied either way."""

    def get_daily_bars(self, symbol: str, lookback_days: int = 400) -> pd.DataFrame:
        from src.data.factory import get_price_provider

        df = get_price_provider().get_ohlcv(symbol, lookback_days=lookback_days)
        return df if not df.empty else _empty()
```

- [ ] **Step 6: Add the factory getter**

```python
def _make_bulk_price_provider(name: str) -> BulkPriceProvider:
    if name == "stooq":
        from src.data.stooq_backend import StooqBulkPriceProvider

        return StooqBulkPriceProvider()
    if name == "yfinance":
        from src.data.stooq_backend import YFinanceBulkPriceProvider

        return YFinanceBulkPriceProvider()
    raise ValueError(f"Unknown data.bulk_price_provider backend: {name!r}")


@functools.lru_cache(maxsize=1)
def get_bulk_price_provider() -> BulkPriceProvider:
    return _make_bulk_price_provider(get_config().data.bulk_price_provider)
```

- [ ] **Step 7: Run tests, then commit**

Run: `python -m pytest tests/test_stooq_backend.py -v && ruff check . && mypy src`

```bash
git add src/data docs/web/data-sources.md tests/test_stooq_backend.py
git commit -m "feat(data): add bulk daily-bar provider with a documented licence check"
```

---

## Task 4.2 — Daily bars ingest `[GLM]`

**Files:** Create `src/research/ingest/prices.py`. Test `tests/test_ingest_prices.py`.

**Interfaces:**
- Produces: `ingest_daily_bars(symbol: str) -> int` returning rows written; upserts on
  `(symbol, date)`; returns 0 without deleting anything when the fetch is empty.

- [ ] **Step 1: Write the failing test**

```python
"""Daily-bar ingest upserts and never truncates on a failed fetch."""

from __future__ import annotations

import pandas as pd
import pytest

from src.research.ingest.prices import ingest_daily_bars
from src.research.store.models import DailyBarRow
from src.research.store.session import init_research_db, research_session


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "src.research.store.session._resolve_url",
        lambda: f"sqlite:///{(tmp_path / 'research.db').as_posix()}",
    )
    monkeypatch.setattr("src.research.store.session._engine", None)
    init_research_db()


def _frame(closes: dict[str, float]) -> pd.DataFrame:
    idx = pd.DatetimeIndex(list(closes), name="Date")
    return pd.DataFrame(
        {
            "Open": list(closes.values()),
            "High": list(closes.values()),
            "Low": list(closes.values()),
            "Close": list(closes.values()),
            "Volume": [1000.0] * len(closes),
        },
        index=idx,
    )


class _Stub:
    def __init__(self, df: pd.DataFrame) -> None:
        self._df = df

    def get_daily_bars(self, symbol: str, lookback_days: int = 400) -> pd.DataFrame:
        return self._df


def test_writes_bars(db, monkeypatch) -> None:
    monkeypatch.setattr(
        "src.research.ingest.prices.get_bulk_price_provider",
        lambda: _Stub(_frame({"2026-08-28": 221.4, "2026-08-29": 223.8})),
    )
    assert ingest_daily_bars("AAPL") == 2
    with research_session() as s:
        assert s.query(DailyBarRow).filter_by(symbol="AAPL").count() == 2


def test_reingest_updates_rather_than_duplicating(db, monkeypatch) -> None:
    monkeypatch.setattr(
        "src.research.ingest.prices.get_bulk_price_provider",
        lambda: _Stub(_frame({"2026-08-28": 221.4})),
    )
    ingest_daily_bars("AAPL")
    monkeypatch.setattr(
        "src.research.ingest.prices.get_bulk_price_provider",
        lambda: _Stub(_frame({"2026-08-28": 999.0})),
    )
    ingest_daily_bars("AAPL")
    with research_session() as s:
        rows = s.query(DailyBarRow).filter_by(symbol="AAPL").all()
        assert len(rows) == 1
        assert rows[0].close == 999.0


def test_empty_fetch_leaves_history_intact(db, monkeypatch) -> None:
    monkeypatch.setattr(
        "src.research.ingest.prices.get_bulk_price_provider",
        lambda: _Stub(_frame({"2026-08-28": 221.4})),
    )
    ingest_daily_bars("AAPL")
    monkeypatch.setattr(
        "src.research.ingest.prices.get_bulk_price_provider",
        lambda: _Stub(pd.DataFrame()),
    )
    assert ingest_daily_bars("AAPL") == 0
    with research_session() as s:
        assert s.query(DailyBarRow).filter_by(symbol="AAPL").count() == 1
```

- [ ] **Step 2: Run it and watch it fail**, then implement `src/research/ingest/prices.py`:

```python
"""Persist daily OHLCV for a symbol."""

from __future__ import annotations

import logging

from src.common.config import get_config
from src.data.factory import get_bulk_price_provider
from src.research.store.models import DailyBarRow
from src.research.store.session import research_session

log = logging.getLogger(__name__)


def ingest_daily_bars(symbol: str) -> int:
    """Upsert daily bars. Returns rows written; 0 leaves existing history untouched."""
    provider = get_bulk_price_provider()
    df = provider.get_daily_bars(symbol)
    if df.empty:
        log.info("No bars returned for %s; leaving history intact", symbol)
        return 0

    source = get_config().data.bulk_price_provider
    written = 0
    with research_session() as session:
        existing = {
            r.date: r for r in session.query(DailyBarRow).filter_by(symbol=symbol).all()
        }
        for ts, row in df.iterrows():
            day = ts.date()
            target = existing.get(day)
            if target is None:
                session.add(
                    DailyBarRow(
                        symbol=symbol, date=day,
                        open=float(row["Open"]), high=float(row["High"]),
                        low=float(row["Low"]), close=float(row["Close"]),
                        volume=float(row["Volume"]), source=source,
                    )
                )
            else:
                target.open = float(row["Open"])
                target.high = float(row["High"])
                target.low = float(row["Low"])
                target.close = float(row["Close"])
                target.volume = float(row["Volume"])
                target.source = source
            written += 1
    return written
```

- [ ] **Step 3: Run tests, then commit**

```bash
git add src/research/ingest/prices.py tests/test_ingest_prices.py
git commit -m "feat(research): persist daily bars"
```

---

## Task 4.3 — Delayed intraday quotes for the warm tier `[GLM]`

**Files:** Create `src/research/ingest/quotes.py`. Modify `src/research/ingest/jobs.py`.
Test `tests/test_ingest_quotes.py`.

**Interfaces:**
- Produces:
  - `warm_symbols() -> list[str]` — union of watchlist items and symbols viewed in the last 7 days
  - `refresh_quotes() -> int`

Freshness target is 15 to 30 minutes (design decision), so the scheduler runs this every 15
minutes during regular trading hours only. Use the existing `src/common/market_hours.py` to
decide, rather than reimplementing a session calendar.

- [ ] **Step 1: Write the failing test**

```python
"""Warm-tier quote refresh covers watchlisted and recently viewed symbols, and only those."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.research.ingest.quotes import refresh_quotes, warm_symbols
from src.research.store.models import (
    QuoteRow,
    RecentlyViewedRow,
    WatchlistItemRow,
    WatchlistRow,
)
from src.research.store.session import init_research_db, research_session


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "src.research.store.session._resolve_url",
        lambda: f"sqlite:///{(tmp_path / 'research.db').as_posix()}",
    )
    monkeypatch.setattr("src.research.store.session._engine", None)
    init_research_db()


def test_warm_set_is_empty_by_default(db) -> None:
    assert warm_symbols() == []


def test_watchlisted_symbols_are_warm(db) -> None:
    with research_session() as s:
        s.add(WatchlistRow(id=1, user_id="owner", name="Default"))
        s.add(WatchlistItemRow(watchlist_id=1, symbol="NVDA", added_at=datetime.now(UTC)))
    assert warm_symbols() == ["NVDA"]


def test_recently_viewed_symbols_are_warm(db) -> None:
    with research_session() as s:
        s.add(RecentlyViewedRow(user_id="owner", symbol="META", viewed_at=datetime.now(UTC)))
    assert warm_symbols() == ["META"]


def test_stale_views_fall_out_of_the_warm_set(db) -> None:
    with research_session() as s:
        s.add(
            RecentlyViewedRow(
                user_id="owner", symbol="OLD",
                viewed_at=datetime.now(UTC) - timedelta(days=30),
            )
        )
    assert warm_symbols() == []


def test_refresh_writes_a_quote(db, monkeypatch) -> None:
    with research_session() as s:
        s.add(RecentlyViewedRow(user_id="owner", symbol="AAPL", viewed_at=datetime.now(UTC)))
    monkeypatch.setattr(
        "src.research.ingest.quotes.get_price_provider",
        lambda: type("P", (), {"get_last_price": staticmethod(lambda sym: 221.4)})(),
    )
    assert refresh_quotes() == 1
    with research_session() as s:
        assert s.get(QuoteRow, "AAPL").price == 221.4


def test_a_missing_quote_does_not_write_a_row(db, monkeypatch) -> None:
    """No quote is not the same as a price of zero."""
    with research_session() as s:
        s.add(RecentlyViewedRow(user_id="owner", symbol="AAPL", viewed_at=datetime.now(UTC)))
    monkeypatch.setattr(
        "src.research.ingest.quotes.get_price_provider",
        lambda: type("P", (), {"get_last_price": staticmethod(lambda sym: None)})(),
    )
    assert refresh_quotes() == 0
    with research_session() as s:
        assert s.get(QuoteRow, "AAPL") is None
```

- [ ] **Step 2: Implement `src/research/ingest/quotes.py`**

```python
"""Delayed intraday quotes for the warm tier.

Scoped to watchlisted and recently viewed symbols so free-tier limits are respected.
Freshness target is 15 to 30 minutes, so the scheduler runs this every 15 minutes during
regular trading hours only.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from src.data.factory import get_price_provider
from src.research.store.models import QuoteRow, RecentlyViewedRow, WatchlistItemRow
from src.research.store.session import research_session

log = logging.getLogger(__name__)

RECENT_VIEW_DAYS = 7


def warm_symbols() -> list[str]:
    cutoff = datetime.now(UTC) - timedelta(days=RECENT_VIEW_DAYS)
    with research_session() as session:
        watched = {r.symbol for r in session.query(WatchlistItemRow).all()}
        viewed = {
            r.symbol
            for r in session.query(RecentlyViewedRow)
            .filter(RecentlyViewedRow.viewed_at >= cutoff)
            .all()
        }
    return sorted(watched | viewed)


def refresh_quotes() -> int:
    provider = get_price_provider()
    now = datetime.now(UTC)
    written = 0

    for symbol in warm_symbols():
        try:
            price = provider.get_last_price(symbol)
        except Exception as exc:
            log.warning("Quote fetch failed for %s: %s", symbol, exc)
            continue
        if price is None:
            continue  # absent, never zero

        with research_session() as session:
            row = session.get(QuoteRow, symbol)
            if row is None:
                session.add(
                    QuoteRow(symbol=symbol, price=price, as_of=now, source="yfinance")
                )
            else:
                row.change_pct = (
                    ((price - row.price) / row.price * 100.0)
                    if row.price
                    else None
                )
                row.price = price
                row.as_of = now
        written += 1

    return written
```

- [ ] **Step 3: Register in the scheduler**

```python
    sched.add_job(
        lambda: run_job("quotes", refresh_quotes),
        IntervalTrigger(minutes=15),
        id="refresh_quotes",
        replace_existing=True,
    )
```

Guard `refresh_quotes` so it returns 0 immediately outside regular trading hours, using the
existing helper in `src/common/market_hours.py`. Read that module and use its actual function
name rather than inventing one.

- [ ] **Step 4: Run tests, then commit**

```bash
git add src/research tests/test_ingest_quotes.py
git commit -m "feat(research): delayed intraday quotes for the warm tier"
```

---

## Task 4.4 — Wire technicals, news, and sentiment into the payload `[SONNET]`

Sonnet: this crosses the analytics tier boundary. Sentiment is enrichment and must reach the
card and the prompt only; it must not become an input to anything deterministic.

**Files:**
- Modify: `src/research/ingest/materialize.py`, `src/api/models/research.py`,
  `src/api/routers/research.py`
- Create: `src/research/ingest/news.py`
- Test: `tests/test_research_enrichment.py`

**Interfaces:**
- Consumes: `get_technical_stats(symbol, lookback_days=260, spot_override=None, cached_yf_price=None)`
  from `src/analytics/technicals.py`; `SentimentScorer().score(symbol) -> SentimentDetail` from
  `src/analytics/sentiment.py`; `get_news_provider().get_headlines(symbol, limit)` from
  `src/data/factory.py`.
- Produces:
  - `ingest_news(symbol: str, limit: int = 25) -> int`
  - `MaterializeResult` gains, for each of technicals / sentiment / news, a triple of
    `<name>`, `<name>_state` and `<name>_reason` — the reason field is what the UI renders when
    a section is unavailable, so every section needs its own
  - `AnalysisResponse` gains `technicals: Section[TechnicalStats]`,
    `sentiment: Section[SentimentDetail]`, `news: Section[list[NewsItem]]`,
    `quote: Sourced[float]`

- [ ] **Step 1: Write the failing test**

```python
"""Enrichment sections degrade independently and never fail the page."""

from __future__ import annotations

import pytest

from src.research.ingest.materialize import SectionState, materialize
from src.research.store.models import SymbolRow
from src.research.store.session import init_research_db, research_session


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "src.research.store.session._resolve_url",
        lambda: f"sqlite:///{(tmp_path / 'research.db').as_posix()}",
    )
    monkeypatch.setattr("src.research.store.session._engine", None)
    init_research_db()
    with research_session() as s:
        s.add(SymbolRow(symbol="AAPL", cik="0000320193", name="Apple Inc."))


def test_a_sentiment_outage_does_not_break_technicals(db, monkeypatch) -> None:
    monkeypatch.setattr(
        "src.research.ingest.materialize.ingest_fundamentals", lambda s, c: object()
    )
    monkeypatch.setattr(
        "src.research.ingest.materialize._technicals",
        lambda symbol: {"rsi_14": 55.0},
    )

    def boom(symbol: str):
        raise RuntimeError("StockTwits down")

    monkeypatch.setattr("src.research.ingest.materialize._sentiment", boom)

    result = materialize("AAPL")
    assert result.technicals_state is SectionState.READY
    assert result.sentiment_state is SectionState.UNAVAILABLE
    assert "StockTwits down" in (result.sentiment_reason or "")


def test_sentiment_is_never_an_input_to_the_deterministic_sections(db) -> None:
    """Structural guard: materialize must not pass sentiment into technicals or fundamentals."""
    import inspect

    from src.research.ingest import materialize as mod

    source = inspect.getsource(mod.materialize)
    sentiment_line = next(
        (line for line in source.splitlines() if "_sentiment(" in line), ""
    )
    assert "technical" not in sentiment_line.lower()
    assert "fundamental" not in sentiment_line.lower()
```

- [ ] **Step 2: Implement**

Add to `src/research/ingest/materialize.py`, keeping each source in its own guarded helper so
one outage cannot cascade:

```python
def _technicals(symbol: str) -> object:
    from src.analytics.technicals import get_technical_stats

    return get_technical_stats(symbol)


def _sentiment(symbol: str) -> object:
    """Enrichment tier. Reaches the card and the prompt only, never a deterministic input."""
    from src.analytics.sentiment import SentimentScorer

    return SentimentScorer().score(symbol)


def _news(symbol: str) -> object:
    from src.research.ingest.news import recent_news

    return recent_news(symbol)


def _section(fn, *args):
    """Run one source. Returns (data, state, reason) and never raises."""
    try:
        data = fn(*args)
    except Exception as exc:
        return None, SectionState.UNAVAILABLE, str(exc)
    if data is None:
        return None, SectionState.UNAVAILABLE, "No data available"
    return data, SectionState.READY, None
```

Then in `materialize`, call `_section(_technicals, symbol)`, `_section(_sentiment, symbol)`
and `_section(_news, symbol)` independently, assigning each to its own state field. **Do not
short-circuit the remaining sources when one fails.**

`src/research/ingest/news.py` reads `get_news_provider().get_headlines(symbol, limit)`,
handles both yfinance shapes (the legacy flat `title` key and the newer `{"content": {...}}`
nesting, as documented in `src/data/protocols.py`), scores each headline with the VADER helper
already in `src/analytics/sentiment.py`, and upserts `NewsItemRow` deduplicated on
`(symbol, url)`.

- [ ] **Step 3: Extend the API models and route**

`AnalysisResponse` gains the four fields listed under Interfaces. `quote` uses
`Sourced[float].of(price, Source.YFINANCE, as_of, fresh_for=timedelta(minutes=30))`, which is
what makes a stale price visibly stale rather than silently wrong.

- [ ] **Step 4: Run tests, regenerate types, commit**

```bash
python -m pytest -q && ruff check . && mypy src
cd web && npm run gen:api && cd ..
git add src docs/web tests
git commit -m "feat(research): wire technicals, news, and sentiment into the analysis payload"
```

---

## Task 4.5 — Price chart `[GLM]`

**Files:** Create `web/components/stock/PriceChart.tsx`, and
`GET /research/{symbol}/bars` in `src/api/routers/research.py`.
Test: `tests/test_api_bars.py`.

**Interfaces:**
- `GET /research/{symbol}/bars?range=1y` returns
  `{as_of, bars: [{time: "YYYY-MM-DD", open, high, low, close, volume}]}` — `time` is
  lightweight-charts' expected field name, so no client-side remapping is needed.

Chart rules from the spec, all mandatory:
- `lightweight-charts` candlestick series plus a volume histogram.
- SMA 50 and SMA 200 overlays computed **server-side** from `daily_bars`, so the chart and the
  technical panel can never disagree.
- **No entry animation on the data.** An animation delays reading a number.
- Colours come from the semantic tokens (`--color-gain`, `--color-loss`), read from CSS custom
  properties at mount, never hard-coded hex.
- The chart container is `overflow-x: auto` so the page body never scrolls horizontally.

- [ ] Write the endpoint test, implement the endpoint, then the component. Verify the chart
  renders a year of AAPL bars with both moving averages. Commit.

---

## Task 4.6 — Technicals, news, and sentiment panels `[GLM]`

**Files:** Create `web/components/stock/TechnicalsPanel.tsx`,
`web/components/stock/NewsPanel.tsx`, `web/components/stock/SentimentPanel.tsx`.
Test each with React Testing Library.

Required behaviours, each with its own test:
- `TechnicalsPanel` shows RSI 14, MACD, SMA 50 and 200, ATR, and the phase and regime badges.
  A `null` metric renders `n/a` in `text-unknown`, never `0`.
- `NewsPanel` lists headlines newest first with a relative age, links out with
  `rel="noopener noreferrer"`, and shows per-item sentiment as a small labelled chip that is
  **not colour-only** (label plus tint).
- `SentimentPanel` shows the composite score, its label, the 1-day delta, and **the sample
  count for each source**. A source with a score and no sample count is not trustworthy, and
  the count is what tells the reader that.
- Every panel is wrapped in `SectionShell` so pending and unavailable states are consistent.

- [ ] Write the tests, implement, run `npx vitest run && npm run build && npm run lint`, commit.

---

## Task 4.7 — Per-provider circuit breaker `[SONNET]`

Sonnet: a judgment call about degradation, and a breaker that opens too eagerly is worse than
none.

**Spec:** §5.6. There are now four external providers (EDGAR, stooq, yfinance prices, yfinance
news) and a provider having a bad hour should stop us hammering it, without taking the page down.

**Files:** Create `src/data/breaker.py`. Modify `src/data/edgar_backend.py`,
`src/data/stooq_backend.py`. Modify `src/api/routers/meta.py` (report breaker state on
`/health`). Test `tests/test_provider_breaker.py`.

**Interfaces:**
- Produces:
  - `CircuitBreaker(name: str, threshold: int = 3, cooldown_seconds: float = 300.0)`
  - `.allow() -> bool`, `.record_success() -> None`, `.record_failure() -> None`
  - `.state -> "closed" | "open" | "half_open"`
  - `get_breaker(name: str) -> CircuitBreaker` (process-wide registry)
  - `breaker_states() -> dict[str, str]` for `/health`

Mirrors the existing `market_data.max_consecutive_chain_timeouts` pattern: consecutive failures
open the circuit, not a failure rate.

- [ ] **Step 1: Write the failing test**

```python
"""Consecutive failures open a provider's circuit; one success closes it."""

from __future__ import annotations

import time

from src.data.breaker import CircuitBreaker


def test_starts_closed_and_allows() -> None:
    b = CircuitBreaker("edgar", threshold=3)
    assert b.state == "closed"
    assert b.allow() is True


def test_opens_after_consecutive_failures() -> None:
    b = CircuitBreaker("edgar", threshold=3, cooldown_seconds=60)
    for _ in range(3):
        b.record_failure()
    assert b.state == "open"
    assert b.allow() is False


def test_a_success_resets_the_failure_run() -> None:
    """Consecutive, not cumulative. An intermittent failure must not accumulate forever."""
    b = CircuitBreaker("edgar", threshold=3, cooldown_seconds=60)
    b.record_failure()
    b.record_failure()
    b.record_success()
    b.record_failure()
    assert b.state == "closed"


def test_it_half_opens_after_the_cooldown() -> None:
    b = CircuitBreaker("edgar", threshold=1, cooldown_seconds=0.01)
    b.record_failure()
    assert b.allow() is False
    time.sleep(0.02)
    assert b.allow() is True
    assert b.state == "half_open"


def test_a_success_while_half_open_closes_it() -> None:
    b = CircuitBreaker("edgar", threshold=1, cooldown_seconds=0.01)
    b.record_failure()
    time.sleep(0.02)
    b.allow()
    b.record_success()
    assert b.state == "closed"


def test_a_failure_while_half_open_reopens_it() -> None:
    b = CircuitBreaker("edgar", threshold=1, cooldown_seconds=0.01)
    b.record_failure()
    time.sleep(0.02)
    b.allow()
    b.record_failure()
    assert b.state == "open"
```

- [ ] **Step 2: Implement, and wire it into both HTTP clients.** When `allow()` is false, the
  client returns its documented empty value immediately (empty dict, empty frame) **without a
  network call**, so an open circuit costs nothing. The affected section renders as
  `UNAVAILABLE` with the reason "Data provider temporarily unavailable", and every other
  section on the page still renders.

- [ ] **Step 3: Report breaker state on `/health`** as `providers: {edgar: "closed", ...}`, and
  add a test asserting an open breaker makes `/health` report `degraded`.

- [ ] **Step 4: Run tests, commit.**

```bash
git add src/data src/api tests/test_provider_breaker.py
git commit -m "feat(data): add per-provider circuit breakers surfaced on /health"
```

---

## Milestone 4 exit criteria

- [ ] Full Python and web gates green
- [ ] `docs/web/data-sources.md` records the licence verdict with a date
- [ ] `/stock/AAPL` shows a year of candles with SMA 50 and 200, technical panels, news with
      per-item sentiment, and a delayed quote with its age
- [ ] A forced sentiment outage leaves every other section rendering
- [ ] No metric renders `0` when the underlying value is `None`
