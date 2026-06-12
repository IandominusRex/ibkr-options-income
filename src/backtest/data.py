"""Historical price loader for the backtest harness (yfinance).

Isolated from `engine.py` so the simulation core stays pure and unit-testable without a network.
"""

from __future__ import annotations

from datetime import date

import yfinance as yf

from src.common.logging import get_logger

log = get_logger(__name__)


def load_price_series(
    symbol: str,
    start: date | None = None,
    end: date | None = None,
    period: str = "2y",
) -> list[tuple[date, float]]:
    """Return ascending ``(date, close)`` daily closes for ``symbol``.

    Uses an explicit ``start``/``end`` window when given, else the rolling ``period``. Returns an
    empty list (never raises) when the fetch fails or the symbol has no history.
    """
    try:
        ticker = yf.Ticker(symbol)
        if start is not None:
            df = ticker.history(start=start.isoformat(), end=end.isoformat() if end else None)
        else:
            df = ticker.history(period=period)
        if df.empty:
            log.warning("backtest: no price history for %s", symbol)
            return []
        return [(idx.date(), float(close)) for idx, close in zip(df.index, df["Close"], strict=False)]
    except Exception as exc:
        log.warning("backtest: price load failed for %s: %s", symbol, exc)
        return []
