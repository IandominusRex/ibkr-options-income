"""Shapes the research layer passes between its own modules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

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
    # The us-gaap concept this fact was actually tagged under. A filer can switch which
    # concept it reports a line item under between fiscal years (e.g. NVIDIA tags revenue
    # `RevenueFromContractWithCustomerExcludingAssessedTax` for FY19-22 and switches to the
    # older `Revenues` tag for FY23-26) — `resolve_line_item` merges facts across every
    # alias concept, so this field is what lets each period keep an accurate, per-fact
    # concept rather than one label borrowed from whichever alias happened to be checked
    # first.
    concept: str


@dataclass(frozen=True, slots=True)
class TtmValue:
    """A trailing-twelve-month figure (value book spec §6.2). ``basis`` is ``"ytd"`` when it is
    fiscal year + year-to-date - prior year-to-date, ``"fy"`` when the fiscal year stands alone."""

    value: float
    end: date
    basis: Literal["ytd", "fy"]
    accn: str
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
