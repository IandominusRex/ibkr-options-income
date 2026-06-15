"""Score stocks from the would_own universe as candidates to buy for future covered calls.

These are not option trades — they are stock purchase recommendations based on how attractive
the symbol is as a CC platform: high IV rank (premium potential), quality fundamentals, and
a non-bearish technical regime. Symbols already held as long positions are excluded.
"""

from __future__ import annotations

import logging
import math
from datetime import date

from src.common.config import get_config
from src.common.schemas import (
    BuyCandidate,
    FundamentalStats,
    IVStats,
    Regime,
    TechnicalStats,
)

log = logging.getLogger(__name__)

# Scoring weights must sum to 1.0
_W_IV = 0.40
_W_FUND = 0.30
_W_TECH = 0.30

# Fallbacks if scoring_weights.yaml has no `buy_to_own:` block.
_DEFAULT_MIN_SCORE = 60.0
_DEFAULT_MAX_CANDIDATES = 8

# Heuristic for the estimated ~30-delta, 30-DTE covered-call premium as a fraction of spot:
#   premium/price ≈ k · IV · √(DTE/365)
# k≈0.3 is a rough Black-Scholes-ish factor for a moderately OTM monthly call. This is a
# "premium potential" indicator for ranking/affording context — NOT a quotable price.
_CC_PREMIUM_K = 0.30
_CC_DTE = 30


def _iv_sub_score(iv_stats: IVStats) -> float:
    """Higher IV rank = better CC premium potential. Range 0–100."""
    rank = iv_stats.iv_rank
    if rank is None:
        return 40.0  # neutral when unknown
    return float(rank)


def _fundamental_sub_score(fund_stats: FundamentalStats) -> float:
    """Quality fundamentals — binary quality flag plus bonus for dividend safety."""
    score = 0.0
    if fund_stats.quality_flag is True:
        score += 70.0
    elif fund_stats.quality_flag is False:
        score += 20.0
    else:
        score += 50.0  # unknown

    if fund_stats.dividend_safe is True:
        score = min(100.0, score + 20.0)
    elif fund_stats.dividend_safe is False:
        score = max(0.0, score - 10.0)

    return round(score, 2)


def _technical_sub_score(tech_stats: TechnicalStats) -> float:
    """Penalise bearish regimes; reward bullish and sideways for CC selling."""
    regime = tech_stats.regime
    if regime is None:
        return 50.0
    if regime == Regime.BEARISH:
        return 10.0  # bad CC environment — high assignment risk on puts, CC premium thin
    if regime == Regime.BULLISH:
        return 80.0  # ideal: stock trends up, CC premium reasonable
    if regime == Regime.SIDEWAYS:
        return 75.0  # ideal for income: stock flat, CC premium decays to zero
    if regime == Regime.HIGH_VOL:
        return 70.0  # great premium but volatile
    if regime == Regime.LOW_VOL:
        return 40.0  # thin premium
    return 50.0


def _est_monthly_cc_yield(iv_stats: IVStats) -> float | None:
    """Estimated ~30-delta, 30-DTE covered-call premium as a fraction of spot (heuristic)."""
    iv = iv_stats.current_iv
    if iv is None or iv <= 0:
        return None
    # current_iv is in percent (72.1 = 72.1%); convert to a fraction before scaling.
    return round(_CC_PREMIUM_K * (iv / 100.0) * math.sqrt(_CC_DTE / 365.0), 4)


def _days_to_earnings(fund_stats: FundamentalStats) -> int | None:
    if fund_stats.next_earnings is None:
        return None
    return (fund_stats.next_earnings - date.today()).days


def _build_rationale(
    iv_stats: IVStats,
    tech_stats: TechnicalStats,
    fund_stats: FundamentalStats,
) -> str:
    """Deterministic one-line thesis from the screen's own signals.

    Replaces the old Claude-filled rationale: the Claude review only enriches option
    candidates (the `top` list), never these buy-to-own names, so the field was always
    empty in this path. This keeps the message self-explanatory without an LLM call.
    """
    bits: list[str] = []

    rank = iv_stats.iv_rank
    if rank is not None:
        if rank >= 70:
            bits.append(f"rich premium (IV rank {rank:.0f})")
        elif rank >= 40:
            bits.append(f"moderate premium (IV rank {rank:.0f})")
        else:
            bits.append(f"thin premium (IV rank {rank:.0f})")

    if iv_stats.vrp is not None and iv_stats.vrp > 0:
        bits.append(f"options rich vs realised (VRP +{iv_stats.vrp:.1f}pts)")

    regime = tech_stats.regime
    if regime == Regime.BULLISH:
        bits.append("uptrend")
    elif regime == Regime.SIDEWAYS:
        bits.append("range-bound (ideal for income)")
    elif regime == Regime.HIGH_VOL:
        bits.append("high-volatility regime")
    elif regime == Regime.LOW_VOL:
        bits.append("calm regime")

    if fund_stats.quality_flag is True:
        bits.append("passes quality")
    elif fund_stats.quality_flag is False:
        bits.append("fails quality screen")

    dte = _days_to_earnings(fund_stats)
    if dte is not None and 0 <= dte <= 14:
        bits.append(f"earnings in {dte}d — size cautiously")

    return "; ".join(bits).capitalize() + "." if bits else ""


