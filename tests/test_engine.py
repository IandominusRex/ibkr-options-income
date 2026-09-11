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
    dte: int = 20,
    delta: float | None = -0.20,
    contracts: int = 1,
    collateral: float = 3_000.0,
    iv_rank: float | None = None,
    current_iv: float | None = None,
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
        current_iv=current_iv,
        dte=dte,
        scores=scores or _scores(),
    )


def _account(
    *,
    net_liquidation: float = 100_000.0,
    buying_power: float = 50_000.0,
    maintenance_margin: float = 20_000.0,
    net_liq: float | None = None,
    cash: float | None = None,
) -> AccountSnapshot:
    """`net_liq`/`cash` are aliases used by the risk-unit tests (Task 4): `net_liq` overrides
    `net_liquidation`, and `cash` overrides `excess_liquidity` — the cash basis
    `capital.resolve_caps` reads — and `total_cash`. Every existing default is unchanged, so
    every pre-existing caller (which never passes these) is unaffected."""
    return AccountSnapshot(
        account="DU123",
        net_liquidation=net_liq if net_liq is not None else net_liquidation,
        total_cash=cash if cash is not None else 50_000.0,
        buying_power=buying_power,
        maintenance_margin=maintenance_margin,
        excess_liquidity=cash if cash is not None else 30_000.0,
    )


def _csp_candidate(
    *,
    underlying: str,
    strike: float,
    contracts: int = 1,
    current_iv: float | None = 30.0,
    dte: int = 20,
    delta: float = -0.20,
    premium: float = 3.0,
) -> TradeCandidate:
    """Build a valid CSP TradeCandidate whose roc/yield clear the configured floors, so only
    the concentration logic under test can reject it."""
    collateral = strike * 100.0 * contracts
    return TradeCandidate(
        candidate_id=f"{underlying}-csp-{strike}-{contracts}",
        strategy=Strategy.CASH_SECURED_PUT,
        underlying=underlying,
        right=OptionRight.PUT,
        strike=strike,
        expiry=date.today() + timedelta(days=dte),
        contracts=contracts,
        premium=premium,
        collateral=collateral,
        roc_pct=2.0,
        annualized_yield_pct=20.0,
        breakeven=strike - premium,
        delta=delta,
        current_iv=current_iv,
        dte=dte,
        scores=_scores(symbol=underlying),
    )


