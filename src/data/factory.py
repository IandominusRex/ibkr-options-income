"""Process-wide factories for the data provider backends.

Read ``config/settings.yaml → data.*`` to pick the active backend for each of the three
Protocols (price / fundamentals / news), instantiate it, and cache the instance for the
life of the process. Analytics/strategies/engine call ``get_price_provider()`` etc. —
never ``yfinance.*`` directly — so a future FMP/Polygon swap is a config change.

The cache is module-level (a single instance per backend per process). Tests that need to
swap a backend monkeypatch the factory directly (or ``get_config.cache_clear()`` after
editing the YAML).
"""

from __future__ import annotations

import functools

from src.common.config import get_config
from src.data.protocols import (
    FundamentalsProvider,
    NewsProvider,
    PriceProvider,
    SymbolDirectoryProvider,
)
from src.data.yfinance_backend import (
    YFinanceFundamentalsProvider,
    YFinanceNewsProvider,
    YFinancePriceProvider,
)


def _make_price_provider(name: str) -> PriceProvider:
    if name == "yfinance":
        return YFinancePriceProvider()
    if name == "fmp":
        from src.data.fmp_backend import FMPPriceProvider

        return FMPPriceProvider()
    raise ValueError(f"Unknown data.price_provider backend: {name!r}")


def _make_fundamentals_provider(name: str) -> FundamentalsProvider:
    if name == "yfinance":
        return YFinanceFundamentalsProvider()
    if name == "fmp":
        from src.data.fmp_backend import FMPFundamentalsProvider

        return FMPFundamentalsProvider()
    raise ValueError(f"Unknown data.fundamentals_provider backend: {name!r}")


def _make_news_provider(name: str) -> NewsProvider:
    if name == "yfinance":
        return YFinanceNewsProvider()
    if name == "fmp":
        from src.data.fmp_backend import FMPNewsProvider

        return FMPNewsProvider()
    raise ValueError(f"Unknown data.news_provider backend: {name!r}")


@functools.lru_cache(maxsize=1)
def get_price_provider() -> PriceProvider:
    """Return the active :class:`PriceProvider` (cached process-wide)."""
    return _make_price_provider(get_config().data.price_provider)


@functools.lru_cache(maxsize=1)
def get_fundamentals_provider() -> FundamentalsProvider:
    """Return the active :class:`FundamentalsProvider` (cached process-wide)."""
    return _make_fundamentals_provider(get_config().data.fundamentals_provider)


@functools.lru_cache(maxsize=1)
def get_news_provider() -> NewsProvider:
    """Return the active :class:`NewsProvider` (cached process-wide)."""
    return _make_news_provider(get_config().data.news_provider)


def _make_symbol_directory_provider(name: str) -> SymbolDirectoryProvider:
    if name == "edgar":
        from src.data.edgar_backend import EdgarSymbolDirectoryProvider

        return EdgarSymbolDirectoryProvider()
    raise ValueError(f"Unknown data.symbol_directory_provider backend: {name!r}")


@functools.lru_cache(maxsize=1)
def get_symbol_directory_provider() -> SymbolDirectoryProvider:
    """Return the active :class:`SymbolDirectoryProvider` (cached process-wide)."""
    return _make_symbol_directory_provider(get_config().data.symbol_directory_provider)
