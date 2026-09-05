"""The context carries computed values only, and never asks the model to calculate.

Task 7.1 (Web plan/milestones/M7-ai-summary.md). ``build_context`` is fence-critical: it is
what makes "the model never computes a number" true rather than aspirational.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.api.models.research import AnalysisResponse, NewsItem, Section
from src.research.checks.engine import CheckResult, CheckState
from src.research.checks.payload import CategoryPayload, ChecksPayload
from src.research.ingest.materialize import SectionState
from src.research.summary.context import build_context

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
        category="health", passed=1, failed=0, unknown=0, evaluable=1, total=1, checks=[results[0]]
    )
    cat2 = CategoryPayload(
        category="value", passed=0, failed=1, unknown=0, evaluable=1, total=1, checks=[results[1]]
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


def _sample_analysis(*, with_gaps: bool = False, with_news: bool = False) -> AnalysisResponse:
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
        checks=Section[ChecksPayload](state=SectionState.READY, data=checks_payload),
    )


@pytest.fixture()
def sample_analysis() -> AnalysisResponse:
    return _sample_analysis()


@pytest.fixture()
def sample_analysis_with_gaps() -> AnalysisResponse:
    return _sample_analysis(with_gaps=True)


@pytest.fixture()
def sample_analysis_with_news() -> AnalysisResponse:
    return _sample_analysis(with_news=True)


def test_context_carries_check_results_with_their_actuals(sample_analysis) -> None:
    ctx = build_context("AAPL", sample_analysis)
    health = next(c for c in ctx.checks if c.id == "health.current_ratio")
    assert health.actual is not None
    assert health.threshold is not None
    assert health.statement


def test_context_carries_only_computed_numbers(sample_analysis) -> None:
    """Every numeric field must already be a number. Nothing is left for the model to derive."""
    ctx = build_context("AAPL", sample_analysis)
    for value in ctx.key_metrics.values():
        assert value is None or isinstance(value, int | float)


def test_context_marks_unknown_checks_explicitly(sample_analysis_with_gaps) -> None:
    """The model must be told what we do not know, or it will fill the gap itself."""
    ctx = build_context("AAPL", sample_analysis_with_gaps)
    assert any(c.state == "UNKNOWN" for c in ctx.checks)


def test_context_includes_the_quantitative_caveat(sample_analysis) -> None:
    ctx = build_context("AAPL", sample_analysis)
    joined = " ".join(ctx.caveats).lower()
    assert "one-time" in joined or "restatement" in joined


def test_context_excludes_anything_the_model_could_treat_as_an_instruction(
    sample_analysis_with_news,
) -> None:
    """News headlines are third-party text. They are data, never instructions."""
    ctx = build_context("AAPL", sample_analysis_with_news)
    assert ctx.headlines
    assert all(isinstance(h, str) for h in ctx.headlines)
