"""The stock order path (risk-envelope Task 31; spec §3.7 item 2, rulings P10, L5-L7).

The wheel's only way to buy or sell shares: a tapped trim or de-lever (``source="repair"``) and the
Leveraged Entry Signal's share buys and trend-break sells (``source="les"``, Task 32a, paper only).
Every order:

1. is gated by ``risk_engine.validate_stock_order`` at decision time (the caller's
   ``gate_now``) and **again here at send time on a fresh quote**; a refusal places nothing;
2. is a ``LimitOrder`` at the mid of that fresh quote (``req_fresh_mkt_data``, never
   ``reqMktData``), rounded to the tick, on a contract ``qualifyContractsAsync`` resolved;
3. is written to ``orders`` (state ``submitted``, its ``order_ref`` = ``orderRef`` =
   ``"<source>:<ref_id>"``) **before** ``placeOrder``, so a fill can never arrive for an order the
   database does not know, and the ref reaches the ledger (``les:`` becomes ``book="les"``);
4. waits for its fills up to ``execution.fill_timeout_minutes``, then is cancelled. What filled
   stands (``partial``). A cancel the broker has not confirmed is **not** recorded as cancelled:
   the row stays working and a later cycle resolves it (``resolve_stale_stock_orders``), as the
   roll and value executors do.

A stock order is never ``queued`` (the option order poll never sees one) and the fill reconcilers
skip it (``is_stock_order_id``): stock fills reach the books through the broker-truth ledger, not
``fills`` (whose rows are per-contract option premiums). Nothing here reads an LLM output.
"""

from __future__ import annotations

import asyncio
import logging
import math
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from src.common.config import get_config
from src.common.schemas import (
    OrderState,
    RiskVerdict,
    StockOrderIntent,
    Verdict,
)
from src.ibkr.market_data import req_fresh_mkt_data
from src.storage.db import session_scope
from src.storage.models import OrderRow

log = logging.getLogger(__name__)
_ET = ZoneInfo("America/New_York")

STOCK_REF_PREFIXES = ("repair:", "les:")
QUOTE_SECONDS = 5.0
CANCEL_CONFIRM_SECONDS = 10.0


def is_stock_order_id(candidate_id: str | None) -> bool:
    """True for a stock order's ``orders.candidate_id`` (``repair:`` or ``les:``)."""
    return bool(candidate_id) and str(candidate_id).startswith(STOCK_REF_PREFIXES)


def tick_round(price: float) -> float:
    """A stock limit to its tick: $0.01 at or above $1, $0.0001 below."""
    return round(price, 2) if price >= 1.0 else round(price, 4)


@dataclass(frozen=True, slots=True)
class StockQuote:
    bid: float
    ask: float

    @property
    def mid(self) -> float:
        return tick_round((self.bid + self.ask) / 2.0)


@dataclass
class StockOrderResult:
    """``filled`` | ``partial`` | ``working`` (cancel unconfirmed) | ``cancelled`` (nothing
    filled) | ``refused`` (a gate or a missing quote) | ``skipped`` (one already working) |
    ``error``."""

    status: str
    intent: StockOrderIntent
    order_id: int | None = None
    order_ref: str | None = None
    limit_price: float | None = None
    filled: float = 0.0
    avg_price: float | None = None
    reasons: list[str] = field(default_factory=list)


def build_stock_order(intent: StockOrderIntent, quote: StockQuote, *, order_ref: str) -> Any:
    """A DAY ``LimitOrder`` at the quote's mid, rounded to the tick, carrying *order_ref*."""
    from ib_async import LimitOrder

    return LimitOrder(intent.side, intent.qty, quote.mid, tif="DAY", orderRef=order_ref)


def stock_contract(symbol: str) -> Any:
    from ib_async import Stock

    return Stock(symbol.upper(), "SMART", "USD")


async def qualify_stock(ib: Any, symbol: str) -> Any | None:
    """The qualified stock contract, or None."""
    try:
        qualified = await ib.qualifyContractsAsync(stock_contract(symbol))
    except Exception:
        log.warning("stock order: qualify failed for %s", symbol, exc_info=True)
        return None
    if not qualified or not getattr(qualified[0], "conId", 0):
        return None
    return qualified[0]


