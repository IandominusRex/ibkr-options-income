"""The shadow record (value book spec §6.8, §7, §7.1, §12): READY entries at the next open,
control groups, re-entry, the three policies' legs, fixed-horizon returns against SPY, the
mechanical rebase, re-evaluations with the original-plan twin, and the ranked monthly record."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pandas as pd
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import src.value.store as store
from src.common.config import get_config
from src.common.value_types import DayBar, FilingEvent, NewsVolume
from src.research.store.models import Base, DailyBarRow
from src.value import shadow
from src.value.exits import LegState
from src.value.scorecard import build_scorecard
from src.value.store import (
    ValueRankedRow,
    ValueReevaluationRow,
    ValueShadowEventRow,
    ValueShadowLegRow,
    ValueShadowRow,
    init_value_db,
    value_session,
)
from tests.value_fixtures import AS_OF, financials, inputs

CFG = get_config().value
NOW = datetime(2026, 4, 1, 10, 0)
SESSIONS = [d.date() for d in pd.bdate_range(start=AS_OF, periods=140)]  # SESSIONS[0] = AS_OF


@pytest.fixture()
def value_db(tmp_path, monkeypatch):
    monkeypatch.setattr(
        store, "_resolve_url", lambda: f"sqlite:///{(tmp_path / 'value.db').as_posix()}"
    )
    store.reset_engine()
    init_value_db()
    yield
    store.reset_engine()


def bars(closes: list[float], *, opens: list[float] | None = None, start: int = 0, **kw):
    """DayBars on consecutive sessions from SESSIONS[start]."""
    return [
        DayBar(
            date=SESSIONS[start + i],
            close=c,
            open=(opens[i] if opens else c),
            **kw,
        )
        for i, c in enumerate(closes)
    ]


def ready(symbol: str = "STDY", close: float = 30.0):
    return build_scorecard(inputs(symbol=symbol, close=close), CFG)


def sick(symbol: str = "SICK", close: float = 25.0):
    fin = financials(net_income=[300, -266, -238, 212, 187])  # health fails, still cheap
    return build_scorecard(inputs(symbol=symbol, close=close, fin=fin), CFG)


def _open(cards, tags=None, atr=None):
    tags = tags or {c.symbol: "trading" for c in cards}
    with value_session() as s:
        return shadow.open_signals(s, cards, tags, atr or {}, live_policy="value", now=NOW)


def _rows():
    with value_session() as s:
        return [
            (r.kind, r.list_name, r.symbol, r.status)
            for r in s.scalars(select(ValueShadowRow).order_by(ValueShadowRow.id))
        ]


def test_a_ready_signal_waits_for_the_next_sessions_open(value_db) -> None:
    assert _open([ready()]) == {"ready": 2, "control_valuation": 0, "control_health": 0}
    market = {
        "STDY": bars([30.0, 31.5], opens=[29.0, 31.0]),
        "SPY": bars([500.0, 502.0], opens=[499.0, 501.0]),
    }
    with value_session() as s:
        assert shadow.fill_pending(s, market, CFG) == (2, 0)
    with value_session() as s:
        row = s.scalars(select(ValueShadowRow)).first()
        assert (row.status, row.entry_date, row.entry_price, row.spy_entry_price) == (
            "open",
            SESSIONS[1],
            31.0,
            501.0,
        )
        policies = sorted(leg.policy for leg in s.scalars(select(ValueShadowLegRow)))
        assert policies == ["full", "full", "hold12", "hold12", "value", "value"]


def test_control_groups_enter_only_on_a_night_with_a_new_ready_entry(value_db) -> None:
    cards = [ready(), ready("DEAR", 45.0), sick()]  # DEAR: deep WAIT, growth READY
    assert _open(cards) == {"ready": 3, "control_valuation": 1, "control_health": 2}
    assert ("control_valuation", "deep_value", "DEAR", "pending") in _rows()
    assert ("control_health", "quality_growth", "SICK", "pending") in _rows()
    # The next night: the same names, nothing new is READY, so no control enters either.
    assert _open(cards) == {"ready": 0, "control_valuation": 0, "control_health": 0}
    market = {s: bars([30.0, 31.0]) for s in ("STDY", "DEAR", "SICK", "SPY")}
    with value_session() as s:
        assert shadow.fill_pending(s, market, CFG) == (6, 0)
    with value_session() as s:
        assert len(s.scalars(select(ValueShadowLegRow)).all()) == 9  # READY entries only: 3 x 3


def test_a_looked_up_name_never_enters_the_shadow_record(value_db) -> None:
    assert _open([ready()], tags={"STDY": "lookup"})["ready"] == 0


def test_a_ready_key_reenters_only_once_its_live_policy_leg_has_exited(value_db) -> None:
    _open([ready()])
    market = {"STDY": bars([30.0, 31.0]), "SPY": bars([500.0, 500.0])}
    with value_session() as s:
        shadow.fill_pending(s, market, CFG)
    assert _open([ready()])["ready"] == 0  # the value legs still hold
    with value_session() as s:
        for leg in s.scalars(select(ValueShadowLegRow).where(ValueShadowLegRow.policy == "value")):
            leg.closed = True
    assert _open([ready()])["ready"] == 2


def test_the_legs_run_each_policy_and_record_every_event(value_db) -> None:
    _open([ready()], atr={"STDY": 0.6})  # full's stop: max(31 - 1.8, 31 x 0.85) = 29.2
    closes = [30.0, 31.0, 29.0, 28.0]
    market = {
        "STDY": bars(closes, opens=[30.0, 31.0, 30.0, 28.5]),
        "SPY": bars([500.0] * 4, opens=[500.0, 500.0, 505.0, 510.0]),
    }
    with value_session() as s:
        shadow.fill_pending(s, market, CFG)
    cards = {"STDY": ready()}
    with value_session() as s:
        events, frozen = shadow.step_legs(s, market, cards, CFG)
        assert frozen == 0 and events == 4  # full stops on both lists: a stop and a fill each
    with value_session() as s:
        full = s.scalars(
            select(ValueShadowLegRow).where(ValueShadowLegRow.policy == "full")
        ).first()
        assert full.closed and full.exit_date == SESSIONS[3]
        assert full.ret_exit == pytest.approx(28.5 / 31.0 - 1.0)  # sold at the 28.50 open
        assert full.spy_ret_exit == pytest.approx(510.0 / 500.0 - 1.0)
        kinds = [e.kind for e in s.scalars(select(ValueShadowEventRow)) if e.policy == "full"]
        assert kinds == ["stop", "fill", "stop", "fill"]
        value = s.scalars(
            select(ValueShadowLegRow).where(ValueShadowLegRow.policy == "value")
        ).first()
        assert not value.closed and value.sessions == 3 and value.last_step == SESSIONS[3]


def test_horizons_mark_h_sessions_after_the_entry_session_against_spy(value_db) -> None:
    _open([ready()])
    closes = [30.0] + [31.0] * 21 + [33.0] + [32.0] * 30
    spy = [500.0] * 22 + [510.0] + [505.0] * 30
    market = {"STDY": bars(closes), "SPY": bars(spy)}
    with value_session() as s:
        shadow.fill_pending(s, market, CFG)  # entry: SESSIONS[1] at 31.00, SPY 500.00
    with value_session() as s:
        assert shadow.mark_horizons(s, market) == 2  # 21 for both lists; 63 not yet
    with value_session() as s:
        row = s.scalars(select(ValueShadowRow)).first()
        assert row.ret_21 == pytest.approx(33.0 / 31.0 - 1.0)  # SESSIONS[22]'s close
        assert row.spy_21 == pytest.approx(0.02)
        assert row.ret_63 is None


def test_a_horizon_waits_for_the_names_bar_then_settles_for_the_last_close(value_db) -> None:
    _open([ready()])
    stdy = bars([30.0] + [31.0] * 10 + [29.0])  # the name's bars stop at SESSIONS[11]
    with value_session() as s:
        shadow.fill_pending(s, {"STDY": stdy, "SPY": bars([500.0] * 2)}, CFG)
    with value_session() as s:  # h21 is SESSIONS[22]; only 2 SPY sessions after it so far
        assert shadow.mark_horizons(s, {"STDY": stdy, "SPY": bars([500.0] * 25)}) == 0
    with value_session() as s:  # 5 SPY sessions after it: settle for the last close
        assert shadow.mark_horizons(s, {"STDY": stdy, "SPY": bars([500.0] * 28)}) == 2
    with value_session() as s:
        row = s.scalars(select(ValueShadowRow)).first()
        assert row.ret_21 == pytest.approx(29.0 / 31.0 - 1.0)
        assert "h21: no bar since" in row.status_detail


def test_an_entry_closes_once_every_horizon_is_marked_and_every_leg_has_exited(value_db) -> None:
    _open([ready()])
    with value_session() as s:
        shadow.fill_pending(s, {"STDY": bars([30.0, 31.0]), "SPY": bars([500.0] * 2)}, CFG)
    with value_session() as s:
        for row in s.scalars(select(ValueShadowRow)):
            for h in shadow.HORIZONS:
                setattr(row, f"ret_{h}", 0.0)
                setattr(row, f"spy_{h}", 0.0)
    with value_session() as s:
        assert shadow.close_finished(s, SESSIONS[130]) == 0  # the legs still hold
    with value_session() as s:
        for leg in s.scalars(select(ValueShadowLegRow)):
            leg.closed = True
    with value_session() as s:
        assert shadow.close_finished(s, SESSIONS[130]) == 2
    assert {r[3] for r in _rows()} == {"closed"}


def _legs(plan: str = "main") -> dict[tuple[str, str], LegState]:
    with value_session() as s:
        rows = {r.id: r.list_name for r in s.scalars(select(ValueShadowRow))}
        return {
            (rows[g.shadow_id], g.policy): LegState.model_validate_json(g.state_json)
            for g in s.scalars(select(ValueShadowLegRow).where(ValueShadowLegRow.plan == plan))
        }


def test_a_split_rebases_the_entry_instead_of_firing_its_stop(value_db) -> None:
    """Spec §7.1: a corporate action is not a trigger; the levels are rebased mechanically."""
    _open([ready()], atr={"STDY": 0.6})  # full's stop: max(31 - 1.8, 31 x 0.85) = 29.2
    with value_session() as s:
        shadow.fill_pending(s, {"STDY": bars([30.0, 31.0]), "SPY": bars([500.0] * 2)}, CFG)
    split = {"STDY": bars([15.0, 15.5, 15.4]), "SPY": bars([500.0] * 3)}  # 2-for-1 rewrite
    with value_session() as s:
        assert shadow.rebase(s, split, SESSIONS[2]) == (2, 0)
    with value_session() as s:
        assert shadow.step_legs(s, split, {}, CFG) == (0, 0)  # 15.40 is above the halved 14.60
    assert {r[3] for r in _rows()} == {"open"}
    legs = _legs()
    assert legs[("deep_value", "full")].stop == pytest.approx(14.6)
    assert legs[("deep_value", "value")].entry_price == pytest.approx(15.5)
    with value_session() as s:
        row = s.scalars(select(ValueShadowRow)).first()
        assert row.entry_price == pytest.approx(15.5) and row.atr14 == pytest.approx(0.3)
        kinds = [(e.kind, e.policy) for e in s.scalars(select(ValueShadowEventRow))]
    assert kinds == [("rebase", "all"), ("rebase", "all")]
    with value_session() as s:  # the same bars again: nothing more to rebase
        assert shadow.rebase(s, split, SESSIONS[2]) == (0, 0)


def test_a_rewrite_after_the_entry_bar_left_the_window_still_rebases(value_db) -> None:
    """The provider serves ~2 years, so a long-held entry's own bar leaves the window: the
    reference is the bar on the legs' last stepped session against the close they saw there.
    A dividend adjustment (x 0.99) is rebased the same way as a split."""
    _open([ready()])
    with value_session() as s:
        shadow.fill_pending(s, {"STDY": bars([30.0, 31.0]), "SPY": bars([500.0] * 2)}, CFG)
    market = {"STDY": bars([30.0, 31.0, 32.0, 33.0]), "SPY": bars([500.0] * 4)}
    with value_session() as s:
        shadow.step_legs(s, market, {}, CFG)
    assert all(leg.last_close == 33.0 for leg in _legs().values())
    split = {"STDY": bars([16.0, 16.5, 16.6], start=2), "SPY": bars([500.0] * 3, start=2)}
    with value_session() as s:
        assert shadow.rebase(s, split, SESSIONS[4]) == (2, 0)
    assert _legs()[("deep_value", "value")].entry_price == pytest.approx(15.5)
    with value_session() as s:
        shadow.step_legs(s, split, {}, CFG)  # the legs now last saw 16.60 on SESSIONS[4]
    # An ex-dividend bar arrives on SESSIONS[5] and the provider adjusts every bar before it.
    adjusted = {"STDY": bars([16.6 * 0.99, 16.4], start=4), "SPY": bars([500.0] * 2, start=4)}
    with value_session() as s:
        assert shadow.rebase(s, adjusted, SESSIONS[5]) == (2, 0)
    assert _legs()[("deep_value", "value")].entry_price == pytest.approx(15.5 * 0.99)


def test_a_part_2_frozen_entry_is_rebased_and_reopened(value_db) -> None:
    """Part 2 froze an entry as rebase_needed (ruling 16); Part 3 un-freezes it. One with no
    bar left to measure against stays frozen and says so in the count."""
    _open([ready()])
    with value_session() as s:
        shadow.fill_pending(s, {"STDY": bars([30.0, 31.0]), "SPY": bars([500.0] * 2)}, CFG)
        for row in s.scalars(select(ValueShadowRow)):
            row.status = "rebase_needed"
    with value_session() as s:
        assert shadow.rebase(s, {"STDY": bars([10.0], start=5)}, SESSIONS[5]) == (0, 2)
    with value_session() as s:
        assert shadow.rebase(s, {"STDY": bars([15.0, 15.5])}, SESSIONS[5]) == (2, 0)
    assert {r[3] for r in _rows()} == {"open"}


def _reevaluations() -> list[tuple[str, str, date, date, list[str]]]:
    with value_session() as s:
        return [
            (
                r.list_name,
                r.severity,
                r.session,
                r.last_session,
                [t["kind"] for t in json.loads(r.triggers_json)],
            )
            for r in s.scalars(select(ValueReevaluationRow).order_by(ValueReevaluationRow.id))
        ]


def _entered(atr: float = 2.0) -> None:
    _open([ready()], atr={"STDY": atr})  # full's stop: max(31 - 3 x 2, 31 x 0.85) = 26.35
    with value_session() as s:
        shadow.fill_pending(s, {"STDY": bars([30.0, 31.0]), "SPY": bars([500.0] * 2)}, CFG)


def test_a_down_shock_raises_fulls_main_stop_and_starts_the_original_twin(value_db) -> None:
    """Spec §7.1: a Major down-move (here the raw 10% backstop: the history is short) opens a
    re-evaluation; under full the stop rises to the shock low - 0.5 x the ATR before the shock
    (27.00 - 0.5 x 0.60 = 26.70); the original plan keeps 26.35. The next close, 26.60, sells
    the re-evaluated full leg only."""
    _entered()
    stdy = [
        DayBar(date=SESSIONS[0], close=30.0, open=30.0),
        DayBar(date=SESSIONS[1], close=31.0, open=31.0, atr14=0.6),
        DayBar(date=SESSIONS[2], close=27.2, open=30.0, low=27.0, atr14=1.0),
        DayBar(date=SESSIONS[3], close=26.6, open=27.0, low=26.5, atr14=1.0),
    ]
    market = {"STDY": stdy, "SPY": bars([500.0] * 4)}
    ctx = shadow.ReevalContext(etf_for={"STDY": "XLK"})
    with value_session() as s:
        events, opened = shadow.step_legs(s, market, {}, CFG, as_of=SESSIONS[3], context=ctx)
    assert opened == 2  # one per entry: the deep-value and quality-growth READY entries
    assert _reevaluations() == [
        ("deep_value", "major", SESSIONS[2], SESSIONS[2], ["move"]),
        ("quality_growth", "major", SESSIONS[2], SESSIONS[2], ["move"]),
    ]
    main, original = _legs("main"), _legs("original")
    assert main[("deep_value", "full")].pending == 1.0  # sold on the 26.60 close
    assert original[("deep_value", "full")].stop == pytest.approx(26.35)
    assert original[("deep_value", "full")].pending == 0.0
    assert main[("deep_value", "value")].pending == 0.0  # value: no tight stop to move
    with value_session() as s:
        r = s.scalars(select(ValueReevaluationRow)).first()
        before, after = json.loads(r.plan_before_json), json.loads(r.plan_after_json)
    assert before["full"]["stop"] == pytest.approx(26.35)
    assert after["full"]["stop"] == pytest.approx(26.7)
    assert after["value"] == before["value"]


def test_an_8k_bankruptcy_item_exits_every_main_leg_and_no_original_one(value_db) -> None:
    """Spec §7.1: an 8-K item 1.03 is a thesis exit on its own, under every policy. The original
    twins hold: that is the comparison the report reads. The live leg's exit frees the key."""
    _entered()
    market = {"STDY": bars([30.0, 31.0, 31.5, 31.2]), "SPY": bars([500.0] * 4)}
    filing = FilingEvent(accn="0000000001-26-000009", form="8-K", filed=SESSIONS[2], items=["1.03"])
    ctx = shadow.ReevalContext(filings={"STDY": [filing]})
    with value_session() as s:
        shadow.step_legs(s, market, {}, CFG, as_of=SESSIONS[3], context=ctx)
    main, original = _legs("main"), _legs("original")
    assert all(leg.closed for leg in main.values())  # sold at SESSIONS[3]'s open
    assert not any(leg.closed or leg.pending for leg in original.values())
    assert _reevaluations()[0][1:] == ("major", SESSIONS[2], SESSIONS[2], ["filing"])
    assert _open([ready()])["ready"] == 2  # the live (value) main legs have exited


