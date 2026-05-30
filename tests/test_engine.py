"""Phase 4: scoring, decision_engine, risk_engine. No live TWS needed."""

from __future__ import annotations

from datetime import date, timedelta

from src.common.schemas import (
    AccountSnapshot,
    OptionQuote,
    OptionRight,
    PositionSnapshot,
    ScoreCard,
    Strategy,
    TradeCandidate,
    Verdict,
)
from src.engine.decision_engine import select_top_candidates
from src.engine.risk_engine import validate_candidates, validate_live_quote
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
    iv_rank: float | None = None,
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
        iv_rank=iv_rank,
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

    def test_missing_delta_rejected_for_income_strategy(self) -> None:
        # Missing greeks on a CC/CSP must REJECT (defense-in-depth), not silently pass.
        verdicts = validate_candidates([_candidate(delta=None)], _account(), [])
        assert "delta_missing" in verdicts[0].reasons
        assert "delta_out_of_range" not in verdicts[0].reasons
        assert verdicts[0].verdict == Verdict.REJECT

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

    # --- Cumulative / portfolio-aware enforcement (S2) ---

    def test_cumulative_concentration_across_same_ticker(self) -> None:
        # max 5% of 100k = 5000. Three AAPL candidates @ 3000 collateral each: only the
        # first fits; the next two breach the per-ticker cap cumulatively.
        cands = [
            _candidate(candidate_id=f"c{i}", underlying="AAPL", collateral=3_000.0)
            for i in range(3)
        ]
        verdicts = validate_candidates(cands, _account(net_liquidation=100_000.0), [])
        passed = [v for v in verdicts if v.verdict == Verdict.PASS]
        assert len(passed) == 1
        assert all("concentration_limit" in v.reasons for v in verdicts if v.verdict == Verdict.REJECT)

    def test_cumulative_buying_power_buffer(self) -> None:
        # bp=20k, required buffer=15% of 100k=15k → only 5k of NEW collateral fits.
        acc = _account(net_liquidation=100_000.0, buying_power=20_000.0, maintenance_margin=10_000.0)
        # Use distinct tickers so per-ticker concentration doesn't mask the BP check.
        cands = [
            _candidate(candidate_id="a", underlying="AAPL", collateral=4_000.0),
            _candidate(candidate_id="b", underlying="MSFT", collateral=4_000.0),
        ]
        verdicts = validate_candidates(cands, acc, [])
        assert verdicts[0].verdict == Verdict.PASS  # 20k-4k=16k >= 15k
        assert "buying_power_buffer" in verdicts[1].reasons  # 20k-8k=12k < 15k

    # --- Sector concentration (S1) ---

    def test_sector_within_cap_passes(self) -> None:
        # Four "tech" names (AAPL/MSFT/GOOGL/AMZN per universe.yaml) @ 4k each on a 100k
        # account: each under the 5% ticker cap (5k), tech bucket 16k under the 25% cap (25k).
        acc = _account(net_liquidation=100_000.0, buying_power=90_000.0, maintenance_margin=0.0)
        cands = [
            _candidate(candidate_id="aapl", underlying="AAPL", collateral=4_000.0),
            _candidate(candidate_id="msft", underlying="MSFT", collateral=4_000.0),
            _candidate(candidate_id="googl", underlying="GOOGL", collateral=4_000.0),
            _candidate(candidate_id="amzn", underlying="AMZN", collateral=4_000.0),
        ]
        verdicts = validate_candidates(cands, acc, [])
        assert all(v.verdict == Verdict.PASS for v in verdicts)
        assert all("sector_limit" not in v.reasons for v in verdicts)

    def test_sector_limit_binds_with_existing_position(self) -> None:
        # Existing NVDA (semis) position already fills most of the 25% sector cap (25k of 100k).
        # A new SMH (also semis) candidate @ 4k tips the semis bucket to 27k > 25k → sector_limit,
        # while SMH itself stays under the 5% ticker cap.
        existing = PositionSnapshot(
            symbol="NVDA", sec_type="STK", position=100.0, avg_cost=230.0, market_value=23_000.0
        )
        cand = _candidate(underlying="SMH", collateral=4_000.0)
        verdicts = validate_candidates([cand], _account(net_liquidation=100_000.0), [existing])
        assert "sector_limit" in verdicts[0].reasons
        assert "concentration_limit" not in verdicts[0].reasons  # SMH ticker itself is fine

    # --- CSP allocation cap (S1/S3) ---

    def test_csp_allocation_within_cap_passes(self) -> None:
        # CSP cap = 60% of 100k = 60k. One small CSP well under it must not trip the cap.
        cand = _candidate(strategy=Strategy.CASH_SECURED_PUT, collateral=4_000.0, delta=-0.20)
        verdicts = validate_candidates([cand], _account(net_liquidation=100_000.0), [])
        assert "csp_allocation_limit" not in verdicts[0].reasons

    def test_csp_allocation_cap_binds_with_existing_puts(self) -> None:
        # Existing short put ties up 57k of the 60k CSP budget (strike 570 * 100 * 1).
        # A new 4k CSP on an unmapped ticker tips total CSP collateral to 61k > 60k.
        existing_put = PositionSnapshot(
            symbol="SPYPUT", sec_type="OPT", position=-1.0, avg_cost=5.0,
            right=OptionRight.PUT, strike=570.0,
        )
        cand = _candidate(
            underlying="ZZTOP", strategy=Strategy.CASH_SECURED_PUT, collateral=4_000.0, delta=-0.20
        )
        verdicts = validate_candidates([cand], _account(net_liquidation=100_000.0), [existing_put])
        assert "csp_allocation_limit" in verdicts[0].reasons
        assert "concentration_limit" not in verdicts[0].reasons

    # --- IV rank gate (S1) ---

    def test_iv_rank_below_minimum_rejected(self) -> None:
        verdicts = validate_candidates([_candidate(iv_rank=10.0)], _account(), [])
        assert "iv_rank_below_minimum" in verdicts[0].reasons

    def test_iv_rank_none_does_not_reject(self) -> None:
        # Missing IV history must not silently zero out the scan.
        verdicts = validate_candidates([_candidate(iv_rank=None)], _account(), [])
        assert "iv_rank_below_minimum" not in verdicts[0].reasons

    def test_iv_rank_above_minimum_passes(self) -> None:
        verdicts = validate_candidates([_candidate(iv_rank=80.0)], _account(), [])
        assert "iv_rank_below_minimum" not in verdicts[0].reasons

    # --- Earnings blackout (F3) ---

    def test_earnings_within_option_life_rejected(self) -> None:
        # Earnings before expiry → option lives through earnings → reject.
        cand = _candidate(dte=30)
        cand = cand.model_copy(update={"next_earnings": date.today() + timedelta(days=10)})
        verdicts = validate_candidates([cand], _account(), [])
        assert "earnings_blackout" in verdicts[0].reasons

    def test_no_earnings_date_does_not_reject(self) -> None:
        verdicts = validate_candidates([_candidate(dte=30)], _account(), [])
        assert "earnings_blackout" not in verdicts[0].reasons

    def test_earnings_after_expiry_not_blackout(self) -> None:
        # Earnings well after expiry and beyond the blackout window → allowed.
        cand = _candidate(dte=21)
        cand = cand.model_copy(update={"next_earnings": date.today() + timedelta(days=90)})
        verdicts = validate_candidates([cand], _account(), [])
        assert "earnings_blackout" not in verdicts[0].reasons


