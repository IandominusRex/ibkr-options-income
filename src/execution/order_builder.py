"""Build option LimitOrders at mid-price.

Never use MarketOrder for option entries — always LimitOrder at mid, rounded to
the nearest $0.05 tick. This is the only place an ib_async Order object is
constructed; nothing outside this module should need to know the constructor.
"""

from __future__ import annotations

from ib_async import LimitOrder

from src.common.schemas import OptionQuote, TradeCandidate


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
    # Round to nearest $0.05 tick (standard for liquid equity options).
    price = round(round(mid / 0.05) * 0.05, 2)
    return LimitOrder(
        action="SELL",
        totalQuantity=candidate.contracts,
        lmtPrice=price,
        tif="DAY",
    )