async def fetch_stock_quote(
    ib: Any, contract: Any, *, timeout: float = QUOTE_SECONDS
) -> StockQuote | None:
    """A fresh two-sided quote (``req_fresh_mkt_data``), cancelled after; None when none came."""
    ticker = req_fresh_mkt_data(ib, contract, "", False, False)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    try:
        while True:
            bid: Any = getattr(ticker, "bid", None)
            ask: Any = getattr(ticker, "ask", None)
            if _good(bid) and _good(ask) and float(ask) >= float(bid):
                return StockQuote(float(bid), float(ask))
            if loop.time() >= deadline:
                return None
            await asyncio.sleep(0.1)
    finally:
        try:
            ib.cancelMktData(contract)
        except Exception:
            pass


def _good(v: object) -> bool:
    try:
        f = float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    return f > 0 and math.isfinite(f)


Gate = Callable[[StockOrderIntent, float], Awaitable[RiskVerdict]]


def _refused(intent: StockOrderIntent, reasons: list[str]) -> StockOrderResult:
    return StockOrderResult("refused", intent, reasons=reasons)


def _ref_for(intent: StockOrderIntent, row_id: int) -> str:
    return f"{intent.source}:{intent.ref_id if intent.ref_id else row_id}"


def _snapshot(intent: StockOrderIntent) -> dict[str, Any]:
    return {
        "strategy": intent.strategy.value,
        "underlying": intent.symbol.upper(),
        "side": intent.side,
        "qty": intent.qty,
        "source": intent.source,
        "ref_id": intent.ref_id,
        "tapped": intent.tapped,
        "reason": intent.reason,
    }


def _write_row(intent: StockOrderIntent, limit: float) -> tuple[int, str] | None:
    """Insert the order row before ``placeOrder``; None when one for this ref is still working."""
    cfg = get_config()
    with session_scope() as s:
        if intent.ref_id:
            ref = f"{intent.source}:{intent.ref_id}"
            working = (
                s.query(OrderRow)
                .filter(
                    OrderRow.candidate_id == ref,
                    OrderRow.state.in_(
                        [OrderState.QUEUED, OrderState.SUBMITTED, OrderState.PARTIAL]
                    ),
                )
                .count()
            )
            if working:
                return None
        row = OrderRow(
            candidate_id=f"{intent.source}:new:{uuid.uuid4().hex[:12]}",
            approval_id=None,
            state=OrderState.SUBMITTED,
            limit_price=limit,
            is_live=bool(cfg.is_live),
            snapshot=_snapshot(intent),
            detail=f"stock {intent.side.lower()} ({intent.source}) {intent.reason}".strip(),
        )
        s.add(row)
        s.flush()
        ref = _ref_for(intent, row.id)
        row.candidate_id = ref
        row.order_ref = ref
        return row.id, ref


def _update(order_id: int, **values: Any) -> None:
    with session_scope() as s:
        row = s.get(OrderRow, order_id)
        if row is None:
            return
        for k, v in values.items():
            setattr(row, k, v)


