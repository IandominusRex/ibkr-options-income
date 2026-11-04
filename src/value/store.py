"""The value book's own SQLite database (``data/value.db``), spec §6.9 and §9.7.

A separate engine and DeclarativeBase (the ``src/spreads/store.py`` pattern), so ``create_all``
can never build a value table in another database. ``src/value/`` is its only writer
(tests/test_web_fence.py). Timestamps are naive UTC.

Part 1 tables:
- ``value_ticker_files`` - the latest Part 1 of every name ever scored (one row per symbol);
- ``value_ticker_history`` - append-only: a full row when anything that matters changed, a
  compact row once per session for names in the ranked universe;
- ``value_runs`` - one row per scoring run (the dry run included).

Part 2 tables (the shadow record, spec §6.8, §7, §12):
- ``value_shadow`` - one hypothetical entry per READY signal or control-group name, with its
  fixed-horizon returns against SPY;
- ``value_shadow_legs`` - one row per entry and exit policy (READY entries only), holding the
  exit engine's state;
- ``value_shadow_events`` - every exit event and fill, append-only;
- ``value_ranked`` - the ranked monthly record: top tenth, bottom tenth and the whole universe
  per list, each held to the next formation.

Part 3 (spec §7.1):
- ``value_reevaluations`` - one row per re-evaluation of a shadow entry: the triggers, the
  severity, the plan before and after the session's close;
- ``value_shadow_legs.plan`` / ``value_shadow_events.plan`` - ``main`` (the re-evaluated plan) or
  ``original`` (the twin carried untouched from the first trigger on); added to an existing
  value.db by ``init_value_db``.

Part 4 (spec §8, Claude as the analyst). Claude's half of the ticker file, every table labelled
``source = claude`` in spirit: read only by display code and Claude's prompts, except
``value_claude_verdicts``, the one the gate (Part 5) reads:
- ``value_claude_reads`` - every read: queued, then done / failed / skipped, with the model,
  the backend, the cost, the prompt and the raw reply;
- ``value_claude_verdicts`` - per read and list: Claude's verdict, its drivers after Python
  clamped them, and the fair value Python computed and capped at 1.5x its own;
- ``value_claude_notes`` - profile, why cheap, thesis, bear case, review state;
- ``value_kill_triggers`` - the predicates Claude picked from the menu, and Python's last
  evaluation of each;
- ``value_claude_facts`` - facts Claude proposed from a filing, each with whether
  ``grounding.py`` accepted it;
- ``value_effective`` - the effective verdict per name and list, rewritten every night;
- ``value_claude_state`` - small key/value state (the breaker).

Part 5 (spec §9, revision 4: money in paper, no cash held back):
- ``value_orders`` - every order clientId 31 sends, written **before** ``placeOrder`` with its
  ``orderRef`` (``value:<id>``), then its fills: the value book's share count V;
- ``value_positions`` - one per name and list while held: the live policy's exit plan (a
  ``LegState``), the tranches done;
- ``value_proposals`` - every buy and sell the book proposes, with who caused it, whether it
  waits for a tap, and what the gate said;
- ``value_funding_requests`` - capital the wheel is asked to release for an approved buy;
- ``value_attribution`` - each shared name's reconcile (broker = wheel + value), and its freeze;
- ``value_book_state`` - small key/value state (the book's high-water mark);
- ``value_reevaluations.position_id`` - a held position's re-evaluation (``shadow_id`` 0).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    create_engine,
    event,
    inspect,
    text,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from src.common.config import get_config


class ValueBase(DeclarativeBase):
    pass


class ValueTickerFileRow(ValueBase):
    __tablename__ = "value_ticker_files"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime)
    as_of: Mapped[date] = mapped_column(Date)
    universe: Mapped[str] = mapped_column(String(16))  # trading|evidence|lookup|held:*
    fingerprint_key: Mapped[str] = mapped_column(String(16))
    fingerprint_json: Mapped[str] = mapped_column(Text)
    ruleset_version: Mapped[str] = mapped_column(String(32))
    ruleset_hash: Mapped[str] = mapped_column(String(12))
    company_class: Mapped[str] = mapped_column(String(16))
    data_quality: Mapped[str] = mapped_column(String(16))
    health: Mapped[str] = mapped_column(String(16))
    verdict_deep: Mapped[str] = mapped_column(String(16))
    verdict_growth: Mapped[str] = mapped_column(String(16))
    filed_list: Mapped[str | None] = mapped_column(String(16), nullable=True)
    fair_value_deep: Mapped[float | None] = mapped_column(Float, nullable=True)
    fair_value_growth: Mapped[float | None] = mapped_column(Float, nullable=True)
    mos_deep: Mapped[float | None] = mapped_column(Float, nullable=True)
    mos_growth: Mapped[float | None] = mapped_column(Float, nullable=True)
    rank_deep: Mapped[float | None] = mapped_column(Float, nullable=True)
    rank_growth: Mapped[float | None] = mapped_column(Float, nullable=True)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    summary_json: Mapped[str] = mapped_column(Text)
    scorecard_json: Mapped[str] = mapped_column(Text)
    last_viewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ValueTickerHistoryRow(ValueBase):
    __tablename__ = "value_ticker_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(16))
    recorded_at: Mapped[datetime] = mapped_column(DateTime)
    as_of: Mapped[date] = mapped_column(Date)
    reason: Mapped[str] = mapped_column(String(16))  # changed | session
    changed: Mapped[str] = mapped_column(Text, default="[]")  # JSON list of what changed
    fingerprint_key: Mapped[str] = mapped_column(String(16))
    ruleset_version: Mapped[str] = mapped_column(String(32))
    summary_json: Mapped[str] = mapped_column(Text)
    scorecard_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # full on "changed"

    __table_args__ = (Index("ix_value_history_symbol_asof", "symbol", "as_of"),)


class ValueRunRow(ValueBase):
    __tablename__ = "value_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(16))  # dry_run | nightly | lookup
    started_at: Mapped[datetime] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    as_of: Mapped[date] = mapped_column(Date)
    ruleset_version: Mapped[str] = mapped_column(String(32))
    ruleset_hash: Mapped[str] = mapped_column(String(12))
    names: Mapped[int] = mapped_column(Integer, default=0)
    rs_cutoff_6m: Mapped[float | None] = mapped_column(Float, nullable=True)
    summary_json: Mapped[str] = mapped_column(Text, default="{}")


class ValueShadowRow(ValueBase):
    """One hypothetical entry (spec §6.8). ``kind``: ``ready`` (a READY signal) or a control
    group, ``control_valuation`` (healthy, too dear: WAIT) or ``control_health`` (cheap enough,
    health failed). ``status``: pending (waiting for the next session's open), open, closed,
    void (no bar ever came) or rebase_needed (the entry bar moved: a split, Part 3 rebases)."""

    __tablename__ = "value_shadow"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    track: Mapped[str] = mapped_column(String(16))  # baseline (Claude's track is Part 4)
    kind: Mapped[str] = mapped_column(String(24))
    list_name: Mapped[str] = mapped_column(String(16))
    symbol: Mapped[str] = mapped_column(String(16))
    universe: Mapped[str] = mapped_column(String(16))  # trading | evidence
    signal_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    status_detail: Mapped[str] = mapped_column(Text, default="")
    verdict: Mapped[str] = mapped_column(String(16))  # Python's baseline verdict at the signal
    signal_close: Mapped[float | None] = mapped_column(Float, nullable=True)
    atr14: Mapped[float | None] = mapped_column(Float, nullable=True)
    fair_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    effective_fair_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    margin_of_safety: Mapped[float | None] = mapped_column(Float, nullable=True)  # a fraction
    required_mos_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    fv_accn: Mapped[str | None] = mapped_column(String(32), nullable=True)
    fingerprint_key: Mapped[str] = mapped_column(String(16))
    ruleset_version: Mapped[str] = mapped_column(String(32))
    ruleset_hash: Mapped[str] = mapped_column(String(12))
    scorecard_json: Mapped[str] = mapped_column(Text)
    entry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    entry_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    spy_entry_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    ret_21: Mapped[float | None] = mapped_column(Float, nullable=True)
    spy_21: Mapped[float | None] = mapped_column(Float, nullable=True)
    ret_63: Mapped[float | None] = mapped_column(Float, nullable=True)
    spy_63: Mapped[float | None] = mapped_column(Float, nullable=True)
    ret_126: Mapped[float | None] = mapped_column(Float, nullable=True)
    spy_126: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    closed_on: Mapped[date | None] = mapped_column(Date, nullable=True)

    __table_args__ = (
        Index("ix_value_shadow_key", "track", "kind", "list_name", "symbol"),
        Index("ix_value_shadow_status", "status"),
    )


class ValueShadowLegRow(ValueBase):
    """One exit policy's simulated holding of one READY entry (spec §7)."""

    __tablename__ = "value_shadow_legs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    shadow_id: Mapped[int] = mapped_column(Integer, index=True)
    policy: Mapped[str] = mapped_column(String(8))  # full | value | hold12
    plan: Mapped[str] = mapped_column(String(8), default="main")  # main | original (Part 3)
    state_json: Mapped[str] = mapped_column(Text)  # src.value.exits.LegState
    last_step: Mapped[date | None] = mapped_column(Date, nullable=True)
    closed: Mapped[bool] = mapped_column(Boolean, default=False)
    exit_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    ret_exit: Mapped[float | None] = mapped_column(Float, nullable=True)
    spy_ret_exit: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_drawdown: Mapped[float | None] = mapped_column(Float, nullable=True)
    sessions: Mapped[int] = mapped_column(Integer, default=0)
    sells: Mapped[int] = mapped_column(Integer, default=0)


class ValueShadowEventRow(ValueBase):
    """Append-only: every exit event and fill of every leg."""

    __tablename__ = "value_shadow_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    shadow_id: Mapped[int] = mapped_column(Integer, index=True)
    policy: Mapped[str] = mapped_column(String(8))  # full | value | hold12 | all (a rebase)
    plan: Mapped[str] = mapped_column(String(8), default="main")  # main | original (Part 3)
    day: Mapped[date] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(String(16))
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    fraction: Mapped[float] = mapped_column(Float, default=0.0)
    detail: Mapped[str] = mapped_column(Text, default="")


class ValueRankedRow(ValueBase):
    """One hypothetical equal-weight portfolio of the ranked record (spec §6.8): a list's top
    tenth, bottom tenth or whole scored universe, formed on the first session of a month and
    held to the next formation."""

    __tablename__ = "value_ranked"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    formed_on: Mapped[date] = mapped_column(Date, index=True)
    list_name: Mapped[str] = mapped_column(String(16))
    bucket: Mapped[str] = mapped_column(String(8))  # top | bottom | all
    members_json: Mapped[str] = mapped_column(Text)  # JSON list of symbols
    n: Mapped[int] = mapped_column(Integer)
    ruleset_version: Mapped[str] = mapped_column(String(32))
    ruleset_hash: Mapped[str] = mapped_column(String(12))
    closed_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    ret: Mapped[float | None] = mapped_column(Float, nullable=True)
    spy_ret: Mapped[float | None] = mapped_column(Float, nullable=True)
    missing: Mapped[int] = mapped_column(Integer, default=0)  # members without a bar at an end


class ValueReevaluationRow(ValueBase):
    """One re-evaluation (spec §7.1) of a shadow entry. A trigger within ``debounce_sessions``
    that is not more severe joins the open row (``last_session``, ``triggers_json``) instead of
    opening a new one. ``review_state`` is Claude's, for held names, from Part 4 on."""

    __tablename__ = "value_reevaluations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    shadow_id: Mapped[int] = mapped_column(Integer, index=True)
    symbol: Mapped[str] = mapped_column(String(16))
    list_name: Mapped[str] = mapped_column(String(16))
    session: Mapped[date] = mapped_column(Date)  # the session it opened on
    last_session: Mapped[date] = mapped_column(Date)  # the newest session a trigger joined
    severity: Mapped[str] = mapped_column(String(8))  # minor | major
    triggers_json: Mapped[str] = mapped_column(Text)  # [{day, kind, severity, ...}]
    plan_before_json: Mapped[str] = mapped_column(Text)  # {policy: {stop, armed, ...}}
    plan_after_json: Mapped[str] = mapped_column(Text)
    verdict_at_entry: Mapped[str] = mapped_column(String(16))
    verdict_now: Mapped[str | None] = mapped_column(String(16), nullable=True)
    review_state: Mapped[str | None] = mapped_column(String(16), nullable=True)
    ruleset_version: Mapped[str] = mapped_column(String(32))
    ruleset_hash: Mapped[str] = mapped_column(String(12))
    created_at: Mapped[datetime] = mapped_column(DateTime)
    position_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # held (Part 5)


class ValueClaudeReadRow(ValueBase):
    """One Claude read of one name (spec §8.3, §8.5). ``kind``: standard | filing | review;
    ``reason``: request | review | filing | top | stale; ``status``: queued | done | failed |
    skipped. ``backend`` ``ollama`` is stored labelled and never decides anything."""

    __tablename__ = "value_claude_reads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(String(16))
    priority: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="queued")
    detail: Mapped[str] = mapped_column(Text, default="")
    requested_at: Mapped[datetime] = mapped_column(DateTime)
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    fingerprint_key: Mapped[str | None] = mapped_column(String(16), nullable=True)
    accn: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reevaluation_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    model: Mapped[str] = mapped_column(String(64), default="")
    backend: Mapped[str] = mapped_column(String(8), default="cli")
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    error: Mapped[str | None] = mapped_column(String(32), nullable=True)
    prompt_version: Mapped[str] = mapped_column(String(32), default="")
    prompt: Mapped[str] = mapped_column(Text, default="")
    raw: Mapped[str] = mapped_column(Text, default="")

    __table_args__ = (Index("ix_value_claude_reads_status", "status", "priority"),)


