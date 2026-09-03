"""Research routes: search today, the analysis payload from Milestone 3."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Query
from sqlalchemy import case, func, or_, select

from src.api.deps import CurrentUser, ResearchDb
from src.api.models.common import Envelope
from src.research.store.models import SymbolRow

router = APIRouter(prefix="/research", tags=["research"])


class SearchHit(Envelope):
    symbol: str
    name: str
    exchange: str | None = None
    is_etf: bool = False


class SearchResponse(Envelope):
    query: str
    results: list[SearchHit]


@router.get("/search", response_model=SearchResponse)
def search(
    user: CurrentUser,
    db: ResearchDb,
    q: str = Query(default="", max_length=64),
    limit: int = Query(default=20, ge=1, le=50),
) -> SearchResponse:
    """Rank: exact ticker, then ticker prefix, then name substring.

    Each band is alphabetical within itself. A blank query returns no results rather
    than the whole table.
    """
    now = datetime.now(UTC)
    term = q.strip()
    if not term:
        return SearchResponse(as_of=now, query=q, results=[])

    upper = term.upper()
    like_prefix = f"{upper}%"
    like_name = f"%{term.lower()}%"

    # Ranking bands: 0 exact ticker, 1 ticker prefix, 2 name substring.
    # `case` is portable across SQLite and Postgres (unlike `func.iif`).
    band = case(
        (SymbolRow.symbol == upper, 0),
        (SymbolRow.symbol.like(like_prefix), 1),
        else_=2,
    ).label("band")

    stmt = (
        select(SymbolRow, band)
        .where(
            or_(
                SymbolRow.symbol.like(like_prefix),
                func.lower(SymbolRow.name).like(like_name),
            )
        )
        .order_by(band, SymbolRow.symbol)
        .limit(limit)
    )

    rows = db.execute(stmt).all()
    return SearchResponse(
        as_of=now,
        query=q,
        results=[
            SearchHit(
                as_of=now,
                symbol=row[0].symbol,
                name=row[0].name,
                exchange=row[0].exchange,
                is_etf=row[0].is_etf,
            )
            for row in rows
        ],
    )
