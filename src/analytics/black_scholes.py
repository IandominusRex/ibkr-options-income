"""Black-Scholes delta and price — pure math, no IBKR connection required.

`bs_delta` is used as a fallback when IBKR model Greeks are unavailable (delayed-data paper
accounts). `bs_price` is used by the offline backtest harness to value synthetic option
premiums from historical price/volatility (the system has no historical option-chain source).
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


def bs_price(
    spot: float,
    strike: float,
    dte: int,
    iv: float,
    right: str,
    r: float = 0.05,
) -> float | None:
    """Black-Scholes price (per share) for a European option.

    Args mirror :func:`bs_delta`. Returns the theoretical premium per share (×100 for a
    contract), or None on degenerate inputs. The result is floored at 0.
    """
    if spot <= 0 or strike <= 0 or dte <= 0 or iv <= 0:
        return None
    t = dte / 365.0
    try:
        sqrt_t = math.sqrt(t)
        d1 = (math.log(spot / strike) + (r + 0.5 * iv * iv) * t) / (iv * sqrt_t)
    except (ValueError, ZeroDivisionError):
        return None
    d2 = d1 - iv * sqrt_t
    discount = math.exp(-r * t)
    if right == "C":
        price = spot * float(norm.cdf(d1)) - strike * discount * float(norm.cdf(d2))
    else:
        price = strike * discount * float(norm.cdf(-d2)) - spot * float(norm.cdf(-d1))
    return max(price, 0.0)


def bs_gamma(
    spot: float,
    strike: float,
    dte: int,
    iv: float,
    right: str,
    r: float = 0.05,
) -> float | None:
    """Black-Scholes gamma for a European option.

    Returns the second derivative of price w.r.t. spot. Positive for both calls and puts.
    """
    if spot <= 0 or strike <= 0 or dte <= 0 or iv <= 0:
        return None
    t = dte / 365.0
    try:
        sqrt_t = math.sqrt(t)
        d1 = (math.log(spot / strike) + (r + 0.5 * iv * iv) * t) / (iv * sqrt_t)
    except (ValueError, ZeroDivisionError):
        return None
    # gamma = N'(d1) / (S * sigma * sqrt(T))
    pdf = float(norm.pdf(d1))
    gamma = pdf / (spot * iv * sqrt_t)
    return gamma


def bs_vega(
    spot: float,
    strike: float,
    dte: int,
    iv: float,
    right: str,
    r: float = 0.05,
) -> float | None:
    """Black-Scholes vega for a European option.

    Sensitivity to volatility (per 1.0 change, i.e., not per 1%).
    """
    if spot <= 0 or strike <= 0 or dte <= 0 or iv <= 0:
        return None
    t = dte / 365.0
    try:
        sqrt_t = math.sqrt(t)
        d1 = (math.log(spot / strike) + (r + 0.5 * iv * iv) * t) / (iv * sqrt_t)
    except (ValueError, ZeroDivisionError):
        return None
    vega = spot * float(norm.pdf(d1)) * sqrt_t
    return vega


def bs_theta(
    spot: float,
    strike: float,
    dte: int,
    iv: float,
    right: str,
    r: float = 0.05,
) -> float | None:
    """Black-Scholes theta for a European option (per year).

    Returns time decay (negative for both calls and puts)."""
    if spot <= 0 or strike <= 0 or dte <= 0 or iv <= 0:
        return None
    t = dte / 365.0
    try:
        sqrt_t = math.sqrt(t)
        d1 = (math.log(spot / strike) + (r + 0.5 * iv * iv) * t) / (iv * sqrt_t)
        d2 = d1 - iv * sqrt_t
    except (ValueError, ZeroDivisionError):
        return None
    pdf = float(norm.pdf(d1))
    if right == "C":
        theta = -spot * pdf * iv / (2 * sqrt_t) - r * strike * math.exp(-r * t) * float(
            norm.cdf(d2)
        )
    else:
        theta = -spot * pdf * iv / (2 * sqrt_t) + r * strike * math.exp(-r * t) * float(
            norm.cdf(-d2)
        )
    return theta


def bs_rho(
    spot: float,
    strike: float,
    dte: int,
    iv: float,
    right: str,
    r: float = 0.05,
) -> float | None:
    """Black-Scholes rho for a European option.

    Sensitivity to risk-free rate.
    """
    if spot <= 0 or strike <= 0 or dte <= 0 or iv <= 0:
        return None
    t = dte / 365.0
    try:
        sqrt_t = math.sqrt(t)
        d1 = (math.log(spot / strike) + (r + 0.5 * iv * iv) * t) / (iv * sqrt_t)
        d2 = d1 - iv * sqrt_t
    except (ValueError, ZeroDivisionError):
        return None
    if right == "C":
        rho = strike * t * math.exp(-r * t) * float(norm.cdf(d2))
    else:
        rho = -strike * t * math.exp(-r * t) * float(norm.cdf(-d2))
    return rho
