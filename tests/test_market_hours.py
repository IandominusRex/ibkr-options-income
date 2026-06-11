"""Tests for the self-contained US market calendar + RTH gate."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from src.common.market_hours import (
    is_early_close,
    is_market_holiday,
    is_rth,
    session_close,
)

_ET = ZoneInfo("America/New_York")


class TestHolidays:
    def test_fixed_and_floating_holidays_2026(self):
        # Spot-check the 2026 NYSE calendar.
        assert is_market_holiday(date(2026, 1, 1))    # New Year's Day (Thursday)
        assert is_market_holiday(date(2026, 1, 19))   # MLK (3rd Mon Jan)
        assert is_market_holiday(date(2026, 2, 16))   # Presidents' (3rd Mon Feb)
        assert is_market_holiday(date(2026, 4, 3))    # Good Friday 2026
        assert is_market_holiday(date(2026, 5, 25))   # Memorial (last Mon May)
        assert is_market_holiday(date(2026, 6, 19))   # Juneteenth
        assert is_market_holiday(date(2026, 7, 3))    # Independence Day observed (Jul 4 = Sat)
        assert is_market_holiday(date(2026, 9, 7))    # Labor Day
        assert is_market_holiday(date(2026, 11, 26))  # Thanksgiving (4th Thu)
        assert is_market_holiday(date(2026, 12, 25))  # Christmas

    def test_regular_weekday_is_not_holiday(self):
        assert not is_market_holiday(date(2026, 6, 11))  # a plain Thursday

    def test_juneteenth_not_observed_before_2022(self):
        assert not is_market_holiday(date(2021, 6, 18))


class TestEarlyClose:
    def test_day_after_thanksgiving_is_early_close(self):
        assert is_early_close(date(2026, 11, 27))  # Friday after Thanksgiving
        assert session_close(date(2026, 11, 27)) is not None

    def test_christmas_eve_weekday_early_close(self):
        assert is_early_close(date(2026, 12, 24))  # Thursday


class TestSessionClose:
    def test_weekend_returns_none(self):
        assert session_close(date(2026, 6, 13)) is None  # Saturday
        assert session_close(date(2026, 6, 14)) is None  # Sunday

    def test_holiday_returns_none(self):
        assert session_close(date(2026, 12, 25)) is None

    def test_regular_day_closes_at_1600(self):
        close = session_close(date(2026, 6, 11))
        assert close is not None and close.hour == 16 and close.minute == 0

    def test_early_close_day_closes_at_1300(self):
        close = session_close(date(2026, 11, 27))
        assert close is not None and close.hour == 13


class TestIsRth:
    def test_midday_regular_weekday_is_rth(self):
        assert is_rth(datetime(2026, 6, 11, 12, 0, tzinfo=_ET))

    def test_before_open_is_not_rth(self):
        assert not is_rth(datetime(2026, 6, 11, 9, 0, tzinfo=_ET))

    def test_after_close_is_not_rth(self):
        assert not is_rth(datetime(2026, 6, 11, 16, 30, tzinfo=_ET))

    def test_holiday_is_not_rth(self):
        # Noon on Christmas — clock says open, calendar says closed.
        assert not is_rth(datetime(2026, 12, 25, 12, 0, tzinfo=_ET))

    def test_early_close_afternoon_is_not_rth(self):
        # 14:00 on the Friday after Thanksgiving — after the 13:00 close.
        assert not is_rth(datetime(2026, 11, 27, 14, 0, tzinfo=_ET))
        # 11:00 the same day is still open.
        assert is_rth(datetime(2026, 11, 27, 11, 0, tzinfo=_ET))

    def test_naive_datetime_treated_as_eastern(self):
        assert is_rth(datetime(2026, 6, 11, 12, 0))
