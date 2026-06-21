"""Generate roll candidates for existing short option positions."""

from __future__ import annotations

from datetime import date as date_cls

from src.analytics.liquidity import passes_liquidity_gates, score_liquidity
from src.common.profile import get_effective_risk
from src.common.schemas import (
    IVStats,
    OptionQuote,
    OptionRight,
    PositionSnapshot,
    ScoreCard,
    Strategy,
    TechnicalStats,
    TradeCandidate,
)
from src.strategies._scoring import make_candidate_id, technical_score


def generate_roll_candidates(
    position: PositionSnapshot,
    quotes: list[OptionQuote],
    iv_stats: IVStats,
    tech_stats: TechnicalStats,
) -> list[TradeCandidate]:
    """Return ranked roll candidates for the given short option *position*.

    Rolls are only generated when DTE <= 21 (nearing expiry) or |delta| > 0.40
    (delta drift). The intraday monitor (Phase 8) handles real-time triggering;
    this function just produces the candidates when asked.
    """
    if position.position >= 0:
        return []
    if position.right is None or position.expiry is None or position.strike is None:
        return []

    pos_dte = (position.expiry - date_cls.today()).days
    pos_delta_abs = abs(position.delta) if position.delta is not None else None

    should_roll = (pos_dte <= 21) or (pos_delta_abs is not None and pos_delta_abs > 0.40)
    if not should_roll:
        return []

    risk = get_effective_risk()
    leg_cfg = (
        risk["covered_call"] if position.right == OptionRight.CALL else risk["cash_secured_put"]
    )
    income_cfg = risk["income"]

    delta_min: float = leg_cfg["delta_min"]
    delta_max: float = leg_cfg["delta_max"]
    dte_min: int = leg_cfg["dte_min"]
    dte_max: int = leg_cfg["dte_max"]

    contracts = abs(int(position.position))
    if contracts < 1:
        return []

    current_mid = _infer_current_mid(position, quotes)
    underlying = position.underlying or position.symbol

    candidates: list[TradeCandidate] = []

    for quote in quotes:
        if quote.right != position.right:
            continue
        if quote.expiry <= position.expiry:
            continue
        if quote.delta is None:
            continue
        delta_abs = abs(quote.delta)
        if not (delta_min <= delta_abs <= delta_max):
            continue
        new_dte = quote.dte
        if not (dte_min <= new_dte <= dte_max):
            continue
        new_mid = quote.mid
        if new_mid is None or new_mid <= 0:
            continue
        if not passes_liquidity_gates(quote):
            continue

        if current_mid is None:
            continue
        roll_credit = new_mid - current_mid
        if roll_credit <= 0:
            continue

        # Collateral = strike price × 100 × contracts (the cash actually at risk,
        # not the entry premium received which is ~100× smaller and produces
        # fictitious 60%+ ROC figures).
        if position.right == OptionRight.PUT:
            collateral = quote.strike * contracts * 100
            roc_basis = quote.strike  # put: ROC = credit / strike (% of collateral at risk)
        else:
            # For covered call rolls, the basis is the underlying cost, which is
            # not available in this function — use strike as a conservative proxy.
            collateral = quote.strike * contracts * 100
            roc_basis = quote.strike
        roc_pct = (roll_credit / roc_basis) * 100 if roc_basis > 0 else 0.0
        annualized_yield_pct = roc_pct * (365 / new_dte) if new_dte > 0 else 0.0

        if roc_pct < income_cfg["min_roc_pct"]:
            continue
        if annualized_yield_pct < income_cfg["min_annualized_yield_pct"]:
            continue

        breakeven = (
            quote.strike - roll_credit
            if position.right == OptionRight.PUT
            else quote.strike + roll_credit
        )

        scores = ScoreCard(
            symbol=underlying,
            iv_score=iv_stats.iv_rank if iv_stats.iv_rank is not None else 0.0,
            technical_score=technical_score(quote, tech_stats),
            fundamental_score=0.0,
            liquidity_score=score_liquidity(quote),
            assignment_safety_score=(1 - delta_abs) * 100,
        )

        candidates.append(
            TradeCandidate(
                candidate_id=make_candidate_id(
                    Strategy.ROLL, underlying, quote.right, quote.strike, quote.expiry
                ),
                strategy=Strategy.ROLL,
                underlying=underlying,
                right=quote.right,
                strike=quote.strike,
                expiry=quote.expiry,
                contracts=contracts,
                premium=round(roll_credit, 4),
                collateral=collateral,
                roc_pct=round(roc_pct, 4),
                annualized_yield_pct=round(annualized_yield_pct, 4),
                breakeven=round(breakeven, 4),
                prob_otm=round(1 - delta_abs, 4),
                delta=quote.delta,
                iv_rank=iv_stats.iv_rank,
                dte=new_dte,
                scores=scores,
                price_source=tech_stats.price_source,
                greeks_source=quote.greeks_source,
            )
        )

    candidates.sort(key=lambda c: c.roc_pct, reverse=True)
    return candidates


def _infer_current_mid(position: PositionSnapshot, quotes: list[OptionQuote]) -> float | None:
    """Find the current mid of the existing short by matching its contract in the chain.

    Returns None when no live quote is found — the caller must skip the candidate
    rather than use the stale entry cost, which would produce a misleadingly high
    roll credit on a challenged position.
    """
    for q in quotes:
        if (
            q.right == position.right
            and q.strike == position.strike
            and q.expiry == position.expiry
        ):
            m = q.mid
            if m is not None:
                return m
    return None
