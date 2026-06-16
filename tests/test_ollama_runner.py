"""Tests for the local-LLM (Ollama) backend: parser functions, ollama_runner, and the
`claude.backend` dispatcher in runner.py.

All tests mock httpx.post / subprocess.run — no live Ollama server or Claude CLI needed.
"""

from __future__ import annotations

import json
from datetime import date
from unittest.mock import MagicMock, patch

import httpx

from src.claude.parser import (
    parse_ollama_journal_output,
    parse_ollama_review_output,
    parse_ollama_roll_output,
    parse_ollama_skill_proposal,
)
from src.claude.runner import review_candidates, review_roll, write_journal_narrative
from src.common.schemas import (
    AccountSnapshot,
    EODSummary,
    OptionQuote,
    OptionRight,
    PositionSnapshot,
    RollAlert,
    ScoreCard,
    SkillProposal,
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


def _make_candidate() -> TradeCandidate:
    scores = ScoreCard(
        symbol="AAPL",
        iv_score=72.0,
        technical_score=65.0,
        fundamental_score=80.0,
        liquidity_score=90.0,
        assignment_safety_score=70.0,
    )
    return TradeCandidate(
        candidate_id="test-001",
        strategy=Strategy.COVERED_CALL,
        underlying="AAPL",
        right=OptionRight.CALL,
        strike=185.0,
        expiry=date(2026, 7, 17),
        contracts=1,
        premium=1.50,
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


def _ollama_response(payload: object) -> MagicMock:
    """A mocked httpx.Response for Ollama's /api/generate with format=json."""
    mock = MagicMock()
    mock.json.return_value = {"response": json.dumps(payload)}
    mock.raise_for_status.return_value = None
    return mock


def _completed_process(stdout: str, returncode: int = 0) -> MagicMock:
    mock = MagicMock()
    mock.stdout = stdout
    mock.stderr = ""
    mock.returncode = returncode
    return mock


def _make_valid_cli_envelope(reviews: list[dict]) -> str:
    return json.dumps({"type": "result", "subtype": "success", "result": json.dumps(reviews)})


# --------------------------------------------------------------------------- #
# parse_ollama_review_output
# --------------------------------------------------------------------------- #


def test_parse_ollama_review_output_valid_list():
    raw = json.dumps([_review_dict()])
    reviews = parse_ollama_review_output(raw)
    assert len(reviews) == 1
    assert reviews[0].candidate_id == "test-001"
    assert reviews[0].recommendation == "sell"


def test_parse_ollama_review_output_single_dict_wrapped():
    raw = json.dumps(_review_dict())
    reviews = parse_ollama_review_output(raw)
    assert len(reviews) == 1


def test_parse_ollama_review_output_fenced():
    raw = "```json\n" + json.dumps([_review_dict()]) + "\n```"
    reviews = parse_ollama_review_output(raw)
    assert len(reviews) == 1


def test_parse_ollama_review_output_empty():
    assert parse_ollama_review_output("") == []


def test_parse_ollama_review_output_invalid_schema():
    raw = json.dumps([{"foo": "bar"}])
    assert parse_ollama_review_output(raw) == []


def test_parse_ollama_review_output_not_json():
    assert parse_ollama_review_output("not json at all {{{") == []


# --------------------------------------------------------------------------- #
# parse_ollama_roll_output / parse_ollama_journal_output
# --------------------------------------------------------------------------- #


def test_parse_ollama_roll_output_valid():
    raw = json.dumps(
        {
            "position_symbol": "AAPL 250718C00190000",
            "recommendation": "roll",
            "roll_target": "roll to $195 Aug 15 CC at 0.30 delta, $1.85 credit",
            "rationale": "Stock approaching strike with 10 DTE remaining.",
            "risks": "Further upside could require another roll.",
            "confidence": 0.7,
        }
    )
    review = parse_ollama_roll_output(raw)
    assert review is not None
    assert review.recommendation == "roll"


def test_parse_ollama_roll_output_empty():
    assert parse_ollama_roll_output("") is None


def test_parse_ollama_journal_output_valid():
    raw = json.dumps({"narrative": "A quiet day with one CSP expiring worthless."})
    assert parse_ollama_journal_output(raw) == "A quiet day with one CSP expiring worthless."


def test_parse_ollama_journal_output_missing_field():
    raw = json.dumps({"foo": "bar"})
    assert parse_ollama_journal_output(raw) is None


# --------------------------------------------------------------------------- #
# parse_ollama_skill_proposal
# --------------------------------------------------------------------------- #

_SKILL_PROPOSAL_DICT = {
    "name": "prefer-high-ivr",
    "description": "Lean to wait on thin-IVR CSPs.",
    "body": "When IVR < 30, bias the recommendation toward wait and lower priority.",
    "rationale": "Thin-IVR sells underperformed in the ledger.",
    "supporting_stats": {"n": 12},
}


def test_parse_ollama_skill_proposal_valid():
    raw = json.dumps(_SKILL_PROPOSAL_DICT)
    proposal = parse_ollama_skill_proposal(raw)
    assert proposal is not None
    assert proposal.name == "prefer-high-ivr"
    assert proposal.supporting_stats == {"n": 12}


def test_parse_ollama_skill_proposal_fenced():
    raw = "```json\n" + json.dumps(_SKILL_PROPOSAL_DICT) + "\n```"
    proposal = parse_ollama_skill_proposal(raw)
    assert proposal is not None
    assert proposal.name == "prefer-high-ivr"


def test_parse_ollama_skill_proposal_empty():
    assert parse_ollama_skill_proposal("") is None


def test_parse_ollama_skill_proposal_invalid_schema():
    raw = json.dumps({"foo": "bar"})
    assert parse_ollama_skill_proposal(raw) is None


def test_parse_ollama_skill_proposal_not_json():
    assert parse_ollama_skill_proposal("not json at all {{{") is None


# --------------------------------------------------------------------------- #
# ollama_runner — review_candidates / review_roll / write_journal_narrative
# --------------------------------------------------------------------------- #


def _patch_ollama_cfg(**overrides):
    """Patch get_config().claude in both runner.py and ollama_runner.py to the same MagicMock."""
    cfg = MagicMock(
        enabled=True,
        backend="ollama",
        ollama_host="http://localhost:11434",
        ollama_model="qwen2.5:14b-instruct",
        ollama_timeout_seconds=120.0,
        **overrides,
    )
    runner_patch = patch("src.claude.runner.get_config")
    ollama_patch = patch("src.claude.ollama_runner.get_config")
    return cfg, runner_patch, ollama_patch


def test_ollama_backend_review_candidates_success():
    account = _make_account()
    candidates = [_make_candidate()]

    cfg, runner_patch, ollama_patch = _patch_ollama_cfg()
    with patch(
        "src.claude.ollama_runner.httpx.post",
        return_value=_ollama_response([_review_dict()]),
    ) as mock_post:
        with runner_patch as mock_runner_cfg, ollama_patch as mock_ollama_cfg:
            mock_runner_cfg.return_value.claude = cfg
            mock_ollama_cfg.return_value.claude = cfg
            reviews = review_candidates(candidates, account)

    assert len(reviews) == 1
    assert reviews[0].candidate_id == "test-001"
    url = mock_post.call_args.args[0]
    assert url == "http://localhost:11434/api/generate"
    body = mock_post.call_args.kwargs["json"]
    assert body["format"] == "json"
    assert body["model"] == "qwen2.5:14b-instruct"


def test_ollama_backend_connection_error_returns_empty():
    account = _make_account()
    candidates = [_make_candidate()]

    cfg, runner_patch, ollama_patch = _patch_ollama_cfg()
    with patch(
        "src.claude.ollama_runner.httpx.post",
        side_effect=httpx.ConnectError("connection refused"),
    ):
        with runner_patch as mock_runner_cfg, ollama_patch as mock_ollama_cfg:
            mock_runner_cfg.return_value.claude = cfg
            mock_ollama_cfg.return_value.claude = cfg
            reviews = review_candidates(candidates, account)

    assert reviews == []


def test_ollama_backend_review_roll_success():
    pos = PositionSnapshot(
        symbol="AAPL250718C00190000",
        sec_type="OPT",
        position=-1,
        avg_cost=185.0,
        underlying="AAPL",
        right=OptionRight.CALL,
        strike=190.0,
        expiry=date(2026, 7, 18),
        delta=0.45,
    )
    quote = OptionQuote(
        underlying="AAPL", right=OptionRight.CALL, strike=190.0, expiry=date(2026, 7, 18)
    )
    alert = RollAlert(
        position_symbol="AAPL250718C00190000",
        underlying="AAPL",
        trigger="delta_drift",
        detail="Delta drifted to 0.45",
        current_delta=0.45,
        dte=10,
    )
    roll_payload = {
        "position_symbol": "AAPL250718C00190000",
        "recommendation": "hold",
        "roll_target": "",
        "rationale": "Still within tolerance.",
        "risks": "Could breach delta band if rally continues.",
        "confidence": 0.6,
    }

    cfg, runner_patch, ollama_patch = _patch_ollama_cfg()
    with patch("src.claude.ollama_runner.httpx.post", return_value=_ollama_response(roll_payload)):
        with runner_patch as mock_runner_cfg, ollama_patch as mock_ollama_cfg:
            mock_runner_cfg.return_value.claude = cfg
            mock_ollama_cfg.return_value.claude = cfg
            review = review_roll(alert, pos, quote)

    assert review is not None
    assert review.recommendation == "hold"


def test_ollama_backend_write_journal_narrative_success():
    summary = EODSummary(
        date=date(2026, 6, 15),
        realized_pnl=120.0,
        unrealized_pnl=300.0,
        unrealized_pnl_delta=50.0,
        fills_today=2,
        open_positions=5,
        net_delta_exposure=-120.0,
        account=_make_account(),
    )
    payload = {"narrative": "Collected premium on two CSPs; no rolls today."}

    cfg, runner_patch, ollama_patch = _patch_ollama_cfg()
    with patch("src.claude.ollama_runner.httpx.post", return_value=_ollama_response(payload)):
        with runner_patch as mock_runner_cfg, ollama_patch as mock_ollama_cfg:
            mock_runner_cfg.return_value.claude = cfg
            mock_ollama_cfg.return_value.claude = cfg
            narrative = write_journal_narrative(summary)

    assert narrative == "Collected premium on two CSPs; no rolls today."


# --------------------------------------------------------------------------- #
# dispatcher — cli_then_ollama fallback
# --------------------------------------------------------------------------- #


def test_cli_then_ollama_falls_back_when_cli_empty():
    """CLI returns unparseable/empty output -> dispatcher falls back to Ollama."""
    account = _make_account()
    candidates = [_make_candidate()]

    cfg = MagicMock(
        enabled=True,
        backend="cli_then_ollama",
        cli_command="claude",
        output_format="json",
        max_turns=1,
        model="",
        disallowed_tools="",
        max_retries=0,
        timeout_seconds=180.0,
        ollama_host="http://localhost:11434",
        ollama_model="qwen2.5:14b-instruct",
        ollama_timeout_seconds=120.0,
    )

    with patch("src.claude.runner.get_config") as mock_runner_cfg:
        mock_runner_cfg.return_value.claude = cfg
        with patch("src.claude.ollama_runner.get_config") as mock_ollama_cfg:
            mock_ollama_cfg.return_value.claude = cfg
            with patch(
                "src.claude.runner.subprocess.run",
                return_value=_completed_process("", returncode=1),
            ):
                with patch(
                    "src.claude.ollama_runner.httpx.post",
                    return_value=_ollama_response([_review_dict()]),
                ) as mock_post:
                    reviews = review_candidates(candidates, account)

    assert len(reviews) == 1
    assert reviews[0].candidate_id == "test-001"
    mock_post.assert_called_once()


def test_cli_then_ollama_skips_fallback_when_cli_succeeds():
    """CLI returns a valid review -> Ollama is never called."""
    account = _make_account()
    candidates = [_make_candidate()]
    envelope = _make_valid_cli_envelope([_review_dict()])

    cfg = MagicMock(
        enabled=True,
        backend="cli_then_ollama",
        cli_command="claude",
        output_format="json",
        max_turns=1,
        model="",
        disallowed_tools="",
        max_retries=0,
        timeout_seconds=180.0,
        ollama_host="http://localhost:11434",
        ollama_model="qwen2.5:14b-instruct",
        ollama_timeout_seconds=120.0,
    )

    with patch("src.claude.runner.get_config") as mock_get_config:
        mock_get_config.return_value.claude = cfg
        with patch(
            "src.claude.runner.subprocess.run",
            return_value=_completed_process(envelope),
        ):
            with patch("src.claude.ollama_runner.httpx.post") as mock_post:
                reviews = review_candidates(candidates, account)

    assert len(reviews) == 1
    mock_post.assert_not_called()


def test_ollama_only_backend_skips_cli_subprocess():
    account = _make_account()
    candidates = [_make_candidate()]

    cfg = MagicMock(
        enabled=True,
        backend="ollama",
        ollama_host="http://localhost:11434",
        ollama_model="qwen2.5:14b-instruct",
        ollama_timeout_seconds=120.0,
    )

    with patch("src.claude.runner.get_config") as mock_runner_cfg:
        mock_runner_cfg.return_value.claude = cfg
        with patch("src.claude.ollama_runner.get_config") as mock_ollama_cfg:
            mock_ollama_cfg.return_value.claude = cfg
            with patch("src.claude.runner.subprocess.run") as mock_subproc:
                with patch(
                    "src.claude.ollama_runner.httpx.post",
                    return_value=_ollama_response([_review_dict()]),
                ):
                    reviews = review_candidates(candidates, account)

    assert len(reviews) == 1
    mock_subproc.assert_not_called()


# --------------------------------------------------------------------------- #
# ollama_runner.propose_skill / proposer dispatch
# --------------------------------------------------------------------------- #


def test_ollama_runner_propose_skill_success():
    from src.claude import ollama_runner

    cfg, _runner_patch, ollama_patch = _patch_ollama_cfg()
    with patch(
        "src.claude.ollama_runner.httpx.post",
        return_value=_ollama_response(_SKILL_PROPOSAL_DICT),
    ):
        with ollama_patch as mock_ollama_cfg:
            mock_ollama_cfg.return_value.claude = cfg
            proposal = ollama_runner.propose_skill("draft a skill prompt")

    assert proposal is not None
    assert proposal.name == "prefer-high-ivr"


def test_ollama_runner_propose_skill_connection_error():
    from src.claude import ollama_runner

    cfg, _runner_patch, ollama_patch = _patch_ollama_cfg()
    with patch(
        "src.claude.ollama_runner.httpx.post",
        side_effect=httpx.ConnectError("connection refused"),
    ):
        with ollama_patch as mock_ollama_cfg:
            mock_ollama_cfg.return_value.claude = cfg
            proposal = ollama_runner.propose_skill("draft a skill prompt")

    assert proposal is None


def _make_skill_proposal_cfg(**overrides):
    return MagicMock(
        enabled=True,
        cli_command="claude",
        output_format="json",
        timeout_seconds=180.0,
        ollama_host="http://localhost:11434",
        ollama_model="qwen3:14b",
        ollama_timeout_seconds=120.0,
        **overrides,
    )


def test_proposer_propose_skill_ollama_backend_skips_cli():
    """`backend: "ollama"` dispatches to ollama_runner.propose_skill, never shells out."""
    from src.claude.skills import proposer

    cfg = _make_skill_proposal_cfg(backend="ollama")
    expected = SkillProposal.model_validate(_SKILL_PROPOSAL_DICT)

    with patch("src.claude.skills.proposer.get_config") as mock_get_config:
        mock_get_config.return_value.claude = cfg
        with patch("src.claude.skills.proposer.load_records", return_value=["record"]):
            with patch("src.claude.skills.proposer.evaluate"):
                with patch(
                    "src.claude.skills.proposer.build_proposal_prompt",
                    return_value="prompt text",
                ):
                    with patch(
                        "src.claude.skills.proposer.ollama_runner.propose_skill",
                        return_value=expected,
                    ) as mock_ollama_propose:
                        with patch("src.claude.skills.proposer.save_proposal") as mock_save:
                            with patch("src.claude.skills.proposer.subprocess.run") as mock_run:
                                result = proposer.propose_skill()

    assert result == expected
    mock_ollama_propose.assert_called_once_with("prompt text")
    mock_run.assert_not_called()
    mock_save.assert_called_once_with(expected)


def test_proposer_propose_skill_cli_then_ollama_falls_back():
    """`backend: "cli_then_ollama"` falls back to ollama when the CLI returns nothing."""
    from src.claude.skills import proposer

    cfg = _make_skill_proposal_cfg(backend="cli_then_ollama")
    expected = SkillProposal.model_validate(_SKILL_PROPOSAL_DICT)

    with patch("src.claude.skills.proposer.get_config") as mock_get_config:
        mock_get_config.return_value.claude = cfg
        with patch("src.claude.skills.proposer.load_records", return_value=["record"]):
            with patch("src.claude.skills.proposer.evaluate"):
                with patch(
                    "src.claude.skills.proposer.build_proposal_prompt",
                    return_value="prompt text",
                ):
                    with patch(
                        "src.claude.skills.proposer.subprocess.run",
                        return_value=_completed_process("", returncode=1),
                    ):
                        with patch(
                            "src.claude.skills.proposer.ollama_runner.propose_skill",
                            return_value=expected,
                        ) as mock_ollama_propose:
                            with patch("src.claude.skills.proposer.save_proposal") as mock_save:
                                result = proposer.propose_skill()

    assert result == expected
    mock_ollama_propose.assert_called_once_with("prompt text")
    mock_save.assert_called_once_with(expected)


def test_proposer_propose_skill_no_closed_records_returns_none():
    from src.claude.skills import proposer

    cfg = _make_skill_proposal_cfg(backend="ollama")

    with patch("src.claude.skills.proposer.get_config") as mock_get_config:
        mock_get_config.return_value.claude = cfg
        with patch("src.claude.skills.proposer.load_records", return_value=[]):
            with patch(
                "src.claude.skills.proposer.ollama_runner.propose_skill"
            ) as mock_ollama_propose:
                result = proposer.propose_skill()

    assert result is None
    mock_ollama_propose.assert_not_called()
