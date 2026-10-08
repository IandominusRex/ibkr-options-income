from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from src.common.config import get_config
from src.common.schemas import ChainOption, SpreadCandidate, SpreadPosition, SpreadVerdict
from src.spreads.executor import SpreadExecutor

NOW = datetime(2026, 10, 7, 14, 30, tzinfo=UTC)
TODAY = date(2026, 10, 7)
_BASE = get_config().spreads
FAST = _BASE.execution.model_copy(
    update={
        "order_ttl_seconds": 0.2,
        "close_ttl_seconds": 0.2,
        "reprice_steps": 3,
        "reprice_tick": 0.01,
        "close_max_concession": 0.10,
        "shadow_slippage_per_leg": 0.02,
        "commission_per_contract": 0.65,
    }
)
SEL = _BASE.selection.model_copy(update={"width": 5.0, "min_credit_pct_of_width": 0.10})
SHADOW = _BASE.model_copy(update={"mode": "shadow", "execution": FAST, "selection": SEL})
PAPER = _BASE.model_copy(update={"mode": "paper", "execution": FAST, "selection": SEL})


def cand() -> SpreadCandidate:
    return SpreadCandidate(
        spread_id="s1",
        side="put",
        expiry=TODAY,
        short_strike=679.0,
        long_strike=674.0,
        width=5.0,
        short_con_id=111,
        long_con_id=222,
        credit_mid=0.61,
        credit_natural=0.56,
        short_delta=-0.12,
        short_leg_spread_pct=0.07,
        long_leg_spread_pct=0.18,
        spot=690.0,
        quote_time=NOW,
    )


def position(contracts: int = 1) -> SpreadPosition:
    return SpreadPosition(
        spread_id="s1",
        mode="paper",
        side="put",
        expiry=TODAY,
        short_strike=679.0,
        long_strike=674.0,
        width=5.0,
        contracts=contracts,
        entry_credit=0.60,
        opened_at=NOW,
        short_con_id=111,
        long_con_id=222,
    )


def q(strike, bid, ask, con) -> ChainOption:
    return ChainOption(
        strike=strike, right="P", expiry=TODAY, bid=bid, ask=ask, delta=-0.1, con_id=con
    )


class FakeBroker:
    def __init__(self, quotes: list[ChainOption]) -> None:
        self.quotes = quotes

    async def requote(self, legs):
        return self.quotes


class FakeTrade:
    def __init__(self, order) -> None:
        self.order = order
        self.orderStatus = SimpleNamespace(status="Submitted", filled=0, avgFillPrice=0.0)
        self.fills: list[SimpleNamespace] = []

    def isDone(self) -> bool:
        return self.orderStatus.status in ("Filled", "Cancelled")


class FakeIB:
    """Fills when the limit equals *fill_at* (lmtPrice space), optionally partially."""

    def __init__(self, fill_at: float | None, fill_qty: int | None = None) -> None:
        self.fill_at = fill_at
        self.fill_qty = fill_qty
        self.placed: list[float] = []
        self.trade: FakeTrade | None = None
        self.cancelled = False

    def placeOrder(self, contract, order):
        self.placed.append(order.lmtPrice)
        if self.trade is None:
            order.permId, order.orderId = 9001, 7
            self.trade = FakeTrade(order)
        if self.fill_at is not None and abs(order.lmtPrice - self.fill_at) < 1e-9:
            qty = self.fill_qty or int(order.totalQuantity)
            self.trade.orderStatus.filled = qty
            self.trade.orderStatus.avgFillPrice = order.lmtPrice
            self.trade.orderStatus.status = "Filled" if qty == order.totalQuantity else "Submitted"
            self.trade.fills = [
                SimpleNamespace(commissionReport=SimpleNamespace(commission=0.65 * qty))
                for _ in range(2)
            ]
        return self.trade

    def cancelOrder(self, order) -> None:
        self.cancelled = True
        assert self.trade is not None
        self.trade.orderStatus.status = "Cancelled"


def approve(fresh: SpreadCandidate) -> SpreadVerdict:
    return SpreadVerdict(spread_id=fresh.spread_id, approved=True, contracts=2)