def generate_buy_candidates(
    universe_symbols: list[str],
    holdings_symbols: set[str],
    analytics: dict[str, tuple[IVStats, TechnicalStats, FundamentalStats]],
    *,
    min_score: float | None = None,
    max_candidates: int | None = None,
) -> list[BuyCandidate]:
    """Return scored BuyCandidate list for symbols worth buying to eventually sell CCs against.

    Args:
        universe_symbols: Symbols from config universe.would_own.
        holdings_symbols: Symbols already held as long stock positions (excluded).
        analytics: Mapping symbol → (IVStats, TechnicalStats, FundamentalStats).
        min_score: Minimum blended score to surface. Defaults to
            ``scoring_weights.yaml → buy_to_own.min_score`` (or 60). Without this floor the
            screen returned *every* non-held, non-bearish universe name (e.g. 46/46 over a
            weekend), making the count meaningless.
        max_candidates: Hard cap on the returned list. Defaults to
            ``scoring_weights.yaml → buy_to_own.max_candidates`` (or 8).

    Returns:
        List sorted by score DESC, filtered to score ≥ min_score and capped at max_candidates.
    """
    if min_score is None or max_candidates is None:
        buy_cfg = get_config().weights.get("buy_to_own", {})
        if min_score is None:
            min_score = float(buy_cfg.get("min_score", _DEFAULT_MIN_SCORE))
        if max_candidates is None:
            max_candidates = int(buy_cfg.get("max_candidates", _DEFAULT_MAX_CANDIDATES))

    candidates: list[BuyCandidate] = []
    below_floor = 0

    for symbol in universe_symbols:
        if symbol in holdings_symbols:
            continue  # already owned; covered-call strategy handles these

        entry = analytics.get(symbol)
        if entry is None:
            log.debug("buy_candidates: no analytics for %s — skipping", symbol)
            continue
        iv_stats, tech_stats, fund_stats = entry

        # Skip bearish regime outright — adding shares into a downtrend is undesirable.
        if tech_stats.regime == Regime.BEARISH:
            log.debug("buy_candidates: %s regime is BEARISH — skipping", symbol)
            continue

        iv_score = _iv_sub_score(iv_stats)
        fund_score = _fundamental_sub_score(fund_stats)
        tech_score = _technical_sub_score(tech_stats)

        blended = round(_W_IV * iv_score + _W_FUND * fund_score + _W_TECH * tech_score, 2)

        # Score floor: only surface names that clear the quality bar.
        if blended < min_score:
            below_floor += 1
            continue

        candidates.append(
            BuyCandidate(
                symbol=symbol,
                score=blended,
                iv_rank=iv_stats.iv_rank,
                quality_flag=fund_stats.quality_flag,
                technical_regime=tech_stats.regime.value if tech_stats.regime else None,
                rationale=_build_rationale(iv_stats, tech_stats, fund_stats),
                price=tech_stats.price or None,
                current_iv=iv_stats.current_iv,
                hv_30=iv_stats.hv_30,
                vrp=iv_stats.vrp,
                rsi_14=tech_stats.rsi_14,
                sma_50=tech_stats.sma_50,
                sma_200=tech_stats.sma_200,
                next_earnings=fund_stats.next_earnings,
                dividend_yield=fund_stats.dividend_yield,
                est_monthly_cc_yield=_est_monthly_cc_yield(iv_stats),
                iv_score=iv_score,
                fundamental_score=fund_score,
                technical_score=tech_score,
            )
        )

    candidates.sort(key=lambda c: c.score, reverse=True)
    capped = candidates[:max_candidates]
    log.info(
        "buy_candidates: %d candidates (>= %.0f) from %d universe symbols "
        "(%d below floor); surfacing %d",
        len(candidates),
        min_score,
        len(universe_symbols),
        below_floor,
        len(capped),
    )
    return capped
