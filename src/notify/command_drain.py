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


class CommandFailed(Exception):
    """Raised by a handler to fail its own command with a machine-readable reason.

    The drain catches this and marks the command ``failed`` with the reason as
    ``result.reason`` (plus any ``detail``), so a receipt can render the cause
    instead of a raw exception string. Any other exception is a handler bug and
    is recorded as ``handler_error`` with the exception text.
    """

    def __init__(self, reason: str, detail: dict | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


# system_settings key: ISO UTC timestamp of the last completed drain cycle. Written
# AFTER the work, never before, so a hung handler cannot make the loop look healthy.
# M2's /options/controls reads this to tell an operator their click is queued and
# nothing is picking it up (spec §4.1, M1 Task 1.5 design point 6).
COMMAND_DRAIN_HEARTBEAT_KEY = "command_drain_heartbeat"

# Populated by M3 onwards; empty in M1.
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

            result = handler(ib=ib, bot=bot, chat_id=chat_id, command=cmd, payload=cmd.payload)
            # Handlers return the result dict stored on the command. The M1
            # machinery wrapped everything as {"ok": True, "result": ...}; a
            # handler's own dict is stored verbatim so a receipt can read
            # fields like "decision" straight off `result` (M3 Task 3.1).
            _applied(cmd.id, result)
            processed += 1
        except CommandFailed as exc:
            log.info("command drain: %s command %d failed: %s", cmd.kind, cmd.id, exc.reason)
            _fail(cmd.id, exc.reason, exc.detail)
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


# ---------------------------------------------------------------------------
# M3 Task 3.1 — approve / reject.
#
# The handler calls ``_process_button`` and does not reimplement one line of it.
# If a future refactor makes the web path diverge from the Telegram path, every
# safety property tested against Telegram silently stops covering the web —
# ``test_the_handler_calls_process_button_rather_than_reimplementing_it`` exists
# to make that refactoring loudly fail instead.
#
# The import is deferred to call time because ``approval_service`` imports this
# module at its own import time (for ``drain_once``); a module-level import
# would be circular.
# ---------------------------------------------------------------------------


def _process_button(approval_id: int, action: str) -> tuple[bool, str, str]:
    """Indirection to ``src.notify.approval_service._process_button``.

    Deferred so ``approval_service`` (which imports this module at import time
    for ``drain_once``) is not a circular import. Tests monkeypatch THIS name to
    assert the handler delegates rather than reimplementing.
    """
    from src.notify.approval_service import _process_button as real

    return real(approval_id, action)


def _apply_approval_decision(*, command: Any, action: str, **_: Any) -> dict:
    """Apply an approve or reject intent by calling ``_process_button`` unchanged.

    Returns the result dict stored on the command. Raises ``CommandFailed`` to
    fail the command. ``ib`` is deliberately unused: a reject with TWS down
    must still apply, and an approve only creates a ``QUEUED`` ``OrderRow``
    that ``process_queued_orders`` picks up when the exec connection returns
    (existing behaviour). The handler sends no Telegram message — notification
    stays with the existing order poll loop, which already reports fills; two
    notification paths for one order is how duplicates start.
    """
    from src.api.models.commands import ApprovePayload, RejectPayload

    payload_cls = ApprovePayload if action == "approve" else RejectPayload
    payload = payload_cls(**command.payload)

    found, decision_text, _short = _process_button(payload.approval_id, action)
    if not found:
        raise CommandFailed("approval_not_found")
    # An already-decided approval is NOT a failure: ``_process_button`` returned
    # "Already <status>" and mutated nothing, but the intent's goal — this
    # approval is decided — is satisfied. Marking it failed would make a normal
    # Telegram-vs-console race look like a malfunction.
    return {"decision": decision_text, "approval_id": payload.approval_id}


@register("approve")
def _approve(*, command: Any, **_: Any) -> dict:
    """Apply an approve intent by calling ``_process_button`` unchanged."""
    return _apply_approval_decision(command=command, action="approve")


@register("reject")
def _reject(*, command: Any, **_: Any) -> dict:
    """Apply a reject intent by calling ``_process_button`` unchanged."""
    return _apply_approval_decision(command=command, action="reject")
