"""Generate cash-secured put candidates filtered to the would_own allowlist."""

from __future__ import annotations

import logging

from src.analytics.fair_value import compute_ideal_zone, zone_for_contract
from src.analytics.liquidity import (
    liquidity_failures,
    score_liquidity,
    volume_gate_active,
)
from src.common.config import get_config
from src.common.schemas import (
    AccountSnapshot,
    FundamentalStats,
    IdealZone,
    IVStats,
    OptionQuote,
    OptionRight,
    Phase,
    PositionSnapshot,
    ScoreCard,
    Strategy,
    TechnicalStats,
    TradeCandidate,
)
from src.common.universe import effective_universe
from src.engine.capital import Budgets, max_contracts, resolve_caps, seed_budgets
from src.strategies._evaluation import (
    REASON_BELOW_FAIR_VALUE,
    REASON_DELTA_MISSING,
    REASON_DELTA_RANGE,
    REASON_DTE_RANGE,
    REASON_INSUFFICIENT_CASH,
    REASON_NO_HEADROOM,
    REASON_NO_MARKET,
    REASON_PHASE_DOWNTREND,
    REASON_ROC,
    REASON_YIELD,
    ScreenResult,
    display_premium,
    liquidity_limits_summary,
    rank_rejects,
)
from src.strategies._scoring import (
    fundamental_score,
    make_candidate_id,
    relative_strength_score,
    technical_score,
)

log = logging.getLogger(__name__)


def generate_csp_candidates(
    symbol: str,
    quotes: list[OptionQuote],
    account: AccountSnapshot,
    iv_stats: IVStats,
    tech_stats: TechnicalStats,
    fund_stats: FundamentalStats,
) -> list[TradeCandidate]:
    """Return ranked CSP candidates for *symbol*.

    Thin wrapper over :func:`screen_csp_candidates` for callers that only want the passing
    slate. Returns [] immediately when *symbol* is not in the would_own allowlist.
    """
    return screen_csp_candidates(symbol, quotes, account, iv_stats, tech_stats, fund_stats).passed


