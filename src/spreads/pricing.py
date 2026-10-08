"""Black-Scholes with fractional-year time, and the ET clock — for same-day options.

``src.analytics.black_scholes`` takes integer calendar DTE and returns ``None`` at 0 DTE, which
is exactly the regime this system trades, so the spreads package carries its own. Pure math.
"""

from __future__ import annotations

import math
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from scipy.stats import norm

ET = ZoneInfo("America/New_York")
_YEAR_SECONDS = 365.0 * 24 * 3600
MIN_T = 60.0 / _YEAR_SECONDS  # one minute — keeps gamma finite at the bell


def years_to_close(now: datetime, expiry: date, close: time = time(16, 0)) -> float:
    """Calendar-time years from *now* (aware) to *expiry*'s close, floored at zero."""
    expiry_dt = datetime.combine(expiry, close, tzinfo=ET)
    return max((expiry_dt - now.astimezone(ET)).total_seconds(), 0.0) / _YEAR_SECONDS


def _d1(spot: float, strike: float, t: float, iv: float, r: float) -> float:
    return (math.log(spot / strike) + (r + 0.5 * iv * iv) * t) / (iv * math.sqrt(t))


def gamma(spot: float, strike: float, t: float, iv: float, r: float = 0.0) -> float:
    if spot <= 0 or strike <= 0 or iv <= 0:
        return 0.0
    t = max(t, MIN_T)
    return float(norm.pdf(_d1(spot, strike, t, iv, r))) / (spot * iv * math.sqrt(t))


def delta(spot: float, strike: float, t: float, iv: float, right: str, r: float = 0.0) -> float:
    if spot <= 0 or strike <= 0 or iv <= 0:
        return 0.0
    t = max(t, MIN_T)
    nd1 = float(norm.cdf(_d1(spot, strike, t, iv, r)))
    return nd1 if right == "C" else nd1 - 1.0


def price(spot: float, strike: float, t: float, iv: float, right: str, r: float = 0.0) -> float:
    intrinsic = max(spot - strike, 0.0) if right == "C" else max(strike - spot, 0.0)
    if t <= 0 or iv <= 0 or spot <= 0 or strike <= 0:
        return intrinsic
    d1 = _d1(spot, strike, t, iv, r)
    d2 = d1 - iv * math.sqrt(t)
    disc = math.exp(-r * t)
    if right == "C":
        return spot * float(norm.cdf(d1)) - strike * disc * float(norm.cdf(d2))
    return strike * disc * float(norm.cdf(-d2)) - spot * float(norm.cdf(-d1))


def implied_vol(
    target: float | None,
    spot: float,
    strike: float,
    t: float,
    right: str,
    r: float = 0.0,
    *,
    lo: float = 0.01,
    hi: float = 5.0,
    tol: float = 1e-6,
    max_iter: int = 200,
) -> float | None:
    """Bisection IV. None when *target* is outside the [lo, hi]-vol price range."""
    if target is None or t <= 0 or spot <= 0 or strike <= 0:
        return None
    if target < price(spot, strike, t, lo, right, r) - tol:
        return None
    if target > price(spot, strike, t, hi, right, r) + tol:
        return None
    a, b = lo, hi
    for _ in range(max_iter):
        m = (a + b) / 2
        if price(spot, strike, t, m, right, r) < target:
            a = m
        else:
            b = m
        if b - a < tol:
            break
    return (a + b) / 2
