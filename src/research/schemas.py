"""Shapes the research layer passes between its own modules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from pydantic import BaseModel


@dataclass(frozen=True, slots=True)
class Fact:
    """One XBRL fact. `start` is None for instant (balance-sheet) facts."""

    value: float
    unit: str
    start: date | None
    end: date
    accn: str
    fy: int | None
    fp: str | None
    form: str
    filed: date


class LineItemValue(BaseModel):
    """One normalised line item for one period, traceable to its filing."""

    line_item: str
    value: float | None
    concept: str | None = None
    accn: str | None = None
    filed: date | None = None
    form: str | None = None


class PeriodStatement(BaseModel):
    """Every line item for one reporting period."""

    period_end: date
    period_type: str  # "annual" | "quarterly"
    items: dict[str, LineItemValue]


class NormalizedFinancials(BaseModel):
    symbol: str
    cik: str
    entity_name: str = ""
    annual: list[PeriodStatement] = []
    quarterly: list[PeriodStatement] = []
