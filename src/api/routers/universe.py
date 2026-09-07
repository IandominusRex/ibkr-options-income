"""GET /universe — the effective scan universe, with per-list override provenance.

`POST /universe/{list_name}/{symbol}` and `DELETE /universe/{list_name}/{symbol}` — the
write path (M7 Task 7.4). Reads `config/universe.yaml` composed with any
`universe_overrides` rows through `effective_universe()` (M7 Task 7.3). `would_own` and
`watchlist` are the only overridable lists — `list_name` is a `Literal["would_own",
"watchlist"]` path parameter, so any other value is rejected with `422` before this
module's code runs at all, and before an `app_commands` row can exist.

Both write routes are thin wrappers over `POST /commands`: they validate (unknown list ->
422, unknown symbol -> 404, actively_wheeling removal from would_own -> 409), then enqueue a
`universe_add`/`universe_remove` intent and return the same `CommandStatus` shape
`POST /commands` returns. The actual mutation happens later, in the drain
(`src/notify/command_drain.py`'s `_universe_add`/`_universe_remove`) — the caller polls the
returned command id, same as every other write route.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Path, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.api.auth import User
from src.api.commands import get_status, submit
from src.api.deps import CurrentUser, OwnerUser, ResearchDb
from src.api.models.commands import CommandKind, UniversePayload, dedupe_key_for
from src.api.models.common import Envelope
from src.api.routers.commands import CommandResponse
from src.common.config import get_config
from src.common.universe import effective_universe
from src.research.store.models import SymbolRow
from src.storage.db import session_scope
from src.storage.models import UniverseOverrideRow
from src.storage.universe_overrides import all_overrides

router = APIRouter(prefix="/universe", tags=["universe"])

log = logging.getLogger(__name__)

# The only two universe.yaml lists an operator may add/remove symbols from — matches
# src.common.universe.OVERRIDABLE_LISTS. Every other key is read-only, defence in depth.
_OVERRIDABLE = frozenset({"would_own", "watchlist"})

# The four lists a GET /universe response reports, in this exact order.
_ALL_LISTS = ("indexes", "watchlist", "would_own", "actively_wheeling")


class UniverseEntry(BaseModel):
    symbol: str
    overridden: bool = False
    removed: bool = False
    created_by: str | None = None
    created_at: datetime | None = None


class UniverseListOut(BaseModel):
    name: str
    overridable: bool
    entries: list[UniverseEntry]


class UniverseResponse(Envelope):
    """The parsed universe.yaml: four lists (each with override provenance for the
    overridable two), the sector map, strike-band overrides. ``editable`` is ``true`` —
    Task 7.4 is the write path this shape describes.
    """

    lists: list[UniverseListOut]
    sectors: dict[str, str]
    strike_bands: dict[str, float]
    editable: bool = True


def _plain_entries(symbols: list[str]) -> list[UniverseEntry]:
    """Entries for a non-overridable list — never carry override metadata, and the
    overrides table is not even queried for these (defence in depth, matching the
    composer's own discipline)."""
    return [UniverseEntry(symbol=s) for s in symbols]


def _overridable_entries(
    list_name: str, overrides: list[UniverseOverrideRow], composed: list[str]
) -> list[UniverseEntry]:
    """Union of the YAML base membership (file order) and any override row for
    *list_name* — NOT just the already-filtered composed list, because a remove-overridden
    YAML-base symbol must still be visible (greyed out) with its provenance, so the UI can
    offer a revert.
    """
    base: list[str] = list(get_config().universe.get(list_name) or [])
    by_symbol = {row.symbol: row for row in overrides}
    composed_set = set(composed)

    entries: list[UniverseEntry] = []
    for symbol in base:
        row = by_symbol.get(symbol)
        if row is not None and row.action == "remove":
            still_present = symbol in composed_set
            entries.append(
                UniverseEntry(
                    symbol=symbol,
                    overridden=True,
                    removed=not still_present,
                    created_by=row.created_by,
                    created_at=row.created_at,
                )
            )
        else:
            entries.append(
                UniverseEntry(
                    symbol=symbol,
                    overridden=row is not None,
                    removed=False,
                    created_by=row.created_by if row else None,
                    created_at=row.created_at if row else None,
                )
            )

    base_set = set(base)
    added = sorted(
        (row for row in overrides if row.action == "add" and row.symbol not in base_set),
        key=lambda row: row.created_at,
    )
    for row in added:
        entries.append(
            UniverseEntry(
                symbol=row.symbol,
                overridden=True,
                removed=False,
                created_by=row.created_by,
                created_at=row.created_at,
            )
        )
    return entries


def _read_overrides_for_entries() -> list[UniverseOverrideRow]:
    """Every override row, or [] on an unreadable table.

    Mirrors ``src.common.universe``'s own fail-safe: a locked/missing overrides table
    must not break ``GET /universe`` — it degrades to showing every ``would_own``/
    ``watchlist`` entry as un-overridden, the same safe direction ``effective_universe()``
    falls back to for the composed lists themselves.
    """
    try:
        with session_scope() as session:
            return all_overrides(session)
    except Exception:
        log.warning(
            "GET /universe: could not read universe_overrides — entries will show no "
            "override provenance",
            exc_info=True,
        )
        return []


def _build_lists() -> list[UniverseListOut]:
    u = effective_universe()

    overrides = _read_overrides_for_entries()
    overrides_by_list: dict[str, list[UniverseOverrideRow]] = {
        name: [row for row in overrides if row.list_name == name] for name in _OVERRIDABLE
    }

    out: list[UniverseListOut] = []
    for name in _ALL_LISTS:
        symbols = [str(s) for s in (u.get(name) or [])]
        if name in _OVERRIDABLE:
            entries = _overridable_entries(name, overrides_by_list[name], symbols)
        else:
            entries = _plain_entries(symbols)
        out.append(UniverseListOut(name=name, overridable=name in _OVERRIDABLE, entries=entries))
    return out


@router.get("", response_model=UniverseResponse)
def universe(user: CurrentUser) -> UniverseResponse:
    u = effective_universe()
    return UniverseResponse(
        as_of=datetime.now(UTC),
        lists=_build_lists(),
        sectors={str(k): str(v) for k, v in (u.get("sectors") or {}).items()},
        strike_bands={str(k): float(v) for k, v in (u.get("strike_bands") or {}).items()},
        editable=True,
    )


def _apply_universe_command(
    *,
    kind: CommandKind,
    list_name: Literal["would_own", "watchlist"],
    symbol: str,
    user: User,
    research: Session,
) -> JSONResponse:
    """Shared validation + enqueue for POST/DELETE. `list_name` is already narrowed to
    `Literal["would_own", "watchlist"]` by the caller's path-parameter type — FastAPI
    returns 422 for anything else before the route body (and this function) ever runs.
    """
    upper = symbol.upper()
    if research.get(SymbolRow, upper) is None:
        raise HTTPException(status_code=404, detail=f"Unknown symbol {upper}")

    if kind == CommandKind.UNIVERSE_REMOVE and list_name == "would_own":
        wheeling = {s.upper() for s in (get_config().universe.get("actively_wheeling") or [])}
        if upper in wheeling:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"reason": "actively_wheeling", "symbol": upper},
            )

    payload = UniversePayload(symbol=upper, list_name=list_name)
    dedupe_key = dedupe_key_for(kind, payload)

    cid, created = submit(
        kind=kind,
        payload=payload.model_dump(),
        user=user,
        dedupe_key=dedupe_key,
        confirm_token=None,
    )
    resp = get_status(cid)
    assert resp is not None
    body = CommandResponse(**resp.model_dump(), created=created)
    code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return JSONResponse(content=body.model_dump(mode="json"), status_code=code)


