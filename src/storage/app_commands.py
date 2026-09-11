"""Helpers for the ``app_commands`` table — the web layer's intent queue.

The API inserts rows here (the only table it may write); the approval-service drain
loop applies them. Mirrors the shape of ``src/storage/buy_candidates.py`` so the two
read as neighbours. All helpers take an existing ``Session`` so the caller controls
the transaction — the API's write path and the drain loop both need that.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from src.storage.models import AppCommandRow

log = logging.getLogger(__name__)


def enqueue_command(
    session: Session,
    *,
    kind: str,
    payload: dict,
    requested_by: str,
    dedupe_key: str | None = None,
    confirm_token: str | None = None,
) -> tuple[AppCommandRow, bool]:
    """Insert a command. Returns ``(row, created)``.

    On a ``dedupe_key`` collision against a still-``pending`` row, returns that row with
    ``created=False`` — never a second row, never an exception. A ``None`` dedupe_key is
    never deduped (refresh, halt, resume, set_autonomy, universe_add, universe_remove may
    repeat harmlessly).

    The lookup is scoped to ``status == "pending"`` (not "any row with this key ever"):
    ``promote`` and ``roll_request`` key on a stable target (``candidate_id`` /
    ``position_symbol``) that outlives any single approval cycle, so once a command has
    been applied/failed/expired the key is no longer live — a later, semantically new
    request for the same target must get a fresh row, not silently no-op against the old
    one's stale result. This still preserves "two clicks produce one command" for every
    keyed kind, since only one row can be pending for a given key at a time.
    """
    if dedupe_key is not None:
        existing = session.execute(
            select(AppCommandRow).where(
                AppCommandRow.dedupe_key == dedupe_key,
                AppCommandRow.status == "pending",
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing, False
    row = AppCommandRow(
        kind=kind,
        payload=payload,
        dedupe_key=dedupe_key,
        status="pending",
        requested_by=requested_by,
        confirm_token=confirm_token,
    )
    session.add(row)
    session.flush()  # assign id without committing — caller owns the transaction
    return row, True


def pending_commands(session: Session, *, limit: int = 50) -> list[AppCommandRow]:
    """All commands still awaiting application, oldest first."""
    return list(
        session.execute(
            select(AppCommandRow)
            .where(AppCommandRow.status == "pending")
            .order_by(AppCommandRow.id)
            .limit(limit)
        )
        .scalars()
        .all()
    )


def mark_applied(session: Session, command_id: int, result: dict) -> None:
    """Record that the drain applied the command successfully."""
    session.execute(
        update(AppCommandRow)
        .where(AppCommandRow.id == command_id)
        .values(status="applied", result=result, applied_at=datetime.now(UTC))
    )


def mark_failed(
    session: Session,
    command_id: int,
    reason: str,
    detail: dict | None = None,
) -> None:
    """Record that the drain could not apply the command, with the reason."""
    session.execute(
        update(AppCommandRow)
        .where(AppCommandRow.id == command_id)
        .values(
            status="failed",
            result={"reason": reason, "detail": detail or {}},
            applied_at=datetime.now(UTC),
        )
    )


def expire_stale_commands(session: Session, older_than_minutes: int) -> int:
    """Mark pending commands older than the cutoff ``expired``. Returns the count.

    A command that has sat pending past its TTL is no longer actionable — the state
    it was meant to mutate may have moved on. Expiring it makes that visible rather
    than leaving it invisible in the queue forever.
    """
    cutoff = datetime.now(UTC).timestamp() - older_than_minutes * 60
    cutoff_dt = datetime.fromtimestamp(cutoff, tz=UTC)
    result = session.execute(
        update(AppCommandRow)
        .where(AppCommandRow.status == "pending")
        .where(AppCommandRow.created_at < cutoff_dt)
        .values(
            status="expired",
            result={"reason": "ttl_expired"},
            applied_at=datetime.now(UTC),
        )
    )
    # rowcount is a CursorResult attribute; mypy only sees the ORM-wrapped result.
    return getattr(result, "rowcount", 0) or 0
