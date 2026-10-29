"""The exit engine as a state machine (value book spec §7, §16): stop, arm, half at fair value,
trail, peak, thesis, catastrophe, time; fair value re-marked only on a new filing; no automatic
exit reads the effective (Claude) fair value."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.common.config import ValueExitsCfg
from src.common.value_types import DayBar
from src.value.exits import (
    POLICIES,
    DayFacts,
    LegState,
    benchmark_return,
    open_leg,
    step,
)

CFG = ValueExitsCfg()
D0 = date(2026, 11, 2)
ACCN = "0000000001-26-000001"


def bar(i: int, close: float, **kw: float | None) -> DayBar:
    return DayBar(date=D0 + timedelta(days=i), close=close, **kw)


def leg(policy: str = "full", fv: float | None = 120.0, atr: float | None = 2.0, **kw) -> LegState:
    return open_leg(
        policy,  # type: ignore[arg-type]
        entry_date=D0,
        entry_price=100.0,
        atr14=atr,
        fair_value=fv,
        effective_fair_value=kw.get("effective", fv),
        fv_accn=ACCN,
        cfg=CFG,
    )


def run(state: LegState, bars: list[DayBar], facts: DayFacts | None = None):
    events = []
    for b in bars:
        state, ev = step(state, b, facts, CFG)
        events += ev
    return state, [(e.kind, round(e.fraction, 6)) for e in events]


def test_full_opens_with_the_initial_stop_never_wider_than_fifteen_percent() -> None:
    assert leg(atr=2.0).stop == pytest.approx(94.0)  # 100 - 3 x 2
    assert leg(atr=10.0).stop == pytest.approx(85.0)  # 3 x ATR would be 30% below: capped
    assert leg(atr=None).stop == pytest.approx(85.0)
    assert leg("value").stop is None and leg("hold12").stop is None


def test_a_close_below_the_stop_sells_everything_at_the_next_open() -> None:
    state, events = run(leg(), [bar(1, 93.0), bar(2, 91.0, open=92.0)])
    assert events == [("stop", 1.0), ("fill", 1.0)]
    assert state.closed and state.exit_date == D0 + timedelta(days=2)
    assert state.exit_return() == pytest.approx(-0.08)  # sold at the 92.00 open


def test_the_trail_arms_half_way_to_fair_value_and_is_never_lowered() -> None:
    state, events = run(leg(), [bar(1, 111.0, atr14=2.0)])
    assert events == [("arm", 0.0)] and state.armed
    assert state.stop == pytest.approx(105.0)  # highest close 111 - 3 x 2
    state, events = run(state, [bar(2, 109.0, atr14=4.0)])
    assert events == [] and state.stop == pytest.approx(105.0)  # 111 - 12 = 99 would lower it
    state, events = run(state, [bar(3, 104.0, atr14=4.0)])
    assert events == [("trail", 1.0)]


def test_half_sells_at_fair_value_then_the_trail_tightens_to_two_atr() -> None:
    state, events = run(leg(), [bar(1, 121.0, atr14=2.0)])
    assert events == [("arm", 0.0), ("half", 0.5)]
    assert state.stop == pytest.approx(117.0)  # 121 - 2 x 2 once half is sold
    state, events = run(state, [bar(2, 123.0, open=122.0, atr14=2.0, sma20=115.0)])
    assert events == [("fill", 0.5)] and state.remaining == pytest.approx(0.5)
    assert state.stop == pytest.approx(119.0)
    state, events = run(state, [bar(3, 118.0, atr14=2.0), bar(4, 116.0, open=117.0)])
    assert events == [("trail", 0.5), ("fill", 0.5)]
    assert state.exit_return() == pytest.approx(0.195)  # (0.5 x 122 + 0.5 x 117) / 100 - 1
    assert state.sells == 2


def test_the_peak_signal_below_the_twenty_day_average_after_fair_value() -> None:
    state, _ = run(leg(fv=110.0, atr=2.0), [bar(1, 111.0)])  # arm and half, no ATR: stop stays
    state, events = run(state, [bar(2, 108.0, open=111.0, sma20=109.0)])
    assert events == [("fill", 0.5), ("peak", 0.5)]


def test_the_peak_signal_when_rsi_falls_back_through_seventy() -> None:
    state, events = run(leg(fv=200.0), [bar(1, 160.0, rsi14=80.0)])
    assert events == [("arm", 0.0)] and state.rsi_hot
    state, events = run(state, [bar(2, 161.0, rsi14=68.0)])
    assert events == [("peak", 1.0)]


@pytest.mark.parametrize("policy", POLICIES)
@pytest.mark.parametrize(
    ("facts", "sma50", "detail"),
    [
        (DayFacts(piotroski=3.0), None, "F-score 3"),
        (DayFacts(altman_z=1.5), None, "Altman Z 1.50"),
        (DayFacts(), 120.0, "fair value"),
    ],
)
def test_thesis_exits_fire_under_every_policy(policy, facts, sma50, detail) -> None:
    fv = 90.0 if detail == "fair value" else 120.0  # 90 < 0.9 x 105 with the close under SMA50
    state, events = run(leg(policy, fv=fv), [bar(1, 105.0, sma50=sma50)], facts)
    assert events == [("thesis", 1.0)]
    assert state.pending_reason == "thesis"


def test_value_sells_half_at_fair_value_and_rides_the_rest_until_a_remark_below() -> None:
    state, events = run(leg("value"), [bar(1, 121.0), bar(2, 130.0, open=121.0), bar(3, 150.0)])
    assert events == [("half", 0.5), ("fill", 0.5)]  # above fair value, no new filing: hold
    newer = DayFacts(python_fair_value=140.0, latest_accn="0000000001-26-000002")
    state, events = run(state, [bar(4, 150.0)], newer)
    assert events == [("remark", 0.0), ("remark_below", 0.5)]
    state, events = run(state, [bar(5, 148.0, open=149.0)], newer)
    assert events == [("fill", 0.5)] and state.closed
    assert state.exit_return() == pytest.approx(0.35)  # (0.5 x 121 + 0.5 x 149) / 100 - 1


@pytest.mark.parametrize("policy", ["value", "hold12"])
def test_the_catastrophe_stop_is_thirty_percent_below_cost(policy) -> None:
    _, events = run(leg(policy), [bar(1, 70.5)])
    assert events == []
    _, events = run(leg(policy), [bar(1, 70.0)])
    assert events == [("catastrophe", 1.0)]


def test_hold12_sells_after_252_sessions() -> None:
    bars = [bar(i, 101.0) for i in range(1, 253)]
    state, events = run(leg("hold12"), bars)
    assert events == [("time", 1.0)] and state.sessions == 252
    state, events = run(state, [bar(253, 101.0, open=102.0)])
    assert events == [("fill", 1.0)] and state.exit_return() == pytest.approx(0.02)


def test_fair_value_moves_only_on_a_new_filing() -> None:
    same = DayFacts(python_fair_value=150.0, latest_accn=ACCN)
    state, events = run(leg("value"), [bar(1, 105.0)], same)
    assert events == [] and state.fair_value == 120.0  # price and news never move it
    newer = DayFacts(python_fair_value=150.0, latest_accn="0000000001-26-000002")
    state, events = run(state, [bar(2, 105.0)], newer)
    assert events == [("remark", 0.0)] and state.fair_value == 150.0


def test_no_automatic_exit_reads_the_effective_fair_value() -> None:
    """Revision 3: an exit only Claude's (effective) value would fire is a tap proposal. The
    half-sale target is the one place the effective value is read, by design."""
    newer = DayFacts(
        python_fair_value=125.0, effective_fair_value=100.0, latest_accn="0000000001-26-000002"
    )
    state, events = run(leg("value", effective=120.0), [bar(1, 110.0)], newer)
    assert ("remark_below", 0.5) not in events and ("remark_below", 1.0) not in events
    assert ("proposal", 0.0) in events
    assert events[-1] == ("half", 0.5)  # 110 >= the effective 100: the half-sale reads it
    state, events = run(
        leg("hold12", fv=120.0, effective=100.0), [bar(1, 115.0, sma50=120.0)], DayFacts()
    )
    assert events == [("proposal", 0.0)] and state.pending == 0.0


def test_a_closed_leg_does_not_move() -> None:
    state, _ = run(leg(), [bar(1, 93.0), bar(2, 91.0, open=92.0)])
    after, events = step(state, bar(3, 200.0), None, CFG)
    assert after is state and events == []


def test_max_drawdown_is_the_worst_fall_from_the_best_close() -> None:
    state, _ = run(leg("value", fv=200.0), [bar(1, 110.0), bar(2, 99.0)])
    assert state.max_drawdown == pytest.approx(0.99 / 1.10 - 1.0)


def test_the_benchmark_return_matches_the_fills() -> None:
    d1, d2 = D0 + timedelta(days=5), D0 + timedelta(days=9)
    opens = {d1: 520.0, d2: 500.0}
    assert benchmark_return([(d1, 0.5), (d2, 0.5)], opens, 500.0) == pytest.approx(0.02)
    assert benchmark_return([(d1, 0.5), (D0, 0.5)], opens, 500.0) is None
    assert benchmark_return([], opens, 500.0) is None
