"""Turn a promoted candidate into an approvable proposal (M4 Task 4.2).

The web console lets an operator promote a candidate the automated pipeline set aside for a
ranking reason (`score_floor`, `dedupe`, `top_n` — the API-boundary guard in
`src/api/routers/commands.py` refuses anything else before a command row can even exist).
`src/notify/command_drain.py`'s ``promote`` handler re-runs a single-ticker scan — a fresh
chain, fresh analytics, the real screens, the real score, the real Rules Engine gate — and,
only when the requested contract still clears every one of those, hands the resulting
`TradeCandidate` here.

This module is strictly the "persist + raise approval" half of
`roll_pipeline.queue_roll_for_approval` — it takes the candidate directly rather than
generating one (the handler has already produced the exact contract to promote via its own
fresh scan), so it never calls a strategy generator itself. Deterministic, synchronous DB
work only — no chain fetch, no gate, no LLM; the caller has already done all of that.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

from src.common.schemas import ApprovalStatus, TradeCandidate
from src.storage.db import session_scope
from src.storage.models import ApprovalRow, CandidateRow
from src.storage.orders import has_active_order

log = logging.getLogger(__name__)


def queue_promoted_for_approval(
    candidate: TradeCandidate,
    *,
    chat_id: str,
    ttl_minutes: int,
) -> int | None:
    """Persist *candidate* and raise a PENDING approval for it.

    Returns the approval id, or None when an order is already active for this candidate
    (idempotent against a replayed drain). Never raises.

    Deliberately mirrors roll_pipeline.queue_roll_for_approval: same has_active_order guard,
    same CandidateRow upsert, same N2a snapshot freeze onto the ApprovalRow. One difference:
    this takes a single TradeCandidate directly rather than raw position+quotes+analytics, so
    it does not call any strategy generator itself — it is strictly the "persist + raise
    approval" half of queue_roll_for_approval, not the "generate" half.
    """
    try:
        with session_scope() as s:
            if has_active_order(s, candidate.candidate_id):
                log.info(
                    "promote: active order already exists for %s — skipping",
                    candidate.candidate_id,
                )
                return None

            # Upsert the candidate payload (same semantics as the scan persister).
            existing = (
                s.query(CandidateRow)
                .filter(CandidateRow.candidate_id == candidate.candidate_id)
                .first()
            )
            if existing is not None:
                s.delete(existing)
                s.flush()
            snapshot = candidate.model_dump(mode="json")
            s.add(
                CandidateRow(
                    candidate_id=candidate.candidate_id,
                    run_id=f"promote-{uuid.uuid4().hex[:8]}",
                    strategy=candidate.strategy.value,
                    underlying=candidate.underlying,
                    right=candidate.right.value,
                    strike=candidate.strike,
                    expiry=candidate.expiry,
                    blended_score=candidate.blended_score,
                    payload=snapshot,
                )
            )
            approval = ApprovalRow(
                candidate_id=candidate.candidate_id,
                status=ApprovalStatus.PENDING,
                chat_id=chat_id,
                expires_at=datetime.now(UTC) + timedelta(minutes=ttl_minutes),
                snapshot=snapshot,  # freeze the approved payload (N2a)
            )
            s.add(approval)
            s.flush()
            approval_id = approval.id
        log.info(
            "promote: queued candidate %s for approval (approval_id=%s)",
            candidate.candidate_id,
            approval_id,
        )
        return approval_id
    except Exception:
        log.exception("promote: failed to queue candidate %s for approval", candidate.underlying)
        return None
