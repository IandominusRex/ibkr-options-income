"""Assemble evaluate() + warnings_for() into the payload the API and the ticker page use.

Two asymmetric exclusions, both deliberate (see the plan's "Two refinements to the spec"):

* An ETF gets all seven categories, five of them NOT_APPLICABLE — the ribbon renders
  dimmed and explains *why* value/growth/past/health/dividend don't apply to a fund that
  files no XBRL. That's meaningful, so it's shown.
* A stock never gets a "Fund" category at all, not even NOT_APPLICABLE. Asking whether a
  stock's expense ratio is under 0.5% isn't a question that degrades gracefully; it's a
  question that shouldn't be posed, so it's omitted rather than rendered dimmed.

This is why the filter below only ever drops "fund" for non-ETF symbols and never touches
the NOT_APPLICABLE categories the engine already produces for ETFs.
"""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel

from src.research.checks.engine import CheckResult, CheckState, evaluate
from src.research.checks.warnings import Warning, warnings_for

_ETF_ONLY_CATEGORIES = frozenset({"fund"})


class CategoryPayload(BaseModel):
    category: str
    passed: int
    failed: int
    unknown: int
    evaluable: int
    total: int
    not_applicable: bool = False
    note: str | None = None
    checks: list[CheckResult] = []


class ChecksPayload(BaseModel):
    categories: list[CategoryPayload]
    warnings: list[Warning] = []


def build_checks_payload(
    metrics: Mapping[str, float | None], *, symbol: str, is_etf: bool
) -> ChecksPayload:
    """Every category the reader should see for this instrument, catalogue order."""
    results = evaluate(metrics, is_etf=is_etf)
    if not is_etf:
        results = [r for r in results if r.category not in _ETF_ONLY_CATEGORIES]

    by_category: dict[str, list[CheckResult]] = {}
    order: list[str] = []
    for r in results:
        if r.category not in by_category:
            by_category[r.category] = []
            order.append(r.category)
        by_category[r.category].append(r)

    categories = [_category_payload(category, by_category[category]) for category in order]
    return ChecksPayload(categories=categories, warnings=warnings_for(symbol, is_etf=is_etf))


def _category_payload(category: str, items: list[CheckResult]) -> CategoryPayload:
    not_applicable = all(i.state is CheckState.NOT_APPLICABLE for i in items)
    passed = sum(1 for i in items if i.state is CheckState.PASS)
    failed = sum(1 for i in items if i.state is CheckState.FAIL)
    unknown = sum(1 for i in items if i.state is CheckState.UNKNOWN)
    return CategoryPayload(
        category=category,
        passed=passed,
        failed=failed,
        unknown=unknown,
        evaluable=passed + failed,
        total=len(items),
        not_applicable=not_applicable,
        note=items[0].note if not_applicable else None,
        checks=items,
    )