async def execute_stock_order(
    ib: Any,
    intent: StockOrderIntent,
    *,
    gate: Gate | None = None,
    timeout: float | None = None,
    cancel_confirm: float = CANCEL_CONFIRM_SECONDS,
) -> StockOrderResult:
    """Qualify, quote fresh, re-gate, write the row, place, wait, record. Never raises.

    *gate* is the send-time Rules Engine check (default ``send_time_gate``: a fresh book, the
    value book's attribution and, for a buy, the envelope on live IV). It is called with the mid of
    the quote fetched here, so the re-gate always sees the price the order is sent at."""
    gate = gate or (lambda i, mid: send_time_gate(ib, i, mid))
    if intent.qty < 1:
        return _refused(intent, ["no_shares"])
    contract = await qualify_stock(ib, intent.symbol)
    if contract is None:
        return StockOrderResult("error", intent, reasons=["qualify_failed"])
    quote = await fetch_stock_quote(ib, contract)
    if quote is None:
        return _refused(intent, ["stock_no_quote"])
    try:
        verdict = await gate(intent, quote.mid)
    except Exception:
        log.exception("stock order: the send-time gate failed for %s", intent.symbol)
        return _refused(intent, ["stock_gate_failed"])
    if verdict.verdict != Verdict.PASS:
        log.warning(
            "stock order %s %s refused at send time: %s",
            intent.side,
            intent.symbol,
            verdict.reasons,
        )
        return _refused(intent, list(verdict.reasons))
    written = await asyncio.to_thread(_write_row, intent, quote.mid)
    if written is None:
        return StockOrderResult("skipped", intent, reasons=["already_working"])
    order_id, ref = written
    result = StockOrderResult(
        "error", intent, order_id=order_id, order_ref=ref, limit_price=quote.mid
    )
    try:
        trade = ib.placeOrder(contract, build_stock_order(intent, quote, order_ref=ref))
    except Exception:
        log.exception("stock order %s: place failed", ref)
        _update(order_id, state=OrderState.REJECTED, detail="place failed")
        result.reasons = ["place_failed"]
        return result
    try:
        _update(order_id, ib_order_id=int(getattr(trade.order, "orderId", 0) or 0) or None)
        wait = timeout if timeout is not None else get_config().execution.fill_timeout_minutes * 60
        loop = asyncio.get_running_loop()
        deadline = loop.time() + wait
        while not trade.isDone() and loop.time() < deadline:
            await asyncio.sleep(1.0)
        if not trade.isDone():
            ib.cancelOrder(trade.order)
            confirm = loop.time() + cancel_confirm
            while not trade.isDone() and loop.time() < confirm:
                await asyncio.sleep(0.5)
        filled = float(getattr(trade.orderStatus, "filled", 0.0) or 0.0)
        avg = float(getattr(trade.orderStatus, "avgFillPrice", 0.0) or 0.0) or None
        result.filled, result.avg_price = filled, avg
        if filled >= intent.qty - 1e-9:
            state, result.status = OrderState.FILLED, "filled"
            detail = f"filled {filled:g} @ {avg or 0:.2f}"
        elif not trade.isDone():
            # The broker never confirmed the cancel: the DAY order may still fill. The row stays
            # working (it blocks a second order on the same ref) until a later cycle resolves it.
            state = OrderState.PARTIAL if filled > 0 else OrderState.SUBMITTED
            result.status = "working"
            detail = "cancel not confirmed; resolved from the broker later"
        elif filled > 0:
            state, result.status = OrderState.PARTIAL, "partial"
            detail = f"part-filled {filled:g} of {intent.qty} @ {avg or 0:.2f}; the rest cancelled"
        else:
            state, result.status = OrderState.CANCELLED, "cancelled"
            detail = "no fill before the timeout"
        _update(order_id, state=state, filled_qty=filled, avg_fill_price=avg, detail=detail)
        log.info(
            "stock order %s %s %d %s: %s %g",
            ref,
            intent.side,
            intent.qty,
            intent.symbol,
            result.status,
            filled,
        )
        return result
    except Exception:
        log.exception("stock order %s: error after placement", ref)
        # IBKR holds the order: never mark it rejected (a second order could double it).
        _update(order_id, detail="error after the order reached IBKR; resolved later")
        result.status, result.reasons = "working", ["exception_after_placement"]
        return result


def resolve_stale_stock_orders(today: Any = None) -> int:
    """Close out stock rows still ``submitted``/``partial`` from an earlier ET day: a DAY order
    cannot work past its session, so it is ``cancelled`` (nothing filled) or ``partial`` (its
    fill stands; the shares themselves are counted from the ledger). Returns the rows moved."""
    from src.common.market_hours import today_et

    day = today or today_et()
    start = datetime(day.year, day.month, day.day, tzinfo=_ET).astimezone(UTC).replace(tzinfo=None)
    moved = 0
    with session_scope() as s:
        rows = (
            s.query(OrderRow)
            .filter(
                OrderRow.state.in_([OrderState.SUBMITTED, OrderState.PARTIAL]),
                OrderRow.created_at < start,
            )
            .all()
        )
        for row in rows:
            if not is_stock_order_id(row.candidate_id):
                continue
            row.state = OrderState.PARTIAL if (row.filled_qty or 0) > 0 else OrderState.CANCELLED
            row.detail = "DAY order past its session (resolved the next day)"
            moved += 1
    return moved


# --------------------------------------------------------------------------- #
# The Rules Engine's inputs, read fresh
# --------------------------------------------------------------------------- #


