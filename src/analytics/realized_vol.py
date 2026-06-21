"""Close-to-close annualized historical volatility over a configurable window.

Separate from the HV30 helper in iv.py so callers can request any window length
and the computation can be patched independently in tests.
"""

from __future__ import annotations

import logging
import math

from src.analytics.price_data import get_ohlcv

log = logging.getLogger(__name__)


def compute_realized_vol(symbol: str, window: int = 20) -> float | None:
    """Annualized close-to-close historical volatility over *window* trading days.

    Uses the same shared OHLCV store as HV30 and the technicals layer (get_ohlcv),
    so no additional yfinance fetch is required after the first call per session.

    Returns None when there is insufficient history (< window + 1 settled bars)
    or when the computation fails — callers must treat None as "data unavailable"
    and not block on it.
    """
    try:
        df = get_ohlcv(symbol)
        if df.empty or len(df) < window + 1:
            log.debug(
                "realized_vol: insufficient history for %s (need %d, have %d)",
                symbol,
                window + 1,
                len(df),
            )
            return None
        pct = (df["Close"] / df["Close"].shift(1)).apply(math.log).dropna()
        rv = pct.rolling(window).std().iloc[-1] * math.sqrt(252) * 100
        result = float(rv)
        return round(result, 4) if math.isfinite(result) else None
    except Exception as exc:
        log.warning("realized_vol: failed for %s (window=%d): %s", symbol, window, exc)
        return None
