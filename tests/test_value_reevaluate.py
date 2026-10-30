"""Re-evaluation (value book spec §7.1, §16): the sector-ETF residual model, every trigger on a
fixture, severity and the debounce, the plan actions, and that news or earnings alone change no
level."""

from __future__ import annotations

import math
from datetime import date, timedelta

import pytest

from src.common.config import ValueExitsCfg, ValueReevaluationCfg
from src.common.value_types import DayBar, FilingEvent, NewsVolume
from src.value import reevaluate as rv
from src.value.exits import open_leg, step
from src.value.residuals import Move, daily_returns, moves

CFG = ValueReevaluationCfg()
D0 = date(2026, 1, 1)
# The ETF's returns repeat +1%, +1%, -1%, -1%; the name's are 1.5x the ETF's plus a residual of
# +0.5%, -0.5%, ... Over whole cycles the two are uncorrelated, so least squares gives beta 1.5 and
# alpha 0 exactly, and the residual's sample sd over 60 sessions is 0.005 x sqrt(60 / 59).
SIGMA = 0.005 * math.sqrt(60 / 59)


def _series(extra_etf: list[float], extra_name: list[float]):
    etf_r = [(0.01, 0.01, -0.01, -0.01)[i % 4] for i in range(124)] + extra_etf
    noise = [(0.005, -0.005)[i % 2] for i in range(124)]
    name_r = [1.5 * e + n for e, n in zip(etf_r, noise, strict=False)] + extra_name
    days = [D0 + timedelta(days=i) for i in range(len(etf_r) + 1)]

    def closes(rets: list[float]) -> list[tuple[date, float]]:
        out, c = [(days[0], 100.0)], 100.0
        for d, r in zip(days[1:], rets, strict=True):
            c *= 1.0 + r
            out.append((d, c))
        return out

    return closes(name_r), closes(etf_r), days


def test_a_shock_day_is_measured_in_residual_standard_deviations() -> None:
    name, etf, days = _series([0.0, -0.01], [-0.04, -0.012])
    out = moves(name, etf, [days[125], days[126]], CFG)
    shock = out[days[125]]
    assert shock.beta == pytest.approx(1.5) and shock.ret == pytest.approx(-0.04)
    assert shock.z == pytest.approx(-0.04 / SIGMA)  # -7.93: Major, down
    calm = out[days[126]]  # -1.2% on a -1% sector day is +0.3% net of 1.5 x the ETF
    assert calm.z is not None and abs(calm.z) < 3.0


def test_a_slow_bleed_is_a_drift_no_single_day_flags() -> None:
    """Five sessions of -0.8% net of the sector: no day reaches |z| 3, the sum does
    (-0.04 / (sigma x sqrt 5) = -3.55), measured with the fit from before the window."""
    name, etf, days = _series([0.0] * 5, [-0.008] * 5)
    out = moves(name, etf, days[125:130], CFG)
    assert all(m.z is not None and abs(m.z) < CFG.abnormal_z for m in out.values())
    assert out[days[129]].drift_z == pytest.approx(-0.04 / (SIGMA * math.sqrt(5)))


def test_a_short_history_has_no_z_and_a_missing_etf_day_keeps_the_raw_move() -> None:
    name, etf, days = _series([0.0], [-0.04])
    short = moves(name[-50:], etf[-50:], [days[125]], CFG)[days[125]]
    assert short.z is None and short.ret == pytest.approx(-0.04)
    gap = moves(name, etf[:-1], [days[125]], CFG)[days[125]]
    assert gap.z is None and gap.ret == pytest.approx(-0.04)
    assert daily_returns([(D0, 10.0), (D0 + timedelta(days=1), 11.0)]) == {
        D0 + timedelta(days=1): pytest.approx(0.1)
    }


DAY = date(2026, 3, 10)


def _fire(**kw) -> list[tuple[str, str, str | None]]:
    base: dict = {
        "day": DAY,
        "after": DAY - timedelta(days=1),
        "move": None,
        "filings": [],
        "earnings": [],
        "news": None,
        "regime_stepped": False,
        "last_reevaluation": DAY - timedelta(days=10),
        "cfg": CFG,
    }
    base.update(kw)
    return [(t.kind, t.severity, t.direction) for t in rv.session_triggers(**base)]


