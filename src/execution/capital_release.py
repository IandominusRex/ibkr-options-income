"""Capital release (value book spec revision 4, operator decision 2026-10-30).

The value book holds no cash back: the wheel sells cash-secured puts against the whole account.
When an approved value buy cannot be funded, the value process opens a funding request in
value.db; this module, run by the trading process every intraday cycle, reads the open requests
through the read-only ``src/common/value_view.py`` and closes the fewest wheel CSPs at breakeven or
better that free enough collateral (``capital.select_releases``), each gated by the Rules Engine
(``risk_engine.validate_release``) at decision time and again at send time on a fresh quote, and
sent through the wheel's own close path (``position_manager.close_short_position``: a LimitOrder
at mid, ``qualifyContracts``, cancel on timeout, the order/fill record, idempotent per contract),
stamped ``CloseReason.CAPITAL_RELEASE`` with the request in the order's detail.

It never buys: the value process confirms the freed cash on its own fresh account snapshot and
only then re-gates and sends the buy. A request exists only for an approved buy, so a release
inherits the buy's approval (Part 5 plan, ruling 7). Nothing here reads an LLM output. Skipped
while halted (the buy could not send) and while the book or release is off.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from datetime import datetime

from ib_async import IB
from sqlalchemy import select
from telegram import Bot

from src.common.config import get_config
from src.common.market_hours import today_et
from src.common.schemas import CloseReason, OptionRight, OrderState, PositionSnapshot
from src.common.value_view import FundingRequest, read_book
from src.engine.capital import ReleaseCandidate, select_releases
from src.engine.risk_engine import validate_release
from src.execution.position_manager import CloseResult, close_candidate_id, close_short_position
from src.storage.db import session_scope
from src.storage.models import OrderRow
from src.storage.roll_chains import chain_entry_credit_per_share
from src.storage.system_settings import is_halted

log = logging.getLogger(__name__)
_REQUEST = re.compile(r"capital release request (\d+)\b")
_CLOSE_ID = re.compile(r"^close:[^:]+:\d{8}:([0-9.]+):P$")


def _today_orders() -> list[OrderRow]:
    start = datetime.combine(today_et(), datetime.min.time())
    with session_scope() as s:
        return list(
            s.scalars(
                select(OrderRow).where(
                    OrderRow.close_reason == CloseReason.CAPITAL_RELEASE.value,
                    OrderRow.created_at >= start,
                )
            )
        )


def _strike(candidate_id: str) -> float | None:
    m = _CLOSE_ID.match(candidate_id or "")
    return float(m.group(1)) if m else None


def day_counts(orders: list[OrderRow]) -> tuple[int, float]:
    """(capital-release closes sent today, collateral they released), from today's orders."""
    sent = [o for o in orders if o.state not in (OrderState.REJECTED, OrderState.CANCELLED)]
    released = 0.0
    for o in sent:
        strike = _strike(o.candidate_id)
        if strike is not None:
            released += strike * 100.0 * float(o.filled_qty or 0.0)
    return len(sent), released


def request_progress(orders: list[OrderRow], request_id: int) -> tuple[bool, float]:
    """(a close for this request is still working, collateral already released for it)."""
    working, released = False, 0.0
    for o in orders:
        m = _REQUEST.search(o.detail or "")
        if m is None or int(m.group(1)) != request_id:
            continue
        if o.state in (OrderState.QUEUED, OrderState.SUBMITTED):
            working = True
        strike = _strike(o.candidate_id)
        if strike is not None:
            released += strike * 100.0 * float(o.filled_qty or 0.0)
    return working, released


Quote = Callable[[PositionSnapshot], Awaitable[tuple[float, float | None]]]


