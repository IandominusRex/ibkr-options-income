"""Share attribution (value book spec §9.2): orderRef through the ledger, the wheel's own count W,
the wheel's view, fail-closed reads and the sell cap. Several of the seven fault drills are pinned
here; tests/test_value_fault_drills.py names all seven."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from src.common.books import attribute, is_value_order_ref, value_sell_cap
from src.common.schemas import PositionSnapshot
from src.common.value_view import ValueHolding
from src.ledger.contracts import stock_contract
from tests.value_book_fixtures import order


def test_the_wheel_sees_min_of_its_count_and_broker_less_value() -> None:
    v = ValueHolding("GOOGL", filled=30, pending_buy=10)
    ok = attribute(130, 100, v)
    assert (ok.wheel_view, ok.unexplained) == (90.0, 0.0)  # a pending buy errs short
    untagged = attribute(160, 130, ValueHolding("GOOGL", filled=30))  # a value fill counted twice
    assert untagged.unexplained == 0 and untagged.wheel_view == 130
    missing = attribute(130, 130, ValueHolding("GOOGL", filled=30))
    assert missing.unexplained == -30 and missing.wheel_view == 100  # errs short
    assert attribute(100, 120, ValueHolding("X")).wheel_view == 100  # never above the broker


def test_an_unreadable_value_db_leaves_the_wheel_only_what_the_broker_confirms() -> None:
    assert attribute(100, 100, None).wheel_view == 100
    assert attribute(130, 100, None).wheel_view == 0  # unexplained shares: no covered call


def test_a_value_sell_never_uncovers_a_wheel_call() -> None:
    assert value_sell_cap(30, 130, 1) == 30
    assert value_sell_cap(30, 120, 1) == 20  # the broker holds 20 fewer than the books say
    assert value_sell_cap(30, 100, 1) == 0
    assert is_value_order_ref("value:12") and not is_value_order_ref("CS:7")


def _exec(qty: float, price: float, when: str, *, ref: str | None = None, exec_id: str):
    from src.common.schemas import ParsedExecution

    return ParsedExecution(
        contract=stock_contract("GOOGL", "USD"),
        trade_time=datetime.fromisoformat(when).replace(tzinfo=UTC),
        quantity=qty,
        price=price,
        proceeds=-qty * price,
        exec_id=exec_id,
        account="U0000001",
        source_kind="exec",
        order_ref=ref,
    )


def test_an_order_ref_round_trips_live_flex_and_ingest(db) -> None:
    """Spec §9.2: IBKR keeps orderRef on every execution; a value fill is tagged by it, never by
    an order id (which collides across clientIds)."""
    from xml.etree import ElementTree

    from src.common.schemas import ParsedStatement
    from src.ledger.flex import _flex_trade
    from src.ledger.ingest import ingest
    from src.ledger.live import fill_to_execution
    from src.storage.models import BrokerExecutionRow
    from src.storage.wheel_shares import wheel_shares

    fill = SimpleNamespace(
        contract=SimpleNamespace(secType="STK", symbol="GOOGL", currency="USD"),
        execution=SimpleNamespace(
            shares=30,
            side="BOT",
            time=datetime(2026, 11, 2, 15, 1, tzinfo=UTC),
            price=150.0,
            execId="v1",
            permId=9,
            orderId=7,
            acctNumber="U0000001",
            orderRef="value:7",
        ),
    )
    live = fill_to_execution(fill)
    assert live is not None and live.order_ref == "value:7"
    el = ElementTree.fromstring(
        '<Trade assetCategory="STK" symbol="GOOGL" currency="USD" quantity="30" '
        'tradePrice="150" dateTime="20261102;100100" ibExecID="v1" orderReference="value:7" '
        'accountId="U0000001"/>'
    )
    flex = _flex_trade(el)
    assert flex is not None and flex.order_ref == "value:7"
    wheel = [
        _exec(100, 140.0, "2026-10-01T15:00:00", exec_id="w1"),  # an assignment at the strike
        _exec(-20, 160.0, "2026-10-20T15:00:00", exec_id="w2"),
    ]
    ingest(ParsedStatement(account="U0000001", executions=[*wheel, live]), source="flex")
    with db() as s:
        books = {r.exec_id: r.book for r in s.scalars(select(BrokerExecutionRow))}
    assert books == {"w1": "manual", "w2": "manual", "v1": "value"}
    w = wheel_shares(["googl"])["GOOGL"]
    assert w.shares == 80 and w.avg_cost == 140.0  # the value fill is not the wheel's


def test_a_flex_only_fill_backfills_the_order_ref_and_retags(db) -> None:
    """Drill: a fill that reached the ledger first without its orderRef is retagged when the
    Flex row carrying it arrives."""
    from src.common.schemas import ParsedStatement
    from src.ledger.ingest import ingest
    from src.storage.models import BrokerExecutionRow

    bare = _exec(30, 150.0, "2026-11-02T15:01:00", exec_id="v1")
    ingest(ParsedStatement(account="U0000001", executions=[bare]), source="csv")
    tagged = bare.model_copy(update={"order_ref": "value:7"})
    ingest(ParsedStatement(account="U0000001", executions=[tagged]), source="flex")
    with db() as s:
        row = s.scalars(select(BrokerExecutionRow)).one()
        assert (row.book, row.order_ref) == ("value", "value:7")


def _pos(symbol: str, qty: float, avg: float = 145.0) -> PositionSnapshot:
    return PositionSnapshot(
        symbol=symbol,
        sec_type="STK",
        position=qty,
        avg_cost=avg,
        market_value=qty * 150.0,
        underlying=symbol,
    )


def test_get_positions_gives_the_wheel_its_own_shares_at_its_own_cost(db, value_book_db) -> None:
    from src.common.schemas import ParsedStatement
    from src.ibkr.portfolio import wheel_view
    from src.ledger.ingest import ingest

    ingest(
        ParsedStatement(
            account="U0000001", executions=[_exec(100, 140.0, "2026-10-01T15:00:00", exec_id="w")]
        ),
        source="flex",
    )
    order("GOOGL", shares=30, filled=30, avg=150.0)
    out = wheel_view([_pos("GOOGL", 130), _pos("MSFT", 50)])
    g = next(p for p in out if p.symbol == "GOOGL")
    assert (g.position, g.avg_cost, g.market_value) == (100.0, 140.0, 15_000.0)
    assert next(p for p in out if p.symbol == "MSFT").position == 50  # not shared: untouched


def _bad_value_db(monkeypatch, tmp_path) -> None:
    bad = tmp_path / "value.db"
    bad.write_bytes(b"garbage")
    monkeypatch.setattr("src.common.value_view._path", lambda: bad)


def test_unreadable_value_db_drops_unexplained_stock(db, monkeypatch, tmp_path) -> None:
    from src.common.config import get_config
    from src.ibkr.portfolio import wheel_view

    _bad_value_db(monkeypatch, tmp_path)
    monkeypatch.setattr(get_config().value.book, "enabled", True)  # the book is on: every name
    assert wheel_view([_pos("MSFT", 50)]) == []  # W is 0 in an empty ledger: 50 unexplained


def test_with_the_book_off_an_unreadable_value_db_checks_only_the_names_it_may_hold(
    db, monkeypatch, tmp_path
) -> None:
    """Review I-10: book off + value.db unreadable used to put EVERY stock name through the W
    check, so positions vanished from every wheel caller (the wheel failed open on concentration).
    Now only the names in data/value_keep_fresh.json are checked; the wheel's other stock stays."""
    from src.common.config import get_config
    from src.common.value_keep_fresh import write_keep_fresh
    from src.ibkr.portfolio import wheel_view

    assert get_config().value.book.enabled is False
    _bad_value_db(monkeypatch, tmp_path)
    write_keep_fresh(["GOOGL"])
    out = wheel_view([_pos("GOOGL", 130), _pos("MSFT", 50)])
    assert [p.symbol for p in out] == ["MSFT"]  # GOOGL: 130 unexplained -> none; MSFT untouched
    assert out[0].position == 50


