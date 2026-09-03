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
