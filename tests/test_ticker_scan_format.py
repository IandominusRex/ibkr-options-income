"""Tests for the single-ticker /scan card (format_ticker_scan_result).

Covers the enrichments layered on top of the deterministic snapshot:
  1. Claude/Ollama verdict rendered beneath the best CC / CSP candidate.
  2. Rejection-reason line shown when a strategy turns up no qualifying option.
  3. Near-miss ("closest contract") block when nothing qualified.
  4. Honest sources footer (reflects actual spot/Greeks provenance).
  5. Premium-environment read derived from IV rank + VRP.
"""

from __future__ import annotations

from datetime import date, timedelta

from src.common.schemas import (
    ClaudeReview,
    FundamentalStats,
    IVStats,
    OptionRight,
    ScoreCard,
    Strategy,
    TechnicalStats,
    TradeCandidate,
)
from src.notify.formatters import (
    _humanize_reject_reason,
    _premium_read,
    _reject_reason_line,
    format_ticker_scan_result,
)


def _iv(symbol: str = "NVDA", iv_rank: float | None = 25.0, vrp: float | None = -5.4) -> IVStats:
    return IVStats(symbol=symbol, iv_rank=iv_rank, vrp=vrp)


def _tech(
    symbol: str = "NVDA", price: float = 210.69, price_source: str = "yfinance"
) -> TechnicalStats:
    return TechnicalStats(symbol=symbol, price=price, price_source=price_source)


def _fund(symbol: str = "NVDA") -> FundamentalStats:
    return FundamentalStats(symbol=symbol)


def _candidate(
    *,
    candidate_id: str = "csp-001",
    strategy: Strategy = Strategy.CASH_SECURED_PUT,
    right: OptionRight = OptionRight.PUT,
) -> TradeCandidate:
    return TradeCandidate(
        candidate_id=candidate_id,
        strategy=strategy,
        underlying="NVDA",
        right=right,
        strike=200.0,
        expiry=date.today() + timedelta(days=30),
        contracts=1,
        premium=3.0,
        collateral=20_000.0,
        roc_pct=1.5,
        annualized_yield_pct=18.0,
        breakeven=197.0,
        delta=-0.20,
        iv_rank=25.0,
        dte=30,
        blended_score=72.0,
        scores=ScoreCard(symbol="NVDA"),
    )


def _review(candidate_id: str, recommendation: str = "wait") -> ClaudeReview:
    return ClaudeReview(
        candidate_id=candidate_id,
        priority=1,
        recommendation=recommendation,
        why_attractive="Decent yield for the delta",
        risks="VRP negative — premium is cheap vs realized vol",
        tradeoffs="",
        assignment_considerations="",
        confidence=0.6,
    )


# ---------------------------------------------------------------------------
# Reason humanizer
# ---------------------------------------------------------------------------


def test_humanize_known_reason() -> None:
    assert _humanize_reject_reason("iv_rank_below_minimum") == "IV rank too low (poor premium)"


def test_humanize_unknown_reason_falls_back_to_desnaked() -> None:
    assert _humanize_reject_reason("some_new_gate") == "some new gate"


def test_reject_reason_line_dedupes_and_caps() -> None:
    line = _reject_reason_line(
        ["yield_below_minimum", "yield_below_minimum", "delta_out_of_range", "dte_out_of_range"]
    )
    assert line is not None
    assert line.count("annualized yield below floor") == 1
    # Capped at 3 distinct reasons.
    assert "Rejected:" in line


def test_reject_reason_line_empty_returns_none() -> None:
    assert _reject_reason_line([]) is None
    assert _reject_reason_line(None) is None


# ---------------------------------------------------------------------------
# Card rendering
# ---------------------------------------------------------------------------


def test_empty_csp_shows_rejection_reason() -> None:
    text = format_ticker_scan_result(
        ticker="NVDA",
        iv_stats=_iv(),
        tech_stats=_tech(),
        fund_stats=_fund(),
        cc_candidates=[],
        csp_candidates=[],
        buy_candidate=None,
        is_held=False,
        quotes_available=True,
        csp_reject_reasons=["yield_below_minimum", "iv_rank_below_minimum"],
    )
    assert "No qualifying CSP options" in text
    assert "Rejected:" in text
    assert "annualized yield below floor" in text


def test_empty_csp_without_reasons_stays_quiet() -> None:
    text = format_ticker_scan_result(
        ticker="NVDA",
        iv_stats=_iv(),
        tech_stats=_tech(),
        fund_stats=_fund(),
        cc_candidates=[],
        csp_candidates=[],
        buy_candidate=None,
        is_held=False,
        quotes_available=True,
    )
    assert "No qualifying CSP options" in text
    assert "Rejected:" not in text