def test_triggers_within_three_sessions_join_the_open_reevaluation(value_db) -> None:
    """Spec §7.1: one re-evaluation is open per position; a trigger within three sessions joins
    it unless it is more severe. Earnings on SESSIONS[2] open one; a 10-Q two sessions later
    joins; a Major 8-K a session after that opens a second; a 10-Q six sessions on, a third."""
    _entered()
    market = {"STDY": bars([30.0] + [31.0] * 11), "SPY": bars([500.0] * 12)}
    filings = [
        FilingEvent(accn="q", form="10-Q", filed=SESSIONS[4]),
        FilingEvent(accn="k", form="8-K", filed=SESSIONS[5], items=["4.02"]),
        FilingEvent(accn="q2", form="10-Q/A", filed=SESSIONS[11]),
    ]
    ctx = shadow.ReevalContext(filings={"STDY": filings}, earnings={"STDY": [SESSIONS[2]]})
    with value_session() as s:
        shadow.step_legs(s, market, {}, CFG, as_of=SESSIONS[11], context=ctx)
    deep = [r for r in _reevaluations() if r[0] == "deep_value"]
    assert [r[1:] for r in deep] == [
        ("minor", SESSIONS[2], SESSIONS[4], ["earnings", "filing"]),
        ("major", SESSIONS[5], SESSIONS[5], ["filing"]),
    ]  # the 8-K 4.02 sold every main leg, so nothing re-evaluates after it
    assert _legs("original")[("deep_value", "value")].closed is False


