"""Account value over time: daily from the journal, intraday from portfolio snapshots."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from src.reporting.account_value import account_value_series, month_start_value
from tests.conftest import _account_dict

NOW = datetime(2026, 10, 13, 18, 0, tzinfo=UTC)  # 14:00 ET, a Tuesday


def _journal(db, day: date, net_liq: float) -> None:
    from src.storage.models import JournalRow

    with db() as s:
        s.add(
            JournalRow(
                entry_date=day,
                realized_pnl=0.0,
                unrealized_pnl=0.0,
                payload={"fills": [], "eod_summary": {"account": _account_dict(net_liq, 80_000.0)}},
            )
        )


def _snap(db, at: datetime, net_liq: float) -> None:
    from src.storage.models import PortfolioSnapshotRow

    with db() as s:
        s.add(
            PortfolioSnapshotRow(
                captured_at=at,
                source="monitor",
                account=_account_dict(net_liq, 80_000.0),
                positions=[],
            )
        )


def test_empty_history_is_empty_not_zero(db) -> None:
    series = account_value_series(db, "1m", now=NOW)
    assert series.points == []
    assert series.latest is None
    assert series.change_today is None


def test_daily_ranges_read_the_journal_and_end_at_the_latest_snapshot(db) -> None:
    _journal(db, date(2026, 10, 9), 100_000.0)
    _journal(db, date(2026, 10, 12), 101_000.0)
    _snap(db, NOW - timedelta(minutes=5), 101_500.0)

    series = account_value_series(db, "1m", now=NOW)
    assert [p.value for p in series.points] == [100_000.0, 101_000.0, 101_500.0]
    assert series.latest == 101_500.0
    assert series.previous_close == 101_000.0
    assert series.change_today == 500.0
    assert round(series.change_today_pct or 0, 4) == round(500 / 101_000 * 100, 4)


def test_one_month_drops_older_journal_days(db) -> None:
    _journal(db, date(2026, 8, 1), 90_000.0)
    _journal(db, date(2026, 10, 12), 101_000.0)
    series = account_value_series(db, "1m", now=NOW)
    assert [p.value for p in series.points] == [101_000.0]


def test_intraday_ranges_read_snapshots(db) -> None:
    _snap(db, NOW - timedelta(days=2), 99_000.0)
    _snap(db, NOW - timedelta(hours=3), 100_000.0)
    _snap(db, NOW - timedelta(minutes=5), 100_200.0)
    assert [p.value for p in account_value_series(db, "1d", now=NOW).points] == [
        100_000.0,
        100_200.0,
    ]
    assert len(account_value_series(db, "1w", now=NOW).points) == 3


def test_an_unreadable_payload_is_skipped_not_zeroed(db) -> None:
    from src.storage.models import JournalRow

    with db() as s:
        s.add(
            JournalRow(
                entry_date=date(2026, 10, 12),
                realized_pnl=0.0,
                unrealized_pnl=0.0,
                payload={"x": 1},
            )
        )
    _journal(db, date(2026, 10, 9), 100_000.0)
    series = account_value_series(db, "1m", now=NOW)
    assert [p.value for p in series.points] == [100_000.0]


def test_a_newer_journal_close_beats_a_stale_snapshot(db) -> None:
    """A monitor that stopped days ago must not pose as today's value (or today's change)."""
    _snap(db, NOW - timedelta(days=5), 95_000.0)
    _journal(db, date(2026, 10, 9), 100_000.0)
    _journal(db, date(2026, 10, 12), 101_000.0)
    series = account_value_series(db, "1m", now=NOW)
    assert series.latest == 101_000.0
    assert series.points[-1].value == 101_000.0
    # Monday's close is not today's value: its change is Monday's, so "today" is unknown.
    assert series.previous_close == 100_000.0
    assert series.change_today is None and series.change_today_pct is None


# Instants for the close-versus-snapshot cases (EDT = UTC-4).
FRI_1545_ET = datetime(2026, 10, 9, 19, 45, tzinfo=UTC)
SAT_NOON_ET = datetime(2026, 10, 10, 16, 0, tzinfo=UTC)
TUE_1000_ET = datetime(2026, 10, 13, 14, 0, tzinfo=UTC)
TUE_1555_ET = datetime(2026, 10, 13, 19, 55, tzinfo=UTC)
TUE_1557_ET = datetime(2026, 10, 13, 19, 57, tzinfo=UTC)
TUE_1900_ET = datetime(2026, 10, 13, 23, 0, tzinfo=UTC)


def test_on_a_saturday_there_is_no_change_today(db) -> None:
    """Friday's 15:45 snapshot to Friday's close is not "today": the change is unknown, not +300."""
    _journal(db, date(2026, 10, 8), 100_000.0)
    _journal(db, date(2026, 10, 9), 101_000.0)
    _snap(db, FRI_1545_ET, 101_300.0)
    series = account_value_series(db, "1m", now=SAT_NOON_ET)
    assert series.latest == 101_000.0  # Friday's close, newer than its 15:45 snapshot
    assert series.points[-1].value == 101_000.0
    assert series.previous_close == 100_000.0  # the close before the day `latest` belongs to
    assert series.change_today is None and series.change_today_pct is None


def test_before_the_first_snapshot_of_the_day_there_is_no_change_today(db) -> None:
    """Journal only, viewed Tuesday 10:00 ET: Monday's close is the value, today's change unknown."""
    _journal(db, date(2026, 10, 9), 100_000.0)
    _journal(db, date(2026, 10, 12), 101_000.0)
    series = account_value_series(db, "1m", now=TUE_1000_ET)
    assert series.latest == 101_000.0
    assert series.previous_close == 100_000.0
    assert series.change_today is None and series.change_today_pct is None


def test_after_the_close_the_headline_is_that_days_close(db) -> None:
    """At 19:00 ET the EOD close (16:00) is newer than the 15:55 snapshot: headline = chart end."""
    _journal(db, date(2026, 10, 12), 100_000.0)
    _journal(db, date(2026, 10, 13), 100_900.0)
    _snap(db, TUE_1555_ET, 100_400.0)
    series = account_value_series(db, "1m", now=TUE_1900_ET)
    assert series.latest == 100_900.0
    assert series.points[-1].value == series.latest
    assert series.change_today == 900.0


def test_after_the_close_the_intraday_chart_also_ends_on_the_headline(db) -> None:
    _journal(db, date(2026, 10, 13), 100_900.0)
    _snap(db, TUE_1555_ET, 100_400.0)
    for range_key in ("1d", "1w"):
        series = account_value_series(db, range_key, now=TUE_1900_ET)
        assert [p.value for p in series.points] == [100_400.0, 100_900.0]
        assert series.points[-1].value == series.latest


def test_a_close_still_in_the_future_is_not_yet_a_close(db) -> None:
    """At 15:57 ET a journal row for today (plotted 16:00) is not a close yet: the snapshot leads
    and the chart ends on it (the local-yesterday route-test flake on UTC+8, 00:00-04:00)."""
    _journal(db, date(2026, 10, 12), 100_000.0)
    _journal(db, date(2026, 10, 13), 100_900.0)
    _snap(db, TUE_1555_ET, 100_400.0)
    series = account_value_series(db, "1m", now=TUE_1557_ET)
    assert series.latest == 100_400.0
    assert series.points[-1].value == series.latest
    assert series.change_today == 400.0


def test_a_zero_net_liquidation_snapshot_is_unknown(db) -> None:
    """IBKR's summary can lack NetLiquidation and 0.0 gets stored: never a point or the headline."""
    _journal(db, date(2026, 10, 12), 99_800.0)
    _snap(db, NOW - timedelta(hours=3), 100_000.0)
    _snap(db, NOW - timedelta(hours=2), 0.0)
    _snap(db, NOW - timedelta(hours=1), 100_200.0)
    _snap(db, NOW - timedelta(minutes=5), 0.0)
    day = account_value_series(db, "1d", now=NOW)
    assert [p.value for p in day.points] == [100_000.0, 100_200.0]
    assert day.latest == 100_200.0
    month = account_value_series(db, "1m", now=NOW)
    assert [p.value for p in month.points] == [99_800.0, 100_200.0]
    assert month.change_today == 400.0