class ValueClaudeVerdictRow(ValueBase):
    """Claude's validated verdict on one list (spec §8.2, §8.3): a verdict from a fixed set,
    the drivers after Python clamped them, and the fair value Python computed and capped. The
    one Claude table the gate reads (spec §9.4, §16)."""

    __tablename__ = "value_claude_verdicts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    read_id: Mapped[int] = mapped_column(Integer, index=True)
    symbol: Mapped[str] = mapped_column(String(16))
    list_name: Mapped[str] = mapped_column(String(16))
    verdict: Mapped[str] = mapped_column(String(8))
    why: Mapped[str] = mapped_column(Text, default="")
    drivers_json: Mapped[str] = mapped_column(Text)
    clamps_json: Mapped[str] = mapped_column(Text, default="[]")
    fair_value: Mapped[float | None] = mapped_column(Float, nullable=True)  # capped: the one used
    uncapped: Mapped[float | None] = mapped_column(Float, nullable=True)
    python_fair_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    clamp_bound: Mapped[bool] = mapped_column(Boolean, default=False)
    unreliable: Mapped[str | None] = mapped_column(Text, nullable=True)
    accn: Mapped[str | None] = mapped_column(String(32), nullable=True)
    fingerprint_key: Mapped[str] = mapped_column(String(16))
    backend: Mapped[str] = mapped_column(String(8))
    created_at: Mapped[datetime] = mapped_column(DateTime)
    superseded: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (Index("ix_value_claude_verdicts_key", "symbol", "list_name", "superseded"),)


