"""The exit engine as a state machine (value book spec §7, §7.1, §16): stop, arm, half at fair
value, trail, peak, thesis, catastrophe, time; fair value re-marked only on a new filing; no
automatic exit reads the effective (Claude) fair value; Part 3's shock stops (full only), the 8-K
and going-concern thesis exits, and the rebase."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.common.config import ValueExitsCfg
from src.common.value_types import DayBar
from src.value.exits import (
    POLICIES,
    DayFacts,
    LegState,
    Reeval,
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


def test_an_armed_leg_never_stops_below_breakeven_even_without_atr() -> None:
    """Review M3: spec §7 - once armed the stop is never below the breakeven."""
    state, _ = run(leg(atr=None), [bar(1, 111.0)])  # arms; the initial stop was 85
    assert state.armed and state.stop == pytest.approx(100.0)
    _, events = run(state, [bar(2, 99.0)])
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
        (DayFacts(altman_z=1.5, latest_accn="0000000001-26-000002"), None, "Altman Z 1.50"),
        (DayFacts(going_concern=True), None, "going-concern"),
        # a fair value re-marked from a new filing to below 90% of the price, price under SMA50
        (DayFacts(python_fair_value=90.0, latest_accn="0000000001-26-000002"), 120.0, "fair value"),
    ],
)
def test_thesis_exits_fire_under_every_policy(policy, facts, sma50, detail) -> None:
    state, events = run(leg(policy, fv=120.0), [bar(1, 105.0, sma50=sma50)], facts)
    assert events[-1] == ("thesis", 1.0)
    assert state.pending_reason == "thesis"


@pytest.mark.parametrize("policy", ["value", "hold12"])
def test_the_static_fair_value_rule_fires_only_on_a_session_with_a_remark(policy) -> None:
    """Review I5 (ruling 14): a price that ran past a static fair value is the ride. FV 130, the
    price at 131 / 150 / 148 under a 149 SMA50, no new filing: the remainder is not sold."""
    state, events = run(
        leg(policy, fv=130.0),
        [bar(1, 131.0), bar(2, 150.0, sma50=140.0), bar(3, 148.0, sma50=149.0)],
    )
    assert ("thesis", 0.5) not in events and ("thesis", 1.0) not in events
    assert not state.closed
    # The same bar on a session that re-marks fair value from a new accession does fire.
    newer = DayFacts(python_fair_value=130.0, latest_accn="0000000001-26-000002")
    _, events = run(state, [bar(4, 148.0, sma50=149.0)], newer)
    assert events[-1][0] == "thesis"


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


def test_the_peak_signal_reads_pythons_fair_value_not_the_effective_one() -> None:
    """Review I1: full's peak exit sells with no tap, so it may not key off Claude's number.
    Python FV 120, effective 105: the price crosses only the effective value, then slips under
    the 20-day average. The half-sale reads 105; the peak signal waits for Python's 120."""
    state, events = run(
        leg(fv=120.0, effective=105.0),
        [bar(1, 106.0), bar(2, 111.0, open=107.0), bar(3, 110.5, sma20=111.0)],
    )
    kinds = [k for k, _ in events]
    assert "peak" not in kinds and not state.above_fv_seen
    assert kinds.count("half") == 1
    assert kinds.count("proposal") == 1  # one note, once per episode
    state, events = run(state, [bar(4, 121.0), bar(5, 119.0, sma20=120.0)])
    assert events[-1] == ("peak", state.pending) and state.above_fv_seen


def test_the_two_atr_trail_waits_for_pythons_fair_value_too() -> None:
    """Decision (review I1): the half-sale itself reads the effective value (ruling 15), but the
    2 x ATR tightening is a stop that sells by itself, so it keys off Python's fair value."""
    state, _ = run(leg(fv=120.0, effective=105.0), [bar(1, 111.0, atr14=2.0)])
    assert state.half_sold and not state.above_fv_seen
    assert state.stop == pytest.approx(105.0)  # 111 - 3 x 2, not 111 - 2 x 2
    state, _ = run(state, [bar(2, 121.0, open=112.0, atr14=2.0)])
    assert state.above_fv_seen and state.stop == pytest.approx(117.0)  # 121 - 2 x 2


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


def test_an_unknown_f_score_component_counts_against_the_exit() -> None:
    """Review M5: an unknown component scores 0, so F-score 3 with one unknown could be 4."""
    _, events = run(leg("value"), [bar(1, 105.0)], DayFacts(piotroski=3.0, piotroski_missing=1))
    assert events == []
    _, events = run(leg("value"), [bar(1, 105.0)], DayFacts(piotroski=2.0, piotroski_missing=1))
    assert events == [("thesis", 1.0)]