def test_each_trigger_fires_on_its_own_fixture() -> None:
    assert _fire(move=Move(DAY, -0.05, -3.2, None, 1.1)) == [("move", "major", "down")]
    assert _fire(move=Move(DAY, 0.02, 2.9, None, 1.1)) == []
    assert _fire(move=Move(DAY, 0.12, None, None, None)) == [("move", "major", "up")]  # backstop
    assert _fire(move=Move(DAY, 0.09, None, None, None)) == []
    assert _fire(move=Move(DAY, -0.01, -0.5, -3.1, 1.0)) == [("drift", "minor", "down")]
    assert _fire(earnings=[DAY]) == [("earnings", "minor", None)]
    assert _fire(earnings=[DAY - timedelta(days=1)]) == []  # already checked
    assert _fire(earnings=[DAY], move=Move(DAY, -0.05, -3.2, None, 1.1)) == [
        ("move", "major", "down"),
        ("earnings", "major", None),  # Minor, Major with trigger 1
    ]
    assert _fire(news=NewsVolume(last_24h=12, daily_median_30d=3.0)) == [("news", "minor", None)]
    assert _fire(news=NewsVolume(last_24h=11, daily_median_30d=3.0)) == []  # below 4 x 3
    assert _fire(news=NewsVolume(last_24h=4, daily_median_30d=0.0)) == []  # below 5 items
    assert _fire(regime_stepped=True) == [("regime", "minor", None)]
    assert _fire(last_reevaluation=DAY - timedelta(days=90)) == [("quiet", "minor", None)]
    assert _fire(last_reevaluation=DAY - timedelta(days=89)) == []


def test_filings_by_form_and_8k_item() -> None:
    def f(form: str, items: list[str], filed: date = DAY) -> FilingEvent:
        return FilingEvent(accn="a", form=form, filed=filed, items=items)

    assert _fire(filings=[f("10-Q", [])]) == [("filing", "minor", None)]
    assert _fire(filings=[f("8-K", ["2.02", "9.01"])]) == []  # results, exhibits: no trigger
    assert _fire(filings=[f("8-K", ["5.02"])]) == [("filing", "minor", None)]
    assert _fire(filings=[f("8-K/A", ["9.01", "4.02"])]) == [("filing", "major", None)]
    assert _fire(filings=[f("10-K", [], DAY - timedelta(days=1))]) == []
    got = rv.session_triggers(
        day=DAY,
        after=DAY - timedelta(days=3),
        move=None,
        filings=[f("8-K", ["1.03"], DAY - timedelta(days=2))],
        earnings=[],
        news=None,
        regime_stepped=False,
        last_reevaluation=DAY,
        cfg=CFG,
    )
    assert [(t.item, t.detail) for t in got] == [("1.03", "8-K item 1.03 (a)")]


def test_the_regime_trigger_fires_on_a_step_into_stressed_or_crisis() -> None:
    assert rv.regime_stepped("cautious", "stressed", CFG)
    assert rv.regime_stepped("stressed", "crisis", CFG)
    assert not rv.regime_stepped("stressed", "stressed", CFG)  # no step
    assert not rv.regime_stepped("crisis", "stressed", CFG)  # easing is not a step into
    assert not rv.regime_stepped("normal", "cautious", CFG)
    assert not rv.regime_stepped(None, "crisis", CFG) and not rv.regime_stepped(
        "unknown", "crisis", CFG
    )


def test_severity_and_the_debounce() -> None:
    minor = rv.Trigger(kind="news", severity="minor")
    major = rv.Trigger(kind="move", severity="major", direction="down")
    assert rv.severity([]) is None and rv.severity([minor]) == "minor"
    assert rv.severity([minor, major]) == "major"
    assert rv.joins("minor", 3, "minor", CFG) and rv.joins("major", 1, "minor", CFG)
    assert not rv.joins("minor", 4, "minor", CFG)  # more than three sessions on
    assert not rv.joins("minor", 1, "major", CFG)  # a higher severity opens a new one
    assert not rv.joins(None, None, "minor", CFG)


