"""The Nasdaq-100 breadth oscillator (deterministic tier; risk-envelope Task 10a, ruling L2).

Inspired by the McClellan oscillator, but built for this book: the stock oscillator counts NYSE
breadth, which held up through the Nov 2026 tech selloff (spec §2.7), while the book's leveraged
risk is Nasdaq-100 and semiconductor risk. So the count is over the Nasdaq-100 constituents:

    RANA_t = (adv - dec) / (adv + dec) x 1000
    osc_t  = EMA_0.10(RANA) - EMA_0.05(RANA)        (the 19- and 39-day smoothing constants)

Everything here is pure: counts in, numbers out, no I/O and no enrichment-tier import (it is on
`tests/test_regime_fence.py`'s deterministic list). History comes from thetrading.tools
(`src/data/breadth_backend.py`, through `src/data/factory.py`); going forward the system makes its
own count each night from the committed constituent list's closes (`count_from_closes`). Where both
sources have a day and disagree by more than a stated number of RANA points, the day is flagged
and our own count is used (`merge_counts`).
"""

from __future__ import annotations

import math
from datetime import date

from src.common.schemas import BreadthCount


def rana(adv: int, dec: int) -> float | None:
    """The ratio-adjusted net advancers: ``(adv - dec) / (adv + dec) x 1000``; None when nothing moved."""
    total = adv + dec
    if total <= 0:
        return None
    return (adv - dec) / total * 1000.0


def oscillator(
    counts: list[BreadthCount],
    *,
    fast: float = 0.10,
    slow: float = 0.05,
    warm_up: int = 60,
) -> list[float | None]:
    """The oscillator for each count, in ascending date order (the input order is irrelevant).

    Both EMAs use ``adjust=False`` (``ema = alpha x x + (1 - alpha) x ema``) and start on the
    first RANA. The first *warm_up* rows are ``None`` (the EMAs run through them, they are just not
    trusted yet). A day with no movers has no RANA: its value is ``None`` and the EMAs skip it.

    The result is aligned with the *date-sorted* counts, which is how callers pair them.
    """
    ordered = sorted(counts, key=lambda c: c.day)
    out: list[float | None] = []
    ema_fast: float | None = None
    ema_slow: float | None = None
    for i, c in enumerate(ordered):
        value = rana(c.adv, c.dec)
        if value is not None:
            if ema_fast is None or ema_slow is None:
                ema_fast = ema_slow = value
            else:
                ema_fast = fast * value + (1.0 - fast) * ema_fast
                ema_slow = slow * value + (1.0 - slow) * ema_slow
        if i < warm_up or value is None or ema_fast is None or ema_slow is None:
            out.append(None)
        else:
            out.append(ema_fast - ema_slow)
    return out


def _valid(close: float | None) -> bool:
    return close is not None and math.isfinite(close) and close > 0.0


def count_from_closes(prev: dict[str, float], today: dict[str, float]) -> tuple[int, int, int]:
    """``(advancing, declining, unchanged)`` between two sessions' closes.

    A name counts only when both sessions carry a usable (finite, positive) close; a missing close
    counts in none of the three.
    """
    adv = dec = unch = 0
    for symbol, close in today.items():
        before = prev.get(symbol)
        if before is None or not (_valid(close) and _valid(before)):
            continue
        if close > before:
            adv += 1
        elif close < before:
            dec += 1
        else:
            unch += 1
    return adv, dec, unch


def merge_counts(
    tt: list[BreadthCount], own: list[BreadthCount], *, gap: float
) -> tuple[list[BreadthCount], set[date]]:
    """One count per day from the two sources, and the days they disagree on.

    A day only one source has takes that source's count. Where both have it, the history (tt) is
    kept unless the two RANA values differ by more than *gap* points: then the day is flagged and
    **our own count is used**. The gap is measured in RANA points (the count level, not the
    smoothed oscillator): with about 100 constituents one name moving from advancing to declining
    is 20 points, so 10 flags a real disagreement and tolerates an advancing/unchanged one.
    Returns the merged counts ascending by day and the set of flagged days.
    """
    tt_by = {c.day: c for c in tt}
    own_by = {c.day: c for c in own}
    merged: list[BreadthCount] = []
    flagged: set[date] = set()
    for day in sorted(set(tt_by) | set(own_by)):
        t, o = tt_by.get(day), own_by.get(day)
        if t is not None and o is not None:
            rt, ro = rana(t.adv, t.dec), rana(o.adv, o.dec)
            if rt is None or ro is None:
                disagree = (rt is None) != (ro is None)
            else:
                disagree = abs(rt - ro) > gap
            if disagree:
                flagged.add(day)
                merged.append(o)
            else:
                merged.append(t)
        else:
            only = t if t is not None else o
            if only is not None:
                merged.append(only)
    return merged, flagged
