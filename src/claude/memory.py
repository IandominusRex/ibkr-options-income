"""Claude learning-loop outcomes.

`ClaudeMemoryRow` rows are written at scan time (in `orchestrator/scan.py`) with their
`outcome` left None. The pipeline back-fills the eventual outcome here so each later scan
can inject *what actually happened* — fills as well as rejections — into the strategist
prompt. Without recording fills, the memory would be negatively biased (rejections only).

Neutral module (depends only on storage) so executor / approval / approval_service can all
call it without import cycles.
"""

from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import select

from src.storage.db import session_scope
from src.storage.models import ClaudeMemoryRow

log = logging.getLogger(__name__)

# Recognized terminal outcomes (kept in sync with ClaudeMemoryRow.outcome docs).
FILLED = "filled"
USER_REJECTED = "user_rejected"
RISK_REJECTED = "risk_rejected"
EXPIRED = "expired"


def record_outcome(candidate_id: str | None, outcome: str) -> None:
    """Set `outcome` on the most recent ClaudeMemoryRow for `candidate_id`.

    No-op if the candidate has no memory row or an outcome is already recorded
    (terminal outcomes are mutually exclusive — don't clobber). Never raises.
    """
    if not candidate_id:
        return
    try:
        with session_scope() as sess:
            row = sess.execute(
                select(ClaudeMemoryRow)
                .where(ClaudeMemoryRow.candidate_id == candidate_id)
                .order_by(ClaudeMemoryRow.created_at.desc())
                .limit(1)
            ).scalar_one_or_none()
            if row and row.outcome is None:
                row.outcome = outcome
                row.outcome_date = date.today()
    except Exception:
        log.exception("Failed to record ClaudeMemoryRow outcome for %s", candidate_id)