def screen_csp_candidates(
    symbol: str,
    quotes: list[OptionQuote],
    account: AccountSnapshot,
    iv_stats: IVStats,
    tech_stats: TechnicalStats,
    fund_stats: FundamentalStats,
    *,
    positions: list[PositionSnapshot] | None = None,
) -> ScreenResult:
    """Screen *symbol*'s put chain, returning both the passing and the rejected contracts.

    Every quote is evaluated against **all** gates rather than short-circuiting on the first
    failure, so a rejected contract carries the complete list of what stood in its way and
    can be ranked by how close it came. Contract count is sized to the largest lot that fits
    every cash/concentration constraint (``engine.capital.max_contracts``) rather than to the
    maximum affordable lot — the same helper the risk gate uses, so the two can never disagree
    about how big a position may be. *positions* seeds the running budgets from what the
    account already holds; omit it (or pass ``[]``) to size against an empty portfolio.
    """
    cfg = get_config()
    result = ScreenResult()
    if symbol not in effective_universe()["would_own"]:
        result.skipped = "not_in_would_own"
        return result

    risk = get_config().risk
    csp_cfg = risk["cash_secured_put"]
    income_cfg = risk["income"]
    # Task 9 (R7): a missing IV rank already passes the IV gate as "data unavailable" —
    # scoring it 0 under IV's 30% weight silently sank the candidate instead. Score the
    # neutral value from config (default 50) and tag the card so the gap stays visible.
    missing_iv_rank_score: float = cfg.weights.get("missing_iv_rank_score", 50.0)

    delta_min: float = csp_cfg["delta_min"]
    delta_max: float = csp_cfg["delta_max"]
    dte_min: int = csp_cfg["dte_min"]
    dte_max: int = csp_cfg["dte_max"]
    hard_max: int = csp_cfg.get("max_contracts", 10)
    caps = resolve_caps(account, risk)
    sector_of = cfg.universe.get("sectors", {}).get
    budgets: Budgets = seed_budgets(positions or [], sector_of, caps=caps)
    sector = sector_of(symbol)

    enforce_volume = volume_gate_active()  # N19: skip the volume gate before the morning cutoff
    rejected: list[tuple[TradeCandidate, list[str]]] = []
    # The ideal zone depends on (symbol, right, DTE) — not on the strike — so memoize per
    # expiry rather than recomputing it for every strike in the chain.
    zones: dict[int, IdealZone] = {}

    for quote in quotes:
        if quote.right != OptionRight.PUT:
            continue
        result.evaluated += 1
        reasons: list[str] = []

        delta_abs = abs(quote.delta) if quote.delta is not None else None
        if delta_abs is None:
            reasons.append(REASON_DELTA_MISSING)
        elif not (delta_min <= delta_abs <= delta_max):
            reasons.append(REASON_DELTA_RANGE)

        dte = quote.dte
        if not (dte_min <= dte <= dte_max):
            reasons.append(REASON_DTE_RANGE)

        # Require a genuine two-sided market (N10): never price a candidate off a stale `last`.
        strict = quote.strict_mid
        if strict is None or strict <= 0:
            reasons.append(REASON_NO_MARKET)
        reasons.extend(liquidity_failures(quote, enforce_volume=enforce_volume))

        # Price the contract for display even when it failed above; the reasons list tells the
        # reader how much to trust it.
        mid = display_premium(strict, quote.mid, quote.last)

        per_contract = quote.strike * 100
        if per_contract <= 0:
            continue
        # Size to the binding constraint rather than to the maximum affordable lot. The gate
        # rejects rather than trims, so proposing the max meant any position whose *largest*
        # size breached a cap was refused entirely — even when one lot fitted comfortably (D1).
        contracts, binding = max_contracts(
            unit_collateral=per_contract,
            current_iv=iv_stats.current_iv,
            dte=dte,
            symbol=symbol,
            sector=sector,
            caps=caps,
            budgets=budgets,
            hard_max=hard_max,
        )
        if contracts < 1:
            reasons.append(REASON_INSUFFICIENT_CASH if binding == "cash" else REASON_NO_HEADROOM)
            contracts = 1  # display a 1-lot; the reason records that it does not fit

        collateral = quote.strike * contracts * 100
        roc_pct = (mid / quote.strike) * 100
        annualized_yield_pct = roc_pct * (365 / dte) if dte > 0 else 0.0

        if roc_pct < income_cfg["min_roc_pct"]:
            reasons.append(REASON_ROC)
        if annualized_yield_pct < income_cfg["min_annualized_yield_pct"]:
            reasons.append(REASON_YIELD)

        zone = zones.get(dte)
        if zone is None:
            zone = compute_ideal_zone(
                symbol=symbol,
                right=OptionRight.PUT,
                dte=dte,
                spot=tech_stats.price,
                tech=tech_stats,
                iv=iv_stats,
                fund=fund_stats,
            )
            zones[dte] = zone

        # Re-price the credit floor at this contract's strike (the band itself is shared
        # across strikes at this DTE) so the card compares like with like, and so the VRP
        # gate below and the displayed `ideal` agree on the same number.
        contract_zone = zone_for_contract(zone, quote.strike, iv_stats)
        if income_cfg.get("require_vrp_edge", True):
            floor = contract_zone.min_credit
            if floor is not None and floor > 0 and mid < floor:
                reasons.append(REASON_BELOW_FAIR_VALUE)

        # Optional down‑trend reject (Phase 3). If configured, reject when market is in DOWNTREND.
        if (
            cfg.risk["cash_secured_put"].get("reject_downtrend", False)
            and tech_stats.phase == Phase.DOWNTREND
        ):
            reasons.append(REASON_PHASE_DOWNTREND)

        scores = ScoreCard(
            symbol=symbol,
            iv_score=iv_stats.iv_rank if iv_stats.iv_rank is not None else missing_iv_rank_score,
            technical_score=technical_score(quote, tech_stats, zone),
            fundamental_score=fundamental_score(fund_stats),
            liquidity_score=score_liquidity(quote),
            assignment_safety_score=(1 - delta_abs) * 100 if delta_abs is not None else 0.0,
            relative_strength=relative_strength_score(tech_stats.relative_strength),
        )

        candidate = TradeCandidate(
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
            prob_otm=round(1 - delta_abs, 4) if delta_abs is not None else None,
            delta=quote.delta,
            iv_rank=iv_stats.iv_rank,
            current_iv=iv_stats.current_iv,
            vrp=iv_stats.vrp,
            iv_rv_ratio=iv_stats.iv_rv_ratio,
            dte=dte,
            next_earnings=fund_stats.next_earnings,
            ideal=contract_zone,
            scores=scores,
            price_source=tech_stats.price_source,
            greeks_source=quote.greeks_source,
            quote_bid=quote.bid,
            quote_ask=quote.ask,
            open_interest=quote.open_interest,
            option_volume=quote.volume,
            rationale_tags=["iv_rank_unavailable"] if iv_stats.iv_rank is None else [],
        )

        if reasons:
            rejected.append((candidate, reasons))
        else:
            result.passed.append(candidate)

    if not result.passed:
        interim = ScreenResult(rejected=rejected, evaluated=result.evaluated)
        if interim.market_data_outage():
            log.warning(
                "data-feed outage suspected for %s: none of %d put quotes had a live bid/ask "
                "this cycle — treat the illiquid_no_quote/no_two_sided_market tally below as an "
                "IBKR market-data gap, not genuine illiquidity",
                symbol,
                result.evaluated,
            )
        tally = interim.tally()
        log.warning(
            "No CSP candidates passed filters for %s (%d put quotes evaluated) — rejections: %s "
            "(limits: %s)",
            symbol,
            result.evaluated,
            ", ".join(f"{k}={v}" for k, v in sorted(tally.items())) or "none",
            liquidity_limits_summary(enforce_volume=enforce_volume),
        )

    result.passed.sort(key=lambda c: c.roc_pct, reverse=True)
    result.rejected = rank_rejects(rejected, delta_mid=(delta_min + delta_max) / 2)
    return result