def test_news_and_the_regime_count_on_tonights_session_only(value_db) -> None:
    """They are measured tonight: a catch-up night attributes them to the session dated as_of."""
    _entered()
    market = {"STDY": bars([30.0, 31.0, 31.2, 31.1]), "SPY": bars([500.0] * 4)}
    ctx = shadow.ReevalContext(
        news={"STDY": NewsVolume(last_24h=20, daily_median_30d=2.0)}, regime_stepped=True
    )
    with value_session() as s:
        shadow.step_legs(s, market, {}, CFG, as_of=SESSIONS[3], context=ctx)
    assert {r[2] for r in _reevaluations()} == {SESSIONS[3]}
    assert _reevaluations()[0][4] == ["news", "regime"]
    assert all(not leg.pending for leg in _legs("main").values())  # neither moves a level


def test_a_catch_up_night_reads_tonights_facts_on_tonights_session_only(value_db) -> None:
    """Review M1: a filing scored tonight is not known on the sessions the night steps over.
    The re-mark lands on SESSIONS[3] (tonight), not on the entry session."""
    _entered()
    market = {"STDY": bars([30.0, 31.0, 31.5, 31.4]), "SPY": bars([500.0] * 4)}
    newer = build_scorecard(
        inputs(symbol="STDY", close=31.4, fin=financials(accn="0000000001-26-000002")), CFG
    )
    with value_session() as s:
        shadow.step_legs(s, market, {"STDY": newer}, CFG, as_of=SESSIONS[3])
    with value_session() as s:
        remarks = {e.day for e in s.scalars(select(ValueShadowEventRow)) if e.kind == "remark"}
    assert remarks == {SESSIONS[3]}


