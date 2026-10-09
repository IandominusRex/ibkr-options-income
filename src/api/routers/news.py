"""GET /news/* — read-only views over data/news.db (spec §7.6).

Every write is the news_brief command (POST /commands); this router never writes and never
imports the news process's read-write engine (src.news.store.session) — it reads through
src/api/news_db.py (mode=ro) and the Session-parameterised helpers in src.news.store.queries.
A missing or unopenable news.db answers `available: false`, never a 500.
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy.orm import Session

from src.api.deps import OwnerUser, TradingDb
from src.api.models.news import (
    ClusterOut,
    EarningsOut,
    EconEventOut,
    NewsCalendarResponse,
    NewsFeedResponse,
    NewsPostDetailResponse,
    NewsPostOut,
    NewsRequestOut,
    NewsStatusResponse,
    NewsTickerResponse,
    SourceLinkOut,
)
from src.api.news_db import news_read_session
from src.api.portfolio_source import read_portfolio
from src.common.config import ROOT, get_config
from src.news.links import links_for
from src.news.store import queries
from src.news.store.models import NewsPostRow
from src.news.store.queries import aware_utc

router = APIRouter(prefix="/news", tags=["news"])
ET = ZoneInfo("America/New_York")
Group = Literal["macro", "market", "tickers", "earnings", "briefs"]


def _now() -> datetime:
    return datetime.now(UTC)


def _post_out(r: NewsPostRow) -> NewsPostOut:
    return NewsPostOut(
        id=r.id,
        kind=r.kind,
        subject=r.subject,
        posted_at=aware_utc(r.posted_at),
        stage=r.stage,
        critical=r.critical,
        silent=r.silent,
        has_chart=bool(r.chart_path),
        payload=r.payload or {},
    )


def _charts_dir() -> Path:
    d = Path(get_config().news.charts_dir)
    return (d if d.is_absolute() else ROOT / d).resolve()


def _chart_uri(path: str | None) -> str | None:
    """Inline a post's PNG — only from inside news.charts_dir, never an arbitrary stored path."""
    if not path:
        return None
    p = Path(path).resolve()
    if _charts_dir() not in p.parents or not p.is_file():
        return None
    return "data:image/png;base64," + base64.b64encode(p.read_bytes()).decode()


@router.get("/feed", response_model=NewsFeedResponse)
def feed(
    _: OwnerUser,
    group: Group | None = None,
    symbol: str | None = None,
    limit: int = Query(30, ge=1, le=100),
    before: int | None = None,
) -> NewsFeedResponse:
    with news_read_session() as s:
        if s is None:
            return NewsFeedResponse(as_of=_now(), available=False)
        rows = queries.recent_posts(s, group=group, symbol=symbol, limit=limit, before_id=before)
        return NewsFeedResponse(as_of=_now(), available=True, posts=[_post_out(r) for r in rows])


@router.get("/posts/{post_id}", response_model=NewsPostDetailResponse)
def post_detail(post_id: int, _: OwnerUser) -> NewsPostDetailResponse:
    with news_read_session() as s:
        row = s.get(NewsPostRow, post_id) if s is not None else None
        if row is None:
            raise HTTPException(status_code=404, detail="Post not found")
        return NewsPostDetailResponse(
            as_of=_now(),
            available=True,
            post=_post_out(row),
            chart_data_uri=_chart_uri(row.chart_path),
        )


def _held(db: Session) -> set[str]:
    """Held underlyings from the trading DB the API already reads (never src.news.collectors —
    that module loads the news process's read-write engine)."""
    snap = read_portfolio(db).snapshot
    positions = snap.positions if snap else []
    return {(p.underlying or p.symbol).upper() for p in positions if p.position != 0}


