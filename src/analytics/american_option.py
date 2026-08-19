"""American option pricer using a Cox‑Ross‑Rubinstein binomial tree.

This implementation is deliberately simple, only used for the Phase‑1 Greeks extension.
It provides:
- :func:`american_price` – price of an American call or put.
- :func:`early_exercise_premium` – difference between American and European (Black‑Scholes)
  prices.

No external dependencies beyond ``math`` and the existing Black‑Scholes ``bs_price``.
"""

from __future__ import annotations

import math
from typing import Literal

from src.analytics.black_scholes import bs_price


def american_price(
    spot: float,
    strike: float,
    dte: int,
    iv: float,
    right: Literal["C", "P"],
    r: float = 0.05,
    n_steps: int = 200,
    q: float = 0.0,
) -> float | None:
    """Cox‑Ross‑Rubinstein binomial‑tree price for an American option.

    Parameters
    ----------
    spot: float
        Underlying price.
    strike: float
        Option strike.
    dte: int
        Days to expiration.
    iv: float
        Implied volatility as a decimal (0.30 = 30 %).
    right: "C" or "P"
        Call or put.
    r: float, default 0.05
        Risk‑free rate.
    n_steps: int, default 200
        Number of binomial steps – more steps = higher accuracy.
    q: float, default 0.0
        Continuous dividend yield (zero for non‑dividend‑paying stocks).

    Returns
    -------
    float | None
        The American option price per share, or ``None`` for degenerate inputs.
    """
    if spot <= 0 or strike <= 0 or dte <= 0 or iv <= 0:
        return None
    T = dte / 365.0
    dt = T / n_steps
    # Up and down factors
    u = math.exp(iv * math.sqrt(dt))
    d = 1 / u
    # Risk‑neutral probability
    disc = math.exp(-r * dt)
    p = (math.exp((r - q) * dt) - d) / (u - d)

    # Initialise asset prices at maturity
    prices = [spot * (u**i) * (d ** (n_steps - i)) for i in range(n_steps + 1)]
    # Option values at maturity
    if right == "C":
        values = [max(p_ - strike, 0.0) for p_ in prices]
    else:
        values = [max(strike - p_, 0.0) for p_ in prices]

    # Backward induction with early‑exercise check
    for step in range(n_steps - 1, -1, -1):
        for i in range(step + 1):
            continuation = disc * (p * values[i + 1] + (1 - p) * values[i])
            underlying = spot * (u**i) * (d ** (step - i))
            intrinsic = (
                max(underlying - strike, 0.0) if right == "C" else max(strike - underlying, 0.0)
            )
            values[i] = max(continuation, intrinsic)
    return values[0]


def early_exercise_premium(
    spot: float,
    strike: float,
    dte: int,
    iv: float,
    right: Literal["C", "P"],
    r: float = 0.05,
    n_steps: int = 200,
    q: float = 0.0,
) -> float | None:
    """Difference between American and European (BS) prices.

    Returns ``american_price - bs_price``. If either price is ``None`` the result is ``None``.
    """
    a_price = american_price(spot, strike, dte, iv, right, r, n_steps, q)
    e_price = bs_price(spot, strike, dte, iv, right, r)
    if a_price is None or e_price is None:
        return None
    return a_price - e_price
