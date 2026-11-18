"""The hedge executor (risk-envelope Task 35; spec §3.10.10 items 5-6, rulings H7, H9, P9).

``execute_hedge(ib, cand)`` sends one hedge order on the hedge's own connection (clientId 32,
``ibkr.client_ids.hedge``, opened for one hedge cycle by ``src/hedge/manager.py``):

1. every leg is qualified (``qualifyContractsAsync``); a leg that does not resolve to a ``conId``
   refuses the order (``hedge_qualify_failed``);
2. every leg is quoted fresh with ``req_fresh_mkt_data`` (never ``ib.reqMktData``), at most two
   lines, held while the order works (the chase reads them) and cancelled after;
3. the candidate is rebuilt on those quotes (the debit is the fresh mid) and re-gated by the
   Rules Engine (``risk_engine.validate_hedge`` through *gate*, on a context read now): a refusal,
   or a fresh debit above the approved debit x 1.05 (``hedge_price_moved``), places nothing;
4. the order row (``hedge_orders``, its ``order_ref`` = ``orderRef`` = ``hedge:<id>``) is written
   **before** ``placeOrder``, so a fill can never arrive for an order the book does not know;
5. the order is a ``LimitOrder`` at mid (``order_builder.build_hedge_order``: a BUY to open, a SELL
   to close; a BAG combo for a vertical), chased with ``reprice_limit`` toward the ask, never above
   the approved debit x 1.05 (a sale toward the bid, never below the approved credit x 0.95);
6. after ``execution.fill_timeout_minutes`` it is cancelled. What filled stands (``partial``) and is
   written to ``hedge_fills``. A cancel the broker has not confirmed is **not** recorded as
   cancelled: the row stays ``working`` (no second order goes out on that position) and
   ``resolve_working`` books any late fill from the broker's executions on a later cycle (the
   Nov 10 spreads lesson).

The wheel's ``orders`` and ``fills`` are never written. Nothing here reads an LLM output.
Deterministic tier: imports no enrichment.
"""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from src.common.config import get_config, get_hedge_cfg
from src.common.schemas import HedgeCandidate, HedgeLeg, RiskVerdict, Verdict
from src.hedge import store
from src.ibkr.market_data import req_fresh_mkt_data

log = logging.getLogger(__name__)
_ET = ZoneInfo("America/New_York")

CHASE_CEILING = 1.05  # spec §3.10.10 item 5: a buy is never chased above the approved debit x 1.05
SALE_FLOOR = 0.95  # a sale to close is never chased below the approved credit x 0.95
QUOTE_SECONDS = 6.0
CANCEL_CONFIRM_SECONDS = 10.0

Gate = Callable[[HedgeCandidate], Awaitable[RiskVerdict]]


@dataclass
class HedgeOrderResult:
    """``filled`` | ``partial`` | ``working`` (cancel unconfirmed) | ``cancelled`` (nothing
    filled) | ``refused`` (a gate, a quote or a price move) | ``error``."""

    status: str
    cand: HedgeCandidate
    order_id: int | None = None
    limit_price: float | None = None
    filled: float = 0.0
    avg_price: float | None = None
    reasons: list[str] = field(default_factory=list)


def _good(v: object) -> float | None:
    try:
        f = float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return f if f > 0 and math.isfinite(f) else None


def leg_contract(cand: HedgeCandidate, leg: HedgeLeg) -> Any:
    """The ib_async ``Option`` for one leg, SMART-routed with the instrument's trading class."""
    from ib_async import Option

    icfg = get_hedge_cfg().instruments.get(cand.instrument.upper())
    return Option(
        cand.instrument.upper(),
        f"{leg.expiry:%Y%m%d}",
        float(leg.strike),
        leg.right,
        "SMART",
        multiplier=str(icfg.multiplier if icfg else cand.multiplier),
        tradingClass=icfg.trading_class if icfg else cand.instrument.upper(),
        currency="USD",
    )


