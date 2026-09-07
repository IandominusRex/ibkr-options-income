"""Command schemas and payload validation for the P2 intent queue.

Every web click that can move money becomes a ``CommandKind`` + a typed payload. The
payload is validated **before** an ``AppCommandRow`` can exist, so a malformed intent
can never reach the drain loop. The rule that matters most is
``UniversePayload.list_name: Literal["would_own", "watchlist"]`` — spec §7.2's narrow
surface is enforced at the type level, so ``sectors`` and ``leveraged_etfs`` fail
parsing and can never become a command row.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.api.models.common import Envelope
from src.common.schemas import AutonomyLevel


class CommandKind(StrEnum):
    """Every intent the web layer can enqueue. Later milestones register handlers."""

    APPROVE = "approve"
    REJECT = "reject"
    PROMOTE = "promote"
    ROLL_REQUEST = "roll_request"
    HALT = "halt"
    RESUME = "resume"
    SET_AUTONOMY = "set_autonomy"
    UNIVERSE_ADD = "universe_add"
    UNIVERSE_REMOVE = "universe_remove"
    REFRESH = "refresh"


# --- Payloads ---------------------------------------------------------------


class ApprovePayload(BaseModel):
    approval_id: int


class RejectPayload(BaseModel):
    approval_id: int


class PromotePayload(BaseModel):
    candidate_id: str
    symbol: str
    strategy: Literal["covered_call", "cash_secured_put"]
    strike: float
    expiry: date


class RollRequestPayload(BaseModel):
    position_symbol: str


class HaltPayload(BaseModel):
    """``reason`` is rendered by ``/status`` and the console's halt banner — an unbounded
    string in a settings value is a rendering bug waiting to happen, so it is capped
    here at parse time, before a command row can exist (M6 Task 6.2).
    """

    model_config = ConfigDict(extra="forbid")
    reason: str = Field(default="", max_length=200)


class ResumePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SetAutonomyPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    level: AutonomyLevel


class UniversePayload(BaseModel):
    """§7.2: only ``would_own`` and ``watchlist`` may be edited from the web.
    ``sectors`` and ``leveraged_etfs`` are rejected at the type level — they can
    never become a command row.
    """

    symbol: str
    list_name: Literal["would_own", "watchlist"]


class RefreshPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")


PAYLOAD_FOR: dict[CommandKind, type[BaseModel]] = {
    CommandKind.APPROVE: ApprovePayload,
    CommandKind.REJECT: RejectPayload,
    CommandKind.PROMOTE: PromotePayload,
    CommandKind.ROLL_REQUEST: RollRequestPayload,
    CommandKind.HALT: HaltPayload,
    CommandKind.RESUME: ResumePayload,
    CommandKind.SET_AUTONOMY: SetAutonomyPayload,
    CommandKind.UNIVERSE_ADD: UniversePayload,
    CommandKind.UNIVERSE_REMOVE: UniversePayload,
    CommandKind.REFRESH: RefreshPayload,
}


def validate_payload(kind: CommandKind, raw: dict) -> BaseModel:
    """Parse ``raw`` against the model for ``kind``. Raises ``ValidationError``."""
    return PAYLOAD_FOR[kind].model_validate(raw)


def dedupe_key_for(kind: CommandKind, payload: BaseModel) -> str | None:
    """The ``f"{kind}:{target}"`` convention from Task 1.1.

    ``None`` for the six repeatable kinds (halt, resume, set_autonomy, refresh,
    universe_add, universe_remove) — repeating them is harmless, so they are never
    deduped. The universe kinds joined this set in the M7 final-review fix round: both
    drain handlers (``_universe_add``/``_universe_remove``) upsert a
    ``UniverseOverrideRow`` via ``set_override``, which is idempotent by construction
    (a later call for the same ``(symbol, list_name)`` overwrites the row in place) —
    the same idempotency shape as halt/resume/set_autonomy. A stable dedupe key here was
    actively wrong: it let a *permanently* stale key (never expiring, never tied to
    status) match an already-``applied`` row on a later, semantically different request
    — remove -> add -> remove would dedupe the second remove to the first ``applied``
    remove command, return ``created: false, status: "applied"``, and never enqueue the
    row that would actually reverse the add. Repeating the command now just creates a
    fresh row and re-applies, which is correct because the handler is upsert-only.
    """
    if kind in (
        CommandKind.HALT,
        CommandKind.RESUME,
        CommandKind.SET_AUTONOMY,
        CommandKind.REFRESH,
        CommandKind.UNIVERSE_ADD,
        CommandKind.UNIVERSE_REMOVE,
    ):
        return None
    if kind in (CommandKind.APPROVE, CommandKind.REJECT):
        assert isinstance(payload, ApprovePayload | RejectPayload)
        return f"{kind.value}:{payload.approval_id}"
    if kind == CommandKind.PROMOTE:
        assert isinstance(payload, PromotePayload)
        return f"{kind.value}:{payload.candidate_id}"
    if kind == CommandKind.ROLL_REQUEST:
        assert isinstance(payload, RollRequestPayload)
        return f"{kind.value}:{payload.position_symbol}"
    return None


class CommandStatus(Envelope):
    """The status of a command, returned by ``GET /commands/{id}`` and ``POST /commands``.

    ``confirm_token`` is present only while a live-mode order-reaching intent is
    awaiting its second confirmation (§4.6). It is returned so the owner — the
    only role that can reach these routes — can supply it back via
    ``POST /commands/{id}/confirm``; it is cleared the moment the command is
    confirmed or expired, and is absent in paper mode entirely.
    """

    id: int
    kind: CommandKind
    status: Literal["pending", "applied", "failed", "expired"]
    result: dict | None = None
    needs_confirmation: bool = False  # true when a live-mode confirm_token is outstanding
    confirm_token: str | None = None
    created_at: datetime
    applied_at: datetime | None = None
    as_of: datetime = Field(default_factory=lambda: datetime.now(UTC))