async def book_for(ib: Any, intent: StockOrderIntent, mid: float) -> dict[str, Any]:
    """Everything ``validate_stock_order`` reads, from the broker and the books now: the wheel's
    positions, the account, the name's attribution and, for a buy, the envelope on live IV."""
    from src.common.books import attribute, les_exposure
    from src.common.value_view import read_book
    from src.ibkr.portfolio import get_account_snapshot_async, get_positions
    from src.storage.wheel_shares import wheel_shares

    cfg = get_config()
    sym = intent.symbol.upper()
    positions = get_positions(ib)
    broker = sum(
        p.position
        for p in get_positions(ib, include_value=True)
        if p.sec_type == "STK" and (p.underlying or p.symbol).upper() == sym
    )
    account = await get_account_snapshot_async(ib, cfg.secrets.ibkr_account or "")
    w = (await asyncio.to_thread(wheel_shares, [sym]))[sym].shares
    book = read_book()
    les_book = await asyncio.to_thread(les_exposure)
    # An unreadable LES book leaves no attribution: a sell is then refused (stock_book_unknown).
    attribution = (
        attribute(
            broker,
            w,
            None if book is None else book.holding(sym),
            les=les_book.shares.get(sym, 0.0),
        )
        if les_book.readable
        else None
    )
    envelope = None
    if intent.side == "BUY":
        envelope = await buy_envelope(ib, positions, account, sym)
    return {
        "account": account,
        "positions": positions,
        "attribution": attribution,
        "envelope": envelope,
        "les_shares": les_book.shares.get(sym, 0.0),
    }


async def buy_envelope(ib: Any, positions: list[Any], account: Any, symbol: str) -> Any:
    """The envelope a stock buy is measured against: the wheel's positions with every option at
    its live IBKR IV, the value book's holdings, and betas for *symbol* and its governing index.
    None when it cannot be measured (the gate then refuses ``envelope_unmeasured``)."""
    from dataclasses import replace

    from src.analytics.shock_inputs import betas, build_inputs
    from src.common.books import les_by_name_for_envelope, value_exposure
    from src.common.market_hours import today_et
    from src.engine.envelope import room as envelope_room
    from src.ibkr.live_iv import live_option_ivs

    try:
        exposure = value_exposure()
        value_by_name = dict(exposure.by_name) if exposure.active and exposure.readable else {}
        live = await live_option_ivs(ib, positions)
        inputs = await asyncio.to_thread(
            build_inputs,
            positions,
            nlv=account.net_liquidation,
            value_by_name=value_by_name,
            les_by_name=les_by_name_for_envelope(),
            ivs=live,
        )
        want = [symbol.upper()]
        gov = inputs.governing.get(symbol.upper())
        if gov:
            want.append(gov)
        missing = [s for s in want if s not in inputs.betas]
        if missing:
            extra, _flagged = await asyncio.to_thread(betas, missing)
            inputs = replace(inputs, betas={**inputs.betas, **extra})
        return envelope_room(inputs, today=today_et(), may_start=False), inputs
    except Exception:
        log.exception("stock buy: the envelope could not be measured (refused)")
        return None


async def send_time_gate(ib: Any, intent: StockOrderIntent, mid: float) -> RiskVerdict:
    """``risk_engine.validate_stock_order`` on a book read now and the quote's *mid*."""
    from src.engine.risk_engine import validate_stock_order

    book = await book_for(ib, intent, mid)
    return validate_stock_order(
        intent,
        book["account"],
        book["positions"],
        envelope=book["envelope"],
        mid=mid,
        attribution=book["attribution"],
        les_shares=book.get("les_shares", 0.0),
    )


async def gate_now(ib: Any, intent: StockOrderIntent) -> tuple[RiskVerdict, StockQuote | None]:
    """The decision-time gate: a fresh quote and ``send_time_gate`` on it (``stock_no_quote``
    when none came). ``execute_stock_order`` runs the same gate again at send time."""
    contract = await qualify_stock(ib, intent.symbol)
    quote = await fetch_stock_quote(ib, contract) if contract is not None else None
    if quote is None:
        return (
            RiskVerdict(
                candidate_id=f"{intent.source}:{intent.symbol}",
                verdict=Verdict.REJECT,
                reasons=["stock_no_quote"],
            ),
            None,
        )
    return await send_time_gate(ib, intent, quote.mid), quote
