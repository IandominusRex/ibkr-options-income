"""Candidate credit verticals placed beyond the day's action zone.

A put spread's short strike sits below BOTH the expected-move floor (spot − em × em_multiple)
and the put wall less a buffer; a call spread's short strike above both the expected-move
ceiling and the call wall plus a buffer. Per side, the closest strike that clears the delta cap
and the minimum credit wins. Further out of the money only gets cheaper, so the walk stops at
the first strike whose credit is too thin. Pure: no IBKR, no I/O, and no gating — that is
``risk.validate``'s job.
"""

from __future__ import annotations

from datetime import date, datetime

from src.common.config import SpreadsCfg
from src.common.schemas import ChainOption, ChainSnapshot, GexLevels, SpreadCandidate, SpreadSide
from src.spreads.pricing import ET


def short_boundary(side: SpreadSide, levels: GexLevels, cfg: SpreadsCfg) -> float | None:
    """Furthest-in strike a short leg may use. None (no trade) without an expected move."""
    if levels.expected_move is None:
        return None
    s = cfg.selection
    move = levels.expected_move * s.em_multiple
    buffer = levels.spot * s.wall_buffer_pct
    if side == "put":
        floor = levels.spot - move
        if levels.put_wall is not None:
            floor = min(floor, levels.put_wall - buffer)
        return floor
    ceiling = levels.spot + move
    if levels.call_wall is not None:
        ceiling = max(ceiling, levels.call_wall + buffer)
    return ceiling


def make_spread_id(
    side: SpreadSide, expiry: date, short_strike: float, long_strike: float, now: datetime
) -> str:
    return (
        f"{expiry:%Y%m%d}-{side[0].upper()}{short_strike:g}-{long_strike:g}"
        f"-{now.astimezone(ET):%H%M%S}"
    )


def _build(
    spread_id: str,
    side: SpreadSide,
    short_q: ChainOption,
    long_q: ChainOption,
    width: float,
    spot: float,
    quote_time: datetime,
) -> SpreadCandidate | None:
    short_mid, long_mid = short_q.mid, long_q.mid
    if short_mid is None or long_mid is None or short_q.bid is None or long_q.ask is None:
        return None
    return SpreadCandidate(
        spread_id=spread_id,
        side=side,
        expiry=short_q.expiry,
        short_strike=short_q.strike,
        long_strike=long_q.strike,
        width=width,
        short_con_id=short_q.con_id,
        long_con_id=long_q.con_id,
        credit_mid=round(short_mid - long_mid, 4),
        credit_natural=round(short_q.bid - long_q.ask, 4),
        short_delta=short_q.delta,
        short_leg_spread_pct=short_q.spread_pct,
        long_leg_spread_pct=long_q.spread_pct,
        spot=spot,
        quote_time=quote_time,
    )


def select_candidates(
    chain: ChainSnapshot,
    levels: GexLevels,
    cfg: SpreadsCfg,
    now: datetime,
    sides: list[SpreadSide] | None = None,
) -> list[SpreadCandidate]:
    """At most one candidate per side. *sides* (the entry trigger's choice) narrows the walk."""
    s = cfg.selection
    today = now.astimezone(ET).date()
    out: list[SpreadCandidate] = []
    for side in s.sides if sides is None else [x for x in s.sides if x in sides]:
        boundary = short_boundary(side, levels, cfg)
        if boundary is None:
            continue
        right = "P" if side == "put" else "C"
        legs = {
            round(o.strike, 2): o for o in chain.options if o.right == right and o.expiry == today
        }
        if side == "put":
            shorts = sorted((k for k in legs if k <= boundary), reverse=True)
        else:
            shorts = sorted(k for k in legs if k >= boundary)
        for k in shorts:
            long_k = round(k - s.width if side == "put" else k + s.width, 2)
            long_q = legs.get(long_k)
            if long_q is None:
                continue
            short_q = legs[k]
            if short_q.delta is not None and abs(short_q.delta) > s.short_delta_max:
                continue
            cand = _build(
                make_spread_id(side, today, k, long_k, now),
                side,
                short_q,
                long_q,
                s.width,
                chain.spot,
                chain.as_of,  # when the quotes were taken: the gate's stale_quote input
            )
            if cand is None or cand.credit_mid <= 0:
                continue
            if cand.credit_mid < s.min_credit_pct_of_width * s.width:
                break
            out.append(cand)
            break
    return out


def refresh_candidate(
    c: SpreadCandidate,
    short_q: ChainOption,
    long_q: ChainOption,
    now: datetime,
    spot: float | None = None,
) -> SpreadCandidate | None:
    """The same spread repriced on fresh leg quotes and, when known, a fresh spot (the
    send-time re-gate's input)."""
    return _build(c.spread_id, c.side, short_q, long_q, c.width, spot or c.spot, now)
