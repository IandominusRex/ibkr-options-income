"""Brief request queue (spec §7.5) — the ONLY src.news module approval_service imports
(fence §10.7). One insert, one read, nothing else: no LLM, ingest or publish code is loaded
into the trading bot's process."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import select

from src.common.config import get_config
from src.news.store.models import NewsPostRow, NewsRequestRow
from src.news.store.queries import naive_utc
from src.news.store.session import init_news_db, news_session

SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


class InvalidSymbol(ValueError):
    pass


def normalize_symbol(raw: str) -> str:
    sym = (raw or "").strip().lstrip("$").upper()
    if not SYMBOL_RE.match(sym):
        raise InvalidSymbol(raw)
    return sym


def enqueue_brief(
    symbol: str, origin: Literal["telegram", "web"], *, now: datetime | None = None
) -> int:
    sym = normalize_symbol(symbol)
    now_n = naive_utc(now or datetime.now(UTC))
    recent = now_n - timedelta(minutes=get_config().news.briefs.dedupe_minutes)
    init_news_db()  # idempotent; the approval process may enqueue before the news process ever ran
    with news_session() as s:
        existing = s.scalar(
            select(NewsRequestRow)
            .where(NewsRequestRow.symbol == sym)
            .where(
                (NewsRequestRow.status.in_(("pending", "running")))
                | ((NewsRequestRow.status == "done") & (NewsRequestRow.finished_at >= recent))
            )
            .order_by(NewsRequestRow.id.desc())
        )
        if existing is not None:
            return existing.id
        row = NewsRequestRow(symbol=sym, origin=origin, status="pending", requested_at=now_n)
        s.add(row)
        s.flush()
        return row.id


def claim_next(now: datetime) -> tuple[int, str] | None:
    with news_session() as s:
        row = s.scalar(
            select(NewsRequestRow)
            .where(NewsRequestRow.status == "pending")
            .order_by(NewsRequestRow.id)
        )
        if row is None:
            return None
        row.status, row.started_at = "running", naive_utc(now)
        return row.id, row.symbol


def finish(
    req_id: int, *, now: datetime, post_id: int | None = None, error: str | None = None
) -> None:
    with news_session() as s:
        row = s.get(NewsRequestRow, req_id)
        if row is None:
            return
        row.status = "failed" if error else "done"
        row.finished_at, row.post_id = naive_utc(now), post_id
        row.error = error[:300] if error else None


def latest_digest_link(chat_id: str, thread: str) -> str | None:
    with news_session() as s:
        mid = s.scalar(
            select(NewsPostRow.telegram_message_id)
            .where(NewsPostRow.kind.like("digest_%"), NewsPostRow.telegram_message_id.is_not(None))
            .order_by(NewsPostRow.posted_at.desc())
        )
    if mid is None or not chat_id.startswith("-100"):
        return None
    return (
        f"https://t.me/c/{chat_id[4:]}/{thread}/{mid}"
        if thread
        else f"https://t.me/c/{chat_id[4:]}/{mid}"
    )
