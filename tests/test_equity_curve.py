"""The equity curve: one point per journal row, gaps for missed days, no interpolation."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from src.reporting.pnl import build_legs, equity_curve


def test_a_missed_trading_day_is_a_gap_and_a_weekend_is_not(db, seed_journal_day) -> None:
    """A straight line across a week nobody measured is a fabricated claim."""
    seed_journal_day(date(2026, 9, 1))  # Tuesday
    seed_journal_day(date(2026, 9, 4))  # Friday — Wed and Thu missing
    seed_journal_day(date(2026, 9, 7))  # Monday — the weekend between is not a gap

    curve = equity_curve(db, [])
    assert date(2026, 9, 2) in curve.gaps
    assert date(2026, 9, 3) in curve.gaps
    assert date(2026, 9, 5) not in curve.gaps  # Saturday
    assert date(2026, 9, 6) not in curve.gaps  # Sunday


def test_one_point_per_journal_row_ordered_ascending(db, seed_journal_day) -> None:
    seed_journal_day(date(2026, 9, 4))
    seed_journal_day(date(2026, 9, 1))
    curve = equity_curve(db, [])
    assert [p.entry_date for p in curve.points] == [date(2026, 9, 1), date(2026, 9, 4)]


def test_starts_at_is_the_first_journal_date_and_not_zero_anchored(db, seed_journal_day) -> None:
    seed_journal_day(date(2026, 9, 1))
    seed_journal_day(date(2026, 9, 4))
    curve = equity_curve(db, [])
    assert curve.starts_at == date(2026, 9, 1)
    assert curve.points[0].cumulative_realized == 0.0  # the system's first day: nothing closed yet


def test_premium_cashflow_is_never_called_realised(db, seed_journal_day) -> None:
    """journal.realized_pnl is premium cashflow. The schema field name says so."""
    seed_journal_day(date(2026, 9, 1), realized_pnl=412.0)
    point = equity_curve(db, []).points[0]
    assert point.premium_cashflow == 412.0
    assert not hasattr(point, "realized_pnl")


def test_an_unreadable_account_payload_still_produces_a_point(db, seed_journal_day) -> None:
    seed_journal_day(date(2026, 9, 1), payload={"eod_summary": {"account": "corrupt"}})
    curve = equity_curve(db, [])
    assert len(curve.points) == 1
    assert curve.points[0].net_liquidation is None


def test_a_journal_row_with_no_account_block_still_produces_a_point(db, seed_journal_day) -> None:
    seed_journal_day(date(2026, 9, 1), payload={})
    curve = equity_curve(db, [])
    assert len(curve.points) == 1
    assert curve.points[0].net_liquidation is None


def test_cumulative_realized_includes_every_leg_closed_on_or_before_each_point(
    db,
    seed_journal_day,
    seed_leg,
) -> None:
    """Two legs closing on different dates: each point carries only what had closed."""
    seed_journal_day(date(2026, 9, 1))
    seed_journal_day(date(2026, 9, 8))
    seed_journal_day(date(2026, 9, 15))

    # A leg closed (bought back) on 2026-09-05: contributes from the 9/8 point on.
    five_days = timedelta(days=5)
    opened_09 = datetime(2026, 8, 30)
    with db() as s:
        from src.storage.models import CandidateRow, FillRow

        s.add(
            CandidateRow(
                candidate_id="early",
                run_id="r",
                strategy="cash_secured_put",
                underlying="NVDA",
                right="P",
                strike=170.0,
                expiry=date(2026, 10, 16),
                payload={},
            )
        )
        s.add(
            FillRow(
                order_id=1,
                candidate_id="early",
                action="SELL",
                filled_qty=1,
                avg_price=1.50,
                commission=1.30,
                filled_at=opened_09,
            )
        )
        s.add(
            FillRow(
                order_id=1,
                candidate_id="early",
                action="BUY",
                filled_qty=1,
                avg_price=0.40,
                commission=1.30,
                filled_at=opened_09 + five_days,
            )
        )

    # A leg closed on 2026-09-12: contributes only from the 9/15 point on.
    with db() as s:
        s.add(
            CandidateRow(
                candidate_id="later",
                run_id="r",
                strategy="cash_secured_put",
                underlying="NVDA",
                right="P",
                strike=175.0,
                expiry=date(2026, 10, 16),
                payload={},
            )
        )
        s.add(
            FillRow(
                order_id=1,
                candidate_id="later",
                action="SELL",
                filled_qty=1,
                avg_price=1.00,
                commission=1.30,
                filled_at=opened_09,
            )
        )
        s.add(
            FillRow(
                order_id=1,
                candidate_id="later",
                action="BUY",
                filled_qty=1,
                avg_price=0.20,
                commission=1.30,
                filled_at=datetime(2026, 9, 12),
            )
        )

    legs = build_legs(db)
    curve = equity_curve(db, legs)
    by_date = {p.entry_date: p for p in curve.points}
    early_pnl = 150.0 - 40.0 - 2.60  # closed 9/5 — hand-computed (two commissions)
    later_pnl = 100.0 - 20.0 - 2.60  # closed 9/12 — hand-computed (two commissions)
    assert by_date[date(2026, 9, 1)].cumulative_realized == 0.0
    assert by_date[date(2026, 9, 8)].cumulative_realized == pytest.approx(early_pnl)
    assert by_date[date(2026, 9, 15)].cumulative_realized == pytest.approx(early_pnl + later_pnl)


def test_no_journal_rows_returns_an_empty_curve_not_an_exception(db) -> None:
    curve = equity_curve(db, [])
    assert curve.points == []
    assert curve.starts_at is None
    assert curve.gaps == []


def test_since_trims_leading_points_and_recomputes_starts_at(db, seed_journal_day) -> None:
    seed_journal_day(date(2026, 9, 1))
    seed_journal_day(date(2026, 9, 2))
    seed_journal_day(date(2026, 9, 3))
    curve = equity_curve(db, [], since=date(2026, 9, 2))
    assert curve.starts_at == date(2026, 9, 2)
    assert [p.entry_date for p in curve.points] == [date(2026, 9, 2), date(2026, 9, 3)]


def test_net_liquidation_is_read_through_the_account_schema(db, seed_journal_day) -> None:
    """A schema drift surfaces as a missing value, not a KeyError at render time."""
    seed_journal_day(date(2026, 9, 1), net_liq=150_000.0)
    point = equity_curve(db, []).points[0]
    assert point.net_liquidation == 150_000.0
    assert point.unrealized_pnl == 0.0


def test_a_holiday_between_rows_is_not_a_gap(db, seed_journal_day) -> None:
    """Labor Day 2026 (Mon Sep 7) — a holiday is not a missed measurement."""
    seed_journal_day(date(2026, 9, 4))  # Friday
    seed_journal_day(date(2026, 9, 8))  # Tuesday — Sep 7 is Labor Day
    curve = equity_curve(db, [])
    assert date(2026, 9, 7) not in curve.gaps
    assert date(2026, 9, 8) not in curve.gaps  # first point after the last one is not a gap either
