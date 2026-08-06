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
    IdealZone,
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
    # Parens must be MarkdownV2-escaped or Telegram rejects the whole message.
    assert "IBKR spot \\(parity\\)" in text
    assert "yfinance Greeks \\(fallback\\)" not in text


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
    # Parens must be MarkdownV2-escaped or Telegram rejects the whole message.
    assert "yfinance Greeks \\(fallback\\)" in text


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


def test_card_has_no_unescaped_markdownv2_parens() -> None:
    """Regression: the sources footer once emitted raw '(parity)'/'(fallback)' parens, which
    Telegram MarkdownV2 rejects with BadRequest — silently freezing the /scan progress message.
    The whole rendered card must never contain an unescaped reserved char."""
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
        greeks_fallback=True,
    )
    # Reserved MarkdownV2 chars that must be escaped in plain text (excluding the
    # entity markers '_' and '*' that the formatter uses intentionally).
    reserved = set(r"[]()~`>#+-=|{}.!")
    unescaped = [
        (i, c) for i, c in enumerate(text) if c in reserved and (i == 0 or text[i - 1] != "\\")
    ]
    assert not unescaped, f"unescaped MarkdownV2 chars in card: {unescaped}"


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


# ---------------------------------------------------------------------------
# Market & Sector backdrop + LLM Read summary (holistic deep-dive)
# ---------------------------------------------------------------------------


def test_market_sector_block_renders_vix_and_sector() -> None:
    from src.common.schemas import MarketConditions, SectorContext

    sc = SectorContext(
        symbol="NVDA",
        sector="Technology",
        industry="Semiconductors",
        sector_etf="XLK",
        sector_ret_1mo_pct=3.2,
        spy_ret_1mo_pct=1.4,
        symbol_ret_1mo_pct=6.1,
        rel_strength_1mo_pct=2.9,
    )
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
        market_conditions=MarketConditions(vix=18.4),
        sector_context=sc,
    )
    assert "Market & Sector" in text
    assert "VIX 18" in text
    assert "Technology" in text and "XLK" in text
    assert "outperforming" in text


def test_market_sector_block_omitted_when_no_data() -> None:
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
    assert "Market & Sector" not in text


def test_llm_read_summary_renders_once() -> None:
    cand = _candidate(candidate_id="csp-xyz")
    review = _review("csp-xyz").model_copy(
        update={
            "summary": "IV rank is low so premium is thin; the sector is leading and NVDA is "
            "outperforming — a constructive but not premium-rich setup."
        }
    )
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
        reviews=[review],
    )
    assert "🧠 *Read*" in text
    assert text.count("🧠 *Read*") == 1
    assert "premium is thin" in text


def test_macro_line_renders_term_structure_rates_and_headlines() -> None:
    from src.common.schemas import MarketConditions

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
        market_conditions=MarketConditions(
            vix=18.4,
            vix_term_ratio=1.15,
            ten_year_yield=4.31,
            ten_year_change_5d_bp=12.0,
            spy_ret_5d_pct=-0.8,
            macro_headline_score=41.0,
            macro_headline_count=7,
        ),
    )
    assert "backwardation" in text
    assert "10y 4" in text
    assert "SPY" in text
    assert "Macro headlines" in text


# ---------------------------------------------------------------------------
# Ideal zone + alternatives considered
# ---------------------------------------------------------------------------


def _zone() -> IdealZone:
    return IdealZone(
        symbol="NVDA",
        right=OptionRight.PUT,
        dte=30,
        spot=210.69,
        expected_move=14.0,
        strike_lo=193.0,
        strike_hi=196.0,
        strike_anchor=195.0,
        strike_anchors=["support $194.10", "anchored to 50d SMA $195.20"],
        min_credit=3.35,
        action_price=209.0,
        action_note="spot >= $209.00 keeps the $195.00 put ~1 sigma OTM",
        buy_below=190.0,
        buy_anchors=["support $190.00"],
        confidence="high",
    )


def _card(**kw) -> str:
    args: dict = {
        "ticker": "NVDA",
        "iv_stats": _iv(),
        "tech_stats": _tech(),
        "fund_stats": _fund(),
        "cc_candidates": [],
        "csp_candidates": [],
        "buy_candidate": None,
        "is_held": False,
        "quotes_available": True,
    }
    args.update(kw)
    return format_ticker_scan_result(**args)


