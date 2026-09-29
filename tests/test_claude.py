"""Tests for Phase 5: Claude integration (parser, runner, prompt builder).

All tests mock subprocess.run — no live Claude CLI or TWS needed.
"""

from __future__ import annotations

import json
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from src.claude.parser import parse_claude_output
from src.claude.prompts.strategist import build_prompt
from src.claude.runner import _review_candidates_cli as review_candidates
from src.common.schemas import (
    AccountSnapshot,
    FundamentalStats,
    IVStats,
    OptionRight,
    Regime,
    ScoreCard,
    Strategy,
    TechnicalStats,
    TradeCandidate,
)

# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


def _make_account() -> AccountSnapshot:
    return AccountSnapshot(
        account="DU123456",
        net_liquidation=100_000.0,
        total_cash=50_000.0,
        buying_power=80_000.0,
        maintenance_margin=10_000.0,
        excess_liquidity=70_000.0,
    )


def _make_candidate(
    candidate_id: str = "test-001",
    strategy: Strategy = Strategy.COVERED_CALL,
    underlying: str = "AAPL",
    strike: float = 185.0,
    premium: float = 1.50,
    right: OptionRight = OptionRight.CALL,
    expiry: date = date(2026, 7, 17),
    next_earnings: date | None = None,
    breakeven: float | None = None,
) -> TradeCandidate:
    scores = ScoreCard(
        symbol=underlying,
        iv_score=72.0,
        technical_score=65.0,
        fundamental_score=80.0,
        liquidity_score=90.0,
        assignment_safety_score=70.0,
    )
    return TradeCandidate(
        candidate_id=candidate_id,
        strategy=strategy,
        underlying=underlying,
        right=right,
        strike=strike,
        expiry=expiry,
        contracts=1,
        premium=premium,
        collateral=18_000.0,
        roc_pct=0.83,
        annualized_yield_pct=18.5,
        breakeven=breakeven if breakeven is not None else round(strike - premium, 2),
        prob_otm=0.72,
        delta=0.28,
        iv_rank=65.0,
        dte=48,
        next_earnings=next_earnings,
        scores=scores,
        blended_score=74.5,
        rationale_tags=["high_iv_rank", "liquid"],
    )


def _make_valid_envelope(reviews: list[dict]) -> str:
    return json.dumps({"type": "result", "subtype": "success", "result": json.dumps(reviews)})


def _review_dict(candidate_id: str = "test-001") -> dict:
    return {
        "candidate_id": candidate_id,
        "priority": 1,
        "recommendation": "sell",
        "why_attractive": "High IV rank provides above-average premium income.",
        "risks": "Earnings next quarter could cause a gap move against position.",
        "tradeoffs": "Caps upside above strike; delta provides moderate assignment risk.",
        "assignment_considerations": "Low probability given 0.28 delta; stock quality is high.",
        "rolling_considerations": "Could roll up-and-out if stock approaches strike before expiry.",
        "confidence": 0.82,
    }


# --------------------------------------------------------------------------- #
# parse_claude_output — happy paths
# --------------------------------------------------------------------------- #


def test_parse_valid_envelope_list():
    raw = _make_valid_envelope([_review_dict()])
    reviews = parse_claude_output(raw)
    assert len(reviews) == 1
    assert reviews[0].candidate_id == "test-001"
    assert reviews[0].recommendation == "sell"
    assert reviews[0].priority == 1
    assert reviews[0].confidence == pytest.approx(0.82)


def test_parse_multiple_reviews():
    raw = _make_valid_envelope([_review_dict("a-001"), _review_dict("b-002")])
    reviews = parse_claude_output(raw)
    assert len(reviews) == 2
    assert reviews[0].candidate_id == "a-001"
    assert reviews[1].candidate_id == "b-002"


def test_parse_single_dict_wrapped_as_list():
    """Envelope result is a single dict (not a list) — should auto-wrap."""
    raw = json.dumps({"type": "result", "result": json.dumps(_review_dict())})
    reviews = parse_claude_output(raw)
    assert len(reviews) == 1


def test_parse_markdown_fenced_inner_json():
    """Claude sometimes wraps its JSON in ```json ... ``` fences."""
    inner = "```json\n" + json.dumps([_review_dict()]) + "\n```"
    raw = json.dumps({"type": "result", "result": inner})
    reviews = parse_claude_output(raw)
    assert len(reviews) == 1
    assert reviews[0].recommendation == "sell"


