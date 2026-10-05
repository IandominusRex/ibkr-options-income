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
    """The fate of every contract a scan priced — approved or not, and why not.

    Rejections used to be entirely ephemeral: generator-stage filters left only an aggregate
    log counter, gate-stage verdicts lived in memory until the run ended, and dedupe/top-N
    losers vanished. That made "why did NVDA never fire in July?" unanswerable after the fact.

    One row per assessed contract per run. `stage` says how far it got (see
    :class:`~src.common.schemas.AssessmentStage`); `reasons` is the raw code list the
    formatters humanize. The ideal-zone columns are denormalized so a historical row can be
    read without recomputing the zone from analytics that have since moved.

    Written best-effort by ``storage.risk_verdicts.record_assessments`` and pruned to 14 days
    by the EOD run.
    """

    __tablename__ = "risk_verdicts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    candidate_id: Mapped[str] = mapped_column(String(64), index=True)
    run_id: Mapped[str | None] = mapped_column(String(40), index=True, nullable=True)
    symbol: Mapped[str | None] = mapped_column(String(16), index=True, nullable=True)
    strategy: Mapped[str | None] = mapped_column(String(20), nullable=True)
    strike: Mapped[float | None] = mapped_column(Float, nullable=True)
    expiry: Mapped[date | None] = mapped_column(Date, nullable=True)
    verdict: Mapped[str] = mapped_column(String(10))
    stage: Mapped[str | None] = mapped_column(String(16), index=True, nullable=True)
    reasons: Mapped[dict] = mapped_column(JSON)
    blended_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    premium: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Denormalized ideal zone (analytics/fair_value.py) as it stood at assessment time.
    ideal_lo: Mapped[float | None] = mapped_column(Float, nullable=True)
    ideal_hi: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_credit: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Quote microstructure behind a liquidity verdict (Task 7) — {bid, ask, spread_pct,
    # open_interest, volume} as they stood at assessment time, so a granular reject
    # (illiquid_oi_low, illiquid_spread_wide, ...) stays auditable without re-fetching the
    # chain. None when the candidate carried no quote microstructure (e.g. old rows predating
    # this column, or a candidate built outside the generators).
    liquidity: Mapped[dict | None] = mapped_column(JSON, nullable=True)
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


class PriceHistoryRow(Base):
    """Daily OHLCV bars (one settled session per row) backing the technical indicators
    and HV30. Bootstrapped by scripts/backfill_prices.py and kept fresh by a daily append;
    scans read from here and only fetch the missing tail from yfinance, instead of pulling a
    full 1y/3mo history per symbol every run.
    """

    __tablename__ = "price_history"
    __table_args__ = (UniqueConstraint("symbol", "obs_date", name="uq_price_history_symbol_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    obs_date: Mapped[date] = mapped_column(Date, index=True)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float, default=0.0)
    source: Mapped[str] = mapped_column(String(16), default="yfinance")


class ScanStateRow(Base):
    """Per-symbol intraday-scan materiality state (S1/S10).

    One row per symbol, upserted whenever that symbol's option chain is actually fetched.
    The 15-min intraday loop reads this to decide which symbols need a fresh (expensive)
    chain fetch this cycle and which can be skipped: a held name is always material, a name
    that cleared the score floor last cycle is material, and a ``would_own`` name is material
    only once its live spot has drifted past ``market_data.intraday_rescan_move_pct`` from
    ``last_spot`` (the spot at its *last fetch* — or, for seed-only dip_watch names, the last
    yfinance probe — so slow drift still accumulates to a re-fetch). Manual ``/scan`` and
    the first intraday cycle fetch actively_wheeling ∪ held names and seed every row; they
    never read the gate. Dip_watch names that didn't gap overnight at startup are seed-only
    (``last_spot`` set from a yfinance probe, ``last_scanned_at`` NULL — see
    ``_persist_seed_only_baselines`` in orchestrator/scan.py, 2026-08-28).
    """

    __tablename__ = "scan_state"
    __table_args__ = (UniqueConstraint("symbol", name="uq_scan_state_symbol"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    last_spot: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_scanned_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cleared_floor: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


# ---------------------------------------------------------------------------
# Fundamentals disk cache
# ---------------------------------------------------------------------------


class FundamentalCacheRow(Base):
    """Persisted per-symbol fundamentals cache.

    ``symbol`` is the primary key. ``data_json`` stores the JSON representation of a
    :class:`~src.common.schemas.FundamentalStats` model (produced via ``model_dump_json``).
    ``fetched_at`` records when the row was populated, allowing TTL logic.
    ``next_earnings_date`` mirrors the ``next_earnings`` field of the cached stats so the
    earnings‑aware TTL can be evaluated without loading the JSON payload.
    """

    __tablename__ = "fundamentals_cache"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    data_json: Mapped[str] = mapped_column(Text)  # JSON string of FundamentalStats
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    next_earnings_date: Mapped[date | None] = mapped_column(Date, nullable=True)


# ---------------------------------------------------------------------------
# Sentiment disk cache
# ---------------------------------------------------------------------------


class SentimentCacheRow(Base):
    """Cache for sentiment sub‑sources.

    ``source`` distinguishes the origin (``stocktwits``, ``news``, ``sentiment``).
    ``data_json`` stores a JSON payload specific to that source; ``fetched_at`` enables a 1‑day TTL.
    """

    __tablename__ = "sentiment_cache"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    data_json: Mapped[str] = mapped_column(Text)  # JSON of source‑specific fields
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


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


class PortfolioSnapshotRow(Base):
    """A point-in-time capture of positions and account values, for the web portfolio.

    Deliberately separate from PositionSnapshotRow: that table is one row per ET trading day
    and assignment auto-detection depends on that contract (see src/claude/eval/assignment.py).
    This one is append-only and captured on an intraday cadence. Pruned by retention, not by
    a unique constraint — two rows may share a captured_at (a `refresh` command moments
    after a monitor write), and the newest id wins a tie.
    """

    __tablename__ = "portfolio_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime, index=True, default=_utcnow)
    source: Mapped[str] = mapped_column(String(8))  # "monitor" | "refresh" | "eod"
    account: Mapped[dict] = mapped_column(JSON)  # AccountSnapshot.model_dump(mode="json")
    positions: Mapped[list] = mapped_column(JSON)  # list[PositionSnapshot.model_dump(mode="json")]
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
    # Net option PREMIUM CASHFLOW for the day (credits − debits), not a paired realized P&L —
    # assignment stock-leg P&L is excluded. Column name kept for back-compat; surfaced to the
    # user as "premium cashflow" (N13).
    realized_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    unrealized_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    narrative: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class BuyCandidateRow(Base):
    """One buy-to-own recommendation per scan run, persisted so the web recommendations
    view can render what ``generate_buy_candidates`` produced without recomputing (which
    would mean a full scan per page load).

    Written by the orchestrator at both call sites (full scan and single-ticker
    ``/scan TICKER``). Single-ticker runs use a ``scan-`` prefixed ``run_id`` so
    ``latest_buy_candidates`` can filter them out: a ``/scan NVDA`` must never displace the
    whole recommendations list with one name. Display-only data; nothing reads this back
    into a gate, score, or sizing decision.
    """

    __tablename__ = "buy_candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(40), index=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    sector: Mapped[str | None] = mapped_column(String(64), nullable=True)
    iv_rank: Mapped[float | None] = mapped_column(Float, nullable=True)
    quality_flag: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    technical_regime: Mapped[str | None] = mapped_column(String(32), nullable=True)
    rationale: Mapped[str] = mapped_column(Text, default="")
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_iv: Mapped[float | None] = mapped_column(Float, nullable=True)
    hv_30: Mapped[float | None] = mapped_column(Float, nullable=True)
    vrp: Mapped[float | None] = mapped_column(Float, nullable=True)
    rsi_14: Mapped[float | None] = mapped_column(Float, nullable=True)
    sma_50: Mapped[float | None] = mapped_column(Float, nullable=True)
    sma_200: Mapped[float | None] = mapped_column(Float, nullable=True)
    next_earnings: Mapped[date | None] = mapped_column(Date, nullable=True)
    dividend_yield: Mapped[float | None] = mapped_column(Float, nullable=True)
    est_monthly_cc_yield: Mapped[float | None] = mapped_column(Float, nullable=True)
    iv_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    fundamental_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    technical_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class AppCommandRow(Base):
    """An intent queued by the web layer for the trading process to act on.

    The bridge between a web click and a mutation inside the exec process: the API
    inserts a row here (the only table it may write — see ``src/api/commands.py``),
    and ``approval_service``'s command-drain loop applies it. Applying a command —
    mutating ``ApprovalRow``, inserting ``OrderRow``, and marking this row
    ``applied`` — is one transaction in the exec process (spec §4.2).

    ``dedupe_key`` is ``f"{kind}:{target}"`` for idempotent kinds (approve, reject,
    promote, roll_request) and ``NULL`` for kinds that may repeat harmlessly (halt,
    resume, set_autonomy, refresh, universe_add, universe_remove — the latter two
    joined this group in M7 after a stable key let a later remove dedupe to an
    earlier, already-applied command and silently no-op — and ledger_import,
    ledger_annotate, ledger_ca_reviewed, which joined in Task 8: an import is an
    idempotent upsert and an annotation is last-write-wins, so a dedupe key would only
    ever reject a legitimate second request). A NULL key never collides.

    Uniqueness on ``dedupe_key`` is enforced at the DB level by
    ``uq_app_commands_dedupe_key_pending`` — a partial index (``src/storage/db.py``'s
    ``_PARTIAL_INDEXES``, same shape as ``orders``' ``uq_orders_active_candidate``) scoped to
    ``status = 'pending'``, not a plain column constraint. ``promote``/``roll_request`` key on
    a target (``candidate_id`` / ``position_symbol``) that outlives one approval cycle, so a
    global unique constraint permanently blocked a fresh request once the first had already
    been applied — the exact defect STATUS.md's "Remaining known issues" described. See
    ``storage.app_commands.enqueue_command`` and ``db._ensure_app_commands_pending_only_dedupe``
    (the one-time rebuild that drops the old global constraint from a pre-existing table).
    """

    __tablename__ = "app_commands"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(24), index=True)
    payload: Mapped[dict] = mapped_column(JSON)  # the intent's arguments
    dedupe_key: Mapped[str | None] = mapped_column(String(96), nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="pending", index=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    requested_by: Mapped[str] = mapped_column(String(64))
    confirm_token: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class CampaignRow(Base):
    """One wheel-strategy campaign — links all legs (CSP→assignment→CC→roll→close) under one P&L thread.

    A campaign groups every option position opened on a symbol since the first entry. Each fill
    (SELL = credit entry, BUY = debit close/roll) is aggregated into total_premium_collected,
    total_debit_paid, and net_premium so the operator can see cumulative income per symbol
    across a multi-leg wheel cycle. adjusted_cost_basis tracks stock cost after assignment.

    **`total_premium_collected`, `total_debit_paid`, and `net_premium` are gross of
    commissions.** `_rollup` (`src/storage/campaigns.py`) sums `avg_price * filled_qty * 100`
    per fill and never reads `FillRow.commission` — it is deliberately not subtracted. This is
    pinned by `tests/test_campaign_rollup_semantics.py` so it cannot silently drift; netting
    commissions into these fields would be a deliberate trading-behaviour change, not a bug fix.
    `src/reporting/legs.py` (from M4) reports the same underlying trades net of
    commissions, matching its `classify_outcome`'s `credit - debit -
    commissions` — so a campaign's `net_premium` and the net P&L of its legs differ by exactly
    the commission total; readers comparing the two must account for that gap explicitly.
    """

    __tablename__ = "campaigns"
    __table_args__ = (UniqueConstraint("campaign_id", name="uq_campaigns_campaign_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[str] = mapped_column(String(64), index=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    status: Mapped[str] = mapped_column(String(10), default="open")  # "open" | "closed"
    opened_date: Mapped[date] = mapped_column(Date)
    closed_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # JSON list of candidate_ids in leg order (earliest first).
    leg_candidate_ids: Mapped[list] = mapped_column(JSON, default=list)
    # Rolled-up financials — recomputed from FillRow on every attach (C6).
    total_premium_collected: Mapped[float] = mapped_column(Float, default=0.0)
    total_debit_paid: Mapped[float] = mapped_column(Float, default=0.0)
    net_premium: Mapped[float] = mapped_column(Float, default=0.0)
    # Assignment tracking.
    assigned: Mapped[bool] = mapped_column(Boolean, default=False)
    # Per-share stock cost after assignment: assignment_price − premium_collected/contracts/100.
    adjusted_cost_basis: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Realized P&L on the stock leg when shares are subsequently sold (CC assigned away).
    realized_stock_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class UniverseOverrideRow(Base):
    """An operator's manual add/remove of a symbol in the `would_own`/`watchlist` universe lists.

    Layered on top of `config/universe.yaml` rather than replacing it — the YAML stays the base
    list, this table holds only the deltas an operator has made through the web UI (consumed by
    `src/common/universe.py`, M7 Task 7.2). One row per `(symbol, list_name)`
    (`uq_universe_overrides_symbol_list`): `set_override` upserts, so a later override for the
    same pair replaces the earlier one in place — an add followed by a remove is one row with
    `action="remove"`, never two rows to reconcile at read time. `symbol` is upper-cased at write
    time (`src/storage/universe_overrides.py`) so `nvda` and `NVDA` collide into the same row.
    """

    __tablename__ = "universe_overrides"
    __table_args__ = (
        UniqueConstraint("symbol", "list_name", name="uq_universe_overrides_symbol_list"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    list_name: Mapped[str] = mapped_column(String(16))  # "would_own" | "watchlist" — nothing else
    action: Mapped[str] = mapped_column(String(8))  # "add" | "remove"
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    created_by: Mapped[str] = mapped_column(String(64))  # user id; the audit trail


# --------------------------------------------------------------------------- #
# Trade ledger — whole-account broker truth (docs/superpowers/specs/2026-10-04-trade-ledger-design.md).
# Written only by src/ledger/ingest.py and src/ledger/annotations.py; read by
# src/reporting/trade_ledger.py. Never read by the engine, execution, or strategies.
# --------------------------------------------------------------------------- #
class BrokerExecutionRow(Base):
    """One IBKR execution (``source_kind="exec"``) or one order-level statement row (``"order"``).

    ``superseded_by`` is set on a row whose twin from a higher-priority feed exists (spec R2);
    builders ignore superseded rows. ``trade_time`` is naive UTC; ``trade_date`` is the
    US/Eastern date.
    """

    __tablename__ = "broker_executions"
    __table_args__ = (UniqueConstraint("dedupe_key", name="uq_broker_executions_dedupe_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dedupe_key: Mapped[str] = mapped_column(String(96))
    source_kind: Mapped[str] = mapped_column(String(8))  # "exec" | "order"
    source: Mapped[str] = mapped_column(String(8))  # "csv" | "flex" | "live"
    exec_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    perm_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    ib_order_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    account: Mapped[str | None] = mapped_column(String(32), nullable=True)
    trade_time: Mapped[datetime] = mapped_column(DateTime)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    contract_ident: Mapped[str] = mapped_column(String(80), index=True)
    underlying: Mapped[str] = mapped_column(String(24), index=True)
    sec_type: Mapped[str] = mapped_column(String(4))
    right: Mapped[str | None] = mapped_column(String(1), nullable=True)
    strike: Mapped[float | None] = mapped_column(Float, nullable=True)
    expiry: Mapped[date | None] = mapped_column(Date, nullable=True)
    multiplier: Mapped[float] = mapped_column(Float, default=1.0)
    currency: Mapped[str] = mapped_column(String(3))
    quantity: Mapped[float] = mapped_column(Float)
    price: Mapped[float] = mapped_column(Float)
    proceeds: Mapped[float] = mapped_column(Float)
    commission: Mapped[float] = mapped_column(Float, default=0.0)
    codes: Mapped[str] = mapped_column(String(32), default="")
    ibkr_realized_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    occurrence_idx: Mapped[int] = mapped_column(Integer, default=0)
    superseded_by: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    book: Mapped[str] = mapped_column(String(8), default="manual")  # "system" | "manual"
    import_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class BrokerCashEventRow(Base):
    """Dividend, withholding, deposit/withdrawal, fee or interest cash line."""

    __tablename__ = "broker_cash_events"
    __table_args__ = (UniqueConstraint("dedupe_key", name="uq_broker_cash_events_dedupe_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dedupe_key: Mapped[str] = mapped_column(String(96))
    event_type: Mapped[str] = mapped_column(String(12))
    event_date: Mapped[date] = mapped_column(Date, index=True)
    currency: Mapped[str] = mapped_column(String(3))
    amount: Mapped[float] = mapped_column(Float)
    description: Mapped[str] = mapped_column(Text, default="")
    underlying: Mapped[str | None] = mapped_column(String(24), nullable=True, index=True)
    source: Mapped[str] = mapped_column(String(8))
    import_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class BrokerCorporateActionRow(Base):
    """Stored and flagged for human review — never auto-applied to cost basis (spec §3)."""

    __tablename__ = "broker_corporate_actions"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_broker_corporate_actions_dedupe_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dedupe_key: Mapped[str] = mapped_column(String(96))
    event_date: Mapped[date] = mapped_column(Date)
    underlying: Mapped[str | None] = mapped_column(String(24), nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    quantity: Mapped[float] = mapped_column(Float, default=0.0)
    proceeds: Mapped[float] = mapped_column(Float, default=0.0)
    reviewed: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str] = mapped_column(String(8))
    import_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class FxRateRow(Base):
    """USD per 1 unit of ``currency`` on ``rate_date`` (from Forex trades / Flex ConversionRates)."""

    __tablename__ = "fx_rates"
    __table_args__ = (UniqueConstraint("rate_date", "currency", name="uq_fx_rates_date_currency"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rate_date: Mapped[date] = mapped_column(Date, index=True)
    currency: Mapped[str] = mapped_column(String(3))
    usd_rate: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(8))


class LedgerImportRunRow(Base):
    """One ingest call — its source, outcome, counts and (capped) parse errors."""

    __tablename__ = "ledger_import_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(8))
    filename: Mapped[str | None] = mapped_column(String(200), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(8), default="running")
    reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    counts: Mapped[dict] = mapped_column(JSON, default=dict)
    errors: Mapped[list] = mapped_column(JSON, default=list)
    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[date | None] = mapped_column(Date, nullable=True)


class TradeAnnotationRow(Base):
    """Operator edits, keyed by the opening order's source-independent ``order_key`` (R3)."""

    __tablename__ = "trade_annotations"
    __table_args__ = (UniqueConstraint("order_key", name="uq_trade_annotations_order_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_key: Mapped[str] = mapped_column(String(16))
    notes: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    outcome_override: Mapped[str | None] = mapped_column(String(16), nullable=True)
    exclude_from_stats: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_by: Mapped[str] = mapped_column(String(64), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)
