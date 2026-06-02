"""Select top-N candidates and annotate with rationale tags."""

from __future__ import annotations

from src.common.config import get_config
from src.common.schemas import TradeCandidate


def _build_tags(c: TradeCandidate) -> list[str]:
    tags: list[str] = []
    if c.scores.iv_score > 70:
        tags.append("high_iv_rank")
    if c.scores.liquidity_score > 80:
        tags.append("liquid")
    if c.scores.fundamental_score > 65:
        tags.append("quality_stock")
    if c.scores.assignment_safety_score > 75:
        tags.append("safe_delta")
    return tags


def select_top_candidates(
    candidates: list[TradeCandidate],
    n: int | None = None,
) -> list[TradeCandidate]:
    """Return the top-N candidates (by blended_score) with rationale_tags filled in.

    Expects candidates already sorted DESC by blended_score (output of score_candidates).
    Deduplicates to the single best strike per (underlying, strategy) first, so the slate
    isn't filled with many strikes of one name at the expense of breadth.
    """
    if n is None:
        cfg = get_config()
        n = cfg.risk["portfolio"]["max_new_positions_per_run"]

    seen: set[tuple[str, str]] = set()
    deduped: list[TradeCandidate] = []
    for c in candidates:  # already sorted desc → first seen per key is the best
        key = (c.underlying, c.strategy.value)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(c)

    top = deduped[:n]
    return [c.model_copy(update={"rationale_tags": _build_tags(c)}) for c in top]
