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
from src.claude.runner import review_candidates
from src.common.schemas import (
    AccountSnapshot,
    OptionRight,
    ScoreCard,
    Strategy,
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
        right=OptionRight.CALL,
        strike=strike,
        expiry=date(2026, 7, 17),
        contracts=1,
        premium=premium,
        collateral=18_000.0,
        roc_pct=0.83,
        annualized_yield_pct=18.5,
        breakeven=183.50,
        prob_otm=0.72,
        delta=0.28,
        iv_rank=65.0,
        dte=48,
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
    assert "AAPL" in prompt
    assert "MSFT" in prompt


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
