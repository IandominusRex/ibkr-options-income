"""FMP (Financial Modeling Prep) provider stubs.

Documents the future swap path away from yfinance. **Not wired in Phase 2** — every method
raises :class:`NotImplementedError` so no accidental swap path exists. The *interface* is
the deliverable: a future FMP/Polygon integration is a new backend implementing the
Protocols in :mod:`src.data.protocols` plus a factory branch reading
``config/settings.yaml → data.*``.

IBKR is *not* a provider — it is the broker + execution path (``src/ibkr/``) and stays
untouched. FMP covers only the keyless external reads (prices, fundamentals, news) that
yfinance provides today.
"""

from __future__ import annotations

import pandas as pd


class FMPPriceProvider:
    """``PriceProvider`` stub for a future FMP backend. Not implemented in Phase 2."""

    def get_ohlcv(self, symbol: str, lookback_days: int = 365) -> pd.DataFrame:
        raise NotImplementedError("FMP price provider is not wired in Phase 2")

    def get_last_price(self, symbol: str) -> float | None:
        raise NotImplementedError("FMP price provider is not wired in Phase 2")


class FMPFundamentalsProvider:
    """``FundamentalsProvider`` stub for a future FMP backend. Not implemented in Phase 2."""

    def get_info(self, symbol: str) -> dict:
        raise NotImplementedError("FMP fundamentals provider is not wired in Phase 2")

    def get_calendar(self, symbol: str) -> dict:
        raise NotImplementedError("FMP fundamentals provider is not wired in Phase 2")


class FMPNewsProvider:
    """``NewsProvider`` stub for a future FMP backend. Not implemented in Phase 2."""

    def get_headlines(self, symbol: str, limit: int = 50) -> list[dict]:
        raise NotImplementedError("FMP news provider is not wired in Phase 2")