# ---------------------------------------------------------------------------
# risk_engine.py — validate_live_quote (send-time second gate, S4)
# ---------------------------------------------------------------------------


class TestValidateLiveQuote:
    def _quote(self, *, bid=2.0, ask=2.2, delta=-0.20) -> OptionQuote:
        return OptionQuote(
            underlying="AAPL",
            right=OptionRight.PUT,
            strike=150.0,
            expiry=date.today() + timedelta(days=30),
            bid=bid,
            ask=ask,
            delta=delta,
        )

    def test_passes_when_delta_in_range(self) -> None:
        v = validate_live_quote(_candidate(), self._quote(delta=-0.20))
        assert v.verdict == Verdict.PASS

    def test_rejects_when_live_delta_out_of_range(self) -> None:
        # Drifted deep ITM intraday: delta now 0.95, outside CSP 0.15–0.30.
        v = validate_live_quote(_candidate(), self._quote(delta=-0.95))
        assert v.verdict == Verdict.REJECT
        assert "live_delta_out_of_range" in v.reasons

    def test_rejects_when_no_mid(self) -> None:
        v = validate_live_quote(_candidate(), self._quote(bid=0.0, ask=0.0, delta=-0.20))
        assert "live_no_mid" in v.reasons

    def test_passes_when_live_delta_missing(self) -> None:
        # Missing live greeks degrade to the decision-time gate, not a block.
        v = validate_live_quote(_candidate(), self._quote(delta=None))
        assert v.verdict == Verdict.PASS
