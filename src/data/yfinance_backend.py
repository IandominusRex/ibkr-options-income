"""The active data backend: yfinance.

Each method wraps the exact yfinance call the analytics layer used to make directly
(``yf.Ticker(symbol).info``, ``yf.Ticker(symbol).history(period=...)``,
``yf.Ticker(symbol).news``, ``yf.Ticker(symbol).fast_info["lastPrice"]``). **No behaviour
change** — the wrapper is the existing code in a class. Swapping to FMP/Polygon is a
config change (``config/settings.yaml → data.*``), not a rewrite of every analytics module.
"""

from __future__ import annotations

import logging

import pandas as pd
import yfinance as yf

from src.data.breaker import get_breaker

log = logging.getLogger(__name__)


def _period_for_lookback(lookback_days: int) -> str:
    """Smallest yfinance period that covers *lookback_days* calendar days.

    The <=365 buckets mirror the previous ``price_data._period_for_gap`` mapping, which no
    caller has ever exceeded, so the wrapped fetch requests exactly the same yfinance period
    the old direct call did. The >365 buckets exist for ``BulkPriceProvider`` (Task 4.1),
    whose documented default is ``lookback_days=400`` — without them, every request past a
    year silently fell back to yfinance's "1y" period and never actually delivered the
    requested lookback.
    """
    if lookback_days <= 5:
        return "5d"
    if lookback_days <= 25:
        return "1mo"
    if lookback_days <= 80:
        return "3mo"
    if lookback_days <= 170:
        return "6mo"
    if lookback_days <= 365:
        return "1y"
    if lookback_days <= 730:
        return "2y"
    return "5y"


class YFinancePriceProvider:
    """``PriceProvider`` backed by yfinance's ``Ticker.history`` and ``fast_info``."""

    def get_ohlcv(self, symbol: str, lookback_days: int = 365) -> pd.DataFrame:
        """Daily OHLCV history for *symbol*.

        Returns yfinance's ``Ticker(symbol).history(period=...)`` frame (ascending, today's
        forming bar included). Callers that want only settled bars exclude today themselves
        (``price_data`` does this before persisting). Empty DataFrame on failure.
        """
        breaker = get_breaker("yfinance_prices")
        if not breaker.allow():
            return pd.DataFrame()
        try:
            period = _period_for_lookback(lookback_days)
            df = yf.Ticker(symbol).history(period=period)
        except Exception:
            log.warning("yfinance_backend: history failed for %s", symbol, exc_info=True)
            breaker.record_failure()
            return pd.DataFrame()
        if df is None:
            breaker.record_failure()
            return pd.DataFrame()
        breaker.record_success()
        return df

    def get_last_price(self, symbol: str) -> float | None:
        """Cheap live quote via yfinance ``fast_info`` — NOT cached, stays current."""
        breaker = get_breaker("yfinance_prices")
        if not breaker.allow():
            return None
        try:
            last = yf.Ticker(symbol).fast_info["lastPrice"]
            if last is None:
                breaker.record_success()
                return None
            breaker.record_success()
            return float(last)
        except Exception:
            breaker.record_failure()
            return None


class YFinanceFundamentalsProvider:
    """``FundamentalsProvider`` backed by yfinance's ``Ticker.info`` and ``Ticker.calendar``."""

    def get_info(self, symbol: str) -> dict:
        """``yf.Ticker(symbol).info`` (or empty dict on failure). Never raises."""
        try:
            return yf.Ticker(symbol).info or {}
        except Exception:
            return {}

    def get_calendar(self, symbol: str) -> dict:
        """``yf.Ticker(symbol).calendar`` (or empty dict on failure). Never raises."""
        try:
            cal = yf.Ticker(symbol).calendar
            return cal or {}
        except Exception:
            return {}


class YFinanceBulkPriceProvider:
    """``BulkPriceProvider`` backed by yfinance's ``Ticker.history``.

    The cold tier's only backend: the 4.1 licence gate ruled stooq out (see
    ``docs/web/data-sources.md``). Wraps the existing :class:`YFinancePriceProvider` so
    the :class:`BulkPriceProvider` Protocol is satisfied; a future bulk source is a
    config change (``data.bulk_price_provider``), not a rewrite.
    """

    def __init__(self, *, provider: YFinancePriceProvider | None = None) -> None:
        self._provider = provider or YFinancePriceProvider()

    def get_daily_bars(self, symbol: str, lookback_days: int = 400) -> pd.DataFrame:
        df = self._provider.get_ohlcv(symbol, lookback_days=lookback_days)
        if df is None or df.empty:
            return pd.DataFrame(
                columns=["Open", "High", "Low", "Close", "Volume"],
                index=pd.DatetimeIndex([], name="Date"),
            )
        # yfinance returns a DatetimeIndex already; ensure the name is set so the
        # shape matches the BulkPriceProvider Protocol's documented contract.
        df.index.name = "Date"
        return df


class YFinanceNewsProvider:
    """``NewsProvider`` backed by yfinance's ``Ticker.news``."""

    def get_headlines(self, symbol: str, limit: int = 50) -> list[dict]:
        """Recent news items for *symbol* (newest first). Empty list on failure.

        yfinance's ``Ticker.news`` already returns newest-first and has no server-side
        ``limit``; *limit* is honoured client-side by truncating the returned list, so the
        shape matches what the existing direct call produced when the caller took all items.
        """
        breaker = get_breaker("yfinance_news")
        if not breaker.allow():
            return []
        try:
            items = yf.Ticker(symbol.upper()).news or []
        except Exception:
            breaker.record_failure()
            return []
        breaker.record_success()
        if limit > 0:
            items = items[:limit]
        return items
