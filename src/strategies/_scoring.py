"""Shared scoring helpers used by all strategy modules."""

from __future__ import annotations

import hashlib
from datetime import date

from src.common.schemas import FundamentalStats, OptionQuote, OptionRight, Regime, TechnicalStats


def make_candidate_id(
    strategy: str, underlying: str, right: str, strike: float, expiry: date
) -> str:
    key = f"{strategy}|{underlying}|{right}|{strike}|{expiry}"
    return hashlib.sha1(key.encode()).hexdigest()[:16]


def technical_score(quote: OptionQuote, tech: TechnicalStats) -> float:
    score = 50.0
    if tech.regime == Regime.BULLISH:
        score += 10.0 if quote.right == OptionRight.CALL else -5.0
    elif tech.regime == Regime.BEARISH:
        score += 10.0 if quote.right == OptionRight.PUT else -5.0
    # ATR contribution removed: penalising high-ATR stocks is backwards for an income
    # strategy — high ATR means richer IV and better premium. ATR-based regime
    # classification in buy_candidates.py already handles this correctly.
    return max(0.0, min(100.0, score))


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