def test_parse_markdown_fence_no_lang():
    inner = "```\n" + json.dumps([_review_dict()]) + "\n```"
    raw = json.dumps({"type": "result", "result": inner})
    reviews = parse_claude_output(raw)
    assert len(reviews) == 1


def test_parse_optional_fields_default():
    """rolling_considerations and confidence may be absent — should use defaults."""
    item = _review_dict()
    del item["rolling_considerations"]
    del item["confidence"]
    raw = _make_valid_envelope([item])
    reviews = parse_claude_output(raw)
    assert len(reviews) == 1
    assert reviews[0].rolling_considerations == ""
    assert reviews[0].confidence is None


def test_parse_reviews_accepts_reviews_wrapper():
    """Task 10: both backends' prompts now request `{"reviews": [...]}` — the schema-constrained
    Ollama path always emits it; the parser must unwrap it regardless of backend."""
    from src.claude.parser import parse_ollama_review_output

    raw = (
        '{"reviews": [{"candidate_id": "a", "priority": 1, "recommendation": "sell", '
        '"why_attractive": "x", "risks": "y", "tradeoffs": "z", '
        '"assignment_considerations": "w"}, {"candidate_id": "b", "priority": 2, '
        '"recommendation": "wait", "why_attractive": "x", "risks": "y", "tradeoffs": "z", '
        '"assignment_considerations": "w"}]}'
    )
    assert [r.candidate_id for r in parse_ollama_review_output(raw)] == ["a", "b"]


# --------------------------------------------------------------------------- #
# parse_claude_output — failure modes
# --------------------------------------------------------------------------- #


def test_parse_recovers_json_wrapped_in_prose():
    """claude -p sometimes wraps the array in explanatory text; recover it anyway."""
    inner = json.dumps([_review_dict()])
    result_text = f"Sure — here are the candidates I'd prioritize:\n{inner}\nHope this helps!"
    raw = json.dumps({"type": "result", "result": result_text})
    reviews = parse_claude_output(raw)
    assert len(reviews) == 1
    assert reviews[0].candidate_id == "test-001"


def test_parse_malformed_outer_json():
    reviews = parse_claude_output("not json at all {{{")
    assert reviews == []


def test_parse_empty_string():
    assert parse_claude_output("") == []


def test_parse_outer_not_dict():
    assert parse_claude_output(json.dumps([1, 2, 3])) == []


def test_parse_missing_result_key():
    raw = json.dumps({"type": "result", "subtype": "error", "error": "rate limited"})
    assert parse_claude_output(raw) == []


def test_parse_invalid_inner_schema():
    """Inner JSON is valid but doesn't match ClaudeReview schema."""
    raw = json.dumps({"type": "result", "result": json.dumps([{"foo": "bar"}])})
    assert parse_claude_output(raw) == []


def test_parse_inner_not_json():
    raw = json.dumps({"type": "result", "result": "Sorry, I cannot help with that."})
    assert parse_claude_output(raw) == []


# --------------------------------------------------------------------------- #
# build_prompt
# --------------------------------------------------------------------------- #


def test_build_prompt_contains_candidate_info():
    account = _make_account()
    candidates = [_make_candidate()]
    prompt = build_prompt(candidates, account)

    assert "test-001" in prompt
    assert "AAPL" in prompt
    assert "185.00" in prompt
    assert "COVERED CALL" in prompt
    assert "74.5" in prompt  # blended_score
    assert "high_iv_rank" in prompt


def test_build_prompt_contains_account_info():
    account = _make_account()
    prompt = build_prompt([_make_candidate()], account)
    assert "100,000" in prompt
    assert "80,000" in prompt


def test_build_prompt_empty_candidates():
    assert build_prompt([], _make_account()) == ""


# --------------------------------------------------------------------------- #
# Ideal zone + macro backdrop in the prompt (enrichment only — never gates)
# --------------------------------------------------------------------------- #


