"""Held names with no shadow entry get spec §7.1's whole trigger set (Part 6, ruling 17), and the
mirror ranks severities instead of comparing the words (the folded-in defect)."""

from __future__ import annotations

import json
from datetime import date, datetime

from sqlalchemy import select

from src.common.config import get_config
from src.common.value_types import FilingEvent, NewsVolume
from src.value import live
from src.value.live import HeldInputs
from src.value.store import (
    ValueBookStateRow,
    ValueClaudeReadRow,
    ValuePositionRow,
    ValueReevaluationRow,
    ValueShadowRow,
    value_session,
)
from tests.value_book_fixtures import NOW

DAY = date(2026, 11, 2)
PLAN = json.dumps({"value": {"stop": 25.0, "armed": False}})


def _cfg():
    return get_config().value


def _position(symbol: str = "STDY", opened: date = date(2026, 10, 1)) -> int:
    with value_session() as s:
        pos = ValuePositionRow(
            symbol=symbol,
            list_name="deep_value",
            opened_on=opened,
            plan_json=PLAN,
            plan_step=opened,
        )
        s.add(pos)
        s.flush()
        return pos.id


def _held(**kw) -> int:
    with value_session() as s:
        return live.held_reevaluations(
            s,
            DAY,
            NOW,
            inputs=kw.get("inputs", {}),
            cfg=_cfg(),
            ruleset_version="v4",
            ruleset_hash="be30d1eaa915",
        )


def _rows(pid: int) -> list[ValueReevaluationRow]:
    with value_session() as s:
        rows = list(
            s.scalars(select(ValueReevaluationRow).where(ValueReevaluationRow.position_id == pid))
        )
        s.expunge_all()
        return rows


def _shadow_row(symbol: str, *, severity: str) -> ValueReevaluationRow:
    return ValueReevaluationRow(
        shadow_id=7,
        symbol=symbol,
        list_name="deep_value",
        session=DAY,
        last_session=DAY,
        severity=severity,
        triggers_json='[{"kind": "kill"}]',
        plan_before_json="{}",
        plan_after_json="{}",
        verdict_at_entry="READY",
        ruleset_version="v4",
        ruleset_hash="x",
        created_at=NOW,
    )


def test_mirror_takes_the_higher_severity(value_book_db) -> None:
    pid = _position()
    with value_session() as s:
        s.add(_shadow_row("STDY", severity="minor"))
        s.add(_shadow_row("STDY", severity="major"))
    with value_session() as s:
        assert live.mirror_reevaluations(s, DAY, NOW) == 1
    assert [r.severity for r in _rows(pid)] == ["major"]  # "minor" > "major" as words


def test_a_held_name_without_a_shadow_entry_gets_an_earnings_trigger(value_book_db) -> None:
    pid = _position()
    assert _held(inputs={"STDY": HeldInputs(earnings=[DAY])}) == 1
    (row,) = _rows(pid)
    triggers = json.loads(row.triggers_json)
    assert [t["kind"] for t in triggers] == ["earnings"]
    assert (row.shadow_id, row.severity, row.session, row.last_session) == (0, "minor", DAY, DAY)
    # a night with nothing to say opens nothing
    assert _held(inputs={}) == 0


def test_a_held_name_without_a_shadow_entry_gets_a_regime_trigger(value_book_db) -> None:
    pid = _position()
    assert _held(inputs={"STDY": HeldInputs(regime_stepped=True)}) == 1
    (row,) = _rows(pid)
    assert [t["kind"] for t in json.loads(row.triggers_json)] == ["regime"]


def test_a_held_name_without_a_shadow_entry_gets_the_quiet_trigger_after_90_days(
    value_book_db,
) -> None:
    young = _position("YNG", opened=date(2026, 10, 1))
    old = _position("OLD", opened=date(2026, 7, 1))
    assert _held() == 1  # only the position 124 days old
    assert _rows(young) == []
    (row,) = _rows(old)
    assert [t["kind"] for t in json.loads(row.triggers_json)] == ["quiet"]
    # the debounce: tomorrow's quiet clock restarted at tonight's re-evaluation
    with value_session() as s:
        again = live.held_reevaluations(
            s,
            date(2026, 11, 3),
            NOW,
            inputs={},
            cfg=_cfg(),
            ruleset_version="v4",
            ruleset_hash="x",
        )
    assert again == 0


def test_a_held_name_with_a_shadow_entry_is_left_to_the_mirror(value_book_db) -> None:
    pid = _position()
    with value_session() as s:
        s.add(
            ValueShadowRow(
                track="baseline",
                kind="ready",
                list_name="deep_value",
                symbol="STDY",
                universe="trading",
                signal_date=date(2026, 9, 30),
                status="open",
                verdict="READY",
                fingerprint_key="k",
                ruleset_version="v4",
                ruleset_hash="x",
                scorecard_json="{}",
                created_at=datetime(2026, 9, 30),
            )
        )
    assert _held(inputs={"STDY": HeldInputs(earnings=[DAY], regime_stepped=True)}) == 0
    assert _rows(pid) == []


def test_held_triggers_move_no_level(value_book_db) -> None:
    pid = _position()
    inputs = {
        "STDY": HeldInputs(
            earnings=[DAY],
            filings=[
                FilingEvent(
                    accn="0001-26-000001",
                    form="8-K",
                    filed=DAY,
                    items=["4.02"],
                )
            ],
            news=NewsVolume(last_24h=40, daily_median_30d=2.0),
            kill=["margin kill trigger"],
        )
    }
    assert _held(inputs=inputs) == 1
    with value_session() as s:
        pos = s.get(ValuePositionRow, pid)
        assert (pos.plan_json, pos.status, pos.tranches_done) == (PLAN, "open", 0)
        (row,) = s.scalars(select(ValueReevaluationRow)).all()
        assert row.severity == "major" and row.plan_before_json == row.plan_after_json == PLAN
        read = s.scalars(select(ValueClaudeReadRow)).one()
        assert (read.kind, read.reevaluation_id) == ("review", row.id)
        checked = json.loads(s.get(ValueBookStateRow, "held_checked").value)
        assert checked == {str(pid): DAY.isoformat()}
