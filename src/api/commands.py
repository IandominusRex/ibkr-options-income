"""The only module allowed to import ``get_command_engine``.

Enqueues web intents into ``app_commands`` and reads their status back through the
read-only engine. The write handle is used for inserts and nothing else — reads go
through ``trading_session`` even for commands, preserving the asymmetry spec §4.2
calls out: the read path stays read-only, the write path touches one table.
"""

from __future__ import annotations

from sqlalchemy import update

from src.api.auth import User
from src.api.models.commands import CommandKind, CommandStatus
from src.api.trading_db import command_session, get_command_engine, trading_session
from src.storage.app_commands import enqueue_command
from src.storage.models import AppCommandRow

_ = get_command_engine  # referenced so static analysis sees the import; used by command_session


def submit(
    *,
    kind: CommandKind,
    payload: dict,
    user: User,
    dedupe_key: str | None,
    confirm_token: str | None = None,
) -> tuple[int, bool]:
    """Enqueue an intent. Returns ``(command_id, created)``.

    ``created`` is False when a duplicate ``dedupe_key`` returned the existing row
    instead of inserting a new one. The write goes through ``command_session`` (the
    only write handle); the caller never sees it.
    """
    with command_session() as s:
        row, created = enqueue_command(
            s,
            kind=kind.value,
            payload=payload,
            requested_by=user.id,
            dedupe_key=dedupe_key,
            confirm_token=confirm_token,
        )
        return row.id, created


def get_status(command_id: int) -> CommandStatus | None:
    """Read one command's status through the READ-ONLY engine, not the write one.

    ``confirm_token`` is exposed only while it is outstanding — after a successful
    confirm or an expiry sweep the field is null, so old commands never leak it.
    """
    from datetime import UTC, datetime

    with trading_session() as s:
        row = s.get(AppCommandRow, command_id)
        if row is None:
            return None
        return CommandStatus(
            id=row.id,
            kind=CommandKind(row.kind),
            status=row.status,  # type: ignore[arg-type]
            result=row.result,
            needs_confirmation=row.confirm_token is not None,
            confirm_token=row.confirm_token,
            created_at=row.created_at if row.created_at else datetime.now(UTC),
            applied_at=row.applied_at,
        )


def clear_confirm_token(command_id: int) -> None:
    """Clear a command's ``confirm_token`` after a successful confirmation.

    The token was written by ``submit`` in live mode; clearing it is a write, so it
    goes through the command engine here (the only module allowed to hold the write
    handle). The router does not import ``command_session``.
    """
    with command_session() as s:
        s.execute(
            update(AppCommandRow).where(AppCommandRow.id == command_id).values(confirm_token=None)
        )
