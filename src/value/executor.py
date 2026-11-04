"""The value book's stock-order path (spec §9.7), as ``src/spreads/executor.py`` is for spreads.

Not in ``src/execution/``: importing that loads ``src.claude.memory``, which the value process
must not load. Paper only (the caller refuses in live). Every order:

1. is written to ``value_orders`` as ``pending`` and committed **before** ``placeOrder``, with
   ``orderRef = "value:<id>"`` (spec §9.2: a fill can never arrive for an order value.db does not
   know, and the ref survives restarts and reaches the ledger);
2. is a ``LimitOrder`` at the mid of a fresh quote (``req_fresh_mkt_data``, never ``reqMktData``),
   on a contract ``qualifyContracts`` resolved, sent from clientId 31;
3. waits for its fills up to ``book.fill_timeout_seconds``, then is cancelled; what filled is
   recorded.

``ValueBroker`` is the boundary (``IbkrValueBroker`` wraps ib_async); tests pass a fake.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy.orm import Session

from src.common.books import VALUE_ORDER_PREFIX
from src.value.store import ValueOrderRow

log = logging.getLogger(__name__)
SessionFactory = Callable[[], AbstractContextManager[Session]]


@dataclass(frozen=True, slots=True)
class Quote:
    bid: float
    ask: float
    at: datetime  # naive UTC

    @property
    def mid(self) -> float:
        return round((self.bid + self.ask) / 2.0, 2)


@dataclass(frozen=True, slots=True)
class Placed:
    ib_order_id: int | None
    perm_id: int | None
    handle: Any


@dataclass(frozen=True, slots=True)
class Outcome:
    filled: float
    avg_price: float | None
    done: bool  # the order reached a terminal state by itself


class ValueBroker(Protocol):
    async def quote(self, symbol: str) -> Quote | None: ...
    async def place(
        self, symbol: str, side: str, shares: float, limit: float, order_ref: str
    ) -> Placed: ...
    async def wait(self, placed: Placed, timeout: float) -> Outcome: ...
    async def cancel(self, placed: Placed) -> Outcome: ...


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def send_order(
    session: SessionFactory,
    broker: ValueBroker,
    *,
    symbol: str,
    list_name: str,
    side: str,
    shares: float,
    limit: float,
    reason: str,
    proposal_id: int | None,
    tranche: int | None,
    timeout: float,
) -> int:
    """Write, place, wait, record. Returns the ``value_orders`` id (its status tells the rest)."""
    with session() as vs:
        row = ValueOrderRow(
            symbol=symbol,
            list_name=list_name,
            side=side,
            tranche=tranche,
            reason=reason,
            proposal_id=proposal_id,
            shares=shares,
            limit_price=limit,
            status="pending",
            created_at=_now(),
        )
        vs.add(row)
        vs.flush()
        row.order_ref = f"{VALUE_ORDER_PREFIX}{row.id}"
        order_id, ref = row.id, row.order_ref
    try:
        placed = await broker.place(symbol, side, shares, limit, ref)
    except Exception as exc:  # noqa: BLE001 - never reached IBKR: record it, never retry blind
        log.exception("value order %s: place failed", ref)
        with session() as vs:
            r = vs.get(ValueOrderRow, order_id)
            assert r is not None
            r.status, r.detail, r.done_at = "error", f"place failed: {exc}", _now()
        return order_id
    with session() as vs:
        r = vs.get(ValueOrderRow, order_id)
        assert r is not None
        r.status, r.sent_at = "submitted", _now()
        r.ib_order_id, r.perm_id = placed.ib_order_id, placed.perm_id
    outcome = await broker.wait(placed, timeout)
    if not outcome.done:
        outcome = await broker.cancel(placed)
    with session() as vs:
        r = vs.get(ValueOrderRow, order_id)
        assert r is not None
        r.filled, r.avg_price = outcome.filled, outcome.avg_price
        # a part-filled order is cancelled for the rest: what filled stands and counts in V
        r.status = "filled" if outcome.filled >= shares - 1e-9 else "cancelled"
        r.done_at = _now()
        status = r.status
    log.info("value order %s %s %g %s: %s %g", ref, side, shares, symbol, status, outcome.filled)
    return order_id


class IbkrValueBroker:
    """``ValueBroker`` over an ib_async ``IB`` connected as clientId 31."""

    def __init__(self, ib: Any, *, quote_seconds: float = 5.0) -> None:
        self.ib = ib
        self.quote_seconds = quote_seconds

    async def _contract(self, symbol: str) -> Any:
        from ib_async import Stock

        qualified = await self.ib.qualifyContractsAsync(Stock(symbol, "SMART", "USD"))
        if not qualified or not getattr(qualified[0], "conId", 0):
            raise RuntimeError(f"could not qualify {symbol}")
        return qualified[0]

    async def quote(self, symbol: str) -> Quote | None:
        from src.ibkr.market_data import req_fresh_mkt_data

        contract = await self._contract(symbol)
        ticker = req_fresh_mkt_data(self.ib, contract, "", False, False)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.quote_seconds
        try:
            while loop.time() < deadline:
                bid, ask = getattr(ticker, "bid", None), getattr(ticker, "ask", None)
                if bid and ask and bid > 0 and ask > 0 and bid == bid and ask == ask:
                    return Quote(float(bid), float(ask), _now())
                await asyncio.sleep(0.1)
            return None
        finally:
            self.ib.cancelMktData(contract)

    async def place(
        self, symbol: str, side: str, shares: float, limit: float, order_ref: str
    ) -> Placed:
        from ib_async import LimitOrder

        contract = await self._contract(symbol)
        order = LimitOrder(
            "BUY" if side == "buy" else "SELL", shares, limit, tif="DAY", orderRef=order_ref
        )
        trade = self.ib.placeOrder(contract, order)
        return Placed(int(trade.order.orderId) or None, int(trade.order.permId) or None, trade)

    async def wait(self, placed: Placed, timeout: float) -> Outcome:
        trade = placed.handle
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while not trade.isDone() and loop.time() < deadline:
            await asyncio.sleep(1.0)
        return self._outcome(trade)

    async def cancel(self, placed: Placed) -> Outcome:
        trade = placed.handle
        if not trade.isDone():
            self.ib.cancelOrder(trade.order)
            await asyncio.sleep(2.0)
        return self._outcome(trade)

    @staticmethod
    def _outcome(trade: Any) -> Outcome:
        filled = float(getattr(trade.orderStatus, "filled", 0.0) or 0.0)
        avg = float(getattr(trade.orderStatus, "avgFillPrice", 0.0) or 0.0)
        return Outcome(filled, avg or None, bool(trade.isDone()))
