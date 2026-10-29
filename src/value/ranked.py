"""The ranked monthly record's arithmetic (spec §6.8). Pure: no I/O.

Each month, per list, every scored name of the evidence universe is ordered by its rank score;
the top tenth, the bottom tenth and the whole scored universe become hypothetical equal-weight
portfolios held to the next formation, each measured against SPY (Gray & Carlisle's decile
test). The score orders names and never feeds a gate or a size.
"""

from __future__ import annotations

from datetime import date
from statistics import mean
from typing import Literal

Bucket = Literal["top", "bottom", "all"]
BUCKETS: tuple[Bucket, Bucket, Bucket] = ("top", "bottom", "all")
MIN_NAMES = 10  # below this a tenth is empty and nothing is formed


def buckets(scores: dict[str, float | None]) -> dict[Bucket, list[str]] | None:
    """The three portfolios: names ordered by score (highest first, ties by symbol), the top
    and bottom ``n // 10`` and all of them. None when fewer than ten names have a score."""
    ordered = sorted(
        ((score, symbol) for symbol, score in scores.items() if score is not None),
        key=lambda pair: (-pair[0], pair[1]),
    )
    k = len(ordered) // 10
    if len(ordered) < MIN_NAMES or k == 0:
        return None
    names = [symbol for _, symbol in ordered]
    return {"top": names[:k], "bottom": names[-k:], "all": names}


def equal_weight_return(
    members: list[str], start: dict[str, float], end: dict[str, float]
) -> tuple[float | None, int]:
    """The mean of the members' close-to-close returns, and how many members were dropped for
    lacking a close at either end (a halted or delisted name: survivorship, printed)."""
    returns = [end[m] / start[m] - 1.0 for m in members if start.get(m, 0.0) > 0.0 and m in end]
    return (mean(returns) if returns else None), len(members) - len(returns)


def is_new_month(last_formed: date | None, as_of: date) -> bool:
    """A new formation on the first nightly run whose session falls in a later month."""
    return last_formed is None or (as_of.year, as_of.month) != (last_formed.year, last_formed.month)
