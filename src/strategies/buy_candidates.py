"""Score stocks from the would_own universe as candidates to buy for future covered calls.

These are not option trades — they are stock purchase recommendations based on how attractive
the symbol is as a CC platform: high IV rank (premium potential), quality fundamentals, and
a non-bearish technical regime. Symbols already held as long positions are excluded.
"""

from __future__ import annotations

import logging

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


def generate_buy_candidates(
    universe_symbols: list[str],
    holdings_symbols: set[str],
    analytics: dict[str, tuple[IVStats, TechnicalStats, FundamentalStats]],
) -> list[BuyCandidate]:
    """Return scored BuyCandidate list for symbols worth buying to eventually sell CCs against.

    Args:
        universe_symbols: Symbols from config universe.would_own.
        holdings_symbols: Symbols already held as long stock positions (excluded).
        analytics: Mapping symbol → (IVStats, TechnicalStats, FundamentalStats).

    Returns:
        List sorted by score DESC.
    """
    candidates: list[BuyCandidate] = []

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

        candidates.append(
            BuyCandidate(
                symbol=symbol,
                score=blended,
                iv_rank=iv_stats.iv_rank,
                quality_flag=fund_stats.quality_flag,
                technical_regime=tech_stats.regime.value if tech_stats.regime else None,
            )
        )

    candidates.sort(key=lambda c: c.score, reverse=True)
    log.info(
        "buy_candidates: %d candidates from %d universe symbols",
        len(candidates),
        len(universe_symbols),
    )
    return candidates
