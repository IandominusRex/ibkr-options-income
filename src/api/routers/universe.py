"""GET /universe — the effective scan universe (read-only in P1).

Reads ``config/universe.yaml`` through ``get_config().universe`` and returns every list
unmodified and in file order. ``editable`` is ``false`` because the
``universe_overrides`` write path belongs to P2; the client must not render an edit
affordance that has no backend behind it (design §4.5 — never claim more than the
backend did).
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter

from src.api.deps import CurrentUser
from src.api.models.common import Envelope
from src.common.config import get_config

router = APIRouter(prefix="/universe", tags=["universe"])


class UniverseResponse(Envelope):
    """The parsed universe.yaml: the four lists, the sector map, strike-band overrides.

    ``sectors`` maps every universe symbol to its sector tag. ``strike_bands`` maps the
    symbols that carry a per-symbol override to the band fraction. Both are read-only
    in P1; ``editable`` is ``false`` so the client knows not to show an edit control.
    """

    indexes: list[str]
    watchlist: list[str]
    would_own: list[str]
    actively_wheeling: list[str]
    sectors: dict[str, str]
    strike_bands: dict[str, float]
    editable: bool = False


def _list(d: dict[str, object], key: str) -> list[str]:
    """Return the list at *key* as a list[str], unmodified and in file order."""
    raw = d.get(key, [])
    return [str(s) for s in raw] if isinstance(raw, list) else []


@router.get("", response_model=UniverseResponse)
def universe(user: CurrentUser) -> UniverseResponse:
    cfg = get_config()
    u = cfg.universe
    return UniverseResponse(
        as_of=datetime.now(UTC),
        indexes=_list(u, "indexes"),
        watchlist=_list(u, "watchlist"),
        would_own=_list(u, "would_own"),
        actively_wheeling=_list(u, "actively_wheeling"),
        sectors={str(k): str(v) for k, v in (u.get("sectors") or {}).items()},
        strike_bands={str(k): float(v) for k, v in (u.get("strike_bands") or {}).items()},
        editable=False,
    )