async def run_capital_release(
    ib_scan: IB,
    ib_exec: IB | None,
    bot: Bot | None = None,
    chat_id: str | None = None,
    *,
    quote: Quote | None = None,
    positions_fn: Callable[[], list[PositionSnapshot]] | None = None,
    net_liq_fn: Callable[[], Awaitable[float]] | None = None,
    close: Callable[..., Awaitable[CloseResult]] = close_short_position,
) -> int:
    """Service every open funding request once. Returns the closes sent."""
    cfg = get_config()
    book_cfg = cfg.value.book
    if not (book_cfg.enabled and book_cfg.release.enabled) or ib_exec is None or is_halted():
        return 0
    book = read_book()
    if book is None or not book.requests:
        return 0
    from src.execution.profit_take import _quote_short
    from src.ibkr.portfolio import get_account_snapshot_async, get_positions

    async def _net_liq() -> float:
        snap = await get_account_snapshot_async(ib_scan, cfg.secrets.ibkr_account or "")
        return snap.net_liquidation

    quote = quote or (lambda pos: _quote_short(ib_scan, pos))
    positions = (positions_fn or (lambda: get_positions(ib_scan)))()
    puts = [
        p
        for p in positions
        if p.sec_type == "OPT"
        and p.right == OptionRight.PUT
        and p.position < 0
        and p.strike
        and p.expiry is not None
    ]
    if not puts:
        return 0
    net_liq = await (net_liq_fn or _net_liq)()
    sent = 0
    for req in book.requests:
        sent += await _service(req, puts, net_liq, quote, close, ib_exec)
    return sent


async def _candidate(pos: PositionSnapshot, quote: Quote) -> ReleaseCandidate | None:
    with session_scope() as s:
        credit = chain_entry_credit_per_share(s, pos)
    if credit is None or credit <= 0:
        return None
    bid, ask = await quote(pos)
    assert pos.strike is not None
    return ReleaseCandidate(
        key=close_candidate_id(pos),
        underlying=(pos.underlying or pos.symbol).upper(),
        strike=float(pos.strike),
        contracts=int(abs(pos.position)),
        entry_credit=credit,
        bid=bid,
        ask=ask,
    )


async def _service(
    req: FundingRequest,
    puts: list[PositionSnapshot],
    net_liq: float,
    quote: Quote,
    close: Callable[..., Awaitable[CloseResult]],
    ib_exec: IB,
) -> int:
    orders = _today_orders()
    working, released = request_progress(orders, req.id)
    needed = req.needed_usd - released
    if working or needed <= 0:
        return 0
    closes_today, released_today = day_counts(orders)
    by_key: dict[str, PositionSnapshot] = {}
    eligible: list[ReleaseCandidate] = []
    for pos in puts:
        c = await _candidate(pos, quote)
        if c is None:
            continue
        reasons = validate_release(
            c,
            right=pos.right,
            closes_today=closes_today,
            released_today=released_today,
            net_liq=net_liq,
        )
        if not reasons:  # decision-time gate
            eligible.append(c)
            by_key[c.key] = pos
    release = get_config().value.book.release.model_dump()
    # The whole set must fit what is left of the day's caps: the gate checks each close alone,
    # so a set that only the day's caps would cut short at send time is never started (no
    # partial release that a predictable refusal would leave behind).
    release["max_closes_per_request"] = min(
        int(release["max_closes_per_request"]),
        int(release["max_closes_per_day"]) - closes_today,
    )
    if release["max_closes_per_request"] < 1:
        return 0
    chosen = select_releases(eligible, needed, release)
    day_cap = net_liq * float(release["max_release_pct_per_day"]) / 100.0
    if chosen and released_today + sum(c.released for c in chosen) > day_cap:
        log.info(
            "capital release: request %d (%s) would pass today's release cap", req.id, req.symbol
        )
        return 0
    if not chosen:
        log.info("capital release: request %d (%s) cannot be funded now", req.id, req.symbol)
        return 0
    sent = 0
    for c in chosen:
        pos = by_key[c.key]
        fresh = await _candidate(pos, quote)  # send-time gate on a fresh quote
        reasons = (
            ["release_no_quote"]
            if fresh is None
            else validate_release(
                fresh,
                right=pos.right,
                closes_today=closes_today + sent,
                released_today=released_today,
                net_liq=net_liq,
            )
        )
        if fresh is None or reasons:
            log.warning("capital release: %s refused at send time: %s", c.key, reasons)
            return sent  # the set no longer covers the request: the rest waits a cycle
        result = await close(
            ib_exec,
            pos,
            fresh.bid,
            fresh.ask or 0.0,
            reason=CloseReason.CAPITAL_RELEASE,
            note=f"capital release request {req.id} for {req.symbol}",
        )
        log.info("capital release: %s for request %d -> %s", c.key, req.id, result.status)
        if result.status in ("filled", "partial", "working"):
            sent += 1
        released_today += c.released
    return sent