async def qualify_legs(ib: Any, cand: HedgeCandidate) -> list[Any] | None:
    """Every leg qualified, in order; None when any leg does not resolve to a ``conId``."""
    contracts = [leg_contract(cand, leg) for leg in cand.legs]
    try:
        await ib.qualifyContractsAsync(*contracts)
    except Exception:
        log.warning("hedge order %s: qualify failed", cand.order_ref, exc_info=True)
        return None
    if not contracts or any(not int(getattr(c, "conId", 0) or 0) for c in contracts):
        return None
    return contracts


def _leg_from(leg: HedgeLeg, contract: Any, ticker: Any, now: datetime) -> HedgeLeg:
    greeks = getattr(ticker, "modelGreeks", None)
    delta = getattr(greeks, "delta", None) if greeks is not None else None
    iv = getattr(greeks, "impliedVol", None) if greeks is not None else None
    try:
        d = float(delta) if delta is not None and math.isfinite(float(delta)) else leg.delta
    except (TypeError, ValueError):
        d = leg.delta
    return leg.model_copy(
        update={
            "con_id": int(getattr(contract, "conId", 0) or 0) or leg.con_id,
            "bid": _good(getattr(ticker, "bid", None)),
            "ask": _good(getattr(ticker, "ask", None)),
            "delta": d,
            "iv": _good(iv) or leg.iv,
            "quoted_at": now,
        }
    )


async def _wait_two_sided(tickers: list[Any], timeout: float) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if all(_good(getattr(t, "bid", None)) and _good(getattr(t, "ask", None)) for t in tickers):
            return
        await asyncio.sleep(0.1)


def net_debit(legs: list[HedgeLeg]) -> float | None:
    """The structure's mid debit per share: the long mids less the short mids; None when a leg has
    no two-sided quote."""
    total = 0.0
    for leg in legs:
        m = leg.mid
        if m is None:
            return None
        total += m if leg.action == "BUY" else -m
    return total


def natural(legs: list[HedgeLeg], action: str) -> tuple[float | None, float | None]:
    """The structure's (bid, ask) per share: buying pays the long asks less the short bids."""
    bid = ask = 0.0
    for leg in legs:
        if leg.bid is None or leg.ask is None:
            return None, None
        if leg.action == "BUY":
            bid, ask = bid + leg.bid, ask + leg.ask
        else:
            bid, ask = bid - leg.ask, ask - leg.bid
    return bid, ask


def refreshed(cand: HedgeCandidate, legs: list[HedgeLeg]) -> HedgeCandidate:
    """*cand* on fresh *legs*: an opening's debit is the fresh mid debit, a close's the negative of
    the structure's fresh mid (money received); ``max_loss`` follows."""
    mid = net_debit(legs)
    if mid is None:
        return cand.model_copy(update={"legs": legs})
    debit = mid if cand.intent == "open" else -mid
    return cand.model_copy(
        update={
            "legs": legs,
            "debit": debit,
            "max_loss": max(0.0, debit) * cand.multiplier * cand.contracts,
        }
    )


def _refused(cand: HedgeCandidate, reasons: list[str]) -> HedgeOrderResult:
    return HedgeOrderResult("refused", cand, reasons=reasons)


def _cancel_lines(ib: Any, contracts: list[Any]) -> None:
    for c in contracts:
        try:
            ib.cancelMktData(c)
        except Exception:
            log.debug("hedge order: cancelMktData failed for %s", getattr(c, "conId", ""))


def counted_executions(fills: Any) -> list[Any]:
    """The executions that count for an order: a vertical's legs also report, so when a BAG
    (combo) execution is present only the BAG ones count; otherwise every option execution.
    One entry per ``execId`` (a repeated report is one execution). One rule for ``_record``
    and ``resolve_working``."""
    seen: set[str] = set()
    unique: list[Any] = []
    for f in fills or []:
        eid = getattr(getattr(f, "execution", None), "execId", None)
        if eid is not None:
            if str(eid) in seen:
                continue
            seen.add(str(eid))
        unique.append(f)
    bag = [f for f in unique if str(getattr(getattr(f, "contract", None), "secType", "")) == "BAG"]
    return bag or unique