def test_a_zero_journal_close_is_unknown(db) -> None:
    _journal(db, date(2026, 10, 9), 100_000.0)
    _journal(db, date(2026, 10, 12), 0.0)
    _snap(db, NOW - timedelta(minutes=5), 100_300.0)
    series = account_value_series(db, "1m", now=NOW)
    assert [p.value for p in series.points] == [100_000.0, 100_300.0]
    assert series.previous_close == 100_000.0
    _journal(db, date(2026, 9, 29), 98_000.0)
    _journal(db, date(2026, 9, 30), 0.0)
    assert month_start_value(db, date(2026, 10, 1)) == 98_000.0


def test_month_start_value_is_the_last_close_before_the_month(db) -> None:
    _journal(db, date(2026, 9, 29), 98_000.0)
    _journal(db, date(2026, 9, 30), 99_000.0)
    _journal(db, date(2026, 10, 1), 99_500.0)
    assert month_start_value(db, date(2026, 10, 1)) == 99_000.0
    assert month_start_value(db, date(2026, 9, 1)) is None


def test_the_change_follows_the_selected_range_and_survives_a_weekend(db) -> None:
    """The Home hero's % was n/a on every weekend and ignored the chip. It now reads the last
    reflected move over the chosen range: 1d is the last session's, longer ranges run from the
    last close before the window, or the window's first point when none predates it."""
    _journal(db, date(2026, 10, 8), 100_000.0)
    _journal(db, date(2026, 10, 9), 101_000.0)
    _journal(db, date(2026, 10, 12), 103_000.0)
    day = account_value_series(db, "1d", now=SAT_NOON_ET)  # Saturday: latest is Friday's close
    assert day.change_today is None
    assert day.change == 1_000.0 and round(day.change_pct or 0, 4) == round(1000 / 100_000 * 100, 4)
    assert day.change_since is not None
    month = account_value_series(db, "1m", now=NOW)
    assert month.change == 3_000.0  # 100k first point (no close predates the window) -> 103k
    assert round(month.change_pct or 0, 4) == 3.0
    assert month.change_since == datetime(2026, 10, 8, 20, 0, tzinfo=UTC)


def test_the_change_is_unknown_not_zero_with_a_single_value(db) -> None:
    _journal(db, date(2026, 10, 12), 103_000.0)
    series = account_value_series(db, "3m", now=NOW)
    assert series.latest == 103_000.0
    assert series.change is None and series.change_pct is None and series.change_since is None
