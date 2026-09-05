"""The SummaryProvider protocol and the Summary model it produces.

Enrichment only. A summary records narrative over numbers the deterministic layer
already computed; it influences nothing. The fence tests in ``tests/test_web_fence.py``
keep it that way.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from pydantic import BaseModel

from src.research.summary.context import ResearchContext


class Summary(BaseModel):
    """Narrative over computed values. Every number in here was passed in via
    ``ResearchContext``; the model never calculates.

    ``caveats`` always carries the quantitative limit carried forward from the Simply
    Wall St finding (see ``context._QUANTITATIVE_CAVEAT``): this analysis is entirely
    quantitative and cannot account for one-time charges, M&A, spinoffs, or restatements.
    """

    thesis: str
    bull_points: list[str] = []
    bear_points: list[str] = []
    watch_items: list[str] = []
    caveats: list[str] = []
    model: str
    data_as_of: datetime


@runtime_checkable
class SummaryProvider(Protocol):
    """One method, one job: turn a fully-computed context into narrative or fail soft.

    ``None`` means "no summary" — a missing key, a timeout, a malformed response all
    collapse to the same no-summary state so the page renders fully without one. This
    mirrors ``src/claude/runner.py``'s fail-soft contract: enrichment, never a
    dependency.
    """

    def generate(self, context: ResearchContext) -> Summary | None: ...
