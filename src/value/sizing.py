"""Sizing and tranches (spec §9.5, §9.6 as amended by revision 4). Pure: no I/O.

The book holds no cash back; its ``ceiling_pct_of_net_liq`` is a ceiling on what it may hold at
cost, and every size is a share of that ceiling: a margin of safety in a list's tier buys that
tier's percentage of the ceiling (8% at most, the name cap), entered in tranches of a third:
the first at READY, the second on a higher low, the third on a close above the 50-day SMA, at
least ``tranche_min_sessions`` apart, each re-gated. A slow trend brake (SPY's month-end close
under its 10-month SMA) halves the ceiling and stops new entries (spec §9.6).
"""

from __future__ import annotations

import math
from datetime import date

from src.common.config import ValueBookCfg

TEN_MONTHS = 10


def tier_pct(mos_pct: float | None, rows: list[tuple[float, float]]) -> float:
    """The size (percent of the ceiling) the margin of safety reaches; 0 below the first row
    or when the margin is unknown."""
    if mos_pct is None:
        return 0.0
    size = 0.0
    for start, pct in rows:
        if mos_pct >= start:
            size = pct
    return size


def ceiling_usd(net_liq: float, cfg: ValueBookCfg, *, trend_brake: bool) -> float:
    cap = max(0.0, net_liq) * cfg.ceiling_pct_of_net_liq / 100.0
    return cap * (cfg.trend_brake_ceiling_pct / 100.0 if trend_brake else 1.0)


def target_cost(
    list_name: str, mos: float | None, net_liq: float, cfg: ValueBookCfg, *, trend_brake: bool
) -> float:
    """The whole position's cost: the tier's share of the ceiling, never above the name cap."""
    ceiling = ceiling_usd(net_liq, cfg, trend_brake=trend_brake)
    rows = getattr(cfg.tiers, list_name)
    pct = min(tier_pct(None if mos is None else mos * 100.0, rows), cfg.name_cap_pct)
    return ceiling * pct / 100.0


def tranche_shares(target: float, tranches: int, price: float, held_cost: float) -> int:
    """Shares for the next tranche: a third of the target (never past it), whole shares."""
    if price <= 0 or tranches < 1:
        return 0
    cost = min(target / tranches, max(0.0, target - held_cost))
    return max(0, math.floor(cost / price))


def tranche_due(
    done: int,
    sessions_since_last: int | None,
    lows_since_last: list[float],
    close: float,
    sma50: float | None,
    cfg: ValueBookCfg,
) -> bool:
    """Whether the next tranche is due: the first at READY; the second on a higher low (the
    last five sessions' low above the low before them, since the last tranche); the third on a
    close above the 50-day SMA. Never two within ``tranche_min_sessions``."""
    if done >= cfg.tranches:
        return False
    if done == 0:
        return True
    if sessions_since_last is None or sessions_since_last < cfg.tranche_min_sessions:
        return False
    if done == 1:
        return len(lows_since_last) >= 10 and min(lows_since_last[-5:]) > min(lows_since_last[:-5])
    return sma50 is not None and close > sma50


def trend_brake(month_end_closes: list[float]) -> bool | None:
    """SPY's last month-end close below the mean of the last ten (spec §9.6); None without ten."""
    if len(month_end_closes) < TEN_MONTHS:
        return None
    window = month_end_closes[-TEN_MONTHS:]
    return month_end_closes[-1] < sum(window) / TEN_MONTHS


def month_end_closes(closes: list[tuple[date, float]]) -> list[float]:
    """The last close of each calendar month in *closes* (ascending), the current month included
    only once it has ended (a later bar exists)."""
    out: list[float] = []
    for i, (day, close) in enumerate(closes):
        nxt = closes[i + 1][0] if i + 1 < len(closes) else None
        if nxt is not None and (nxt.year, nxt.month) != (day.year, day.month):
            out.append(close)
    return out