def _cc_candidate(
    *,
    underlying: str,
    strike: float,
    contracts: int = 1,
    current_iv: float | None = 30.0,
    dte: int = 20,
    delta: float = 0.28,
) -> TradeCandidate:
    """Build a valid CC TradeCandidate whose roc/yield clear the configured floors, so only
    the concentration logic under test can reject it."""
    collateral = strike * 100.0 * contracts
    return TradeCandidate(
        candidate_id=f"{underlying}-cc-{strike}-{contracts}",
        strategy=Strategy.COVERED_CALL,
        underlying=underlying,
        right=OptionRight.CALL,
        strike=strike,
        expiry=date.today() + timedelta(days=dte),
        contracts=contracts,
        premium=3.0,
        collateral=collateral,
        roc_pct=2.0,
        annualized_yield_pct=20.0,
        breakeven=strike + 3.0,
        delta=delta,
        current_iv=current_iv,
        dte=dte,
        scores=_scores(symbol=underlying),
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
            dte=20,
            delta=-0.20,
            contracts=1,
            collateral=1_000.0,
        )
        verdicts = validate_candidates([cand], _account(), [])
        assert len(verdicts) == 1
        assert verdicts[0].verdict == Verdict.PASS
        assert verdicts[0].reasons == []

    def test_reject_roc_below_minimum(self) -> None:
        # D2: min_roc_pct dropped from 1.0% (primary gate) to 0.15% (noise floor only, now
        # that require_vrp_edge is the primary gate) — 0.5% used to trip it; 0.10% still does.
        verdicts = validate_candidates([_candidate(roc_pct=0.10)], _account(), [])
        assert "roc_below_minimum" in verdicts[0].reasons
        assert verdicts[0].verdict == Verdict.REJECT

    def test_reject_yield_below_minimum(self) -> None:
        # D2: min_annualized_yield_pct dropped from 12.0% to 0.0% (noise floor only). A real
        # candidate's annualized yield is never negative, so this gate is now only reachable
        # by a negative value — still worth covering, since a human can raise the config knob
        # back to a live gate and this proves the comparison itself still works.
        verdicts = validate_candidates([_candidate(annualized_yield_pct=-1.0)], _account(), [])
        assert "yield_below_minimum" in verdicts[0].reasons

    def test_reject_dte_too_low(self) -> None:
        verdicts = validate_candidates([_candidate(dte=3)], _account(), [])
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
        # D1: with no current_iv the gate falls back to the raw-collateral cap (10% of
        # 100k = 10,000), which only rejects when the CUMULATIVE collateral clears it AND
        # the new candidate's OWN collateral clears the 25%-of-NLV large-position ceiling
        # (25,000) — a deliberately conservative fallback, since a raw position snapshot
        # carries no IV to size a risk-unit charge from. existing 4,000 + new 26,000 =
        # 30,000 > 10,000, and 26,000 > 25,000, so both legs of the fallback trip.
        pos = PositionSnapshot(
            symbol="AAPL",
            sec_type="STK",
            position=40.0,
            avg_cost=100.0,
            market_value=4_000.0,
        )
        cand = _candidate(collateral=26_000.0, underlying="AAPL")
        verdicts = validate_candidates(
            [cand], _account(net_liquidation=100_000.0, cash=100_000.0), [pos]
        )
        assert "concentration_limit" in verdicts[0].reasons

    def test_pass_concentration_within_limit(self) -> None:
        # existing 0 + collateral 1000 < 5% of 100k (5000)
        cand = _candidate(collateral=1_000.0, underlying="AAPL")
        verdicts = validate_candidates([cand], _account(net_liquidation=100_000.0), [])
        assert "concentration_limit" not in verdicts[0].reasons

    def test_concentration_counts_option_positions_by_underlying(self) -> None:
        # Option position where underlying=="AAPL" but symbol differs — must key off
        # `underlying`. Same raw-collateral fallback arithmetic as the test above:
        # cumulative 4,500 + 26,000 = 30,500 > the 10,000 ticker cap, and the new
        # candidate's own 26,000 > the 25,000 large-position ceiling.
        pos = PositionSnapshot(
            symbol="AAPL  250117P00150000",
            sec_type="OPT",
            position=-1.0,
            avg_cost=3.0,
            market_value=4_500.0,
            underlying="AAPL",
        )
        cand = _candidate(collateral=26_000.0, underlying="AAPL")
        verdicts = validate_candidates(
            [cand], _account(net_liquidation=100_000.0, cash=100_000.0), [pos]
        )
        assert "concentration_limit" in verdicts[0].reasons

    def test_reject_margin_limit(self) -> None:
        # 60% margin usage > max 50%
        acc = _account(
            net_liquidation=100_000.0, maintenance_margin=60_000.0, buying_power=50_000.0
        )
        verdicts = validate_candidates([_candidate(collateral=1_000.0)], acc, [])
        assert "margin_limit" in verdicts[0].reasons

    def test_reject_buying_power_buffer(self) -> None:
        # D1: the BP buffer is now `capital.resolve_caps`' deployable cash. Deployable =
        # max(0, cash - reserve); reserve = max(cash_reserve_pct% of cash, cash_reserve_absolute).
        # At cash=$1,000, reserve = max(200, 10,000) = 10,000, so deployable clips to 0.0,
        # less than the $1,000 of new collateral requested.
        acc = _account(net_liquidation=100_000.0, cash=1_000.0, maintenance_margin=20_000.0)
        verdicts = validate_candidates([_candidate(collateral=1_000.0)], acc, [])
        assert "buying_power_buffer" in verdicts[0].reasons

    def test_multiple_reject_reasons_on_single_candidate(self) -> None:
        # D2: min_annualized_yield_pct dropped to 0.0% (noise floor only), so a positive
        # yield like the old fixture's 5.0 no longer trips it (see test_reject_yield_below_
        # minimum for why that gate is now only reachable with a negative value). Re-derived
        # using roc_pct below the new 0.15% floor and annualized_yield_pct below 0.0%, so
        # both income reasons still fire together — preserving this test's intent.
        cand = _candidate(roc_pct=0.10, annualized_yield_pct=-1.0)
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
        # Two-pass design (2026-09-11): identical-score candidates for the same
        # (underlying, strategy) are deduped to a single representative BEFORE the
        # cumulative budget is ever checked, so only one of the three ever reaches it —
        # and it fits comfortably (one candidate's ~2,216 risk units vs the 5,000 cap).
        # The other two are rejected pre-gate, not by the budget.
        cands = [
            _candidate(
                candidate_id=f"c{i}",
                underlying="AAPL",
                collateral=10_000.0,
                dte=28,
                current_iv=80.0,
            )
            for i in range(3)
        ]
        verdicts = validate_candidates(cands, _account(net_liquidation=100_000.0), [])
        passed = [v for v in verdicts if v.verdict == Verdict.PASS]
        assert len(passed) == 1
        rejected = [v for v in verdicts if v.verdict == Verdict.REJECT]
        assert len(rejected) == 2
        assert all(v.reasons == ["dedupe_pre_gate"] for v in rejected)

    def test_cumulative_buying_power_buffer(self) -> None:
        # D1 + Task 9: deployable cash = excess_liquidity(16,000) minus the reserve. Task 9
        # formalized `cash_reserve_absolute: 10000` in risk_limits.yaml, so at this account size
        # the absolute floor (10,000) dominates the 20% percentage reserve (16,000 x 20% =
        # 3,200) -> reserve = 10,000, deployable = 6,000; only one $4,000 CSP fits before the
        # second breaches the buffer.
        acc = _account(net_liquidation=100_000.0, cash=16_000.0, maintenance_margin=10_000.0)
        # Use distinct tickers so per-ticker concentration doesn't mask the BP check.
        cands = [
            _candidate(candidate_id="a", underlying="AAPL", collateral=4_000.0),
            _candidate(candidate_id="b", underlying="MSFT", collateral=4_000.0),
        ]
        verdicts = validate_candidates(cands, acc, [])
        assert verdicts[0].verdict == Verdict.PASS  # cash_used 0 -> 4,000 <= deployable 6,000
        assert "buying_power_buffer" in verdicts[1].reasons  # cumulative 8,000 > deployable 6,000

    # --- Sector concentration (S1) ---

    def test_sector_within_cap_passes(self) -> None:
        # Four "tech" names (AAPL/MSFT/GOOGL/AMZN per universe.yaml), each $4,000 collateral
        # at 30% IV / 30 DTE (~344 risk units): every ticker is far under its own 5,000 cap,
        # and the tech-sector total (~1,377) is far under the sector's 25,000 cap.
        acc = _account(net_liquidation=100_000.0, cash=90_000.0, maintenance_margin=0.0)
        cands = [
            _candidate(candidate_id="aapl", underlying="AAPL", collateral=4_000.0, current_iv=30.0),
            _candidate(candidate_id="msft", underlying="MSFT", collateral=4_000.0, current_iv=30.0),
            _candidate(
                candidate_id="googl", underlying="GOOGL", collateral=4_000.0, current_iv=30.0
            ),
            _candidate(candidate_id="amzn", underlying="AMZN", collateral=4_000.0, current_iv=30.0),
        ]
        verdicts = validate_candidates(cands, acc, [])
        assert all(v.verdict == Verdict.PASS for v in verdicts)
        assert all("sector_limit" not in v.reasons for v in verdicts)

    def test_sector_limit_binds_cumulatively_across_new_candidates(self) -> None:
        # D1: sector_risk is a risk-units tally. This test passes NO existing positions, so it
        # is fed only by the NEW priced candidates below (seeding it from the book requires the
        # caller to supply an IV lookup — see `seed_budgets`). Six "tech" CSPs, each $10,000
        # (at the 10,000 large-position threshold, so none of them consume the large
        # slot) at 160% IV / 28 DTE (~4,432 risk units — safely under the 5,000 ticker
        # cap on its own): the first five sum to ~22,158 (< the 25,000 sector cap) and
        # all pass; the sixth tips the cumulative to ~26,590 and is rejected for
        # sector_limit, not its own ticker concentration.
        tickers = ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "PLTR"]
        cands = [
            _candidate(candidate_id=t, underlying=t, collateral=10_000.0, dte=28, current_iv=160.0)
            for t in tickers
        ]
        acc = _account(net_liquidation=100_000.0, cash=200_000.0)
        verdicts = validate_candidates(cands, acc, [])
        vm = {v.candidate_id: v for v in verdicts}
        assert vm["PLTR"].verdict == Verdict.REJECT
        assert "sector_limit" in vm["PLTR"].reasons
        assert "concentration_limit" not in vm["PLTR"].reasons

    # --- CSP allocation cap (S1/S3) ---

    def test_csp_allocation_within_cap_passes(self) -> None:
        # D1: the CSP budget is `capital.resolve_caps`' deployable cash (excess liquidity
        # minus the reserve), not a flat % of net liquidation. One small CSP well under
        # it must not trip the cap.
        cand = _candidate(strategy=Strategy.CASH_SECURED_PUT, collateral=4_000.0, delta=-0.20)
        verdicts = validate_candidates([cand], _account(net_liquidation=100_000.0), [])
        assert "csp_allocation_limit" not in verdicts[0].reasons

    def test_csp_allocation_cap_binds_with_existing_puts(self) -> None:
        # D1: the existing short put alone (57k) already exceeds the deployable-cash-based
        # CSP budget (24,000 = 30,000 excess liquidity - a 20% reserve), so the cap binds
        # regardless of the new candidate's size — the point being that it binds AT ALL,
        # not that the new 4k tips a marginal balance (as it did under the old flat-60%
        # cap this test predates).
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
        # N5 + D1 (Finding 2, human ruling): an existing short put must count toward the
        # CSP/collateral budgets at strike collateral (strike*100*contracts = 60k), not its
        # tiny |market value| (~500). This raw position (no IV) cannot feed `ticker_risk`, so
        # the new candidate is priced on the IV-missing fallback, which now rejects on the
        # cumulative collateral breach ALONE (mirroring `capital._fits` — no AND with the
        # large-position ceiling): cumulative 60k existing + 4k new = 64k > the 10k
        # max_ticker_collateral fallback cap -> concentration_limit. The strike-collateral
        # valuation ALSO blows the cumulative CSP allocation once the short put is counted at
        # 60k rather than ~500 -> csp_allocation_limit too. Previously (pre-N5) neither would
        # have fired.
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
        # Deployable-cash CSP budget = 24,000 (30,000 excess liquidity - a 20% reserve);
        # the existing put's true 60k strike collateral blows straight through it. The same
        # 60k also blows the 10,000 max_ticker_collateral fallback cap once the new 4k is added.
        verdicts = validate_candidates([cand], _account(net_liquidation=100_000.0), [existing_put])
        assert "csp_allocation_limit" in verdicts[0].reasons
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
# risk_engine.py — D1: concentration measured in RISK UNITS, not raw collateral
# ---------------------------------------------------------------------------


