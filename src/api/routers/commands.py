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

from src.api.commands import clear_confirm_token, get_status, submit
from src.api.deps import OwnerUser
from src.api.models.commands import (
    CommandKind,
    CommandStatus,
    dedupe_key_for,
    validate_payload,
)
from src.common.config import get_config

router = APIRouter(prefix="/commands", tags=["commands"])

# Kinds that can reach an order in live mode and need a second confirmation (§4.6).
_LIVE_CONFIRM_KINDS: frozenset[CommandKind] = frozenset(
    {CommandKind.APPROVE, CommandKind.PROMOTE, CommandKind.ROLL_REQUEST}
)


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

    In paper mode no token was issued, so this is a no-op 204. In live mode a mismatched
    or missing token returns 409. A command not awaiting confirmation (already applied,
    or not an order-reaching kind) also returns 409.
    """
    resp = get_status(command_id)
    if resp is None:
        raise HTTPException(status_code=404, detail="Command not found")
    if not resp.needs_confirmation:
        return Response(status_code=204)
    if not body.confirm_token:
        raise HTTPException(status_code=409, detail="A confirm_token is required for this command")
    # The token is stored on the row; we verify it by reading through the read-only
    # engine and comparing. A mismatch is 409.
    from src.api.trading_db import trading_session
    from src.storage.models import AppCommandRow

    with trading_session() as s:
        row = s.get(AppCommandRow, command_id)
        if row is None or row.confirm_token is None:
            raise HTTPException(status_code=409, detail="Not awaiting confirmation")
        if not secrets.compare_digest(body.confirm_token, row.confirm_token):
            raise HTTPException(status_code=409, detail="Confirm token does not match")
    # Clearing the token is a write — it goes through the command engine, via the only
    # module allowed to hold the write handle. The router never imports the write session.
    clear_confirm_token(command_id)
    return Response(status_code=204)