@router.get("/calendar", response_model=NewsCalendarResponse)
def calendar(
    _: OwnerUser, db: TradingDb, days: int = Query(7, ge=1, le=21)
) -> NewsCalendarResponse:
    now = _now()
    with news_read_session() as s:
        if s is None:
            return NewsCalendarResponse(as_of=now, available=False)
        econ = queries.econ_events_between(s, now - timedelta(hours=12), now + timedelta(days=days))
        today = now.astimezone(ET).date()
        earn = queries.earnings_between(s, today, today + timedelta(days=days))
    held = _held(db)
    return NewsCalendarResponse(
        as_of=now,
        available=True,
        econ=[
            EconEventOut(
                title=e.title,
                scheduled_at=e.scheduled_at,
                impact=e.impact,
                forecast=e.forecast,
                previous=e.previous,
                actual=e.actual,
                surprise_dir=e.surprise_dir,
            )
            for e in econ
        ],
        earnings=[
            EarningsOut(
                symbol=e.symbol,
                report_date=e.report_date,
                timing=e.timing,
                eps_est=e.eps_est,
                eps_actual=e.eps_actual,
                status=e.status,
                held=e.symbol in held,
            )
            for e in earn
        ],
    )


@router.get("/ticker/{symbol}", response_model=NewsTickerResponse)
def ticker(symbol: str, _: OwnerUser) -> NewsTickerResponse:
    sym = symbol.upper()
    now = _now()
    with news_read_session() as s:
        if s is None:
            return NewsTickerResponse(as_of=now, available=False, symbol=sym)
        brief = queries.latest_brief(s, sym)
        clusters = queries.clusters_since(s, now - timedelta(hours=72), symbol=sym, limit=10)
        today = now.astimezone(ET).date()
        upcoming = queries.earnings_between(
            s, today - timedelta(days=1), today + timedelta(days=60), {sym}
        )
        req = queries.request_for(s, sym)
        rank = get_config().news.source_rank
        nxt = upcoming[0] if upcoming else None
        return NewsTickerResponse(
            as_of=now,
            available=True,
            symbol=sym,
            latest_brief=_post_out(brief) if brief else None,
            clusters=[
                ClusterOut(
                    id=c.id,
                    headline=c.headline,
                    source_count=c.source_count,
                    last_seen=c.last_seen,
                    links=[SourceLinkOut(name=lk.name, url=lk.url) for lk in links_for(c, rank)],
                )
                for c in clusters
            ],
            next_earnings=(
                EarningsOut(
                    symbol=sym,
                    report_date=nxt.report_date,
                    timing=nxt.timing,
                    eps_est=nxt.eps_est,
                    eps_actual=nxt.eps_actual,
                    status=nxt.status,
                )
                if nxt
                else None
            ),
            request=(
                NewsRequestOut(
                    id=req.id,
                    status=req.status,
                    requested_at=aware_utc(req.requested_at),
                    post_id=req.post_id,
                    error=req.error,
                )
                if req
                else None
            ),
        )


@router.get("/status", response_model=NewsStatusResponse)
def status(_: OwnerUser) -> NewsStatusResponse:
    now = _now()
    cap = get_config().news.llm.max_calls_per_day
    llm_key = f"llm_calls:{now.astimezone(ET).date().isoformat()}"
    with news_read_session() as s:
        if s is None:
            return NewsStatusResponse(as_of=now, available=False, llm_cap=cap)
        hb = queries.state_values(s, "heartbeat").get("heartbeat")
        src_ok = queries.state_values(s, "source_ok:")
        calls = queries.state_values(s, llm_key).get(llm_key)
    hb_at = aware_utc(datetime.fromisoformat(hb)) if hb else None
    return NewsStatusResponse(
        as_of=now,
        available=True,
        heartbeat_at=hb_at,
        heartbeat_age_s=(now - hb_at).total_seconds() if hb_at else None,
        sources_ok={
            k.split(":", 1)[1]: aware_utc(datetime.fromisoformat(v)) for k, v in src_ok.items()
        },
        llm_calls_today=int(calls) if calls else 0,
        llm_cap=cap,
    )
