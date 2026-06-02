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

    Uses the true bid/ask midpoint only — never the `last` print that `OptionQuote.mid`
    falls back to (a stale trade can sit far from the live market and misprice the order).
    Raises ValueError when a genuine two-sided market is unavailable.
    """
    if quote.ask is None or quote.ask <= 0:
        raise ValueError(
            f"No mid price (no ask) for {candidate.candidate_id} "
            f"({candidate.underlying} {candidate.right} {candidate.strike} "
            f"{candidate.expiry}) — bid={quote.bid} ask={quote.ask}"
        )
    # bid=0.00 is valid for far-OTM options (no buyers); use ask/2 as the mid.
    effective_bid = quote.bid if (quote.bid is not None and quote.bid >= 0) else 0.0
    mid = (effective_bid + quote.ask) / 2
    price = _round_to_tick(mid)
    return LimitOrder(
        action="SELL",
        totalQuantity=candidate.contracts,
        lmtPrice=price,
        tif="DAY",
    )