class TestConcentrationInRiskUnits:
    def test_gate_accepts_a_high_priced_name_within_risk_units(self) -> None:
        """D1: a $65k META put at 35% IV is ~$5.5k of risk units, inside a 5%-of-300k cap."""
        cand = _csp_candidate(underlying="META", strike=650.0, contracts=1, current_iv=35.0, dte=21)
        account = _account(net_liq=300_000.0, cash=100_000.0)
        verdicts = validate_candidates([cand], account, [])
        assert verdicts[0].verdict.value == "pass", verdicts[0].reasons

    def test_gate_rejects_a_cheap_high_vol_name_that_is_large_in_risk_units(self) -> None:
        """MARA at 110% IV must be charged for its volatility, not just its collateral.
        With 10 contracts (the max) at strike 70, collateral is $70k at 110% IV / 21 DTE
        ~= $18.4k risk units, past the $15k cap."""
        cand = _csp_candidate(
            underlying="MARA", strike=70.0, contracts=10, current_iv=110.0, dte=21
        )
        account = _account(net_liq=300_000.0, cash=100_000.0)
        verdicts = validate_candidates([cand], account, [])
        assert verdicts[0].verdict.value == "reject"
        assert "concentration_limit" in verdicts[0].reasons

    def test_gate_falls_back_to_collateral_when_iv_is_missing(self) -> None:
        """With no IV to size a risk-unit charge from, the gate falls back to the stricter
        raw-collateral cap and rejects on the cumulative breach alone — mirroring
        `capital._fits`'s identical fallback, so the gate is never looser than the sizer that
        feeds it (D1 human ruling, Finding 2)."""
        cand = _csp_candidate(underlying="META", strike=650.0, contracts=1, current_iv=None, dte=21)
        account = _account(net_liq=300_000.0, cash=100_000.0)
        verdicts = validate_candidates([cand], account, [])
        # $65k cumulative > the 10%-of-NLV ($30k) collateral fallback cap.
        assert verdicts[0].verdict.value == "reject"
        assert "concentration_limit" in verdicts[0].reasons

    def test_covered_calls_still_consume_no_budget(self) -> None:
        """CCs are written against shares already owned — unchanged by the new model."""
        cand = _cc_candidate(underlying="AAPL", strike=250.0, contracts=5)
        assert cand.strategy == Strategy.COVERED_CALL
        account = _account(net_liq=300_000.0, cash=0.0)  # no cash at all
        verdicts = validate_candidates([cand], account, [])
        assert "buying_power_buffer" not in verdicts[0].reasons
        assert "concentration_limit" not in verdicts[0].reasons

    def test_existing_option_position_charges_the_ticker_risk_budget(self) -> None:
        """Final-review Critical: concentration is measured in risk units, so an existing
        option position has to be *seeded* in risk units — otherwise it counts as zero against
        the per-ticker cap on the common path where the candidate's own IV is known, and the
        cap only ever constrains candidates against each other, never against the book.

        50 MARA 15-strike puts = $75,000 collateral at 70% IV / 30 DTE = ~15,054 risk units,
        already past the $15,000 cap (5% of $300k NLV): one more lot must not fit."""
        existing = PositionSnapshot(
            symbol="MARA  260918P00015000",
            sec_type="OPT",
            position=-50.0,
            avg_cost=100.0,
            right=OptionRight.PUT,
            strike=15.0,
            expiry=date.today() + timedelta(days=30),
            underlying="MARA",
            market_value=-2_000.0,
        )
        cand = _csp_candidate(underlying="MARA", strike=15.0, contracts=1, current_iv=70.0, dte=21)
        account = _account(net_liq=300_000.0, cash=300_000.0)
        verdicts = validate_candidates([cand], account, [existing], iv_by_symbol={"MARA": 70.0})
        assert verdicts[0].verdict.value == "reject"
        assert "concentration_limit" in verdicts[0].reasons

    def test_existing_exposure_binds_the_gate_without_an_iv_map(self) -> None:
        """The backstop for the callers that cannot supply `iv_by_symbol` — the order-approval
        re-validation gate and the single-ticker deep-dive, both of which would need a new
        network round-trip to get one.

        With `ticker_risk` unseeded, the candidate's own risk units ($252) sit far under the
        $15,000 cap and say nothing about the book. The cumulative raw-collateral comparison in
        the large-position check is what catches it: $75,000 already held + $1,500 new is past
        the 25%-of-NLV ceiling. Comparing the candidate's marginal $1,500 alone (as it did
        before) skipped the check entirely."""
        existing = PositionSnapshot(
            symbol="MARA  260918P00015000",
            sec_type="OPT",
            position=-50.0,
            avg_cost=100.0,
            right=OptionRight.PUT,
            strike=15.0,
            expiry=date.today() + timedelta(days=30),
            underlying="MARA",
            market_value=-2_000.0,
        )
        cand = _csp_candidate(underlying="MARA", strike=15.0, contracts=1, current_iv=70.0, dte=21)
        account = _account(net_liq=300_000.0, cash=300_000.0)

        verdicts = validate_candidates([cand], account, [existing])  # no iv_by_symbol
        assert verdicts[0].verdict.value == "reject"
        assert "concentration_limit" in verdicts[0].reasons

        # The same candidate against an empty book still passes — it is the existing exposure
        # that binds, not the candidate's own size (D1: one large lot stays reachable).
        clean = validate_candidates([cand], account, [])
        assert clean[0].verdict.value == "pass", clean[0].reasons

    def test_seeded_sector_risk_binds_across_the_existing_book(self) -> None:
        """The same seeding feeds the SECTOR tally, which `seed_budgets` previously only ever
        `setdefault`-ed to 0.0 — so a sector could never be full before this scan started."""
        held = [
            PositionSnapshot(
                symbol=f"{sym} PUT",
                sec_type="OPT",
                position=-10.0,
                avg_cost=100.0,
                right=OptionRight.PUT,
                strike=150.0,
                expiry=date.today() + timedelta(days=30),
                underlying=sym,
                market_value=-2_000.0,
            )
            for sym in ("AAPL", "MSFT")
        ]  # 2 x $150,000 collateral at 100% IV / 30 DTE = ~$86,000 of "tech" risk units
        cand = _csp_candidate(underlying="GOOGL", strike=100.0, contracts=1, current_iv=30.0)
        account = _account(net_liq=300_000.0, cash=500_000.0)
        verdicts = validate_candidates(
            [cand], account, held, iv_by_symbol={"AAPL": 100.0, "MSFT": 100.0}
        )
        # tech sector cap = 25% of $300k = $75,000 risk units; the book alone is already past it,
        # while GOOGL's own ticker budget (~$860 of $15,000) is untouched.
        assert "sector_limit" in verdicts[0].reasons
        assert "concentration_limit" not in verdicts[0].reasons

    def test_second_large_position_hits_the_slot_cap(self) -> None:
        """max_large_positions defaults to 1. Two DIFFERENT (unmapped-sector) tickers, each
        $40,000 collateral at 20% IV / 21 DTE (~1,919 risk units — nowhere near the 15,000
        ticker-risk cap on its own): $40,000 clears the 30,000 ticker-collateral threshold
        (10% of 300k) but sits well under the 75,000 large ceiling (25%), so the first
        candidate consumes the account's one large-position slot and passes; the second,
        on a different ticker so neither the ticker-risk nor sector caps mask it, finds the
        slot already taken."""
        cand_a = _csp_candidate(
            underlying="ZZZ1", strike=400.0, contracts=1, current_iv=20.0, dte=21
        )
        cand_b = _csp_candidate(
            underlying="ZZZ2", strike=400.0, contracts=1, current_iv=20.0, dte=21
        )
        account = _account(net_liq=300_000.0, cash=200_000.0)
        verdicts = validate_candidates([cand_a, cand_b], account, [])
        vm = {v.candidate_id: v for v in verdicts}
        assert vm[cand_a.candidate_id].verdict.value == "pass", vm[cand_a.candidate_id].reasons
        assert vm[cand_b.candidate_id].verdict.value == "reject"
        assert "large_position_slot_full" in vm[cand_b.candidate_id].reasons
        assert "concentration_limit" not in vm[cand_b.candidate_id].reasons


