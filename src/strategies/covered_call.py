"""Generate covered-call candidates from existing long stock positions."""

from __future__ import annotations

import logging
import math

from src.analytics.liquidity import (
    passes_liquidity_gates,
    score_liquidity,
    volume_gate_active,
)
from src.common.config import get_config
from src.common.schemas import (
    FundamentalStats,
    IVStats,
    OptionQuote,
    OptionRight,
    PositionSnapshot,
    ScoreCard,
    Strategy,
    TechnicalStats,
    TradeCandidate,
)
from src.strategies._scoring import fundamental_score, make_candidate_id, technical_score

log = logging.getLogger(__name__)


def generate_cc_candidates(
    symbol: str,
    quotes: list[OptionQuote],
    position: PositionSnapshot,
    iv_stats: IVStats,
    tech_stats: TechnicalStats,
    fund_stats: FundamentalStats,
    existing_short_calls: int = 0,
) -> list[TradeCandidate]:
    """Return ranked CC candidates for *symbol* given the existing long stock *position*.

    *existing_short_calls* is the number of call contracts already written against this
    underlying (sum of |position| over short OPT/CALL legs). Sizing nets these out so we
    only ever propose calls covered by *uncovered* shares — without this, a re-scan (and
    especially the 15-min automated loop) would regenerate the full-share-count CC every
    cycle and stack writes on top of already-written calls, ending in naked short calls.

    Returns [] when position is short/zero, all shares are already covered, or no quotes
    pass filters.
    """
    if position.position <= 0:
        return []

    owned_contracts = math.floor(abs(position.position) / 100)
    contracts = owned_contracts - max(0, existing_short_calls)
    if contracts < 1:
        return []

    cfg = get_config()
    cc_cfg = cfg.risk["covered_call"]
    income_cfg = cfg.risk["income"]

    delta_min: float = cc_cfg["delta_min"]
    delta_max: float = cc_cfg["delta_max"]
    dte_min: int = cc_cfg["dte_min"]
    dte_max: int = cc_cfg["dte_max"]
    min_strike_vs_basis: float = cc_cfg.get("min_strike_vs_basis", 1.00)

    candidates: list[TradeCandidate] = []
    enforce_volume = volume_gate_active()  # N19: skip the volume gate before the morning cutoff

    for quote in quotes:
        if quote.right != OptionRight.CALL:
            continue
        if quote.delta is None:
            continue
        delta = abs(quote.delta)
        if not (delta_min <= delta <= delta_max):
            continue
        dte = quote.dte
        if not (dte_min <= dte <= dte_max):
            continue
        # Require a genuine two-sided market (N10): never price a candidate off a stale `last`.
        mid = quote.strict_mid
        if mid is None or mid <= 0:
            continue
        if not passes_liquidity_gates(quote, enforce_volume=enforce_volume):
            continue
        # Drawdown-CC policy (N18, explicit decision): with the default `min_strike_vs_basis: 1.00`
        # a strike below cost basis is rejected — so an *underwater* holding generates no covered
        # calls (writing below basis would lock in a loss if assigned). This is deliberate: it
        # favours not capping the recovery over squeezing income from a loser. To allow below-basis
        # writes (e.g. to keep harvesting premium on a long-term hold), lower the knob in
        # risk_limits.yaml (e.g. 0.95 permits strikes down to 5% below basis).
        if quote.strike < position.avg_cost * min_strike_vs_basis:
            continue

        collateral = position.avg_cost * contracts * 100  # full capital at risk for all contracts
        # ROC is deliberately measured against the cost BASIS (avg_cost), i.e. return on the
        # capital actually tied up in the shares you own — not the current market price. For a
        # name that has run up this understates yield-on-market-value, which is the conservative
        # choice for an income screen (you don't want the run-up to inflate the apparent yield).
        roc_pct = (mid / position.avg_cost) * 100
        annualized_yield_pct = roc_pct * (365 / dte) if dte > 0 else 0.0

        if roc_pct < income_cfg["min_roc_pct"]:
            continue
        if annualized_yield_pct < income_cfg["min_annualized_yield_pct"]:
            continue

        scores = ScoreCard(
            symbol=symbol,
            iv_score=iv_stats.iv_rank if iv_stats.iv_rank is not None else 0.0,
            technical_score=technical_score(quote, tech_stats),
            fundamental_score=fundamental_score(fund_stats),
            liquidity_score=score_liquidity(quote),
            assignment_safety_score=(1 - delta) * 100,
        )

        candidates.append(
            TradeCandidate(
                candidate_id=make_candidate_id(
                    Strategy.COVERED_CALL, symbol, quote.right, quote.strike, quote.expiry
                ),
                strategy=Strategy.COVERED_CALL,
                underlying=symbol,
                right=quote.right,
                strike=quote.strike,
                expiry=quote.expiry,
                contracts=contracts,
                premium=mid,
                collateral=collateral,
                roc_pct=round(roc_pct, 4),
                annualized_yield_pct=round(annualized_yield_pct, 4),
                breakeven=round(position.avg_cost - mid, 4),
                prob_otm=round(1 - delta, 4),
                delta=quote.delta,
                iv_rank=iv_stats.iv_rank,
                vrp=iv_stats.vrp,
                dte=dte,
                next_earnings=fund_stats.next_earnings,
                scores=scores,
            )
        )

    if not candidates:
        call_quotes = sum(1 for q in quotes if q.right == OptionRight.CALL)
        log.warning(
            "No CC candidates passed filters for %s (%d call quotes evaluated)", symbol, call_quotes
        )

    candidates.sort(key=lambda c: c.roc_pct, reverse=True)
    return candidates
