"""Evaluate the check catalogue against one symbol's metrics.

Four states, and the difference between them is the point:
  PASS / FAIL       - we had the data and measured it
  UNKNOWN           - we could not get the data. NEVER coerced to FAIL.
  NOT_APPLICABLE    - the question does not apply to this instrument (fundamental
                      categories against an ETF, which files no 10-K).

Reporting "3 of 6" when two were unknown would be a lie about the evidence, so category
scores carry `evaluable` alongside `total` and the UI shows both.

This module is deterministic. It must never import the AI summary layer.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum

from pydantic import BaseModel

from src.research.checks.definitions import CheckDef, CheckOp, load_checks
from src.research.checks.metrics import METRICS

_FUNDAMENTAL_CATEGORIES = frozenset({"value", "growth", "past", "health", "dividend"})


class CheckState(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class CheckResult(BaseModel):
    id: str
    category: str
    statement: str
    state: CheckState
    actual: float | None = None
    threshold: float | list[float] | None = None
    note: str | None = None


class CategoryScore(BaseModel):
    category: str
    passed: int
    failed: int
    unknown: int
    evaluable: int
    total: int


def _compare(value: float, op: CheckOp, threshold: float | list[float] | None) -> bool:
    if op is CheckOp.TRUTHY:
        return bool(value)
    if op is CheckOp.BETWEEN:
        assert isinstance(threshold, list)
        return threshold[0] <= value <= threshold[1]
    assert isinstance(threshold, int | float)
    return {
        CheckOp.LT: value < threshold,
        CheckOp.LTE: value <= threshold,
        CheckOp.GT: value > threshold,
        CheckOp.GTE: value >= threshold,
    }[op]


def _evaluate_one(
    check: CheckDef, metrics: Mapping[str, float | None], *, is_etf: bool
) -> CheckResult:
    if is_etf and check.category in _FUNDAMENTAL_CATEGORIES:
        return CheckResult(
            id=check.id,
            category=check.category,
            statement=check.statement,
            threshold=check.threshold,
            state=CheckState.NOT_APPLICABLE,
            note="Funds file no XBRL financial statements",
        )

    if any(metrics.get(name) is None for name in check.requires):
        return CheckResult(
            id=check.id,
            category=check.category,
            statement=check.statement,
            threshold=check.threshold,
            state=CheckState.UNKNOWN,
            note="Input data unavailable",
        )

    metric_fn = METRICS.get(check.fn)
    if metric_fn is None:
        return CheckResult(
            id=check.id,
            category=check.category,
            statement=check.statement,
            threshold=check.threshold,
            state=CheckState.UNKNOWN,
            note=f"No metric named {check.fn!r}",
        )

    actual = metric_fn(metrics)
    if actual is None:
        return CheckResult(
            id=check.id,
            category=check.category,
            statement=check.statement,
            threshold=check.threshold,
            state=CheckState.UNKNOWN,
            note="Metric not computable",
        )

    state = CheckState.PASS if _compare(actual, check.op, check.threshold) else CheckState.FAIL
    return CheckResult(
        id=check.id,
        category=check.category,
        statement=check.statement,
        threshold=check.threshold,
        state=state,
        actual=actual,
    )


def evaluate(metrics: Mapping[str, float | None], *, is_etf: bool) -> list[CheckResult]:
    """Every check in the catalogue, in catalogue order."""
    return [_evaluate_one(c, metrics, is_etf=is_etf) for c in load_checks()]


def summarize(results: list[CheckResult]) -> list[CategoryScore]:
    """Per-category counts. Categories that are entirely NOT_APPLICABLE are omitted."""
    by_category: dict[str, list[CheckResult]] = {}
    for r in results:
        by_category.setdefault(r.category, []).append(r)

    scores: list[CategoryScore] = []
    for category, items in by_category.items():
        if all(i.state is CheckState.NOT_APPLICABLE for i in items):
            continue
        passed = sum(1 for i in items if i.state is CheckState.PASS)
        failed = sum(1 for i in items if i.state is CheckState.FAIL)
        unknown = sum(1 for i in items if i.state is CheckState.UNKNOWN)
        scores.append(
            CategoryScore(
                category=category,
                passed=passed,
                failed=failed,
                unknown=unknown,
                evaluable=passed + failed,
                total=len(items),
            )
        )
    return scores
