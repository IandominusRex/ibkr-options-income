"""Persistence for assessed contracts — what the scan looked at and why it passed.

Every scan prices contracts and sets most of them aside. Until now that decision left no
durable trace: generator-stage filters emitted an aggregate log counter, gate-stage verdicts
were in-memory only, and dedupe/top-N losers vanished entirely. So a question like "why did
NVDA never produce a CSP in July — was it IV rank, the delta band, or did it keep losing the
slot to a better strike?" had no answer once the Telegram status message rolled over.

This module writes one :class:`RiskVerdictRow` per assessed contract per run. Read-only
forensics and calibration data for the ideal zone; nothing in the pipeline reads it back, so
it can never affect a trading decision.

Best-effort throughout: a write failure is logged and swallowed. Losing an audit row must
never abort a scan.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from src.common.schemas import AssessedContract
from src.storage.db import session_scope
from src.storage.models import RiskVerdictRow

log = logging.getLogger(__name__)


def record_assessments(run_id: str, assessed: list[AssessedContract]) -> int:
    """Persist every contract *assessed* during run *run_id*. Returns the number written."""
    if not assessed:
        return 0
    try:
        rows = [_to_row(run_id, item) for item in assessed]
        with session_scope() as s:
            s.add_all(rows)
        return len(rows)
    except Exception:
        log.warning("record_assessments(%s) failed — audit trail skipped", run_id, exc_info=True)
        return 0


def purge_old_risk_verdicts(days: int = 14) -> int:
    """Delete assessment rows older than *days*. Returns the number deleted.

    A scan writes hundreds of rows per run and ~26 runs a day, so without pruning this table
    would dominate the database.
    """
    cutoff = datetime.now(UTC) - timedelta(days=days)
    try:
        with session_scope() as s:
            deleted = (
                s.query(RiskVerdictRow)
                .filter(RiskVerdictRow.created_at < cutoff)
                .delete(synchronize_session=False)
            )
        if deleted:
            log.info("Pruned %d risk_verdicts row(s) older than %d days", deleted, days)
        return int(deleted or 0)
    except Exception:
        log.exception("risk_verdicts purge failed")
        return 0


def _to_row(run_id: str, item: AssessedContract) -> RiskVerdictRow:
    cand = item.candidate
    zone = cand.ideal
    return RiskVerdictRow(
        candidate_id=cand.candidate_id,
        run_id=run_id,
        symbol=cand.underlying,
        strategy=cand.strategy.value,
        strike=cand.strike,
        expiry=cand.expiry,
        verdict="pass" if item.passed else "reject",
        stage=item.stage.value,
        reasons=list(item.reasons),
        blended_score=cand.blended_score,
        premium=cand.premium,
        ideal_lo=zone.strike_lo if zone else None,
        ideal_hi=zone.strike_hi if zone else None,
        min_credit=zone.min_credit if zone else None,
    )
