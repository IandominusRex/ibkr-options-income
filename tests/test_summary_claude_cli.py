"""The CLI backend parses strictly, fails soft, and reuses runner.py's subprocess loop.

Task 7.2 (Web plan/milestones/P0-P1/M7-ai-summary.md). ``ClaudeCliSummaryProvider`` shells out
via ``src.claude.runner``'s shared ``_run_cli``/``_build_cmd`` rather than a second CLI
invoker, so it inherits the same hardening flags and cost logging as the strategist review.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from src.api.models.research import AnalysisResponse, NewsItem, Section
from src.research.checks.engine import CheckResult, CheckState
from src.research.checks.payload import CategoryPayload, ChecksPayload
from src.research.ingest.materialize import SectionState
from src.research.summary.claude_cli import ClaudeCliSummaryProvider, parse_summary
from src.research.summary.context import ResearchContext, build_context
from src.research.summary.prompt import build_prompt

NOW = datetime.now(UTC)


def _checks_payload(*, with_unknowns: bool = False) -> ChecksPayload:
    results = [
        CheckResult(
            id="health.current_ratio",
            category="health",
            statement="Current ratio above 1.0",
            state=CheckState.PASS,
            actual=1.5,
            threshold=1.0,
        )
    ]
    cats = [
        CategoryPayload(
            category="health", passed=1, failed=0, unknown=0, evaluable=1, total=1, checks=results
        )
    ]
    if with_unknowns:
        unknown_check = CheckResult(
            id="growth.revenue_growth",
            category="growth",
            statement="Revenue growing",
            state=CheckState.UNKNOWN,
            note="Input data unavailable",
        )
        cats.append(
            CategoryPayload(
                category="growth",
                passed=0,
                failed=0,
                unknown=1,
                evaluable=0,
                total=1,
                checks=[unknown_check],
            )
        )
    return ChecksPayload(categories=cats, warnings=[])


def _sample_analysis(*, with_gaps: bool = False) -> AnalysisResponse:
    return AnalysisResponse(
        as_of=NOW,
        symbol="AAPL",
        name="Apple Inc.",
        is_etf=False,
        fundamentals=Section[object](state=SectionState.READY, data=None),
        technicals=Section[object](state=SectionState.READY, data=None),
        sentiment=Section[object](state=SectionState.READY, data=None),
        news=Section[list[NewsItem]](state=SectionState.UNAVAILABLE, data=None),
        checks=Section[ChecksPayload](
            state=SectionState.READY, data=_checks_payload(with_unknowns=with_gaps)
        ),
    )


@pytest.fixture()
def sample_context() -> ResearchContext:
    return build_context("AAPL", _sample_analysis())


@pytest.fixture()
def sample_context_with_unknowns() -> ResearchContext:
    return build_context("AAPL", _sample_analysis(with_gaps=True))


# ---------------------------------------------------------------------------
# parse_summary — strict, fail-soft
# ---------------------------------------------------------------------------


def test_parses_a_well_formed_response() -> None:
    raw = """{"thesis": "Steady compounder with rich options premium.",
              "bull_points": ["ROE above 15%"], "bear_points": ["P/E above the market"],
              "watch_items": ["Earnings on 30 Oct"], "caveats": ["Quantitative only"]}"""
    s = parse_summary(raw, model="claude-sonnet-4-6", data_as_of=NOW)
    assert s is not None
    assert s.thesis.startswith("Steady")
    assert s.bull_points == ["ROE above 15%"]


def test_parses_json_wrapped_in_prose() -> None:
    raw = (
        'Here is the summary:\n```json\n{"thesis": "x", "bull_points": [], '
        '"bear_points": [], "watch_items": [], "caveats": []}\n```'
    )
    assert parse_summary(raw, model="m", data_as_of=NOW) is not None


def test_unparseable_output_returns_none_rather_than_raising() -> None:
    """A bad parse renders the page without a summary. Enrichment, never a dependency."""
    assert parse_summary("I could not do that.", model="m", data_as_of=NOW) is None


def test_a_missing_required_field_returns_none() -> None:
    """``thesis`` is the only field with no default — a response missing it is unusable."""
    assert parse_summary('{"bull_points": []}', model="m", data_as_of=NOW) is None


def test_prompt_forbids_calculation(sample_context) -> None:
    p = build_prompt(sample_context).lower()
    assert "must appear in the context" in p or "never calculate" in p


def test_prompt_forbids_trade_recommendations(sample_context) -> None:
    p = build_prompt(sample_context).lower()
    assert "not recommend" in p or "never recommend" in p


def test_prompt_states_unknowns_explicitly(sample_context_with_unknowns) -> None:
    assert "UNKNOWN" in build_prompt(sample_context_with_unknowns)


# ---------------------------------------------------------------------------
# ClaudeCliSummaryProvider — reuses runner.py's subprocess loop, not a second one
# ---------------------------------------------------------------------------


class _StubSecrets:
    anthropic_api_key = ""
    openai_api_key = ""


class _StubClaude:
    enabled = True
    cli_command = "claude"
    output_format = "json"
    max_turns = 1
    model = ""
    disallowed_tools = ""
    timeout_seconds = 180.0
    max_retries = 1


class _StubSummary:
    backend = "claude_cli"
    model = "test-model"
    timeout_seconds = 10
    cache_ttl_hours = 24


class _StubResearch:
    summary = _StubSummary()


class _StubConfig:
    secrets = _StubSecrets()
    claude = _StubClaude()
    research = _StubResearch()


def _stub_config() -> _StubConfig:
    return _StubConfig()


def test_claude_cli_missing_binary_returns_none(monkeypatch) -> None:
    import subprocess

    from src.research.summary import claude_cli as cli_mod

    monkeypatch.setattr(cli_mod, "get_config", _stub_config)

    def _raise(*a, **kw):
        raise FileNotFoundError("claude not found")

    monkeypatch.setattr(subprocess, "run", _raise)
    p = ClaudeCliSummaryProvider()
    assert p.generate(build_context("AAPL", _sample_analysis())) is None


def test_claude_cli_reuses_runner_build_cmd_not_a_second_invoker(monkeypatch) -> None:
    """Task 7.2: 'reuse src/claude/runner.py's subprocess and timeout handling rather
    than writing a second CLI invoker.' The command passed to subprocess.run must be
    exactly what runner._build_cmd produces for the same claude config.
    """
    from src.claude.runner import _build_cmd
    from src.research.summary import claude_cli as cli_mod

    monkeypatch.setattr(cli_mod, "get_config", _stub_config)

    seen_cmd: list[str] = []

    def _fake_run(cmd, **kw):
        seen_cmd.extend(cmd)
        resp = MagicMock()
        resp.returncode = 0
        resp.stdout = json.dumps(
            {
                "result": json.dumps(
                    {"thesis": "x", "bull_points": [], "bear_points": [], "watch_items": [], "caveats": []}
                )
            }
        )
        resp.stderr = ""
        return resp

    monkeypatch.setattr("src.claude.runner.subprocess.run", _fake_run)
    p = ClaudeCliSummaryProvider()
    s = p.generate(build_context("AAPL", _sample_analysis()))
    assert s is not None
    assert seen_cmd == _build_cmd(_StubClaude())


def test_claude_cli_logs_cost_on_success(monkeypatch, caplog) -> None:
    """Before this fix, claude_cli built its own subprocess.run call and never invoked
    runner._log_cost — CLI-backend summary generation had no cost visibility at all.
    """
    import logging

    from src.research.summary import claude_cli as cli_mod

    monkeypatch.setattr(cli_mod, "get_config", _stub_config)

    def _fake_run(cmd, **kw):
        resp = MagicMock()
        resp.returncode = 0
        resp.stdout = json.dumps(
            {
                "total_cost_usd": 0.0123,
                "result": json.dumps(
                    {"thesis": "x", "bull_points": [], "bear_points": [], "watch_items": [], "caveats": []}
                ),
            }
        )
        resp.stderr = ""
        return resp

    monkeypatch.setattr("src.claude.runner.subprocess.run", _fake_run)
    with caplog.at_level(logging.INFO, logger="src.claude.runner"):
        s = ClaudeCliSummaryProvider().generate(build_context("AAPL", _sample_analysis()))
    assert s is not None
    assert any("call cost" in rec.message for rec in caplog.records)


def test_claude_cli_does_not_retry(monkeypatch) -> None:
    """Enrichment triggered live from a page load should fail fast, not retry — unlike
    the scheduled strategist review, which retries up to claude.max_retries.
    """
    from src.research.summary import claude_cli as cli_mod

    monkeypatch.setattr(cli_mod, "get_config", _stub_config)

    calls = {"n": 0}

    def _fake_run(cmd, **kw):
        calls["n"] += 1
        resp = MagicMock()
        resp.returncode = 1
        resp.stdout = ""
        resp.stderr = "boom"
        return resp

    monkeypatch.setattr("src.claude.runner.subprocess.run", _fake_run)
    result = ClaudeCliSummaryProvider().generate(build_context("AAPL", _sample_analysis()))
    assert result is None
    assert calls["n"] == 1
