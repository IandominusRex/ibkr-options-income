"""The portfolio spine's storage. Separate table, append-only, never raises.

`PortfolioSnapshotRow` is deliberately separate from `PositionSnapshotRow` (P3-P4 M1 Task 1.1):
that table is one row per ET trading day and assignment auto-detection diffs its rows
(src/claude/eval/assignment.py); this one is append-only on an intraday cadence for the web
portfolio. No unique constraint — pruned by retention, and two snapshots may share a
timestamp because a `refresh` command moments after a monitor write must not fail.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.common.schemas import AccountSnapshot, PositionSnapshot
from src.storage.models import Base, PositionSnapshotRow
from src.storage.portfolio_snapshots import (
    latest_capture_time,
    load_latest_portfolio_snapshot,
    prune_portfolio_snapshots,
    save_portfolio_snapshot,
)

# ---------------------------------------------------------------------------
# Fixtures — copies of tests/test_eod_idempotency.py's db/session pattern.
# ---------------------------------------------------------------------------


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """Isolated in-process SQLite DB wired into src.storage.db."""
    import src.storage.db as _db_mod

    db_url = f"sqlite:///{tmp_path / 'portfolio_snapshots.db'}"
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(_db_mod, "_engine", engine)
    monkeypatch.setattr(_db_mod, "_SessionLocal", Session)
    return Session


@pytest.fixture()
def session(db):
    """A live session on the isolated `db`, for reading rows back directly in assertions."""
    s = db()
    yield s
    s.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _account(net_liq: float = 100_000.0) -> AccountSnapshot:
    return AccountSnapshot(
        account="DU123",
        net_liquidation=net_liq,
        total_cash=50_000.0,
        buying_power=200_000.0,
        maintenance_margin=10_000.0,
        excess_liquidity=90_000.0,
    )


def _positions() -> list[PositionSnapshot]:
    return [PositionSnapshot(symbol="NVDA", sec_type="STK", position=100.0, avg_cost=170.0)]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_a_snapshot_round_trips(db) -> None:
    save_portfolio_snapshot(account=_account(), positions=_positions(), source="monitor")
    snap = load_latest_portfolio_snapshot()
    assert snap is not None
    assert snap.source == "monitor"
    assert snap.account.net_liquidation == 100_000.0
    assert len(snap.positions) == 1
    assert snap.positions[0].symbol == "NVDA"


def test_captured_at_defaults_to_now_and_is_stored_as_given(db) -> None:
    when = datetime.now(UTC) - timedelta(minutes=5)
    save_portfolio_snapshot(account=_account(), positions=[], source="monitor", captured_at=when)
    snap = load_latest_portfolio_snapshot()
    assert snap is not None
    assert snap.captured_at == when


def test_two_snapshots_may_share_a_timestamp(db) -> None:
    """No unique constraint. A refresh moments after a monitor write must not fail."""
    when = datetime.now(UTC)
    first = save_portfolio_snapshot(
        account=_account(1.0), positions=[], source="monitor", captured_at=when
    )
    second = save_portfolio_snapshot(
        account=_account(2.0), positions=[], source="refresh", captured_at=when
    )
    assert first is not None and second is not None
    snap = load_latest_portfolio_snapshot()
    assert snap is not None and snap.account.net_liquidation == 2.0


def test_an_empty_table_returns_none_not_an_empty_snapshot(db) -> None:
    assert load_latest_portfolio_snapshot() is None
    assert latest_capture_time() is None


def test_a_failing_save_returns_none_and_does_not_raise(db, monkeypatch) -> None:
    """A live event loop calls this. It may never propagate."""

    def boom(*_a, **_k):
        raise RuntimeError("database is locked")

    monkeypatch.setattr("src.storage.portfolio_snapshots.session_scope", boom)
    assert (
        save_portfolio_snapshot(account=_account(), positions=_positions(), source="monitor")
        is None
    )


def test_prune_deletes_only_rows_past_retention(db) -> None:
    now = datetime.now(UTC)
    save_portfolio_snapshot(
        account=_account(),
        positions=[],
        source="monitor",
        captured_at=now - timedelta(days=31),
    )
    save_portfolio_snapshot(
        account=_account(),
        positions=[],
        source="monitor",
        captured_at=now - timedelta(days=29),
    )
    assert prune_portfolio_snapshots(30) == 1
    assert latest_capture_time() is not None


def test_position_snapshots_is_never_touched(db, session) -> None:
    """Assignment auto-detection depends on that table. This milestone does not write it."""
    before = session.query(PositionSnapshotRow).count()
    save_portfolio_snapshot(account=_account(), positions=_positions(), source="monitor")
    assert session.query(PositionSnapshotRow).count() == before
