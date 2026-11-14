"""The stock order path (risk-envelope Task 31; spec §3.7 item 2, rulings P10, L7).

``risk_engine.validate_stock_order`` is pure; ``stock_orders.execute_stock_order`` runs on a fake
broker (nothing here connects to IBKR)."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from src.common.books import attribute
from src.common.envelope_types import BookLine, EnvelopeRoom, ShockInputs
from src.common.schemas import (
    AccountSnapshot,
    OptionRight,
    PositionSnapshot,
    RiskVerdict,
    StockOrderIntent,
    Verdict,
)
from src.common.value_view import ValueHolding
from src.engine.risk_engine import validate_stock_order

ACCOUNT = AccountSnapshot(
    account="DU1",
    net_liquidation=100_000.0,
    total_cash=50_000.0,
    buying_power=80_000.0,
    maintenance_margin=5_000.0,
    excess_liquidity=60_000.0,
)


def _sell(qty: int, *, source: str = "repair", tapped: bool = True, sym: str = "GOOGL"):
    return StockOrderIntent(
        side="SELL",
        symbol=sym,
        qty=qty,
        source=source,
        ref_id="7",
        tapped=tapped,  # type: ignore[arg-type]
    )


def _buy(qty: int, *, source: str = "les", sym: str = "AAPL", tapped: bool = False):
    return StockOrderIntent(side="BUY", symbol=sym, qty=qty, source=source, tapped=tapped)  # type: ignore[arg-type]


def _call(sym: str = "GOOGL", contracts: int = 1) -> PositionSnapshot:
    return PositionSnapshot(
        symbol=f"{sym} C",
        sec_type="OPT",
        position=-contracts,
        avg_cost=1.0,
        right=OptionRight.CALL,
        strike=200.0,
        underlying=sym,
    )


def test_validate_stock_order_refuses_value_shares() -> None:
    # broker 130, the wheel's ledger count 100, the value book 30: the wheel's view is 100
    att = attribute(130, 100, ValueHolding("GOOGL", filled=30))
    over = validate_stock_order(_sell(110), ACCOUNT, [], envelope=None, mid=150.0, attribution=att)
    assert over.verdict == Verdict.REJECT and "stock_sell_not_wheel_shares" in over.reasons
    ok = validate_stock_order(_sell(100), ACCOUNT, [], envelope=None, mid=150.0, attribution=att)
    assert ok.verdict == Verdict.PASS, ok.reasons
    # value.db unreadable and the broker disagrees with W: nothing is the wheel's to sell
    unknown = attribute(130, 100, None)
    assert (
        "stock_sell_not_wheel_shares"
        in validate_stock_order(
            _sell(1), ACCOUNT, [], envelope=None, mid=150.0, attribution=unknown
        ).reasons
    )
    assert (
        "stock_book_unknown"
        in validate_stock_order(
            _sell(1), ACCOUNT, [], envelope=None, mid=150.0, attribution=None
        ).reasons
    )


def test_it_refuses_to_uncover_a_short_call() -> None:
    att = attribute(150, 150, ValueHolding("GOOGL"))
    positions = [_call(contracts=1)]
    bad = validate_stock_order(
        _sell(100), ACCOUNT, positions, envelope=None, mid=150.0, attribution=att
    )
    assert bad.reasons == ["stock_sell_uncovers_call"]
    good = validate_stock_order(
        _sell(50), ACCOUNT, positions, envelope=None, mid=150.0, attribution=att
    )
    assert good.verdict == Verdict.PASS


def _inputs(*lines: BookLine) -> ShockInputs:
    return ShockInputs(
        lines=tuple(lines),
        betas={"AAPL": 1.2, "GOOGL": 1.1, "QQQ": 1.1},
        betas_smh={},
        leverage={"TQQQ": 3},
        governing={"TQQQ": "QQQ"},
        tech_linked=frozenset(),
        semis=frozenset(),
        nlv=100_000.0,
    )


def _room(inputs: ShockInputs, *, s10_limit: float, enforce: str = "on") -> EnvelopeRoom:
    from src.analytics.shock import measure

    r = measure(inputs)
    return EnvelopeRoom(
        s10_gross=r.s10,
        s10_limit=s10_limit,
        uew=r.uew,
        uew_limit=1.5,
        t20_gross=r.t20,
        t20_limit=None,
        enforce=enforce,
        measured=True,
    )


def test_a_sell_lowers_s10() -> None:
    from src.engine.repair import trim_proposals

    inputs = _inputs(
        BookLine("GOOGL", "stock", 400.0, 150.0), BookLine("AAPL", "stock", 100.0, 180.0)
    )
    room = _room(inputs, s10_limit=5.0)  # the book is above L(t)
    now = datetime(2026, 11, 16, tzinfo=UTC)
    [trim, *_rest] = trim_proposals(inputs, room, {"GOOGL": 400.0, "AAPL": 100.0}, now=now)
    assert trim.symbol == "GOOGL" and trim.kind == "trim"
    assert trim.s10_before - trim.s10_after >= 1.0 - 1e-6  # the stated point comes off
    assert trim.shares == 61  # ceil(1% x 100k / (150 x 1.1 x 10%))
    # a sale needs no envelope pass: it lowers risk
    sale = validate_stock_order(
        _sell(int(trim.shares)),
        ACCOUNT,
        [],
        envelope=None,
        mid=150.0,
        attribution=attribute(400, 400, ValueHolding("GOOGL")),
    )
    assert sale.verdict == Verdict.PASS
    # never more than the sellable shares
    capped = trim_proposals(inputs, room, {"GOOGL": 20.0}, now=now)
    assert [t.shares for t in capped] == [20.0]
    # at or under L(t): no trim at all
    assert trim_proposals(inputs, _room(inputs, s10_limit=50.0), {"GOOGL": 400.0}, now=now) == []


def test_a_buy_must_pass_the_envelope() -> None:
    inputs = _inputs(BookLine("GOOGL", "stock", 400.0, 150.0))
    tight = _room(inputs, s10_limit=6.7, enforce="record")  # S10 now 6.6%: room for a little
    big = validate_stock_order(
        _buy(200), ACCOUNT, [], envelope=(tight, inputs), mid=180.0, attribution=None
    )
    assert "shock_budget" in big.reasons  # refused even while envelope_enforce is record
    small = validate_stock_order(
        _buy(2), ACCOUNT, [], envelope=(tight, inputs), mid=180.0, attribution=None
    )
    assert small.verdict == Verdict.PASS, small.reasons
    none = validate_stock_order(_buy(2), ACCOUNT, [], envelope=None, mid=180.0, attribution=None)
    assert none.reasons == ["envelope_unmeasured"]
    unmeasured = validate_stock_order(
        _buy(2, sym="ZZZZ"), ACCOUNT, [], envelope=(tight, inputs), mid=10.0, attribution=None
    )
    assert unmeasured.reasons == ["envelope_unmeasured"]  # no beta: never valued at zero


def test_refused_in_live_unless_tapped(monkeypatch) -> None:
    from src.common.config import Config

    monkeypatch.setattr(Config, "is_live", property(lambda self: True))
    att = attribute(100, 100, ValueHolding("GOOGL"))
    tapped = validate_stock_order(_sell(10), ACCOUNT, [], envelope=None, mid=150.0, attribution=att)
    assert tapped.verdict == Verdict.PASS
    untapped = validate_stock_order(
        _sell(10, tapped=False), ACCOUNT, [], envelope=None, mid=150.0, attribution=att
    )
    assert untapped.reasons == ["stock_not_tapped"]
    les = validate_stock_order(
        _sell(10, source="les", tapped=True),
        ACCOUNT,
        [],
        envelope=None,
        mid=150.0,
        attribution=att,
        les_shares=10,
    )
    assert "les_paper_only" in les.reasons  # the LES path is refused in live, even with a tap


def test_a_repair_order_is_never_sent_untapped_in_paper() -> None:
    att = attribute(100, 100, ValueHolding("GOOGL"))
    v = validate_stock_order(
        _sell(10, tapped=False), ACCOUNT, [], envelope=None, mid=150.0, attribution=att
    )
    assert v.reasons == ["stock_not_tapped"]  # P10 at every autonomy level


# --------------------------------------------------------------------------- #
# The executor on a fake broker
# --------------------------------------------------------------------------- #


class FakeTrade:
    def __init__(self, order: Any, *, fill: float, done: bool = True, cancel_confirms: bool = True):
        self.order = order
        order.orderId = 41
        self._fill = fill
        self._done = done
        self.cancel_confirms = cancel_confirms
        self.orderStatus = SimpleNamespace(
            filled=fill, avgFillPrice=order.lmtPrice if fill else 0.0
        )

    def isDone(self) -> bool:
        return self._done


class FakeIB:
    def __init__(
        self,
        *,
        bid: float = 50.0,
        ask: float = 50.2,
        fill: float | None = None,
        done: bool = True,
        cancel_confirms: bool = True,
    ):
        self.calls: list[Any] = []
        self.bid, self.ask = bid, ask
        self.fill, self.done, self.cancel_confirms = fill, done, cancel_confirms
        self.trade: FakeTrade | None = None
        self.ref_seen_in_db: bool | None = None

    async def qualifyContractsAsync(self, contract: Any) -> list[Any]:
        self.calls.append("qualify")
        contract.conId = 99
        return [contract]

    def placeOrder(self, contract: Any, order: Any) -> FakeTrade:
        from src.storage.db import session_scope
        from src.storage.models import OrderRow

        self.calls.append("place")
        with session_scope() as s:
            self.ref_seen_in_db = s.query(OrderRow).filter_by(order_ref=order.orderRef).count() == 1
        fill = order.totalQuantity if self.fill is None else self.fill
        self.trade = FakeTrade(
            order, fill=fill, done=self.done, cancel_confirms=self.cancel_confirms
        )
        return self.trade

    def cancelOrder(self, order: Any) -> None:
        self.calls.append("cancel")
        if self.trade is not None and self.trade.cancel_confirms:
            self.trade._done = True

    def cancelMktData(self, contract: Any) -> None:
        self.calls.append("cancel_mkt")


@pytest.fixture()
def fake_quote(monkeypatch):
    def install(ib: FakeIB) -> None:
        monkeypatch.setattr(
            "src.execution.stock_orders.req_fresh_mkt_data",
            lambda _ib, _c, *a, **k: SimpleNamespace(bid=ib.bid, ask=ib.ask),
        )

    return install


def _pass(seen: list[float]):
    async def gate(intent: StockOrderIntent, mid: float) -> RiskVerdict:
        seen.append(mid)
        return RiskVerdict(candidate_id="x", verdict=Verdict.PASS)

    return gate


async def test_limit_at_mid_and_qualified(db, fake_quote) -> None:
    from ib_async import LimitOrder

    from src.execution.stock_orders import execute_stock_order
    from src.storage.models import OrderRow

    ib = FakeIB(bid=50.0, ask=50.25)
    fake_quote(ib)
    res = await execute_stock_order(ib, _sell(20), gate=_pass([]), timeout=0)
    assert res.status == "filled" and res.filled == 20
    assert ib.calls.index("qualify") < ib.calls.index("place")
    assert ib.trade is not None
    order = ib.trade.order
    assert isinstance(order, LimitOrder) and order.action == "SELL" and order.tif == "DAY"
    assert order.lmtPrice == 50.12 or order.lmtPrice == 50.13  # the mid, to the cent
    assert order.orderRef == "repair:7"
    assert ib.ref_seen_in_db is True  # written before placeOrder
    with db() as s:
        row = s.query(OrderRow).one()
        assert (row.candidate_id, row.order_ref, row.state) == ("repair:7", "repair:7", "filled")
        assert row.snapshot["strategy"] == "stock_sell"


async def test_the_send_time_regate_uses_a_fresh_quote(db, fake_quote) -> None:
    from src.execution.stock_orders import execute_stock_order
    from src.storage.models import OrderRow

    ib = FakeIB(bid=50.0, ask=50.2)
    fake_quote(ib)
    seen: list[float] = []
    await execute_stock_order(ib, _sell(5), gate=_pass(seen), timeout=0)
    assert seen == [50.1]  # the gate saw the quote fetched at send time

    async def refuse(intent: StockOrderIntent, mid: float) -> RiskVerdict:
        return RiskVerdict(candidate_id="x", verdict=Verdict.REJECT, reasons=["shock_budget"])

    ib2 = FakeIB()
    fake_quote(ib2)
    res = await execute_stock_order(ib2, _buy(5, source="les"), gate=refuse, timeout=0)
    assert res.status == "refused" and res.reasons == ["shock_budget"]
    assert "place" not in ib2.calls
    with db() as s:
        assert s.query(OrderRow).count() == 1  # only the first order's row

    ib3 = FakeIB(bid=0.0, ask=0.0)
    fake_quote(ib3)
    res3 = await execute_stock_order(ib3, _sell(5), gate=_pass([]), timeout=0)
    assert res3.status == "refused" and res3.reasons == ["stock_no_quote"]


async def test_reconciler_ignores_stock(db) -> None:
    from src.execution.reconciliation import reconcile_orphan_fills, recover_orphan_orders
    from src.storage.models import OrderRow

    with db() as s:
        s.add(
            OrderRow(
                candidate_id="repair:9",
                state="submitted",
                order_ref="repair:9",
                snapshot={"strategy": "stock_sell"},
            )
        )
        s.add(OrderRow(candidate_id="les:10", state="submitted", ib_order_id=5, order_ref="les:10"))
        s.add(OrderRow(candidate_id="opt-1", state="submitted"))
    recover_orphan_orders()
    with db() as s:
        states = {r.candidate_id: r.state for r in s.query(OrderRow)}
    assert states["repair:9"] == "rejected"  # never queued for the option order poll
    assert states["opt-1"] == "queued"

    class Ex:
        async def reqExecutionsAsync(self) -> list[Any]:
            raise AssertionError("nothing to reconcile: the stock order is skipped")

    await reconcile_orphan_fills(Ex(), None, "1")  # type: ignore[arg-type]
    with db() as s:
        assert s.query(OrderRow).filter_by(candidate_id="les:10").one().state == "submitted"


def test_a_stock_order_left_working_is_closed_the_next_day(db) -> None:
    from datetime import timedelta

    from src.common.market_hours import today_et
    from src.execution.stock_orders import resolve_stale_stock_orders
    from src.storage.models import OrderRow

    old = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=3)
    with db() as s:
        s.add(OrderRow(candidate_id="les:1", state="submitted", created_at=old))
        s.add(OrderRow(candidate_id="les:2", state="partial", filled_qty=4, created_at=old))
        s.add(OrderRow(candidate_id="opt-2", state="submitted", created_at=old))
        s.add(OrderRow(candidate_id="les:3", state="submitted"))  # today's: still working
    assert resolve_stale_stock_orders(today_et()) == 2
    with db() as s:
        states = {r.candidate_id: r.state for r in s.query(OrderRow)}
    assert states == {
        "les:1": "cancelled",  # nothing filled
        "les:2": "partial",  # its fill stands
        "opt-2": "submitted",  # an option order is not the stock path's
        "les:3": "submitted",  # today's DAY order may still work
    }


async def test_a_tapped_trim_is_gated_twice_and_recorded(db, fake_quote, monkeypatch) -> None:
    from src.common.schemas import RepairProposal
    from src.execution import repair_orders, stock_orders
    from src.storage.models import RepairProposalRow
    from src.storage.repair_proposals import decide, save_proposals

    base = dict(s10_before=9.0, s10_after=8.0, uew_before=1.3, uew_after=1.2)
    [p] = save_proposals(
        [RepairProposal(kind="trim", symbol="GOOGL", detail="", shares=10, mark=150.0, **base)],
        datetime.now(UTC).date(),
    )
    assert p.id is not None and decide(p.id, "approved", by="telegram")
    seen: list[float] = []

    async def gate(ib: Any, intent: StockOrderIntent, mid: float) -> RiskVerdict:
        assert intent.tapped and intent.source == "repair" and intent.side == "SELL"
        seen.append(mid)
        return RiskVerdict(candidate_id="x", verdict=Verdict.PASS)

    monkeypatch.setattr(stock_orders, "send_time_gate", gate)
    monkeypatch.setattr(stock_orders.get_config().execution, "fill_timeout_minutes", 0)
    ib = FakeIB()
    fake_quote(ib)
    text = await repair_orders.execute_repair(ib, p)
    assert len(seen) == 2  # decision time, then send time
    assert "SELL 10 of 10 GOOGL" in text
    with db() as s:
        row = s.get(RepairProposalRow, p.id)
        assert row.status == "sent" and "GOOGL" in (row.result or "")
