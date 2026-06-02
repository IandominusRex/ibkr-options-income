"""Generate cash-secured put candidates filtered to the would_own allowlist."""

from __future__ import annotations

from src.analytics.liquidity import passes_liquidity_gates, score_liquidity
from src.common.config import get_config
from src.common.schemas import (
    AccountSnapshot,
    FundamentalStats,
    IVStats,
    OptionQuote,
    OptionRight,
    ScoreCard,
    Strategy,
    TechnicalStats,
    TradeCandidate,
)
from src.strategies._scoring import fundamental_score, make_candidate_id, technical_score


def generate_csp_candidates(
    symbol: str,
    quotes: list[OptionQuote],
    account: AccountSnapshot,
    iv_stats: IVStats,
    tech_stats: TechnicalStats,
    fund_stats: FundamentalStats,
) -> list[TradeCandidate]:
    """Return ranked CSP candidates for *symbol*.

    Returns [] immediately when *symbol* is not in the would_own allowlist.
    Contract count is sized by available buying power, capped by config.
    """
    cfg = get_config()
    if symbol not in cfg.universe["would_own"]:
        return []

    csp_cfg = cfg.risk["cash_secured_put"]
    income_cfg = cfg.risk["income"]
    portfolio_cfg = cfg.risk.get("portfolio", {})

    delta_min: float = csp_cfg["delta_min"]
    delta_max: float = csp_cfg["delta_max"]
    dte_min: int = csp_cfg["dte_min"]
    dte_max: int = csp_cfg["dte_max"]
    max_contracts: int = csp_cfg.get("max_contracts", 10)
    # Total CSP collateral budget (% of net liq). Sizing a single CSP to this ceiling keeps
    # it from blowing the whole cap by itself — which would make the cumulative risk gate
    # reject it outright (the gate rejects, it does not trim) and yield zero fills.
    max_csp_pct: float = portfolio_cfg.get("max_csp_allocation_pct", 60.0)

    candidates: list[TradeCandidate] = []

    for quote in quotes:
        if quote.right != OptionRight.PUT:
            continue
        if quote.delta is None:
            continue
        delta_abs = abs(quote.delta)
        if not (delta_min <= delta_abs <= delta_max):
            continue
        dte = quote.dte
        if not (dte_min <= dte <= dte_max):
            continue
        mid = quote.mid
        if mid is None or mid <= 0:
            continue
        if not passes_liquidity_gates(quote):
            continue

        # Size off ExcessLiquidity (the post-margin-requirement cushion) rather than
        # TotalCashValue, which can overstate available capacity for margin accounts
        # because it includes premium received on existing short puts without deducting
        # the reserved collateral. Also bound a single CSP to the total-CSP budget so
        # it cannot, on its own, exceed the cumulative cap (which the risk engine would
        # then reject rather than trim).
        per_contract = quote.strike * 100
        if per_contract <= 0:
            continue
        cash_n = int(account.excess_liquidity // per_contract)
        csp_budget_n = int((account.net_liquidation * max_csp_pct / 100) // per_contract)
        contracts = min(max_contracts, cash_n, csp_budget_n)
        if contracts < 1:
            # Not enough cash/budget to secure even one contract — skip rather than fake a 1-lot.
            continue
        collateral = quote.strike * contracts * 100
        roc_pct = (mid / quote.strike) * 100
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
            assignment_safety_score=(1 - delta_abs) * 100,
        )

        candidates.append(
            TradeCandidate(
                candidate_id=make_candidate_id(
                    Strategy.CASH_SECURED_PUT, symbol, quote.right, quote.strike, quote.expiry
                ),
                strategy=Strategy.CASH_SECURED_PUT,
                underlying=symbol,
                right=quote.right,
                strike=quote.strike,
                expiry=quote.expiry,
                contracts=contracts,
                premium=mid,
                collateral=collateral,
                roc_pct=round(roc_pct, 4),
                annualized_yield_pct=round(annualized_yield_pct, 4),
                breakeven=round(quote.strike - mid, 4),
                prob_profit=round(1 - delta_abs, 4),
                delta=quote.delta,
                iv_rank=iv_stats.iv_rank,
                dte=dte,
                next_earnings=fund_stats.next_earnings,
                scores=scores,
            )
        )

    candidates.sort(key=lambda c: c.roc_pct, reverse=True)
    return candidates
