"""Outcome-ledger access layer.

Maps `VerdictLedgerRow` (ORM) ↔ `VerdictRecord` (schema) so every other module in the
enrichment loop works in terms of the Pydantic shape, never the ORM — consistent with the
project's "modules talk in schemas" invariant.

Writes are upserts on `candidate_id`: a re-scan refreshes the pre-outcome fields (signals,
verdict, baseline) without clobbering an outcome the reconciler may already have attached.
Every function swallows storage errors and logs — the ledger is observability, and must never
take the trading pipeline down.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.common.schemas import (
    OptionRight,
    Strategy,
    VerdictOutcome,
    VerdictRecord,
)
from src.storage.db import session_scope
from src.storage.models import OrderRow, VerdictLedgerRow

log = logging.getLogger(__name__)

# Outcomes that mean "this trade is done" — the reconciler skips these.
_TERMINAL = {
    VerdictOutcome.EXPIRED_WORTHLESS,
    VerdictOutcome.ASSIGNED,
    VerdictOutcome.CLOSED_EARLY,
    VerdictOutcome.NOT_FILLED,
    VerdictOutcome.USER_REJECTED,
    VerdictOutcome.RISK_REJECTED,
}


def _row_to_record(row: VerdictLedgerRow) -> VerdictRecord:
    return VerdictRecord(
        candidate_id=row.candidate_id,
        run_id=row.run_id,
        scan_date=row.scan_date,
        underlying=row.underlying,
        strategy=Strategy(row.strategy),
        right=OptionRight(row.right),
        strike=row.strike,
        expiry=row.expiry,
        dte=row.dte,
        signals=dict(row.signals or {}),
        claude_recommendation=row.claude_recommendation,
        claude_priority=row.claude_priority,
        claude_confidence=row.claude_confidence,
        claude_rationale=row.claude_rationale,
        baseline_recommendation=row.baseline_recommendation,
        baseline_rank=row.baseline_rank,
        baseline_score=row.baseline_score,
        agreement=row.agreement,
        outcome=VerdictOutcome(row.outcome),
        outcome_date=row.outcome_date,
        realized_pnl=row.realized_pnl,
        filled=row.filled,
        entry_premium=row.entry_premium,
        contracts=row.contracts,
    )


def record_verdicts(records: list[VerdictRecord]) -> int:
    """Upsert ledger rows for a scan. Returns the number written. Never raises.

    Refreshes the pre-outcome fields for an existing candidate but preserves any outcome
    already attached (so a re-scan of a candidate that has since closed doesn't reset it).

    Once an order exists for the candidate (it has been approved/queued), the signal vector is
    frozen (N2b): re-scans no longer refresh it, so the row that eventually receives the
    realized outcome still carries the signals of the scan that produced the fill — not a later
    scan's. This mirrors the approved-snapshot freeze on the OrderRow (N2a).
    """
    if not records:
        return 0
    try:
        with session_scope() as sess:
            for rec in records:
                existing = sess.execute(
                    select(VerdictLedgerRow).where(
                        VerdictLedgerRow.candidate_id == rec.candidate_id
                    )
                ).scalar_one_or_none()
                if existing is None:
                    sess.add(_record_to_new_row(rec))
                elif not _candidate_is_committed(sess, rec.candidate_id):
                    _refresh_presoutcome_fields(existing, rec)
                # else: an order exists — freeze the committed scan's signals (N2b).
        log.info("ledger: recorded %d verdict(s)", len(records))
        return len(records)
    except Exception:
        log.exception("ledger: failed to record verdicts")
        return 0


def _candidate_is_committed(sess: Session, candidate_id: str) -> bool:
    """True once any OrderRow exists for this candidate (approved/queued or beyond).

    The presence of an order means the candidate was committed to execution; from that point
    its ledger signal vector must not be overwritten by later re-scans (N2b).
    """
    return (
        sess.execute(select(OrderRow.id).where(OrderRow.candidate_id == candidate_id)).first()
        is not None
    )


def _record_to_new_row(rec: VerdictRecord) -> VerdictLedgerRow:
    return VerdictLedgerRow(
        candidate_id=rec.candidate_id,
        run_id=rec.run_id,
        scan_date=rec.scan_date,
        underlying=rec.underlying,
        strategy=rec.strategy.value,
        right=rec.right.value,
        strike=rec.strike,
        expiry=rec.expiry,
        dte=rec.dte,
        signals=rec.signals,
        claude_recommendation=rec.claude_recommendation,
        claude_priority=rec.claude_priority,
        claude_confidence=rec.claude_confidence,
        claude_rationale=rec.claude_rationale,
        baseline_recommendation=rec.baseline_recommendation,
        baseline_rank=rec.baseline_rank,
        baseline_score=rec.baseline_score,
        agreement=rec.agreement,
        outcome=rec.outcome.value,
        outcome_date=rec.outcome_date,
        realized_pnl=rec.realized_pnl,
        filled=rec.filled,
        entry_premium=rec.entry_premium,
        contracts=rec.contracts,
    )


def _refresh_presoutcome_fields(row: VerdictLedgerRow, rec: VerdictRecord) -> None:
    """Update the scan-time fields in place; never touch a recorded outcome."""
    row.run_id = rec.run_id
    row.scan_date = rec.scan_date
    row.dte = rec.dte
    row.signals = rec.signals
    row.claude_recommendation = rec.claude_recommendation
    row.claude_priority = rec.claude_priority
    row.claude_confidence = rec.claude_confidence
    row.claude_rationale = rec.claude_rationale
    row.baseline_recommendation = rec.baseline_recommendation
    row.baseline_rank = rec.baseline_rank
    row.baseline_score = rec.baseline_score
    row.agreement = rec.agreement


def update_outcome(
    candidate_id: str,
    outcome: VerdictOutcome,
    *,
    realized_pnl: float | None = None,
    outcome_date: date | None = None,
    filled: bool | None = None,
    entry_premium: float | None = None,
    contracts: int | None = None,
) -> bool:
    """Attach a terminal (or fill-state) outcome to a ledger row. Never raises.

    Returns True if a row was updated. Idempotent for terminal outcomes — a row that already
    holds a terminal outcome is left untouched so the reconciler can run repeatedly.
    """
    try:
        with session_scope() as sess:
            row = sess.execute(
                select(VerdictLedgerRow).where(VerdictLedgerRow.candidate_id == candidate_id)
            ).scalar_one_or_none()
            if row is None:
                return False
            if VerdictOutcome(row.outcome) in _TERMINAL:
                return False  # already settled — don't clobber
            row.outcome = outcome.value
            if outcome_date is not None:
                row.outcome_date = outcome_date
            elif outcome in _TERMINAL:
                row.outcome_date = datetime.now(UTC).date()
            if realized_pnl is not None:
                row.realized_pnl = realized_pnl
            if filled is not None:
                row.filled = filled
            if entry_premium is not None:
                row.entry_premium = entry_premium
            if contracts is not None:
                row.contracts = contracts
            return True
    except Exception:
        log.exception("ledger: failed to update outcome for %s", candidate_id)
        return False


def mark_filled(
    candidate_id: str,
    *,
    entry_premium: float | None = None,
    contracts: int | None = None,
) -> bool:
    """Flag a ledger row as executed (still_open) and stamp its entry economics. Never raises."""
    return update_outcome(
        candidate_id,
        VerdictOutcome.STILL_OPEN,
        filled=True,
        entry_premium=entry_premium,
        contracts=contracts,
    )


def load_records(
    *,
    closed_only: bool = False,
    filled_only: bool = False,
    since: date | None = None,
    until: date | None = None,
) -> list[VerdictRecord]:
    """Load ledger rows as VerdictRecords, newest scan first. Never raises (returns [])."""
    try:
        with session_scope() as sess:
            stmt = select(VerdictLedgerRow).order_by(VerdictLedgerRow.scan_date.desc())
            if since is not None:
                stmt = stmt.where(VerdictLedgerRow.scan_date >= since)
            if until is not None:
                stmt = stmt.where(VerdictLedgerRow.scan_date <= until)
            if filled_only:
                stmt = stmt.where(VerdictLedgerRow.filled.is_(True))
            rows = list(sess.execute(stmt).scalars().all())
        records = [_row_to_record(r) for r in rows]
    except Exception:
        log.exception("ledger: failed to load records")
        return []
    if closed_only:
        records = [r for r in records if r.outcome in _TERMINAL and r.realized_pnl is not None]
    return records


def open_filled_records() -> list[VerdictRecord]:
    """Filled rows with no terminal outcome yet — the reconciler's work queue."""
    return [
        r
        for r in load_records(filled_only=True)
        if r.outcome == VerdictOutcome.STILL_OPEN
    ]
