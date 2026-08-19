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

log = logging.getLogger(__name__)


def _period_for_lookback(lookback_days: int) -> str:
    """Smallest yfinance period that covers *lookback_days* calendar days.

    Mirrors the previous ``price_data._period_for_gap`` mapping so the wrapped fetch
    requests exactly the same yfinance period the old direct call did.
    """
    if lookback_days <= 5:
        return "5d"
    if lookback_days <= 25:
        return "1mo"
    if lookback_days <= 80:
        return "3mo"
    if lookback_days <= 170:
        return "6mo"
    return "1y"


class YFinancePriceProvider:
    """``PriceProvider`` backed by yfinance's ``Ticker.history`` and ``fast_info``."""

    def get_ohlcv(self, symbol: str, lookback_days: int = 365) -> pd.DataFrame:
        """Daily OHLCV history for *symbol*.

        Returns yfinance's ``Ticker(symbol).history(period=...)`` frame (ascending, today's
        forming bar included). Callers that want only settled bars exclude today themselves
        (``price_data`` does this before persisting). Empty DataFrame on failure.
        """
        try:
            period = _period_for_lookback(lookback_days)
            df = yf.Ticker(symbol).history(period=period)
        except Exception:
            log.warning("yfinance_backend: history failed for %s", symbol, exc_info=True)
            return pd.DataFrame()
        if df is None:
            return pd.DataFrame()
        return df

    def get_last_price(self, symbol: str) -> float | None:
        """Cheap live quote via yfinance ``fast_info`` — NOT cached, stays current."""
        try:
            last = yf.Ticker(symbol).fast_info["lastPrice"]
            return float(last) if last is not None else None
        except Exception:
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


class YFinanceNewsProvider:
    """``NewsProvider`` backed by yfinance's ``Ticker.news``."""

    def get_headlines(self, symbol: str, limit: int = 50) -> list[dict]:
        """Recent news items for *symbol* (newest first). Empty list on failure.

        yfinance's ``Ticker.news`` already returns newest-first and has no server-side
        ``limit``; *limit* is honoured client-side by truncating the returned list, so the
        shape matches what the existing direct call produced when the caller took all items.
        """
        try:
            items = yf.Ticker(symbol.upper()).news or []
        except Exception:
            return []
        if limit > 0:
            items = items[:limit]
        return items
