"""Build option LimitOrders at mid-price.

Never use MarketOrder for option entries — always LimitOrder at mid, rounded to
the nearest $0.05 tick. This is the only place an ib_async Order object is
constructed; nothing outside this module should need to know the constructor.
"""

from __future__ import annotations

from ib_async import LimitOrder

from src.common.schemas import OptionQuote, TradeCandidate


def _round_to_tick(price: float) -> float:
    """Round a premium to its exchange tick size.

    Penny-pilot classes (which cover essentially all of this system's liquid
    ETF/large-cap universe) quote in $0.01 below $3.00 and $0.05 at/above $3.00.
    Rounding everything to $0.05 (the old behaviour) mispriced sub-$3 premiums.
    """
    tick = 0.01 if price < 3.0 else 0.05
    return round(round(price / tick) * tick, 2)


def build_limit_order(candidate: TradeCandidate, quote: OptionQuote) -> LimitOrder:
    """Return a mid-price DAY LimitOrder (SELL) for the given candidate.

    Raises ValueError if there is no mid price on the quote.
    """
    mid = quote.mid
    if mid is None:
        raise ValueError(
            f"No mid price available for {candidate.candidate_id} "
            f"({candidate.underlying} {candidate.right} {candidate.strike} "
            f"{candidate.expiry}) — bid={quote.bid} ask={quote.ask}"
        )
    price = _round_to_tick(mid)
    return LimitOrder(
        action="SELL",
        totalQuantity=candidate.contracts,
        lmtPrice=price,
        tif="DAY",
    )