class ValueClaudeNoteRow(ValueBase):
    """Claude's prose for one read (spec §8.1): display and Claude's own prompts only."""

    __tablename__ = "value_claude_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    read_id: Mapped[int] = mapped_column(Integer, index=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    profile: Mapped[str] = mapped_column(Text, default="")
    why_cheap: Mapped[str] = mapped_column(Text, default="")
    thesis: Mapped[str] = mapped_column(Text, default="")
    bear_case: Mapped[str] = mapped_column(Text, default="")
    review_state: Mapped[str | None] = mapped_column(String(16), nullable=True)
    review_why: Mapped[str] = mapped_column(Text, default="")
    backend: Mapped[str] = mapped_column(String(8))
    created_at: Mapped[datetime] = mapped_column(DateTime)


class ValueKillTriggerRow(ValueBase):
    """A predicate Claude picked from the menu (spec §8.4); Python bounds its threshold and
    evaluates it every night (``last_state``: fired | near | far | unknown)."""

    __tablename__ = "value_kill_triggers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    read_id: Mapped[int] = mapped_column(Integer, index=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    chosen_at: Mapped[datetime] = mapped_column(DateTime)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_state: Mapped[str | None] = mapped_column(String(8), nullable=True)
    last_actual: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_checked: Mapped[date | None] = mapped_column(Date, nullable=True)
    fired_on: Mapped[date | None] = mapped_column(Date, nullable=True)


