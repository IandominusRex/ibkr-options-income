"""The account value is USD only: SGD-era net liquidations (before 2026-10-09) are dropped."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from src.reporting import pnl
from src.reporting.account_value import account_value_series, month_start_value
from tests.test_reporting_account_value import _journal, _snap

NOW = datetime(2026, 10, 27, 18, 0, tzinfo=UTC)  # a Tuesday, 14:00 ET


@pytest.fixture(autouse=True)
def _real_cutoff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pnl, "NET_LIQ_USD_FROM", datetime(2026, 10, 9, 17, 0))
    monkeypatch.setattr(pnl, "NET_LIQ_USD_FROM_DAY", date(2026, 10, 9))


def test_the_series_starts_at_the_first_usd_close(db) -> None:
    _journal(db, date(2026, 10, 5), 1_034_824.0)  # SGD
    _journal(db, date(2026, 10, 7), 1_046_465.0)  # SGD
    _journal(db, date(2026, 10, 9), 795_309.0)  # first USD close
    _journal(db, date(2026, 10, 13), 787_130.0)

    series = account_value_series(db, "all", now=NOW)
    assert [p.value for p in series.points] == [795_309.0, 787_130.0]


def test_an_sgd_snapshot_is_never_the_headline(db) -> None:
    _snap(db, datetime(2026, 10, 9, 16, 46), 1_018_420.0)  # the last SGD capture
    series = account_value_series(db, "1m", now=datetime(2026, 10, 9, 17, 30, tzinfo=UTC))
    assert series.latest is None and series.points == []

    _snap(db, datetime(2026, 10, 9, 17, 3), 795_040.0)  # the first USD capture
    series = account_value_series(db, "1d", now=datetime(2026, 10, 9, 17, 30, tzinfo=UTC))
    assert series.latest == 795_040.0
    assert [p.value for p in series.points] == [795_040.0]


def test_the_month_start_never_falls_back_to_an_sgd_close(db) -> None:
    _journal(db, date(2026, 9, 30), 1_024_846.0)  # SGD
    _journal(db, date(2026, 10, 1), 1_023_139.0)  # SGD
    assert month_start_value(db, date(2026, 10, 1)) is None  # no USD close before October
    _journal(db, date(2026, 10, 26), 712_093.0)
    assert month_start_value(db, date(2026, 11, 1)) == 712_093.0


def test_the_equity_curve_leaves_sgd_days_unknown(db) -> None:
    from src.reporting.pnl import equity_curve

    _journal(db, date(2026, 10, 7), 1_046_465.0)
    _journal(db, date(2026, 10, 9), 795_309.0)
    curve = equity_curve(db, [])
    assert [p.net_liquidation for p in curve.points] == [None, 795_309.0]


def test_a_week_of_intraday_snapshots_is_untouched(db) -> None:
    _snap(db, NOW - timedelta(hours=3), 700_000.0)
    _snap(db, NOW - timedelta(minutes=5), 701_000.0)
    series = account_value_series(db, "1w", now=NOW)
    assert [p.value for p in series.points] == [700_000.0, 701_000.0]
