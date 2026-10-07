"""Order-creation idempotency helpers.

The deterministic ``candidate_id`` (hash of strategy/underlying/right/strike/expiry)
means every scan of the same option produces the same id. The 15-minute automated
intraday loop therefore regenerates identical candidates each cycle; without a guard,
each cycle would mint a fresh approval + order and stack a duplicate position on top of
one that is already working or filled (for covered calls — which bypass the cumulative
exposure gates — this ends in naked short calls).

``has_active_order`` is the single chokepoint both order-creation paths consult
(``sender._auto_queue_candidates`` for automated mode, ``approval_service._process_button``
for manual approvals).
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.common.schemas import OrderState
from src.storage.models import CandidateRow, FillRow, OrderRow

# States in which a prior order for the same candidate makes a new order a duplicate:
# still working (QUEUED/SUBMITTED) or already executed (FILLED/PARTIAL). Terminal
# failures (CANCELLED/REJECTED) are NOT included — a candidate that was TTL-cancelled or
# transiently re-gate-rejected may legitimately be re-proposed on a later scan.
_ACTIVE_ORDER_STATES = (
    OrderState.QUEUED,
    OrderState.SUBMITTED,
    OrderState.FILLED,
    OrderState.PARTIAL,
)


def has_active_order(session: Session, candidate_id: str) -> bool:
    """Return True if an open or already-filled order exists for *candidate_id*.

    Note: this is an application-level check, not atomic across concurrent callers.
    It closes the realistic stacking path (the sequential 15-min loop, and repeat
    manual approvals of the same re-surfaced candidate). The remaining race — two
    concurrent callbacks for two *different* approvals of the same candidate — is
    bounded by ``OrderRow.approval_id`` uniqueness only when they share an approval;
    a partial unique index on ``candidate_id`` would close it fully.
    """
    count = session.execute(
        select(func.count())
        .select_from(OrderRow)
        .where(
            OrderRow.candidate_id == candidate_id,
            OrderRow.state.in_(_ACTIVE_ORDER_STATES),
        )
    ).scalar_one()
    return count > 0


def active_order_for(session: Session, candidate_id: str) -> OrderRow | None:
    """The most recent active order for *candidate_id*, or None.

    The row-level companion to ``has_active_order`` (same active-state set). M5 Task 5.1's
    ``roll_request`` drain handler uses it to link a ``roll_already_working`` receipt to the
    approval the working order came from — ``has_active_order`` answers the yes/no, this
    returns the row whose ``approval_id`` the receipt links to. Ordered newest-first so a
    candidate with a filled order followed by a fresh re-queue still links to the live one.
    """
    return session.execute(
        select(OrderRow)
        .where(
            OrderRow.candidate_id == candidate_id,
            OrderRow.state.in_(_ACTIVE_ORDER_STATES),
        )
        .order_by(OrderRow.created_at.desc(), OrderRow.id.desc())
        .limit(1)
    ).scalar_one_or_none()


def open_short_candidate_id(
    session: Session, underlying: str, right: str, strike: float, expiry: date
) -> str | None:
    """The system short a buy-to-close of this exact contract closes, or None.

    A close's ``OrderRow`` carries a synthetic ``close:`` id (the idempotency key), but its
    BUY ``FillRow`` belongs on the candidate that SOLD the contract: the verdict-ledger
    reconciler and ``/pnl/system`` pair a short's fills by ``candidate_id``, so a debit filed
    under the synthetic id is invisible to both (2026-10: five profit-take closes read as
    still open). Picks the most recently sold candidate that is still net short
    (Σ SELL − Σ BUY > 0); None when the system never sold it (a hand-opened short).
    """
    rows = session.execute(
        select(CandidateRow.candidate_id, CandidateRow.strike, FillRow.action, FillRow.filled_qty)
        .join(FillRow, FillRow.candidate_id == CandidateRow.candidate_id)
        .where(
            CandidateRow.underlying == underlying,
            CandidateRow.right == right[:1].upper(),
            CandidateRow.expiry == expiry,
        )
        .order_by(FillRow.filled_at)
    ).all()
    net: dict[str, float] = {}
    for candidate_id, cand_strike, action, qty in rows:
        if abs((cand_strike or 0.0) - strike) >= 1e-3:
            continue
        sign = -1.0 if (action or "SELL").upper() == "BUY" else 1.0
        net[candidate_id] = net.get(candidate_id, 0.0) + sign * (qty or 0.0)
    open_ids = [cid for cid, q in net.items() if q > 0]
    return open_ids[-1] if open_ids else None
