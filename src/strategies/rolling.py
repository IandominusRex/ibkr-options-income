"""Generate roll candidates for existing short option positions."""

from __future__ import annotations

from src.analytics.fair_value import compute_ideal_zone, zone_for_contract
from src.analytics.liquidity import passes_liquidity_gates, score_liquidity
from src.common.config import get_config
from src.common.market_hours import today_et
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
from src.strategies._scoring import make_candidate_id, technical_score


def generate_roll_candidates(
    position: PositionSnapshot,
    quotes: list[OptionQuote],
    iv_stats: IVStats,
    tech_stats: TechnicalStats,
    *,
    defensive: bool = False,
) -> list[TradeCandidate]:
    """Return ranked roll candidates for the given short option *position*.

    Rolls are only generated when DTE <= 21 (nearing expiry) or |delta| > 0.40
    (delta drift). The intraday monitor (Phase 8) handles real-time triggering;
    this function just produces the candidates when asked.

    Two economics, deliberately separated (D4). An **income** roll rolls an unchallenged
    position forward for a credit and must clear the ROC/yield gates. A **defensive** roll
    rescues a challenged short and is judged on risk reduction instead: it may cost a bounded
    debit and must materially reduce |delta|. Requiring 1% ROC from a defensive roll meant the
    candidate list was empty exactly when the monitor fired, because a 0.60-delta short cannot
    be rolled to a 0.30-delta strike for a credit.
    """
    if position.position >= 0:
        return []
    if position.right is None or position.expiry is None or position.strike is None:
        return []

    pos_dte = (position.expiry - today_et()).days
    pos_delta_abs = abs(position.delta) if position.delta is not None else None

    should_roll = (pos_dte <= 21) or (pos_delta_abs is not None and pos_delta_abs > 0.40)
    if not should_roll:
        return []

    risk = get_config().risk
    leg_cfg = (
        risk["covered_call"] if position.right == OptionRight.CALL else risk["cash_secured_put"]
    )
    income_cfg = risk["income"]
    roll_cfg = get_config().monitor.roll_defensive if defensive else {}

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
    # The ideal zone depends on (symbol, right, DTE) — not on the strike — so memoize per
    # expiry rather than recomputing it for every quote, matching the CSP/CC generators.
    zones: dict[int, IdealZone] = {}

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

        if defensive:
            max_debit = float(roll_cfg.get("max_debit", 0.50))
            min_reduction = float(roll_cfg.get("min_delta_reduction", 0.10))
            require_be = bool(roll_cfg.get("require_breakeven_improvement", True))
            if roll_credit < -max_debit:
                continue
            if pos_delta_abs is None or (pos_delta_abs - delta_abs) < min_reduction:
                continue
            if require_be and position.strike is not None:
                improves = (
                    quote.strike < position.strike
                    if position.right == OptionRight.PUT
                    else quote.strike > position.strike
                )
                if not improves and roll_credit <= 0:
                    continue
            roc_pct = 0.0
            annualized_yield_pct = 0.0
        else:
            if roll_credit <= 0:
                continue
            roc_basis = quote.strike
            roc_pct = (roll_credit / roc_basis) * 100 if roc_basis > 0 else 0.0
            annualized_yield_pct = roc_pct * (365 / new_dte) if new_dte > 0 else 0.0
            if roc_pct < income_cfg["min_roc_pct"]:
                continue
            if annualized_yield_pct < income_cfg["min_annualized_yield_pct"]:
                continue

        # Collateral = strike price × 100 × contracts (the cash actually at risk, not the
        # entry premium received which is ~100× smaller and produces fictitious 60%+ ROC
        # figures). Uses strike as the basis for both PUT and CALL rolls — for a covered-call
        # roll the underlying's actual cost basis is not available in this function.
        collateral = quote.strike * contracts * 100

        # D2 follow-up: populate `ideal` so the risk engine's variance-risk-premium gate
        # (which reads `TradeCandidate.ideal.min_credit`, not anything roll-specific) covers
        # rolls too — without this, `cand.ideal` defaulted to None and the gate could never
        # fire for a ROLL, leaving the lowered 0.15%/0.0% noise floors as the only check.
        # No fundamentals are available in this function (no `FundamentalStats` input), so a
        # minimal symbol-only instance is used — `zone_for_contract`'s min_credit depends only
        # on `zone.spot`/`zone.dte`/`zone.right` (set from this call's own args, never touched
        # by `fund`) and the strike passed in below, never on fundamentals.
        zone = zones.get(new_dte)
        if zone is None:
            zone = compute_ideal_zone(
                symbol=underlying,
                right=position.right,
                dte=new_dte,
                spot=tech_stats.price,
                tech=tech_stats,
                iv=iv_stats,
                fund=FundamentalStats(symbol=underlying),
            )
            zones[new_dte] = zone
        # No cost_basis: this function has no access to the underlying's stock cost basis for
        # a covered-call roll (same limitation as `roc_basis` above), so `min_credit_for` falls
        # back to strike for both PUT and CALL rolls, consistent with the ROC treatment above.
        contract_zone = zone_for_contract(zone, quote.strike, iv_stats)

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
                ideal=contract_zone,
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
