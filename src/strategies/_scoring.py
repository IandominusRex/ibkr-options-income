"""Shared scoring helpers used by all strategy modules."""

from __future__ import annotations

import hashlib
from datetime import date

from src.common.schemas import FundamentalStats, OptionQuote, OptionRight, Regime, TechnicalStats


def make_candidate_id(
    strategy: str, underlying: str, right: str, strike: float, expiry: date
) -> str:
    """Stable identity for a contract+strategy.

    Composed from ``strategy|underlying|right|strike|expiry`` — deliberately **date-free**.
    The scan date is *not* part of the id: this is the property that lets the 15-minute scan
    loop regenerate the exact same id every cycle, so ``has_active_order`` can dedupe and the
    auto-queue path never stacks duplicate positions on a re-scan. The trade-off is that the
    approved *payload* (contracts, premium) may drift between re-scans — that drift is handled
    separately by freezing the approved snapshot onto the Approval/Order row at approval time
    (N2a), not by encoding the date here.
    """
    key = f"{strategy}|{underlying}|{right}|{strike}|{expiry}"
    return hashlib.sha1(key.encode()).hexdigest()[:16]


def technical_score(quote: OptionQuote, tech: TechnicalStats) -> float:
    """Regime alignment for **short** premium (we are *selling* these options).

    A short call (covered call) profits when the underlying stays flat or falls; a short put
    (cash-secured put) profits when it stays flat or rises. So the favourable regime is the
    one working *against the long side of the contract we wrote* — the opposite of how regime
    would align for someone *buying* the option:

      * BULLISH  → favours selling PUTs (CSP); a headwind for CCs (shares called away on a run).
      * BEARISH  → favours selling CALLs (CC); a headwind for CSPs (assigned into a falling name).
      * SIDEWAYS → grouped with CALLs: a range-bound name is the textbook covered-call write.

    Before this fix the alignment was inverted (it rewarded selling calls into BULLISH and puts
    into BEARISH — the *buy*-side alignment), systematically mis-ranking toward the riskiest
    regime/right combinations (N1).
    """
    score = 50.0
    if quote.right == OptionRight.PUT:
        # Cash-secured put: bullish tailwind favourable, bearish a headwind, sideways neutral.
        if tech.regime == Regime.BULLISH:
            score += 10.0
        elif tech.regime == Regime.BEARISH:
            score -= 5.0
    else:  # OptionRight.CALL — covered call
        # Covered call: bearish/sideways favourable, bullish a headwind (upside given up).
        if tech.regime in (Regime.BEARISH, Regime.SIDEWAYS):
            score += 10.0
        elif tech.regime == Regime.BULLISH:
            score -= 5.0
    # ATR contribution removed: penalising high-ATR stocks is backwards for an income
    # strategy — high ATR means richer IV and better premium. ATR-based regime
    # classification in buy_candidates.py already handles this correctly.
    return max(0.0, min(100.0, score))


_ANNUALIZED_ROC_CAP = 100.0  # % — prevents tiny-DTE blow-up in score normalization (C2)


def annualized_roc_score(annualized_yield_pct: float) -> float:
    """Normalize annualized ROC to 0-100, capped at _ANNUALIZED_ROC_CAP to prevent
    tiny-DTE candidates from dominating purely on inflated annualized yield math."""
    capped = min(annualized_yield_pct, _ANNUALIZED_ROC_CAP)
    return round((capped / _ANNUALIZED_ROC_CAP) * 100.0, 4)


def fundamental_score(fund: FundamentalStats) -> float:
    if fund.quality_flag is True:
        score = 70.0
    elif fund.quality_flag is False:
        score = 20.0
    else:
        score = 50.0
    if fund.dividend_safe is True:
        score += 15.0
    return min(100.0, score)