def test_qualifying_candidate_shows_the_ideal_zone_beside_the_strike() -> None:
    cand = _candidate().model_copy(update={"ideal": _zone()})
    text = _card(csp_candidates=[cand])
    assert "Ideal strike" in text
    assert "193" in text and "196" in text
    assert "Ideal credit" in text
    assert "below fair value" in text  # premium 3.00 vs min_credit 3.35


def test_levels_block_names_the_action_and_share_entry_prices() -> None:
    cand = _candidate().model_copy(update={"ideal": _zone()})
    text = _card(csp_candidates=[cand])
    assert "Levels" in text
    assert "Buy shares below" in text
    assert "190" in text


def test_levels_block_survives_an_empty_screen_via_assessed() -> None:
    """Nothing qualified, but the deep-dive can still say where to act."""
    from src.common.schemas import AssessedContract, AssessmentStage

    rejected = _candidate(candidate_id="csp-rej").model_copy(update={"ideal": _zone()})
    text = _card(
        assessed=[
            AssessedContract(
                candidate=rejected,
                stage=AssessmentStage.RISK_GATE,
                reasons=["iv_rank_below_minimum"],
            )
        ]
    )
    assert "Levels" in text
    assert "Other contracts considered" in text
    assert "IV rank too low" in text


def test_alternatives_block_is_omitted_when_everything_qualified() -> None:
    from src.common.schemas import AssessedContract, AssessmentStage

    cand = _candidate()
    text = _card(
        csp_candidates=[cand],
        assessed=[AssessedContract(candidate=cand, stage=AssessmentStage.PASSED)],
    )
    assert "Other contracts considered" not in text


def test_full_card_with_every_new_block_stays_markdownv2_safe() -> None:
    """The whole reason this regression test exists: one raw paren freezes the message."""
    from src.common.schemas import AssessedContract, AssessmentStage, MarketConditions

    cand = _candidate().model_copy(update={"ideal": _zone()})
    rejected = _candidate(candidate_id="rej").model_copy(update={"ideal": _zone()})
    text = _card(
        csp_candidates=[cand],
        market_conditions=MarketConditions(
            vix=18.4,
            vix_term_ratio=1.15,
            ten_year_yield=4.31,
            ten_year_change_5d_bp=-12.0,
            spy_ret_5d_pct=-0.8,
            macro_headline_score=41.0,
            macro_headline_count=7,
        ),
        assessed=[
            AssessedContract(candidate=cand, stage=AssessmentStage.PASSED),
            AssessedContract(
                candidate=rejected, stage=AssessmentStage.GENERATOR, reasons=["illiquid"]
            ),
        ],
    )
    reserved = set(r"[]()~`>#+-=|{}.!")
    unescaped = [
        (i, c) for i, c in enumerate(text) if c in reserved and (i == 0 or text[i - 1] != "\\")
    ]
    assert not unescaped, f"unescaped MarkdownV2 chars in card: {unescaped}"


def test_assignment_considerations_rendered_under_candidate() -> None:
    cand = _candidate(candidate_id="csp-xyz")
    review = _review("csp-xyz").model_copy(
        update={"assignment_considerations": "Low 0.20 delta keeps assignment odds modest."}
    )
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
        reviews=[review],
    )
    assert "assignment odds modest" in text


def test_runner_up_qualifying_strikes_are_listed() -> None:
    """The card leads with the best contract; without this the alternatives a trader would
    actually weigh against it are invisible."""
    best = _candidate(candidate_id="a")
    second = _candidate(candidate_id="b").model_copy(update={"strike": 195.0, "premium": 2.4})
    third = _candidate(candidate_id="c").model_copy(update={"strike": 190.0, "premium": 1.8})
    fourth = _candidate(candidate_id="d").model_copy(update={"strike": 185.0, "premium": 1.2})
    text = _card(csp_candidates=[best, second, third, fourth])
    assert "Also qualifying" in text
    assert "195" in text and "190" in text
    assert "and 1 more qualifying" in text  # the 4th is truncated, but counted


def test_no_alternatives_line_for_a_single_qualifying_strike() -> None:
    text = _card(csp_candidates=[_candidate()])
    assert "Also qualifying" not in text