def _book_executions(
    fills: list[Any], *, order_id: int, hedge_id: str, sign: float, multiplier: int, known: set[str]
) -> float:
    """Book each execution not yet booked as its own fill row; returns the contracts booked."""
    booked = 0.0
    for f in fills:
        ex = getattr(f, "execution", None)
        exec_id = getattr(ex, "execId", None)
        shares = float(getattr(ex, "shares", 0.0) or 0.0)
        if shares <= 0 or (exec_id is not None and str(exec_id) in known):
            continue
        cr = getattr(f, "commissionReport", None)
        store.record_fill(
            hedge_id=hedge_id,
            qty=sign * shares,
            price=float(getattr(ex, "price", 0.0) or 0.0),
            multiplier=multiplier,
            order_id=order_id,
            commission=abs(float(getattr(cr, "commission", 0.0) or 0.0)) if cr is not None else 0.0,
            exec_id=None if exec_id is None else str(exec_id),
        )
        if exec_id is not None:
            known.add(str(exec_id))
        booked += shares
    return booked


async def quote_candidate(
    ib: Any, cand: HedgeCandidate, *, quote_seconds: float = QUOTE_SECONDS
) -> HedgeCandidate | None:
    """*cand* qualified and priced on fresh quotes (the decision-time read): every leg
    ``qualifyContractsAsync``-ed and quoted with ``req_fresh_mkt_data``, the lines cancelled after.
    None when a leg does not qualify or has no two-sided quote."""
    contracts = await qualify_legs(ib, cand)
    if contracts is None:
        return None
    tickers = [req_fresh_mkt_data(ib, c, "", False, False) for c in contracts]
    try:
        await _wait_two_sided(tickers, quote_seconds)
        now = datetime.now(UTC)
        fresh = refreshed(
            cand,
            [
                _leg_from(leg, c, t, now)
                for leg, c, t in zip(cand.legs, contracts, tickers, strict=True)
            ],
        )
    finally:
        _cancel_lines(ib, contracts)
    return fresh if net_debit(fresh.legs) is not None else None


async def execute_hedge(
    ib: Any,
    cand: HedgeCandidate,
    *,
    gate: Gate,
    timeout: float | None = None,
    cancel_confirm: float = CANCEL_CONFIRM_SECONDS,
    quote_seconds: float = QUOTE_SECONDS,
) -> HedgeOrderResult:
    """Qualify, quote fresh, re-gate, write the row, place, chase, record. Never raises.

    *gate* is the send-time Rules Engine check: ``validate_hedge`` on a context read now. It is
    called with the candidate rebuilt on the quotes fetched here, so the re-gate always sees the
    price the order is sent at."""
    from src.execution.order_builder import build_hedge_combo, build_hedge_order, reprice_limit

    if cand.contracts < 1:
        return _refused(cand, ["no_contracts"])
    contracts = await qualify_legs(ib, cand)
    if contracts is None:
        return HedgeOrderResult("error", cand, reasons=["hedge_qualify_failed"])
    tickers = [req_fresh_mkt_data(ib, c, "", False, False) for c in contracts]
    try:
        await _wait_two_sided(tickers, quote_seconds)
        now = datetime.now(UTC)
        fresh = refreshed(
            cand,
            [
                _leg_from(leg, c, t, now)
                for leg, c, t in zip(cand.legs, contracts, tickers, strict=True)
            ],
        )
        if net_debit(fresh.legs) is None:
            return _refused(fresh, ["hedge_quote_one_sided"])
        if cand.intent == "open" and fresh.debit > cand.debit * CHASE_CEILING + 1e-9:
            return _refused(fresh, ["hedge_price_moved"])
        try:
            verdict = await gate(fresh)
        except Exception:
            log.exception("hedge order %s: the send-time gate failed", cand.order_ref)
            return _refused(fresh, ["hedge_gate_failed"])
        if verdict.verdict != Verdict.PASS:
            log.warning("hedge order %s refused at send time: %s", cand.order_ref, verdict.reasons)
            return _refused(fresh, list(verdict.reasons))
        order = build_hedge_order(fresh)
        contract = (
            contracts[0]
            if len(contracts) == 1
            else build_hedge_combo(fresh, [int(c.conId) for c in contracts])
        )
        limit = float(order.lmtPrice or 0.0)
        order_id = await asyncio.to_thread(store.record_order, fresh, limit_price=limit)
        result = HedgeOrderResult("error", fresh, order_id=order_id, limit_price=limit)
        try:
            trade = ib.placeOrder(contract, order)
        except Exception:
            log.exception("hedge order %s: place failed", cand.order_ref)
            store.update_order(order_id, state="rejected", detail="place failed")
            result.reasons = ["place_failed"]
            return result
        try:
            store.update_order(
                order_id, ib_order_id=int(getattr(trade.order, "orderId", 0) or 0) or None
            )
            await _work(
                ib,
                trade,
                contract,
                order,
                fresh,
                tickers,
                timeout,
                cancel_confirm,
                reprice_limit,
                approved=abs(cand.debit),
            )
            return _record(trade, fresh, order_id, result)
        except Exception:
            log.exception("hedge order %s: error after placement", cand.order_ref)
            # IBKR holds the order: never mark it rejected (a second order could double it).
            store.update_order(
                order_id, state="working", detail="error after the order reached IBKR"
            )
            result.status, result.reasons = "working", ["exception_after_placement"]
            return result
    finally:
        _cancel_lines(ib, contracts)


