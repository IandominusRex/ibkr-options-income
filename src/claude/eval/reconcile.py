"""Close reconciler — attach the realized outcome to each ledger row when its trade settles.

The ledger row is written at scan time with `outcome=still_open`. This module is the only
place that moves it to a terminal state. It is *deterministic and DB-only*: it joins the
ledger against fills, orders, and approvals already persisted by the trading pipeline, so it
runs without IBKR and is fully unit-testable.

Outcome decision (per still-open ledger row):

  has a SELL (entry) fill?
    ├─ yes → entry economics recorded; row is `filled`
    │        ├─ has a BUY (close) fill?  → CLOSED_EARLY,  realized = credit − debit − commissions
    │        ├─ else past expiry?
    │        │     ├─ flagged assigned   → ASSIGNED,      realized = premium kept (option leg)*
    │        │     └─ else               → EXPIRED_WORTHLESS, realized = premium kept
    │        └─ else                     → STILL_OPEN (just stamp fill economics)
    └─ no  → approval rejected?          → USER_REJECTED
             order risk-rejected?        → RISK_REJECTED
             approval expired / past expiry / order cancelled → NOT_FILLED
             else                        → STILL_OPEN (await execution)

  *Assignment realizes additional stock-leg P&L that this option-leg ledger does not model;
   the realized figure for ASSIGNED is the premium kept and is flagged approximate. Whether a
   row is "assigned" is a caller decision (it needs position knowledge) passed via
   `assigned_candidate_ids`; on its own the reconciler treats every past-expiry short as
   expired-worthless, the common income-desk case.

`OPTION_MULTIPLIER` (100) converts per-share premium to contract dollars.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import date
from zoneinfo import ZoneInfo

from sqlalchemy import select

from src.claude.eval.ledger import open_filled_records
from src.common.market_hours import today_et
from src.common.schemas import VerdictOutcome
from src.storage.db import session_scope
from src.storage.models import (
    ApprovalRow,
    FillRow,
    OrderRow,
    VerdictLedgerRow,
)

log = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")
OPTION_MULTIPLIER = 100


def _fill_economics(fills: list[FillRow]) -> tuple[float, float, float, float, int]:
    """Split fills into entry (SELL) and close (BUY) legs.

    Returns (credit_dollars, debit_dollars, commissions, entry_premium_per_share, entry_qty).
    """
    credit = debit = commissions = 0.0
    entry_notional = 0.0  # Σ price*qty over SELL fills, for the qty-weighted entry premium
    entry_qty = 0
    for f in fills:
        commissions += f.commission or 0.0
        dollars = f.avg_price * f.filled_qty * OPTION_MULTIPLIER
        if (f.action or "SELL").upper() == "BUY":
            debit += dollars
        else:
            credit += dollars
            entry_notional += f.avg_price * f.filled_qty
            entry_qty += int(f.filled_qty)
    entry_premium = (entry_notional / entry_qty) if entry_qty else 0.0
    return credit, debit, commissions, entry_premium, entry_qty


def _classify(
    candidate_id: str,
    fills: list[FillRow],
    approval: ApprovalRow | None,
    order: OrderRow | None,
    expiry: date,
    today: date,
    assigned: bool,
) -> tuple[VerdictOutcome, float | None, bool, float | None, int | None]:
    """Pure outcome decision. Returns
    (outcome, realized_pnl, filled, entry_premium, contracts)."""
    sell_fills = [f for f in fills if (f.action or "SELL").upper() == "SELL"]
    buy_fills = [f for f in fills if (f.action or "SELL").upper() == "BUY"]

    if sell_fills:
        credit, debit, commissions, entry_premium, entry_qty = _fill_economics(fills)
        if buy_fills:
            realized = credit - debit - commissions
            return VerdictOutcome.CLOSED_EARLY, realized, True, entry_premium, entry_qty
        if today > expiry:
            realized = credit - commissions  # premium kept (option leg)
            outcome = VerdictOutcome.ASSIGNED if assigned else VerdictOutcome.EXPIRED_WORTHLESS
            return outcome, realized, True, entry_premium, entry_qty
        # Filled and live, not yet expired — stamp economics, stay open.
        return VerdictOutcome.STILL_OPEN, None, True, entry_premium, entry_qty

    # Never filled.
    if approval is not None and approval.status == "rejected":
        return VerdictOutcome.USER_REJECTED, None, False, None, None
    if order is not None and order.state == "rejected":
        return VerdictOutcome.RISK_REJECTED, None, False, None, None
    stale = (
        today > expiry
        or (order is not None and order.state == "cancelled")
        or (approval is not None and approval.status == "expired")
    )
    if stale:
        return VerdictOutcome.NOT_FILLED, None, False, None, None
    return VerdictOutcome.STILL_OPEN, None, False, None, None


def reconcile(
    *,
    today: date | None = None,
    assigned_candidate_ids: Iterable[str] | None = None,
    include_unfilled: bool = True,
) -> dict[str, int]:
    """Reconcile open ledger rows against persisted fills/orders/approvals.

    Args:
        today: ET date to evaluate expiry against (defaults to now in ET).
        assigned_candidate_ids: rows whose past-expiry short was actually assigned (the caller
            determines this from positions); everything else past expiry is expired-worthless.
        include_unfilled: also sweep never-filled rows for user/risk rejection or staleness.
            When False, only filled-and-open rows are reconciled (faster; for intraday use).

    Returns a count of rows moved into each terminal outcome. Never raises.
    """
    today = today or today_et()
    assigned = set(assigned_candidate_ids or ())
    counts: dict[str, int] = {}

    try:
        rows = _rows_to_reconcile(include_unfilled)
    except Exception:
        log.exception("reconcile: failed to load ledger rows")
        return counts

    for cid, expiry in rows:
        try:
            outcome, realized, filled, entry_premium, contracts = _reconcile_one(
                cid, expiry, today, cid in assigned
            )
        except Exception:
            log.exception("reconcile: failed on candidate %s", cid)
            continue
        if outcome == VerdictOutcome.STILL_OPEN and not filled:
            continue  # nothing to record yet
        from src.claude.eval.ledger import update_outcome

        if update_outcome(
            cid,
            outcome,
            realized_pnl=realized,
            outcome_date=today if outcome != VerdictOutcome.STILL_OPEN else None,
            filled=filled,
            entry_premium=entry_premium,
            contracts=contracts,
        ):
            if outcome != VerdictOutcome.STILL_OPEN:
                counts[outcome.value] = counts.get(outcome.value, 0) + 1

    if counts:
        log.info("reconcile: %s", counts)
    return counts


def _rows_to_reconcile(include_unfilled: bool) -> list[tuple[str, date]]:
    """(candidate_id, expiry) for every still-open ledger row needing a look."""
    if not include_unfilled:
        return [(r.candidate_id, r.expiry) for r in open_filled_records()]
    with session_scope() as sess:
        rows = (
            sess.execute(
                select(VerdictLedgerRow.candidate_id, VerdictLedgerRow.expiry).where(
                    VerdictLedgerRow.outcome == VerdictOutcome.STILL_OPEN.value
                )
            )
            .tuples()
            .all()
        )
    return [(cid, expiry) for cid, expiry in rows]


def _reconcile_one(
    candidate_id: str,
    expiry: date,
    today: date,
    assigned: bool,
) -> tuple[VerdictOutcome, float | None, bool, float | None, int | None]:
    with session_scope() as sess:
        fills = list(
            sess.execute(select(FillRow).where(FillRow.candidate_id == candidate_id)).scalars()
        )
        order = (
            sess.execute(
                select(OrderRow)
                .where(OrderRow.candidate_id == candidate_id)
                .order_by(OrderRow.created_at.desc())
            )
            .scalars()
            .first()
        )
        approval = (
            sess.execute(
                select(ApprovalRow)
                .where(ApprovalRow.candidate_id == candidate_id)
                .order_by(ApprovalRow.created_at.desc())
            )
            .scalars()
            .first()
        )
        # Detach the pure-decision inputs from the session before it closes.
        fills_snapshot = [
            FillRow(
                candidate_id=f.candidate_id,
                action=f.action,
                filled_qty=f.filled_qty,
                avg_price=f.avg_price,
                commission=f.commission,
            )
            for f in fills
        ]
        approval_status = approval.status if approval else None
        order_state = order.state if order else None

    approval_stub = ApprovalRow(status=approval_status) if approval_status else None
    order_stub = OrderRow(state=order_state) if order_state else None
    return _classify(
        candidate_id, fills_snapshot, approval_stub, order_stub, expiry, today, assigned
    )