def test_with_the_book_off_no_keep_fresh_file_means_the_value_book_never_ran(
    db, monkeypatch, tmp_path
) -> None:
    from src.ibkr.portfolio import wheel_view

    _bad_value_db(monkeypatch, tmp_path)  # no value_keep_fresh.json (the fixture's tmp one)
    assert [p.symbol for p in wheel_view([_pos("MSFT", 50)])] == ["MSFT"]


def test_with_the_book_off_an_unreadable_keep_fresh_file_keeps_the_all_names_rule(
    db, monkeypatch, tmp_path
) -> None:
    import src.common.value_keep_fresh as kf
    from src.ibkr.portfolio import wheel_view

    _bad_value_db(monkeypatch, tmp_path)
    kf.KEEP_FRESH_FILE.write_text("not json at all", encoding="utf-8")
    assert wheel_view([_pos("MSFT", 50)]) == []  # neither file readable: fail closed on everything


def test_in_live_the_wheel_view_and_the_value_exposure_ignore_a_paper_value_db(
    db, value_book_db, monkeypatch
) -> None:
    """Review I-3: the book runs in paper only, so a paper value.db may never feed live gates."""
    from src.common.books import value_exposure
    from src.common.config import get_config
    from src.ibkr.portfolio import wheel_view

    order("GOOGL", shares=30, filled=30, avg=150.0)
    monkeypatch.setattr(get_config().value.book, "enabled", True)
    assert wheel_view([_pos("GOOGL", 130)]) == []  # paper: W is 0 in an empty ledger
    assert value_exposure().active is True
    monkeypatch.setattr(get_config().secrets, "live_trading", True)
    assert wheel_view([_pos("GOOGL", 130)])[0].position == 130  # the wheel's own, untouched
    off = value_exposure()
    assert (off.active, off.claim, off.by_name, off.earmarked) == (False, 0.0, {}, 0.0)


def test_a_split_corporate_action_restates_the_wheels_count() -> None:
    from src.storage.wheel_shares import split_ratio

    assert split_ratio("GOOGL(US02079K3059) SPLIT 20 FOR 1 (GOOGL, ...)") == 20.0
    assert split_ratio("XYZ SPLIT 1 FOR 10") == 0.1
    assert split_ratio("XYZ CASH DIVIDEND 0.20 USD") is None


def test_value_exposure_is_nothing_while_the_book_is_off(value_book_db, monkeypatch) -> None:
    from src.common.books import value_exposure
    from src.common.config import get_config

    order("GOOGL", shares=100, filled=100, avg=150.0)
    off = value_exposure()
    assert (off.active, off.claim, off.by_name) == (False, 0.0, {})
    monkeypatch.setattr(get_config().value.book, "enabled", True)
    on = value_exposure()
    assert on.by_name == {"GOOGL": 15_000.0} and on.claim == pytest.approx(11_250.0)
