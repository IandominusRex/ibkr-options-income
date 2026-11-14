"""The Leveraged Entry Signal (risk-envelope Task 10a, rulings L1 and L4; spec §3.5.1).

Pure and fail-closed: price bars and breadth in, a `LesSignal` out. Every test that depends on a
price pattern first asserts the facts of the pattern it built (the averages, the RSI), so a
mistake in a fixture reads as a fixture failure, not a signal failure.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from src.analytics.leveraged_entry import les_signal, rsi_series
from src.common.config import get_regime_cfg

CFG = get_regime_cfg().leveraged_entry
LAST = pd.Timestamp("2026-11-13")


def frame(closes: list[float]) -> pd.DataFrame:
    idx = pd.bdate_range(end=LAST, periods=len(closes))
    return pd.DataFrame({"Close": closes}, index=idx)


def uptrend(n: int = 300, lo: float = 100.0, hi: float = 200.0) -> list[float]:
    return list(np.linspace(lo, hi, n))


def sma(closes: list[float], n: int) -> float:
    return float(np.mean(closes[-n:]))


def with_osc(value: float, on: date | None = None) -> list[tuple[date, float]]:
    day = on or LAST.date()
    return [(day - timedelta(days=2), 5.0), (day, value)]


# a steady climb that ends on a sharp two-day drop: above both averages, RSI(2) deep under 5
RSI_PULLBACK = [*uptrend(298), 197.0, 194.0]
# a long slide from a high that stays above the 200-day but ends below the 50-day, with an up
# close at the end so that RSI(2) is not the reason
SMA50_PULLBACK = [*uptrend(260, 100, 200), *np.linspace(199, 168, 38), 172.0, 176.0]
DOWNTREND = list(np.linspace(200, 100, 300))


def test_no_signal_under_200_bars():
    sig = les_signal(frame(uptrend(150)), with_osc(-60.0), CFG, index="QQQ")
    assert (sig.trend_up, sig.pullback, sig.washout, sig.trend_break) == (
        False,
        False,
        False,
        False,
    )
    assert sig.tier_pct == 0.0 and sig.index == "QQQ"
    assert "history" in " ".join(sig.reasons)
    # the same series with its history long enough does carry a signal
    assert les_signal(frame(uptrend(260)), [], CFG, index="QQQ").trend_up is True


def test_a_missing_close_is_no_signal():
    closes = uptrend(260)
    closes[-5] = float("nan")
    sig = les_signal(frame(closes), with_osc(-60.0), CFG, index="QQQ")
    assert (sig.trend_up, sig.pullback, sig.washout) == (False, False, False)
    assert "missing close" in " ".join(sig.reasons)
    assert les_signal(None, [], CFG, index="QQQ").tier_pct == 0.0  # no frame at all


def test_trend_gate():
    up = les_signal(frame(uptrend()), [], CFG, index="QQQ")
    assert up.trend_up is True and up.asof == LAST.date()
    # below the 200-day nothing else can fire, whatever RSI(2) and breadth say
    closes = DOWNTREND
    assert closes[-1] < sma(closes, 200) and float(rsi_series(pd.Series(closes), 2).iloc[-1]) < 5
    down = les_signal(frame(closes), with_osc(-80.0), CFG, index="QQQ")
    assert down.trend_up is False
    assert (down.pullback, down.washout) == (False, False)
    assert down.tier_pct == 0.0
    assert "200-day" in " ".join(down.reasons)


def test_pullback_on_rsi2_under_5():
    closes = RSI_PULLBACK
    assert closes[-1] > sma(closes, 200) and closes[-1] > sma(closes, 50)  # not the average rule
    assert float(rsi_series(pd.Series(closes), 2).iloc[-1]) < CFG.rsi_max
    sig = les_signal(frame(closes), [], CFG, index="QQQ")
    assert sig.trend_up and sig.pullback and not sig.washout
    assert sig.tier_pct == 3.0
    assert "RSI(2)" in " ".join(sig.reasons)


def test_pullback_on_close_under_sma50():
    closes = SMA50_PULLBACK
    assert closes[-1] > sma(closes, 200)  # the trend gate holds
    assert closes[-1] < sma(closes, 50)  # under the 50-day
    assert float(rsi_series(pd.Series(closes), 2).iloc[-1]) >= CFG.rsi_max  # so RSI is not why
    sig = les_signal(frame(closes), [], CFG, index="QQQ")
    assert sig.trend_up and sig.pullback and sig.tier_pct == 3.0
    assert "50-day" in " ".join(sig.reasons)


def test_no_pullback_when_neither_part_holds():
    sig = les_signal(frame(uptrend()), [], CFG, index="QQQ")  # a calm climb
    assert sig.trend_up and not sig.pullback and sig.tier_pct == 0.0


def test_washout_lifts_the_tier_to_6():
    sig = les_signal(frame(RSI_PULLBACK), with_osc(-43.0), CFG, index="QQQ")
    assert sig.pullback and sig.washout and sig.tier_pct == 6.0
    # -40 exactly counts (<=); -39.9 does not
    assert les_signal(frame(RSI_PULLBACK), with_osc(-40.0), CFG, index="QQQ").washout is True
    assert les_signal(frame(RSI_PULLBACK), with_osc(-39.9), CFG, index="QQQ").washout is False
    # a washout needs the pullback: breadth alone on a calm climb is nothing
    calm = les_signal(frame(uptrend()), with_osc(-60.0), CFG, index="QQQ")
    assert calm.washout is False and calm.tier_pct == 0.0
    # any of the last 5 sessions counts, an older one does not
    bars = frame(RSI_PULLBACK)
    days = [d.date() for d in bars.index[-8:]]
    recent = [(days[4], -50.0), (days[7], -10.0)]  # 3 sessions back, then the last day
    assert les_signal(bars, recent, CFG, index="QQQ").washout is True
    old = [(days[1], -50.0), (days[7], -10.0)]  # 6 sessions back
    assert les_signal(bars, old, CFG, index="QQQ").washout is False


def test_below_200_tier_is_half_of_3():
    """`les_signal` never returns the below-trend tier (it fires no LES share and the
    bottoming path applies it in `regime_limits`, Task 23); the configured value is half of 3."""
    assert CFG.tiers.below_trend == 1.5
    assert CFG.tiers.below_trend == CFG.tiers.pullback / 2
    down = les_signal(frame(DOWNTREND), with_osc(-80.0), CFG, index="QQQ")
    assert down.tier_pct == 0.0


def test_trend_break_needs_two_closes():
    base = uptrend(300)
    one = [*base[:-1], 90.0]  # the last close alone under the 200-day
    sig1 = les_signal(frame(one), [], CFG, index="QQQ")
    assert sig1.trend_break is False and sig1.trend_up is False
    two = [*base[:-2], 90.0, 90.0]
    sig2 = les_signal(frame(two), [], CFG, index="QQQ")
    assert sig2.trend_break is True
    assert "2 closes" in " ".join(sig2.reasons) or "2 consecutive" in " ".join(sig2.reasons)
    # a close back above the average ends the run
    recovered = [*base[:-2], 90.0, 199.0]
    assert les_signal(frame(recovered), [], CFG, index="QQQ").trend_break is False


def test_stale_breadth_means_pullback_tier_only():
    bars = frame(RSI_PULLBACK)
    stale = [
        (LAST.date() - timedelta(days=4), -60.0)
    ]  # a washout reading, but not the last session
    sig = les_signal(bars, stale, CFG, index="QQQ")
    assert sig.pullback is True and sig.washout is False and sig.tier_pct == 3.0
    assert "stale" in " ".join(sig.reasons)
    # no breadth at all is the same
    none = les_signal(bars, [], CFG, index="QQQ")
    assert none.washout is False and none.tier_pct == 3.0


def test_reasons_name_each_part():
    sig = les_signal(frame(RSI_PULLBACK), with_osc(-43.0), CFG, index="QQQ")
    text = " | ".join(sig.reasons).lower()
    for part in ("trend", "pullback", "washout"):
        assert part in text, (part, sig.reasons)
    brk = les_signal(frame([*uptrend(298), 90.0, 90.0]), [], CFG, index="QQQ")
    assert "break" in " ".join(brk.reasons).lower()


def test_rsi_series_is_wilder_smoothed():
    close = pd.Series([10.0, 11.0, 10.0, 12.0, 11.0, 11.5])
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(com=1, adjust=False).mean()  # alpha 1/n with n = 2
    loss = (-delta.clip(upper=0)).ewm(com=1, adjust=False).mean()
    expected = 100 - 100 / (1 + gain / loss)
    pd.testing.assert_series_equal(rsi_series(close, 2), expected, check_names=False)


def test_the_shipped_block_matches_the_ruling():
    assert CFG.governing == {"TQQQ": "QQQ", "SOXL": "SOXX"}
    assert (CFG.sma_trend, CFG.sma_pullback, CFG.rsi_n, CFG.rsi_max) == (200, 50, 2, 5)
    assert (CFG.washout_osc, CFG.washout_sessions, CFG.break_closes) == (-40, 5, 2)
    assert (CFG.tiers.pullback, CFG.tiers.washout, CFG.tiers.below_trend) == (3.0, 6.0, 1.5)
    assert (CFG.pace_sessions, CFG.source_gap_flag) == (3, 10)
    with pytest.raises(ValueError, match="unknown key"):
        type(CFG)(rsi_maxx=5)
