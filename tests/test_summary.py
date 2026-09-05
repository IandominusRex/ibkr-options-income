"""Tests for the summary layer: backends and the caching/on-demand service.

Task 7.1 (context builder) and 7.2 (parser + prompt contract) have their own dedicated
files per the plan: tests/test_summary_context.py and tests/test_summary_claude_cli.py.
This file covers Task 7.3 (backend transports) and 7.4 (caching/on-demand trigger): each
backend handles missing-key/timeout/malformed gracefully, and the service obeys the
on-demand rule (GET makes no model call).
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from src.api.models.research import AnalysisResponse, NewsItem, Section
from src.research.checks.engine import CheckResult, CheckState
from src.research.checks.payload import CategoryPayload, ChecksPayload
from src.research.ingest.materialize import SectionState
from src.research.summary.claude_cli import parse_summary
from src.research.summary.context import ResearchContext
from src.research.summary.protocol import Summary

NOW = datetime.now(UTC)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _checks_payload(*, with_unknowns: bool = False) -> ChecksPayload:
    results = [
        CheckResult(
            id="health.current_ratio",
            category="health",
            statement="Current ratio above 1.0",
            state=CheckState.PASS,
            actual=1.5,
            threshold=1.0,
        ),
        CheckResult(
            id="value.pe_ratio",
            category="value",
            statement="P/E below 25",
            state=CheckState.FAIL,
            actual=30.0,
            threshold=25.0,
        ),
    ]
    if with_unknowns:
        results.append(
            CheckResult(
                id="growth.revenue_growth",
                category="growth",
                statement="Revenue growing",
                state=CheckState.UNKNOWN,
                note="Input data unavailable",
            )
        )
    cat = CategoryPayload(
        category="health",
        passed=1,
        failed=0,
        unknown=0,
        evaluable=1,
        total=1,
        checks=[results[0]],
    )
    cat2 = CategoryPayload(
        category="value",
        passed=0,
        failed=1,
        unknown=0,
        evaluable=1,
        total=1,
        checks=[results[1]],
    )
    cats = [cat, cat2]
    if with_unknowns:
        cats.append(
            CategoryPayload(
                category="growth",
                passed=0,
                failed=0,
                unknown=1,
                evaluable=0,
                total=1,
                checks=[results[2]],
            )
        )
    return ChecksPayload(categories=cats, warnings=[])


def _sample_analysis(
    *,
    with_gaps: bool = False,
    with_news: bool = False,
    checks_ready: bool = True,
) -> AnalysisResponse:
    checks_payload = _checks_payload(with_unknowns=with_gaps)
    return AnalysisResponse(
        as_of=NOW,
        symbol="AAPL",
        name="Apple Inc.",
        is_etf=False,
        fundamentals=Section[object](state=SectionState.READY, data=None),
        technicals=Section[object](state=SectionState.READY, data=None),
        sentiment=Section[object](state=SectionState.READY, data=None),
        news=Section[list[NewsItem]](
            state=SectionState.READY if with_news else SectionState.UNAVAILABLE,
            data=[NewsItem(title="Apple announces new product")] if with_news else None,
        ),
        checks=Section[ChecksPayload](
            state=SectionState.READY if checks_ready else SectionState.PENDING,
            data=checks_payload if checks_ready else None,
        ),
    )


@pytest.fixture()
def sample_analysis() -> AnalysisResponse:
    return _sample_analysis()


# ---------------------------------------------------------------------------
# Task 7.3 — backend transports (fail-soft, shared parser)
# ---------------------------------------------------------------------------


def _stub_context() -> ResearchContext:
    return ResearchContext(
        symbol="AAPL",
        name="Apple Inc.",
        key_metrics={"health.current_ratio": 1.5},
        data_as_of=NOW,
        caveats=["Quantitative only."],
    )


def test_anthropic_missing_key_returns_none(monkeypatch) -> None:
    from src.research.summary import anthropic as anthropic_mod
    from src.research.summary.anthropic import AnthropicSummaryProvider

    anthropic_mod._missing_key_logged = False
    monkeypatch.setattr(anthropic_mod, "get_config", _config_with_no_keys)
    p = AnthropicSummaryProvider()
    assert p.generate(_stub_context()) is None


def test_openai_missing_key_returns_none(monkeypatch) -> None:
    from src.research.summary import openai as openai_mod
    from src.research.summary.openai import OpenAISummaryProvider

    openai_mod._missing_key_logged = False
    monkeypatch.setattr(openai_mod, "get_config", _config_with_no_keys)
    p = OpenAISummaryProvider()
    assert p.generate(_stub_context()) is None


def test_ollama_timeout_returns_none(monkeypatch) -> None:
    import httpx

    from src.research.summary import ollama as ollama_mod
    from src.research.summary.ollama import OllamaSummaryProvider

    monkeypatch.setattr(ollama_mod, "get_config", _config_with_ollama)

    def _raise(*a, **kw):
        raise httpx.TimeoutException("timeout")

    monkeypatch.setattr(ollama_mod.httpx, "post", _raise)
    p = OllamaSummaryProvider()
    assert p.generate(_stub_context()) is None


def test_anthropic_malformed_response_returns_none(monkeypatch) -> None:
    from src.research.summary import anthropic as anthropic_mod

    anthropic_mod._missing_key_logged = False
    monkeypatch.setattr(anthropic_mod, "get_config", _config_with_anthropic_key)

    resp = MagicMock()
    resp.json.return_value = {"unexpected": "shape"}
    resp.raise_for_status = lambda: None

    monkeypatch.setattr(anthropic_mod.httpx, "post", lambda *a, **kw: resp)
    p = anthropic_mod.AnthropicSummaryProvider()
    assert p.generate(_stub_context()) is None


def test_openai_parses_well_formed_response(monkeypatch) -> None:
    from src.research.summary import openai as openai_mod
    from src.research.summary.openai import OpenAISummaryProvider

    openai_mod._missing_key_logged = False
    monkeypatch.setattr(openai_mod, "get_config", _config_with_openai_key)

    resp = MagicMock()
    resp.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": '{"thesis": "x", "bull_points": [], "bear_points": [], '
                    '"watch_items": [], "caveats": []}'
                }
            }
        ]
    }
    resp.raise_for_status = lambda: None

    monkeypatch.setattr(openai_mod.httpx, "post", lambda *a, **kw: resp)
    s = OpenAISummaryProvider().generate(_stub_context())
    assert s is not None
    assert s.thesis == "x"


def test_parsed_summary_identical_across_backends_for_same_output(monkeypatch) -> None:
    """The parser is shared, so identical model output yields identical Summary."""
    raw = '{"thesis": "same", "bull_points": ["a"], "bear_points": [], "watch_items": [], "caveats": []}'
    s1 = parse_summary(raw, model="claude", data_as_of=NOW)
    s2 = parse_summary(raw, model="openai", data_as_of=NOW)
    assert s1 is not None and s2 is not None
    assert s1.thesis == s2.thesis
    assert s1.bull_points == s2.bull_points


def test_claude_cli_missing_binary_returns_none(monkeypatch) -> None:
    import subprocess

    from src.research.summary import claude_cli as cli_mod

    monkeypatch.setattr(cli_mod, "get_config", _config_with_claude_enabled)

    def _raise(*a, **kw):
        raise FileNotFoundError("claude not found")

    monkeypatch.setattr(subprocess, "run", _raise)
    p = cli_mod.ClaudeCliSummaryProvider()
    assert p.generate(_stub_context()) is None


# ---------------------------------------------------------------------------
# Config stubs for backend tests
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
    ollama_host = "http://localhost:11434"
    ollama_model = "qwen3:8b"
    ollama_keep_alive = "10m"
    ollama_temperature = 0.2
    ollama_num_ctx = 8192


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


def _config_with_no_keys() -> _StubConfig:
    return _StubConfig()


def _config_with_anthropic_key() -> _StubConfig:
    cfg = _StubConfig()
    cfg.secrets.anthropic_api_key = "sk-ant-test"
    return cfg


def _config_with_openai_key() -> _StubConfig:
    cfg = _StubConfig()
    cfg.secrets.openai_api_key = "sk-test"
    return cfg


def _config_with_ollama() -> _StubConfig:
    return _StubConfig()


def _config_with_claude_enabled() -> _StubConfig:
    return _StubConfig()


# ---------------------------------------------------------------------------
# Task 7.4 — caching and on-demand trigger
# ---------------------------------------------------------------------------


@pytest.fixture()
def service_db(monkeypatch, tmp_path):
    from sqlalchemy.orm import sessionmaker

    from src.research.store.models import Base
    from src.research.store.session import research_session

    engine = __import__("sqlalchemy").create_engine(
        f"sqlite:///{(tmp_path / 'r.db').as_posix()}", future=True
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True, expire_on_commit=False)

    monkeypatch.setattr("src.research.store.session._SessionLocal", Session)
    monkeypatch.setattr("src.research.store.session._engine", engine)
    with research_session() as s:
        yield s


def test_get_on_symbol_with_no_cached_summary_makes_no_model_call(
    service_db, sample_analysis, monkeypatch
) -> None:
    from src.research.summary import service as svc

    called = {"n": 0}

    def _gen(_ctx):
        called["n"] += 1
        return None

    monkeypatch.setattr(svc, "_generate", _gen)
    summary, state = svc.summary_for("AAPL", sample_analysis, service_db, force=False)
    assert summary is None
    assert state == "unavailable"
    assert called["n"] == 0


def test_post_generates_and_caches(service_db, sample_analysis, monkeypatch) -> None:
    from src.research.summary import service as svc

    fixed = Summary(
        thesis="cached",
        bull_points=[],
        bear_points=[],
        watch_items=[],
        caveats=[],
        model="test-model",
        data_as_of=sample_analysis.as_of,
    )
    monkeypatch.setattr(svc, "_generate", lambda _ctx: fixed)
    s1, st1 = svc.summary_for("AAPL", sample_analysis, service_db, force=True)
    assert s1 is not None and st1 == "ready"

    # Second call (no force) reads from cache — _generate must not be called again.
    monkeypatch.setattr(svc, "_generate", lambda _ctx: pytest.fail("cache miss"))
    s2, st2 = svc.summary_for("AAPL", sample_analysis, service_db, force=False)
    assert s2 is not None and st2 == "ready"
    assert s2.thesis == "cached"


def test_changed_data_as_of_misses(service_db, sample_analysis, monkeypatch) -> None:
    from src.research.summary import service as svc

    fixed = Summary(
        thesis="v1",
        bull_points=[],
        bear_points=[],
        watch_items=[],
        caveats=[],
        model="test-model",
        data_as_of=sample_analysis.as_of,
    )
    monkeypatch.setattr(svc, "_generate", lambda _ctx: fixed)
    svc.summary_for("AAPL", sample_analysis, service_db, force=True)

    # New analysis with a newer data_as_of should miss the cache.
    newer = _sample_analysis()
    from datetime import timedelta

    object.__setattr__(newer, "__dict__", {**newer.__dict__, "as_of": NOW + timedelta(hours=2)})
    fixed2 = Summary(
        thesis="v2",
        bull_points=[],
        bear_points=[],
        watch_items=[],
        caveats=[],
        model="test-model",
        data_as_of=newer.as_of,
    )
    monkeypatch.setattr(svc, "_generate", lambda _ctx: fixed2)
    s, st = svc.summary_for("AAPL", newer, service_db, force=True)
    assert s is not None and s.thesis == "v2"


def test_watchlisted_symbol_is_eligible(service_db) -> None:
    from src.research.store.models import WatchlistItemRow, WatchlistRow
    from src.research.summary.service import is_watchlisted

    service_db.add(WatchlistRow(id=1, user_id="owner", name="Default"))
    service_db.add(WatchlistItemRow(watchlist_id=1, symbol="AAPL", added_at=NOW))
    service_db.flush()
    assert is_watchlisted(service_db, "AAPL") is True
    assert is_watchlisted(service_db, "MSFT") is False


def test_provider_model_name_is_preserved_in_cached_payload(
    service_db, sample_analysis, monkeypatch
) -> None:
    """The provider's self-reported ``Summary.model`` is what the user sees in the
    attribution line, even when it differs from the cache-key model.

    The cache key's ``model`` is config-derived (``research.summary.model``) so GET
    and POST always agree on the row. The provider's own model name (e.g. ``qwen3:8b``
    from ollama, which ignores ``research.summary.model``) is carried in the payload's
    ``model`` field and preferred by ``_row_to_summary``. Before the fix, the column
    value overwrote the payload value and the user always saw the config model.
    """
    from src.research.summary import service as svc

    provider_summary = Summary(
        thesis="from ollama",
        bull_points=[],
        bear_points=[],
        watch_items=[],
        caveats=[],
        model="qwen3:8b",  # provider self-reports this, differs from config model
        data_as_of=sample_analysis.as_of,
    )
    monkeypatch.setattr(svc, "_generate", lambda _ctx: provider_summary)
    s1, st1 = svc.summary_for("AAPL", sample_analysis, service_db, force=True)
    assert s1 is not None and st1 == "ready"
    assert s1.model == "qwen3:8b"  # the live Summary carries the provider's name

    # Re-read from cache (no force, no generation) — the attribution survives.
    monkeypatch.setattr(svc, "_generate", lambda _ctx: pytest.fail("cache miss"))
    s2, st2 = svc.summary_for("AAPL", sample_analysis, service_db, force=False)
    assert s2 is not None and st2 == "ready"
    assert s2.model == "qwen3:8b", "cached read lost the provider's model attribution"


def test_cached_summary_for_returns_unavailable_on_miss(service_db) -> None:
    """The read-only cache lookup returns ``unavailable`` without building a context."""
    from src.research.summary.service import cached_summary_for

    summary, state = cached_summary_for("AAPL", service_db)
    assert summary is None
    assert state == "unavailable"


def test_cached_summary_for_returns_ready_on_hit(service_db, sample_analysis, monkeypatch) -> None:
    """After a POST writes a row, the read-only lookup finds it without a context."""
    from src.research.summary import service as svc
    from src.research.summary.service import cached_summary_for

    fixed = Summary(
        thesis="cached via post",
        bull_points=[],
        bear_points=[],
        watch_items=[],
        caveats=[],
        model="test-model",
        data_as_of=sample_analysis.as_of,
    )
    monkeypatch.setattr(svc, "_generate", lambda _ctx: fixed)
    svc.summary_for("AAPL", sample_analysis, service_db, force=True)

    summary, state = cached_summary_for("AAPL", service_db)
    assert summary is not None and state == "ready"
    assert summary.thesis == "cached via post"
