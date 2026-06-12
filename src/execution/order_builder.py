"""Build option LimitOrders at mid-price.

Never use MarketOrder for option entries — always LimitOrder at mid, rounded to
the nearest $0.05 tick. This is the only place an ib_async Order object is
constructed; nothing outside this module should need to know the constructor.
"""

from __future__ import annotations

from ib_async import ComboLeg, Contract, LimitOrder

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


def _round_combo_tick(price: float) -> float:
    """Round a net combo price to a penny.

    Options combos (BAG) price the *net* in $0.01 increments regardless of the
    per-leg penny-pilot tier, so a single $0.01 tick is correct here.
    """
    return round(round(price / 0.01) * 0.01, 2)


def build_combo_roll_order(
    underlying: str,
    close_conid: int,
    open_conid: int,
    contracts: int,
    net_credit: float,
) -> tuple[Contract, LimitOrder]:
    """Build a two-leg BAG combo + net LimitOrder to roll a short option.

    Leg 1 BUYs back the existing short (``close_conid``); leg 2 SELLs the new short
    (``open_conid``) at a later expiry/strike. Submitting both as a single combo means
    they fill together-or-not-at-all — there is no legging risk where the buy-back fills
    but the re-sell does not (leaving the account flat and un-hedged) or vice-versa.

    Pricing convention (IBKR options combo): the parent order BUYs the bag and
    ``lmtPrice`` is the NET DEBIT per share. A roll that collects a credit is therefore a
    NEGATIVE limit price — ``lmtPrice = -net_credit`` — and the order will not fill for
    less than ``net_credit`` of credit.

    NOTE: this combo sign convention is exercised against mocked IBKR in tests but has
    **not** been verified end-to-end in a live paper session. It is on the STATUS.md
    "needs live verification" list and must be confirmed on a paper account before any
    real-money roll.
    """
    if contracts < 1:
        raise ValueError(f"roll combo needs >=1 contract, got {contracts}")
    if close_conid <= 0 or open_conid <= 0:
        raise ValueError(
            f"roll combo requires qualified conIds for both legs "
            f"(close={close_conid}, open={open_conid})"
        )

    combo = Contract(
        symbol=underlying,
        secType="BAG",
        currency="USD",
        exchange="SMART",
        comboLegs=[
            # openClose: 1 = OPEN, 2 = CLOSE (IBKR ComboLeg convention).
            ComboLeg(conId=close_conid, ratio=1, action="BUY", exchange="SMART", openClose=2),
            ComboLeg(conId=open_conid, ratio=1, action="SELL", exchange="SMART", openClose=1),
        ],
    )
    order = LimitOrder(
        action="BUY",
        totalQuantity=contracts,
        lmtPrice=_round_combo_tick(-net_credit),
        tif="DAY",
    )
    return combo, order
