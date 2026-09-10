"""Response shapes for the P&L surfaces (P3-P4 M5).

Every route is a thin renderer over `src/reporting/pnl.py` — no figure is
computed here. Filters are echoed back on every response so a client can prove
what it is looking at, and `marks_as_of` names the snapshot backing every
unrealised figure (null when no snapshot exists — never a zero).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

from src.api.models.common import Envelope
from src.common.schemas import CampaignPnl, EquityCurve, PnlSummary, ScoreOutcomeReport


class LedgerFilters(Envelope):
    """Echoed back on every response so the client can prove what it is looking at."""

    symbol: str | None = None
    strategy: str | None = None
    outcome: str | None = None
    since: date | None = None
    until: date | None = None
    book: Literal["paper", "live", "all"] = "all"


class LedgerResponse(Envelope):
    filters: LedgerFilters
    campaigns: list[CampaignPnl]
    marks_as_of: datetime | None = None  # the snapshot backing every unrealised figure
    n_legs: int  # every leg, across every campaign; the client checks the sum


class SummaryResponse(Envelope):
    filters: LedgerFilters
    summary: PnlSummary
    marks_as_of: datetime | None = None


class EquityResponse(Envelope):
    filters: LedgerFilters
    curve: EquityCurve


class VerdictAgreement(BaseModel):
    """How often Claude's verdict matched the deterministic baseline, and how each did."""

    n_closed: int
    n_agreed: int
    agreement_rate: float | None = None  # None when n_closed is 0, never 0.0
    claude_win_rate: float | None = None
    baseline_win_rate: float | None = None


class SystemPerformanceResponse(Envelope):
    """The score-vs-outcome report plus verdict agreement — P3-P4 M6's fenced read (Task 6.1)."""

    report: ScoreOutcomeReport
    agreement: VerdictAgreement
    since: date | None = None
    until: date | None = None
