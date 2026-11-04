"""The value book's stock-order path (spec §9.7), as ``src/spreads/executor.py`` is for spreads.

Not in ``src/execution/``: importing that loads ``src.claude.memory``, which the value process
must not load. Paper only (the caller refuses in live). Every order:

1. is written to ``value_orders`` as ``pending`` and committed **before** ``placeOrder``, with
   ``orderRef = "value:<id>"`` (spec §9.2: a fill can never arrive for an order value.db does not
   know, and the ref survives restarts and reaches the ledger);
2. is a ``LimitOrder`` at the mid of a fresh quote (``req_fresh_mkt_data``, never ``reqMktData``),
   on a contract ``qualifyContracts`` resolved, sent from clientId 31;
3. waits for its fills up to ``book.fill_timeout_seconds``, then is cancelled; what filled is
   recorded. A cancel the broker has not confirmed is **not** recorded as cancelled (the DAY order
   may still fill after clientId 31 disconnects): the row stays ``submitted`` and the next cycle
   resolves it from the broker (``live.resolve_working_orders``, spec §9.2: V is rebuilt from the
   broker and the ledger, never from this process's memory).

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
    at: datetime  # naive UTC: the quote's own last update (the ticker's time), not our clock
    received: datetime | None = None  # naive UTC: when it reached us; None: no age to speak of

    @property
    def mid(self) -> float:
        return round((self.bid + self.ask) / 2.0, 2)

    @property
    def age_seconds(self) -> float:
        """How old the quote already was when it reached us, for the gate's staleness check."""
        return 0.0 if self.received is None else max(0.0, (self.received - self.at).total_seconds())


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


@dataclass(frozen=True, slots=True)
class Found:
    """An order the broker still knows by its ``orderRef``: what it shows as filled, and the
    handle to cancel it when it is still open (``placed`` is None once it is no longer open)."""

    outcome: Outcome
    placed: Placed | None = None


class ValueBroker(Protocol):
    async def quote(self, symbol: str) -> Quote | None: ...
    async def place(
        self, symbol: str, side: str, shares: float, limit: float, order_ref: str
    ) -> Placed: ...
    async def wait(self, placed: Placed, timeout: float) -> Outcome: ...
    async def cancel(self, placed: Placed) -> Outcome: ...
    async def lookup(self, order_ref: str) -> Found | None:
        """The order with this ``orderRef`` on clientId 31: open (``placed`` set) or done (its
        executions), else None. Raises when the broker cannot be asked (the caller then leaves
        the row alone)."""
        ...


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _ticker_time(ticker: Any, fallback: datetime) -> datetime:
    """The ticker's own last-update time as naive UTC (``fallback`` when it carries none)."""
    t = getattr(ticker, "time", None)
    if not isinstance(t, datetime):
        return fallback
    return t.astimezone(UTC).replace(tzinfo=None) if t.tzinfo else t


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
        if outcome.filled >= shares - 1e-9:
            r.status, r.done_at = "filled", _now()
        elif not outcome.done:
            # the broker never confirmed the cancel: it may still fill, so the row stays
            # working (V counts it) and the next cycle resolves it from the broker
            r.status = "partial" if outcome.filled > 0 else "submitted"
            r.detail = "cancel not confirmed; resolved from the broker next cycle"
        else:
            # a part-filled order is cancelled for the rest: what filled stands and counts in V
            r.status, r.done_at = "cancelled", _now()
        status = r.status
    log.info("value order %s %s %g %s: %s %g", ref, side, shares, symbol, status, outcome.filled)
    return order_id


class IbkrValueBroker:
    """``ValueBroker`` over an ib_async ``IB`` connected as clientId 31."""

    def __init__(
        self,
        ib: Any,
        *,
        quote_seconds: float = 5.0,
        cancel_confirm_seconds: float = 10.0,
        executions_timeout_seconds: float = 20.0,
    ) -> None:
        self.ib = ib
        self.quote_seconds = quote_seconds
        self.cancel_confirm_seconds = cancel_confirm_seconds
        self.executions_timeout_seconds = executions_timeout_seconds

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
                    received = _now()
                    return Quote(float(bid), float(ask), _ticker_time(ticker, received), received)
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
        """Cancel and **confirm**: poll until the order reaches a terminal state (the outcome's
        ``done`` says whether it did within ``cancel_confirm_seconds``)."""
        trade = placed.handle
        if not trade.isDone():
            self.ib.cancelOrder(trade.order)
            loop = asyncio.get_running_loop()
            deadline = loop.time() + self.cancel_confirm_seconds
            while not trade.isDone() and loop.time() < deadline:
                await asyncio.sleep(0.5)
        return self._outcome(trade)

    async def lookup(self, order_ref: str) -> Found | None:
        """This client's open order with *order_ref*, else its executions (today's, at IBKR)."""
        for trade in await self.ib.reqOpenOrdersAsync():
            if getattr(trade.order, "orderRef", "") == order_ref:
                oid, pid = int(trade.order.orderId) or None, int(trade.order.permId) or None
                return Found(self._outcome(trade), Placed(oid, pid, trade))
        fills = await asyncio.wait_for(
            self.ib.reqExecutionsAsync(), timeout=self.executions_timeout_seconds
        )
        qty = notional = 0.0
        for f in fills:
            ex: Any = getattr(f, "execution", None)
            if ex is not None and getattr(ex, "orderRef", "") == order_ref:
                qty += float(ex.shares)
                notional += float(ex.shares) * float(ex.price)
        if qty <= 0:
            return None
        return Found(Outcome(qty, notional / qty, True), None)

    @staticmethod
    def _outcome(trade: Any) -> Outcome:
        filled = float(getattr(trade.orderStatus, "filled", 0.0) or 0.0)
        avg = float(getattr(trade.orderStatus, "avgFillPrice", 0.0) or 0.0)
        return Outcome(filled, avg or None, bool(trade.isDone()))
