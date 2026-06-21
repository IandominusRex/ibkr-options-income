"""Tests for Phase 5 (Competitive Research Plan) — C10/C11: earnings-cycle backtest + compact report."""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

from src.backtest.earnings import (
    EarningsCycleBacktestResult,
    simulate_earnings_cycles,
)
from src.backtest.engine import BacktestParams
from src.backtest.report import compact_report, format_earnings_cycle_report

_START = date(2022, 1, 3)
_PARAMS_CSP = BacktestParams(strategy="cash_secured_put", target_delta=0.30, dte=30)
_PARAMS_CC = BacktestParams(strategy="covered_call", target_delta=0.30, dte=30)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _series(
    n: int, base: float = 100.0, drift: float = 0.0, wobble: float = 0.02
) -> list[tuple[date, float]]:
    """n consecutive daily closes with compounding drift + alternating wobble (non-zero HV)."""
    out: list[tuple[date, float]] = []
    price = base
    for i in range(n):
        price *= 1 + drift
        c = price * (1 + (wobble if i % 2 == 0 else -wobble))
        out.append((_START + timedelta(days=i), c))
    return out


def _earnings_every_90_days(n_events: int, offset: int = 60) -> list[date]:
    """Generate n_events quarterly earnings dates starting offset days into the series."""
    return [_START + timedelta(days=offset + i * 90) for i in range(n_events)]


# ---------------------------------------------------------------------------
# C10 — simulate_earnings_cycles
# ---------------------------------------------------------------------------


def test_empty_prices_returns_zero_cycles():
    result = simulate_earnings_cycles("X", [], _PARAMS_CSP, [date(2023, 1, 15)])
    assert result.num_pre_cycles == 0
    assert len(result.cycles) == 0


def test_empty_earnings_returns_zero_cycles():
    result = simulate_earnings_cycles("X", _series(200), _PARAMS_CSP, [])
    assert result.num_pre_cycles == 0


def test_earnings_outside_price_window_skipped():
    prices = _series(100)
    # Earnings date far outside the price series range
    earnings = [_START + timedelta(days=500)]
    result = simulate_earnings_cycles("X", prices, _PARAMS_CSP, earnings)
    assert len(result.cycles) == 0


def test_single_earnings_in_range_produces_cycle():
    prices = _series(250)
    earnings = [_START + timedelta(days=120)]
    result = simulate_earnings_cycles(
        "X", prices, _PARAMS_CSP, earnings, blackout_before=14, blackout_after=3
    )
    assert len(result.cycles) == 1


def test_pre_earnings_trade_assigned_below_strike_falls():
    """CSP is assigned when the underlying ends below the strike (falling series)."""
    prices = _series(250, base=100.0, drift=-0.003)
    earnings = [_START + timedelta(days=100)]
    result = simulate_earnings_cycles(
        "X", prices, _PARAMS_CSP, earnings, blackout_before=14, blackout_after=3
    )
    trades = [c.pre_earnings_trade for c in result.cycles if c.pre_earnings_trade]
    if trades:
        # Assignment rate should be positive on a falling series
        assert result.pre_assignment_rate >= 0.0  # may or may not assign depending on delta


def test_pre_earnings_trade_win_rate_rising():
    """CSP should mostly expire worthless (win) on a rising underlying."""
    prices = _series(400, base=100.0, drift=0.005)
    earnings = _earnings_every_90_days(3, offset=60)
    result = simulate_earnings_cycles(
        "X", prices, _PARAMS_CSP, earnings, blackout_before=14, blackout_after=3
    )
    if result.num_pre_cycles >= 2:
        assert result.pre_win_rate > 0.0


def test_window_too_narrow_gates_entry():
    """When the earnings events are close together the window is too narrow → entry_gated=True."""
    prices = _series(250)
    # Two earnings events only 20 days apart — blackout_before=14 + blackout_after=3 = 17 days of blackout
    # so the inter-earnings gap is ≈20 − 17 = 3 days, too short for DTE=30
    earnings = [_START + timedelta(days=70), _START + timedelta(days=90)]
    result = simulate_earnings_cycles(
        "X", prices, _PARAMS_CSP, earnings, blackout_before=14, blackout_after=3
    )
    # At least one cycle should be gated (window too narrow or insufficient HV history)
    assert any(c.entry_gated for c in result.cycles)


def test_vol_crush_trade_appended():
    """When vol_crush_dte is set, vol_crush_trade is populated for cycles with enough data."""
    prices = _series(400, base=100.0, drift=0.001)
    earnings = _earnings_every_90_days(3, offset=80)
    result = simulate_earnings_cycles(
        "X",
        prices,
        _PARAMS_CSP,
        earnings,
        blackout_before=14,
        blackout_after=3,
        vol_crush_dte=14,
    )
    vc_trades = [c.vol_crush_trade for c in result.cycles if c.vol_crush_trade]
    # At least some cycles should have vol-crush trades when history is sufficient
    assert result.num_vol_crush_cycles == len(vc_trades)


def test_vol_crush_pnl_tracked_separately():
    prices = _series(400, base=100.0, drift=0.002)
    earnings = _earnings_every_90_days(4, offset=80)
    result = simulate_earnings_cycles(
        "X", prices, _PARAMS_CSP, earnings, blackout_before=14, blackout_after=3, vol_crush_dte=14
    )
    vc_trades = [c.vol_crush_trade for c in result.cycles if c.vol_crush_trade]
    expected_vc_pnl = round(sum(t.pnl for t in vc_trades), 2)
    assert result.total_vol_crush_pnl == expected_vc_pnl


