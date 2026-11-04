"""The seven fault drills of value book spec §9.2, as unit tests (build acceptance: all must pass
before the first paper share purchase; each also has a scripted paper drill, SETUP §19). One test
per drill, named for it; each pins that the wheel never sees more shares than it owns and that an
unexplained count freezes rather than guesses."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from src.common.books import attribute
from src.common.schemas import ParsedExecution, ParsedStatement, PositionSnapshot
from src.common.value_view import read_book
from src.ledger.contracts import stock_contract
from src.value import book
from src.value.store import value_session
from tests.value_book_fixtures import NOW, order


def _exec(qty, price, when, *, exec_id, ref=None, codes=""):
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
        codes=codes,
    )


def _ingest(*execs, source="flex"):
    from src.ledger.ingest import ingest

    ingest(ParsedStatement(account="U0000001", executions=list(execs)), source=source)


def _w() -> float:
    from src.storage.wheel_shares import wheel_shares

    return wheel_shares(["GOOGL"])["GOOGL"].shares


def _state(broker: float) -> str:
    with value_session() as s:
        book.reconcile(s, {"GOOGL": broker}, {"GOOGL": _w()}, {}, now=NOW, grace_hours=36)
        return book.get_state(s, "x") or s.get(book.ValueAttributionRow, "GOOGL").state


def test_drill_1_assignment_on_a_shared_ticker(db, value_book_db) -> None:
    order("GOOGL", shares=30, filled=30, avg=150.0)
    _ingest(_exec(100, 140.0, "2026-11-02T21:00:00", exec_id="a1", codes="A"))  # assigned put
    att = attribute(130, _w(), read_book(NOW).holding("GOOGL"))
    assert (att.wheel_view, att.unexplained) == (100.0, 0.0)  # wheel stock (spec §9.1)
    assert _state(130) == "ok"


def test_drill_2_a_partial_value_fill(db, value_book_db) -> None:
    order("GOOGL", shares=30, filled=7, avg=150.0, status="partial")
    h = read_book(NOW).holding("GOOGL")
    assert (h.filled, h.pending_buy, h.claimed) == (7.0, 23.0, 30.0)
    assert attribute(7, 0.0, h).wheel_view == 0.0  # errs short while the rest is working
    assert _state(7) == "ok"


def test_drill_3_a_restart_mid_order(db, value_book_db) -> None:
    """The order row was written before placeOrder; the process died while the order waited. The
    next cycle rebuilds V from the broker (spec 9.2): the fill is recorded, the proposal is
    terminal, the name can be proposed again; and the ledger tags the same fill by its ref."""
    import asyncio

    from sqlalchemy import select

    from src.common.config import get_config
    from src.value import live
    from src.value.executor import Found, Outcome
    from src.value.store import ValueOrderRow, ValueProposalRow
    from tests.value_book_fixtures import proposal

    pid = proposal("GOOGL", status="sent", cost=4_500.0)
    oid = order("GOOGL", shares=30, filled=0, avg=None, status="submitted")
    with value_session() as s:
        s.get(ValueOrderRow, oid).proposal_id = pid
    assert read_book(NOW).holding("GOOGL").claimed == 30.0  # the working row claims the shares

    class RestartedBroker:
        async def lookup(self, order_ref):
            assert order_ref == f"value:{oid}"
            return Found(Outcome(30.0, 150.0, True), None)  # IBKR shows the fill

    msgs = asyncio.run(
        live.resolve_working_orders(
            value_session, RestartedBroker(), now=NOW, cfg=get_config().value
        )
    )
    assert msgs[0] == f"Value book: recovered a buy of 30 GOOGL (order value:{oid})"
    assert msgs[1].startswith("Value book: bought 30 GOOGL")
    with value_session() as s:
        row = s.scalars(select(ValueOrderRow)).one()
        assert (row.status, row.filled, row.avg_price) == ("filled", 30.0, 150.0)
        assert s.get(ValueProposalRow, pid).status == "done"
        assert (
            book.propose(
                s,
                kind="buy",
                symbol="GOOGL",
                list_name="deep_value",
                shares=5,
                price=150.0,
                reason="tranche 2",
                cause="python",
                auto=True,
                now=NOW,
                ttl_hours=30,
                tranche=2,
            )
            is not None
        )  # a 'sent' proposal that never ends used to block this for good
    h = read_book(NOW).holding("GOOGL")
    assert (h.filled, h.pending_buy) == (30.0, 0.0)
    _ingest(_exec(30, 150.0, "2026-11-02T15:05:00", exec_id="v1", ref=f"value:{oid}"))
    assert (
        _w() == 0.0
    )  # and when the ledger brings the fill it is the value book's, not the wheel's


def test_drill_4_a_split_freezes_until_restated_and_cleared(db, value_book_db) -> None:
    from src.storage.db import session_scope
    from src.storage.models import BrokerCorporateActionRow

    order("GOOGL", shares=30, filled=30, avg=150.0)
    _ingest(_exec(100, 140.0, "2026-10-01T15:00:00", exec_id="w1"))
    assert _state(130) == "ok"
    with session_scope() as s:  # the ledger records the 2-for-1 split as a corporate action
        s.add(
            BrokerCorporateActionRow(
                dedupe_key="ca1",
                event_date=date(2026, 11, 3),
                underlying="GOOGL",
                description="GOOGL(...) SPLIT 2 FOR 1",
                quantity=130,
                source="flex",
            )
        )
    assert _w() == 200.0  # W restated by the split
    with value_session() as s:
        later = NOW + timedelta(days=2)
        book.reconcile(s, {"GOOGL": 260.0}, {"GOOGL": _w()}, {}, now=later, grace_hours=36)
        assert s.get(book.ValueAttributionRow, "GOOGL").state == "pending"  # V still pre-split
        book.reconcile(
            s,
            {"GOOGL": 260.0},
            {"GOOGL": _w()},
            {},
            now=later + timedelta(hours=37),
            grace_hours=36,
        )
        assert s.get(book.ValueAttributionRow, "GOOGL").state == "frozen"
        assert book.apply_split(s, "GOOGL", 2.0, later) == 1
        book.reconcile(s, {"GOOGL": 260.0}, {"GOOGL": _w()}, {}, now=later, grace_hours=36)
        assert s.get(book.ValueAttributionRow, "GOOGL").state == "frozen"  # a human clears it
        assert book.clear_attribution(s, "GOOGL", later)
    assert read_book(NOW).holding("GOOGL").filled == 60.0


def test_drill_5_a_manual_tws_trade(db, value_book_db) -> None:
    """A trade placed by hand is wheel stock once the ledger has it; before then the shares are
    unexplained and the wheel sees fewer, never more."""
    order("GOOGL", shares=30, filled=30, avg=150.0)
    _ingest(_exec(100, 140.0, "2026-10-01T15:00:00", exec_id="w1"))
    before = attribute(150, _w(), read_book(NOW).holding("GOOGL"))
    assert (before.wheel_view, before.unexplained) == (100.0, 20.0)
    _ingest(_exec(20, 151.0, "2026-11-02T16:00:00", exec_id="m1"))  # untagged: manual
    after = attribute(150, _w(), read_book(NOW).holding("GOOGL"))
    assert (after.wheel_view, after.unexplained) == (120.0, 0.0)


def test_drill_6_flex_only_arrival_of_a_fill(db, value_book_db) -> None:
    oid = order("GOOGL", shares=30, filled=30, avg=150.0)
    _ingest(_exec(30, 150.0, "2026-11-02T15:05:00", exec_id="v1"), source="csv")  # no ref
    assert _w() == 30.0  # counted twice (W and V): the reconcile catches it
    assert attribute(30, _w(), read_book(NOW).holding("GOOGL")).unexplained == -30.0
    _ingest(_exec(30, 150.0, "2026-11-02T15:05:00", exec_id="v1", ref=f"value:{oid}"))
    assert _w() == 0.0  # Flex brought the ref: retagged value


def test_drill_7_value_db_unreadable(db, monkeypatch, tmp_path) -> None:
    from src.common.value_keep_fresh import write_keep_fresh
    from src.ibkr.portfolio import wheel_view

    bad = tmp_path / "value.db"
    bad.write_bytes(b"garbage")
    monkeypatch.setattr("src.common.value_view._path", lambda: bad)
    write_keep_fresh(["GOOGL"])  # the book is off here: only the names it may hold are checked
    assert read_book(NOW) is None
    _ingest(_exec(100, 140.0, "2026-10-01T15:00:00", exec_id="w1"))
    pos = [
        PositionSnapshot(
            symbol="GOOGL", sec_type="STK", position=p, avg_cost=140.0, underlying="GOOGL"
        )
        for p in (100, 130)
    ]
    assert wheel_view(pos[:1])[0].position == 100  # broker agrees with W: kept
    assert wheel_view(pos[1:]) == []  # 30 unexplained: no covered call at all
