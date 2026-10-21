"""The scale-in ladder's pure rules (deterministic tier; spec section 6).

In a clear downturn a further CSP lot on a name is accepted only once the price has fallen into
a **zone** worked out from that name's own technicals. Everything here is a pure function of
numbers and bars handed in: no I/O, no config reads, no clock. The context builder
(`src/regime/context.py`) feeds it and `src/engine/regime_limits.py` applies the zone it
produces; the generator and the gate call the same functions.

* `name_drawdown_triggered` and `near_money_short_put` are the name-level triggers (any market
  regime): a sharp fall of the name itself, and a short put on it that is at or near the money.
* `compute_zone` places the zone below the **anchor** (the price at the last lot).
* `recovered` is the rebound exit: N closes **after the anchor lot** above the 20-day average
  and above the level that last broke (decision 35: closes from before the lot lifted the ladder
  on 2026-10-13 and 10-14 for exactly the TQQQ re-entries it exists to stop).
* `last_broken_support` finds that level.

This module reads technicals and bars only: nothing from the enrichment tier.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from src.analytics.support_levels import broken_supports
from src.common.config import RegimeLadderCfg
from src.common.schemas import (
    MarketRegime,
    OptionRight,
    PositionSnapshot,
    ScaleInZone,
)


def name_drawdown_triggered(bars: pd.DataFrame, atr: float, *, sessions: int, k_atr: float) -> bool:
    """True when the name has fallen at least *k_atr* ATRs from its recent high.

    ``1 - last_close / max(High[-sessions:]) >= k_atr x atr / last_close``. Judged on the
    name's own ATR, so a 3x ETF is held to its own volatility.
    """
    if bars is None or len(bars) == 0 or atr is None or not np.isfinite(atr) or atr <= 0:
        return False
    last = float(bars["Close"].iloc[-1])
    high = float(bars["High"].iloc[-sessions:].max())
    if last <= 0 or high <= 0:
        return False
    return (1.0 - last / high) >= k_atr * atr / last


def near_money_short_put(
    positions: list[PositionSnapshot], symbol: str, spot: float, atr: float, *, k_atr: float
) -> bool:
    """True when a short put on *symbol* has ``spot <= strike + k_atr x atr``.

    Not a strict in-the-money test: TQQQ 75P x10 was opened on 2026-10-13 with the underlying
    $0.12 *above* the 78P it was being added to, and an ITM test missed it.
    """
    target = symbol.upper()
    for p in positions:
        if (
            p.sec_type == "OPT"
            and p.right == OptionRight.PUT
            and p.position < 0
            and p.strike is not None
            and (p.underlying or p.symbol).upper() == target
            and spot <= p.strike + k_atr * atr
        ):
            return True
    return False


def compute_zone(
    *,
    anchor: float,
    anchor_source: str,
    atr: float,
    supports: list[float],
    regime: MarketRegime,
    triggers: list[str],
    cfg: RegimeLadderCfg,
) -> ScaleInZone:
    """The entry zone for the next lot below *anchor*.

    ``gap = max(min_gap_pct[regime] / 100, min_gap_atr x atr / anchor)``;
    ``ceiling = anchor x (1 - gap)``. The target is the first support at or under the ceiling,
    +- ``band_atr x atr`` and capped at the ceiling on top; with no such support the zone is the
    gap itself, ``[ceiling - band_atr x atr, ceiling]``. *supports* must be detected relative
    to the **anchor** (not the spot): detected relative to the spot, a support between the spot
    and the ceiling would be dropped and a price already past the target would be blocked.
    """
    gap = max(cfg.min_gap_pct[regime] / 100.0, cfg.min_gap_atr * atr / anchor)
    ceiling = anchor * (1.0 - gap)
    band = cfg.band_atr * atr
    support = next((lvl for lvl in sorted(supports, reverse=True) if lvl <= ceiling), None)
    if support is not None:
        low, high = support - band, min(support + band, ceiling)
    else:
        low, high = ceiling - band, ceiling
    return ScaleInZone(
        anchor=anchor,
        anchor_source=anchor_source,  # type: ignore[arg-type]
        zone_low=round(low, 4),
        zone_high=round(high, 4),
        support=round(support, 4) if support is not None else None,
        min_gap_pct=round(gap * 100.0, 4),
        triggers=list(triggers),
    )


def last_broken_support(
    bars: pd.DataFrame, *, anchor: float, after: date, atr: float, broken_atr: float
) -> float | None:
    """The support that broke most recently, among those that broke after *after*.

    "Broken" is the support detector's own rule (a close more than ``broken_atr x atr`` under
    the swing low). Only levels under the *anchor* that broke on a date after the anchor lot's
    fill are considered; the latest break wins, the higher level on a tie. None when nothing
    broke since the lot.
    """
    best: tuple[date, float] | None = None
    for level, when in broken_supports(bars, spot=anchor, atr=atr, broken_atr=broken_atr):
        if when <= after:
            continue
        if best is None or (when, level) > best:
            best = (when, level)
    return best[1] if best is not None else None


def recovered(
    bars: pd.DataFrame, *, sma20: float | None, level: float, closes: int, after: date
) -> bool:
    """The rebound exit: the last *closes* daily closes after *after* are all above both
    *sma20* and *level*.

    Only closes dated **after** *after* (the anchor lot's fill date, ET) count, and there must
    be at least *closes* of them. *level* is the most recently broken support, else the anchor.
    """
    if sma20 is None or bars is None or len(bars) == 0 or closes < 1:
        return False
    mask = np.array([d > after for d in bars.index.date])
    later = bars["Close"].astype(float)[mask]
    if len(later) < closes:
        return False
    tail = later.iloc[-closes:]
    return bool((tail > sma20).all() and (tail > level).all())
