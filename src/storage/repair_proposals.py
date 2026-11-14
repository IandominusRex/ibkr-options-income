"""The ``repair_proposals`` table (risk-envelope Task 30; spec §3.7 item 2, ruling P10).

Written by the EOD run (``save_proposals``), decided by a Telegram tap (``decide``), and re-marked
every EOD whether tapped or not (``mark_shadow_values``). Nothing on the trading path reads a
proposal back except the tap handler that acts on the one the human tapped.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, date, datetime

from sqlalchemy import select

from src.common.schemas import RepairProposal
from src.storage.db import session_scope
from src.storage.models import RepairProposalRow

log = logging.getLogger(__name__)


def save_proposals(proposals: list[RepairProposal], day: date) -> list[RepairProposal]:
    """Insert each proposal not stored yet for (*day*, kind, symbol); return the new ones with
    their ids. A re-run of the EOD on the same day adds nothing."""
    saved: list[RepairProposal] = []
    with session_scope() as s:
        have = {
            (k, sym)
            for k, sym in s.execute(
                select(RepairProposalRow.kind, RepairProposalRow.symbol).where(
                    RepairProposalRow.day == day
                )
            ).all()
        }
        for p in proposals:
            if (p.kind, p.symbol) in have:
                continue
            row = RepairProposalRow(
                day=day,
                kind=p.kind,
                symbol=p.symbol,
                detail=p.detail,
                s10_before=p.s10_before,
                s10_after=p.s10_after,
                uew_before=p.uew_before,
                uew_after=p.uew_after,
                s10_limit=p.s10_limit,
                uew_limit=p.uew_limit,
                payload=p.model_dump(mode="json"),
                status="pending",
            )
            s.add(row)
            s.flush()
            have.add((p.kind, p.symbol))
            saved.append(p.model_copy(update={"id": row.id}))
    return saved


def load_proposal(proposal_id: int) -> tuple[RepairProposal, str] | None:
    """The stored proposal and its status, or None."""
    with session_scope() as s:
        row = s.get(RepairProposalRow, proposal_id)
        if row is None:
            return None
        return RepairProposal.model_validate({**row.payload, "id": row.id}), row.status


def decide(proposal_id: int, status: str, *, by: str, result: str | None = None) -> bool:
    """Move a pending proposal to *status* (``approved`` / ``rejected``), or a decided one to
    ``sent`` / ``failed``. False when it is missing, or already decided for a first decision (a
    repeated tap never acts twice)."""
    with session_scope() as s:
        row = s.get(RepairProposalRow, proposal_id)
        if row is None:
            return False
        first = status in ("approved", "rejected")
        if first and row.status != "pending":
            return False
        row.status = status
        if first:
            row.decided_at = datetime.now(UTC)
            row.decided_by = by
        if result is not None:
            row.result = result
        return True


Valuer = Callable[[RepairProposal], float | None]


def mark_shadow_values(today: date, value_of: Valuer) -> int:
    """Re-mark every proposal's ``shadow_value`` with *value_of* (``engine.repair.shadow_value``
    on the latest stored closes, composed by the EOD run), whatever its status (spec §3.7:
    shadow-valued whether tapped or not). Returns the rows marked."""
    marked = 0
    with session_scope() as s:
        for row in s.scalars(select(RepairProposalRow)):
            try:
                p = RepairProposal.model_validate({**row.payload, "id": row.id})
            except Exception:
                log.warning("repair proposal %s unreadable, not marked", row.id, exc_info=True)
                continue
            try:
                value = value_of(p)
            except Exception:
                log.warning("repair proposal %s not valued", row.id, exc_info=True)
                continue
            if value is None:
                continue
            row.shadow_value = value
            row.shadow_marked_on = today
            marked += 1
    return marked
