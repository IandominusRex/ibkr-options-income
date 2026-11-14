"""The static macro calendar (risk-envelope Task 2)."""

from __future__ import annotations

from datetime import date, timedelta

from src.common.macro_calendar import events_between, events_on, load_calendar

# Any FOMC decision day the Fed published on a day other than Wednesday goes here, with the reason.
# None as of 2026-11-14: every decision day on the 2026-12 to 2027-11 schedule is a Wednesday.
FOMC_NON_WEDNESDAY_EXCEPTIONS: set[date] = set()


def test_the_calendar_loads_and_is_sorted() -> None:
    cal = load_calendar()
    assert len(cal) > 50
    assert [e.day for e in cal] == sorted(e.day for e in cal)
    assert {e.kind for e in cal} == {"FOMC", "CPI", "PPI", "NFP", "PCE"}
    assert min(e.day for e in cal) >= date(2026, 11, 14)
    for e in cal:
        assert e.day.weekday() < 5, e
        assert e.time_et in {"08:30", "14:00"}, e


def test_every_row_names_a_source() -> None:
    for e in load_calendar():
        assert e.source.startswith("https://www."), e
        assert any(h in e.source for h in ("federalreserve.gov", "bls.gov", "bea.gov")), e


def test_events_on_returns_the_days_rows() -> None:
    fomc = events_on(date(2026, 12, 9))
    assert [e.kind for e in fomc] == ["FOMC"] and fomc[0].time_et == "14:00"
    assert events_on(date(2026, 12, 8)) == []
    # two releases the same morning come back together
    assert {e.kind for e in events_on(date(2027, 3, 31))} == {"PCE"}
    rng = events_between(date(2026, 12, 1), date(2026, 12, 31))
    assert [e.kind for e in rng] == ["NFP", "FOMC", "CPI", "PPI", "PCE"]
    assert events_between(date(2030, 1, 1), date(2030, 12, 31)) == []


def test_fomc_days_are_wednesdays_or_announced_exceptions() -> None:
    fomc = [e for e in load_calendar() if e.kind == "FOMC"]
    assert fomc
    for e in fomc:
        assert e.day.weekday() == 2 or e.day in FOMC_NON_WEDNESDAY_EXCEPTIONS, e
        assert e.time_et == "14:00"


def test_the_calendar_reaches_a_year_ahead() -> None:
    assert max(e.day for e in load_calendar()) >= date.today() + timedelta(days=300)