class TestBudgetDedupeAcrossSameSymbol:
    """The 2026-09-11 fix: a symbol's own candidates must not compete against each other
    for its shared per-ticker/sector/CSP/cash budget. Exactly one candidate per
    (underlying, strategy) — the highest-scoring pass-1 survivor — ever reaches the
    cumulative checks; every other survivor in the group is rejected with
    "dedupe_pre_gate" without the shared budget being touched at all."""

    def test_only_the_best_scoring_sibling_reaches_the_budget(self) -> None:
        # Three TQQQ CSPs, same collateral/IV/DTE as the old
        # test_cumulative_concentration_across_same_ticker fixture (each ~2,216 risk units,
        # well under the 5,000 ticker-risk cap on its own) but DIFFERENT blended_score, so
        # there's an unambiguous "best" one. Under the old greedy-per-candidate design all
        # three would be walked through the budget in list order and the first two would
        # both pass (4,432 <= 5,000); under the two-pass design only the highest-scoring one
        # (c_best) is ever tested against the budget, and it must pass alone.
        c_low = _candidate(
            candidate_id="c_low",
            underlying="TQQQ",
            collateral=10_000.0,
            dte=28,
            current_iv=80.0,
            scores=_scores(
                iv=40, technical=40, fundamental=40, liquidity=40, assignment=40, symbol="TQQQ"
            ),
        )
        c_best = _candidate(
            candidate_id="c_best",
            underlying="TQQQ",
            collateral=10_000.0,
            dte=28,
            current_iv=80.0,
            scores=_scores(
                iv=90, technical=90, fundamental=90, liquidity=90, assignment=90, symbol="TQQQ"
            ),
        )
        c_mid = _candidate(
            candidate_id="c_mid",
            underlying="TQQQ",
            collateral=10_000.0,
            dte=28,
            current_iv=80.0,
            scores=_scores(
                iv=65, technical=65, fundamental=65, liquidity=65, assignment=65, symbol="TQQQ"
            ),
        )
        # score_candidates sorts DESC by blended_score — feed validate_candidates already
        # sorted, exactly as scan.py does.
        scored = score_candidates([c_low, c_best, c_mid])
        verdicts = validate_candidates(scored, _account(net_liquidation=100_000.0), [])
        vm = {v.candidate_id: v for v in verdicts}

        assert vm["c_best"].verdict == Verdict.PASS, vm["c_best"].reasons
        assert vm["c_low"].verdict == Verdict.REJECT
        assert vm["c_low"].reasons == ["dedupe_pre_gate"]
        assert vm["c_mid"].verdict == Verdict.REJECT
        assert vm["c_mid"].reasons == ["dedupe_pre_gate"]

    def test_different_symbols_still_compete_for_the_shared_budget_by_score(self) -> None:
        # Cross-symbol behaviour (the actual reason the greedy-by-score design exists) must
        # be untouched: two DIFFERENT tickers, each individually under the ticker-risk cap,
        # but together they blow the shared deployable-cash buffer. The higher-scored one
        # (by feed order, since score_candidates sorts DESC) still wins the shared resource.
        acc = _account(net_liquidation=100_000.0, cash=16_000.0, maintenance_margin=10_000.0)
        c_a = _candidate(
            candidate_id="a",
            underlying="AAPL",
            collateral=4_000.0,
            scores=_scores(iv=90, technical=90, fundamental=90, liquidity=90, assignment=90),
        )
        c_b = _candidate(
            candidate_id="b",
            underlying="MSFT",
            collateral=4_000.0,
            scores=_scores(
                iv=10, technical=10, fundamental=10, liquidity=10, assignment=10, symbol="MSFT"
            ),
        )
        scored = score_candidates([c_a, c_b])
        verdicts = validate_candidates(scored, acc, [])
        vm = {v.candidate_id: v for v in verdicts}
        assert vm["a"].verdict == Verdict.PASS  # higher score, spends the buffer first
        assert vm["b"].verdict == Verdict.REJECT
        assert "buying_power_buffer" in vm["b"].reasons

    def test_representative_that_fails_the_budget_is_not_replaced_by_a_sibling(self) -> None:
        # Deliberate, documented non-goal (see the plan's Background section): if the sole
        # representative fails a cumulative check, the whole group is done for this cycle —
        # no retry against a lower-scored sibling.
        acc = _account(net_liquidation=100_000.0, cash=100_000.0)
        c_best = _candidate(
            candidate_id="c_best",
            underlying="MARA",
            collateral=60_000.0,  # blows the 10%-of-NLV (10,000) raw-collateral fallback cap
            current_iv=None,
            scores=_scores(
                iv=90, technical=90, fundamental=90, liquidity=90, assignment=90, symbol="MARA"
            ),
        )
        c_small = _candidate(
            candidate_id="c_small",
            underlying="MARA",
            collateral=1_000.0,  # would easily fit alone
            current_iv=None,
            scores=_scores(
                iv=10, technical=10, fundamental=10, liquidity=10, assignment=10, symbol="MARA"
            ),
        )
        scored = score_candidates([c_best, c_small])
        verdicts = validate_candidates(scored, acc, [])
        vm = {v.candidate_id: v for v in verdicts}
        assert vm["c_best"].verdict == Verdict.REJECT
        assert "concentration_limit" in vm["c_best"].reasons
        assert vm["c_small"].verdict == Verdict.REJECT
        assert vm["c_small"].reasons == ["dedupe_pre_gate"]

    def test_covered_calls_are_not_grouped_or_deduped(self) -> None:
        # CCs never touch the shared budget (adds_new_exposure is False for them), so
        # multiple CC strikes on the same underlying must ALL be able to pass — the
        # pre-gate dedupe must only ever apply to strategies that add new exposure.
        pos = PositionSnapshot(
            symbol="AAPL", sec_type="STK", position=200.0, avg_cost=150.0, market_value=30_000.0
        )
        cc_a = _cc_candidate(underlying="AAPL", strike=180.0, contracts=1)
        cc_b = _cc_candidate(underlying="AAPL", strike=190.0, contracts=1)
        verdicts = validate_candidates(
            score_candidates([cc_a, cc_b]), _account(net_liquidation=100_000.0), [pos]
        )
        assert all(v.verdict == Verdict.PASS for v in verdicts)

    def test_rolls_are_not_grouped_or_deduped(self) -> None:
        # M1: a ROLL replaces an existing short leg that `positions` already counts, so it
        # adds no new exposure and never reaches the shared budget — exactly like a CC.
        # Two rolls on one underlying, each with collateral far past the 10%-of-NLV
        # raw-collateral cap, must therefore BOTH pass: neither may be charged against the
        # budget, and neither may be dedupe_pre_gate'd out of the way of the other.
        roll_a = _candidate(
            candidate_id="roll_a",
            strategy=Strategy.ROLL,
            underlying="MARA",
            collateral=60_000.0,
            scores=_scores(
                iv=90, technical=90, fundamental=90, liquidity=90, assignment=90, symbol="MARA"
            ),
        )
        roll_b = _candidate(
            candidate_id="roll_b",
            strategy=Strategy.ROLL,
            underlying="MARA",
            collateral=60_000.0,
            scores=_scores(
                iv=10, technical=10, fundamental=10, liquidity=10, assignment=10, symbol="MARA"
            ),
        )
        verdicts = validate_candidates(
            score_candidates([roll_a, roll_b]), _account(net_liquidation=100_000.0), []
        )
        vm = {v.candidate_id: v for v in verdicts}
        assert vm["roll_a"].verdict == Verdict.PASS, vm["roll_a"].reasons
        assert vm["roll_b"].verdict == Verdict.PASS, vm["roll_b"].reasons
        assert all("dedupe_pre_gate" not in v.reasons for v in verdicts)


