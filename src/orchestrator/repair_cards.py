"""The EOD's book-repair step (risk-envelope Task 30; spec §3.7 item 2, ruling P10).

Measures the book on stored IV (as the EOD envelope line does), builds today's proposals with the
pure ``engine.repair.build_proposals``, stores them (``repair_proposals``), re-marks every stored
proposal's shadow value from the latest stored closes (tapped or not), and posts one tap-only card
per new proposal. Nothing here sends an order: a card's Approve is the only way anything in it is
ever acted on, and that act goes through the Rules Engine.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select

from src.common.schemas import AccountSnapshot, PositionSnapshot, RepairProposal, TradeCandidate
from src.storage.db import session_scope
from src.storage.models import CandidateRow

log = logging.getLogger(__name__)
_ET = ZoneInfo("America/New_York")


def todays_cc_candidates(today: date, positions: list[PositionSnapshot]) -> list[TradeCandidate]:
    """Today's stored covered-call candidates (every scan's survivors), each cut to the calls the
    wheel's own uncovered shares can still back now (``uncovered_call_capacity``); none left
    drops it."""
    from src.strategies.covered_call import uncovered_call_capacity

    start = datetime(today.year, today.month, today.day, tzinfo=_ET).astimezone(UTC)
    with session_scope() as s:
        payloads = [
            row.payload
            for row in s.scalars(
                select(CandidateRow).where(
                    CandidateRow.strategy == "covered_call",
                    CandidateRow.created_at >= start.replace(tzinfo=None),
                )
            )
        ]
    out: list[TradeCandidate] = []
    for raw in payloads:
        try:
            cand = TradeCandidate.model_validate(raw)
        except Exception:
            continue
        room = uncovered_call_capacity(positions, cand.underlying)
        if room < 1:
            continue
        out.append(cand.model_copy(update={"contracts": min(cand.contracts, room)}))
    return out


def addable_names() -> list[str]:
    """The names a new cash-secured put may still open on: ``would_own`` (the effective list,
    overrides composed) and ``actively_wheeling``."""
    from src.common.universe import effective_universe

    uni = effective_universe()
    names = {str(s).upper() for s in uni.get("would_own") or []}
    names |= {str(s).upper() for s in uni.get("actively_wheeling") or []}
    return sorted(names)


def latest_close(symbol: str) -> float | None:
    from src.storage.price_history import load_bars

    bars = load_bars(symbol.upper(), limit=1)
    return bars[-1].close if bars and bars[-1].close > 0 else None


def build_and_store(
    positions: list[PositionSnapshot], account: AccountSnapshot, *, today: date
) -> list[RepairProposal]:
    """Build today's proposals and store the new ones; re-mark every stored proposal's shadow
    value. Returns the proposals stored today (with ids). Never raises."""
    from src.analytics.shock_inputs import build_inputs, stored_ivs
    from src.common.books import value_exposure
    from src.engine.envelope import room as envelope_room
    from src.engine.repair import build_proposals, shadow_value
    from src.storage.repair_proposals import mark_shadow_values, save_proposals

    saved: list[RepairProposal] = []
    try:
        exposure = value_exposure()
        value_by_name = dict(exposure.by_name) if exposure.active and exposure.readable else {}
        underlyings = sorted(
            {(p.underlying or p.symbol).upper() for p in positions if p.sec_type == "OPT"}
        )
        inputs = build_inputs(
            positions,
            nlv=account.net_liquidation,
            value_by_name=value_by_name,
            ivs=stored_ivs(underlyings),
        )
        room = envelope_room(inputs, today=today, may_start=False)
        proposals = build_proposals(
            inputs=inputs,
            room=room,
            cc_candidates=todays_cc_candidates(today, positions),
            addable=addable_names(),
            now=datetime.now(UTC),
        )
        saved = save_proposals(proposals, today)
    except Exception:
        log.exception("repair: today's proposals were not built")
    try:
        mark_shadow_values(
            today,
            lambda p: shadow_value(
                p,
                close=latest_close(p.symbol),
                twin_close=latest_close(p.twin) if p.twin else None,
                today=today,
            ),
        )
    except Exception:
        log.exception("repair: shadow values not marked")
    return saved


async def run_repair_step(
    positions: list[PositionSnapshot], account: AccountSnapshot, *, today: date
) -> int:
    """The EOD step: build, store, mark, and post the new cards. Returns the cards posted."""
    import asyncio

    from src.notify.sender import send_repair_cards

    saved = await asyncio.to_thread(build_and_store, positions, account, today=today)
    return await send_repair_cards(saved)
