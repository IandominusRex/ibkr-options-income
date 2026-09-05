"""Watchlist routes: the user's tracked symbols and their landing-page summary.

Items are scoped by ``user_id`` (defaulting to ``"owner"``). A second user's items are not
returned — the multi-user seam is proven before it is needed. Adding a symbol promotes
it to the warm tier immediately: ``warm_symbols()`` reads ``WatchlistItemRow``, so a
newly-added symbol is quoted on the next ``refresh_quotes`` cycle without a restart.

POST/DELETE are idempotent: a repeat add returns 200 (not 201 and not an error); a repeat
delete returns 204. Adding an unknown symbol returns 404 rather than creating a row that
can never resolve to a name.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, HTTPException, Path, Response, status
from sqlalchemy import select

from src.api.deps import CurrentUser, ResearchDb, TradingDb
from src.api.models.common import Source, Sourced
from src.api.models.research import WatchlistItem, WatchlistResponse
from src.research.store.models import (
    QuoteRow,
    SymbolRow,
    WatchlistItemRow,
    WatchlistRow,
)
from src.storage.models import FundamentalCacheRow, IVHistoryRow

router = APIRouter(prefix="/watchlist", tags=["watchlist"])

_DEFAULT_LIST_NAME = "Default"
# Quote freshness for the watchlist price Sourced envelope.
_QUOTE_FRESH_FOR = timedelta(minutes=30)


def _ensure_list(db: ResearchDb, user_id: str) -> WatchlistRow:
    """Find or create the user's default watchlist row. Returns it (flushed)."""
    row = (
        db.execute(
            select(WatchlistRow).where(
                WatchlistRow.user_id == user_id,
                WatchlistRow.name == _DEFAULT_LIST_NAME,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = WatchlistRow(user_id=user_id, name=_DEFAULT_LIST_NAME)
        db.add(row)
        db.flush()
    return row


def _iv_rank_for(trading: TradingDb, symbol: str) -> float | None:
    """Read-only IV rank from the trading DB's iv_history (replicates analytics/iv.py)."""
    rows = (
        (
            trading.execute(
                select(IVHistoryRow.iv)
                .where(IVHistoryRow.symbol == symbol)
                .order_by(IVHistoryRow.obs_date.desc())
                .limit(365)
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return None
    history = list(rows)
    current = history[0]
    lo, hi = min(history), max(history)
    if hi == lo:
        return None
    return round(max(0.0, min(100.0, (current - lo) / (hi - lo) * 100)), 2)


def _next_earnings_for(trading: TradingDb, symbol: str) -> date | None:
    """Read-only next-earnings date from the fundamentals cache (trading DB)."""
    row = trading.get(FundamentalCacheRow, symbol)
    return row.next_earnings_date if row is not None else None


def _checks_summary(symbol: str) -> dict[str, int]:
    """Placeholder check counts for the watchlist row.

    The full checks payload lives on the ticker page (M5). On the watchlist we surface
    only the aggregate {passed, evaluable, unknown} so the row stays scannable; the
    detail is one click away. Computed lazily by the analysis route — here we return
    zeros so the shape is stable before that wiring lands.
    """
    return {"passed": 0, "evaluable": 0, "unknown": 0}


@router.get("", response_model=WatchlistResponse)
def list_watchlist(
    user: CurrentUser,
    db: ResearchDb,
    trading: TradingDb,
) -> WatchlistResponse:
    """Return this user's watchlist items. A second user's items are not returned."""
    now = datetime.now(UTC)
    wl = _ensure_list(db, user.id)
    items = (
        (
            db.execute(
                select(WatchlistItemRow)
                .where(WatchlistItemRow.watchlist_id == wl.id)
                .order_by(WatchlistItemRow.added_at.desc())
            )
        )
        .scalars()
        .all()
    )

    out: list[WatchlistItem] = []
    for item in items:
        sym = item.symbol
        name_row = db.get(SymbolRow, sym)
        name = name_row.name if name_row else sym

        quote = db.get(QuoteRow, sym)
        price_sourced: Sourced[float] | None = None
        change_pct: float | None = None
        if quote is not None:
            change_pct = quote.change_pct
            if quote.price is not None and quote.as_of is not None:
                price_sourced = Sourced[float].of(
                    quote.price,
                    Source.YFINANCE,
                    quote.as_of,
                    fresh_for=_QUOTE_FRESH_FOR,
                )

        iv_rank = _iv_rank_for(trading, sym)
        out.append(
            WatchlistItem(
                symbol=sym,
                name=name,
                price=price_sourced,
                change_pct=change_pct,
                iv_rank=iv_rank,
                checks=_checks_summary(sym),
                next_earnings=_next_earnings_for(trading, sym),
            )
        )

    return WatchlistResponse(as_of=now, items=out)


@router.post("/{symbol}", status_code=status.HTTP_201_CREATED)
def add_symbol(
    user: CurrentUser,
    db: ResearchDb,
    response: Response,
    symbol: str = Path(..., min_length=1, max_length=16),
):
    """Add *symbol* to this user's watchlist. Idempotent: a repeat is 200, not an error.

    Returns 201 on first add, 200 on a repeat. 404 if the symbol is not a known filer — we
    never create a row that can never resolve to a name. Adding a symbol promotes it to the
    warm tier immediately (``warm_symbols`` reads ``WatchlistItemRow``).
    """
    upper = symbol.upper()
    if db.get(SymbolRow, upper) is None:
        raise HTTPException(status_code=404, detail=f"Unknown symbol {upper}")

    wl = _ensure_list(db, user.id)
    existing = (
        db.execute(
            select(WatchlistItemRow).where(
                WatchlistItemRow.watchlist_id == wl.id,
                WatchlistItemRow.symbol == upper,
            )
        )
    ).scalar_one_or_none()

    if existing is not None:
        # Idempotent repeat: 200, no change.
        response.status_code = status.HTTP_200_OK
        return {"symbol": upper, "added": False}

    db.add(
        WatchlistItemRow(
            watchlist_id=wl.id,
            symbol=upper,
            added_at=datetime.now(UTC),
        )
    )
    db.flush()
    return {"symbol": upper, "added": True}


@router.delete("/{symbol}", status_code=status.HTTP_204_NO_CONTENT)
def remove_symbol(
    user: CurrentUser,
    db: ResearchDb,
    symbol: str = Path(..., min_length=1, max_length=16),
):
    """Remove *symbol* from this user's watchlist. Idempotent: a repeat delete is 204."""
    upper = symbol.upper()
    wl = _ensure_list(db, user.id)
    row = (
        db.execute(
            select(WatchlistItemRow).where(
                WatchlistItemRow.watchlist_id == wl.id,
                WatchlistItemRow.symbol == upper,
            )
        )
    ).scalar_one_or_none()
    if row is not None:
        db.delete(row)
        db.flush()
    # 204 either way — idempotent.
