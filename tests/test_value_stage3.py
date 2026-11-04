"""Stage 3's process side (value book spec §9.7, §7.1; Part 5): the broker snapshot, held
re-evaluations mirrored from the shadow record, held names kept fresh, the notifier, the CLI."""

from __future__ import annotations

import asyncio
from datetime import date

from sqlalchemy import select

from src.common.schemas import OptionRight, PositionSnapshot
from src.value import live, notify
from src.value.service import held_names
from src.value.stage3 import build_snapshot
from src.value.store import (
    ValueClaudeReadRow,
    ValuePositionRow,
    ValueReevaluationRow,
    value_session,
)
from tests.value_book_fixtures import NOW, order


def _p(symbol, sec, qty, **kw) -> PositionSnapshot:
    return PositionSnapshot(
        symbol=symbol,
        sec_type=sec,
        position=qty,
        avg_cost=1.0,
        underlying=kw.pop("underlying", symbol),
        **kw,
    )


def test_the_snapshot_is_the_brokers_whole_view() -> None:
    snap = build_snapshot(
        [
            _p("GOOGL", "STK", 130, market_price=150.0),
            _p("GOOGL C", "OPT", -1, underlying="GOOGL", right=OptionRight.CALL, strike=180.0),
            _p("AAPL P", "OPT", -2, underlying="AAPL", right=OptionRight.PUT, strike=200.0),
        ],
        100_000.0,
    )
    assert snap.shares == {"GOOGL": 130} and snap.marks == {"GOOGL": 150.0}
    assert snap.wheel_short_calls == {"GOOGL": 1} and snap.csp_by_name == {"AAPL": 40_000.0}
    assert (snap.stock_value, snap.csp_collateral) == (19_500.0, 40_000.0)


def _position() -> int:
    order("STDY", shares=20, filled=20, avg=30.0)
    with value_session() as s:
        pos = ValuePositionRow(symbol="STDY", list_name="deep_value", opened_on=date(2026, 10, 1))
        s.add(pos)
        s.flush()
        return pos.id


def test_a_shadow_reevaluation_tonight_is_mirrored_onto_the_held_position(value_book_db) -> None:
    pid = _position()
    day = date(2026, 11, 2)
    with value_session() as s:
        s.add(
            ValueReevaluationRow(
                shadow_id=7,
                symbol="STDY",
                list_name="deep_value",
                session=day,
                last_session=day,
                severity="minor",
                triggers_json='[{"kind": "kill"}]',
                plan_before_json="{}",
                plan_after_json="{}",
                verdict_at_entry="READY",
                ruleset_version="v4",
                ruleset_hash="x",
                created_at=NOW,
            )
        )
    with value_session() as s:
        assert live.mirror_reevaluations(s, day, NOW) == 1
        assert live.mirror_reevaluations(s, day, NOW) == 0  # once a session
        held = s.scalars(
            select(ValueReevaluationRow).where(ValueReevaluationRow.position_id == pid)
        ).one()
        assert (held.shadow_id, held.triggers_json) == (0, '[{"kind": "kill"}]')
        assert s.scalars(select(ValueClaudeReadRow)).one().kind == "review"
        assert held_names(s) == {"STDY"}


def test_the_notifier_logs_and_sends_nothing_without_a_token() -> None:
    assert asyncio.run(notify.send(["Value book: test"])) == 0
