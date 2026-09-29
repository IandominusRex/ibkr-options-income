"""Tests for always-return-assessed-contracts (the "why was nothing approved?" path).

Before this, a contract rejected by a strategy generator was dropped with a bare `continue`
and survived only as an aggregate log counter — so a symbol whose entire chain failed the
delta band produced no candidate, no near-miss, and no explanation.

Covers:
  1. Generators return rejects with *all* the gates each failed, not just the first.
  2. Reject ranking — closest-to-passing first.
  3. Post-gate drops (dedupe / top-N) are reported instead of vanishing.
  4. format_assessed_contracts rendering + MarkdownV2 safety.
  5. The ideal zone reaching the cards.
"""

from __future__ import annotations

from datetime import date, timedelta

from src.common.schemas import (
    AccountSnapshot,
    AssessedContract,
    AssessmentStage,
    FundamentalStats,
    IdealZone,
    IVStats,
    OptionQuote,
    OptionRight,
    PositionSnapshot,
    ScoreCard,
    Strategy,
    TechnicalStats,
    TradeCandidate,
)
from src.engine.decision_engine import select_top_candidates_detailed
from src.notify.formatters import format_assessed_contracts, format_candidate
from src.strategies._evaluation import (
    REASON_DELTA_RANGE,
    REASON_DTE_RANGE,
    REASON_ILLIQUID,
    REASON_ROC,
    REASON_YIELD,
    ScreenResult,
    rank_rejects,
)
from src.strategies.cash_secured_put import screen_csp_candidates
from src.strategies.covered_call import screen_cc_candidates

_EXPIRY = date.today() + timedelta(days=20)


def _quote(
    right: OptionRight = OptionRight.PUT,
    *,
    strike: float = 190.0,
    delta: float | None = -0.20,
    bid: float | None = 3.0,
    ask: float | None = 3.2,
    expiry: date | None = None,
    oi: int | None = 500,
    volume: int | None = 100,
) -> OptionQuote:
    return OptionQuote(
        underlying="AAPL",
        right=right,
        strike=strike,
        expiry=expiry or _EXPIRY,
        bid=bid,
        ask=ask,
        delta=delta,
        open_interest=oi,
        volume=volume,
    )


def _account() -> AccountSnapshot:
    return AccountSnapshot(
        account="DU1",
        net_liquidation=500_000.0,
        total_cash=400_000.0,
        buying_power=400_000.0,
        maintenance_margin=0.0,
        excess_liquidity=400_000.0,
    )


def _long_stock(avg_cost: float = 180.0) -> PositionSnapshot:
    return PositionSnapshot(symbol="AAPL", sec_type="STK", position=500.0, avg_cost=avg_cost)


def _iv() -> IVStats:
    return IVStats(symbol="AAPL", iv_rank=50.0, current_iv=35.0, hv_30=28.0)


def _tech() -> TechnicalStats:
    return TechnicalStats(symbol="AAPL", price=200.0)


def _fund() -> FundamentalStats:
    return FundamentalStats(symbol="AAPL", quality_flag=True)


def _cand(
    cid: str,
    *,
    underlying: str = "AAPL",
    strategy: Strategy = Strategy.CASH_SECURED_PUT,
    score: float = 70.0,
    strike: float = 190.0,
    delta: float | None = -0.20,
    roc: float = 1.5,
) -> TradeCandidate:
    return TradeCandidate(
        candidate_id=cid,
        strategy=strategy,
        underlying=underlying,
        right=OptionRight.PUT,
        strike=strike,
        expiry=_EXPIRY,
        contracts=1,
        premium=3.0,
        collateral=19_000.0,
        roc_pct=roc,
        annualized_yield_pct=18.0,
        breakeven=187.0,
        delta=delta,
        dte=30,
        blended_score=score,
        scores=ScoreCard(symbol=underlying),
    )


# ---------------------------------------------------------------------------
# 1. Generators return rejects
# ---------------------------------------------------------------------------


def test_csp_screen_reports_a_reject_for_a_far_delta_contract() -> None:
    screen = screen_csp_candidates(
        "AAPL", [_quote(delta=-0.02)], _account(), _iv(), _tech(), _fund()
    )
    assert screen.passed == []
    assert len(screen.rejected) == 1
    cand, reasons = screen.rejected[0]
    assert REASON_DELTA_RANGE in reasons
    assert cand.strike == 190.0  # a real, nameable contract — not just a counter


def test_a_reject_carries_every_gate_it_failed_not_just_the_first() -> None:
    """Multiple simultaneous failures must all be reported, or ranking by closeness lies."""
    screen = screen_csp_candidates(
        "AAPL",
        [_quote(delta=-0.02, expiry=date.today() + timedelta(days=3), oi=1, volume=0)],
        _account(),
        _iv(),
        _tech(),
        _fund(),
    )
    _, reasons = screen.rejected[0]
    assert REASON_DELTA_RANGE in reasons
    assert REASON_DTE_RANGE in reasons
    # oi=1 always fails illiquid_oi_low regardless of wall-clock time; volume=0 only adds
    # illiquid_volume_low once the N19 morning cutoff has passed, so assert on the
    # time-independent granular code rather than the legacy collapsed one.
    assert "illiquid_oi_low" in reasons


