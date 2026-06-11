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

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.common.schemas import OrderState
from src.storage.models import OrderRow

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
