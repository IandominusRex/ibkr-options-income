"""SQLAlchemy ORM models — the persisted state of the system.

Tables map roughly to pipeline stages: candidates produced, risk verdicts,
Claude reviews, approvals, orders, fills, the IV history used for IV Rank, and
the daily journal. Lightweight by design; JSON columns hold the richer Pydantic
payloads so the schema stays stable as those evolve.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class CandidateRow(Base):
    __tablename__ = "candidates"
    __table_args__ = (UniqueConstraint("candidate_id", name="uq_candidates_candidate_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    candidate_id: Mapped[str] = mapped_column(String(64), index=True)
    run_id: Mapped[str] = mapped_column(String(40), index=True)  # which scan produced it
    strategy: Mapped[str] = mapped_column(String(20))
    underlying: Mapped[str] = mapped_column(String(16), index=True)
    right: Mapped[str] = mapped_column(String(1))
    strike: Mapped[float] = mapped_column(Float)
    expiry: Mapped[date] = mapped_column(Date)
    blended_score: Mapped[float] = mapped_column(Float, default=0.0)
    payload: Mapped[dict] = mapped_column(JSON)  # full TradeCandidate.model_dump()
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class RiskVerdictRow(Base):
    __tablename__ = "risk_verdicts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    candidate_id: Mapped[str] = mapped_column(String(64), index=True)
    verdict: Mapped[str] = mapped_column(String(10))
    reasons: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class ClaudeReviewRow(Base):
    __tablename__ = "claude_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    candidate_id: Mapped[str] = mapped_column(String(64), index=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    recommendation: Mapped[str] = mapped_column(String(20))
    payload: Mapped[dict] = mapped_column(JSON)  # full ClaudeReview
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class ApprovalRow(Base):
    __tablename__ = "approvals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    candidate_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(12), default="pending")
    telegram_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chat_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Frozen TradeCandidate payload the human was shown when this approval was raised (N2a).
    # Copied onto the OrderRow at approval time so execution runs the size/premium that was
    # actually approved, never a payload mutated by a later re-scan.
    snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class OrderRow(Base):
    __tablename__ = "orders"
    __table_args__ = (UniqueConstraint("approval_id", name="uq_orders_approval_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    candidate_id: Mapped[str] = mapped_column(String(64), index=True)
    approval_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ib_order_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    state: Mapped[str] = mapped_column(String(12), default="queued")
    limit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    filled_qty: Mapped[float] = mapped_column(Float, default=0.0)
    avg_fill_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_live: Mapped[bool] = mapped_column(Boolean, default=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Frozen approved TradeCandidate payload (N2a). process_queued_orders executes THIS, not the
    # latest CandidateRow payload, so a 15-min re-scan that changes contracts/premium between
    # approval and execution can never alter the size the human approved. Nullable for rows
    # created before the freeze was introduced (execution falls back to CandidateRow then).
    snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class IVHistoryRow(Base):
    """Daily implied-vol observations powering IV Rank/Percentile."""

    __tablename__ = "iv_history"
    __table_args__ = (UniqueConstraint("symbol", "obs_date", name="uq_iv_history_symbol_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    obs_date: Mapped[date] = mapped_column(Date, index=True)
    iv: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(16), default="ibkr")


class OptionQuoteRow(Base):
    """Option chain snapshot: one row per (run_id, symbol) with all quotes as JSON."""

    __tablename__ = "option_quotes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(40), index=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    payload: Mapped[list] = mapped_column(JSON)  # list[OptionQuote.model_dump()]
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class PositionSnapshotRow(Base):
    """Daily portfolio snapshot for assignment auto-detection (position diffing).

    One row per ET trading day, written by the EOD run. Assignment detection diffs the most
    recent prior snapshot against current positions: a short option that vanished plus a stock
    position that moved by ~100×contracts in the assignment direction is an assignment, not an
    expiry. (SYSTEM_REVIEW Phase 4 — assignment auto-detection.)
    """

    __tablename__ = "position_snapshots"
    __table_args__ = (UniqueConstraint("snapshot_date", name="uq_position_snapshots_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_date: Mapped[date] = mapped_column(Date, index=True)
    payload: Mapped[list] = mapped_column(JSON)  # list[PositionSnapshot.model_dump(mode="json")]
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class FillRow(Base):
    """One row per execution fill; order may have multiple (partial fills)."""

    __tablename__ = "fills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(Integer, index=True)
    candidate_id: Mapped[str] = mapped_column(String(64), index=True)
    ib_exec_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Order side: "SELL" (premium credit) or "BUY" (debit, e.g. a buy-to-close).
    # Used to sign the EOD option premium cashflow correctly.
    action: Mapped[str] = mapped_column(String(4), default="SELL")
    filled_qty: Mapped[float] = mapped_column(Float)
    avg_price: Mapped[float] = mapped_column(Float)
    commission: Mapped[float | None] = mapped_column(Float, nullable=True)
    entry_iv: Mapped[float | None] = mapped_column(Float, nullable=True)  # IV at execution time
    is_live: Mapped[bool] = mapped_column(Boolean, default=False)
    filled_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class RollAlertRow(Base):
    """One row per fired roll-trigger alert; used for de-duplication and audit."""

    __tablename__ = "roll_alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    position_symbol: Mapped[str] = mapped_column(String(32), index=True)
    underlying: Mapped[str] = mapped_column(String(16), index=True)
    trigger: Mapped[str] = mapped_column(String(20))
    detail: Mapped[str] = mapped_column(Text)
    claude_recommendation: Mapped[str | None] = mapped_column(String(20), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class ClaudeMemoryRow(Base):
    """Persistent record of Claude recommendations across scan runs.

    Enables Claude to learn from prior decisions by injecting this history into
    each new scan prompt. Outcomes are back-filled as approvals and fills happen.
    """

    __tablename__ = "claude_memory"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scan_date: Mapped[date] = mapped_column(Date, index=True)
    underlying: Mapped[str] = mapped_column(String(16), index=True)
    strategy_type: Mapped[str] = mapped_column(
        String(20)
    )  # covered_call | cash_secured_put | buy_to_own
    recommendation: Mapped[str] = mapped_column(String(20))  # sell | skip | buy | wait
    priority: Mapped[int] = mapped_column(Integer, default=0)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    rationale: Mapped[str] = mapped_column(Text, default="")
    outcome: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # filled | user_rejected | risk_rejected | expired | None
    outcome_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    candidate_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class VerdictLedgerRow(Base):
    """Outcome ledger — one row per Claude-reviewed candidate.

    Captures the full signal vector Claude saw, its verdict, and the deterministic baseline
    counterfactual at scan time; the realized trade outcome (assigned / expired / closed early,
    P&L) is back-filled by the reconciler when the position closes. This is the labeled history
    that powers verdict evaluation and the skill loop. Enrichment-layer only — the risk engine
    never reads it. Upserted on candidate_id so a re-scan refreshes the pre-outcome fields.
    """

    __tablename__ = "verdict_ledger"
    __table_args__ = (UniqueConstraint("candidate_id", name="uq_verdict_ledger_candidate_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    candidate_id: Mapped[str] = mapped_column(String(64), index=True)
    run_id: Mapped[str] = mapped_column(String(40), index=True)
    scan_date: Mapped[date] = mapped_column(Date, index=True)
    underlying: Mapped[str] = mapped_column(String(16), index=True)
    strategy: Mapped[str] = mapped_column(String(20))
    right: Mapped[str] = mapped_column(String(1))
    strike: Mapped[float] = mapped_column(Float)
    expiry: Mapped[date] = mapped_column(Date)
    dte: Mapped[int] = mapped_column(Integer, default=0)
    signals: Mapped[dict] = mapped_column(JSON, default=dict)  # signal vector Claude saw
    # Claude verdict
    claude_recommendation: Mapped[str] = mapped_column(String(10), default="none")
    claude_priority: Mapped[int | None] = mapped_column(Integer, nullable=True)
    claude_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    claude_rationale: Mapped[str] = mapped_column(Text, default="")
    # Deterministic baseline counterfactual
    baseline_recommendation: Mapped[str] = mapped_column(String(10), default="skip")
    baseline_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    baseline_score: Mapped[float] = mapped_column(Float, default=0.0)
    agreement: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # Realized outcome (back-filled on close)
    outcome: Mapped[str] = mapped_column(String(20), default="still_open", index=True)
    outcome_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    realized_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    filled: Mapped[bool] = mapped_column(Boolean, default=False)
    entry_premium: Mapped[float | None] = mapped_column(Float, nullable=True)
    contracts: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class SystemSettingRow(Base):
    """Persistent key-value store for runtime system settings (e.g. automated_mode toggle)."""

    __tablename__ = "system_settings"
    __table_args__ = (UniqueConstraint("key", name="uq_system_settings_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(64), index=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class JournalRow(Base):
    """End-of-day narrative + metrics, written by the EOD orchestrator."""

    __tablename__ = "journal"
    __table_args__ = (UniqueConstraint("entry_date", name="uq_journal_entry_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entry_date: Mapped[date] = mapped_column(Date, index=True)
    realized_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    unrealized_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    narrative: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
