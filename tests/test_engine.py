"""Phase 4: scoring, decision_engine, risk_engine. No live TWS needed."""

from __future__ import annotations

from datetime import date, timedelta

from src.common.schemas import (
    AccountSnapshot,
    OptionRight,
    PositionSnapshot,
    ScoreCard,
    Strategy,
    TradeCandidate,
    Verdict,
)
from src.engine.decision_engine import select_top_candidates
from src.engine.risk_engine import validate_candidates
from src.engine.scoring import score_candidates

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _scores(
    iv: float = 50.0,
    technical: float = 50.0,
    fundamental: float = 50.0,
    liquidity: float = 50.0,
    assignment: float = 50.0,
    sentiment: float | None = None,
    symbol: str = "AAPL",
) -> ScoreCard:
    return ScoreCard(
        symbol=symbol,
        iv_score=iv,
        technical_score=technical,
        fundamental_score=fundamental,
        liquidity_score=liquidity,
        assignment_safety_score=assignment,
        sentiment_score=sentiment,
    )


def _candidate(
    *,
    candidate_id: str = "test-001",
    strategy: Strategy = Strategy.CASH_SECURED_PUT,
    underlying: str = "AAPL",
    right: OptionRight = OptionRight.PUT,
    scores: ScoreCard | None = None,
    roc_pct: float = 2.0,
    annualized_yield_pct: float = 20.0,
    dte: int = 30,
    delta: float | None = -0.20,
    contracts: int = 1,
    collateral: float = 3_000.0,
) -> TradeCandidate:
    return TradeCandidate(
        candidate_id=candidate_id,
        strategy=strategy,
        underlying=underlying,
        right=right,
        strike=150.0,
        expiry=date.today() + timedelta(days=dte),
        contracts=contracts,
        premium=3.0,
        collateral=collateral,
        roc_pct=roc_pct,
        annualized_yield_pct=annualized_yield_pct,
        breakeven=147.0,
        delta=delta,
        dte=dte,
        scores=scores or _scores(),
    )


def _account(
    *,
    net_liquidation: float = 100_000.0,
    buying_power: float = 50_000.0,
    maintenance_margin: float = 20_000.0,
) -> AccountSnapshot:
    return AccountSnapshot(
        account="DU123",
        net_liquidation=net_liquidation,
        total_cash=50_000.0,
        buying_power=buying_power,
        maintenance_margin=maintenance_margin,
        excess_liquidity=30_000.0,
    )


# ---------------------------------------------------------------------------
# scoring.py
# ---------------------------------------------------------------------------


class TestScoreCandidates:
    def test_blended_score_in_range(self) -> None:
        c = _candidate(
            scores=_scores(iv=80, technical=60, fundamental=70, liquidity=90, assignment=50)
        )
        result = score_candidates([c])
        assert 0.0 <= result[0].blended_score <= 100.0

    def test_sorted_desc(self) -> None:
        low = _candidate(
            candidate_id="low",
            scores=_scores(iv=10, technical=10, fundamental=10, liquidity=10, assignment=10),
        )
        high = _candidate(
            candidate_id="high",
            scores=_scores(iv=90, technical=90, fundamental=90, liquidity=90, assignment=90),
        )
        result = score_candidates([low, high])
        assert result[0].candidate_id == "high"
        assert result[1].candidate_id == "low"

    def test_returns_new_list_without_mutating_originals(self) -> None:
        candidates = [_candidate()]
        result = score_candidates(candidates)
        assert result is not candidates
        assert candidates[0].blended_score == 0.0

    def test_all_hundred_gives_hundred(self) -> None:
        c = _candidate(
            scores=_scores(
                iv=100, technical=100, fundamental=100, liquidity=100, assignment=100, sentiment=100
            )
        )
        result = score_candidates([c])
        assert abs(result[0].blended_score - 100.0) < 0.01

    def test_all_zero_gives_zero(self) -> None:
        c = _candidate(
            scores=_scores(iv=0, technical=0, fundamental=0, liquidity=0, assignment=0, sentiment=0)
        )
        result = score_candidates([c])
        assert result[0].blended_score == 0.0

    def test_empty_input(self) -> None:
        assert score_candidates([]) == []

    def test_cc_uses_higher_assignment_weight_than_csp(self) -> None:
        """CC assignment_risk weight (0.20) > CSP (0.10) so a 100 assignment score
        should produce a higher blended for CC than CSP with all other scores equal."""
        s = _scores(iv=50, technical=50, fundamental=50, liquidity=50, assignment=100)
        cc = _candidate(
            candidate_id="cc", strategy=Strategy.COVERED_CALL, scores=s, right=OptionRight.CALL
        )
        csp = _candidate(candidate_id="csp", strategy=Strategy.CASH_SECURED_PUT, scores=s)
        cc_blended = score_candidates([cc])[0].blended_score
        csp_blended = score_candidates([csp])[0].blended_score
        assert cc_blended > csp_blended

    def test_roll_falls_back_to_equal_weights(self) -> None:
        """ROLL has no weights entry → equal weights → must produce a valid score."""
        c = _candidate(
            candidate_id="roll", strategy=Strategy.ROLL, scores=_scores(iv=80, assignment=80)
        )
        result = score_candidates([c])
        assert 0.0 < result[0].blended_score <= 100.0