async def _work(
    ib: Any,
    trade: Any,
    contract: Any,
    order: Any,
    cand: HedgeCandidate,
    tickers: list[Any],
    timeout: float | None,
    cancel_confirm: float,
    reprice_limit: Callable[..., float | None],
    *,
    approved: float,
) -> None:
    """Wait for the fill, chasing within the ceiling (a buy) or the floor (a sale); cancel at the
    timeout and wait *cancel_confirm* for the broker to confirm it."""
    ex = get_config().execution
    wait = timeout if timeout is not None else ex.fill_timeout_minutes * 60
    loop = asyncio.get_running_loop()
    deadline = loop.time() + wait
    next_chase = loop.time() + ex.reprice_interval_seconds
    chases = 0
    action = str(order.action)
    ceiling = approved * CHASE_CEILING if action == "BUY" else None
    floor = approved * SALE_FLOOR if action == "SELL" else None
    while not trade.isDone() and loop.time() < deadline:
        await asyncio.sleep(0.5)
        if (
            ex.reprice_enabled
            and chases < ex.max_reprices
            and loop.time() >= next_chase
            and not trade.isDone()
        ):
            now = datetime.now(UTC)
            legs = [
                _leg_from(leg, c, t, now)
                for leg, c, t in zip(cand.legs, [None] * len(tickers), tickers, strict=True)
            ]
            bid, ask = natural(legs, action)
            if action == "SELL":  # a sale of the structure: its bid is what we receive
                new = reprice_limit(
                    "SELL", float(order.lmtPrice), bid, ask, ex.reprice_step_pct, floor=floor
                )
            else:
                new = reprice_limit(
                    "BUY", float(order.lmtPrice), bid, ask, ex.reprice_step_pct, ceiling=ceiling
                )
            chases += 1
            next_chase = loop.time() + ex.reprice_interval_seconds
            if new is not None:
                order.lmtPrice = new
                ib.placeOrder(contract, order)  # modify the working order in place
    if not trade.isDone():
        ib.cancelOrder(trade.order)
        confirm = loop.time() + cancel_confirm
        while not trade.isDone() and loop.time() < confirm:
            await asyncio.sleep(0.5)


