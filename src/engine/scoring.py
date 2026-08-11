"""Weighted score blending: ScoreCard components → TradeCandidate.blended_score."""

from __future__ import annotations

from src.common.config import get_config
from src.common.schemas import Strategy, TradeCandidate

_EQUAL_WEIGHTS: dict[str, float] = {
    "iv": 0.2,
    "technical": 0.2,
    "fundamental": 0.2,
    "liquidity": 0.2,
    "assignment_risk": 0.2,
    "sentiment": 0.0,  # off by default; enabled when sentiment weight is in config
}


# Keys inside a strategy block that are NOT component weights and must be excluded from the
# normalization sum. `zone_fit` is a blend *within* technical_score (see _scoring.py), not a
# ScoreCard component — counting it here would silently dilute every real weight.
_NON_COMPONENT_KEYS = frozenset({"zone_fit"})


def _get_weights(strategy: Strategy) -> dict[str, float]:
    """Return normalized weights for a strategy, falling back to equal weights."""
    block: dict[str, float] = get_config().weights.get(strategy.value, {})
    raw = {k: v for k, v in block.items() if k not in _NON_COMPONENT_KEYS}
    if not raw:
        return _EQUAL_WEIGHTS.copy()
    total = sum(raw.values())
    if total <= 0:
        return _EQUAL_WEIGHTS.copy()
    return {k: v / total for k, v in raw.items()}


def score_candidates(candidates: list[TradeCandidate]) -> list[TradeCandidate]:
    """Return a new list with blended_score filled in, sorted by blended_score DESC."""
    result: list[TradeCandidate] = []
    for c in candidates:
        w = _get_weights(c.strategy)
        s = c.scores
        # Treat missing sentiment as neutral (50) so the weight still applies uniformly
        sentiment = s.sentiment_score if s.sentiment_score is not None else 50.0
        blended = (
            s.iv_score * w.get("iv", 0.2)
            + s.technical_score * w.get("technical", 0.2)
            + s.fundamental_score * w.get("fundamental", 0.2)
            + s.liquidity_score * w.get("liquidity", 0.2)
            + s.assignment_safety_score * w.get("assignment_risk", 0.2)
            + sentiment * w.get("sentiment", 0.0)
        )
        result.append(c.model_copy(update={"blended_score": round(blended, 4)}))
    result.sort(key=lambda c: c.blended_score, reverse=True)
    return result
