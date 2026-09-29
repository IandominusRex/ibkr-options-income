"""Generate covered-call candidates from existing long stock positions."""

from __future__ import annotations

import logging
import math

from src.analytics.fair_value import compute_ideal_zone, zone_for_contract
from src.analytics.liquidity import (
    liquidity_failures,
    score_liquidity,
    volume_gate_active,
)
from src.common.config import get_config
from src.common.schemas import (
    FundamentalStats,
    IdealZone,
    IVStats,
    OptionQuote,
    OptionRight,
    PositionSnapshot,
    ScoreCard,
    Strategy,
    TechnicalStats,
    TradeCandidate,
)
from src.storage.campaigns import adjusted_cost_basis_for
from src.strategies._evaluation import (
    REASON_BELOW_BASIS,
    REASON_BELOW_FAIR_VALUE,
    REASON_DELTA_MISSING,
    REASON_DELTA_RANGE,
    REASON_DTE_RANGE,
    REASON_NO_MARKET,
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


def uncovered_call_capacity(positions: list[PositionSnapshot], underlying: str) -> int:
    """How many *fresh* call contracts *underlying*'s current book can cover right now.

    ``floor(long shares / 100) - existing short calls`` — the exact sizing formula
    ``screen_cc_candidates`` uses, extracted so a caller that only needs the number (not a
    full screen) doesn't re-derive it. Used both at scan time (indirectly, via
    ``screen_cc_candidates``) and at execution time by ``execution.approval.process_queued_orders``,
    which re-checks a queued covered call against a **fresh** position snapshot immediately
    before sending it — shares sold (manually, or by an assignment the reconciler hasn't
    caught yet) between scan and execution must not result in a naked call.
    """
    shares = sum(
        p.position
        for p in positions
        if (p.underlying or p.symbol) == underlying and p.sec_type == "STK" and p.position > 0
    )
    existing_short_calls = sum(
        int(abs(p.position))
        for p in positions
        if (p.underlying or p.symbol) == underlying
        and p.sec_type == "OPT"
        and p.right == OptionRight.CALL
        and p.position < 0
    )
    return math.floor(shares / 100) - max(0, existing_short_calls)


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

    Thin wrapper over :func:`screen_cc_candidates` for callers that only want the passing
    slate. Returns [] when position is short/zero, all shares are already covered, or no
    quotes pass filters.
    """
    return screen_cc_candidates(
        symbol, quotes, position, iv_stats, tech_stats, fund_stats, existing_short_calls
    ).passed


def screen_cc_candidates(
    symbol: str,
    quotes: list[OptionQuote],
    position: PositionSnapshot,
    iv_stats: IVStats,
    tech_stats: TechnicalStats,
    fund_stats: FundamentalStats,
    existing_short_calls: int = 0,
) -> ScreenResult:
    """Screen *symbol*'s call chain, returning both the passing and the rejected contracts.

    *existing_short_calls* is the number of call contracts already written against this
    underlying (sum of |position| over short OPT/CALL legs). Sizing nets these out so we
    only ever propose calls covered by *uncovered* shares — without this, a re-scan (and
    especially the 15-min automated loop) would regenerate the full-share-count CC every
    cycle and stack writes on top of already-written calls, ending in naked short calls.

    Every quote is evaluated against **all** gates rather than short-circuiting on the first
    failure, so a rejected contract carries the complete list of what stood in its way.
    """
    result = ScreenResult()
    if position.position <= 0:
        result.skipped = "no_long_shares"
        return result

    owned_contracts = math.floor(abs(position.position) / 100)
    contracts = owned_contracts - max(0, existing_short_calls)
    if contracts < 1:
        result.skipped = "shares_already_covered" if owned_contracts else "under_one_round_lot"
        return result

    # Prefer the wheel-adjusted basis: after a CSP assignment the real basis is the assignment
    # price less the premium already collected on this campaign (D5) — without it, the gate
    # below compares strikes to IBKR's raw avg_cost and refuses strikes that are genuinely
    # profitable on the campaign. Falls back to avg_cost for shares bought outright.
    basis = adjusted_cost_basis_for(symbol) or position.avg_cost

    risk = get_config().risk
    cc_cfg = risk["covered_call"]
    income_cfg = risk["income"]
    # Task 9 (R7): a missing IV rank already passes the IV gate as "data unavailable" —
    # scoring it 0 under IV's 30% weight silently sank the candidate instead. Score the
    # neutral value from config (default 50) and tag the card so the gap stays visible.
    missing_iv_rank_score: float = get_config().weights.get("missing_iv_rank_score", 50.0)

    delta_min: float = cc_cfg["delta_min"]
    delta_max: float = cc_cfg["delta_max"]
    dte_min: int = cc_cfg["dte_min"]
    dte_max: int = cc_cfg["dte_max"]
    min_strike_vs_basis: float = cc_cfg.get("min_strike_vs_basis", 1.00)

    enforce_volume = volume_gate_active()  # N19: skip the volume gate before the morning cutoff
    rejected: list[tuple[TradeCandidate, list[str]]] = []
    # The ideal zone depends on (symbol, right, DTE) — not on the strike — so memoize per
    # expiry rather than recomputing it for every strike in the chain.
    zones: dict[int, IdealZone] = {}

    for quote in quotes:
        if quote.right != OptionRight.CALL:
            continue
        result.evaluated += 1
        reasons: list[str] = []

        delta = abs(quote.delta) if quote.delta is not None else None
        if delta is None:
            reasons.append(REASON_DELTA_MISSING)
        elif not (delta_min <= delta <= delta_max):
            reasons.append(REASON_DELTA_RANGE)

        dte = quote.dte
        if not (dte_min <= dte <= dte_max):
            reasons.append(REASON_DTE_RANGE)

        # Require a genuine two-sided market (N10): never price a candidate off a stale `last`.
        strict = quote.strict_mid
        if strict is None or strict <= 0:
            reasons.append(REASON_NO_MARKET)
        reasons.extend(liquidity_failures(quote, enforce_volume=enforce_volume))

        # Drawdown-CC policy (N18, explicit decision): with the default `min_strike_vs_basis: 1.00`
        # a strike below cost basis is rejected — so an *underwater* holding generates no covered
        # calls (writing below basis would lock in a loss if assigned). This is deliberate: it
        # favours not capping the recovery over squeezing income from a loser. To allow below-basis
        # writes (e.g. to keep harvesting premium on a long-term hold), lower the knob in
        # risk_limits.yaml (e.g. 0.95 permits strikes down to 5% below basis).
        if quote.strike < basis * min_strike_vs_basis:
            reasons.append(REASON_BELOW_BASIS)

        # Price the contract for display even when it failed above; the reasons list tells the
        # reader how much to trust it.
        mid = display_premium(strict, quote.mid, quote.last)

        collateral = basis * contracts * 100  # full capital at risk for all contracts
        # ROC is deliberately measured against the cost basis — the wheel-adjusted basis when a
        # campaign exists, else IBKR's avg_cost — i.e. return on the capital actually tied up in
        # the shares you own — not the current market price. For a name that has run up this
        # understates yield-on-market-value, which is the conservative choice for an income
        # screen (you don't want the run-up to inflate the apparent yield).
        roc_pct = (mid / basis) * 100 if basis > 0 else 0.0
        annualized_yield_pct = roc_pct * (365 / dte) if dte > 0 else 0.0

        if roc_pct < income_cfg["min_roc_pct"]:
            reasons.append(REASON_ROC)
        if annualized_yield_pct < income_cfg["min_annualized_yield_pct"]:
            reasons.append(REASON_YIELD)

        zone = zones.get(dte)
        if zone is None:
            zone = compute_ideal_zone(
                symbol=symbol,
                right=OptionRight.CALL,
                dte=dte,
                spot=tech_stats.price,
                tech=tech_stats,
                iv=iv_stats,
                fund=fund_stats,
                cost_basis=basis,
            )
            zones[dte] = zone

        # Re-price the credit floor at this contract's strike (the band itself is shared
        # across strikes at this DTE) so the card compares like with like, and so the VRP
        # gate below and the displayed `ideal` agree on the same number.
        contract_zone = zone_for_contract(zone, quote.strike, iv_stats, cost_basis=basis)
        if income_cfg.get("require_vrp_edge", True):
            floor = contract_zone.min_credit
            if floor is not None and floor > 0 and mid < floor:
                reasons.append(REASON_BELOW_FAIR_VALUE)

        scores = ScoreCard(
            symbol=symbol,
            iv_score=iv_stats.iv_rank if iv_stats.iv_rank is not None else missing_iv_rank_score,
            technical_score=technical_score(quote, tech_stats, zone),
            fundamental_score=fundamental_score(fund_stats),
            liquidity_score=score_liquidity(quote),
            assignment_safety_score=(1 - delta) * 100 if delta is not None else 0.0,
            relative_strength=relative_strength_score(tech_stats.relative_strength),
        )

        candidate = TradeCandidate(
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
            breakeven=round(basis - mid, 4),
            prob_otm=round(1 - delta, 4) if delta is not None else None,
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
                "data-feed outage suspected for %s: none of %d call quotes had a live bid/ask "
                "this cycle — treat the illiquid_no_quote/no_two_sided_market tally below as an "
                "IBKR market-data gap, not genuine illiquidity",
                symbol,
                result.evaluated,
            )
        tally = interim.tally()
        log.warning(
            "No CC candidates passed filters for %s (%d call quotes evaluated) — rejections: %s "
            "(limits: %s)",
            symbol,
            result.evaluated,
            ", ".join(f"{k}={v}" for k, v in sorted(tally.items())) or "none",
            liquidity_limits_summary(enforce_volume=enforce_volume),
        )

    result.passed.sort(key=lambda c: c.roc_pct, reverse=True)
    result.rejected = rank_rejects(rejected, delta_mid=(delta_min + delta_max) / 2)
    return result
