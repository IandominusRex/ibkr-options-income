"""The envelope: the glide L(t), the admission test and the measurement record (risk-envelope
plan Task 13; spec §3.4.1-3.4.2, rulings E4, E5, H8, P1, P3)."""

from __future__ import annotations

import asyncio
import json
from datetime import date, timedelta

import pytest

from src.analytics.shock import measure
from src.common.envelope_types import BookLine, ShockInputs, ShockResult
from src.engine import envelope as env
from src.storage import envelope_state as st
from src.storage import envelope_switches as sw

DAY = date(2026, 11, 16)
NLV = 100_000.0


@pytest.fixture(autouse=True)
def _trading_db(db):
    return db


def _result(s10: float, uew: float, *, t20: float | None = None, unmeasured=()) -> ShockResult:
    t = s10 if t20 is None else t20
    return ShockResult(
        s10=s10, s20=2 * s10, g10=s10, p20=2 * s10, t20=t, s_smh=s10, s10_vol10=s10 + 1,
        s10_net=s10, s20_net=2 * s10, g10_net=s10, p20_net=2 * s10, t20_net=t, s_smh_net=s10,
        s10_vol10_net=s10 + 1, uew=uew, unmeasured=tuple(unmeasured),
    )  # fmt: skip


def _inputs(*lines: BookLine) -> ShockInputs:
    return ShockInputs(
        lines=tuple(lines),
        betas={"SPY": 1.0},
        betas_smh={"SPY": 0.8},
        leverage={},
        governing={},
        tech_linked=frozenset(),
        semis=frozenset(),
        nlv=NLV,
    )


SPY_BOOK = BookLine(symbol="SPY", kind="stock", qty=250, spot=600.0)  # $150k: S10 15%, U_ew 1.5


def _put(qty: float = 1.0, strike: float = 590.0, iv: float | None = 0.20) -> BookLine:
    return BookLine("SPY", "short_put", qty, 600.0, strike=strike, dte=30, iv=iv)


def _record(s10_start: float = 23.0, uew_start: float = 1.37) -> st.GlideRecord:
    return st.GlideRecord(DAY, s10_start, uew_start, 13, 15.0, 1.25)


def test_the_glide_steps_weekly_to_the_target() -> None:
    rec = _record()
    assert st.limits_on(rec, DAY) == pytest.approx((23.0, 1.37))
    assert st.limits_on(rec, DAY + timedelta(days=6)) == pytest.approx((23.0, 1.37))
    assert st.limits_on(rec, DAY + timedelta(days=7)) == pytest.approx(
        (23.0 - 8.0 / 13, 1.37 - 0.12 / 13)
    )
    assert st.limits_on(rec, DAY + timedelta(days=70))[0] == pytest.approx(23.0 - 8.0 * 10 / 13)
    assert st.glide_end(rec) == DAY + timedelta(days=91)
    assert st.glide_span(rec, DAY + timedelta(days=15)).week == 3


def test_the_glide_starts_on_the_first_on_session_rounded_up() -> None:
    sw.set_switch("envelope_enforce", "on", source="cli")
    r = env.room(_inputs(SPY_BOOK), today=DAY, result=_result(22.3, 1.361))
    rec = st.load_glide()
    assert rec is not None and (rec.s10_start, rec.uew_start) == (23.0, 1.37)
    assert rec.start_date == DAY and (r.s10_limit, r.uew_limit) == pytest.approx((23.0, 1.37))
    # idempotent: a later session's measurement never restarts it
    env.room(_inputs(SPY_BOOK), today=DAY + timedelta(days=8), result=_result(30.0, 2.0))
    assert st.load_glide() == rec
    # exact levels are not bumped by float noise, and never below the targets
    assert st.start_levels(_result(22.0, 1.36), s10_target=15.0, uew_target=1.25) == (22.0, 1.36)
    assert st.start_levels(_result(9.2, 0.8), s10_target=15.0, uew_target=1.25) == (15.0, 1.25)


def test_no_glide_record_while_record_mode() -> None:
    assert sw.get_switch("envelope_enforce") == "record"
    r = env.room(_inputs(SPY_BOOK), today=DAY, result=_result(22.3, 1.361))
    assert st.load_glide() is None
    assert (r.s10_limit, r.uew_limit) == pytest.approx((23.0, 1.37))  # as if starting today
    assert r.enforce == "record" and r.measured