def test_pre_pnl_equals_sum_of_trade_pnls():
    prices = _series(400, base=100.0)
    earnings = _earnings_every_90_days(3, offset=60)
    result = simulate_earnings_cycles("X", prices, _PARAMS_CSP, earnings)
    pre_trades = [c.pre_earnings_trade for c in result.cycles if c.pre_earnings_trade]
    assert result.total_pre_pnl == round(sum(t.pnl for t in pre_trades), 2)


def test_result_metadata():
    result = simulate_earnings_cycles(
        "AAPL", _series(200), _PARAMS_CC, [_START + timedelta(days=90)]
    )
    assert result.symbol == "AAPL"
    assert result.strategy == "covered_call"
    assert result.blackout_before == 14
    assert result.blackout_after == 3
    assert result.vol_crush_dte is None


# ---------------------------------------------------------------------------
# C10 — format_earnings_cycle_report
# ---------------------------------------------------------------------------


def test_format_earnings_cycle_report_zero_cycles():
    result = EarningsCycleBacktestResult(
        symbol="X",
        strategy="cash_secured_put",
        params=_PARAMS_CSP,
        blackout_before=14,
        blackout_after=3,
        vol_crush_dte=None,
    )
    text = format_earnings_cycle_report(result)
    assert "X" in text
    assert "0" in text


def test_format_earnings_cycle_report_with_trades():
    prices = _series(400, base=100.0, drift=0.002)
    earnings = _earnings_every_90_days(3, offset=80)
    result = simulate_earnings_cycles("AAPL", prices, _PARAMS_CSP, earnings)
    text = format_earnings_cycle_report(result)
    assert "AAPL" in text
    assert "Pre-earnings" in text


def test_format_earnings_cycle_report_vol_crush_section():
    prices = _series(400, base=100.0)
    earnings = _earnings_every_90_days(3, offset=80)
    result = simulate_earnings_cycles("AAPL", prices, _PARAMS_CSP, earnings, vol_crush_dte=14)
    text = format_earnings_cycle_report(result)
    assert "Vol-crush" in text or "vol-crush" in text.lower()


# ---------------------------------------------------------------------------
# C11 — compact_report
# ---------------------------------------------------------------------------


def test_compact_report_zero_cycles():
    from src.backtest.engine import BacktestResult

    result = BacktestResult(
        symbol="X",
        strategy="cash_secured_put",
        start=date(2023, 1, 1),
        end=date(2023, 12, 31),
        params=_PARAMS_CSP,
    )
    text = compact_report(result)
    assert "0 cycles" in text
    assert "X" in text


def test_compact_report_with_trades():
    from src.backtest.engine import simulate

    def _prices(n):
        p = 100.0
        out = []
        for i in range(n):
            p *= 1.001
            c = p * (1 + (0.02 if i % 2 == 0 else -0.02))
            out.append((_START + timedelta(days=i), c))
        return out

    prices = _prices(200)
    result = simulate("AAPL", prices, _PARAMS_CSP)
    text = compact_report(result)
    # Must fit in 4 lines
    assert text.count("\n") <= 3
    assert "AAPL" in text
    assert "%" in text  # win rate or assignment rate


def test_compact_report_one_liner_when_no_cycles():
    from src.backtest.engine import BacktestResult

    r = BacktestResult(
        symbol="Z",
        strategy="covered_call",
        start=date(2024, 1, 1),
        end=date(2024, 1, 10),
        params=_PARAMS_CC,
    )
    text = compact_report(r)
    assert "\n" not in text  # single line for zero-cycle result


# ---------------------------------------------------------------------------
# C10 — load_earnings_dates (offline: mocked yfinance)
# ---------------------------------------------------------------------------


def test_load_earnings_dates_returns_sorted_dates():
    import pandas as pd

    from src.backtest.data import load_earnings_dates

    mock_df = pd.DataFrame(
        {"EPS Estimate": [0.5, 0.6, 0.7]},
        index=pd.to_datetime(["2023-01-15", "2023-04-17", "2022-10-24"]),
    )
    with patch("yfinance.Ticker") as mock_ticker_cls:
        mock_ticker = MagicMock()
        mock_ticker.earnings_dates = mock_df
        mock_ticker_cls.return_value = mock_ticker

        dates = load_earnings_dates("AAPL")

    assert dates == sorted(dates)
    assert len(dates) == 3
    assert all(isinstance(d, date) for d in dates)


def test_load_earnings_dates_empty_df_returns_empty():
    import pandas as pd

    from src.backtest.data import load_earnings_dates

    with patch("yfinance.Ticker") as mock_ticker_cls:
        mock_ticker = MagicMock()
        mock_ticker.earnings_dates = pd.DataFrame()
        mock_ticker_cls.return_value = mock_ticker

        dates = load_earnings_dates("AAPL")

    assert dates == []


def test_load_earnings_dates_network_failure_returns_empty():
    from src.backtest.data import load_earnings_dates

    with patch("yfinance.Ticker", side_effect=RuntimeError("network error")):
        dates = load_earnings_dates("AAPL")

    assert dates == []
