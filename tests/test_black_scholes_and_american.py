import math
from typing import Literal

import pytest

from src.analytics.american_option import american_price, early_exercise_premium
from src.analytics.black_scholes import (
    bs_delta,
    bs_gamma,
    bs_price,
    bs_theta,
    bs_vega,
)


# Helper for tolerance comparisons
def rel_diff(a: float, b: float) -> float:
    return abs(a - b) / max(abs(a), abs(b), 1e-12)


@pytest.mark.parametrize(
    "spot,strike,dte,iv,right",
    [
        (100.0, 100.0, 30, 0.20, "C"),
        (100.0, 100.0, 30, 0.20, "P"),
        (120.0, 100.0, 60, 0.25, "C"),
        (80.0, 100.0, 45, 0.30, "P"),
    ],
)
def test_price_parity(spot: float, strike: float, dte: int, iv: float, right: Literal["C", "P"]):
    # Black‑Scholes price for call and put should satisfy put‑call parity:
    # C - P = S - K * exp(-r T)
    r = 0.05
    call = bs_price(spot, strike, dte, iv, "C", r)
    put = bs_price(spot, strike, dte, iv, "P", r)
    assert call is not None and put is not None
    t = dte / 365.0
    lhs = call - put
    rhs = spot - strike * math.exp(-r * t)
    assert rel_diff(lhs, rhs) < 1e-6


def test_greek_finite_difference():
    spot = 100.0
    strike = 100.0
    dte = 30
    iv = 0.20
    right = "C"
    eps = 0.01
    # Gamma via finite diff of delta
    delta_up = bs_delta(spot + eps, strike, dte, iv, right)
    delta_down = bs_delta(spot - eps, strike, dte, iv, right)
    fd_gamma = (delta_up - delta_down) / (2 * eps)
    bs_gamma_val = bs_gamma(spot, strike, dte, iv, right)
    assert bs_gamma_val is not None
    assert rel_diff(bs_gamma_val, fd_gamma) < 1e-3

    # Vega via finite diff of price wrt iv
    iv_eps = 0.0001
    price_up = bs_price(spot, strike, dte, iv + iv_eps, right)
    price_down = bs_price(spot, strike, dte, iv - iv_eps, right)
    fd_vega = (price_up - price_down) / (2 * iv_eps)
    bs_vega_val = bs_vega(spot, strike, dte, iv, right)
    assert bs_vega_val is not None
    assert rel_diff(bs_vega_val, fd_vega) < 1e-3


def test_theta_sign():
    spot = 100.0
    strike = 100.0
    dte = 30
    iv = 0.20
    for right in ("C", "P"):
        theta = bs_theta(spot, strike, dte, iv, right)
        assert theta is not None
        # Theta should be non‑positive (time decay)
        assert theta <= 0


def test_american_vs_european():
    # American price should be at least as high as European (no-arb). Test for call and put.
    # A small discretization slack is allowed: the binomial tree (200 steps) converges to the
    # Black-Scholes price from below for ATM calls, so the American price can land a fraction
    # of a cent under the closed-form European value at finite step counts.
    spot = 100.0
    strike = 100.0
    dte = 30
    iv = 0.20
    for right in ("C", "P"):
        a_price = american_price(spot, strike, dte, iv, right)
        e_price = bs_price(spot, strike, dte, iv, right)
        assert a_price is not None and e_price is not None
        assert a_price >= e_price - 0.01

    # Early-exercise premium for a deep OTM put (no intrinsic value, no dividend) should be
    # ~0 — early exercise is never optimal when there's no intrinsic value to capture.
    spot = 150.0
    strike = 80.0
    dte = 30
    iv = 0.20
    premium = early_exercise_premium(spot, strike, dte, iv, "P")
    assert premium is not None
    assert abs(premium) < 1e-4
