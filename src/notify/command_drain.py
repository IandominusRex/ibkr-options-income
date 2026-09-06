"""The command-drain loop's handlers and the ``drain_once`` entry point.

Runs inside ``approval_service`` (the process that holds the exec connection). Every
``interval`` seconds, the loop reads all ``pending`` commands and applies each one
through its registered handler. In M1 ``HANDLERS`` is empty — the only observable
behaviour is the unknown-kind path and the expiry sweep. This is deliberate: the
machinery is proven before anything can use it.

Design points that are not negotiable (see M1-write-foundation.md Task 1.5):

1. ``drain_once`` never raises. A handler that throws marks its own command ``failed``
   with the exception text and the loop continues to the next one.
2. An unknown kind is ``failed``, not skipped — a command sitting ``pending`` forever
   is the failure mode the operator cannot see.
3. A command with an outstanding ``confirm_token`` is **skipped**, not failed — it is
   waiting for a human, which is not an error. Skipping does not count toward the
   return value.
4. The loop starts even when ``ib is None``. Commands that do not need the broker
   (reject, halt, resume, set_autonomy, universe edits) must still apply when TWS is
   down. Handlers that do need it fail their own command with ``broker_unavailable``.
5. ``expire_stale_commands`` runs once per drain, using ``approval.ttl_minutes``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from ib_async import IB

from src.common.config import get_config
from src.storage.app_commands import (
    expire_stale_commands,
    mark_applied,
    mark_failed,
    pending_commands,
)
from src.storage.db import session_scope
from src.storage.system_settings import set_setting

log = logging.getLogger(__name__)

CommandHandler = Callable[..., Any]

# system_settings key: ISO UTC timestamp of the last completed drain cycle. Written
# AFTER the work, never before, so a hung handler cannot make the loop look healthy.
# M2's /options/controls reads this to tell an operator their click is queued and
# nothing is picking it up (spec §4.1, M1 Task 1.5 design point 6).
COMMAND_DRAIN_HEARTBEAT_KEY = "command_drain_heartbeat"

# Populated by M3–M7; empty in M1.
HANDLERS: dict[str, CommandHandler] = {}


def register(kind: str) -> Callable[[CommandHandler], CommandHandler]:
    """Decorator. Each later milestone registers its own kinds here."""

    def decorator(fn: CommandHandler) -> CommandHandler:
        HANDLERS[kind] = fn
        return fn

    return decorator


async def drain_once(ib: IB | None, bot: Any, chat_id: str) -> int:
    """Apply every pending command. Returns how many were processed. Never raises.

    A command awaiting confirmation (``confirm_token`` is set) is skipped and does not
    count toward the return value. An unknown kind is failed with ``unknown_kind``.
    A throwing handler marks its own command ``failed`` and the loop continues.
    """
    with session_scope() as s:
        # 1. Expire stale commands past their TTL.
        ttl = get_config().approval.ttl_minutes
        expired = expire_stale_commands(s, ttl)
        if expired:
            log.info("command drain: expired %d stale command(s)", expired)

        # 2. Read pending commands (after expiry, so expired ones are not processed).
        commands = pending_commands(s)
        s.commit()  # release the read lock before processing

    processed = 0
    for cmd in commands:
        # Skip commands awaiting a human confirmation.
        if cmd.confirm_token is not None:
            log.debug("command drain: skipping %d (awaiting confirmation)", cmd.id)
            continue

        try:
            handler = HANDLERS.get(cmd.kind)
            if handler is None:
                _fail(cmd.id, "unknown_kind")
                continue

            result = handler(ib=ib, bot=bot, chat_id=chat_id, payload=cmd.payload)
            _applied(cmd.id, {"ok": True, "result": result})
            processed += 1
        except Exception as exc:
            log.exception("command drain: handler for %s raised", cmd.kind)
            _fail(cmd.id, "handler_error", {"error": str(exc)})

    # Heartbeat written AFTER the work, never before — a hung handler cannot make the
    # loop look healthy. Written even when nothing was processed, so a stalled queue
    # is distinguishable from a dead loop (M2 /options/controls reads this).
    set_setting(
        COMMAND_DRAIN_HEARTBEAT_KEY,
        datetime.now(UTC).isoformat(),
    )
    return processed


def _applied(command_id: int, result: dict) -> None:
    with session_scope() as s:
        mark_applied(s, command_id, result)


def _fail(command_id: int, reason: str, detail: dict | None = None) -> None:
    with session_scope() as s:
        mark_failed(s, command_id, reason, detail)
