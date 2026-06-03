"""Black-Scholes delta — pure math, no IBKR connection required.

Used as a fallback when IBKR model Greeks are unavailable (delayed-data paper accounts).
"""

from __future__ import annotations

import math

from scipy.stats import norm


def bs_delta(
    spot: float,
    strike: float,
    dte: int,
    iv: float,
    right: str,
    r: float = 0.05,
) -> float | None:
    """Black-Scholes delta for a European option.

    Args:
        spot:   Underlying spot price.
        strike: Option strike price.
        dte:    Days to expiration (calendar days).
        iv:     Implied volatility as a decimal fraction (0.30 = 30 %).
        right:  "C" for call, "P" for put.
        r:      Risk-free rate as a decimal fraction (default 5 %).

    Returns:
        Delta in [0, 1] for calls and [-1, 0] for puts, or None on degenerate inputs.
    """
    if spot <= 0 or strike <= 0 or dte <= 0 or iv <= 0:
        return None
    t = dte / 365.0
    try:
        d1 = (math.log(spot / strike) + (r + 0.5 * iv * iv) * t) / (iv * math.sqrt(t))
    except (ValueError, ZeroDivisionError):
        return None
    if right == "C":
        return float(norm.cdf(d1))
    return float(norm.cdf(d1) - 1.0)
