"""Phase 4: scoring, decision_engine, risk_engine. No live TWS needed."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

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
        assert all(
            "concentration_limit" in v.reasons for v in verdicts if v.verdict == Verdict.REJECT
        )

    def test_cumulative_buying_power_buffer(self) -> None:
        # bp=20k, required buffer=15% of 100k=15k → only 5k of NEW collateral fits.
        acc = _account(
            net_liquidation=100_000.0, buying_power=20_000.0, maintenance_margin=10_000.0
        )
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
            symbol="SPYPUT",
            sec_type="OPT",
            position=-1.0,
            avg_cost=5.0,
            right=OptionRight.PUT,
            strike=570.0,
        )
        cand = _candidate(
            underlying="ZZTOP", strategy=Strategy.CASH_SECURED_PUT, collateral=4_000.0, delta=-0.20
        )
        verdicts = validate_candidates([cand], _account(net_liquidation=100_000.0), [existing_put])
        assert "csp_allocation_limit" in verdicts[0].reasons
        assert "concentration_limit" not in verdicts[0].reasons

    def test_existing_short_put_charged_at_strike_for_concentration(self) -> None:
        # N5: an existing short put must count toward per-ticker concentration at strike
        # collateral (strike*100*contracts = 60k), not its tiny |market value| (~500). With the
        # old |MV| seeding this ticker looked nearly unexposed and a new CSP slipped past the cap.
        existing_put = PositionSnapshot(
            symbol="NVDA",
            sec_type="OPT",
            position=-1.0,
            avg_cost=5.0,
            right=OptionRight.PUT,
            strike=600.0,
            market_value=-500.0,
        )
        cand = _candidate(
            underlying="NVDA", strategy=Strategy.CASH_SECURED_PUT, collateral=4_000.0, delta=-0.20
        )
        # 5%/ticker cap = 5k of 100k net liq; 60k existing already blows it.
        verdicts = validate_candidates([cand], _account(net_liquidation=100_000.0), [existing_put])
        assert "concentration_limit" in verdicts[0].reasons

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

    # --- Covered calls are exempt from concentration / BP (write against owned shares) ---

    def test_covered_call_on_large_holding_not_concentration_rejected(self) -> None:
        # A holding worth 20% of net-liq already exceeds the 5% ticker cap, but writing a
        # call against it adds NO new exposure and consumes NO buying power — it must PASS.
        pos = PositionSnapshot(
            symbol="AAPL", sec_type="STK", position=100.0, avg_cost=200.0, market_value=20_000.0
        )
        cc = _candidate(
            strategy=Strategy.COVERED_CALL,
            right=OptionRight.CALL,
            delta=0.28,  # within CC 0.20–0.35
            collateral=20_000.0,
            underlying="AAPL",
        )
        verdicts = validate_candidates([cc], _account(net_liquidation=100_000.0), [pos])
        assert "concentration_limit" not in verdicts[0].reasons
        assert "buying_power_buffer" not in verdicts[0].reasons
        assert verdicts[0].verdict == Verdict.PASS

    def test_covered_call_does_not_consume_ticker_budget_for_following_csp(self) -> None:
        # The CC must not eat the per-ticker budget: a CSP on the same name still sees the
        # full 5% headroom. (If the CC wrongly consumed it, the CSP would be rejected.)
        cc = _candidate(
            candidate_id="cc",
            strategy=Strategy.COVERED_CALL,
            right=OptionRight.CALL,
            delta=0.28,
            collateral=20_000.0,
            underlying="AAPL",
        )
        csp = _candidate(
            candidate_id="csp",
            strategy=Strategy.CASH_SECURED_PUT,
            delta=-0.20,
            collateral=4_000.0,  # < 5% of 100k
            underlying="AAPL",
        )
        verdicts = validate_candidates([cc, csp], _account(net_liquidation=100_000.0), [])
        vm = {v.candidate_id: v for v in verdicts}
        assert vm["cc"].verdict == Verdict.PASS
        assert "concentration_limit" not in vm["csp"].reasons


# ---------------------------------------------------------------------------
# risk_engine.py — validate_live_quote (send-time second gate, S4)
# ---------------------------------------------------------------------------


class TestValidateLiveQuote:
    def _quote(self, *, bid=2.95, ask=3.05, delta=-0.20, greeks_source="ibkr") -> OptionQuote:
        # Default mid 3.0 matches _candidate() premium 3.0 so the F2 premium-collapse
        # floor doesn't trip on the delta-focused cases below.
        return OptionQuote(
            underlying="AAPL",
            right=OptionRight.PUT,
            strike=150.0,
            expiry=date.today() + timedelta(days=30),
            bid=bid,
            ask=ask,
            delta=delta,
            greeks_source=greeks_source,
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

    def test_rejects_negative_bid_sentinel(self) -> None:
        # IBKR uses -1.0 as a sentinel for "no bid data" — a negative bid must reject
        # because mid = (-1 + 2) / 2 = 0.50 would be wildly wrong.
        v = validate_live_quote(_candidate(), self._quote(bid=-1.0, ask=2.0))
        assert v.verdict == Verdict.REJECT
        assert "negative_bid_sentinel" in v.reasons

    # --- F2: premium-collapse re-gate ---
    def test_rejects_on_premium_collapse(self) -> None:
        # Approved at premium 3.0; live mid 1.1 (≈63% drop) is below the 0.80 floor.
        v = validate_live_quote(_candidate(), self._quote(bid=1.0, ask=1.2, delta=-0.20))
        assert v.verdict == Verdict.REJECT
        assert "live_premium_collapse" in v.reasons

    def test_passes_when_premium_within_floor(self) -> None:
        # Live mid 2.5 vs premium 3.0 ≈ 83% — above the 0.80 floor, so no collapse flag.
        v = validate_live_quote(_candidate(), self._quote(bid=2.45, ask=2.55, delta=-0.20))
        assert "live_premium_collapse" not in v.reasons

    # --- F6: live mode requires IBKR-sourced greeks ---
    def test_live_mode_rejects_non_ibkr_greeks(self, monkeypatch) -> None:
        from src.common.config import get_config

        monkeypatch.setattr(get_config().secrets, "live_trading", True)
        q = self._quote(delta=-0.20, greeks_source="black_scholes")
        v = validate_live_quote(_candidate(), q)
        assert v.verdict == Verdict.REJECT
        assert "live_greeks_required" in v.reasons

    def test_live_mode_rejects_missing_live_greeks(self, monkeypatch) -> None:
        from src.common.config import get_config

        monkeypatch.setattr(get_config().secrets, "live_trading", True)
        v = validate_live_quote(_candidate(), self._quote(delta=None))
        assert "live_greeks_required" in v.reasons

    def test_paper_mode_allows_fallback_greeks(self) -> None:
        # In paper mode (is_live False) the fallback degrade is preserved — no F6 block.
        q = self._quote(delta=-0.20, greeks_source="black_scholes")
        v = validate_live_quote(_candidate(), q)
        assert "live_greeks_required" not in v.reasons


class TestValidateCandidatesDeltaSign:
    """P1-05: delta sign validation prevents wrong-sign data from passing abs() checks."""

    def test_put_with_negative_delta_passes(self) -> None:
        cand = _candidate(delta=-0.20, right=OptionRight.PUT)
        verdicts = validate_candidates([cand], _account(), [])
        assert "delta_sign_mismatch" not in verdicts[0].reasons

    def test_put_with_positive_delta_rejects(self) -> None:
        cand = _candidate(delta=0.20, right=OptionRight.PUT)
        verdicts = validate_candidates([cand], _account(), [])
        assert "delta_sign_mismatch" in verdicts[0].reasons
        assert verdicts[0].verdict == Verdict.REJECT

    def test_call_with_positive_delta_passes(self) -> None:
        cand = _candidate(
            delta=0.28,
            right=OptionRight.CALL,
            strategy=Strategy.COVERED_CALL,
        )
        verdicts = validate_candidates([cand], _account(), [])
        assert "delta_sign_mismatch" not in verdicts[0].reasons

    def test_call_with_negative_delta_rejects(self) -> None:
        cand = _candidate(
            delta=-0.28,
            right=OptionRight.CALL,
            strategy=Strategy.COVERED_CALL,
        )
        verdicts = validate_candidates([cand], _account(), [])
        assert "delta_sign_mismatch" in verdicts[0].reasons


class TestValidateCandidatesMaxContracts:
    """P1-06: max_contracts config key is enforced."""

    def test_within_max_contracts_passes(self) -> None:
        # max_contracts=10 per config; 1 contract is well within limit.
        cand = _candidate(contracts=1)
        verdicts = validate_candidates([cand], _account(), [])
        assert "contracts_exceeds_max" not in verdicts[0].reasons

    def test_exceeds_max_contracts_rejects(self) -> None:
        # max_contracts=10; 15 contracts must be rejected.
        cand = _candidate(contracts=15, collateral=15_000.0)
        verdicts = validate_candidates([cand], _account(), [])
        assert "contracts_exceeds_max" in verdicts[0].reasons
        assert verdicts[0].verdict == Verdict.REJECT


# ---------------------------------------------------------------------------
# C1: IV/RV richness gate (iv_rv_below_minimum)
# ---------------------------------------------------------------------------


class TestIVRVGate:
    """C1: validate_candidates enforces min_iv_rv_ratio from risk_limits.yaml → iv."""

    def _cand_with_ratio(self, ratio: float | None) -> TradeCandidate:
        c = _candidate(iv_rank=80.0)
        return c.model_copy(update={"iv_rv_ratio": ratio})

    def test_ratio_above_minimum_passes(self) -> None:
        # default min_iv_rv_ratio = 1.05; ratio 1.20 > 1.05 → pass
        cand = self._cand_with_ratio(1.20)
        verdicts = validate_candidates([cand], _account(), [])
        assert "iv_rv_below_minimum" not in verdicts[0].reasons

    def test_ratio_exactly_at_minimum_passes(self) -> None:
        cand = self._cand_with_ratio(1.05)
        verdicts = validate_candidates([cand], _account(), [])
        assert "iv_rv_below_minimum" not in verdicts[0].reasons

    def test_ratio_below_minimum_rejects(self) -> None:
        # ratio 0.82 < 1.05 → iv_rv_below_minimum
        cand = self._cand_with_ratio(0.82)
        verdicts = validate_candidates([cand], _account(), [])
        assert "iv_rv_below_minimum" in verdicts[0].reasons
        assert verdicts[0].verdict == Verdict.REJECT

    def test_none_ratio_does_not_reject(self) -> None:
        # Missing ratio = data unavailable, not a capital risk → never blocks the scan.
        cand = self._cand_with_ratio(None)
        verdicts = validate_candidates([cand], _account(), [])
        assert "iv_rv_below_minimum" not in verdicts[0].reasons

    def test_iv_rv_reason_in_rejection_tally(self) -> None:
        # Confirm the reason string is exactly "iv_rv_below_minimum" (used by C7 skipped-reason).
        cand = self._cand_with_ratio(0.80)
        verdicts = validate_candidates([cand], _account(), [])
        assert verdicts[0].reasons == [
            r
            for r in verdicts[0].reasons
            if r  # all non-empty
        ]
        assert any(r == "iv_rv_below_minimum" for r in verdicts[0].reasons)


# ---------------------------------------------------------------------------
# C2: annualized_roc_score helper and ranking
# ---------------------------------------------------------------------------


class TestAnnualizedRocScore:
    """C2: annualized_roc_score normalizes correctly and the cap prevents blow-up."""

    def test_yield_at_cap_scores_100(self) -> None:
        from src.strategies._scoring import annualized_roc_score

        assert annualized_roc_score(100.0) == 100.0

    def test_yield_above_cap_clamped_to_100(self) -> None:
        from src.strategies._scoring import annualized_roc_score

        # A 7-DTE option with 1% ROC ≈ 52% annualized — but 500% should still be 100.
        assert annualized_roc_score(500.0) == 100.0

    def test_yield_at_half_cap_scores_50(self) -> None:
        from src.strategies._scoring import annualized_roc_score

        assert annualized_roc_score(50.0) == pytest.approx(50.0, abs=0.01)

    def test_zero_yield_scores_zero(self) -> None:
        from src.strategies._scoring import annualized_roc_score

        assert annualized_roc_score(0.0) == 0.0

    def test_minimum_gate_yield_scores_low_but_nonzero(self) -> None:
        from src.strategies._scoring import annualized_roc_score

        # min_annualized_yield_pct = 12%; score = 12/100 * 100 = 12.
        score = annualized_roc_score(12.0)
        assert 10.0 < score < 20.0

    def test_higher_annualized_yield_ranks_higher_with_nonzero_weight(self) -> None:
        """With annualized_roc weight > 0, a higher annualized yield must produce a
        higher blended_score — verifying cross-DTE candidates rank correctly (C2)."""
        from src.common.config import get_config
        from src.engine.scoring import score_candidates

        cfg = get_config()
        orig_weights = cfg.weights.get("cash_secured_put", {}).copy()
        cfg.weights["cash_secured_put"] = {
            "iv": 0.0,
            "technical": 0.0,
            "fundamental": 0.0,
            "liquidity": 0.0,
            "assignment_risk": 0.0,
            "sentiment": 0.0,
            "annualized_roc": 1.0,
        }
        try:
            low_yield = _candidate(candidate_id="low", annualized_yield_pct=15.0)
            low_yield = low_yield.model_copy(
                update={
                    "scores": low_yield.scores.model_copy(update={"annualized_roc_score": 15.0})
                }
            )
            high_yield = _candidate(candidate_id="high", annualized_yield_pct=40.0)
            high_yield = high_yield.model_copy(
                update={
                    "scores": high_yield.scores.model_copy(update={"annualized_roc_score": 40.0})
                }
            )
            result = score_candidates([low_yield, high_yield])
            assert result[0].candidate_id == "high"
            assert result[1].candidate_id == "low"
        finally:
            cfg.weights["cash_secured_put"] = orig_weights