class ValueClaudeFactRow(ValueBase):
    """A fact Claude proposed from a filing (spec §8.2 "Grounded facts") and whether
    ``src/value/grounding.py`` accepted it. Only a grounded fact is ever read again."""

    __tablename__ = "value_claude_facts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    read_id: Mapped[int] = mapped_column(Integer, index=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    accn: Mapped[str] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(32))
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str] = mapped_column(String(16), default="")
    quote: Mapped[str] = mapped_column(Text)
    item: Mapped[str | None] = mapped_column(String(48), nullable=True)
    grounded: Mapped[bool] = mapped_column(Boolean)
    why: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime)


class ValueEffectiveRow(ValueBase):
    """The effective verdict per name and list (spec §6.7), rewritten every night: what the
    strip shows and Stage 3 acts on. ``decided_by`` is ``claude`` or ``python``."""

    __tablename__ = "value_effective"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    list_name: Mapped[str] = mapped_column(String(16), primary_key=True)
    as_of: Mapped[date] = mapped_column(Date)
    verdict: Mapped[str] = mapped_column(String(16))
    decided_by: Mapped[str] = mapped_column(String(8))
    python_verdict: Mapped[str] = mapped_column(String(16))
    claude_verdict: Mapped[str | None] = mapped_column(String(8), nullable=True)
    verdict_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fair_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    entry_ceiling: Mapped[float | None] = mapped_column(Float, nullable=True)
    margin_of_safety: Mapped[float | None] = mapped_column(Float, nullable=True)
    mos_review: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class ValueClaudeStateRow(ValueBase):
    """Small key/value state of Claude's side: the breaker (spec §8.2)."""

    __tablename__ = "value_claude_state"

    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class ValueOrderRow(ValueBase):
    """One order of the value book (spec §9.2, §9.7). Written before ``placeOrder`` so a fill
    can never arrive for an order value.db does not know; ``order_ref`` is ``value:<id>``.
    ``status``: pending (written, not sent) | submitted | partial | filled | cancelled |
    rejected | error."""

    __tablename__ = "value_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    list_name: Mapped[str] = mapped_column(String(16))
    side: Mapped[str] = mapped_column(String(4))  # buy | sell
    tranche: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason: Mapped[str] = mapped_column(String(32), default="")
    proposal_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shares: Mapped[float] = mapped_column(Float)
    filled: Mapped[float] = mapped_column(Float, default=0.0)
    limit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(12), default="pending")
    order_ref: Mapped[str] = mapped_column(String(32), default="")
    ib_order_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    perm_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    done_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    detail: Mapped[str] = mapped_column(Text, default="")