def _zoned_candidate():
    """A candidate carrying an ideal zone whose band deliberately excludes its own strike."""
    from src.common.schemas import IdealZone

    cand = _make_candidate()  # strike 185.0
    return cand.model_copy(
        update={
            "ideal": IdealZone(
                symbol="AAPL",
                right=OptionRight.CALL,
                dte=30,
                spot=180.0,
                expected_move=9.0,
                strike_lo=190.0,
                strike_hi=196.0,
                strike_anchor=193.0,
                strike_anchors=["resistance $192.00"],
                min_credit=2.10,
                credit_anchors=["fair value $1.90 at HV30 24%"],
                action_price=184.0,
                action_note="spot <= $184.00 keeps the $193.00 call ~1s OTM",
                buy_below=170.0,
                confidence="high",
            )
        }
    )


def test_prompt_states_where_the_strike_should_be_and_where_it_is():
    prompt = build_prompt([_zoned_candidate()], _make_account())
    assert "Ideal strike:" in prompt
    assert "$190.00-$196.00" in prompt
    assert "OUTSIDE" in prompt  # the offered 185 strike sits below the band
    assert "resistance $192.00" in prompt


def test_prompt_flags_a_credit_below_fair_value():
    prompt = build_prompt([_zoned_candidate()], _make_account())  # premium 1.50 vs min 2.10
    assert "Ideal credit:" in prompt
    assert "is below it" in prompt
    assert "fair value $1.90" in prompt


def test_prompt_reports_a_credit_that_clears_fair_value():
    cand = _zoned_candidate()
    rich = cand.model_copy(update={"premium": 3.00})
    prompt = build_prompt([rich], _make_account())
    assert "is above it" in prompt


def test_prompt_omits_the_zone_block_when_none_was_derivable():
    prompt = build_prompt([_make_candidate()], _make_account())
    assert "Ideal strike:" not in prompt


def test_macro_backdrop_is_injected_for_the_single_ticker_deep_dive():
    from src.common.schemas import MarketConditions

    mc = MarketConditions(vix=18.4, vix_term_ratio=1.15, ten_year_yield=4.31)
    prompt = build_prompt(
        [_make_candidate()], _make_account(), market_conditions=mc, single_ticker=True
    )
    assert "MACRO BACKDROP" in prompt
    assert "backwardation" in prompt


def test_macro_backdrop_is_omitted_from_the_full_universe_prompt():
    """The full-scan prompt is shared across ~10 candidates and must stay compact."""
    from src.common.schemas import MarketConditions

    mc = MarketConditions(vix=18.4, vix_term_ratio=1.15, ten_year_yield=4.31)
    prompt = build_prompt([_make_candidate()], _make_account(), market_conditions=mc)
    assert "MACRO BACKDROP" not in prompt
    assert "VIX: 18.4" in prompt  # the one-line VIX hint is still there


def test_summary_guide_asks_the_model_to_address_the_zone():
    prompt = build_prompt([_zoned_candidate()], _make_account(), single_ticker=True)
    assert "IDEAL STRIKE / IDEAL CREDIT" in prompt
    assert "variance-risk premium" in prompt


def test_build_prompt_injects_scan_time_spot_prices():
    """N17: scan-time spot prices are injected and flagged authoritative; static block warns stale."""
    account = _make_account()
    candidates = [_make_candidate()]  # underlying AAPL
    prompt = build_prompt(candidates, account, spot_prices={"AAPL": 211.42})

    assert "SCAN-TIME SPOT PRICES" in prompt
    assert "211.42" in prompt
    assert "STALE" in prompt  # the static universe block now carries the staleness banner


def test_build_prompt_without_spot_prices_has_no_block():
    prompt = build_prompt([_make_candidate()], _make_account())
    # The static banner references the block by name, but the actual block header is absent.
    assert "authoritative — use these" not in prompt


def test_build_prompt_multiple_candidates():
    account = _make_account()
    c1 = _make_candidate("id-001", underlying="AAPL")
    c2 = _make_candidate("id-002", underlying="MSFT", strategy=Strategy.CASH_SECURED_PUT)
    prompt = build_prompt([c1, c2], account)
    assert "id-001" in prompt
    assert "id-002" in prompt


def test_build_prompt_includes_vix_regime():
    from src.common.schemas import MarketConditions

    account = _make_account()
    prompt = build_prompt(
        [_make_candidate()], account, market_conditions=MarketConditions(vix=25.0)
    )
    assert "VIX: 25.0" in prompt
    assert "elevated" in prompt


def test_build_prompt_vix_unavailable_when_none():
    account = _make_account()
    prompt = build_prompt([_make_candidate()], account)  # no market_conditions
    assert "VIX: unavailable" in prompt


