"""Three rungs, and the bottom one must not look like an empty account.

`read_portfolio` (P3-P4 M1 Task 1.5) resolves the freshest portfolio state available to the
API, which cannot ask IBKR anything:

  1. the newest `portfolio_snapshots` row (source="monitor"/"refresh", as_of = captured_at);
  2. the newest `position_snapshots` row plus the account block out of the newest
     `journal.payload["eod_summary"]["account"]` (source="eod", degraded);
  3. an explicit empty reading (source="none", snapshot=None, degraded) — never a
     zeroed-out PortfolioSnapshot, because a portfolio page rendering zeros is
     indistinguishable from an account that is genuinely empty, and the difference is the
     whole account.

A failure on any rung falls through to the next; `as_of` is the capture time, never request
time.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.common.schemas import AccountSnapshot, PositionSnapshot
from src.storage.models import (
    Base,
    JournalRow,
    PortfolioSnapshotRow,
    PositionSnapshotRow,
)


@pytest.fixture()
def db(tmp_path):
    """An in-memory-isolated trading DB the API layer can read through.

    `read_portfolio(db)` takes the caller's Session (the API passes its read-only
    `trading_session`), so the test wires a plain sessionmaker over a tmp-file SQLite and
    yields a live session.
    """
    db_url = f"sqlite:///{tmp_path / 'portfolio_source.db'}"
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session_ = sessionmaker(bind=engine, expire_on_commit=False)
    s = Session_()
    yield s
    s.close()


def _account(net_liq: float = 100_000.0) -> dict:
    """An AccountSnapshot-shaped dict as stored in the JSON columns / journal payload."""
    return AccountSnapshot(
        account="DU123",
        net_liquidation=net_liq,
        total_cash=50_000.0,
        buying_power=80_000.0,
        maintenance_margin=5_000.0,
        excess_liquidity=75_000.0,
    ).model_dump(mode="json")


# ---------------------------------------------------------------------------
# Seed helpers — one per rung input
# ---------------------------------------------------------------------------


def _seed_portfolio_snapshot(
    db: Session,
    *,
    captured_at: datetime | None = None,
    source: str = "monitor",
    net_liq: float = 100_000.0,
    corrupt: bool = False,
) -> None:
    when = captured_at or datetime.now(UTC)
    db.add(
        PortfolioSnapshotRow(
            captured_at=when,
            source=source,
            account={"this is not": "an AccountSnapshot"},
            positions=[],
        )
        if corrupt
        else PortfolioSnapshotRow(
            captured_at=when,
            source=source,
            account=_account(net_liq),
            positions=[
                PositionSnapshot(
                    symbol="NVDA", sec_type="STK", position=100.0, avg_cost=170.0
                ).model_dump(mode="json")
            ],
        )
    )
    db.commit()


def _seed_position_snapshot(db: Session, *, symbols: list[str]) -> None:
    db.add(
        PositionSnapshotRow(
            snapshot_date=date.today(),
            payload=[
                PositionSnapshot(
                    symbol=sym, sec_type="STK", position=100.0, avg_cost=170.0
                ).model_dump(mode="json")
                for sym in symbols
            ],
        )
    )
    db.commit()


def _seed_journal(db: Session, *, net_liq: float = 456.0, with_account: bool = True) -> None:
    payload: dict = {"fills": []}
    if with_account:
        payload["eod_summary"] = {"account": _account(net_liq)}
    db.add(
        JournalRow(
            entry_date=date.today(),
            realized_pnl=0.0,
            unrealized_pnl=0.0,
            narrative=None,
            payload=payload,
        )
    )
    db.commit()


# ---------------------------------------------------------------------------
# Rung 1 — the newest portfolio_snapshots row
# ---------------------------------------------------------------------------


def test_the_newest_snapshot_wins(db) -> None:
    from src.api.portfolio_source import read_portfolio

    when = datetime.now(UTC) - timedelta(minutes=7)
    _seed_portfolio_snapshot(db, captured_at=when, source="monitor", net_liq=123.0)

    reading = read_portfolio(db)
    assert reading.source == "monitor"
    assert reading.degraded is False
    assert reading.as_of == when
    assert reading.snapshot is not None
    assert reading.snapshot.account.net_liquidation == 123.0


def test_a_newer_refresh_row_beats_an_older_monitor_row(db) -> None:
    from src.api.portfolio_source import read_portfolio

    _seed_portfolio_snapshot(
        db,
        captured_at=datetime.now(UTC) - timedelta(minutes=30),
        source="monitor",
        net_liq=1.0,
    )
    _seed_portfolio_snapshot(
        db,
        captured_at=datetime.now(UTC) - timedelta(minutes=2),
        source="refresh",
        net_liq=2.0,
    )

    reading = read_portfolio(db)
    assert reading.source == "refresh"
    assert reading.snapshot is not None
    assert reading.snapshot.account.net_liquidation == 2.0


# ---------------------------------------------------------------------------
# Rung 2 — position_snapshots + journal payload
# ---------------------------------------------------------------------------


def test_the_eod_rung_is_used_when_no_snapshot_exists(db) -> None:
    from src.api.portfolio_source import read_portfolio

    _seed_position_snapshot(db, symbols=["NVDA"])
    _seed_journal(db, net_liq=456.0)

    reading = read_portfolio(db)
    assert reading.source == "eod"
    assert reading.degraded is True
    assert reading.snapshot is not None
    assert reading.snapshot.account.net_liquidation == 456.0


def test_the_eod_rung_returns_positions_without_a_journal_account(db) -> None:
    """The account is optional on the eod rung: positions still return, account is None."""
    from src.api.portfolio_source import read_portfolio

    _seed_position_snapshot(db, symbols=["NVDA"])
    # A journal row with no eod_summary.account block (or no journal row at all).

    reading = read_portfolio(db)
    assert reading.source == "eod"
    assert reading.snapshot is not None
    assert reading.snapshot.account is None
    assert len(reading.snapshot.positions) == 1


# ---------------------------------------------------------------------------
# Rung 3 — nothing at all
# ---------------------------------------------------------------------------


def test_nothing_at_all_is_reported_as_nothing_not_as_an_empty_account(db) -> None:
    """Zeros here would be a claim about the account. This is the point of the task."""
    from src.api.portfolio_source import read_portfolio

    reading = read_portfolio(db)
    assert reading.source == "none"
    assert reading.snapshot is None
    assert reading.as_of is None
    assert reading.degraded is True


# ---------------------------------------------------------------------------
# Fall-through and as_of discipline
# ---------------------------------------------------------------------------


def test_a_corrupt_newest_row_falls_through(db) -> None:
    """A corrupt payload in the newest row must not take the portfolio down."""
    from src.api.portfolio_source import read_portfolio

    _seed_portfolio_snapshot(db, corrupt=True)
    _seed_position_snapshot(db, symbols=["NVDA"])
    _seed_journal(db, net_liq=456.0)

    reading = read_portfolio(db)
    assert reading.source == "eod"


def test_as_of_is_the_capture_time_not_request_time(db) -> None:
    from src.api.portfolio_source import read_portfolio

    old = datetime.now(UTC) - timedelta(hours=6)
    _seed_portfolio_snapshot(db, captured_at=old)

    reading = read_portfolio(db)
    assert reading.as_of == old
    # never datetime.now() — a 6-hour-old capture must not masquerade as fresh
    assert (
        abs((reading.as_of - datetime.now(UTC)).total_seconds())
        > timedelta(hours=5).total_seconds()
    )
