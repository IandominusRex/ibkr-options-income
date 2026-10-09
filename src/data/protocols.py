"""Provider Protocols — the interface every data backend must implement.

These are :class:`typing.Protocol` classes (structural subtyping): a backend satisfies a
Protocol by implementing its methods, with no inheritance declaration. The
yfinance backend in :mod:`src.data.yfinance_backend` and the FMP stub in
:mod:`src.data.fmp_backend` both implement these Protocols.

The Protocols intentionally return the *same* shapes the existing yfinance call sites
already consume (``pd.DataFrame`` for OHLCV, ``dict`` for info/calendar, ``list[dict]``
for news items) — wrapping the existing code, not redesigning its output. A backend
swap is therefore a config change (``config/settings.yaml → data.*``), not a rewrite of
every analytics module.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Protocol, runtime_checkable

import pandas as pd
from pydantic import BaseModel


@runtime_checkable
class PriceProvider(Protocol):
    """Daily OHLCV history and a cheap live quote for a symbol (or index)."""

    def get_ohlcv(self, symbol: str, lookback_days: int = 365) -> pd.DataFrame:
        """Return settled daily OHLCV (Open/High/Low/Close/Volume) for *symbol*.

        Ascending by date, the current forming session excluded — callers overlay the
        live price themselves. Returns an empty DataFrame when no history is available.
        ``lookback_days`` is a hint; backends may return more or fewer bars if the
        underlying API works in fixed periods (yfinance uses ``1y``/``3mo`` etc.).
        """
        ...

    def get_last_price(self, symbol: str) -> float | None:
        """Cheap live quote (e.g. yfinance ``fast_info["lastPrice"]``).

        NOT cached — callers fetch this fresh so the scan-time spot stays current.
        Returns None when the quote is unavailable.
        """
        ...


@runtime_checkable
class FundamentalsProvider(Protocol):
    """Per-symbol fundamentals: the ``info`` dict and the earnings ``calendar`` dict."""

    def get_info(self, symbol: str) -> dict:
        """Return yfinance's ``Ticker(symbol).info`` dict (or the backend's equivalent).

        Empty dict when unavailable. Never raises.
        """
        ...

    def get_calendar(self, symbol: str) -> dict:
        """Return yfinance's ``Ticker(symbol).calendar`` dict (or equivalent).

        Empty dict when unavailable. Never raises.
        """
        ...


@runtime_checkable
class NewsProvider(Protocol):
    """Recent news headlines for a symbol (keyless)."""

    def get_headlines(self, symbol: str, limit: int = 50) -> list[dict]:
        """Return recent news items for *symbol*, newest first.

        Each item is the raw dict yfinance returns (either the legacy flat shape with a
        ``title`` key, or the newer ``{"content": {...}}`` nesting — callers handle both).
        Empty list when unavailable. Never raises.
        """
        ...


class NewsItem(BaseModel):
    """One free-text news headline — from Google News RSS search or yfinance's per-symbol
    headlines (see :class:`NewsSearchProvider` / :class:`NewsProvider`).

    ``id`` is empty as returned by a provider; :func:`src.claude.news_context.build_news_block`
    assigns the prompt-facing ``N1``, ``N2``, ... ids when it renders items into the ``=== NEWS
    ===`` block.
    """

    id: str = ""
    title: str
    source: str | None = None
    published: datetime | None = None
    url: str | None = None
    summary: str | None = None  # plain-text teaser (Finnhub/RSS); never HTML
    image_url: str | None = None  # article image when the source supplies one


@runtime_checkable
class NewsSearchProvider(Protocol):
    """Keyless free-text news search (vs :class:`NewsProvider`'s per-symbol headlines).

    Backs the Task 11 "news-grounded review": a static ``=== NEWS ===`` block built from
    recent headlines, plus the bounded tool-calling research turn
    (:mod:`src.claude.ollama_tools`) that lets the local reviewer search for more. Enrichment
    tier only — never reaches ``src/engine/``, ``src/execution/``, or ``src/strategies/`` (see
    ``tests/test_eval_skills.py``).
    """

    def search(self, query: str, *, days: int = 7, limit: int = 10) -> list[NewsItem]:
        """Return recent news items matching *query*, newest first.

        Empty list on any failure (network, parse, rate limit). Never raises.
        """
        ...


class SymbolRecord(BaseModel):
    """One row of the symbol directory. ``cik`` is zero-padded to 10 digits."""

    symbol: str
    cik: str
    name: str = ""
    exchange: str | None = None


@runtime_checkable
class SymbolDirectoryProvider(Protocol):
    """The full list of listed US filers: ticker, CIK, name, exchange.

    A backend satisfies this Protocol by implementing ``list_symbols`` — no inheritance
    declaration needed. The EDGAR backend in :mod:`src.data.edgar_backend` is the first
    implementation; a future FMP/Polygon swap is a config change
    (``config/settings.yaml → data.symbol_directory_provider``).
    """

    def list_symbols(self) -> list[SymbolRecord]:
        """Return every symbol the backend knows about.

        Empty list when unavailable. Never raises.
        """
        ...


@runtime_checkable
class FilingsProvider(Protocol):
    """XBRL company facts for one filer, keyed by CIK."""

    def get_company_facts(self, cik: str, *, etag: str | None = None) -> tuple[dict, str | None]:
        """Return the backend's full XBRL fact document for *cik*.

        Returns ``(payload, etag)``. ``payload`` is an empty dict when unavailable
        (no XBRL, 404, throttled, or 304 Not Modified). ``etag`` is the response's
        ETag when a fresh payload was returned, or the *input* etag when a 304
        meant the caller's cached payload is still current. Never raises.
        """
        ...


@runtime_checkable
class BulkPriceProvider(Protocol):
    """Daily OHLCV for the cold tier, where a keyed per-symbol API would be too expensive.

    Distinct from :class:`PriceProvider`: the cold tier serves any US ticker on first view,
    so a free bulk source is what makes the economics work. stooq was the plan's first
    choice but the 4.1 licence gate ruled it out (see ``docs/web/data-sources.md``); yfinance
    is the only backend today. The Protocol is what the rest of the system depends on, so a
    future source is a config change (``data.bulk_price_provider``), not a rewrite.
    """

    def get_daily_bars(self, symbol: str, lookback_days: int = 400) -> pd.DataFrame:
        """Ascending daily OHLCV with a ``DatetimeIndex`` and the columns
        ``Open, High, Low, Close, Volume``. Empty frame when unavailable. Never raises.
        """
        ...


class FeedFetch(BaseModel):
    """One conditional-GET of a feed. ``not_modified`` = HTTP 304 (keep the stored validators)."""

    items: list[NewsItem]
    etag: str | None = None
    last_modified: str | None = None
    not_modified: bool = False


@runtime_checkable
class FeedProvider(Protocol):
    """RSS/Atom feeds with HTTP conditional requests. Never raises."""

    def fetch(
        self,
        url: str,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
        limit: int = 50,
    ) -> FeedFetch: ...


class EconScheduleItem(BaseModel):
    """A scheduled economic release (ForexFactory). ``scheduled_at`` is tz-aware."""

    title: str
    country: str
    scheduled_at: datetime
    impact: str  # High | Medium | Low | Holiday | Non-Economic
    forecast: str | None = None
    previous: str | None = None


class EconActualItem(BaseModel):
    """A released (or scheduled) value from Nasdaq's economic calendar, US rows only.

    ``et_day``/``et_time`` are the US Eastern date and HH:MM the release belongs to, after the
    backend's D+1 correction (spec §5.1). ``et_time`` is None for untimed rows.
    """

    title: str
    et_day: date
    et_time: str | None = None
    actual: str | None = None
    consensus: str | None = None
    previous: str | None = None


@runtime_checkable
class EconScheduleProvider(Protocol):
    def this_week(self) -> list[EconScheduleItem]: ...


@runtime_checkable
class EconActualsProvider(Protocol):
    def actuals(self, et_day: date) -> list[EconActualItem]: ...


class EarningsItem(BaseModel):
    symbol: str
    report_date: date
    timing: str = "unknown"  # bmo | amc | unknown
    eps_est: float | None = None
    eps_actual: float | None = None
    rev_est: float | None = None
    rev_actual: float | None = None
    source: str = ""


@runtime_checkable
class EarningsCalendarProvider(Protocol):
    def on(self, et_day: date) -> list[EarningsItem]: ...


@runtime_checkable
class IntradayPriceProvider(Protocol):
    """Intraday bars incl. pre/post market. Index is tz-aware; columns Open/High/Low/Close/Volume.
    Empty DataFrame when unavailable. Never raises."""

    def get_intraday(self, symbol: str, *, interval: str = "1m", days: int = 1) -> pd.DataFrame: ...