def test_build_prompt_includes_vrp_line():
    account = _make_account()
    cand = _make_candidate().model_copy(update={"vrp": 4.2})
    prompt = build_prompt([cand], account)
    assert "VRP" in prompt and "+4.2%" in prompt


def test_build_prompt_full_scan_requests_summary_without_the_long_guide():
    """Task 10: `summary` is requested on every path now, but the full-universe prompt stays
    concise — it must not pull in the longer single-ticker SUMMARY GUIDE."""
    prompt = build_prompt([_make_candidate()], _make_account())
    assert '"summary"' in prompt
    assert "SUMMARY GUIDE" not in prompt


def test_build_prompt_single_ticker_requests_summary_and_guide():
    """`/scan TICKER` deep-dive asks for a `summary` and includes the explain-the-metrics guide."""
    prompt = build_prompt([_make_candidate()], _make_account(), single_ticker=True)
    assert '"summary"' in prompt
    assert "SUMMARY GUIDE" in prompt
    # The guide must steer the model to *explain* the metrics, not just restate them.
    assert "IV rank" in prompt and "VRP" in prompt


def test_build_prompt_single_ticker_injects_sector_context():
    sector_block = "=== SECTOR & MARKET BACKDROP ===\n  Sector: Technology (proxy XLK)"
    prompt = build_prompt(
        [_make_candidate()],
        _make_account(),
        sector_context=sector_block,
        single_ticker=True,
    )
    assert "SECTOR & MARKET BACKDROP" in prompt
    assert "XLK" in prompt


def test_build_prompt_sector_context_ignored_when_not_single_ticker():
    """Sector backdrop is a single-ticker concern; the full scan must not inject it."""
    prompt = build_prompt(
        [_make_candidate()],
        _make_account(),
        sector_context="=== SECTOR & MARKET BACKDROP ===\n  Sector: Technology",
        single_ticker=False,
    )
    assert "SECTOR & MARKET BACKDROP" not in prompt
    assert "AAPL" in prompt
    assert "MSFT" in prompt


def _make_analytics() -> dict[str, tuple[IVStats, TechnicalStats, FundamentalStats]]:
    """Per-symbol raw analytics for AAPL (the default candidate's underlying)."""
    iv = IVStats(
        symbol="AAPL",
        current_iv=22.1,
        hv_30=18.0,
        iv_rank=65.0,
        iv_percentile=41.0,
        iv_rv_ratio=1.18,
        term_structure_slope=0.0021,
        put_call_skew=1.2,
        vrp=4.1,
    )
    tech = TechnicalStats(
        symbol="AAPL",
        price=211.42,
        rsi_14=58.0,
        regime=Regime.SIDEWAYS,
        sma_50=200.0,
        sma_200=190.0,
        atr_ratio=1.4,
    )
    fund = FundamentalStats(
        symbol="AAPL",
        pe_ratio=28.5,
        debt_to_equity=45.0,
        free_cash_flow=12.4e9,
        dividend_yield=0.009,
        dividend_safe=True,
        ex_dividend_date=date(2026, 8, 10),
    )
    return {"AAPL": (iv, tech, fund)}


def test_build_prompt_injects_raw_analytics_signals():
    """Raw technical/fundamental/IV signals are surfaced, not just the ScoreCard composites."""
    prompt = build_prompt([_make_candidate()], _make_account(), analytics=_make_analytics())
    # Technicals
    assert "Technicals:" in prompt
    assert "RSI 58" in prompt
    assert "regime sideways" in prompt
    assert "above 50d" in prompt and "above 200d" in prompt
    assert "ATR/px 1.4%" in prompt
    # Fundamentals
    assert "Fundamentals:" in prompt
    assert "P/E 28.5" in prompt
    assert "D/E 45" in prompt
    assert "FCF +$12.4B" in prompt
    assert "div 0.9% safe" in prompt
    assert "ex-div 2026-08-10" in prompt
    # IV microstructure (previously computed but never reached the model)
    assert "IV structure:" in prompt
    assert "IV%ile 41" in prompt
    assert "IV/RV 1.18" in prompt
    assert "contango" in prompt
    assert "skew +1.20" in prompt


