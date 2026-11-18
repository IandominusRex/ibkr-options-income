"""Buy-to-open hedge orders and their executor (risk-envelope Task 35; spec §3.10.10 items 5-6).

Every broker object here is a fake: nothing connects to IBKR."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.common.schemas import HedgeCandidate, HedgeLeg, RiskVerdict, Verdict

EXP = date(2027, 2, 19)
NOW = datetime(2026, 11, 18, 16, 0, tzinfo=UTC)


def leg(action: str = "BUY", strike: float = 560.0, bid: float = 5.9, ask: float = 6.1, **kw):
    return HedgeLeg(
        action=action,
        strike=strike,
        expiry=EXP,
        bid=bid,
        ask=ask,
        delta=-0.22 if action == "BUY" else -0.05,
        quoted_at=NOW,
        **kw,
    )


def cand(*, vertical: bool = False, contracts: int = 2, intent: str = "open", **kw):
    legs = [leg()] + ([leg("SELL", 500.0, 1.0, 1.04)] if vertical else [])
    debit = 6.0 - (1.02 if vertical else 0.0)
    data: dict[str, Any] = {
        "hedge_id": "h1",
        "order_ref": "hedge:h1",
        "instrument": "QQQ",
        "intent": intent,
        "kind": "vertical" if vertical else "outright",
        "legs": legs,
        "contracts": contracts,
        "debit": debit if intent == "open" else -debit,
        "max_loss": debit * 100 * contracts if intent == "open" else 0.0,
        "spot": 600.0,
        "dte": 93,
    }
    if intent == "close":
        data.update(hedge_id="h1x", order_ref="hedge:h1x", closes="h1")
    data.update(kw)
    return HedgeCandidate(**data)


# --------------------------------------------------------------------------- #
# order_builder
# --------------------------------------------------------------------------- #


def test_build_hedge_order_is_a_buy_limit_at_mid() -> None:
    from ib_async import LimitOrder

    from src.execution.order_builder import build_hedge_order

    order = build_hedge_order(cand())
    assert isinstance(order, LimitOrder)
    assert (order.action, order.totalQuantity, order.lmtPrice) == ("BUY", 2, 6.0)
    assert order.orderRef == "hedge:h1" and order.tif == "DAY"
    sale = build_hedge_order(cand(intent="close"))
    assert (sale.action, sale.lmtPrice, sale.orderRef) == ("SELL", 6.0, "hedge:h1x")


def test_a_vertical_is_a_bag() -> None:
    from src.execution.order_builder import build_hedge_combo, build_hedge_order

    c = cand(vertical=True)
    combo = build_hedge_combo(c, [9001, 9002])
    assert combo.secType == "BAG" and combo.symbol == "QQQ" and combo.exchange == "SMART"
    legs = [(x.conId, x.action, x.ratio) for x in combo.comboLegs]
    assert legs == [(9001, "BUY", 1), (9002, "SELL", 1)]
    order = build_hedge_order(c)
    assert (order.action, order.lmtPrice) == ("BUY", 4.98)  # net debit, penny tick
    with pytest.raises(ValueError):
        build_hedge_combo(c, [9001])


def test_the_chase_never_exceeds_debit_times_1_05() -> None:
    from src.execution.order_builder import reprice_limit

    ceiling = 6.0 * 1.05
    price = 6.0
    for _ in range(20):  # an ask far above: the chase walks up and stops at the ceiling
        nxt = reprice_limit("BUY", price, 6.0, 9.0, 0.5, ceiling=ceiling)
        if nxt is None:
            break
        price = nxt
    assert price <= ceiling + 1e-9 and price == pytest.approx(6.3)


# --------------------------------------------------------------------------- #
# The executor, on a fake broker
# --------------------------------------------------------------------------- #


class FakeTrade:
    def __init__(self, order: Any, fill_now: float = 0.0, *, done_on_cancel: bool = True) -> None:
        self.order = order
        self.order.orderId = 41
        self.orderStatus = SimpleNamespace(filled=fill_now, avgFillPrice=6.0 if fill_now else 0.0)
        self.fills: list[Any] = []
        self.done = False
        self.done_on_cancel = done_on_cancel

    def isDone(self) -> bool:
        return self.done


class FakeIB:
    """qualify sets conIds; quotes come back two-sided; placeOrder records what was sent and
    checks the order row already exists (the ref is written first)."""

    def __init__(
        self,
        *,
        fill: float = 2.0,
        done_on_cancel: bool = True,
        qualify: bool = True,
        trade_fills: list[Any] | None = None,
    ) -> None:
        self.fill = fill
        self.trade_fills = trade_fills or []
        self.done_on_cancel = done_on_cancel
        self.qualify = qualify
        self.qualified: list[Any] = []
        self.placed: list[tuple[Any, Any]] = []
        self.rows_at_place: list[int] = []
        self.cancelled = 0
        self.trade: FakeTrade | None = None
        self.wrapper = SimpleNamespace(tickers={}, ticker2ReqId={"mktData": {}})

    async def qualifyContractsAsync(self, *contracts: Any) -> list[Any]:
        for c in contracts:
            self.qualified.append(c)
            if self.qualify:
                c.conId = 9000 + int(c.strike // 100)
        return list(contracts)

    def reqMktData(self, contract: Any, *a: Any, **k: Any) -> Any:
        if contract.strike == 560.0:
            return SimpleNamespace(bid=5.9, ask=6.1, modelGreeks=SimpleNamespace(delta=-0.22))
        return SimpleNamespace(bid=1.0, ask=1.04, modelGreeks=SimpleNamespace(delta=-0.05))

    def cancelMktData(self, contract: Any) -> None:
        pass

    def placeOrder(self, contract: Any, order: Any) -> Any:
        import src.storage.db as dbmod
        from src.storage.models import HedgeOrderRow

        with dbmod.session_scope() as s:
            self.rows_at_place.append(
                s.query(HedgeOrderRow).filter_by(order_ref=order.orderRef).count()
            )
        self.placed.append((contract, order))
        if self.trade is None:
            self.trade = FakeTrade(order, self.fill, done_on_cancel=self.done_on_cancel)
            self.trade.done = self.fill > 0 and self.fill >= order.totalQuantity
            self.trade.fills = list(self.trade_fills)
        return self.trade

    def cancelOrder(self, order: Any) -> None:
        self.cancelled += 1
        assert self.trade is not None
        if self.trade.done_on_cancel:
            self.trade.done = True


async def passing_gate(c: HedgeCandidate) -> RiskVerdict:
    return RiskVerdict(candidate_id=c.hedge_id, verdict=Verdict.PASS)


async def run(ib: FakeIB, c: HedgeCandidate, **kw):
    from src.hedge.executor import execute_hedge

    return await execute_hedge(
        ib, c, gate=kw.pop("gate", passing_gate), timeout=0.0, cancel_confirm=0.0, **kw
    )


async def test_every_leg_is_qualified(hedge_db) -> None:
    ib = FakeIB()
    await run(ib, cand(vertical=True))
    assert [(c.strike, c.right, c.tradingClass) for c in ib.qualified] == [
        (560.0, "P", "QQQ"),
        (500.0, "P", "QQQ"),
    ]
    bad = FakeIB(qualify=False)
    res = await run(bad, cand())
    assert res.reasons == ["hedge_qualify_failed"] and bad.placed == []


async def test_the_ref_is_written_before_place_order(hedge_db) -> None:
    from src.common import hedge_view

    ib = FakeIB()
    res = await run(ib, cand())
    assert ib.rows_at_place == [1]  # the row existed when placeOrder was called
    ((_, order),) = ib.placed
    assert order.orderRef == "hedge:h1" and order.action == "BUY"
    assert res.status == "filled" and res.filled == 2
    (h,) = hedge_view.open_hedges() or []
    assert (h.hedge_id, h.contracts, h.cost) == ("h1", 2.0, 1200.0)


async def test_a_refusal_at_send_time_places_nothing(hedge_db) -> None:
    async def refusing(c: HedgeCandidate) -> RiskVerdict:
        return RiskVerdict(candidate_id=c.hedge_id, verdict=Verdict.REJECT, reasons=["hedge_x"])

    ib = FakeIB()
    res = await run(ib, cand(), gate=refusing)
    assert res.status == "refused" and res.reasons == ["hedge_x"] and ib.placed == []


async def test_a_price_move_above_the_ceiling_is_refused(hedge_db) -> None:
    ib = FakeIB()
    res = await run(ib, cand(debit=5.0, max_loss=1000.0))  # fresh mid 6.0 > 5.0 x 1.05
    assert res.reasons == ["hedge_price_moved"] and ib.placed == []


async def test_partial_fill_and_unconfirmed_cancel(hedge_db) -> None:
    """The Nov 10 case: a part fill stands and is booked; a cancel the broker never confirms
    leaves the row working (no second order), and a later fill is booked once from the
    executions."""
    import src.storage.db as dbmod
    from src.common import hedge_view
    from src.hedge import executor
    from src.storage.models import HedgeFillRow, HedgeOrderRow

    part = FakeIB(fill=1.0)
    res = await run(part, cand())
    assert (res.status, res.filled, part.cancelled) == ("partial", 1.0, 1)
    with dbmod.session_scope() as s:
        assert s.query(HedgeOrderRow).one().state == "partial"

    unconfirmed = FakeIB(fill=1.0, done_on_cancel=False)
    res = await run(unconfirmed, cand(hedge_id="h2", order_ref="hedge:h2"))
    assert res.status == "working"
    with dbmod.session_scope() as s:
        row = s.query(HedgeOrderRow).filter_by(hedge_id="h2").one()
        assert row.state == "working" and row.filled_qty == 1.0

    # a later cycle: the broker reports a second execution of that order, and no longer holds it
    late = MagicMock()

    async def execs() -> list[Any]:
        def ex(exec_id: str) -> Any:
            return SimpleNamespace(
                execution=SimpleNamespace(
                    execId=exec_id, orderRef="hedge:h2", shares=1.0, price=6.0
                ),
                contract=SimpleNamespace(secType="OPT"),
                commissionReport=SimpleNamespace(commission=0.65),
            )

        return [ex("e-first"), ex("e-late")]

    late.reqExecutionsAsync = execs
    late.openTrades.return_value = []
    # the executor booked the first execution under no execId (the fake trade carried none):
    with dbmod.session_scope() as s:
        s.query(HedgeFillRow).filter_by(hedge_id="h2").update({"exec_id": "e-first"})
    assert await executor.resolve_working(late, today=date(2026, 11, 18)) == 1
    assert await executor.resolve_working(late, today=date(2026, 11, 18)) == 0  # booked once
    with dbmod.session_scope() as s:
        row = s.query(HedgeOrderRow).filter_by(hedge_id="h2").one()
        assert (row.state, row.filled_qty) == ("filled", 2.0)
    h2 = next(h for h in hedge_view.open_hedges() or [] if h.hedge_id == "h2")
    assert h2.contracts == 2.0


def _fill(exec_id: str, ref: str, *, sec: str = "OPT", shares: float = 1.0, price: float = 6.0):
    return SimpleNamespace(
        execution=SimpleNamespace(execId=exec_id, orderRef=ref, shares=shares, price=price),
        contract=SimpleNamespace(secType=sec),
        commissionReport=SimpleNamespace(commission=0.65),
    )


def _broker_with(fills: list[Any]) -> Any:
    late = MagicMock()

    async def execs() -> list[Any]:
        return fills

    late.reqExecutionsAsync = execs
    late.openTrades.return_value = []
    return late


async def test_every_execution_is_its_own_fill_row_and_a_late_one_is_booked_once(
    hedge_db,
) -> None:
    """Review fix 2: a 3-lot buy part-filled 2 in two executions, cancel unconfirmed, then
    resolve_working: three rows with three execIds, total 3, nothing booked twice."""
    import src.storage.db as dbmod
    from src.common import hedge_view
    from src.hedge import executor
    from src.storage.models import HedgeFillRow, HedgeOrderRow

    ref = "hedge:h3"
    ib = FakeIB(
        fill=2.0,
        done_on_cancel=False,
        trade_fills=[_fill("e1", ref), _fill("e2", ref, price=6.1)],
    )
    res = await run(ib, cand(hedge_id="h3", order_ref=ref, contracts=3))
    assert res.status == "working"
    with dbmod.session_scope() as s:
        rows = s.query(HedgeFillRow).filter_by(hedge_id="h3").order_by(HedgeFillRow.id).all()
        assert [(r.exec_id, r.qty, r.price) for r in rows] == [("e1", 1.0, 6.0), ("e2", 1.0, 6.1)]
    broker = _broker_with([_fill("e1", ref), _fill("e2", ref, price=6.1), _fill("e3", ref)])
    assert await executor.resolve_working(broker, today=date(2026, 11, 18)) == 1
    assert await executor.resolve_working(broker, today=date(2026, 11, 18)) == 0
    with dbmod.session_scope() as s:
        row = s.query(HedgeOrderRow).filter_by(hedge_id="h3").one()
        assert (row.state, row.filled_qty) == ("filled", 3.0)
        ids = [r.exec_id for r in s.query(HedgeFillRow).filter_by(hedge_id="h3").all()]
        assert sorted(ids) == ["e1", "e2", "e3"]
    h3 = next(h for h in hedge_view.open_hedges() or [] if h.hedge_id == "h3")
    assert h3.contracts == 3.0


async def test_resolving_without_a_new_execution_does_not_double_count(hedge_db) -> None:
    import src.storage.db as dbmod
    from src.hedge import executor
    from src.storage.models import HedgeFillRow, HedgeOrderRow

    ref = "hedge:h4"
    ib = FakeIB(fill=2.0, done_on_cancel=False, trade_fills=[_fill("e1", ref), _fill("e2", ref)])
    await run(ib, cand(hedge_id="h4", order_ref=ref, contracts=3))
    broker = _broker_with([_fill("e1", ref), _fill("e2", ref)])
    await executor.resolve_working(broker, today=date(2026, 11, 18))
    with dbmod.session_scope() as s:
        row = s.query(HedgeOrderRow).filter_by(hedge_id="h4").one()
        assert row.filled_qty == 2.0  # not 4: the two executions were already booked
        assert s.query(HedgeFillRow).filter_by(hedge_id="h4").count() == 2


async def test_a_vertical_books_the_bag_execution_once(hedge_db) -> None:
    """Review fix 2: the trade's fills hold each leg's execution plus the combo's; only the BAG
    one counts, exactly as resolve_working counts it."""
    import src.storage.db as dbmod
    from src.storage.models import HedgeFillRow

    ref = "hedge:h5"
    fills = [
        _fill("leg-a", ref, sec="OPT", shares=2.0, price=5.9),
        _fill("leg-b", ref, sec="OPT", shares=2.0, price=0.9),
        _fill("bag-1", ref, sec="BAG", shares=2.0, price=5.0),
    ]
    ib = FakeIB(fill=2.0, trade_fills=fills)
    res = await run(ib, cand(hedge_id="h5", order_ref=ref, vertical=True, contracts=2))
    assert res.status == "filled"
    with dbmod.session_scope() as s:
        rows = s.query(HedgeFillRow).filter_by(hedge_id="h5").all()
        assert [(r.exec_id, r.qty, r.price) for r in rows] == [("bag-1", 2.0, 5.0)]


async def test_a_close_sells_and_books_negative_contracts(hedge_db) -> None:
    from src.common import hedge_view
    from tests.test_hedge_book import hedge_candidate, seed_open_hedge

    seed_open_hedge(hedge_candidate("h1", con_id=9005))
    ib = FakeIB()
    res = await run(ib, cand(intent="close"))
    ((_, order),) = ib.placed
    assert order.action == "SELL" and res.status == "filled"
    assert hedge_view.open_hedges() == []


def test_the_hedge_executor_never_constructs_an_order_object() -> None:
    """The order object is built only in ``src/execution/order_builder.py``."""
    from pathlib import Path

    text = Path("src/hedge/executor.py").read_text()
    assert "LimitOrder(" not in text and "MarketOrder" not in text and ".reqMktData(" not in text


def test_the_ref_prefix_is_the_hedge_books() -> None:
    from src.common.books import is_hedge_order_ref

    assert is_hedge_order_ref(cand().order_ref)
    assert is_hedge_order_ref(cand(intent="close").order_ref)


def test_the_hedge_has_its_own_client_id_and_ids_stay_unique() -> None:
    from pydantic import ValidationError

    from src.common.config import IBKRCfg, get_config

    ids = get_config().ibkr.client_ids
    assert ids["hedge"] == 32
    assert len(set(ids.values())) == len(ids)
    with pytest.raises(ValidationError, match="share clientId 32"):
        IBKRCfg(client_ids={**ids, "other": 32})
