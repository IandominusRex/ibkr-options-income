"""Research-database ORM models.

A SEPARATE SQLAlchemy Base from `src/storage/models.py`, deliberately. SQLite permits one
writer per database; a nightly research ingest writing into the trading database would
serialise against approval_service's writes, and the failure mode is a delayed trade
approval. Keeping the metadata separate also means `create_all()` can never build the wrong
schema against the wrong engine. See Web plan/P0-P1-design.md §4.3.

NEVER import the trading schema's Base (src / storage / models.py) here.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Research schema root. Distinct from the trading schema's Base."""


class SymbolRow(Base):
    """The symbol directory: every SEC filer, refreshed weekly. Search reads this."""

    __tablename__ = "symbols"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    cik: Mapped[str | None] = mapped_column(String(10), index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    exchange: Mapped[str | None] = mapped_column(String(16))
    sector: Mapped[str | None] = mapped_column(String(64))
    industry: Mapped[str | None] = mapped_column(String(128))
    is_etf: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)


class CompanyFactsRawRow(Base):
    """Raw EDGAR companyfacts payload, kept so normalisation is replayable.

    When the concept map gains a mapping, every affected symbol can be re-normalised
    without re-fetching from SEC.
    """

    __tablename__ = "company_facts_raw"

    cik: Mapped[str] = mapped_column(String(10), primary_key=True)
    payload_json: Mapped[str] = mapped_column(Text)
    etag: Mapped[str | None] = mapped_column(String(128))
    fetched_at: Mapped[datetime] = mapped_column(DateTime)


class FinancialRow(Base):
    """One normalised line item for one period, traceable to its filing."""

    __tablename__ = "financials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    period_end: Mapped[date] = mapped_column(Date)
    period_type: Mapped[str] = mapped_column(String(8))  # "annual" | "quarterly"
    line_item: Mapped[str] = mapped_column(String(64))
    value: Mapped[float | None] = mapped_column(Float)
    concept: Mapped[str | None] = mapped_column(String(128))
    accn: Mapped[str | None] = mapped_column(String(32))
    filed: Mapped[date | None] = mapped_column(Date)
    form: Mapped[str | None] = mapped_column(String(16))

    __table_args__ = (
        Index("ix_financials_lookup", "symbol", "period_type", "line_item", "period_end"),
    )


class DailyBarRow(Base):
    __tablename__ = "daily_bars"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    open: Mapped[float | None] = mapped_column(Float)
    high: Mapped[float | None] = mapped_column(Float)
    low: Mapped[float | None] = mapped_column(Float)
    close: Mapped[float | None] = mapped_column(Float)
    volume: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(16), default="stooq")


class QuoteRow(Base):
    """Delayed intraday quote for a warm-tier symbol. One row per symbol."""

    __tablename__ = "quotes"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    price: Mapped[float | None] = mapped_column(Float)
    change_pct: Mapped[float | None] = mapped_column(Float)
    as_of: Mapped[datetime] = mapped_column(DateTime)
    source: Mapped[str] = mapped_column(String(16), default="yfinance")


class NewsItemRow(Base):
    __tablename__ = "news_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime)
    title: Mapped[str] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(String(64))
    sentiment: Mapped[float | None] = mapped_column(Float)


class AnalysisCacheRow(Base):
    """The assembled ticker-page payload. One row per symbol."""

    __tablename__ = "analysis_cache"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    payload_json: Mapped[str] = mapped_column(Text)
    computed_at: Mapped[datetime] = mapped_column(DateTime)
    tier: Mapped[str] = mapped_column(String(8), default="cold")  # hot | warm | cold


class CheckResultRow(Base):
    __tablename__ = "check_results"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    check_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    state: Mapped[str] = mapped_column(String(16))  # PASS | FAIL | UNKNOWN | NOT_APPLICABLE
    actual: Mapped[float | None] = mapped_column(Float)
    threshold: Mapped[float | None] = mapped_column(Float)
    computed_at: Mapped[datetime] = mapped_column(DateTime)


class SummaryRow(Base):
    __tablename__ = "summaries"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    model: Mapped[str] = mapped_column(String(64), primary_key=True)
    prompt_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    data_as_of: Mapped[datetime] = mapped_column(DateTime)
    payload_json: Mapped[str] = mapped_column(Text)
    generated_at: Mapped[datetime] = mapped_column(DateTime)


class WatchlistRow(Base):
    __tablename__ = "watchlists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True, default="owner")
    name: Mapped[str] = mapped_column(String(64), default="Default")


class WatchlistItemRow(Base):
    __tablename__ = "watchlist_items"

    watchlist_id: Mapped[int] = mapped_column(
        ForeignKey("watchlists.id", ondelete="CASCADE"), primary_key=True
    )
    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    added_at: Mapped[datetime] = mapped_column(DateTime)


class RecentlyViewedRow(Base):
    __tablename__ = "recently_viewed"

    user_id: Mapped[str] = mapped_column(String(64), primary_key=True, default="owner")
    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    viewed_at: Mapped[datetime] = mapped_column(DateTime)


class WorkerHeartbeatRow(Base):
    """Single-row table. Written only after a job SUCCEEDS, so /health cannot lie."""

    __tablename__ = "worker_heartbeat"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    beat_at: Mapped[datetime] = mapped_column(DateTime)
    last_job: Mapped[str | None] = mapped_column(String(64))


class IngestJobRow(Base):
    __tablename__ = "ingest_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    kind: Mapped[str] = mapped_column(String(32))  # fundamentals | prices | news | quote
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    enqueued_at: Mapped[datetime] = mapped_column(DateTime)