def test_build_prompt_without_analytics_omits_signal_block():
    prompt = build_prompt([_make_candidate()], _make_account())
    assert "Technicals:" not in prompt
    assert "IV structure:" not in prompt


def test_build_prompt_analytics_missing_symbol_is_skipped():
    """A candidate whose underlying has no analytics entry just omits the block (no crash)."""
    prompt = build_prompt(
        [_make_candidate()], _make_account(), analytics={"NVDA": _make_analytics()["AAPL"]}
    )  # noqa: E501
    assert "Technicals:" not in prompt


def test_build_prompt_full_scan_states_gate_approved():
    """Full-universe framing asserts the candidates cleared the Rules Engine."""
    prompt = build_prompt([_make_candidate()], _make_account())
    assert "already been approved by the deterministic Rules Engine" in prompt


def test_build_prompt_single_ticker_framing_is_gate_neutral():
    """Single-ticker may review near-misses, so its framing must not claim gate approval."""
    prompt = build_prompt([_make_candidate()], _make_account(), single_ticker=True)
    assert "already been approved by the deterministic Rules Engine" not in prompt
    assert "surfaced by the deterministic screen" in prompt


# --------------------------------------------------------------------------- #
# FACTS block (_candidate_facts) — Task 10
# --------------------------------------------------------------------------- #


def test_facts_state_moneyness_and_earnings_relative_to_expiry():
    from src.claude.prompts.strategist import _candidate_facts

    c = _make_candidate(
        strategy=Strategy.CASH_SECURED_PUT,
        right=OptionRight.PUT,
        strike=720.0,
        expiry=date(2026, 9, 30),
        premium=8.75,
        next_earnings=date(2026, 10, 29),
    )
    facts = "\n".join(_candidate_facts(c, spot=744.10))
    assert "F1" in facts and "3.2% BELOW spot" in facts and "out-of-the-money" in facts
    assert "AFTER expiry" in facts and "no earnings inside this trade" in facts


def test_facts_flag_earnings_inside_the_trade():
    from src.claude.prompts.strategist import _candidate_facts

    c = _make_candidate(
        strategy=Strategy.CASH_SECURED_PUT,
        right=OptionRight.PUT,
        strike=720.0,
        expiry=date(2026, 9, 30),
        premium=8.75,
        next_earnings=date(2026, 9, 25),
    )
    facts = "\n".join(_candidate_facts(c, spot=744.10))
    assert "F3" in facts and "INSIDE this trade" in facts and "event risk" in facts
    assert "5 days before expiry" in facts


def test_facts_call_moneyness_is_mirrored():
    from src.claude.prompts.strategist import _candidate_facts

    c = _make_candidate(strategy=Strategy.COVERED_CALL, right=OptionRight.CALL, strike=250.0)
    facts = "\n".join(_candidate_facts(c, spot=232.40))
    assert "ABOVE spot" in facts and "out-of-the-money call" in facts


def test_facts_iv_rank_missing_says_so_plainly():
    """Task 9 gave missing IV rank a neutral score + a tag; F5 must say so, not invent a bucket."""
    from src.claude.prompts.strategist import _candidate_facts

    c = _make_candidate().model_copy(update={"iv_rank": None})
    facts = "\n".join(_candidate_facts(c, spot=None))
    assert "F5 IV rank unavailable" in facts
    assert "RICH" not in facts and "THIN" not in facts and "NORMAL" not in facts


def test_facts_always_states_the_gate_pass():
    from src.claude.prompts.strategist import _candidate_facts

    facts = "\n".join(_candidate_facts(_make_candidate(), spot=None))
    assert "F7" in facts and "Passed every deterministic gate" in facts


def test_build_prompt_injects_facts_block():
    prompt = build_prompt([_make_candidate()], _make_account(), spot_prices={"AAPL": 211.42})
    assert "FACTS:" in prompt
    assert "F1 Strike" in prompt
    assert "F7 Passed every deterministic gate" in prompt


def test_build_prompt_includes_decision_rubric():
    prompt = build_prompt([_make_candidate()], _make_account())
    assert "=== DECISION RUBRIC ===" in prompt
    assert '"evidence"' in prompt


# --------------------------------------------------------------------------- #
# review_candidates — mocked subprocess
# --------------------------------------------------------------------------- #


def _completed_process(stdout: str, returncode: int = 0) -> MagicMock:
    mock = MagicMock()
    mock.stdout = stdout
    mock.stderr = ""
    mock.returncode = returncode
    return mock