def test_the_plan_actions_of_a_session() -> None:
    bar = DayBar(date=DAY, close=92.0, low=90.0)
    before = DayBar(date=DAY - timedelta(days=1), close=100.0, atr14=2.0)
    down = [rv.Trigger(kind="move", severity="major", direction="down")]
    act = rv.plan_actions(down, bar, before, CFG)
    assert act is not None and act.stop_at_least == pytest.approx(89.0)  # 90 - 0.5 x 2
    assert rv.plan_actions(down, bar, DayBar(date=DAY, close=100.0), CFG) is None  # no ATR
    up = [rv.Trigger(kind="move", severity="major", direction="up")]
    act = rv.plan_actions(up, DayBar(date=DAY, close=110.0, low=103.0), before, CFG)
    assert act is not None and act.arm_from == 103.0 and act.stop_at_least is None
    k8 = [rv.Trigger(kind="filing", severity="major", item="4.02")]
    act = rv.plan_actions(k8, bar, before, CFG)
    assert act is not None and act.thesis == "8-K item 4.02"
    minor = [
        rv.Trigger(kind="news", severity="minor"),
        rv.Trigger(kind="earnings", severity="minor"),
        rv.Trigger(kind="drift", severity="minor", direction="down"),
        rv.Trigger(kind="filing", severity="minor", item="5.02"),
    ]
    assert rv.plan_actions(minor, bar, before, CFG) is None


def test_news_or_earnings_alone_move_no_level_under_any_policy() -> None:
    """Spec §7.1 fence: trigger 5 may only open a re-evaluation; it moves no stop, no fair value
    and sends nothing."""
    triggers = [
        rv.Trigger(kind="news", severity="minor"),
        rv.Trigger(kind="earnings", severity="minor"),
    ]
    bar = DayBar(date=DAY, close=99.0, low=95.0, atr14=2.0)
    assert rv.plan_actions(triggers, bar, bar, CFG) is None
    for policy in ("full", "value", "hold12"):
        leg = open_leg(
            policy,  # type: ignore[arg-type]
            entry_date=DAY,
            entry_price=100.0,
            atr14=2.0,
            fair_value=120.0,
            effective_fair_value=120.0,
            fv_accn="a",
            cfg=ValueExitsCfg(),
        )
        after, events = step(leg, bar, None, ValueExitsCfg(), None)
        assert (after.stop, after.fair_value, after.pending, events) == (leg.stop, 120.0, 0.0, [])


def test_a_level_change_waits_for_the_close() -> None:
    """The shock session's low exists only at its close: the raised stop is tested from the next
    session, never against the close that set it."""
    leg = open_leg(
        "full",
        entry_date=DAY,
        entry_price=100.0,
        atr14=2.0,
        fair_value=120.0,
        effective_fair_value=120.0,
        fv_accn="a",
        cfg=ValueExitsCfg(),
    )
    bar = DayBar(date=DAY, close=95.0, low=94.5)
    act = rv.plan_actions(
        [rv.Trigger(kind="move", severity="major", direction="down")],
        bar,
        DayBar(date=DAY, close=100.0, atr14=0.2),
        CFG,
    )
    assert act is not None and act.stop_at_least == pytest.approx(94.4)
    after, events = step(leg, bar, None, ValueExitsCfg(), act)
    assert [e.kind for e in events] == ["shock"] and after.pending == 0.0
    _, events = step(after, DayBar(date=DAY + timedelta(days=1), close=94.3), None, ValueExitsCfg())
    assert [(e.kind, e.fraction) for e in events] == [("stop", 1.0)]


def test_an_unknown_low_means_no_shock_level() -> None:
    """Review minor: ruling 14, unknown is never zero. A bar with no low must not stand its close
    in for it (a close above the low would tighten the stop or set the trail's floor higher)."""
    before = DayBar(date=DAY - timedelta(days=1), close=100.0, atr14=2.0)
    bar = DayBar(date=DAY, close=92.0)
    down = [rv.Trigger(kind="move", severity="major", direction="down")]
    up = [rv.Trigger(kind="move", severity="major", direction="up")]
    assert rv.plan_actions(down, bar, before, CFG) is None
    assert rv.plan_actions(up, bar, before, CFG) is None
