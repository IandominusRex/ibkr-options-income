"""Wing planning for the SPXW capture (risk-envelope Task 17; spec §3.3, ruling E3). Pure, no I/O.

The SPY baseline candidate is a vertical at some distance from spot, which the GEX map's scale
(``levels.scale``: SPY level = SPX level x scale) turns into an index level. A wing is the same
vertical on SPXW or XSP: its short strike is the SPY short strike expressed in index points, snapped
to a **listed strike at or beyond it** (never closer to spot than the SPY leg), and its long strike
``width`` index points further out. That keeps the wing at the SPY candidate's distance in expected
moves, to within one strike step, because the expected move scales the same way.

Capture only: this module plans strikes, it never builds an order.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from src.common.schemas import ChainOption, SpreadCandidate

# Both candidates are CBOE index products. SPXW is SPX's daily class; XSP trades at SPX / 10.
INDEX_EXCHANGE = "CBOE"
XSP_SYMBOL = "XSP"
XSP_TRADING_CLASS = "XSP"
XSP_DIVISOR = 10.0


@dataclass(frozen=True, slots=True)
class WingPlan:
    instrument: str  # SPXW | XSP
    width: float
    short_strike: float
    long_strike: float
    expiry: date


@dataclass(frozen=True, slots=True)
class WingCapture:
    """A planned wing and the two leg quotes that came back for it (None: not quoted)."""

    plan: WingPlan
    trading_class: str
    short: ChainOption | None
    long: ChainOption | None


def plan_leg(
    cand: SpreadCandidate, *, ratio: float, strikes: list[float], width: float, instrument: str = ""
) -> WingPlan | None:
    """The wing for *cand* at *width* index points, or None when it cannot be planned.

    *ratio* is the SPY / wing-index level ratio (SPY / SPX = ``levels.scale``; SPY / XSP is
    ``scale * 10``). The short strike is the nearest listed strike at or beyond ``short / ratio``
    (below it for a put, above it for a call); the long strike is ``width`` further out and must
    also be listed.
    """
    if ratio <= 0 or width <= 0 or not strikes:
        return None
    listed = sorted({float(k) for k in strikes})
    target = cand.short_strike / ratio
    if cand.side == "put":
        beyond = [k for k in listed if k <= target + 1e-9]
        short = max(beyond) if beyond else None
        long = None if short is None else short - width
    else:
        beyond = [k for k in listed if k >= target - 1e-9]
        short = min(beyond) if beyond else None
        long = None if short is None else short + width
    if short is None or long is None or not any(abs(k - long) < 1e-9 for k in listed):
        return None
    return WingPlan(instrument, width, short, long, cand.expiry)
