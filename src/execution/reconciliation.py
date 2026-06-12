"""Broker ↔ DB reconciliation: recover orders/fills the daemon may have missed.

Extracted from ``approval_service`` (SYSTEM_REVIEW structural finding — the notify layer
should not own broker reconciliation). Two recovery paths, both strictly additive against
the broker (they only reset stuck local state or record *proven* fills — never cancel or
resubmit, so they cannot cause a double trade):

* :func:`recover_orphan_orders` — SUBMITTED rows with no ``ib_order_id`` (claimed by a prior
  process that crashed before ``placeOrder``) are reset to QUEUED so the poll loop retries.
* :func:`reconcile_orphan_fills` — SUBMITTED rows *with* an ``ib_order_id`` whose fill event
  was lost during a socket drop get their FillRow back-filled from ``reqExecutions``. Run at
  startup **and** periodically from the intraday loop (SYSTEM_REVIEW F7) so a fill that lands
  during a mid-session reconnect is recovered on the next cycle, not only on the next restart.
"""

from __future__ import annotations

import logging
from datetime import date

from ib_async import IB
from sqlalchemy import select

from src.claude.memory import FILLED, record_outcome
from src.common.config import get_config
from src.common.schemas import OrderState
from src.storage.db import session_scope
from src.storage.models import CandidateRow, FillRow, OrderRow

log = logging.getLogger(__name__)


def recover_orphan_orders() -> None:
    """Reset SUBMITTED orders with no IB order id back to QUEUED (crash before placeOrder)."""
    with session_scope() as s:
        orphans = (
            s.query(OrderRow)
            .filter(OrderRow.state == OrderState.SUBMITTED, OrderRow.ib_order_id.is_(None))
            .all()
        )
        for o in orphans:
            o.state = OrderState.QUEUED
            log.warning("Recovered orphan order id=%s to QUEUED", o.id)


def _expiry_to_date(yyyymmdd: str) -> date | None:
    if not yyyymmdd or len(yyyymmdd) < 8:
        return None
    try:
        return date(int(yyyymmdd[0:4]), int(yyyymmdd[4:6]), int(yyyymmdd[6:8]))
    except (ValueError, TypeError):
        return None


def _exec_matches_candidate(fill: object, candidate: CandidateRow, ib_order_id: int | None) -> bool:
    """True if an IBKR Fill corresponds to the opening (SELL) order for *candidate*.

    Primary match is the broker order id (stable within a clientId session); falls back to a
    contract match (symbol / right / strike / expiry) so a fill is still recovered after an id
    churn across a full restart.
    """
    execution = getattr(fill, "execution", None)
    contract = getattr(fill, "contract", None)
    if execution is None or contract is None:
        return False

    if ib_order_id is not None and getattr(execution, "orderId", None) == ib_order_id:
        return True

    if getattr(contract, "symbol", None) != candidate.underlying:
        return False
    right = str(getattr(contract, "right", "") or "")[:1].upper()
    if right and candidate.right and right != candidate.right[:1].upper():
        return False
    if candidate.strike and abs(float(getattr(contract, "strike", 0.0)) - candidate.strike) > 1e-3:
        return False
    exp = _expiry_to_date(str(getattr(contract, "lastTradeDateOrContractMonth", "")))
    if candidate.expiry and exp is not None and exp != candidate.expiry:
        return False
    # Opening income trades are sells; ignore buy-side executions (e.g. a buy-to-close).
    side = str(getattr(execution, "side", "") or "").upper()
    return side in ("", "SLD")


async def reconcile_orphan_fills(ib: IB, bot: object, chat_id: str) -> None:
    """Recover SELL fills that landed while the service was disconnected.

    For any SUBMITTED order with a matching execution and no FillRow, record the fill, mark
    the order FILLED/PARTIAL, and notify. Idempotent (skips orders that already have a
    FillRow), so it is safe to run repeatedly — at startup and on the intraday cadence.
    """
    with session_scope() as s:
        rows = (
            s.query(OrderRow)
            .filter(OrderRow.state == OrderState.SUBMITTED, OrderRow.ib_order_id.isnot(None))
            .all()
        )
        orphans = [(o.id, o.candidate_id, o.ib_order_id) for o in rows]
        already_filled = {
            fid
            for (fid,) in s.query(FillRow.order_id).filter(
                FillRow.order_id.in_([o.id for o in rows] or [-1])
            )
        }
    orphans = [o for o in orphans if o[0] not in already_filled]
    if not orphans:
        return

    try:
        fills = await ib.reqExecutionsAsync()
    except Exception:
        log.exception("Fill reconciliation: reqExecutions failed")
        return

    is_live = bool(get_config().is_live)
    recovered = 0
    for order_id, candidate_id, ib_order_id in orphans:
        with session_scope() as s:
            cand = s.execute(
                select(CandidateRow).where(CandidateRow.candidate_id == candidate_id)
            ).scalar_one_or_none()
            if cand is None:
                continue
            matched = [f for f in fills if _exec_matches_candidate(f, cand, ib_order_id)]
            if not matched:
                continue

            total_qty = 0.0
            notional = 0.0
            commission = 0.0
            exec_id = None
            for f in matched:
                ex = f.execution
                shares = float(getattr(ex, "shares", 0.0) or 0.0)
                price = float(getattr(ex, "price", 0.0) or 0.0)
                total_qty += shares
                notional += shares * price
                exec_id = getattr(ex, "execId", exec_id)
                cr = getattr(f, "commissionReport", None)
                c = getattr(cr, "commission", None) if cr is not None else None
                if c:
                    commission += float(c)
            if total_qty <= 0:
                continue
            avg_price = notional / total_qty

            order = s.get(OrderRow, order_id)
            if order is None or order.state != OrderState.SUBMITTED:
                continue
            payload = cand.payload or {}
            contracts = float(payload.get("contracts", total_qty))
            order.state = OrderState.FILLED if total_qty >= contracts else OrderState.PARTIAL
            order.filled_qty = total_qty
            order.avg_fill_price = avg_price
            order.detail = "Recovered from reqExecutions"
            s.add(
                FillRow(
                    order_id=order_id,
                    candidate_id=candidate_id,
                    action="SELL",
                    filled_qty=total_qty,
                    avg_price=avg_price,
                    commission=commission or None,
                    ib_exec_id=exec_id,
                    is_live=is_live,
                )
            )
        record_outcome(candidate_id, FILLED)
        recovered += 1
        log.warning(
            "Fill reconciliation: recovered fill for order_id=%s candidate=%s qty=%.0f @ %.2f",
            order_id,
            candidate_id,
            total_qty,
            avg_price,
        )
        try:
            await bot.send_message(  # type: ignore[attr-defined]
                chat_id=chat_id,
                text=(
                    f"♻️ Recovered a missed fill: {cand.underlying} "
                    f"{total_qty:.0f} @ {avg_price:.2f} (order_id={order_id})."
                ),
            )
        except Exception:
            log.exception("Fill reconciliation: failed to notify for order_id=%s", order_id)

    if recovered:
        log.warning("Fill reconciliation: recovered %d missed fill(s)", recovered)