@router.post("/{list_name}/{symbol}")
def add_to_universe(
    user: OwnerUser,
    research: ResearchDb,
    list_name: Literal["would_own", "watchlist"],
    symbol: str = Path(..., min_length=1, max_length=16),
) -> JSONResponse:
    """Enqueue a `universe_add` intent. `201` if new, `200` if a dedupe returned the
    existing command. `404` for an unknown symbol; `422` for a non-overridable list."""
    return _apply_universe_command(
        kind=CommandKind.UNIVERSE_ADD,
        list_name=list_name,
        symbol=symbol,
        user=user,
        research=research,
    )


@router.delete("/{list_name}/{symbol}")
def remove_from_universe(
    user: OwnerUser,
    research: ResearchDb,
    list_name: Literal["would_own", "watchlist"],
    symbol: str = Path(..., min_length=1, max_length=16),
) -> JSONResponse:
    """Enqueue a `universe_remove` intent. `409` if removing an `actively_wheeling` symbol
    from `would_own` — you cannot stop being willing to own something you are actively
    wheeling. `404` for an unknown symbol; `422` for a non-overridable list."""
    return _apply_universe_command(
        kind=CommandKind.UNIVERSE_REMOVE,
        list_name=list_name,
        symbol=symbol,
        user=user,
        research=research,
    )