def test_the_altman_z_exit_is_read_only_when_a_new_filing_lands() -> None:
    """Review M6: Z carries the market cap. A new filing with Z 2.0 holds; the price then falls
    and tonight's Z reads 1.5 on the same filing: no sale until the next filing says so."""
    newer = "0000000001-26-000002"
    state, events = run(leg("value"), [bar(1, 105.0)], DayFacts(altman_z=2.0, latest_accn=newer))
    assert events == [] and state.seen_accn == newer
    state, events = run(state, [bar(2, 95.0)], DayFacts(altman_z=1.5, latest_accn=newer))
    assert events == []
    third = DayFacts(altman_z=1.5, latest_accn="0000000001-26-000003")
    _, events = run(state, [bar(3, 95.0)], third)
    assert events == [("thesis", 1.0)]


@pytest.mark.parametrize("policy", POLICIES)
def test_an_8k_thesis_item_sells_under_every_policy(policy) -> None:
    state, events = step(leg(policy), bar(1, 104.0), None, CFG, Reeval(thesis="8-K item 1.03"))
    assert [(e.kind, e.fraction, e.detail) for e in events] == [("thesis", 1.0, "8-K item 1.03")]
    assert state.pending == 1.0


@pytest.mark.parametrize("policy", POLICIES)
def test_a_down_shock_raises_only_fulls_stop_and_never_lowers_it(policy) -> None:
    """Spec §7.1: shock stops apply under full only; the stop tightens, never loosens."""
    state, events = step(leg(policy), bar(1, 99.0), None, CFG, Reeval(stop_at_least=96.0))
    if policy == "full":
        assert state.stop == pytest.approx(96.0) and [e.kind for e in events] == ["shock"]
        state, events = step(state, bar(2, 98.0), None, CFG, Reeval(stop_at_least=90.0))
        assert state.stop == pytest.approx(96.0) and events == []
        _, events = step(state, bar(3, 95.5), None, CFG)
        assert [(e.kind, e.fraction) for e in events] == [("stop", 1.0)]
    else:
        assert state.stop is None and events == []


def test_an_up_shock_arms_the_trail_from_the_shock_low() -> None:
    """Spec §7.1: the trail arms at once, trailing from the shock session's low; at the half-way
    mark §7's breakeven floor takes over."""
    state, events = step(leg(), bar(1, 101.0, low=97.0), None, CFG, Reeval(arm_from=97.0))
    assert [e.kind for e in events] == ["shock"]
    assert state.armed and state.trail_floor == 97.0 and state.stop == pytest.approx(97.0)
    _, events = step(state, bar(2, 96.5), None, CFG)
    assert [(e.kind, e.fraction) for e in events] == [("trail", 1.0)]
    later, events = step(state, bar(2, 111.0, atr14=2.0), None, CFG)
    assert events == [] and later.trail_floor is None
    assert later.stop == pytest.approx(105.0)  # 111 - 3 x 2, above the breakeven


def test_the_effective_only_proposal_is_noted_once_per_episode() -> None:
    """Review M14: one tap proposal per episode, and none on the baseline track, where Python's
    value says the same thing (its exit waits for a re-mark)."""
    closes = [115.0, 116.0, 105.0, 115.0]
    _, events = run(
        leg("hold12", fv=120.0, effective=100.0),
        [bar(i + 1, c, sma50=120.0) for i, c in enumerate(closes)],
    )
    assert events == [("proposal", 0.0), ("proposal", 0.0)]
    _, events = run(
        leg("hold12", fv=100.0), [bar(i + 1, c, sma50=120.0) for i, c in enumerate(closes)]
    )
    assert events == []


def test_a_rebase_scales_every_price_level_and_no_return() -> None:
    state, _ = run(leg(), [bar(1, 121.0, atr14=2.0), bar(2, 123.0, open=122.0, atr14=2.0)])
    half = state.rebased(0.5)
    assert (half.entry_price, half.fair_value, half.stop, half.highest_close) == (
        50.0,
        60.0,
        pytest.approx(state.stop / 2),
        61.5,
    )
    assert half.last_close == 61.5 and half.proceeds == pytest.approx(state.proceeds / 2)
    assert (half.remaining, half.max_drawdown, half.peak_value) == (
        state.remaining,
        state.max_drawdown,
        state.peak_value,
    )