def test_after_thirteen_weeks_the_limit_is_the_target() -> None:
    rec = _record()
    for days in (91, 92, 400):
        assert st.limits_on(rec, DAY + timedelta(days=days)) == pytest.approx((15.0, 1.25))


def test_room_is_unmeasured_when_any_book_option_lacks_live_iv() -> None:
    sw.set_switch("envelope_enforce", "on", source="cli")
    inputs = _inputs(SPY_BOOK, _put(iv=None))
    r = env.room(inputs, today=DAY)
    assert not r.measured and "unmeasured:SPY" in r.reasons_if_unmeasured
    assert st.load_glide() is None  # an unmeasured book never starts the glide
    assert env.admits(r, inputs, [_put()]) == ["envelope_unmeasured"]
    # a measured book with an unreadable glide record fails closed, it never restarts the glide
    from src.storage.system_settings import set_setting

    set_setting(st.GLIDE_KEY, "{not json")
    r2 = env.room(_inputs(SPY_BOOK), today=DAY)
    assert not r2.measured and "glide_unreadable" in r2.reasons_if_unmeasured


def test_t20_trigger_turns_the_switch_on_once() -> None:
    assert env.check_t20_trigger(_result(20.0, 1.3, t20=22.5)) is None  # 2.5 points: no
    assert sw.get_switch("t20_limit") == "off"
    notice = env.check_t20_trigger(_result(20.0, 1.3, t20=23.5))
    assert notice is not None and "t20_limit" in notice
    assert sw.get_switch("t20_limit") == "on"
    assert sw.switch_record("t20_limit")["source"] == "trigger:t20"
    sw.set_switch("t20_limit", "off", source="cli")  # the operator turns it off again
    assert env.check_t20_trigger(_result(20.0, 1.3, t20=30.0)) is None
    assert sw.get_switch("t20_limit") == "off"
    # once on, T20 joins the admission test against the same L(t)
    sw.set_switch("t20_limit", "on", source="cli")
    assert env.room(_inputs(SPY_BOOK), today=DAY).t20_limit == pytest.approx(15.0)


def test_a_snapshot_is_written_each_cycle(monkeypatch) -> None:
    from sqlalchemy import select

    import src.orchestrator.scan as scan
    from src.common.schemas import AccountSnapshot, OptionRight, PositionSnapshot
    from src.storage.db import session_scope
    from src.storage.models import EnvelopeSnapshotRow

    positions = [
        PositionSnapshot(symbol="SPY", sec_type="STK", position=100, avg_cost=590.0, market_price=600.0),
        PositionSnapshot(
            symbol="SPY P590", sec_type="OPT", position=-1, avg_cost=5.0, right=OptionRight.PUT,
            strike=590.0, expiry=date.today() + timedelta(days=30), underlying="SPY", con_id=7,
        ),
    ]  # fmt: skip
    account = AccountSnapshot(
        account="DU1", net_liquidation=NLV, total_cash=40_000.0, buying_power=1.0,
        maintenance_margin=1.0, excess_liquidity=1.0,
    )  # fmt: skip

    async def live(_ib, _positions):
        return {7: 0.22}

    monkeypatch.setattr(scan, "live_option_ivs", live)
    monkeypatch.setattr(scan, "stored_ivs", lambda syms: {"SPY": 0.18})
    out = asyncio.run(scan._measure_envelope(object(), account, positions, {"SPY": 600.0}))
    with session_scope() as s:
        rows = (
            s.execute(select(EnvelopeSnapshotRow).order_by(EnvelopeSnapshotRow.id)).scalars().all()
        )
        assert [r.source for r in rows] == ["live", "stored"]
        assert rows[1].cash_after_itm == pytest.approx(40_000.0)  # the 590 put is out of the money
        assert rows[0].s10 > 0 and rows[0].enforce == "record"
    assert out is not None and out[1].measured  # the live room, for the gate (Task 19)

    sw.set_switch("envelope_enforce", "off", source="cli")
    assert asyncio.run(scan._measure_envelope(object(), account, positions, {"SPY": 600.0})) is None
    with session_scope() as s:
        rows = s.execute(select(EnvelopeSnapshotRow.source)).scalars().all()
        assert rows.count("stored") == 2 and rows.count("live") == 1  # off: the display only


