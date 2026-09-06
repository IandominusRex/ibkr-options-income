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

from pydantic import BaseModel, Field

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
    reason: str = ""


class ResumePayload(BaseModel):
    pass


class SetAutonomyPayload(BaseModel):
    level: AutonomyLevel


class UniversePayload(BaseModel):
    """§7.2: only ``would_own`` and ``watchlist`` may be edited from the web.
    ``sectors`` and ``leveraged_etfs`` are rejected at the type level — they can
    never become a command row.
    """

    symbol: str
    list_name: Literal["would_own", "watchlist"]


class RefreshPayload(BaseModel):
    pass


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

    ``None`` for the four repeatable kinds (halt, resume, set_autonomy, refresh) —
    repeating them is harmless, so they are never deduped.
    """
    if kind in (
        CommandKind.HALT,
        CommandKind.RESUME,
        CommandKind.SET_AUTONOMY,
        CommandKind.REFRESH,
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
    if kind in (CommandKind.UNIVERSE_ADD, CommandKind.UNIVERSE_REMOVE):
        assert isinstance(payload, UniversePayload)
        return f"{kind.value}:{payload.list_name}:{payload.symbol}"
    return None


class CommandStatus(Envelope):
    """The status of a command, returned by ``GET /commands/{id}`` and ``POST /commands``."""

    id: int
    kind: CommandKind
    status: Literal["pending", "applied", "failed", "expired"]
    result: dict | None = None
    needs_confirmation: bool = False  # true when a live-mode confirm_token is outstanding
    created_at: datetime
    applied_at: datetime | None = None
    as_of: datetime = Field(default_factory=lambda: datetime.now(UTC))