# ---------------------------------------------------------------------------
# decision_engine.py
# ---------------------------------------------------------------------------


class TestSelectTopCandidates:
    def test_returns_at_most_n(self) -> None:
        candidates = [_candidate(candidate_id=str(i)) for i in range(20)]
        scored = score_candidates(candidates)
        top = select_top_candidates(scored, n=5)
        assert len(top) <= 5

    def test_returns_all_when_fewer_than_n(self) -> None:
        scored = score_candidates([_candidate(candidate_id="only")])
        assert len(select_top_candidates(scored, n=10)) == 1

    def test_high_iv_rank_tag(self) -> None:
        scored = score_candidates([_candidate(scores=_scores(iv=80))])
        assert "high_iv_rank" in select_top_candidates(scored, n=10)[0].rationale_tags

    def test_no_high_iv_rank_when_below_threshold(self) -> None:
        scored = score_candidates([_candidate(scores=_scores(iv=50))])
        assert "high_iv_rank" not in select_top_candidates(scored, n=10)[0].rationale_tags

    def test_liquid_tag(self) -> None:
        scored = score_candidates([_candidate(scores=_scores(liquidity=85))])
        assert "liquid" in select_top_candidates(scored, n=10)[0].rationale_tags

    def test_quality_stock_tag(self) -> None:
        scored = score_candidates([_candidate(scores=_scores(fundamental=70))])
        assert "quality_stock" in select_top_candidates(scored, n=10)[0].rationale_tags

    def test_safe_delta_tag(self) -> None:
        scored = score_candidates([_candidate(scores=_scores(assignment=80))])
        assert "safe_delta" in select_top_candidates(scored, n=10)[0].rationale_tags

    def test_no_tags_for_average_scores(self) -> None:
        scored = score_candidates([_candidate(scores=_scores())])
        assert select_top_candidates(scored, n=10)[0].rationale_tags == []

    def test_multiple_tags_at_once(self) -> None:
        s = _scores(iv=80, liquidity=85, fundamental=70, assignment=80)
        scored = score_candidates([_candidate(scores=s)])
        tags = select_top_candidates(scored, n=10)[0].rationale_tags
        assert "high_iv_rank" in tags
        assert "liquid" in tags
        assert "quality_stock" in tags
        assert "safe_delta" in tags

    def test_empty_input(self) -> None:
        assert select_top_candidates([], n=5) == []

    def test_default_n_from_config(self) -> None:
        candidates = [_candidate(candidate_id=str(i)) for i in range(15)]
        scored = score_candidates(candidates)
        # config max_new_positions_per_run = 10
        assert len(select_top_candidates(scored)) <= 10


# ---------------------------------------------------------------------------
# risk_engine.py
# ---------------------------------------------------------------------------


