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
    if tech.atr_14 is not None and tech.price > 0:
        atr_pct = tech.atr_14 / tech.price
        score += max(0.0, 10.0 * (0.02 - atr_pct) / 0.02)
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