class TestDedupeOptOut:
    """C1 (final-review fix): `dedupe_same_symbol=False` restores the pre-fix single-pass
    behaviour for the one caller that must never pick a winner — the `/scan TICKER`
    deep-dive, a browse/compare view whose whole point is showing every strike that
    individually qualifies. The real safety backstop for that path is the order-approval
    re-validation gate, which keeps the dedupe ON."""

    def _two_siblings(self) -> list[TradeCandidate]:
        # Two TQQQ CSPs that BOTH fit the shared budget together: ~2,216 risk units each
        # against the 5,000 ticker-risk cap, and 20,000 of collateral against the 20,000
        # deployable-cash / CSP caps. Nothing here is scarce — the only thing that can
        # reject the runner-up is the pre-gate dedupe itself.
        low = _candidate(
            candidate_id="c_low",
            underlying="TQQQ",
            collateral=10_000.0,
            dte=28,
            current_iv=80.0,
            scores=_scores(
                iv=40, technical=40, fundamental=40, liquidity=40, assignment=40, symbol="TQQQ"
            ),
        )
        best = _candidate(
            candidate_id="c_best",
            underlying="TQQQ",
            collateral=10_000.0,
            dte=28,
            current_iv=80.0,
            scores=_scores(
                iv=90, technical=90, fundamental=90, liquidity=90, assignment=90, symbol="TQQQ"
            ),
        )
        return score_candidates([low, best])

    def test_opting_out_lets_every_qualifying_sibling_pass(self) -> None:
        verdicts = validate_candidates(
            self._two_siblings(),
            _account(net_liquidation=100_000.0),
            [],
            dedupe_same_symbol=False,
        )
        vm = {v.candidate_id: v for v in verdicts}
        assert vm["c_best"].verdict == Verdict.PASS, vm["c_best"].reasons
        assert vm["c_low"].verdict == Verdict.PASS, vm["c_low"].reasons
        assert all("dedupe_pre_gate" not in v.reasons for v in verdicts)

    def test_the_default_still_dedupes_the_identical_input(self) -> None:
        # Same fixture, default argument — proves the opt-out is what changed the outcome,
        # not the fixture being too easy to reject.
        verdicts = validate_candidates(
            self._two_siblings(), _account(net_liquidation=100_000.0), []
        )
        vm = {v.candidate_id: v for v in verdicts}
        assert vm["c_best"].verdict == Verdict.PASS, vm["c_best"].reasons
        assert vm["c_low"].verdict == Verdict.REJECT
        assert vm["c_low"].reasons == ["dedupe_pre_gate"]

    def test_opting_out_still_consumes_the_shared_budget_greedily(self) -> None:
        # The opt-out removes the grouping, NOT the cumulative budget: with the deployable
        # cash sized for one of the two, the higher-scored sibling still wins it and the
        # other is rejected for the real economic reason, not for being a duplicate.
        acc = _account(net_liquidation=100_000.0, cash=16_000.0, maintenance_margin=10_000.0)
        c_a = _candidate(
            candidate_id="a",
            underlying="TQQQ",
            collateral=4_000.0,
            scores=_scores(
                iv=90, technical=90, fundamental=90, liquidity=90, assignment=90, symbol="TQQQ"
            ),
        )
        c_b = _candidate(
            candidate_id="b",
            underlying="TQQQ",
            collateral=4_000.0,
            scores=_scores(
                iv=10, technical=10, fundamental=10, liquidity=10, assignment=10, symbol="TQQQ"
            ),
        )
        verdicts = validate_candidates(
            score_candidates([c_a, c_b]), acc, [], dedupe_same_symbol=False
        )
        vm = {v.candidate_id: v for v in verdicts}
        assert vm["a"].verdict == Verdict.PASS, vm["a"].reasons
        assert vm["b"].verdict == Verdict.REJECT
        assert "buying_power_buffer" in vm["b"].reasons
        assert "dedupe_pre_gate" not in vm["b"].reasons


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
# risk_engine.py — D2: variance-risk-premium floor promoted from display to gate
# ---------------------------------------------------------------------------


