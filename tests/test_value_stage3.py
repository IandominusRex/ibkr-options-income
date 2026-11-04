"""Stage 3's process side (value book spec §9.7, §7.1; Part 5): the broker snapshot, held
re-evaluations mirrored from the shadow record, held names kept fresh, the notifier, the CLI."""

from __future__ import annotations

import asyncio
from datetime import date

from sqlalchemy import select

from src.common.schemas import OptionRight, PositionSnapshot
from src.value import live, notify
from src.value.book import totals
from src.value.service import held_names
from src.value.stage3 import build_snapshot
from src.value.store import (
    ValueClaudeReadRow,
    ValueOrderRow,
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


def test_the_operator_cli_taps_clears_and_restates(value_book_db, capsys) -> None:
    from scripts.value_book import main
    from src.value.book import propose
    from src.value.store import ValueAttributionRow

    order("STDY", shares=20, filled=20, avg=30.0)
    with value_session() as s:
        pid = propose(
            s,
            kind="buy",
            symbol="STDY",
            list_name="deep_value",
            shares=10,
            price=30.0,
            reason="tranche 2",
            cause="python",
            auto=False,
            now=NOW,
            ttl_hours=1e6,
        ).id
        s.add(
            ValueAttributionRow(
                symbol="STDY", broker=40, wheel=0, value_filled=20, state="frozen", updated_at=NOW
            )
        )
    assert main(["--approve", str(pid), "--split", "STDY", "2:1", "--clear", "STDY"]) == 0
    out = capsys.readouterr().out
    assert f"proposal {pid}: approved" in out and "STDY: cleared" in out
    with value_session() as s:
        assert totals(s).names["STDY"].filled == 40.0
        assert s.scalars(select(ValueOrderRow)).one().avg_price == 15.0


def test_the_ledger_fill_of_a_value_order_is_read_by_its_order_ref(db) -> None:
    """Review I-5: a restart's working order is resolved from the ledger's book="value" rows."""
    from datetime import UTC, datetime

    from src.common.schemas import ParsedExecution, ParsedStatement
    from src.ledger.contracts import stock_contract
    from src.ledger.ingest import ingest
    from src.value.stage3 import ledger_fill

    def ex(qty, price, exec_id, ref):
        return ParsedExecution(
            contract=stock_contract("STDY", "USD"),
            trade_time=datetime(2026, 11, 2, 15, 5, tzinfo=UTC),
            quantity=qty,
            price=price,
            proceeds=-qty * price,
            exec_id=exec_id,
            account="U0000001",
            source_kind="exec",
            order_ref=ref,
        )

    ingest(
        ParsedStatement(
            account="U0000001",
            executions=[
                ex(12, 30.0, "a", "value:7"),
                ex(8, 31.0, "b", "value:7"),
                ex(5, 9.0, "c", None),
            ],
        ),
        source="flex",
    )
    assert ledger_fill("value:7") == (20.0, (12 * 30.0 + 8 * 31.0) / 20.0)
    assert ledger_fill("value:8") == (0.0, None)