class TestValidateCandidates:
    def test_pass_within_all_limits(self) -> None:
        cand = _candidate(
            roc_pct=2.0,
            annualized_yield_pct=20.0,
            dte=30,
            delta=-0.20,
            contracts=1,
            collateral=1_000.0,
        )
        verdicts = validate_candidates([cand], _account(), [])
        assert len(verdicts) == 1
        assert verdicts[0].verdict == Verdict.PASS
        assert verdicts[0].reasons == []

    def test_reject_roc_below_minimum(self) -> None:
        verdicts = validate_candidates([_candidate(roc_pct=0.5)], _account(), [])
        assert "roc_below_minimum" in verdicts[0].reasons
        assert verdicts[0].verdict == Verdict.REJECT

    def test_reject_yield_below_minimum(self) -> None:
        verdicts = validate_candidates([_candidate(annualized_yield_pct=5.0)], _account(), [])
        assert "yield_below_minimum" in verdicts[0].reasons

    def test_reject_dte_too_low(self) -> None:
        verdicts = validate_candidates([_candidate(dte=10)], _account(), [])
        assert "dte_out_of_range" in verdicts[0].reasons

    def test_reject_dte_too_high(self) -> None:
        verdicts = validate_candidates([_candidate(dte=60)], _account(), [])
        assert "dte_out_of_range" in verdicts[0].reasons

    def test_reject_delta_out_of_range(self) -> None:
        verdicts = validate_candidates([_candidate(delta=-0.50)], _account(), [])
        assert "delta_out_of_range" in verdicts[0].reasons

    def test_skip_delta_check_when_none(self) -> None:
        verdicts = validate_candidates([_candidate(delta=None)], _account(), [])
        assert "delta_out_of_range" not in verdicts[0].reasons

    def test_reject_no_contracts(self) -> None:
        verdicts = validate_candidates([_candidate(contracts=0)], _account(), [])
        assert "no_contracts" in verdicts[0].reasons

    def test_reject_concentration_limit(self) -> None:
        # max 5% of 100k = 5000; existing 4000 + collateral 3000 = 7000 > 5000
        pos = PositionSnapshot(
            symbol="AAPL",
            sec_type="STK",
            position=40.0,
            avg_cost=100.0,
            market_value=4_000.0,
        )
        cand = _candidate(collateral=3_000.0, underlying="AAPL")
        verdicts = validate_candidates([cand], _account(net_liquidation=100_000.0), [pos])
        assert "concentration_limit" in verdicts[0].reasons

    def test_pass_concentration_within_limit(self) -> None:
        # existing 0 + collateral 1000 < 5% of 100k (5000)
        cand = _candidate(collateral=1_000.0, underlying="AAPL")
        verdicts = validate_candidates([cand], _account(net_liquidation=100_000.0), [])
        assert "concentration_limit" not in verdicts[0].reasons

    def test_concentration_counts_option_positions_by_underlying(self) -> None:
        # Option position where underlying=="AAPL" but symbol differs
        pos = PositionSnapshot(
            symbol="AAPL  250117P00150000",
            sec_type="OPT",
            position=-1.0,
            avg_cost=3.0,
            market_value=4_500.0,
            underlying="AAPL",
        )
        cand = _candidate(collateral=3_000.0, underlying="AAPL")
        verdicts = validate_candidates([cand], _account(net_liquidation=100_000.0), [pos])
        assert "concentration_limit" in verdicts[0].reasons

    def test_reject_margin_limit(self) -> None:
        # 60% margin usage > max 50%
        acc = _account(
            net_liquidation=100_000.0, maintenance_margin=60_000.0, buying_power=50_000.0
        )
        verdicts = validate_candidates([_candidate(collateral=1_000.0)], acc, [])
        assert "margin_limit" in verdicts[0].reasons

    def test_reject_buying_power_buffer(self) -> None:
        # required = 15% of 100k = 15000; buying_power = 10000 < 15000
        acc = _account(
            net_liquidation=100_000.0, buying_power=10_000.0, maintenance_margin=20_000.0
        )
        verdicts = validate_candidates([_candidate(collateral=1_000.0)], acc, [])
        assert "buying_power_buffer" in verdicts[0].reasons

    def test_multiple_reject_reasons_on_single_candidate(self) -> None:
        cand = _candidate(roc_pct=0.5, annualized_yield_pct=5.0)
        verdicts = validate_candidates([cand], _account(), [])
        assert "roc_below_minimum" in verdicts[0].reasons
        assert "yield_below_minimum" in verdicts[0].reasons
        assert verdicts[0].verdict == Verdict.REJECT

    def test_empty_input(self) -> None:
        assert validate_candidates([], _account(), []) == []

    def test_candidate_id_preserved(self) -> None:
        cand = _candidate(candidate_id="unique-xyz")
        verdicts = validate_candidates([cand], _account(), [])
        assert verdicts[0].candidate_id == "unique-xyz"

    def test_one_verdict_per_candidate(self) -> None:
        candidates = [_candidate(candidate_id=str(i)) for i in range(5)]
        verdicts = validate_candidates(candidates, _account(), [])
        assert len(verdicts) == 5
