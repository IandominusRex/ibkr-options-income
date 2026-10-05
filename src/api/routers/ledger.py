"""GET /ledger/* — the whole-account trade ledger (docs/superpowers/specs/2026-10-04-trade-ledger-design.md §6).

Thin renderers over src/reporting/trade_ledger.py: every figure comes from ``build_book``, so the
trades table, ticker pages, summary tiles, CSV export and the Google Sheet mirror agree by
construction. Read-only — every write is a POST /commands intent (ledger_import,
ledger_annotate, ledger_ca_reviewed) that the drain applies (R11).
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, date, datetime
from typing import Literal, cast
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from src.api.deps import OwnerUser, TradingDb
from src.api.models.ledger import (
    LedgerCorporateActionOut,
    LedgerExecutionOut,
    LedgerFeedStatus,
    LedgerImportRunOut,
    LedgerImportsResponse,
    LedgerSummaryResponse,
    LedgerTickerResponse,
    LedgerTickersResponse,
    LedgerTradeResponse,
    LedgerTradesFilters,
    LedgerTradesResponse,
)
from src.api.portfolio_source import read_portfolio
from src.common.config import get_config
from src.common.schemas import LedgerBook, LedgerOutcome, LedgerTrade, OptionRight
from src.ledger.state import (
    LEDGER_FLEX_LAST_RUN_KEY,
    LEDGER_FLEX_LAST_STATUS_KEY,
    LEDGER_SHEETS_LAST_ERROR_KEY,
    LEDGER_SHEETS_LAST_SYNC_KEY,
)
from src.reporting.trade_ledger import (
    SHEET_HEADER,
    TradeSort,
    build_book,
    filter_trades,
    sheet_row,
    ticker_detail,
)
from src.storage.models import (
    BrokerCorporateActionRow,
    BrokerExecutionRow,
    LedgerImportRunRow,
    SystemSettingRow,
)

router = APIRouter(prefix="/ledger", tags=["ledger"])

_ET = ZoneInfo("America/New_York")


def _book(db: Session) -> LedgerBook:
    reading = read_portfolio(db)
    return build_book(
        db, today=datetime.now(_ET).date(), snapshot=reading.snapshot, marks_as_of=reading.as_of
    )


def _now() -> datetime:
    return datetime.now(UTC)


def _filtered(db: Session, f: LedgerTradesFilters) -> list[LedgerTrade]:
    # f.right is an `OptionRight` (see LedgerTradesFilters — a real Enum, not a bare Literal,
    # to dodge pydantic's process-global inline-Literal schema cache; see the comment there).
    # filter_trades' own signature (Task 6/7, not ours to change) still takes the narrower
    # Literal["P", "C"] it was written against — OptionRight's values ARE exactly "P"/"C", so
    # this cast is just bridging two correct, differently-shaped types, not a real unsafe cast.
    right = cast(Literal["P", "C"], f.right.value) if f.right is not None else None
    return filter_trades(
        _book(db).trades,
        symbol=f.symbol,
        right=right,
        outcome=f.outcome,
        book=f.book,
        tag=f.tag,
        since=f.since,
        until=f.until,
        sort=f.sort,
    )


def _filters(
    symbol: str | None,
    right: OptionRight | None,
    outcome: LedgerOutcome | None,
    book: Literal["system", "manual"] | None,
    tag: str | None,
    since: date | None,
    until: date | None,
    sort: TradeSort,
) -> LedgerTradesFilters:
    return LedgerTradesFilters(
        symbol=symbol.upper() if symbol else None,
        right=right,
        outcome=outcome,
        book=book,
        tag=tag,
        since=since,
        until=until,
        sort=sort,
    )


def _setting(db: Session, key: str) -> str | None:
    value = db.scalar(select(SystemSettingRow.value).where(SystemSettingRow.key == key))
    return value or None


@router.get("/summary", response_model=LedgerSummaryResponse)
def get_summary(db: TradingDb, _user: OwnerUser) -> LedgerSummaryResponse:
    return LedgerSummaryResponse(as_of=_now(), summary=_book(db).summary)


@router.get("/tickers", response_model=LedgerTickersResponse)
def get_tickers(db: TradingDb, _user: OwnerUser) -> LedgerTickersResponse:
    tickers = sorted(_book(db).tickers, key=lambda t: t.total_realized, reverse=True)
    return LedgerTickersResponse(as_of=_now(), tickers=tickers)


@router.get("/tickers/{symbol}", response_model=LedgerTickerResponse)
def get_ticker(symbol: str, db: TradingDb, _user: OwnerUser) -> LedgerTickerResponse:
    detail = ticker_detail(_book(db), symbol)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"No ledger history for {symbol.upper()}")
    return LedgerTickerResponse(as_of=_now(), detail=detail)


@router.get("/trades", response_model=LedgerTradesResponse)
def get_trades(
    db: TradingDb,
    _user: OwnerUser,
    symbol: str | None = None,
    right: OptionRight | None = None,
    outcome: LedgerOutcome | None = None,
    book: Literal["system", "manual"] | None = None,
    tag: str | None = None,
    since: date | None = None,
    until: date | None = None,
    # Bare default, not `Query(...)`: `TradeSort` is a `Literal[...]` ALIAS (defined once in
    # trade_ledger.py per F10), and ruff's B008 immutable-annotation allowlist only recognizes
    # inline `Literal[...]` syntax, not a name bound to one — wrapping this in `Query(...)`
    # would trip the mutable-default-argument lint for no behavioural gain (same convention
    # `options.py::list_approvals` already uses for `since`/`until`).
    sort: TradeSort = "-order_date",
) -> LedgerTradesResponse:
    f = _filters(symbol, right, outcome, book, tag, since, until, sort)
    trades = _filtered(db, f)
    return LedgerTradesResponse(as_of=_now(), filters=f, n=len(trades), trades=trades)


@router.get("/trades.csv")
def get_trades_csv(
    db: TradingDb,
    _user: OwnerUser,
    symbol: str | None = None,
    right: OptionRight | None = None,
    outcome: LedgerOutcome | None = None,
    book: Literal["system", "manual"] | None = None,
    tag: str | None = None,
    since: date | None = None,
    until: date | None = None,
    sort: TradeSort = "-order_date",
) -> Response:
    trades = _filtered(db, _filters(symbol, right, outcome, book, tag, since, until, sort))
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(SHEET_HEADER)
    writer.writerows(sheet_row(t) for t in trades)
    filename = f"trade-ledger-{datetime.now(_ET).date().isoformat()}.csv"
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/trades/{order_key}", response_model=LedgerTradeResponse)
def get_trade(order_key: str, db: TradingDb, _user: OwnerUser) -> LedgerTradeResponse:
    trade = next((t for t in _book(db).trades if t.order_key == order_key), None)
    if trade is None:
        raise HTTPException(status_code=404, detail="No such trade")
    ids = trade.exec_row_ids
    rows = db.scalars(
        select(BrokerExecutionRow)
        .where(or_(BrokerExecutionRow.id.in_(ids), BrokerExecutionRow.superseded_by.in_(ids)))
        .order_by(BrokerExecutionRow.trade_time, BrokerExecutionRow.id)
    )
    executions = [
        LedgerExecutionOut(
            id=r.id,
            source=r.source,
            source_kind=r.source_kind,
            exec_id=r.exec_id,
            trade_time=r.trade_time.replace(tzinfo=UTC),
            quantity=r.quantity,
            price=r.price,
            proceeds=r.proceeds,
            commission=r.commission,
            codes=r.codes,
            book=r.book,
            superseded_by=r.superseded_by,
        )
        for r in rows
    ]
    return LedgerTradeResponse(as_of=_now(), trade=trade, executions=executions)


@router.get("/imports", response_model=LedgerImportsResponse)
def get_imports(db: TradingDb, _user: OwnerUser) -> LedgerImportsResponse:
    secrets = get_config().secrets
    runs = db.scalars(
        select(LedgerImportRunRow)
        .where(LedgerImportRunRow.source.in_(("csv", "flex")))
        .order_by(LedgerImportRunRow.id.desc())
        .limit(50)
    )
    actions = db.scalars(
        select(BrokerCorporateActionRow)
        .order_by(BrokerCorporateActionRow.reviewed, BrokerCorporateActionRow.event_date.desc())
        .limit(100)
    )
    return LedgerImportsResponse(
        as_of=_now(),
        runs=[
            LedgerImportRunOut(
                id=r.id,
                source=r.source,
                filename=r.filename,
                started_at=r.started_at.replace(tzinfo=UTC),
                finished_at=r.finished_at.replace(tzinfo=UTC) if r.finished_at else None,
                status=r.status,
                reason=r.reason,
                counts=r.counts or {},
                errors=(r.errors or [])[:50],
            )
            for r in runs
        ],
        flex=LedgerFeedStatus(
            configured=bool(secrets.ibkr_flex_token and secrets.ibkr_flex_query_id),
            last_run=_setting(db, LEDGER_FLEX_LAST_RUN_KEY),
            last_status=_setting(db, LEDGER_FLEX_LAST_STATUS_KEY),
            last_error=None,
        ),
        sheets=LedgerFeedStatus(
            configured=bool(secrets.google_sheets_credentials_path and secrets.ledger_sheet_id),
            last_run=_setting(db, LEDGER_SHEETS_LAST_SYNC_KEY),
            last_status=None,
            last_error=_setting(db, LEDGER_SHEETS_LAST_ERROR_KEY),
        ),
        corporate_actions=[
            LedgerCorporateActionOut(
                id=a.id,
                event_date=a.event_date,
                underlying=a.underlying,
                description=a.description,
                quantity=a.quantity,
                proceeds=a.proceeds,
                reviewed=a.reviewed,
            )
            for a in actions
        ],
    )