def test_csp_screen_still_passes_a_good_contract() -> None:
    screen = screen_csp_candidates("AAPL", [_quote()], _account(), _iv(), _tech(), _fund())
    assert len(screen.passed) == 1
    assert screen.rejected == []


def test_screen_records_why_a_symbol_was_skipped_entirely() -> None:
    screen = screen_csp_candidates("ZZZZ", [_quote()], _account(), _iv(), _tech(), _fund())
    assert screen.skipped == "not_in_would_own"
    assert screen.passed == [] and screen.rejected == []


def test_cc_screen_skips_when_no_shares_are_held() -> None:
    flat = PositionSnapshot(symbol="AAPL", sec_type="STK", position=0.0, avg_cost=0.0)
    screen = screen_cc_candidates("AAPL", [_quote(OptionRight.CALL)], flat, _iv(), _tech(), _fund())
    assert screen.skipped == "no_long_shares"


def test_cc_screen_reports_a_strike_below_cost_basis() -> None:
    screen = screen_cc_candidates(
        "AAPL",
        [_quote(OptionRight.CALL, strike=150.0, delta=0.25)],
        _long_stock(avg_cost=180.0),
        _iv(),
        _tech(),
        _fund(),
    )
    assert screen.passed == []
    _, reasons = screen.rejected[0]
    assert "strike_below_basis" in reasons


def test_a_contract_with_no_market_is_still_named() -> None:
    """No bid/ask means we can't trade it — but we can still say which strike it was."""
    screen = screen_csp_candidates(
        "AAPL", [_quote(bid=None, ask=None)], _account(), _iv(), _tech(), _fund()
    )
    cand, reasons = screen.rejected[0]
    assert "no_two_sided_market" in reasons
    assert cand.strike == 190.0


def test_tally_counts_reasons_across_rejects() -> None:
    screen = screen_csp_candidates(
        "AAPL",
        [_quote(delta=-0.02), _quote(strike=185.0, delta=-0.01)],
        _account(),
        _iv(),
        _tech(),
        _fund(),
    )
    assert screen.tally()[REASON_DELTA_RANGE] == 2


# ---------------------------------------------------------------------------
# 2. Reject ranking
# ---------------------------------------------------------------------------


def test_rank_puts_the_fewest_failures_first() -> None:
    one_gate = (_cand("a", delta=-0.22), [REASON_ROC])
    three_gates = (_cand("b", delta=-0.22), [REASON_ROC, REASON_YIELD, REASON_ILLIQUID])
    ranked = rank_rejects([three_gates, one_gate], delta_mid=0.225)
    assert ranked[0][0].candidate_id == "a"


def test_rank_breaks_ties_on_distance_from_the_delta_band_midpoint() -> None:
    near = (_cand("near", delta=-0.22), [REASON_ROC])
    far = (_cand("far", delta=-0.90), [REASON_ROC])
    ranked = rank_rejects([far, near], delta_mid=0.225)
    assert ranked[0][0].candidate_id == "near"


def test_a_reject_without_a_delta_sorts_last_within_its_group() -> None:
    with_delta = (_cand("d", delta=-0.22), [REASON_ROC])
    no_delta = (_cand("n", delta=None), [REASON_ROC])
    ranked = rank_rejects([no_delta, with_delta], delta_mid=0.225)
    assert ranked[0][0].candidate_id == "d"


# ---------------------------------------------------------------------------
# 3. Post-gate drops are reported
# ---------------------------------------------------------------------------


def test_dedupe_and_top_n_losers_are_returned_with_a_reason() -> None:
    """These used to vanish, making a full slate indistinguishable from a gated-out one."""
    cands = [
        _cand("a", underlying="AAPL", score=90),
        _cand("b", underlying="AAPL", score=80),  # same name+strategy → dedupe
        _cand("c", underlying="MSFT", score=70),
        _cand("d", underlying="NVDA", score=60),  # beyond n=2 → top_n
    ]
    top, dropped = select_top_candidates_detailed(cands, n=2)
    assert [c.candidate_id for c in top] == ["a", "c"]
    reasons = {cid: why for (c, why) in dropped for cid in [c.candidate_id]}
    assert reasons == {"b": "dedupe", "d": "top_n"}


def test_select_top_candidates_wrapper_is_unchanged() -> None:
    cands = [_cand("a", score=90), _cand("b", underlying="MSFT", score=80)]
    from src.engine.decision_engine import select_top_candidates

    assert [c.candidate_id for c in select_top_candidates(cands, n=1)] == ["a"]


# ---------------------------------------------------------------------------
# 4. Rendering
# ---------------------------------------------------------------------------


