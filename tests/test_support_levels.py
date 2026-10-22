"""The support detector (Task 5): swing lows on daily lows, merged, below the price.

Synthetic frames are built from "cones" (``level + slope * |bar - centre|``) so that every
valley is a strict swing low at every window and nothing else is.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.analytics.support_levels import broken, support_levels
from src.analytics.technicals import _rsi14, rsi14_series
from tests.conftest import week_bars


def _cone_bars(valleys: list[tuple[int, float]], n: int, *, close_gap: float = 0.5) -> pd.DataFrame:
    """Daily bars whose lows are the lower envelope of cones at ``(centre, level)`` pairs."""
    idx = pd.bdate_range("2026-01-01", periods=n)
    i = np.arange(n)
    low = np.min([lvl + 1.0 * np.abs(i - c) for c, lvl in valleys], axis=0)
    return pd.DataFrame(
        {
            "Open": low + close_gap,
            "High": low + 2 * close_gap,
            "Low": low,
            "Close": low + close_gap,
            "Volume": 1_000.0,
        },
        index=idx,
    )


def test_swing_low_found_and_below_spot():
    bars = _cone_bars([(15, 8.0)], 31)
    assert support_levels(bars, spot=12.0, atr=1.0) == [8.0]
    # a level at or above the price is not a support
    assert support_levels(bars, spot=8.0, atr=1.0) == []
    assert support_levels(bars, spot=7.0, atr=1.0) == []


def test_levels_are_nearest_first_and_capped():
    valleys = [(15 + 30 * k, 10.0 + 5.0 * k) for k in range(7)]  # 10, 15, ... 40
    bars = _cone_bars(valleys, 7 * 30)
    assert support_levels(bars, spot=100.0, atr=1.0) == [40.0, 35.0, 30.0, 25.0, 20.0]
    assert support_levels(bars, spot=100.0, atr=1.0, max_levels=3) == [40.0, 35.0, 30.0]
    # nearest first means nearest *below the price*
    assert support_levels(bars, spot=31.0, atr=1.0, max_levels=2) == [30.0, 25.0]


def test_close_levels_merge_to_the_lower():
    bars = _cone_bars([(15, 20.0), (45, 20.3)], 61)
    # 0.3 apart is inside merge_atr x atr = 0.5: one level, the lower
    assert support_levels(bars, spot=30.0, atr=1.0, merge_atr=0.5) == [20.0]
    # a narrower merge distance keeps both
    assert support_levels(bars, spot=30.0, atr=1.0, merge_atr=0.2) == [20.3, 20.0]


def test_broken_level_is_dropped():
    # a deeper valley later closes more than one ATR under the first valley's 20.0
    bars = _cone_bars([(15, 20.0), (60, 15.0)], 91)
    assert support_levels(bars, spot=30.0, atr=1.0) == [15.0]
    # the same frame with a very tolerant break distance keeps both
    assert support_levels(bars, spot=30.0, atr=1.0, broken_atr=100.0) == [20.0, 15.0]
    # broken(): strictly more than broken_atr x atr under the level, on a close after it
    closes = pd.Series([21.0, 19.5, 18.9])
    assert broken(20.0, closes, atr=1.0, broken_atr=1.0) is True
    assert broken(20.0, closes.iloc[:2], atr=1.0, broken_atr=1.0) is False
    assert broken(20.0, closes.iloc[:0], atr=1.0, broken_atr=1.0) is False


def test_no_history_gives_no_levels():
    empty = pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    assert support_levels(empty, spot=10.0, atr=1.0) == []
    short = _cone_bars([(3, 8.0)], 6)
    assert support_levels(short, spot=12.0, atr=1.0) == []
    # no ATR given and too little history to compute one: nothing is claimed
    assert support_levels(_cone_bars([(5, 8.0)], 11), spot=12.0) == []


def test_tqqq_levels_on_oct_13_are_all_below_spot():
    bars = week_bars("TQQQ").loc[:"2026-10-13"]
    assert float(bars["Close"].iloc[-1]) == 78.81
    levels = support_levels(bars, spot=78.81)
    assert levels, "a year of TQQQ lows must give at least one support under 78.81"
    assert all(level < 78.81 for level in levels)
    assert levels == sorted(levels, reverse=True)
    assert len(levels) <= 5


def test_rsi14_series_last_value_matches_rsi14():
    rng = np.random.default_rng(7)
    close = pd.Series(100 + np.cumsum(rng.normal(0, 1, 120)))
    series = rsi14_series(close)
    assert len(series) == len(close)
    assert round(float(series.iloc[-1]), 2) == _rsi14(close)
    # too little history: _rsi14 keeps saying None
    assert _rsi14(close.iloc[:14]) is None