def test_gate_rejects_premium_below_fair_value():
    """D2: selling at or below BS-fair-value-at-realised-vol earns no edge."""
    from src.common.schemas import IdealZone, OptionRight
    from src.engine.risk_engine import validate_candidates

    zone = IdealZone(symbol="MARA", right=OptionRight.PUT, dte=21, spot=15.0, min_credit=0.90)
    cand = _csp_candidate(
        underlying="MARA", strike=15.0, contracts=1, current_iv=110.0, dte=21, premium=0.50
    ).model_copy(update={"ideal": zone})
    verdicts = validate_candidates([cand], _account(), [])
    assert "premium_below_fair_value" in verdicts[0].reasons


def test_gate_accepts_a_low_iv_name_paying_a_real_edge():
    """SPY at 13.5% IV was rejected by the flat 1% ROC floor regardless of edge."""
    from src.common.schemas import IdealZone, OptionRight
    from src.engine.risk_engine import validate_candidates

    zone = IdealZone(symbol="SPY", right=OptionRight.PUT, dte=21, spot=660.0, min_credit=1.80)
    cand = _csp_candidate(
        underlying="SPY", strike=640.0, contracts=1, current_iv=13.5, dte=21, premium=2.10
    ).model_copy(update={"ideal": zone, "roc_pct": 0.33, "annualized_yield_pct": 4.0})
    verdicts = validate_candidates([cand], _account(net_liq=2_000_000.0, cash=500_000.0), [])
    assert verdicts[0].verdict.value == "pass", verdicts[0].reasons