def _assessed(stage: AssessmentStage, reasons: list[str], **kw) -> AssessedContract:
    return AssessedContract(candidate=_cand("x", **kw), stage=stage, reasons=reasons)


def test_assessed_block_names_the_contract_and_the_reason() -> None:
    text = format_assessed_contracts(
        [_assessed(AssessmentStage.GENERATOR, ["iv_rank_below_minimum"])]
    )
    assert "AAPL" in text
    assert "190" in text
    assert "IV rank too low" in text


def test_assessed_block_is_empty_when_everything_passed() -> None:
    passed = AssessedContract(candidate=_cand("x"), stage=AssessmentStage.PASSED)
    assert format_assessed_contracts([passed]) == ""


def test_assessed_block_filters_by_strategy() -> None:
    items = [
        _assessed(AssessmentStage.GENERATOR, ["illiquid"]),
        AssessedContract(
            candidate=_cand("y", underlying="MSFT", strategy=Strategy.COVERED_CALL),
            stage=AssessmentStage.GENERATOR,
            reasons=["illiquid"],
        ),
    ]
    text = format_assessed_contracts(items, strategy="covered_call")
    assert "MSFT" in text and "AAPL" not in text


def test_assessed_block_truncates_and_says_how_many_are_hidden() -> None:
    items = [_assessed(AssessmentStage.GENERATOR, ["illiquid"]) for _ in range(10)]
    text = format_assessed_contracts(items, max_rows=3)
    assert "and 7 more assessed" in text


def test_generator_stage_reason_codes_are_humanized() -> None:
    for code, phrase in [
        ("no_two_sided_market", "no live bid/ask"),
        ("illiquid", "liquidity gates"),
        ("insufficient_cash", "not enough cash"),
        ("dedupe_not_surfaced", "better strike"),
        ("top_n_not_surfaced", "max new positions"),
    ]:
        text = format_assessed_contracts([_assessed(AssessmentStage.GENERATOR, [code])])
        assert phrase in text, f"{code} rendered as: {text}"


def test_assessed_block_has_no_unescaped_markdownv2_chars() -> None:
    """Regression guard: an unescaped reserved char makes Telegram reject the whole message."""
    zone = IdealZone(
        symbol="AAPL",
        right=OptionRight.PUT,
        dte=30,
        spot=200.0,
        expected_move=12.5,
        strike_lo=185.5,
        strike_hi=192.25,
        strike_anchor=188.0,
        min_credit=3.45,
        strike_anchors=["35% vol → 1σ ±$12.50 over 30d", "support $186.10"],
        action_price=200.5,
        action_note="spot ≥ $200.50 keeps the $188.00 put ~1σ OTM (now -0.2% vs that level)",
    )
    cand = _cand("x").model_copy(update={"ideal": zone})
    text = format_assessed_contracts(
        [
            AssessedContract(
                candidate=cand,
                stage=AssessmentStage.RISK_GATE,
                reasons=["iv_rank_below_minimum", "earnings_blackout"],
            )
        ]
    )
    reserved = set(r"[]()~`>#+-=|{}.!")
    unescaped = [
        (i, c) for i, c in enumerate(text) if c in reserved and (i == 0 or text[i - 1] != "\\")
    ]
    assert not unescaped, f"unescaped MarkdownV2 chars: {unescaped}"


# ---------------------------------------------------------------------------
# 5. Ideal zone on the cards
# ---------------------------------------------------------------------------


def test_generators_attach_an_ideal_zone_to_every_contract() -> None:
    screen = screen_csp_candidates("AAPL", [_quote()], _account(), _iv(), _tech(), _fund())
    assert screen.passed[0].ideal is not None
    assert screen.passed[0].ideal.expected_move is not None


def test_approval_card_shows_the_ideal_zone_next_to_the_strike() -> None:
    screen = screen_csp_candidates("AAPL", [_quote()], _account(), _iv(), _tech(), _fund())
    text = format_candidate(screen.passed[0], None)
    assert "Ideal strike" in text
    assert "Ideal credit" in text


def test_approval_card_omits_the_zone_when_none_was_derivable() -> None:
    text = format_candidate(_cand("x"), None)  # no `ideal` attached
    assert "Ideal strike" not in text


def test_approval_card_stays_markdownv2_safe_with_a_zone() -> None:
    screen = screen_csp_candidates("AAPL", [_quote()], _account(), _iv(), _tech(), _fund())
    text = format_candidate(screen.passed[0], None)
    reserved = set(r"[]~`>#+=|{}!")  # excludes chars the formatter uses as entity markers
    unescaped = [
        (i, c) for i, c in enumerate(text) if c in reserved and (i == 0 or text[i - 1] != "\\")
    ]
    assert not unescaped, f"unescaped MarkdownV2 chars: {unescaped}"


def test_screen_result_tally_of_an_empty_screen_is_empty() -> None:
    assert ScreenResult().tally() == {}
