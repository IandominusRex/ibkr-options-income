"""Liquidity scoring and gate checks for option quotes.

Pure math on OptionQuote objects — no external calls, no DB access.
Thresholds are read from config/risk_limits.yaml via get_config().
"""

from __future__ import annotations

import math

from src.common.config import get_config
from src.common.schemas import OptionQuote


def passes_liquidity_gates(quote: OptionQuote) -> bool:
    """Return True iff the quote clears all three liquidity hard gates.

    Any None field fails its gate (conservative default).
    """
    cfg = get_config().risk["liquidity"]
    max_spread = cfg["max_bid_ask_spread_pct"]
    min_oi = cfg["min_open_interest"]
    min_vol = cfg["min_option_volume"]

    spread = quote.spread_pct
    if spread is None or spread > max_spread:
        return False

    oi = quote.open_interest
    if oi is None or oi < min_oi:
        return False

    vol = quote.volume
    if vol is None or vol < min_vol:
        return False

    return True


def score_liquidity(quote: OptionQuote) -> float:
    """Return a 0–100 liquidity score (higher is better).

    Averages three sub-scores: spread, open interest, and volume.
    None values are treated as 0 (penalise missing data).
    """
    cfg = get_config().risk["liquidity"]
    max_spread: float = cfg["max_bid_ask_spread_pct"]

    spread = quote.spread_pct
    spread_score = max(0.0, 100.0 - (spread / max_spread) * 100.0) if spread is not None else 0.0

    oi = quote.open_interest
    # Log-scale so high-liquidity options (OI 50k+) score distinctly better than barely-passing ones.
    # log10(1 + oi/10) normalized so OI=1000 ≈ 70, OI=10000 ≈ 85, OI=100000 ≈ 100.
    oi_score = (
        min(100.0, math.log10(1 + (oi or 0) / 10) / math.log10(1001) * 100.0)
        if oi is not None
        else 0.0
    )

    vol = quote.volume
    vol_score = (
        min(100.0, math.log10(1 + (vol or 0)) / math.log10(101) * 100.0) if vol is not None else 0.0
    )

    return round((spread_score + oi_score + vol_score) / 3.0, 2)
