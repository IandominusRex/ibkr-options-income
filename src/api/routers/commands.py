"""POST /commands, GET /commands/{id}, POST /commands/{id}/confirm.

The first write routes in the web layer. Every later write route copies this pattern:
owner-only auth, payload validation against the typed schema, dedupe via dedupe_key,
and the read path through the read-only engine.
"""

from __future__ import annotations

import secrets

from fastapi import APIRouter, HTTPException, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.commands import clear_confirm_token, get_status, submit
from src.api.deps import OwnerUser
from src.api.models.commands import (
    CommandKind,
    CommandStatus,
    PromotePayload,
    dedupe_key_for,
    validate_payload,
)
from src.api.trading_db import trading_session
from src.common.config import get_config
from src.storage.models import RiskVerdictRow

router = APIRouter(prefix="/commands", tags=["commands"])

# Kinds that can reach an order in live mode and need a second confirmation (§4.6).
#
# The control kinds (halt, resume, set_autonomy, refresh) are deliberately NOT in this
# set — that is not an oversight, it is the M6 asymmetry: the live token exists for
# intents that can reach an order, and a halt must never be slowed by a second step
# (halting when you did not mean to costs missed premium; failing to halt when you
# meant to can cost a great deal more). Pinned by tests in tests/test_command_schemas.py
# and tests/test_write_path_invariants.py::test_control_kinds_never_require_live_confirmation.
_LIVE_CONFIRM_KINDS: frozenset[CommandKind] = frozenset(
    {CommandKind.APPROVE, CommandKind.PROMOTE, CommandKind.ROLL_REQUEST}
)

# Spec §5.2: exactly these three stages are a ranking decision the operator may
# override. RISK_GATE (the Rules Engine said no) and GENERATOR (the strategy
# filters said no) are not — and PASSED already has an approval. A future edit
# that widens this set is asserted against in tests/test_write_path_invariants.py.
PROMOTABLE_STAGES: frozenset[str] = frozenset({"score_floor", "dedupe", "top_n"})


def assert_promotable(session: Session, candidate_id: str) -> RiskVerdictRow:
    """Look up the assessed row and refuse a non-promotable stage with 409.

    ``RiskVerdictRow.candidate_id`` is not unique — the same candidate can be
    assessed differently across scan runs (14 days of history are kept), so
    "the assessed row" means the most recent one: ordered by ``created_at``
    descending, ``id`` descending as a tiebreaker.

    Raises HTTPException(404) when no assessed row exists for this candidate_id.
    Raises HTTPException(409, {"reason": "stage_not_promotable", "stage": ...})
    when the most recent row's stage is not in PROMOTABLE_STAGES.
    """
    row = session.execute(
        select(RiskVerdictRow)
        .where(RiskVerdictRow.candidate_id == candidate_id)
        .order_by(RiskVerdictRow.created_at.desc(), RiskVerdictRow.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found")
    if row.stage not in PROMOTABLE_STAGES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"reason": "stage_not_promotable", "stage": row.stage},
        )
    return row


class CommandRequest(BaseModel):
    kind: CommandKind
    payload: dict


class CommandResponse(CommandStatus):
    created: bool = False


class ConfirmRequest(BaseModel):
    confirm_token: str = ""


@router.post("", response_model=CommandResponse)
def post_commands(req: CommandRequest, user: OwnerUser) -> JSONResponse:
    """Enqueue an intent. 201 if new, 200 if a dedupe returned the existing row."""
    kind = req.kind
    try:
        payload = validate_payload(kind, req.payload)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.errors(),
        ) from exc

    if kind == CommandKind.PROMOTE:
        # The refusal must be total, at the API boundary, before a command row
        # exists — a non-promotable stage never reaches enqueue_command (§5.2).
        assert isinstance(payload, PromotePayload)
        with trading_session() as s:
            assert_promotable(s, payload.candidate_id)

    dedupe_key = dedupe_key_for(kind, payload)

    confirm_token: str | None = None
    if get_config().is_live and kind in _LIVE_CONFIRM_KINDS:
        confirm_token = secrets.token_urlsafe(32)

    cid, created = submit(
        kind=kind,
        payload=req.payload,
        user=user,
        dedupe_key=dedupe_key,
        confirm_token=confirm_token,
    )
    resp = get_status(cid)
    assert resp is not None
    body = CommandResponse(**resp.model_dump(), created=created)
    code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return JSONResponse(
        content=body.model_dump(mode="json"),
        status_code=code,
    )


@router.get("/{command_id}", response_model=CommandStatus)
def get_command(command_id: int, _user: OwnerUser) -> CommandStatus:
    """Read one command's status through the read-only engine."""
    resp = get_status(command_id)
    if resp is None:
        raise HTTPException(status_code=404, detail="Command not found")
    return resp


@router.post("/{command_id}/confirm", status_code=status.HTTP_204_NO_CONTENT)
def confirm_command(command_id: int, body: ConfirmRequest, _user: OwnerUser) -> Response:
    """Supply the confirm token for a live-mode order-reaching intent.

    In paper mode no token was issued, so this is a no-op 204. A command not
    awaiting confirmation (already applied, expired, or not an order-reaching
    kind) returns 409 — the request does not make sense for that command. A
    wrong or missing token is **403**: the caller has not proven authority to
    release this order, and the token is NOT cleared, so the command stays
    pending (the fail-closed property, M3 Task 3.5).
    """
    resp = get_status(command_id)
    if resp is None:
        raise HTTPException(status_code=404, detail="Command not found")
    if not resp.needs_confirmation:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Command is not awaiting confirmation",
        )
    if not body.confirm_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="A confirm_token is required to release this command",
        )
    # The token is stored on the row; we verify it by reading through the read-only
    # engine and comparing. A mismatch is 403 and does not clear the field.
    from src.storage.models import AppCommandRow

    with trading_session() as s:
        row = s.get(AppCommandRow, command_id)
        if row is None or row.confirm_token is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Not awaiting confirmation",
            )
        if not secrets.compare_digest(body.confirm_token, row.confirm_token):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Confirm token does not match",
            )
    # Clearing the token is a write — it goes through the command engine, via the only
    # module allowed to hold the write handle. The router never imports the write session.
    clear_confirm_token(command_id)
    return Response(status_code=204)