def test_a_signal_that_never_gets_a_bar_is_voided(value_db) -> None:
    _open([ready()])
    market = {"STDY": bars([30.0]), "SPY": bars([500.0] * 6)}
    with value_session() as s:
        assert shadow.fill_pending(s, market, CFG) == (0, 2)
    assert {r[3] for r in _rows()} == {"void"}


@pytest.fixture()
def research(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'research.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _bar(s: Session, symbol: str, day: date, close: float) -> None:
    s.add(DailyBarRow(symbol=symbol, date=day, open=close, high=close, low=close, close=close))


def test_the_ranked_record_forms_monthly_and_closes_at_the_next_formation(
    value_db, research
) -> None:
    names = [f"S{i}" for i in range(10)]
    cards = [ready(n, 20.0 + 2 * i) for i, n in enumerate(names)]  # S0 cheapest: ranks top
    april = date(2026, 4, 1)
    for i, n in enumerate(names):
        _bar(research, n, AS_OF, 20.0 + 2 * i)
        _bar(research, n, april, (20.0 + 2 * i) * (1.10 if i == 0 else 1.0))
    _bar(research, "SPY", AS_OF, 500.0)
    _bar(research, "SPY", april, 505.0)
    research.flush()
    with value_session() as s:
        assert shadow.run_ranked(
            s, research, cards, set(names), as_of=AS_OF, version="v2", digest="x"
        ) == (6, 0)  # three buckets per list
    with value_session() as s:
        top = s.scalars(
            select(ValueRankedRow).where(
                ValueRankedRow.list_name == "deep_value", ValueRankedRow.bucket == "top"
            )
        ).one()
        assert json.loads(top.members_json) == ["S0"] and top.n == 1
    with value_session() as s:  # the same month again: nothing
        assert shadow.run_ranked(
            s, research, cards, set(names), as_of=AS_OF, version="v2", digest="x"
        ) == (0, 0)
    with value_session() as s:
        assert shadow.run_ranked(
            s, research, cards, set(names), as_of=april, version="v2", digest="x"
        ) == (6, 6)
    with value_session() as s:
        closed = {
            (r.list_name, r.bucket): (r.ret, r.spy_ret, r.missing)
            for r in s.scalars(select(ValueRankedRow).where(ValueRankedRow.closed_on == april))
        }
    assert closed[("deep_value", "top")][0] == pytest.approx(0.10)
    assert closed[("deep_value", "bottom")][0] == pytest.approx(0.0)
    assert closed[("deep_value", "all")][0] == pytest.approx(0.01)  # 10% / 10 names
    assert closed[("deep_value", "top")][1] == pytest.approx(0.01)
    assert closed[("deep_value", "top")][2] == 0


def test_process_runs_a_night_in_order(value_db, research) -> None:
    for i, d in enumerate(SESSIONS[:3]):
        _bar(research, "STDY", d, 30.0 + i)
        _bar(research, "SPY", d, 500.0)
    research.flush()
    night = {"tags": {"STDY": "trading"}, "atr": {}, "evidence": set(), "cfg": CFG}
    with value_session() as s:
        out = shadow.process(
            s,
            research,
            [ready()],
            as_of=AS_OF,
            version="v2",
            digest="x",
            now=datetime.now(UTC).replace(tzinfo=None),
            **night,
        )
    assert out.opened["ready"] == 2 and out.filled == 0
    with value_session() as s:
        out = shadow.process(
            s,
            research,
            [ready()],
            as_of=SESSIONS[1],
            version="v2",
            digest="x",
            now=datetime.now(UTC).replace(tzinfo=None),
            **night,
        )
    assert (out.filled, out.opened["ready"]) == (2, 0)
    assert out.events == 0  # the entry session's close is read; nothing fires


def test_process_reads_the_filings_feed_and_the_going_concern_flag(value_db, research) -> None:
    """The night reads research.db's filing index: an 8-K 1.03 filed on the session re-evaluates
    and exits the main legs; a going-concern doubt in the newest read 10-Q exits every leg."""
    from src.research.store.models import FilingIndexRow, SymbolRow

    for i, d in enumerate(SESSIONS[:3]):
        _bar(research, "STDY", d, 30.0 + i)
        _bar(research, "SPY", d, 500.0)
    research.add(SymbolRow(symbol="STDY", cik="0000000001"))
    research.add(
        FilingIndexRow(
            accn="0000000001-26-000009",
            cik="0000000001",
            form="8-K",
            filed=SESSIONS[2],
            items="1.03,9.01",
        )
    )
    research.flush()
    night = {"tags": {"STDY": "trading"}, "atr": {}, "evidence": set(), "cfg": CFG}
    for day in SESSIONS[:3]:
        with value_session() as s:
            out = shadow.process(
                s, research, [ready()], as_of=day, version="v3", digest="x", now=NOW, **night
            )
    assert out.reevaluations == 2 and out.events == 6  # a thesis exit on each main leg
    assert {r[1] for r in _reevaluations()} == {"major"}
    research.add(
        FilingIndexRow(
            accn="0000000001-26-000008",
            cik="0000000001",
            form="10-Q",
            filed=SESSIONS[1],
            going_concern=True,
        )
    )
    _bar(research, "STDY", SESSIONS[3], 33.0)
    _bar(research, "SPY", SESSIONS[3], 500.0)
    research.flush()
    with value_session() as s:
        shadow.process(
            s, research, [ready()], as_of=SESSIONS[3], version="v3", digest="x", now=NOW, **night
        )
    assert all(leg.pending == 1.0 for leg in _legs("original").values())
