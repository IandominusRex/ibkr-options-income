"""Response shapes for GET /ledger/* (docs/superpowers/specs/2026-10-04-trade-ledger-design.md §6.1)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

from src.api.models.common import Envelope
from src.common.schemas import (
    LedgerBookName,
    LedgerOutcome,
    LedgerSummary,
    LedgerTicker,
    LedgerTickerDetail,
    LedgerTrade,
)
from src.reporting.trade_ledger import TradeSort


class LedgerSummaryResponse(Envelope):
    summary: LedgerSummary


class LedgerTickersResponse(Envelope):
    tickers: list[LedgerTicker]


class LedgerTickerResponse(Envelope):
    detail: LedgerTickerDetail


class LedgerTradesFilters(BaseModel):
    symbol: str | None = None
    # `Literal["C", "P"]`, matching `filter_trades`'s own signature AND the order
    # `LedgerContract.right`/`LedgerTrade.right`/`CampaignLeg.right`/`OptionLeg.right` all
    # already use: pydantic's JSON-schema generator shares a process-global cache for inline
    # Literal schemas keyed by VALUE SET, order-insensitive, so the FIRST such schema built
    # anywhere in the app silently wins the rendered member order for every other one with the
    # same value set. A second, reversed declaration (`Literal["P", "C"]`) is what made
    # docs/web/openapi.json nondeterministic under the full test suite until this was aligned —
    # every "P"/"C" Literal in the app must declare this same order, or the ambiguity returns.
    right: Literal["C", "P"] | None = None
    outcome: LedgerOutcome | None = None
    book: LedgerBookName | None = None
    tag: str | None = None
    since: date | None = None
    until: date | None = None
    sort: TradeSort = "-order_date"


class LedgerTradesResponse(Envelope):
    filters: LedgerTradesFilters
    n: int
    trades: list[LedgerTrade]


class LedgerExecutionOut(BaseModel):
    id: int
    source: str
    source_kind: str
    exec_id: str | None
    trade_time: datetime
    quantity: float
    price: float
    proceeds: float
    commission: float
    codes: str
    book: str
    superseded_by: int | None


class LedgerTradeResponse(Envelope):
    trade: LedgerTrade
    executions: list[LedgerExecutionOut]


class LedgerImportRunOut(BaseModel):
    id: int
    source: str
    filename: str | None
    started_at: datetime
    finished_at: datetime | None
    status: str
    reason: str | None
    counts: dict[str, int]
    errors: list[dict[str, object]]


class LedgerFeedStatus(BaseModel):
    configured: bool
    last_run: str | None
    last_status: str | None
    last_error: str | None


class LedgerCorporateActionOut(BaseModel):
    id: int
    event_date: date
    underlying: str | None
    description: str
    quantity: float
    proceeds: float
    reviewed: bool


class LedgerImportsResponse(Envelope):
    runs: list[LedgerImportRunOut]
    flex: LedgerFeedStatus
    sheets: LedgerFeedStatus
    corporate_actions: list[LedgerCorporateActionOut]