def reject(fresh: SpreadCandidate) -> SpreadVerdict:
    return SpreadVerdict(spread_id=fresh.spread_id, approved=False, reasons=["stale_quote"])


async def test_shadow_open_charges_slippage_and_commission() -> None:
    r = await SpreadExecutor(None, FakeBroker([]), SHADOW, now=lambda: NOW).open(cand(), 1, approve)
    assert (
        r.filled_qty == 1 and r.price == pytest.approx(0.57) and r.commission == pytest.approx(1.30)
    )
    assert r.order_ref == "CS:s1"


async def test_shadow_close_uses_mid_plus_slippage_or_the_worst_case() -> None:
    ex = SpreadExecutor(None, FakeBroker([]), SHADOW, now=lambda: NOW)
    r = await ex.close(position(), q(679, 0.38, 0.42, 111), q(674, 0.09, 0.11, 222), urgent=False)
    assert r.price == pytest.approx(0.34)
    worst = await ex.close(position(), None, None, urgent=True)
    assert worst.price == pytest.approx(5.0)


async def test_paper_open_walks_the_ladder_until_it_fills() -> None:
    ib = FakeIB(fill_at=-0.60)
    fresh = [q(679, 0.80, 0.86, 111), q(674, 0.20, 0.24, 222)]
    r = await SpreadExecutor(ib, FakeBroker(fresh), PAPER, now=lambda: NOW, poll_seconds=0.01).open(
        cand(), 1, approve
    )
    assert ib.placed == [-0.61, -0.60]
    assert (r.filled_qty, r.price, r.perm_id, r.ib_order_id) == (1, pytest.approx(0.60), 9001, 7)
    assert r.commission == pytest.approx(1.30)


async def test_paper_open_is_regated_on_fresh_quotes_and_can_be_refused() -> None:
    ib = FakeIB(fill_at=-0.61)
    fresh = [q(679, 0.80, 0.86, 111), q(674, 0.20, 0.24, 222)]
    r = await SpreadExecutor(ib, FakeBroker(fresh), PAPER, now=lambda: NOW).open(cand(), 1, reject)
    assert r.filled_qty == 0 and r.reason == "regate:stale_quote" and ib.placed == []


async def test_paper_open_without_a_fresh_quote_never_sends() -> None:
    ib = FakeIB(fill_at=-0.61)
    r = await SpreadExecutor(ib, FakeBroker([]), PAPER, now=lambda: NOW).open(cand(), 1, approve)
    assert r.reason == "no_fresh_quote" and ib.placed == []


# Review Focus 3 — a partial combo fill keeps what filled.
async def test_partial_fill_is_reported_after_the_cancel() -> None:
    ib = FakeIB(fill_at=-0.61, fill_qty=1)
    fresh = [q(679, 0.80, 0.86, 111), q(674, 0.20, 0.24, 222)]
    r = await SpreadExecutor(ib, FakeBroker(fresh), PAPER, now=lambda: NOW, poll_seconds=0.01).open(
        cand(), 2, approve
    )
    assert ib.cancelled and r.filled_qty == 1 and r.price == pytest.approx(0.61)


async def test_unfilled_order_is_cancelled() -> None:
    ib = FakeIB(fill_at=None)
    fresh = [q(679, 0.80, 0.86, 111), q(674, 0.20, 0.24, 222)]
    r = await SpreadExecutor(ib, FakeBroker(fresh), PAPER, now=lambda: NOW, poll_seconds=0.01).open(
        cand(), 1, approve
    )
    assert ib.cancelled and r.filled_qty == 0 and r.reason == "not_filled"


async def test_urgent_close_ends_at_the_natural_debit() -> None:
    ib = FakeIB(fill_at=0.34)
    ex = SpreadExecutor(ib, FakeBroker([]), PAPER, now=lambda: NOW, poll_seconds=0.01)
    r = await ex.close(position(), q(679, 0.38, 0.42, 111), q(674, 0.08, 0.12, 222), urgent=True)
    assert ib.placed == [0.30, 0.31, 0.32, 0.34]
    assert r.filled_qty == 1 and r.price == pytest.approx(0.34)
