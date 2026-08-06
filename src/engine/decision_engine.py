"""Select top-N candidates and annotate with rationale tags."""

from __future__ import annotations

from src.common.profile import get_effective_risk
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

    Thin wrapper over :func:`select_top_candidates_detailed` for callers that don't care
    what was dropped.
    """
    return select_top_candidates_detailed(candidates, n)[0]


def select_top_candidates_detailed(
    candidates: list[TradeCandidate],
    n: int | None = None,
) -> tuple[list[TradeCandidate], list[tuple[TradeCandidate, str]]]:
    """Return ``(top, dropped)`` where each dropped candidate carries *why* it was dropped.

    Expects candidates already sorted DESC by blended_score (output of score_candidates).
    Deduplicates to the single best strike per (underlying, strategy) first, so the slate
    isn't filled with many strikes of one name at the expense of breadth.

    The two drop reasons read very differently to an operator and are reported separately:

      * ``"dedupe"`` — a better strike on the same name won; the trade is available, just not
        this contract.
      * ``"top_n"`` — the candidate was good enough but ``max_new_positions_per_run`` was
        already full; raising the cap would surface it.

    Both used to vanish silently, which made a fully-gated slate indistinguishable from one
    that simply ran out of room.
    """
    if n is None:
        n = get_effective_risk()["portfolio"]["max_new_positions_per_run"]

    seen: set[tuple[str, str]] = set()
    deduped: list[TradeCandidate] = []
    dropped: list[tuple[TradeCandidate, str]] = []
    for c in candidates:  # already sorted desc → first seen per key is the best
        key = (c.underlying, c.strategy.value)
        if key in seen:
            dropped.append((c, "dedupe"))
            continue
        seen.add(key)
        deduped.append(c)

    top = deduped[:n]
    dropped.extend((c, "top_n") for c in deduped[n:])
    return [c.model_copy(update={"rationale_tags": _build_tags(c)}) for c in top], dropped
