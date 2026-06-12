"""Daily position-snapshot persistence for assignment auto-detection (SYSTEM_REVIEW Phase 4).

The EOD run saves one snapshot per ET trading day; assignment detection diffs the most recent
*prior* snapshot against current positions. Kept deliberately small — one upserted JSON row per
day, pruned alongside the other audit tables.
"""

from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import select

from src.common.schemas import PositionSnapshot
from src.storage.db import session_scope
from src.storage.models import PositionSnapshotRow

log = logging.getLogger(__name__)


def save_position_snapshot(snapshot_date: date, positions: list[PositionSnapshot]) -> None:
    """Upsert the snapshot for *snapshot_date* (idempotent if the EOD run repeats)."""
    payload = [p.model_dump(mode="json") for p in positions]
    try:
        with session_scope() as s:
            row = (
                s.query(PositionSnapshotRow).filter_by(snapshot_date=snapshot_date).first()
            )
            if row is None:
                s.add(PositionSnapshotRow(snapshot_date=snapshot_date, payload=payload))
            else:
                row.payload = payload
    except Exception:
        log.exception("save_position_snapshot failed for %s", snapshot_date)


def load_latest_position_snapshot(before: date | None = None) -> list[PositionSnapshot]:
    """Return the most recent stored snapshot (strictly before *before* if given).

    Empty list when none exists — the first-ever EOD run has no baseline to diff against.
    """
    try:
        with session_scope() as s:
            stmt = select(PositionSnapshotRow).order_by(PositionSnapshotRow.snapshot_date.desc())
            if before is not None:
                stmt = stmt.where(PositionSnapshotRow.snapshot_date < before)
            row = s.execute(stmt.limit(1)).scalars().first()
            payload = list(row.payload) if row is not None else []
    except Exception:
        log.exception("load_latest_position_snapshot failed")
        return []
    return [PositionSnapshot.model_validate(p) for p in payload]