class ValuePositionRow(ValueBase):
    """One held name on one list (spec §11): its exit plan under the live policy and its
    tranches. ``status``: open | closed."""

    __tablename__ = "value_positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    list_name: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(8), default="open")
    opened_on: Mapped[date] = mapped_column(Date)
    closed_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    tranches_done: Mapped[int] = mapped_column(Integer, default=0)
    last_tranche_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    low_since_tranche: Mapped[float | None] = mapped_column(Float, nullable=True)
    plan_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # exits.LegState
    plan_step: Mapped[date | None] = mapped_column(Date, nullable=True)
    decided_by: Mapped[str] = mapped_column(String(8), default="python")


class ValueProposalRow(ValueBase):
    """A buy or a sell the book proposes (spec §9.5, §7). ``cause``: python | claude (a sale
    only Claude's number would make always waits for a tap). ``status``: pending (waits for a
    tap) | approved | funding (approved, waiting for released capital) | sent | done |
    rejected | refused (the gate said no at send time) | expired."""

    __tablename__ = "value_proposals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(4))  # buy | sell
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    list_name: Mapped[str] = mapped_column(String(16))
    shares: Mapped[float] = mapped_column(Float)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)  # the close it was sized at
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)  # earmarked while approved
    tranche: Mapped[int | None] = mapped_column(Integer, nullable=True)
    position_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason: Mapped[str] = mapped_column(String(48))
    cause: Mapped[str] = mapped_column(String(8), default="python")
    needs_tap: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(12), default="pending", index=True)
    gate_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(12), nullable=True)
    order_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    detail: Mapped[str] = mapped_column(Text, default="")


