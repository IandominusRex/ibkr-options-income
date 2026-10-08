"""Exit rules for open spreads, settlement math, and broker reconciliation. Pure.

Exit order: the time stop dominates once ``force_close`` is reached (it must fire even with no
quote); before it, nothing is decided without a usable mid. Then stop-loss, profit-take, a
short-strike touch, and the maximum hold time (OPG is usually out within two hours; same-day
options get riskier into the close). At the time stop every spread is closed, because SPY settles
in shares (``exits.let_expire: false``). Only with ``let_expire: true`` — a cash-settled XSP/SPX
book — is a far-OTM spread costing no more than ``let_expire_max_debit`` left to expire instead.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from src.common.config import SpreadsCfg
from src.common.schemas import ChainOption, SpreadExit, SpreadPosition
from src.spreads.pricing import ET


def _leg_mid(q: ChainOption | None) -> float | None:
    """A leg's mid; a leg nobody bids (but with a live ask) is a no-bid market worth ask / 2."""
    if q is None:
        return None
    if q.mid is not None:
        return q.mid
    if q.ask is not None and q.ask > 0 and (q.bid is None or q.bid < 0):
        return q.ask / 2
    return None


def _sale_value(q: ChainOption | None) -> float:
    """What selling the long leg back fetches at the natural price: its bid, else nothing."""
    if q is None or q.bid is None or q.bid < 0:
        return 0.0
    return q.bid


def debit_to_close(
    short_q: ChainOption | None, long_q: ChainOption | None
) -> tuple[float | None, float | None]:
    """(mid debit, natural debit = short ask − long bid) per share; None where unquoted.

    ib_async reports a bid as NaN whenever its size is 0 (``wrapper.priceSizeTick``), which is
    the normal state of a far-OTM 0DTE long once the trade is winning. A missing bid is a
    no-bid market, not a missing quote: the long sells for nothing at the natural price and is
    marked at ask / 2. Only a missing short ask leaves a close unpriceable.
    """
    mid: float | None = None
    nat: float | None = None
    short_mid, long_mid = _leg_mid(short_q), _leg_mid(long_q)
    if short_mid is not None and long_mid is not None:
        mid = round(short_mid - long_mid, 4)
    if short_q is not None and short_q.ask is not None and short_q.ask > 0:
        nat = round(short_q.ask - _sale_value(long_q), 4)
    return mid, nat


def short_strike_touched(pos: SpreadPosition, spot: float | None) -> bool:
    if spot is None:
        return False
    return spot <= pos.short_strike if pos.side == "put" else spot >= pos.short_strike


def evaluate_exit(
    pos: SpreadPosition,
    short_q: ChainOption | None,
    long_q: ChainOption | None,
    spot: float | None,
    now: datetime,
    cfg: SpreadsCfg,
) -> SpreadExit | None:
    x = cfg.exits
    mid, _ = debit_to_close(short_q, long_q)
    touched = short_strike_touched(pos, spot)
    if now.astimezone(ET).strftime("%H:%M") >= cfg.schedule.force_close:
        if (
            x.let_expire
            and mid is not None
            and mid <= x.let_expire_max_debit
            and spot is not None
            and not touched
        ):
            return SpreadExit(spread_id=pos.spread_id, reason="expire_worthless", close=False)
        return SpreadExit(spread_id=pos.spread_id, reason="time_stop", close=True)
    if mid is None:
        return None
    if mid >= pos.entry_credit * x.stop_debit_multiple:
        return SpreadExit(spread_id=pos.spread_id, reason="stop_loss", close=True)
    if mid <= pos.entry_credit * (1 - x.profit_take_pct / 100.0):
        return SpreadExit(spread_id=pos.spread_id, reason="profit_take", close=True)
    if x.close_on_short_strike_touch and touched:
        return SpreadExit(spread_id=pos.spread_id, reason="strike_touch", close=True)
    if x.max_hold_minutes is not None and now - pos.opened_at >= timedelta(
        minutes=x.max_hold_minutes
    ):
        return SpreadExit(spread_id=pos.spread_id, reason="max_hold", close=True)
    return None


def intrinsic_debit(pos: SpreadPosition, spot: float) -> float:
    """Settlement value per share of a short vertical at *spot*, in [0, width]."""
    if pos.side == "put":
        raw = pos.short_strike - spot
    else:
        raw = spot - pos.short_strike
    return max(0.0, min(pos.width, raw))


def reconcile(expected: list[SpreadPosition], broker_legs: dict[int, float]) -> list[str]:
    """Compare open *paper* spreads with the broker's spreads-book option legs (conId → qty).

    Empty list = consistent. Shadow positions never reach the broker and are ignored.
    """
    want: dict[int, float] = defaultdict(float)
    problems: list[str] = []
    for p in expected:
        if p.mode != "paper":
            continue
        if p.short_con_id is None or p.long_con_id is None:
            problems.append(f"{p.spread_id}: missing leg conIds")
            continue
        want[p.short_con_id] -= p.contracts
        want[p.long_con_id] += p.contracts
    for con_id in sorted(set(want) | set(broker_legs)):
        w, h = want.get(con_id, 0.0), broker_legs.get(con_id, 0.0)
        if abs(w - h) > 1e-9:
            problems.append(f"conId {con_id}: expected {w:+g}, broker holds {h:+g}")
    return problems
