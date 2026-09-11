"""I2 (whole-branch review fix): `dedupe_pre_gate` must not pose as a near miss.

The risk gate's per-symbol dedupe rejects a candidate that cleared every economic gate and
lost only because a better strike on its own name reached the shared budget first. That is a
true rejection — it belongs in `result.assessed` and in the persisted audit trail — but it is
a useless answer to the question the near-miss digest and the rejection tallies exist to
answer ("we found nothing this cycle; what came closest, and why did it fail?"). One busy name
throws off a dozen strikes per scan, so without this filter its own siblings would crowd out
every genuine economic near-miss (`_NEAR_MISS_LIMIT` is 1).
"""

from __future__ import annotations

from datetime import date, timedelta

from src.common.schemas import (
    AssessedContract,
    AssessmentStage,
    OptionRight,
    ScoreCard,
    Strategy,
    TradeCandidate,
)
from src.orchestrator.scan import _lost_only_to_a_sibling, _near_misses, _rank_assessed


def _cand(candidate_id: str, *, score: float, strike: float = 100.0) -> TradeCandidate:
    return TradeCandidate(
        candidate_id=candidate_id,
        strategy=Strategy.CASH_SECURED_PUT,
        underlying="TQQQ",
        right=OptionRight.PUT,
        strike=strike,
        expiry=date.today() + timedelta(days=21),
        contracts=1,
        premium=2.0,
        collateral=strike * 100,
        roc_pct=2.0,
        annualized_yield_pct=20.0,
        breakeven=strike - 2.0,
        delta=-0.25,
        dte=21,
        blended_score=score,
        scores=ScoreCard(symbol="TQQQ"),
    )


def test_a_dedupe_pre_gate_reject_is_not_offered_as_the_closest_miss() -> None:
    sibling = AssessedContract(
        candidate=_cand("sibling", score=90.0, strike=100.0),
        stage=AssessmentStage.RISK_GATE,
        reasons=["dedupe_pre_gate"],
    )
    real = AssessedContract(
        candidate=_cand("real", score=40.0, strike=105.0),
        stage=AssessmentStage.RISK_GATE,
        reasons=["premium_below_fair_value"],
    )
    shown, more = _near_misses(_rank_assessed([sibling, real]), "cash_secured_put")

    # The sibling outranks the genuine miss on every tiebreak `_rank_assessed` uses (same
    # stage, much higher score) — only the filter keeps it out.
    assert [c.candidate_id for c, _ in shown] == ["real"]
    assert [reasons for _, reasons in shown] == [["premium_below_fair_value"]]
    assert more == 0  # and it is not counted in the "…and N more" tally either


def test_a_sibling_with_an_economic_reason_alongside_it_is_still_shown() -> None:
    """The filter is "nothing else went wrong", not "the code appears anywhere".

    `validate_candidates` only ever appends `dedupe_pre_gate` to a candidate whose reason list
    is otherwise empty, so today the two are equivalent — but if that ever changes, a contract
    carrying a real economic reason must keep surfacing it.
    """
    mixed = AssessedContract(
        candidate=_cand("mixed", score=90.0),
        stage=AssessmentStage.RISK_GATE,
        reasons=["dedupe_pre_gate", "iv_rank_below_minimum"],
    )
    shown, _ = _near_misses(_rank_assessed([mixed]), "cash_secured_put")
    assert [c.candidate_id for c, _ in shown] == ["mixed"]


def test_the_predicate_only_matches_the_sole_dedupe_reason() -> None:
    assert _lost_only_to_a_sibling(["dedupe_pre_gate"]) is True
    assert _lost_only_to_a_sibling([]) is False
    assert _lost_only_to_a_sibling(["concentration_limit"]) is False
    assert _lost_only_to_a_sibling(["dedupe_pre_gate", "concentration_limit"]) is False
    # The post-gate slate drop is a different code and keeps its near-miss standing.
    assert _lost_only_to_a_sibling(["dedupe_not_surfaced"]) is False
