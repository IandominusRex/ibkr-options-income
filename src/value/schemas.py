"""The value book's output shapes (spec §6.7, §6.9). Pydantic only: the API may import this
module (tests/test_value_fence.py)."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from src.common.value_types import Classification

GateState = Literal["pass", "fail", "unknown", "not_applicable"]
Verdict = Literal["READY", "WATCH", "WAIT", "NO", "UNKNOWN", "NOT_APPLICABLE"]
ListName = Literal["deep_value", "quality_growth"]
CompanyClass = Literal["operating", "cyclical", "bank", "insurer", "reit", "etf"]
MethodName = Literal["A", "B", "C", "D", "PTBV"]
MethodState = Literal["ok", "absent", "unreliable", "not_applicable"]

LISTS: tuple[ListName, ListName] = ("deep_value", "quality_growth")


class Check(BaseModel):
    """One gate or rule, with the number it read and the bar it was held to."""

    id: str
    state: GateState
    actual: float | None = None
    threshold: float | None = None
    detail: str = ""


def combine(checks: list[Check]) -> GateState:
    """A conjunction: any fail -> fail; else any unknown -> unknown; else pass.
    Checks that do not apply are ignored; all of them not applying -> not_applicable."""
    states = [c.state for c in checks if c.state != "not_applicable"]
    if not states:
        return "not_applicable"
    if "fail" in states:
        return "fail"
    if "unknown" in states:
        return "unknown"
    return "pass"


class MethodValue(BaseModel):
    """One valuation method's per-share value (spec §6.5)."""

    method: MethodName
    value: float | None = None
    state: MethodState = "absent"
    detail: str = ""
    inputs: dict[str, float | None] = Field(default_factory=dict)


class ListEvaluation(BaseModel):
    """Python's baseline for one list (spec §6.7)."""

    list_name: ListName
    entry: GateState  # deep value: always pass; quality growth: the entry rule
    entry_checks: list[Check] = Field(default_factory=list)
    methods: list[MethodValue] = Field(default_factory=list)
    fair_value: float | None = None
    required_mos_pct: float
    margin_of_safety: float | None = None  # a fraction: (fair value - price) / fair value
    entry_ceiling: float | None = None
    timing: GateState = "unknown"
    timing_checks: list[Check] = Field(default_factory=list)
    verdict: Verdict
    reasons: list[str] = Field(default_factory=list)
    mos_review: bool = False  # a margin above review_above_pct goes to a human (spec §9.4)


class Fingerprint(BaseModel):
    """The inputs a ticker file was computed from (spec §6.9)."""

    latest_accn: str | None = None
    latest_filed: date | None = None
    price_date: date | None = None
    price_close: float | None = None
    regime: str = "unknown"
    ruleset_version: str
    ruleset_hash: str

    def key(self) -> str:
        blob = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


class ValueScorecard(BaseModel):
    """Part 1 of a ticker file: every number, gate and baseline verdict for one name."""

    symbol: str
    as_of: date
    ruleset_version: str
    ruleset_hash: str
    company_class: CompanyClass
    classification: Classification
    data_quality: GateState
    data_quality_checks: list[Check] = Field(default_factory=list)
    health: GateState = "unknown"
    health_checks: list[Check] = Field(default_factory=list)
    not_applicable_reason: str | None = None
    price: float | None = None
    market_cap_edgar: float | None = None
    metrics: dict[str, float | None] = Field(default_factory=dict)
    reverse_dcf_implied_growth: float | None = None
    realised_fcf_ps_cagr: float | None = None
    lists: dict[str, ListEvaluation] = Field(default_factory=dict)
    adjustments: list[str] = Field(default_factory=list)
    fingerprint: Fingerprint

    def verdict_for(self, list_name: str) -> str:
        """The list's baseline verdict. NOT_APPLICABLE and UNKNOWN are the whole card's; a
        healthy name that is not on a list reads NO for that list."""
        if self.not_applicable_reason is not None:
            return "NOT_APPLICABLE"
        if self.data_quality != "pass":
            return "UNKNOWN"
        ev = self.lists.get(list_name)
        return ev.verdict if ev is not None else "NO"
