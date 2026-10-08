"""Dealer gamma exposure (GEX) levels from a chain snapshot — the day's "action zones".

Standard retail model: dealers are long the calls customers sell and short the puts customers
buy, so per-strike GEX = Γ·OI·100·S²·0.01 (calls +, puts −) — dollars of underlying dealers
must trade per 1% move. Open interest is the prior close's figure (OPRA, ~06:30 ET) and
intraday 0DTE flow is invisible, so these levels are a regime filter and a strike-placement
guide, never a price target. Pure: no IBKR, no I/O.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime

from src.common.config import SpreadsCfg
from src.common.schemas import ChainOption, ChainSnapshot, GammaRegime, GexLevels
from src.spreads.pricing import ET, gamma, years_to_close

CONTRACT_MULTIPLIER = 100.0


def strike_gex(options: list[ChainOption], spot: float, now: datetime) -> dict[float, float]:
    out: dict[float, float] = defaultdict(float)
    for o in options:
        if not o.open_interest or o.iv is None or o.iv <= 0:
            continue
        g = gamma(spot, o.strike, years_to_close(now, o.expiry), o.iv)
        value = g * o.open_interest * CONTRACT_MULTIPLIER * spot * spot * 0.01
        out[o.strike] += value if o.right == "C" else -value
    return dict(out)


def net_gex(options: list[ChainOption], spot: float, now: datetime) -> float:
    return sum(strike_gex(options, spot, now).values())


def regime_of(net: float, has_data: bool) -> GammaRegime:
    if not has_data or net == 0:
        return "unknown"
    return "positive" if net > 0 else "negative"


def gamma_flip(
    options: list[ChainOption], spot: float, now: datetime, search_pct: float, steps: int = 121
) -> float | None:
    """The spot level nearest *spot* where net GEX changes sign (linear interpolation)."""
    if steps < 2 or spot <= 0:
        return None
    lo, hi = spot * (1 - search_pct), spot * (1 + search_pct)
    grid = [lo + (hi - lo) * i / (steps - 1) for i in range(steps)]
    values = [net_gex(options, s, now) for s in grid]
    best: float | None = None
    for i in range(steps - 1):
        s0, s1, v0, v1 = grid[i], grid[i + 1], values[i], values[i + 1]
        if v0 == 0 and v1 == 0:
            continue
        if v0 == 0:
            crossing = s0
        elif v0 * v1 < 0:
            crossing = s0 + (s1 - s0) * (-v0) / (v1 - v0)
        else:
            continue
        if best is None or abs(crossing - spot) < abs(best - spot):
            best = crossing
    return best


def walls(per_strike: dict[float, float], spot: float) -> tuple[float | None, float | None]:
    """(call_wall, put_wall): largest positive GEX at/above spot, most negative at/below."""
    calls = {k: v for k, v in per_strike.items() if k >= spot and v > 0}
    puts = {k: v for k, v in per_strike.items() if k <= spot and v < 0}
    call_wall = max(calls, key=lambda k: calls[k]) if calls else None
    put_wall = min(puts, key=lambda k: puts[k]) if puts else None
    return call_wall, put_wall


def expected_move(
    options: list[ChainOption], spot: float, expiry: date, factor: float
) -> float | None:
    """ATM straddle mid (strike nearest spot with both legs quoted) × *factor*."""
    mids: dict[float, dict[str, float]] = {}
    for o in options:
        m = o.mid
        if o.expiry != expiry or m is None:
            continue
        mids.setdefault(o.strike, {})[o.right] = m
    both = [k for k, v in mids.items() if "C" in v and "P" in v]
    if not both:
        return None
    atm = min(both, key=lambda k: abs(k - spot))
    return (mids[atm]["C"] + mids[atm]["P"]) * factor


def build_levels(
    gex_chain: ChainSnapshot, traded_chain: ChainSnapshot, cfg: SpreadsCfg, now: datetime
) -> GexLevels:
    # SPY trails SPX/10 as dividends accrue (more than the 0.1% wall buffer), so by default the
    # multiplier is the live spot ratio, measured with the same map.
    scale = cfg.gex.scale_to_underlying or traded_chain.spot / gex_chain.spot
    per = strike_gex(gex_chain.options, gex_chain.spot, now)
    net = sum(per.values())
    flip = (
        gamma_flip(gex_chain.options, gex_chain.spot, now, cfg.gex.flip_search_pct) if per else None
    )
    call_wall, put_wall = walls(per, gex_chain.spot)
    today = now.astimezone(ET).date()
    em = expected_move(
        traded_chain.options, traded_chain.spot, today, cfg.selection.em_straddle_factor
    )
    return GexLevels(
        as_of=now,
        spot=traded_chain.spot,
        net_gex=net,
        regime=regime_of(net, bool(per)),
        flip=flip * scale if flip is not None else None,
        call_wall=call_wall * scale if call_wall is not None else None,
        put_wall=put_wall * scale if put_wall is not None else None,
        expected_move=em,
        scale=scale,
    )


def regime_at(
    gex_chain: ChainSnapshot, traded_spot: float, scale: float, now: datetime
) -> GammaRegime:
    """Re-evaluate the regime at the current spot between map refreshes (OI fixed, Γ moves).

    *scale* is the multiplier the map was built with (``GexLevels.scale``).
    """
    spot = traded_spot / scale
    per = strike_gex(gex_chain.options, spot, now)
    return regime_of(sum(per.values()), bool(per))
