"""Position management — buy-to-close execution for short option positions.

This module exists to close SYSTEM_REVIEW.md finding **F1**: the profit-take
auto-close path used to call ``ib.placeOrder`` directly, bypassing the order/fill
storage layer, the cancel-on-timeout discipline, and the idempotency guards that
every *entry* order goes through. The consequences were severe in AUTOMATED mode:

  * no cancel-on-timeout left a working DAY order at IBKR; the next intraday cycle
    saw the position still short and placed a *second* buy-to-close → potential net
    long calls the account never wanted;
  * no ``FillRow`` meant EOD cashflow overstated the day (the BUY debit was invisible)
    and the verdict-ledger reconciler mislabeled auto-closed positions as
    ``expired_worthless`` with the full premium as realized P&L, corrupting the
    learning loop's training labels;
  * the close never appeared in ``/fills`` or ``/status``.

``close_short_position`` routes the buy-to-close through the same ``OrderRow``/
``FillRow`` lifecycle and cancel-on-timeout discipline as ``executor.execute_candidate``.

Buy-to-close is risk-*reducing*, so it deliberately does **not** pass through the
income Rules Engine gate (which exists to size/limit *new* exposure). It does go
through the order/fill records and the cancel discipline — the part F1 found missing.
Contract-level idempotency (a deterministic synthetic ``candidate_id``) prevents a
working close from being doubled by the next intraday cycle.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date
from typing import cast

from ib_async import IB, LimitOrder
from ib_async import Contract as IBContract
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.common.config import get_config
from src.common.schemas import OrderState, PositionSnapshot
from src.execution.executor import _as_float, _refetch_bid_ask, _safe_float
from src.execution.order_builder import reprice_limit
from src.ibkr.contracts import build_option
from src.storage.db import session_scope
from src.storage.models import CandidateRow, FillRow, OrderRow
from src.storage.orders import open_short_candidate_id

log = logging.getLogger(__name__)


@dataclass
class CloseResult:
    """Outcome of a buy-to-close attempt, returned to the caller for notification."""

    status: str  # "filled" | "partial" | "working" | "skipped" | "error"
    symbol: str
    qty: int
    limit_price: float
    filled_qty: float = 0.0
    avg_price: float = 0.0
    detail: str | None = None


def close_candidate_id(pos: PositionSnapshot) -> str:
    """Deterministic synthetic candidate id for a buy-to-close of *pos*.

    The same short position always maps to the same id, so ``has_active_order``
    blocks a second close while the first is still QUEUED/SUBMITTED/FILLED/PARTIAL.
    """
    assert pos.expiry is not None and pos.strike is not None and pos.right is not None
    expiry = pos.expiry.strftime("%Y%m%d") if isinstance(pos.expiry, date) else str(pos.expiry)
    return f"close:{pos.underlying or pos.symbol}:{expiry}:{pos.strike:g}:{pos.right.value}"


async def close_short_position(
    ib_exec: IB,
    pos: PositionSnapshot,
    bid: float,
    ask: float,
) -> CloseResult:
    """Buy-to-close a short option position at mid, recording the full order/fill lifecycle.

    Idempotent at the contract level: if an active close order already exists for this
    position, returns ``status="skipped"`` without placing anything.
    """
    assert pos.expiry is not None and pos.strike is not None and pos.right is not None

    cfg = get_config()
    cand_id = close_candidate_id(pos)
    qty = int(abs(pos.position))

    mid = (bid + ask) / 2 if bid > 0 else ask
    tick = 0.01 if mid < 3.0 else 0.05
    limit_price = round(round(mid / tick) * tick, 2)

    # 1. Idempotency + OrderRow creation in one transaction. has_active_order blocks a
    #    second close while the first is still working (the F1 stacking path).
    with session_scope() as session:
        if _close_blocked(session, cand_id, pos):
            log.info("close: active close order already exists for %s — skipping", pos.symbol)
            return CloseResult("skipped", pos.symbol, qty, limit_price, detail="already_working")
        order_row = OrderRow(
            candidate_id=cand_id,
            approval_id=None,  # closes have no approval; UniqueConstraint allows multiple NULLs
            state=OrderState.QUEUED,
            limit_price=limit_price,
            is_live=cfg.is_live,
            detail="buy-to-close (profit-take)",
        )
        session.add(order_row)
        session.flush()
        order_id = order_row.id

    placed = False
    try:
        contract = build_option(
            pos.underlying or pos.symbol, pos.expiry, pos.strike, pos.right.value
        )
        qualified_list = await ib_exec.qualifyContractsAsync(contract)
        if not qualified_list:
            _mark_order(order_id, OrderState.REJECTED, "could not qualify contract")
            return CloseResult("error", pos.symbol, qty, limit_price, detail="qualify_failed")
        qualified = cast(IBContract, qualified_list[0])

        order = LimitOrder("BUY", qty, limit_price, tif="DAY")
        trade = ib_exec.placeOrder(qualified, order)
        placed = True
        log.info(
            "close placed: %s qty=%d @ %.2f order_id=%s", pos.symbol, qty, limit_price, order_id
        )

        with session_scope() as session:
            row = session.get(OrderRow, order_id)
            if row:
                row.state = OrderState.SUBMITTED
                row.ib_order_id = trade.order.orderId

        # 2. Wait for terminal state or timeout — cancel on timeout (the F1 fix).
        # Optionally chase the fill by repricing toward the ask (config-gated; default off).
        exec_cfg = cfg.execution
        reprice_enabled = getattr(exec_cfg, "reprice_enabled", False) is True
        reprice_interval = _as_float(getattr(exec_cfg, "reprice_interval_seconds", 45.0), 45.0)
        max_reprices = int(_as_float(getattr(exec_cfg, "max_reprices", 0), 0.0))
        step_pct = _as_float(getattr(exec_cfg, "reprice_step_pct", 0.34), 0.34)

        loop = asyncio.get_running_loop()
        deadline = loop.time() + cfg.execution.fill_timeout_minutes * 60
        next_reprice_at = loop.time() + reprice_interval
        reprices_done = 0
        while not trade.isDone():
            await asyncio.sleep(1)
            now = loop.time()
            if now > deadline:
                log.warning(
                    "close fill timeout for %s order_id=%s — cancelling", pos.symbol, order_id
                )
                ib_exec.cancelOrder(trade.order)
                await asyncio.sleep(2)
                break
            if (
                reprice_enabled
                and reprices_done < max_reprices
                and now >= next_reprice_at
                and not trade.isDone()
            ):
                next_reprice_at = now + reprice_interval
                cur_limit = _safe_float(order.lmtPrice)
                fresh_bid, fresh_ask = await _refetch_bid_ask(ib_exec, qualified)
                new_price = (
                    reprice_limit("BUY", cur_limit, fresh_bid, fresh_ask, step_pct)
                    if cur_limit is not None and fresh_ask is not None
                    else None
                )
                if new_price is not None:
                    order.lmtPrice = new_price
                    ib_exec.placeOrder(qualified, order)
                    reprices_done += 1
                    log.info(
                        "close reprice %d/%d %s -> %.2f",
                        reprices_done,
                        max_reprices,
                        pos.symbol,
                        new_price,
                    )
                    with session_scope() as session:
                        row = session.get(OrderRow, order_id)
                        if row:
                            row.limit_price = new_price

        filled_qty = float(getattr(trade.orderStatus, "filled", 0.0) or 0.0)
        avg_price = float(getattr(trade.orderStatus, "avgFillPrice", 0.0) or 0.0)

        # 3. Record the fill (action="BUY" → EOD cashflow debit; ledger sees the close).
        if filled_qty > 0:
            exec_id: str | None = None
            commission: float | None = None
            if trade.fills:
                exec_id = getattr(getattr(trade.fills[-1], "execution", None), "execId", None)
                total_comm = 0.0
                for f in trade.fills:
                    cr = getattr(f, "commissionReport", None)
                    if cr is not None:
                        c = getattr(cr, "commission", None)
                        if c is not None and c > 0:
                            total_comm += c
                commission = total_comm if total_comm > 0 else None

            new_state = OrderState.FILLED if filled_qty >= qty else OrderState.PARTIAL
            with session_scope() as session:
                # The fill belongs to the short it closes (verdict ledger, /pnl/system); the
                # synthetic id stays on the OrderRow as the idempotency key.
                fill_candidate = (
                    open_short_candidate_id(
                        session,
                        pos.underlying or pos.symbol,
                        pos.right.value,
                        pos.strike,
                        pos.expiry,
                    )
                    or cand_id
                )
                session.add(
                    FillRow(
                        order_id=order_id,
                        candidate_id=fill_candidate,
                        action="BUY",  # buy-to-close debit
                        filled_qty=filled_qty,
                        avg_price=avg_price,
                        commission=commission,
                        ib_exec_id=exec_id,
                        is_live=cfg.is_live,
                    )
                )
                row = session.get(OrderRow, order_id)
                if row:
                    row.state = new_state
                    row.filled_qty = filled_qty
                    row.avg_fill_price = avg_price
            log.info(
                "close filled: %s qty=%.0f @ %.2f state=%s",
                pos.symbol,
                filled_qty,
                avg_price,
                new_state,
            )
            status = "filled" if new_state == OrderState.FILLED else "partial"
            return CloseResult(status, pos.symbol, qty, limit_price, filled_qty, avg_price)

        # No fill: order was cancelled on timeout (or never worked).
        _mark_order(order_id, OrderState.CANCELLED, "no fill before timeout")
        return CloseResult("working", pos.symbol, qty, limit_price, detail="cancelled_no_fill")

    except Exception:
        log.exception("close failed for %s", pos.symbol)
        if placed:
            # IBKR holds the order (2026-10-02: the Gateway dropped mid-reprice and the order
            # filled 8s later). REJECTED would be false and would let the next cycle stack a
            # second buy-to-close; SUBMITTED keeps has_active_order blocking that, and
            # reconcile_orphan_fills records the fill or expires the DAY order.
            _mark_order(
                order_id,
                OrderState.SUBMITTED,
                "error after the order reached IBKR; awaiting fill reconciliation",
            )
            return CloseResult(
                "error", pos.symbol, qty, limit_price, detail="exception_after_placement"
            )
        _mark_order(order_id, OrderState.REJECTED, "exception during close")
        return CloseResult("error", pos.symbol, qty, limit_price, detail="exception")


def _close_blocked(session: Session, cand_id: str, pos: PositionSnapshot) -> bool:
    """True when a close for this contract is working, or already filled for this sale.

    A working (QUEUED/SUBMITTED) close always blocks. A FILLED/PARTIAL one blocks too (a
    stale portfolio snapshot can still show the short right after its close fills, and a
    second buy-to-close would leave the account net long), but only until the system sells
    the contract again: ``cand_id`` is per contract, so counting every past filled close
    would block a later re-sale of the same strike/expiry from ever being auto-closed.
    """
    assert pos.expiry is not None and pos.strike is not None and pos.right is not None
    closes = session.execute(
        select(OrderRow.state, OrderRow.created_at).where(
            OrderRow.candidate_id == cand_id,
            OrderRow.state.in_(
                [OrderState.QUEUED, OrderState.SUBMITTED, OrderState.FILLED, OrderState.PARTIAL]
            ),
        )
    ).all()
    if any(state in (OrderState.QUEUED, OrderState.SUBMITTED) for state, _ in closes):
        return True
    last_sale = session.execute(
        select(func.max(FillRow.filled_at))
        .join(CandidateRow, CandidateRow.candidate_id == FillRow.candidate_id)
        .where(
            FillRow.action == "SELL",
            CandidateRow.underlying == (pos.underlying or pos.symbol),
            CandidateRow.right == pos.right.value,
            CandidateRow.expiry == pos.expiry,
            func.abs(CandidateRow.strike - pos.strike) < 1e-3,
        )
    ).scalar_one_or_none()
    return any(last_sale is None or created_at > last_sale for _, created_at in closes)


def _mark_order(order_id: int, state: str, detail: str) -> None:
    with session_scope() as session:
        row = session.get(OrderRow, order_id)
        if row:
            row.state = state
            row.detail = detail