def test_csp_candidate_renders_llm_verdict() -> None:
    cand = _candidate(candidate_id="csp-xyz")
    text = format_ticker_scan_result(
        ticker="NVDA",
        iv_stats=_iv(),
        tech_stats=_tech(),
        fund_stats=_fund(),
        cc_candidates=[],
        csp_candidates=[cand],
        buy_candidate=None,
        is_held=False,
        quotes_available=True,
        reviews=[_review("csp-xyz", recommendation="wait")],
    )
    assert "WAIT" in text
    assert "60% confidence" in text
    assert "Claude/Ollama review" in text  # footer notes the LLM was consulted


def test_no_review_omits_llm_footer() -> None:
    cand = _candidate(candidate_id="csp-xyz")
    text = format_ticker_scan_result(
        ticker="NVDA",
        iv_stats=_iv(),
        tech_stats=_tech(),
        fund_stats=_fund(),
        cc_candidates=[],
        csp_candidates=[cand],
        buy_candidate=None,
        is_held=False,
        quotes_available=True,
    )
    assert "Claude/Ollama review" not in text


# ---------------------------------------------------------------------------
# #3 Near-miss ("closest contract") block
# ---------------------------------------------------------------------------


def test_near_miss_renders_closest_contract_and_reasons() -> None:
    near = _candidate(candidate_id="csp-near")
    text = format_ticker_scan_result(
        ticker="NVDA",
        iv_stats=_iv(),
        tech_stats=_tech(),
        fund_stats=_fund(),
        cc_candidates=[],
        csp_candidates=[],
        buy_candidate=None,
        is_held=False,
        quotes_available=True,
        csp_near_miss=near,
        csp_reject_reasons=["yield_below_minimum"],
    )
    assert "Closest contract" in text
    assert "✗" in text
    assert "annualized yield below floor" in text


def test_near_miss_absent_falls_back_to_reason_line() -> None:
    text = format_ticker_scan_result(
        ticker="NVDA",
        iv_stats=_iv(),
        tech_stats=_tech(),
        fund_stats=_fund(),
        cc_candidates=[],
        csp_candidates=[],
        buy_candidate=None,
        is_held=False,
        quotes_available=True,
        csp_reject_reasons=["iv_rank_below_minimum"],
    )
    assert "Closest contract" not in text
    assert "Rejected:" in text


# ---------------------------------------------------------------------------
# #4 Honest sources footer
# ---------------------------------------------------------------------------


def test_footer_reports_ibkr_parity_spot() -> None:
    text = format_ticker_scan_result(
        ticker="NVDA",
        iv_stats=_iv(),
        tech_stats=_tech(price_source="ibkr"),
        fund_stats=_fund(),
        cc_candidates=[],
        csp_candidates=[],
        buy_candidate=None,
        is_held=False,
        quotes_available=True,
    )
    assert "IBKR spot (parity)" in text
    assert "yfinance Greeks (fallback)" not in text


def test_footer_reports_yfinance_spot_and_greeks_fallback() -> None:
    text = format_ticker_scan_result(
        ticker="NVDA",
        iv_stats=_iv(),
        tech_stats=_tech(price_source="yfinance"),
        fund_stats=_fund(),
        cc_candidates=[],
        csp_candidates=[],
        buy_candidate=None,
        is_held=False,
        quotes_available=True,
        greeks_fallback=True,
    )
    assert "yfinance spot" in text
    assert "yfinance Greeks (fallback)" in text


def test_footer_omits_chain_when_no_quotes() -> None:
    text = format_ticker_scan_result(
        ticker="NVDA",
        iv_stats=_iv(),
        tech_stats=_tech(),
        fund_stats=_fund(),
        cc_candidates=[],
        csp_candidates=[],
        buy_candidate=None,
        is_held=False,
        quotes_available=False,
    )
    assert "IBKR option chain" not in text


# ---------------------------------------------------------------------------
# #5 Premium-environment read
# ---------------------------------------------------------------------------


def test_premium_read_low_iv_negative_vrp() -> None:
    line = _premium_read(25.0, -5.4)
    assert line is not None
    assert "IV rank low" in line
    assert "options cheap vs realized" in line


def test_premium_read_high_iv_positive_vrp() -> None:
    line = _premium_read(70.0, 8.0)
    assert line is not None
    assert "elevated" in line
    assert "premium above realized" in line


def test_premium_read_none_when_no_data() -> None:
    assert _premium_read(None, None) is None


def test_premium_read_appears_in_card() -> None:
    text = format_ticker_scan_result(
        ticker="NVDA",
        iv_stats=_iv(iv_rank=25.0, vrp=-5.4),
        tech_stats=_tech(),
        fund_stats=_fund(),
        cc_candidates=[],
        csp_candidates=[],
        buy_candidate=None,
        is_held=False,
        quotes_available=True,
    )
    assert "💡" in text