def _record(
    trade: Any, cand: HedgeCandidate, order_id: int, result: HedgeOrderResult
) -> HedgeOrderResult:
    filled = float(getattr(trade.orderStatus, "filled", 0.0) or 0.0)
    avg = float(getattr(trade.orderStatus, "avgFillPrice", 0.0) or 0.0) or None
    result.filled, result.avg_price = filled, avg
    if filled > 0:
        sign = 1.0 if cand.intent == "open" else -1.0
        hedge_id = store.position_id(cand)
        _book_executions(
            counted_executions(getattr(trade, "fills", None)),
            order_id=order_id,
            hedge_id=hedge_id,
            sign=sign,
            multiplier=cand.multiplier,
            known=store.fill_exec_ids(order_id),
        )
        short = filled - store.order_booked_qty(order_id)
        if short > 1e-9 and trade.isDone():
            # the order is over and the trade's fill list lags its status: book the rest once, at
            # the average price. A still-working order is left to resolve_working (by execId).
            store.record_fill(
                hedge_id=hedge_id,
                qty=sign * short,
                price=avg or 0.0,
                multiplier=cand.multiplier,
                order_id=order_id,
            )
    if filled >= cand.contracts - 1e-9:
        state, result.status = "filled", "filled"
        detail = f"filled {filled:g} @ {avg or 0:.2f}"
    elif not trade.isDone():
        # The broker never confirmed the cancel: the DAY order may still fill. The row stays
        # working (no second order on this position) until resolve_working settles it.
        state, result.status = "working", "working"
        detail = "cancel not confirmed; resolved from the broker's executions later"
    elif filled > 0:
        state, result.status = "partial", "partial"
        detail = f"part-filled {filled:g} of {cand.contracts} @ {avg or 0:.2f}; the rest cancelled"
    else:
        state, result.status = "cancelled", "cancelled"
        detail = "no fill before the timeout"
    store.update_order(order_id, state=state, filled_qty=filled, avg_fill_price=avg, detail=detail)
    log.info(
        "hedge order %s %s %d %s: %s %g",
        cand.order_ref,
        cand.intent,
        cand.contracts,
        cand.instrument,
        result.status,
        filled,
    )
    return result


async def resolve_working(ib: Any, *, today: Any = None) -> int:
    """Settle every ``working`` / ``submitted`` hedge order from the broker's executions: a fill the
    executor never saw (a cancel it could not confirm, a reconnect) is booked once, by ``execId``;
    an order IBKR no longer holds, or one from an earlier ET day (a DAY order), is closed out as
    ``filled``, ``partial`` or ``cancelled``. Returns the rows settled. Never raises."""
    from src.common.market_hours import today_et

    try:
        rows = await asyncio.to_thread(store.working_orders)
    except Exception:
        log.warning("hedge: working orders unreadable", exc_info=True)
        return 0
    if not rows:
        return 0
    try:
        fills = await asyncio.wait_for(ib.reqExecutionsAsync(), timeout=30.0)
    except Exception:
        log.warning("hedge: reqExecutions failed; working orders left as they are", exc_info=True)
        return 0
    open_refs = {
        str(getattr(t.order, "orderRef", "") or "")
        for t in (ib.openTrades() if hasattr(ib, "openTrades") else [])
    }
    day = today or today_et()
    settled = 0
    for row in rows:
        ref = row["order_ref"]
        mine = [
            f
            for f in fills
            if str(getattr(f.execution, "orderRef", "") or "") == ref
            and str(getattr(f.contract, "secType", "") or "") in ("OPT", "BAG")
        ]
        counted = counted_executions(mine)  # a vertical's legs also report: the combo counts once
        known = store.fill_exec_ids(row["id"])
        new = [f for f in counted if str(getattr(f.execution, "execId", None)) not in known]
        _book_executions(
            new,
            order_id=row["id"],
            hedge_id=row["hedge_id"],
            sign=1.0 if row["intent"] == "open" else -1.0,
            multiplier=int(row.get("multiplier") or 100),
            known=known,
        )
        # what is booked is the truth: never the stored count plus the new, which double counts
        # an execution the executor had already booked
        filled = max(float(row["filled_qty"] or 0.0), store.order_booked_qty(row["id"]))
        created = row["created_at"]
        stale = created is not None and created.replace(tzinfo=UTC).astimezone(_ET).date() < day
        if ref in open_refs and not stale and filled < row["contracts"] - 1e-9:
            if filled > float(row["filled_qty"] or 0.0):
                store.update_order(row["id"], filled_qty=filled)
            continue
        state = (
            "filled"
            if filled >= row["contracts"] - 1e-9
            else "partial"
            if filled > 0
            else "cancelled"
        )
        store.update_order(
            row["id"],
            state=state,
            filled_qty=filled,
            detail="settled from the broker's executions",
        )
        settled += 1
    return settled
