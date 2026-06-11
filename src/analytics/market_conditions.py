"""Market-level conditions: VIX and related signals.

Fetched once per scan (not per-symbol) and passed through the pipeline
as a MarketConditions snapshot.
"""

from __future__ import annotations

import logging

from src.common.schemas import MarketConditions

log = logging.getLogger(__name__)


def get_market_conditions() -> MarketConditions:
    """Fetch current market-level conditions via yfinance.

    Returns a MarketConditions with vix=None on any failure — callers must
    handle None gracefully.
    """
    vix = _fetch_vix()
    return MarketConditions(vix=vix)


def _fetch_vix() -> float | None:
    """Return the current CBOE VIX level from yfinance ^VIX."""
    try:
        import yfinance as yf

        ticker = yf.Ticker("^VIX")
        info = ticker.fast_info
        price = getattr(info, "last_price", None)
        if price is not None and float(price) > 0:
            return round(float(price), 2)
        # Fallback: last close from history
        hist = ticker.history(period="1d")
        if not hist.empty:
            return round(float(hist["Close"].iloc[-1]), 2)
    except Exception as exc:
        log.warning("get_vix: failed — %s", exc)
    return None
