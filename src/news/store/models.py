"""The news service's own SQLite database (``data/news.db``).

A separate engine and DeclarativeBase from the trading DB (the ``src/spreads/store.py``
pattern), so ``create_all`` can never build a news table in ``income_system.db``.
Timestamps are stored naive-UTC; convert with ``queries.aware_utc`` at the edges.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class NewsBase(DeclarativeBase):
    pass


class NewsItemRow(NewsBase):
    __tablename__ = "news_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    url_hash: Mapped[str] = mapped_column(String(40), unique=True)
    title_hash: Mapped[str] = mapped_column(String(40), index=True)
    title: Mapped[str] = mapped_column(String(500))
    url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    source: Mapped[str | None] = mapped_column(String(120), nullable=True)
    source_domain: Mapped[str | None] = mapped_column(String(120), nullable=True)
    category: Mapped[str] = mapped_column(String(16), index=True)
    origin: Mapped[str] = mapped_column(String(16))  # rss | google | yfinance | finnhub
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    tickers: Mapped[list] = mapped_column(JSON, default=list)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    det_sentiment: Mapped[float | None] = mapped_column(Float, nullable=True)
    summary: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    cluster_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)


class NewsClusterRow(NewsBase):
    __tablename__ = "news_clusters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    headline: Mapped[str] = mapped_column(String(500))
    category: Mapped[str] = mapped_column(String(16), index=True)
    first_seen: Mapped[datetime] = mapped_column(DateTime, index=True)
    last_seen: Mapped[datetime] = mapped_column(DateTime, index=True)
    source_domains: Mapped[list] = mapped_column(JSON, default=list)
    source_count: Mapped[int] = mapped_column(Integer, default=1)
    tickers: Mapped[list] = mapped_column(JSON, default=list)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    topic_class: Mapped[str] = mapped_column(String(16), default="other")
    title_tokens: Mapped[list] = mapped_column(JSON, default=list)


class EconEventRow(NewsBase):
    __tablename__ = "econ_events"

    event_key: Mapped[str] = mapped_column(String(200), primary_key=True)
    title: Mapped[str] = mapped_column(String(160))
    playbook_key: Mapped[str | None] = mapped_column(String(40), nullable=True)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime, index=True)  # naive UTC
    impact: Mapped[str] = mapped_column(String(16))
    forecast: Mapped[str | None] = mapped_column(String(40), nullable=True)
    previous: Mapped[str | None] = mapped_column(String(40), nullable=True)
    consensus: Mapped[str | None] = mapped_column(String(40), nullable=True)
    actual: Mapped[str | None] = mapped_column(String(40), nullable=True)
    actual_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    surprise_dir: Mapped[str | None] = mapped_column(String(8), nullable=True)
    alerted: Mapped[bool] = mapped_column(Boolean, default=False)


class EarningsEventRow(NewsBase):
    __tablename__ = "earnings_events"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    report_date: Mapped[date] = mapped_column(Date, primary_key=True)
    timing: Mapped[str] = mapped_column(String(8), default="unknown")  # bmo | amc | unknown
    eps_est: Mapped[float | None] = mapped_column(Float, nullable=True)
    eps_actual: Mapped[float | None] = mapped_column(Float, nullable=True)
    rev_est: Mapped[float | None] = mapped_column(Float, nullable=True)
    rev_actual: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="scheduled")  # scheduled | released
    released_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    alerted: Mapped[bool] = mapped_column(Boolean, default=False)


class FeedStateRow(NewsBase):
    __tablename__ = "feed_state"

    feed_url: Mapped[str] = mapped_column(String(1000), primary_key=True)
    etag: Mapped[str | None] = mapped_column(String(300), nullable=True)
    last_modified: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_polled: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_ok: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class NewsPostRow(NewsBase):
    __tablename__ = "news_posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(24), index=True)
    subject: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    telegram_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chart_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cluster_ids: Mapped[list] = mapped_column(JSON, default=list)
    posted_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    stage: Mapped[str] = mapped_column(String(12), default="facts")  # facts|explained|fallback
    llm_backend: Mapped[str | None] = mapped_column(String(16), nullable=True)
    prompt_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    silent: Mapped[bool] = mapped_column(Boolean, default=False)
    critical: Mapped[bool] = mapped_column(Boolean, default=False)
    edits: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)  # CardPayload.model_dump(mode="json")
    chart_path: Mapped[str | None] = mapped_column(String(300), nullable=True)


class AlertStateRow(NewsBase):
    __tablename__ = "alert_state"
    __table_args__ = (UniqueConstraint("trigger", "subject", "trade_date", name="uq_alert_once"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trigger: Mapped[str] = mapped_column(String(32))
    subject: Mapped[str] = mapped_column(String(200))
    trade_date: Mapped[date] = mapped_column(Date)
    fired_at: Mapped[datetime] = mapped_column(DateTime)


class NewsRequestRow(NewsBase):
    __tablename__ = "news_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    origin: Mapped[str] = mapped_column(String(12))  # telegram | web
    status: Mapped[str] = mapped_column(String(10), default="pending", index=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    post_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(String(300), nullable=True)


class NewsStateRow(NewsBase):
    __tablename__ = "news_state"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(2000))
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class TickerAliasRow(NewsBase):
    __tablename__ = "ticker_aliases"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    fetched_at: Mapped[datetime] = mapped_column(DateTime)