def test_admits_rejects_a_put_that_breaches_l_of_t() -> None:
    inputs = _inputs(SPY_BOOK)
    r = env.room(inputs, today=DAY)  # record: L = 15% (the book's own, rounded up), U_ew 1.5
    assert r.s10_limit == pytest.approx(15.0) and r.uew_limit == pytest.approx(1.5)
    assert env.admits(r, inputs, [_put()]) == ["shock_budget", "gross_budget"]


def test_admits_passes_a_covered_call() -> None:
    inputs = _inputs(SPY_BOOK)
    r = env.room(inputs, today=DAY)
    call = BookLine("SPY", "short_call", 2, 600.0, strike=630.0, dte=30, iv=0.18)
    assert env.admits(r, inputs, [call]) == []
    assert measure(env_inputs_with(inputs, call)).s10 < r.s10_gross  # it lowers S10, never raises


def env_inputs_with(inputs: ShockInputs, line: BookLine) -> ShockInputs:
    from dataclasses import replace

    return replace(inputs, lines=inputs.lines + (line,))


def test_max_contracts_under_room_trims() -> None:
    sw.set_switch("envelope_enforce", "on", source="cli")
    from src.storage.system_settings import set_setting

    set_setting(
        st.GLIDE_KEY,
        json.dumps(
            {"start_date": DAY.isoformat(), "s10_start": 18.0, "uew_start": 9.0,
             "weeks": 13, "s10_target": 15.0, "uew_target": 1.25}
        ),
    )  # fmt: skip
    inputs = _inputs(SPY_BOOK)
    r = env.room(inputs, today=DAY)
    assert (r.s10_limit, r.uew_limit) == pytest.approx((18.0, 9.0)) and r.measured
    n, why = env.max_contracts_under(r, inputs, _put(strike=520.0), 20)
    assert 0 < n < 20 and why == "shock_budget"
    assert env.admits(r, inputs, [_put(qty=n, strike=520.0)]) == []
    assert env.admits(r, inputs, [_put(qty=n + 1, strike=520.0)]) == ["shock_budget"]
    from dataclasses import replace

    tight = replace(r, uew_limit=2.0)  # one 520 put adds 0.52 to U_ew 1.5: none fits
    assert env.max_contracts_under(tight, inputs, _put(strike=520.0), 20) == (0, "gross_budget")
    assert env.max_contracts_under(r, inputs, _put(), 0) == (0, "")
    assert env.max_contracts_under(r, inputs, _put(strike=1.0), 3) == (3, "")


def test_cash_after_every_itm_put_is_assigned() -> None:
    inputs = _inputs(SPY_BOOK, _put(qty=2, strike=610.0), _put(qty=1, strike=590.0))
    assert env.cash_after_itm_assignment(50_000.0, inputs) == pytest.approx(50_000 - 122_000)


def test_the_cli_shows_the_snapshot_and_the_glide(capsys) -> None:
    from scripts import envelope as cli

    inputs = _inputs(SPY_BOOK)
    env.record_snapshot(
        _result(22.3, 1.361), env.room(inputs, today=DAY), "stored", nlv=NLV, cash_after_itm=-5e3
    )
    assert cli.main(["show"]) == 0
    out = capsys.readouterr().out
    assert "latest stored-IV snapshot" in out and "S10 22.3% gross" in out
    assert "cash after every ITM put is assigned: $-5,000" in out
    assert "latest live-IV snapshot: none yet" in out and "glide: not started" in out
    snap = st.latest_snapshot()
    assert snap is not None and snap.source == "stored" and snap.result.uew == pytest.approx(1.361)


def test_stabilisation_prints_the_three_conditions_and_changes_nothing(tmp_path) -> None:
    from datetime import UTC, datetime

    from scripts import envelope as cli
    from src.common.schemas import EnvelopeReportResult

    assert "no harness result file yet" in cli.stabilisation_text(tmp_path)
    (tmp_path / "harness.json").write_text(
        EnvelopeReportResult(
            id="harness", passed=True, criterion="P2", metrics={}, switch="envelope_enforce",
            value_on_pass="on", written_at=datetime(2026, 12, 1, tzinfo=UTC),
        ).model_dump_json()
    )  # fmt: skip
    text = cli.stabilisation_text(tmp_path)
    assert "1. market-level bottoming signal: unknown" in text
    assert "2. survivability harness at the new level: PASS (harness" in text
    assert "3. operator ruling required" in text
    assert sw.switch_record("envelope_enforce") is None and st.load_glide() is None
