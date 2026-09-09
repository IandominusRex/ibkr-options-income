"""A repeated EOD run must not silently skip reconciliation and tomorrow's baseline.

`_write_journal` used to do a bare `session.add(JournalRow(...))`. `JournalRow` carries
`UniqueConstraint("entry_date")`, and `session_scope` rolls back and re-raises — so a second
EOD run on the same ET day raised `IntegrityError` at step 6, and the reconciler, assignment
auto-detection, and `save_position_snapshot` (step 6b) never ran. These tests pin the fix:
the journal write upserts, and a repeated `run()` still reaches step 6b.

Fixtures mirror tests/test_eod.py's `isolated_db` (in-process SQLite wired into
`src.storage.db`) rather than building a second harness from scratch.
"""

from __future__ import annotations

import asyncio
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.common.schemas import AccountSnapshot, EODSummary
from src.storage.models import JournalRow

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_account(nlv: float = 100_000.0) -> AccountSnapshot:
    return AccountSnapshot(
        account="DU123456",
        net_liquidation=nlv,
        total_cash=50_000.0,
        buying_power=80_000.0,
        maintenance_margin=5_000.0,
        excess_liquidity=75_000.0,
    )


def await_eod_run(eod_env) -> None:
    """Run the real EOD orchestrator synchronously, for tests that aren't themselves async.

    `eod_env` is the (patched) `src.orchestrator.eod_report` module — see the fixture below.
    """
    asyncio.run(eod_env.run())


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """Isolated in-process SQLite DB wired into src.storage.db.

    Mirrors tests/test_eod.py's `isolated_db` fixture — kept as a local copy rather than
    imported, since this file also builds a `session` and an `eod_env` on top of it.
    """
    import src.storage.db as _db_mod
    from src.storage.models import Base

    db_url = f"sqlite:///{tmp_path / 'eod_idempotency.db'}"
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


@pytest.fixture()
def an_eod_summary():
    """Factory for a valid EODSummary, overriding only what a given test cares about."""

    def _make(*, entry_date: date, **overrides: object) -> EODSummary:
        defaults: dict = dict(
            date=entry_date,
            realized_pnl=142.50,
            unrealized_pnl=-320.0,
            unrealized_pnl_delta=-85.0,
            fills_today=2,
            open_positions=3,
            net_delta_exposure=-0.28,
            account=_make_account(),
            top_movers=["AAPL", "SPY"],
            tomorrow_watchlist=["AAPL", "SPY", "NVDA"],
        )
        defaults.update(overrides)
        return EODSummary(**defaults)  # type: ignore[arg-type]

    return _make


@pytest.fixture()
def eod_env(db, monkeypatch):
    """Patch every IBKR/network/Claude/Telegram touchpoint in `eod_report.run()` so the real
    orchestrator can be driven end-to-end against the isolated `db`, twice in a row, without
    touching IBKR, yfinance, the Claude CLI, Telegram, or the on-disk production DB backup.

    Deliberately leaves `reconcile` and `save_position_snapshot` unpatched — the test that
    needs them patches those two itself, to assert they are reached on the second run.
    """
    from src.orchestrator import eod_report

    class _FakeConnection:
        """Stands in for IBKRConnection's async-context-manager protocol."""

        def __init__(self, role: str) -> None:
            self.role = role

        async def __aenter__(self):
            return MagicMock(name="ib")

        async def __aexit__(self, *exc_info: object) -> bool:
            return False

    monkeypatch.setattr(eod_report, "IBKRConnection", _FakeConnection)
    monkeypatch.setattr(eod_report, "get_positions", lambda ib: [])
    monkeypatch.setattr(
        eod_report, "get_account_snapshot_async", AsyncMock(return_value=_make_account())
    )
    monkeypatch.setattr(
        eod_report, "enrich_positions_with_greeks_async", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(eod_report, "_append_daily_iv", AsyncMock(return_value=None))
    monkeypatch.setattr(eod_report, "_append_daily_prices", AsyncMock(return_value=None))
    monkeypatch.setattr(eod_report, "write_journal_narrative", lambda summary: "narrative")
    monkeypatch.setattr(eod_report, "_send_eod_telegram", AsyncMock(return_value=None))
    # backup_database resolves its own DB path from get_config() rather than the patched
    # engine above — left unpatched it would back up the real on-disk system of record.
    monkeypatch.setattr("src.storage.maintenance.backup_database", lambda *a, **k: None)
    return eod_report


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_a_repeated_journal_write_upserts_rather_than_raising(db, session, an_eod_summary) -> None:
    from src.orchestrator.eod_report import _write_journal

    summary = an_eod_summary(entry_date=date(2026, 9, 9), unrealized_pnl=100.0)
    _write_journal(summary, "first narrative", [1])

    summary_again = an_eod_summary(entry_date=date(2026, 9, 9), unrealized_pnl=250.0)
    _write_journal(summary_again, "second narrative", [1, 2])  # must not raise

    rows = session.query(JournalRow).filter_by(entry_date=date(2026, 9, 9)).all()
    assert len(rows) == 1
    assert rows[0].unrealized_pnl == 250.0
    assert rows[0].narrative == "second narrative"
    assert rows[0].payload["fills"] == [1, 2]


def test_a_repeated_eod_run_still_reconciles_and_snapshots(db, eod_env) -> None:
    """The real defect: step 6 raised, so steps 6b never ran, so the day was never reconciled."""
    with (
        patch("src.orchestrator.eod_report.reconcile") as reconcile,
        patch("src.orchestrator.eod_report.save_position_snapshot") as snapshot,
    ):
        await_eod_run(eod_env)  # first run
        await_eod_run(eod_env)  # second run, same ET day

    assert reconcile.call_count == 2
    assert snapshot.call_count == 2


def test_created_at_survives_an_upsert(db, session, an_eod_summary) -> None:
    from src.orchestrator.eod_report import _write_journal

    _write_journal(an_eod_summary(entry_date=date(2026, 9, 9)), "first", [])
    original = session.query(JournalRow).filter_by(entry_date=date(2026, 9, 9)).one().created_at

    _write_journal(an_eod_summary(entry_date=date(2026, 9, 9)), "second", [])
    assert (
        session.query(JournalRow).filter_by(entry_date=date(2026, 9, 9)).one().created_at
        == original
    )


def test_a_different_date_creates_a_second_row(db, session, an_eod_summary) -> None:
    from src.orchestrator.eod_report import _write_journal

    _write_journal(an_eod_summary(entry_date=date(2026, 9, 9)), "a", [])
    _write_journal(an_eod_summary(entry_date=date(2026, 9, 10)), "b", [])
    assert session.query(JournalRow).count() == 2
