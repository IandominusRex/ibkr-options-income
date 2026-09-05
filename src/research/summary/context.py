"""Build the fully-computed context the model reasons over.

The contract (P0-P1-design §7 rule 1): the model receives the inputs already computed
and writes narrative only. Every numeric field on ``ResearchContext`` is a number we
already produced — nothing is left for the model to derive. ``UNKNOWN`` checks are
passed through as ``UNKNOWN`` so the model says "we don't know" rather than inventing.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from src.research.checks.engine import CheckResult
from src.research.checks.payload import ChecksPayload

if TYPE_CHECKING:
    from src.api.models.research import AnalysisResponse

# Carried forward from the Simply Wall St finding (P0-P1-design §7): this analysis is
# entirely quantitative and cannot account for one-time charges, M&A, spinoffs, or
# accounting restatements. The model is told this, and the rendered summary shows it
# too — the caveat most likely to be papered over by fluent prose stays visible.
_QUANTITATIVE_CAVEAT = (
    "This analysis is entirely quantitative. It cannot account for one-time charges, "
    "mergers, spinoffs, or accounting restatements."
)


class ResearchContext(BaseModel):
    """The fully-computed inputs to a summary. Nothing for the model to derive.

    ``key_metrics`` carries the same numbers the checks engine already evaluated; each
    value is either a real number or ``None`` (genuinely unknown), never a placeholder
    the model might mistake for one. ``checks`` is the per-check list with each check's
    ``actual``/``threshold``/``state`` so the model can cite them, and ``UNKNOWN`` is
    preserved as a state rather than coerced to a number.
    """

    symbol: str
    name: str = ""
    is_etf: bool = False
    key_metrics: dict[str, float | None] = Field(default_factory=dict)
    checks: list[CheckResult] = []
    category_scores: list[dict] = []
    technicals: dict | None = None
    sentiment: dict | None = None
    headlines: list[str] = []
    warnings: list[str] = []
    caveats: list[str] = []
    data_as_of: datetime = Field(default_factory=lambda: datetime.now(UTC))


def build_context(symbol: str, analysis: AnalysisResponse) -> ResearchContext:
    """Assemble the context from a fully-computed ``AnalysisResponse``.

    Reads only the already-computed fields — never triggers a fresh fetch, a scan, or a
    model call. A section that is ``PENDING`` or ``UNAVAILABLE`` contributes what it has
    (possibly nothing) and the model is told via the check state / empty lists rather
    than via a synthesised value.
    """
    upper = symbol.upper()

    caveats = [_QUANTITATIVE_CAVEAT]

    checks_payload: ChecksPayload | None = None
    if analysis.checks.state == "ready" and isinstance(analysis.checks.data, ChecksPayload):
        checks_payload = analysis.checks.data

    check_results: list[CheckResult] = []
    category_scores: list[dict] = []
    warnings: list[str] = []
    if checks_payload is not None:
        for cat in checks_payload.categories:
            check_results.extend(cat.checks)
        category_scores = [cat.model_dump() for cat in checks_payload.categories]
        for w in checks_payload.warnings:
            warnings.append(w.message if hasattr(w, "message") else str(w))

    key_metrics = _extract_key_metrics(check_results)

    technicals: dict | None = None
    if analysis.technicals.state == "ready" and analysis.technicals.data is not None:
        technicals = _model_to_dict(analysis.technicals.data)

    sentiment: dict | None = None
    if analysis.sentiment.state == "ready" and analysis.sentiment.data is not None:
        sentiment = _model_to_dict(analysis.sentiment.data)

    headlines: list[str] = []
    if analysis.news.state == "ready" and analysis.news.data:
        for item in analysis.news.data:
            title = getattr(item, "title", "") or ""
            if title:
                headlines.append(title)

    return ResearchContext(
        symbol=upper,
        name=analysis.name or "",
        is_etf=analysis.is_etf,
        key_metrics=key_metrics,
        checks=check_results,
        category_scores=category_scores,
        technicals=technicals,
        sentiment=sentiment,
        headlines=headlines,
        warnings=warnings,
        caveats=caveats,
        data_as_of=analysis.as_of,
    )


def _extract_key_metrics(checks: list[CheckResult]) -> dict[str, float | None]:
    """The actual values the checks engine evaluated, keyed by check id.

    A check with ``actual is None`` (UNKNOWN / NOT_APPLICABLE) is still included with a
    ``None`` value — the model must be told what we do not know, or it will fill the gap
    itself (Task 7.1 test contract).
    """
    out: dict[str, float | None] = {}
    for c in checks:
        out[c.id] = c.actual
    return out


def _model_to_dict(model: object) -> dict:
    """Best-effort Pydantic -> dict, so the context is plain JSON-serialisable."""
    if hasattr(model, "model_dump"):
        return model.model_dump()
    if isinstance(model, dict):
        return model
    return {}


__all__ = ["ResearchContext", "build_context"]
