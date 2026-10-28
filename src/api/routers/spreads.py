"""GET /spreads/positions and GET /spreads/picks — read-only, through src/api/spreads_db.py
(never src.spreads)."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query
from pydantic import ValidationError

from src.api.deps import OwnerUser
from src.api.models.common import as_utc
from src.api.models.spreads import (
    SpreadMenuItemOut,
    SpreadOrderOut,
    SpreadOrdersResponse,
    SpreadPickOut,
    SpreadPicksResponse,
    SpreadPositionsResponse,
)
from src.api.spread_inputs import spread_position_out
from src.api.spreads_db import (
    read_activity_days,
    read_spread_rows,
    spreads_read_session,
    try_read_pick_rows,
    try_read_spread_order_rows,
    try_read_spread_rows_opened,
)
from src.common.config import get_config
from src.common.schemas import SpreadMenuItem

router = APIRouter(prefix="/spreads", tags=["spreads"])

NEW_YORK = ZoneInfo("America/New_York")


@router.get("/positions", response_model=SpreadPositionsResponse)
def spread_positions(
    user: OwnerUser,  # noqa: ARG001
    status: Literal["open", "closed", "all"] = "open",
    mode: Literal["paper", "shadow", "baseline"] = "paper",
    limit: int = Query(50, ge=1, le=500),
) -> SpreadPositionsResponse:
    now = datetime.now(UTC)
    underlying = get_config().spreads.underlying
    with spreads_read_session() as s:
        if s is None:
            return SpreadPositionsResponse(
                as_of=now, available=False, underlying=underlying, mode=mode
            )
        rows = read_spread_rows(s, mode=mode, status=status, limit=limit)
    positions = [spread_position_out(r, now) for r in rows]
    return SpreadPositionsResponse(
        as_of=now, available=True, underlying=underlying, mode=mode, positions=positions
    )


def _now() -> datetime:
    """The picks route's clock. Patched in tests."""
    return datetime.now(UTC)


def _new_york_day_bounds(day: date) -> tuple[datetime, datetime]:
    """[start, end) of a New York calendar day as naive UTC, the form spreads.db stores."""
    start = datetime.combine(day, time.min, NEW_YORK).astimezone(UTC)
    end = datetime.combine(day + timedelta(days=1), time.min, NEW_YORK).astimezone(UTC)
    return start.replace(tzinfo=None), end.replace(tzinfo=None)


def _menu_item_out(item: SpreadMenuItem) -> SpreadMenuItemOut:
    c = item.candidate
    return SpreadMenuItemOut(
        letter=item.letter,
        position=item.position,
        side=c.side,
        short_strike=c.short_strike,
        long_strike=c.long_strike,
        width=c.width,
        contracts=item.contracts,
        credit_mid=c.credit_mid,
        credit_after_costs=item.credit_after_costs,
        max_loss_per_contract_usd=item.max_loss_per_contract_usd,
        short_delta=c.short_delta,
        spot=c.spot,
        dist_spot_pts=item.dist_spot_pts,
        dist_em_multiple=item.dist_em_multiple,
        be_nominal_exits=item.be_nominal_exits,
    )


def _pick_out(row: dict[str, Any], spread_id: str | None) -> SpreadPickOut:
    """One spread_picks row. A menu that no longer parses (an older or damaged row) is said to
    be unreadable rather than guessed at, and never takes the other picks down with it."""
    menu: list[SpreadMenuItemOut] = []
    readable = row["menu"] is not None
    if readable:
        try:
            menu = [_menu_item_out(SpreadMenuItem.model_validate(m)) for m in row["menu"]]
        except ValidationError:
            readable, menu = False, []
    return SpreadPickOut(
        pick_id=row["id"],
        created_at=as_utc(row["created_at"]),
        book_mode=row["book_mode"],
        choice=row["choice"],
        reason=row["reason"] or "",
        fallback_reason=row["fallback_reason"],
        executed_letter=row["executed_letter"],
        send_rejected=row["send_rejected"],
        send_reasons=[str(r) for r in row["send_reasons"]],
        filled=row["filled"],
        model=row["model"],
        regime=row["regime"],
        side=row["side"] or None,
        plan_bias=row["plan_bias"],
        event_flag=row["event_flag"],
        menu_readable=readable,
        menu=menu,
        spread_id=spread_id,
    )


@router.get("/picks", response_model=SpreadPicksResponse)
def spread_picks(
    user: OwnerUser,  # noqa: ARG001
    day: date | None = None,
) -> SpreadPicksResponse:
    """One New York day of the spreads picker: each menu Claude was shown, its choice, what was
    sent, and every spread any book opened that day. `day` defaults to today in New York."""
    now = _now()
    cfg = get_config().spreads
    the_day = day or now.astimezone(NEW_YORK).date()
    unavailable = SpreadPicksResponse(
        as_of=now,
        available=False,
        underlying=cfg.underlying,
        mode=cfg.mode,
        ai_enabled=cfg.ai.enabled,
        day=the_day,
    )
    with spreads_read_session() as s:
        if s is None:
            return unavailable
        start, end = _new_york_day_bounds(the_day)
        opened = try_read_spread_rows_opened(s, start=start, end=end)
        if opened is None:
            return unavailable
        pick_rows = try_read_pick_rows(s, day=the_day) or []
        days = read_activity_days(s)
    by_pick = {r["pick_id"]: r["spread_id"] for r in opened if r.get("pick_id") is not None}
    return unavailable.model_copy(
        update={
            "available": True,
            "previous_day": max((d for d in days if d < the_day), default=None),
            "next_day": min((d for d in days if d > the_day), default=None),
            "picks": [_pick_out(p, by_pick.get(p["id"])) for p in pick_rows],
            "positions": [
                spread_position_out({k: v for k, v in r.items() if k != "pick_id"}, now)
                for r in opened
            ],
        }
    )


@router.get("/orders", response_model=SpreadOrdersResponse)
def spread_orders(
    user: OwnerUser,  # noqa: ARG001
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(200, ge=1, le=500),
) -> SpreadOrdersResponse:
    """The book's filled orders, newest first (web overhaul Part 3). An older file without the
    table answers ``available: true`` with no orders, as `/spreads/picks` does for the picker.
    A missing file, or a table that exists but cannot be read, is ``available: false`` and never
    an empty list: "unavailable" is not "none"."""
    now = _now()
    underlying = get_config().spreads.underlying
    with spreads_read_session() as s:
        if s is None:
            return SpreadOrdersResponse(as_of=now, available=False, underlying=underlying)
        rows = try_read_spread_order_rows(
            s, start=(now - timedelta(days=days)).replace(tzinfo=None), limit=limit
        )
    if rows is None:
        return SpreadOrdersResponse(as_of=now, available=False, underlying=underlying)
    orders = [
        SpreadOrderOut(
            spread_id=r["spread_id"],
            kind=r["kind"],
            ib_order_id=r["ib_order_id"],
            perm_id=r["perm_id"],
            filled_qty=r["filled_qty"],
            price=r["price"],
            commission=r["commission"],
            reason=r["reason"],
            created_at=as_utc(r["created_at"]),
            mode=r["mode"],
            side=r["side"],
            expiry=r["expiry"],
            short_strike=r["short_strike"],
            long_strike=r["long_strike"],
        )
        for r in rows
    ]
    return SpreadOrdersResponse(as_of=now, available=True, underlying=underlying, orders=orders)