def test_review_candidates_success():
    account = _make_account()
    candidates = [_make_candidate()]
    envelope = _make_valid_envelope([_review_dict()])

    with patch("src.claude.runner.subprocess.run", return_value=_completed_process(envelope)):
        reviews = review_candidates(candidates, account)

    assert len(reviews) == 1
    assert reviews[0].candidate_id == "test-001"


def test_review_candidates_timeout_returns_empty():
    import subprocess as _subprocess

    account = _make_account()
    candidates = [_make_candidate()]

    with patch(
        "src.claude.runner.subprocess.run",
        side_effect=_subprocess.TimeoutExpired(cmd="claude", timeout=180),
    ):
        reviews = review_candidates(candidates, account)

    assert reviews == []


def test_review_candidates_nonzero_returncode_no_stdout():
    account = _make_account()
    candidates = [_make_candidate()]

    with patch(
        "src.claude.runner.subprocess.run",
        return_value=_completed_process("", returncode=1),
    ):
        reviews = review_candidates(candidates, account)

    assert reviews == []


def test_review_candidates_disabled_by_config():
    account = _make_account()
    candidates = [_make_candidate()]

    mock_cfg = MagicMock()
    mock_cfg.enabled = False

    with patch("src.claude.runner.get_config") as mock_get_config:
        mock_get_config.return_value.claude = mock_cfg
        with patch("src.claude.runner.subprocess.run") as mock_run:
            reviews = review_candidates(candidates, account)
            mock_run.assert_not_called()

    assert reviews == []


def test_review_candidates_empty_list_no_subprocess():
    account = _make_account()

    with patch("src.claude.runner.subprocess.run") as mock_run:
        reviews = review_candidates([], account)
        mock_run.assert_not_called()

    assert reviews == []


# --------------------------------------------------------------------------- #
# N3 — headless-subprocess hardening
# --------------------------------------------------------------------------- #


def test_build_cmd_includes_hardening_flags():
    from types import SimpleNamespace

    from src.claude.runner import _build_cmd

    cfg = SimpleNamespace(
        cli_command="claude",
        output_format="json",
        max_turns=1,
        model="claude-sonnet-4-6",
        disallowed_tools="Bash Edit Write",
    )
    cmd = _build_cmd(cfg)
    assert cmd[:3] == ["claude", "--output-format", "json"]
    assert cmd[cmd.index("--max-turns") + 1] == "1"
    assert cmd[cmd.index("--model") + 1] == "claude-sonnet-4-6"
    assert cmd[cmd.index("--disallowedTools") + 1] == "Bash Edit Write"


def test_build_cmd_omits_disabled_flags():
    from types import SimpleNamespace

    from src.claude.runner import _build_cmd

    cfg = SimpleNamespace(
        cli_command="claude", output_format="json", max_turns=0, model="", disallowed_tools=""
    )
    assert _build_cmd(cfg) == ["claude", "--output-format", "json"]


def test_review_candidates_passes_hardened_cmd():
    """The live review path must invoke the CLI with the hardening flags, not bare."""
    account = _make_account()
    candidates = [_make_candidate()]
    envelope = _make_valid_envelope([_review_dict()])

    with patch(
        "src.claude.runner.subprocess.run", return_value=_completed_process(envelope)
    ) as mock_run:
        review_candidates(candidates, account)

    cmd = mock_run.call_args.args[0]
    assert "--max-turns" in cmd
    assert "--disallowedTools" in cmd


def test_review_candidates_cli_not_found():
    account = _make_account()
    candidates = [_make_candidate()]

    with patch(
        "src.claude.runner.subprocess.run", side_effect=FileNotFoundError("claude not found")
    ):
        reviews = review_candidates(candidates, account)

    assert reviews == []


def test_review_candidates_retry_on_transient_failure():
    """First call returns non-zero + empty stdout; second call succeeds."""
    account = _make_account()
    candidates = [_make_candidate()]
    envelope = _make_valid_envelope([_review_dict()])

    fail = _completed_process("", returncode=1)
    success = _completed_process(envelope, returncode=0)

    with patch("src.claude.runner.subprocess.run", side_effect=[fail, success]):
        reviews = review_candidates(candidates, account)

    assert len(reviews) == 1
