"""Roll candidates for existing short option positions.

``construct_roll`` (2026-10-11 roll redesign) is the policy-driven builder: nearest later expiry
first, then the most favourable strike (lowest put / highest call) that clears the net-credit
floor without raising |delta|, with every rejection counted by reason code. Its inputs and
limits come from ``config/settings.yaml → roll:`` (``RollCfg``), the same object the Rules
Engine and the roll executor read. It replaced the pre-redesign ``generate_roll_candidates``,
which required a 0.10 delta cut inside the entry band and so never produced a roll.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from src.analytics.fair_value import compute_ideal_zone, zone_for_contract
from src.analytics.liquidity import liquidity_failures, score_liquidity
from src.common.config import RollCfg, get_config
from src.common.schemas import (
    FundamentalStats,
    IVStats,
    OptionQuote,
    OptionRight,
    PositionSnapshot,
    RollOrigin,
    ScoreCard,
    Strategy,
    TechnicalStats,
    TradeCandidate,
)
from src.engine.risk_engine import rolls_down_enough
from src.storage.roll_chains import RollChainState
from src.strategies._scoring import make_candidate_id, technical_score

# ---------------------------------------------------------------------------
# Policy-driven construction (2026-10-11 roll redesign)
# ---------------------------------------------------------------------------

_EPS = 1e-9  # float noise must not reject a roll sitting exactly on a floor


@dataclass(frozen=True)
class RollContext:
    """Everything ``construct_roll`` needs to know about the short being rolled."""

    position: PositionSnapshot
    current: OptionQuote  # live quote of the alerted contract itself
    spot: float | None
    chain: RollChainState
    closed_candidate_id: str | None  # the system candidate that sold the short, for the ledger
    next_earnings: date | None
    ex_div_date: date | None
    dividend: float | None  # next cash dividend $/sh
    allow_debit: bool  # a keep-shares covered-call roll may pay up to roll.cc.max_debit
    today: date


def construct_roll(
    ctx: RollContext,
    quotes: list[OptionQuote],
    iv_stats: IVStats,
    tech_stats: TechnicalStats,
    cfg: RollCfg,
) -> tuple[TradeCandidate | None, dict[str, int]]:
    """Return the roll to propose (or None) and a count of every rejection by reason code.

    Selection is lexicographic: the nearest later expiry that yields any qualifying strike
    wins; within it the most favourable strike does. A qualifying strike is same-or-better
    (put ≤ old, call ≥ old), liquid, priced, nets at least the floor (``min_net_credit``, or
    ``-cc.max_debit`` for a keep-shares call roll), does not raise |delta|, and — for a call
    expiring after an ex-date — keeps more extrinsic than the dividend plus the buffer. The
    expiry must stay before earnings, inside ``new_leg.target_dte_max`` and inside the chain's
    extension cap. A chain already at ``limits.max_rolls_per_chain`` inspects nothing.
    """
    rej: Counter[str] = Counter()
    pos = ctx.position
    assert pos.expiry is not None and pos.strike is not None and pos.right is not None
    if ctx.chain.seq >= cfg.limits.max_rolls_per_chain:
        return None, {"roll_limit_reached": 1}
    old_mid = ctx.current.strict_mid
    if old_mid is None or old_mid <= 0:
        return None, {"current_unpriced": 1}
    old_delta = abs(ctx.current.delta) if ctx.current.delta is not None else None
    floor = -cfg.cc.max_debit if ctx.allow_debit else cfg.new_leg.min_net_credit
    is_put = pos.right == OptionRight.PUT
    latest = ctx.chain.original_expiry + timedelta(days=cfg.limits.max_extension_days)

    by_expiry: dict[date, list[OptionQuote]] = defaultdict(list)
    for quote in quotes:
        if quote.right == pos.right and quote.expiry > pos.expiry:
            by_expiry[quote.expiry].append(quote)

    for expiry in sorted(by_expiry):
        group = by_expiry[expiry]
        if expiry > latest:
            rej["extension_cap"] += len(group)
            continue
        if (expiry - ctx.today).days > cfg.new_leg.target_dte_max:
            rej["dte_cap"] += len(group)
            continue
        if ctx.next_earnings is not None and ctx.next_earnings <= expiry:
            rej["earnings_before_expiry"] += len(group)
            continue
        for quote in sorted(group, key=lambda x: x.strike, reverse=not is_put):
            reason = _reject_reason(quote, ctx, old_mid, old_delta, floor, cfg)
            if reason is not None:
                rej[reason] += 1
                continue
            return _roll_candidate(quote, ctx, old_mid, iv_stats, tech_stats), dict(rej)
    return None, dict(rej)


def _reject_reason(
    quote: OptionQuote,
    ctx: RollContext,
    old_mid: float,
    old_delta: float | None,
    floor: float,
    cfg: RollCfg,
) -> str | None:
    pos = ctx.position
    assert pos.strike is not None
    is_put = pos.right == OptionRight.PUT
    if (quote.strike > pos.strike) if is_put else (quote.strike < pos.strike):
        return "strike_worse"
    new_mid = quote.strict_mid
    if new_mid is None or new_mid <= 0:
        return "unpriced"
    # Volume is an entry-quality filter; a roll re-places existing exposure, so only the
    # quote and open-interest gates apply to the new leg.
    failures = liquidity_failures(quote, enforce_volume=False)
    if failures:
        return failures[0]
    if new_mid - old_mid < floor - _EPS:
        return "net_below_floor"
    if is_put and ctx.spot is not None and ctx.spot < pos.strike:
        # In the money: only a roll down that lowers the assignment cost is worth sending.
        if not rolls_down_enough(pos.strike, quote.strike, new_mid - old_mid, cfg):
            return "not_rolled_down"
    if quote.delta is None:
        return "delta_missing"
    if old_delta is not None and abs(quote.delta) > old_delta + _EPS:
        return "delta_increases"
    if (
        not is_put
        and ctx.ex_div_date is not None
        and ctx.dividend is not None
        and ctx.today <= ctx.ex_div_date <= quote.expiry  # yfinance can return a past ex-date
    ):
        intrinsic = max(0.0, (ctx.spot or 0.0) - quote.strike)
        if new_mid - intrinsic < ctx.dividend + cfg.ex_div.buffer - _EPS:
            return "ex_div_assignment_risk"
    return None


def _roll_candidate(
    quote: OptionQuote,
    ctx: RollContext,
    old_mid: float,
    iv_stats: IVStats,
    tech_stats: TechnicalStats,
) -> TradeCandidate:
    pos = ctx.position
    assert pos.expiry is not None and pos.strike is not None and pos.right is not None
    new_mid = quote.strict_mid
    assert new_mid is not None
    underlying = pos.underlying or pos.symbol
    contracts = abs(int(pos.position))
    net = round(new_mid - old_mid, 4)
    new_dte = (quote.expiry - ctx.today).days
    delta_abs = abs(quote.delta) if quote.delta is not None else 0.0
    missing_iv_rank_score: float = get_config().weights.get("missing_iv_rank_score", 50.0)
    # Display/audit only for a roll (the Rules Engine scopes the fair-value gate to income
    # strategies); the card shows the new strike's zone like every other candidate.
    zone = compute_ideal_zone(
        symbol=underlying,
        right=pos.right,
        dte=new_dte,
        spot=tech_stats.price,
        tech=tech_stats,
        iv=iv_stats,
        fund=FundamentalStats(symbol=underlying),
    )
    breakeven = quote.strike - net if pos.right == OptionRight.PUT else quote.strike + net
    return TradeCandidate(
        candidate_id=make_candidate_id(
            Strategy.ROLL, underlying, quote.right, quote.strike, quote.expiry
        ),
        strategy=Strategy.ROLL,
        underlying=underlying,
        right=quote.right,
        strike=quote.strike,
        expiry=quote.expiry,
        contracts=contracts,
        premium=net,
        collateral=quote.strike * contracts * 100,
        roc_pct=0.0,
        annualized_yield_pct=0.0,
        breakeven=round(breakeven, 4),
        prob_otm=round(1 - delta_abs, 4),
        delta=quote.delta,
        iv_rank=iv_stats.iv_rank,
        dte=new_dte,
        next_earnings=ctx.next_earnings,
        ideal=zone_for_contract(zone, quote.strike, iv_stats),
        scores=ScoreCard(
            symbol=underlying,
            iv_score=iv_stats.iv_rank if iv_stats.iv_rank is not None else missing_iv_rank_score,
            technical_score=technical_score(quote, tech_stats),
            fundamental_score=0.0,
            liquidity_score=score_liquidity(quote),
            assignment_safety_score=(1 - delta_abs) * 100,
        ),
        price_source=tech_stats.price_source,
        greeks_source=quote.greeks_source,
        quote_bid=quote.bid,
        quote_ask=quote.ask,
        open_interest=quote.open_interest,
        option_volume=quote.volume,
        rationale_tags=["iv_rank_unavailable"] if iv_stats.iv_rank is None else [],
        roll_from=RollOrigin(
            con_id=pos.con_id,
            candidate_id=ctx.closed_candidate_id,
            strike=pos.strike,
            expiry=pos.expiry,
            right=pos.right,
            contracts=contracts,
            chain_id=ctx.chain.chain_id,
            seq=ctx.chain.seq + 1,
            original_expiry=ctx.chain.original_expiry,
            old_mid=old_mid,
            new_mid=new_mid,
            allow_debit=ctx.allow_debit,
            itm_at_proposal=(
                pos.right == OptionRight.PUT and ctx.spot is not None and ctx.spot < pos.strike
            ),
        ),
    )
