"""Response shapes for the research routes."""

from __future__ import annotations

from pydantic import BaseModel

from src.api.models.common import Envelope
from src.research.ingest.materialize import SectionState
from src.research.schemas import NormalizedFinancials


class Section[T](BaseModel):
    """One region of the page, with its own state.

    A slow or missing section never fails the whole page. `reason` is rendered to the user
    verbatim, so it must read as an explanation rather than an exception string.
    """

    state: SectionState
    data: T | None = None
    reason: str | None = None


class AnalysisResponse(Envelope):
    symbol: str
    name: str
    exchange: str | None = None
    is_etf: bool = False
    fundamentals: Section[NormalizedFinancials]