class ValueFundingRow(ValueBase):
    """Capital the wheel is asked to release for an approved buy (revision 4). The trading
    process reads open rows through ``src/common/value_view.py`` and closes eligible CSPs through
    the Rules Engine; the value process marks the row funded when its own fresh account shows the
    cash, or lapsed. ``status``: open | funded | lapsed."""

    __tablename__ = "value_funding_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    proposal_id: Mapped[int] = mapped_column(Integer, index=True)
    symbol: Mapped[str] = mapped_column(String(16))
    needed_usd: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(8), default="open", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    detail: Mapped[str] = mapped_column(Text, default="")


class ValueAttributionRow(ValueBase):
    """One name's share reconcile (spec §9.2): broker = wheel (W) + value (V filled). ``state``:
    ok | pending (unexplained, inside the grace) | frozen (both books stop opening on the name
    until a human clears it)."""

    __tablename__ = "value_attribution"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    broker: Mapped[float] = mapped_column(Float)
    wheel: Mapped[float] = mapped_column(Float)
    value_filled: Mapped[float] = mapped_column(Float)
    value_pending: Mapped[float] = mapped_column(Float, default=0.0)
    mark: Mapped[float | None] = mapped_column(Float, nullable=True)  # the last price seen
    state: Mapped[str] = mapped_column(String(8), default="ok")
    since: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime)
    cleared_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    detail: Mapped[str] = mapped_column(Text, default="")


class ValueBookStateRow(ValueBase):
    """Small key/value state of the book (its high-water mark)."""

    __tablename__ = "value_book_state"

    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None

# Columns added after a table's first release: create_all never ALTERs an existing table
# (the src/spreads/store.py pattern).
_ADDED_COLUMNS: dict[str, tuple[tuple[str, str], ...]] = {
    "value_shadow_legs": (("plan", "VARCHAR(8) NOT NULL DEFAULT 'main'"),),
    "value_shadow_events": (("plan", "VARCHAR(8) NOT NULL DEFAULT 'main'"),),
    "value_reevaluations": (("position_id", "INTEGER"),),
}


def _resolve_url() -> str:
    """Absolute sqlite URL for the value database. Patched in tests."""
    return get_config().value_db_url_abs()


def get_value_engine() -> Engine:
    global _engine, _SessionLocal
    if _engine is None:
        url = _resolve_url()
        if url.startswith("sqlite:///"):
            Path(url[len("sqlite:///") :]).parent.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(url, future=True)

        @event.listens_for(_engine, "connect")
        def _set_pragmas(dbapi_conn, _record):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

        _SessionLocal = sessionmaker(bind=_engine, future=True, expire_on_commit=False)
    return _engine


def reset_engine() -> None:
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine, _SessionLocal = None, None


def _add_missing_columns(engine: Engine) -> None:
    insp = inspect(engine)
    for table, cols in _ADDED_COLUMNS.items():
        if not insp.has_table(table):
            continue
        have = {c["name"] for c in insp.get_columns(table)}
        for name, ddl in cols:
            if name not in have:
                with engine.begin() as conn:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


def init_value_db() -> None:
    engine = get_value_engine()
    ValueBase.metadata.create_all(engine)
    _add_missing_columns(engine)


@contextmanager
def value_session() -> Iterator[Session]:
    get_value_engine()
    assert _SessionLocal is not None
    s = _SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def record_run(
    session: Session,
    *,
    kind: str,
    started_at: datetime,
    finished_at: datetime | None,
    as_of: date,
    ruleset_version: str,
    ruleset_hash: str,
    names: int,
    rs_cutoff_6m: float | None,
    summary_json: str,
) -> ValueRunRow:
    """Add one ``value_runs`` row. The only way a caller outside this package records a run,
    so ``src/value/`` stays the sole constructor of value.db rows."""
    row = ValueRunRow(
        kind=kind,
        started_at=started_at,
        finished_at=finished_at,
        as_of=as_of,
        ruleset_version=ruleset_version,
        ruleset_hash=ruleset_hash,
        names=names,
        rs_cutoff_6m=rs_cutoff_6m,
        summary_json=summary_json,
    )
    session.add(row)
    return row
