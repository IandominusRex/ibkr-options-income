"""Tests for the offline backtest harness (IMPROVEMENT_PLAN Phase 4).

The simulation core is pure (takes an in-memory price series), so these run with no network.
Directional series exercise the assignment / expire-worthless branches; the Black-Scholes price
is checked against put-call parity.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

from src.analytics.black_scholes import bs_price
from src.backtest.engine import (
    BacktestParams,
    _strike_for_delta,
    _trailing_hv,
    simulate,
)
from src.backtest.report import format_report

_START = date(2023, 1, 2)


def _series(n: int, base: float, drift: float, wobble: float = 0.02) -> list[tuple[date, float]]:
    """n consecutive daily closes with a compounding drift plus an alternating wobble.

    The wobble gives non-zero return variance (so trailing HV > 0); the drift sets direction.
    """
    out: list[tuple[date, float]] = []
    price = base
    for i in range(n):
        price *= 1 + drift
        c = price * (1 + (wobble if i % 2 == 0 else -wobble))
        out.append((_START + timedelta(days=i), c))
    return out


# --------------------------------------------------------------------------- #
# Black-Scholes price
# --------------------------------------------------------------------------- #
def test_bs_price_put_call_parity():
    spot, strike, dte, iv, r = 100.0, 100.0, 30, 0.30, 0.05
    call = bs_price(spot, strike, dte, iv, "C", r)
    put = bs_price(spot, strike, dte, iv, "P", r)
    assert call is not None and put is not None
    # C − P = S − K·e^(−rT)
    expected = spot - strike * math.exp(-r * dte / 365.0)
    assert (call - put) == round(expected, 6) or abs((call - put) - expected) < 1e-6


def test_bs_price_positive_and_degenerate():
    assert bs_price(100, 100, 30, 0.3, "C") > 0
    assert bs_price(100, 200, 30, 0.3, "C") >= 0  # deep OTM call → ~0, never negative
    assert bs_price(100, 100, 0, 0.3, "C") is None  # no time
    assert bs_price(100, 100, 30, 0.0, "C") is None  # no vol


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def test_trailing_hv_needs_history_and_is_positive():
    closes = [c for _, c in _series(60, 100.0, 0.0)]
    assert _trailing_hv(closes, 10) is None  # < 30 prior closes
    hv = _trailing_hv(closes, 40)
    assert hv is not None and hv > 0


def test_strike_for_delta_brackets_target():
    # A ~0.30-delta put sits below spot; a ~0.30-delta call sits above.
    put_k = _strike_for_delta(100.0, 30, 0.30, "P", 0.30, 0.05)
    call_k = _strike_for_delta(100.0, 30, 0.30, "C", 0.30, 0.05)
    assert put_k is not None and put_k < 100.0
    assert call_k is not None and call_k > 100.0


# --------------------------------------------------------------------------- #
# simulate
# --------------------------------------------------------------------------- #
def test_simulate_short_series_zero_cycles():
    res = simulate("X", _series(20, 100.0, 0.0), BacktestParams(strategy="cash_secured_put"))
    assert res.num_cycles == 0
    assert res.total_pnl == 0.0


def test_csp_rising_underlying_expires_worthless():
    """Short puts under a rising underlying finish OTM → premium kept, no assignment."""
    prices = _series(150, 100.0, 0.01)
    res = simulate("UP", prices, BacktestParams(strategy="cash_secured_put", dte=30))
    assert res.num_cycles >= 2
    assert res.assignment_rate == 0.0
    assert res.win_rate == 1.0
    assert res.total_pnl > 0
    assert res.buy_hold_return_pct > 0
    # Aggregate P&L equals the sum of per-cycle P&L.
    assert res.total_pnl == round(sum(t.pnl for t in res.trades), 2)


def test_csp_falling_underlying_gets_assigned():
    prices = _series(150, 100.0, -0.01)
    res = simulate("DOWN", prices, BacktestParams(strategy="cash_secured_put", dte=30))
    assert res.num_cycles >= 2
    assert res.assignment_rate > 0.0
    assert any(t.assigned and t.intrinsic_cost > 0 for t in res.trades)


def test_covered_call_rising_underlying_gets_called_away():
    prices = _series(150, 100.0, 0.01)
    res = simulate("UP", prices, BacktestParams(strategy="covered_call", dte=30))
    assert res.num_cycles >= 2
    assert res.params.right == "C"
    assert res.assignment_rate > 0.0
    assert any(t.assigned and t.intrinsic_cost > 0 for t in res.trades)
    # Capital base for a CC is the share basis at first entry, not a strike.
    assert res.capital_base == round(res.trades[0].spot_at_entry * 100, 2) or res.capital_base > 0


def test_metrics_in_range_and_report_renders():
    prices = _series(150, 100.0, 0.005)
    res = simulate("X", prices, BacktestParams(strategy="cash_secured_put", contracts=2))
    assert 0.0 <= res.win_rate <= 1.0
    assert 0.0 <= res.assignment_rate <= 1.0
    assert res.max_drawdown_pct >= 0.0
    text = format_report(res)
    assert "Backtest — X cash_secured_put" in text
    assert "Annualized:" in text


def test_report_handles_zero_cycles():
    res = simulate("X", _series(10, 100.0, 0.0), BacktestParams(strategy="cash_secured_put"))
    text = format_report(res)
    assert "no cycles" in text


# --------------------------------------------------------------------------- #
# v2 (N21): stored-IV pricing, profit-take, IV-rank gating
# --------------------------------------------------------------------------- #


def test_stored_iv_pricing_captures_vrp_on_flat_underlying():
    """Selling rich IV (0.80) on a ~flat underlying should bank a positive variance-risk
    premium — the edge a fair-value (HV) backtest can't see by construction."""
    prices = _series(150, 100.0, 0.0, wobble=0.01)  # ~flat → low realised HV
    iv = [0.80] * len(prices)
    params = BacktestParams(strategy="cash_secured_put", dte=30)

    res = simulate("FLAT", prices, params, iv_series=iv)
    assert res.iv_source == "stored_iv"
    assert res.num_cycles > 0
    assert res.mean_vrp_pct > 0  # entry IV (0.80) far exceeds the realised HV
    assert res.total_pnl > 0  # the seller keeps the premium when price barely moves

    # Same path priced at trailing HV (the old fair-value engine) has no VRP edge to report.
    fair = simulate("FLAT", prices, params)
    assert fair.iv_source == "trailing_hv"
    assert fair.mean_vrp_pct == 0.0


def test_profit_take_closes_cycles_early():
    prices = _series(150, 100.0, 0.0, wobble=0.01)
    iv = [0.80] * len(prices)
    res = simulate(
        "FLAT",
        prices,
        BacktestParams(strategy="cash_secured_put", dte=30, profit_take_pct=0.50),
        iv_series=iv,
    )
    assert res.num_cycles > 0
    assert res.profit_take_rate > 0  # theta decay on a flat name trips the 50% rule
    assert any(t.closed_early for t in res.trades)


def test_iv_rank_gating_reduces_cycle_count():
    # Alternating high/low IV blocks so the backtest IV rank actually varies.
    prices = _series(220, 100.0, 0.0, wobble=0.01)
    iv = [0.80 if (i // 20) % 2 == 0 else 0.30 for i in range(len(prices))]

    ungated = simulate(
        "OSC", prices, BacktestParams(strategy="cash_secured_put", dte=30), iv_series=iv
    )
    gated = simulate(
        "OSC",
        prices,
        BacktestParams(strategy="cash_secured_put", dte=30, min_iv_rank=50.0),
        iv_series=iv,
    )
    assert ungated.num_cycles > 0
    assert gated.num_cycles < ungated.num_cycles  # low-IV-rank windows are skipped
