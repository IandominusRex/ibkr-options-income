"""Turn a roll trigger into an approvable roll candidate (N20).

The intraday monitor fires a `RollAlert` when a short option breaches its delta/DTE/IV limits.
Historically that was alert-only — `generate_roll_candidates` had no production caller and
`execute_roll` was unreachable. This module closes the gap: given the triggered position and a
fresh chain, it generates the best roll candidate, persists it as a `CandidateRow`, and raises a
PENDING `ApprovalRow` (with the frozen snapshot, N2a). The existing Telegram Approve handler then
creates a QUEUED ROLL `OrderRow`, which `process_queued_orders` → `execute_candidate` routes to
`execute_roll` (the two-leg BAG combo).

Deterministic, synchronous DB work only — the caller (the monitor) does the chain fetch and the
Telegram send. Returns the approval id + candidate so the caller can attach the inline keyboard.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

from src.common.schemas import (
    ApprovalStatus,
    IVStats,
    OptionQuote,
    PositionSnapshot,
    TechnicalStats,
    TradeCandidate,
)
from src.storage.db import session_scope
from src.storage.models import ApprovalRow, CandidateRow
from src.storage.orders import has_active_order
from src.strategies.rolling import generate_roll_candidates

log = logging.getLogger(__name__)


def queue_roll_for_approval(
    position: PositionSnapshot,
    quotes: list[OptionQuote],
    iv_stats: IVStats,
    tech_stats: TechnicalStats,
    *,
    chat_id: str,
    ttl_minutes: int,
) -> tuple[int, TradeCandidate] | None:
    """Generate the best roll candidate for *position* and raise a PENDING approval for it.

    Returns ``(approval_id, candidate)`` so the caller can send an Approve/Reject message, or
    None when there is no qualifying roll or an order is already working for that candidate
    (idempotent against the monitor re-firing the same trigger). Never raises.
    """
    try:
        candidates = generate_roll_candidates(position, quotes, iv_stats, tech_stats)
        if not candidates:
            return None
        cand = candidates[0]  # generate_roll_candidates sorts by ROC desc

        with session_scope() as s:
            if has_active_order(s, cand.candidate_id):
                log.info("roll: active order already exists for %s — skipping", cand.candidate_id)
                return None

            # Upsert the candidate payload (same semantics as the scan persister).
            existing = (
                s.query(CandidateRow).filter(CandidateRow.candidate_id == cand.candidate_id).first()
            )
            if existing is not None:
                s.delete(existing)
                s.flush()
            snapshot = cand.model_dump(mode="json")
            s.add(
                CandidateRow(
                    candidate_id=cand.candidate_id,
                    run_id=f"roll-{uuid.uuid4().hex[:8]}",
                    strategy=cand.strategy.value,
                    underlying=cand.underlying,
                    right=cand.right.value,
                    strike=cand.strike,
                    expiry=cand.expiry,
                    blended_score=cand.blended_score,
                    payload=snapshot,
                )
            )
            approval = ApprovalRow(
                candidate_id=cand.candidate_id,
                status=ApprovalStatus.PENDING,
                chat_id=chat_id,
                expires_at=datetime.now(UTC) + timedelta(minutes=ttl_minutes),
                snapshot=snapshot,  # freeze the approved payload (N2a)
            )
            s.add(approval)
            s.flush()
            approval_id = approval.id
        log.info(
            "roll: queued candidate %s for approval (approval_id=%s)",
            cand.candidate_id,
            approval_id,
        )
        return approval_id, cand
    except Exception:
        log.exception("roll: failed to queue roll candidate for %s", position.symbol)
        return None