def test_missing_ideal_zone_never_blocks():
    """A candidate with no computable zone is data-unavailable, not a rejection."""
    from src.engine.risk_engine import validate_candidates

    cand = _csp_candidate(underlying="AAPL", strike=200.0, contracts=1, current_iv=28.0, dte=21)
    assert cand.ideal is None
    verdicts = validate_candidates([cand], _account(), [])
    assert "premium_below_fair_value" not in verdicts[0].reasons


# ---------------------------------------------------------------------------
# risk_engine.py — the income gates (ROC floor, annualized-yield floor, and the D2
# variance-risk-premium floor) are scoped to the INCOME strategies. A defensive roll
# is a repair, not an income trade: it books roc_pct = 0.0 by construction and pays a
# premium deliberately under the new strike's fair value, so leaving it inside those
# gates rejected every defensive roll at the approval-queue re-gate — after the
# operator had already approved it. `strategies/rolling.py`'s own max_debit /
# min_delta_reduction bounds are the real economic control for a roll; `cand.ideal`
# stays populated and visible on the card, it just no longer rejects.
# ---------------------------------------------------------------------------


def test_defensive_roll_is_not_rejected_by_the_income_gates():
    """A defensive roll (zero ROC, premium under the zone's min_credit) must pass."""
    from src.common.schemas import IdealZone, OptionRight
    from src.engine.risk_engine import validate_candidates

    zone = IdealZone(symbol="MARA", right=OptionRight.PUT, dte=30, spot=15.0, min_credit=0.90)
    cand = _candidate(strategy=Strategy.ROLL, underlying="MARA", right=OptionRight.PUT).model_copy(
        update={"premium": 0.50, "ideal": zone, "roc_pct": 0.0, "annualized_yield_pct": 0.0}
    )
    verdicts = validate_candidates([cand], _account(), [])
    assert verdicts[0].verdict == Verdict.PASS, verdicts[0].reasons
    assert "premium_below_fair_value" not in verdicts[0].reasons
    assert "roc_below_minimum" not in verdicts[0].reasons
    assert "yield_below_minimum" not in verdicts[0].reasons


