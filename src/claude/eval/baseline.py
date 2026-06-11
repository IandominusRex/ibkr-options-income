"""The deterministic baseline — what the system would do WITHOUT Claude.

This is the counterfactual the outcome ledger scores Claude against. It is *pure Python over
the engine's own output*: the Rules Engine + scoring already decide which candidates are
tradeable and in what order (highest blended_score first). The baseline simply names that:
every candidate the engine surfaced is a `sell`, ranked by blended_score; anything not
surfaced is a `skip`.

No LLM, no new tunables — it reuses the exact slate `decision_engine.select_top_candidates`
produced, so "follow the baseline" means "trade the deterministic top-N as ranked." Keeping
this separate and tiny makes the fence obvious: the baseline is the engine talking, Claude's
verdict is layered on top for comparison only.
"""

from __future__ import annotations

from src.common.schemas import BaselineDecision, TradeCandidate


def baseline_decisions(
    surfaced: list[TradeCandidate],
    skipped: list[TradeCandidate] | None = None,
) -> dict[str, BaselineDecision]:
    """Map candidate_id → BaselineDecision.

    Args:
        surfaced: candidates the engine selected as tradeable (the slate Claude reviews),
            already ordered best-first by blended_score.
        skipped: optional candidates that passed earlier stages but were not surfaced
            (e.g. dropped by the score floor or top-N cap) — recorded as `skip`.
    """
    decisions: dict[str, BaselineDecision] = {}
    # Rank by blended_score so the baseline ordering is independent of input order.
    ordered = sorted(surfaced, key=lambda c: c.blended_score, reverse=True)
    for rank, c in enumerate(ordered, start=1):
        decisions[c.candidate_id] = BaselineDecision(
            candidate_id=c.candidate_id,
            recommendation="sell",
            rank=rank,
            score=c.blended_score,
        )
    for c in skipped or []:
        decisions.setdefault(
            c.candidate_id,
            BaselineDecision(
                candidate_id=c.candidate_id,
                recommendation="skip",
                rank=None,
                score=c.blended_score,
            ),
        )
    return decisions