def test_the_same_income_gates_still_bite_a_csp():
    """The scoping is per-strategy, not a global bypass: an identical CSP is still rejected."""
    from src.common.schemas import IdealZone, OptionRight
    from src.engine.risk_engine import validate_candidates

    zone = IdealZone(symbol="MARA", right=OptionRight.PUT, dte=30, spot=15.0, min_credit=0.90)
    cand = _candidate(
        strategy=Strategy.CASH_SECURED_PUT, underlying="MARA", right=OptionRight.PUT
    ).model_copy(
        update={"premium": 0.50, "ideal": zone, "roc_pct": 0.0, "annualized_yield_pct": 0.0}
    )
    verdicts = validate_candidates([cand], _account(), [])
    assert verdicts[0].verdict == Verdict.REJECT
    assert "premium_below_fair_value" in verdicts[0].reasons
    assert "roc_below_minimum" in verdicts[0].reasons


def test_gate_accepts_a_roll_premium_that_clears_fair_value():
    """A roll collecting more than fair value clears the gate, same as any other strategy."""
    from src.common.schemas import IdealZone, OptionRight
    from src.engine.risk_engine import validate_candidates

    zone = IdealZone(symbol="MARA", right=OptionRight.PUT, dte=30, spot=15.0, min_credit=0.90)
    cand = _candidate(strategy=Strategy.ROLL, underlying="MARA", right=OptionRight.PUT).model_copy(
        update={"premium": 2.10, "ideal": zone}
    )
    verdicts = validate_candidates([cand], _account(), [])
    assert "premium_below_fair_value" not in verdicts[0].reasons


def test_require_vrp_edge_false_bypasses_the_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """The bypass knob genuinely disables the gate, not just defaults it off."""
    import src.engine.risk_engine as risk_engine_module
    from src.common.config import get_config
    from src.common.schemas import IdealZone, OptionRight
    from src.engine.risk_engine import validate_candidates

    patched_cfg = get_config().model_copy(deep=True)
    patched_cfg.risk["income"]["require_vrp_edge"] = False

    monkeypatch.setattr(risk_engine_module, "get_config", lambda: patched_cfg)

    zone = IdealZone(symbol="MARA", right=OptionRight.PUT, dte=21, spot=15.0, min_credit=0.90)
    cand = _csp_candidate(
        underlying="MARA", strike=15.0, contracts=1, current_iv=110.0, dte=21, premium=0.50
    ).model_copy(update={"ideal": zone})
    verdicts = validate_candidates([cand], _account(), [])
    assert "premium_below_fair_value" not in verdicts[0].reasons
