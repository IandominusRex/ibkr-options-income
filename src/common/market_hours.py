"""US equity-market trading calendar + Regular Trading Hours (RTH) gate.

Self-contained — no external market-calendar dependency. Computes the NYSE/Nasdaq
full-day holidays and the three early-close (13:00 ET) sessions for any year, so the
desk never transmits orders or runs the intraday loop on a market holiday.

The early-close rules are an approximation of NYSE practice (good for the common
cases); verify against the official NYSE calendar for unusual edge years.

Single source of truth: both the order-execution bridge and the approval-service
intraday loop call :func:`is_rth` here instead of each keeping their own copy.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from datetime import time as dtime
from functools import lru_cache
from zoneinfo import ZoneInfo

_ET = ZoneInfo("America/New_York")
_OPEN = dtime(9, 30)
_REGULAR_CLOSE = dtime(16, 0)
_EARLY_CLOSE = dtime(13, 0)

# Mon=0 .. Sun=6
_MON, _THU, _FRI, _SAT, _SUN = 0, 3, 4, 5, 6


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """The *n*-th *weekday* of *month* (e.g. 3rd Monday of January)."""
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    """The last *weekday* of *month* (e.g. last Monday of May)."""
    if month == 12:
        last = date(year, 12, 31)
    else:
        last = date(year, month + 1, 1) - timedelta(days=1)
    offset = (last.weekday() - weekday) % 7
    return last - timedelta(days=offset)


def _easter(year: int) -> date:
    """Gregorian Easter Sunday (anonymous computus). Good Friday is two days earlier."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    ll = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ll) // 451
    month = (h + ll - 7 * m + 114) // 31
    day = ((h + ll - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _observed(d: date) -> date:
    """NYSE observance: a Saturday holiday rolls to Friday, a Sunday holiday to Monday."""
    if d.weekday() == _SAT:
        return d - timedelta(days=1)
    if d.weekday() == _SUN:
        return d + timedelta(days=1)
    return d


@lru_cache(maxsize=16)
def _holidays(year: int) -> frozenset[date]:
    """Full-day NYSE/Nasdaq market holidays for *year*."""
    days: set[date] = set()

    # New Year's Day — NYSE does NOT roll a Saturday Jan 1 back to Friday (that Friday is
    # in the prior year and trades normally), but a Sunday Jan 1 is observed on Monday.
    nyd = date(year, 1, 1)
    days.add(nyd + timedelta(days=1) if nyd.weekday() == _SUN else nyd)

    days.add(_nth_weekday(year, 1, _MON, 3))  # MLK Day
    days.add(_nth_weekday(year, 2, _MON, 3))  # Washington's Birthday / Presidents' Day
    days.add(_easter(year) - timedelta(days=2))  # Good Friday
    days.add(_last_weekday(year, 5, _MON))  # Memorial Day
    if year >= 2022:
        days.add(_observed(date(year, 6, 19)))  # Juneteenth
    days.add(_observed(date(year, 7, 4)))  # Independence Day
    days.add(_nth_weekday(year, 9, _MON, 1))  # Labor Day
    days.add(_nth_weekday(year, 11, _THU, 4))  # Thanksgiving
    days.add(_observed(date(year, 12, 25)))  # Christmas

    return frozenset(days)


@lru_cache(maxsize=16)
def _early_closes(year: int) -> frozenset[date]:
    """Half-day (13:00 ET close) sessions for *year* — approximation of NYSE practice."""
    days: set[date] = set()

    # July 3 closes early when it is a weekday and July 4 is a full-day weekday holiday.
    jul3 = date(year, 7, 3)
    if jul3.weekday() < _SAT and date(year, 7, 4).weekday() < _SAT:
        days.add(jul3)

    # Friday after Thanksgiving.
    days.add(_nth_weekday(year, 11, _THU, 4) + timedelta(days=1))

    # Christmas Eve when it falls Mon–Thu (a Friday Dec 24 is the observed Christmas holiday).
    dec24 = date(year, 12, 24)
    if dec24.weekday() <= _THU:
        days.add(dec24)

    return frozenset(days) - _holidays(year)


def is_market_holiday(d: date) -> bool:
    """True if *d* is a full-day US equity-market holiday."""
    return d in _holidays(d.year)


def is_early_close(d: date) -> bool:
    """True if *d* is a half-day (13:00 ET) trading session."""
    return d in _early_closes(d.year)


def is_trading_day(d: date) -> bool:
    """True if *d* is a regular US-equity trading session (weekday, not a holiday)."""
    return d.weekday() < _SAT and not is_market_holiday(d)


def previous_session(d: date) -> date:
    """The most recent completed trading session strictly before *d*.

    Walks back over weekends and full-day holidays. Used by the OHLCV loader to decide whether
    the stored history is current: if the newest stored bar is on/after this date, no fetch is
    needed (the latest settled session is already persisted).
    """
    cur = date.fromordinal(d.toordinal() - 1)
    while not is_trading_day(cur):
        cur = date.fromordinal(cur.toordinal() - 1)
    return cur


def session_close(d: date) -> dtime | None:
    """Closing time for *d*, or None if the market is closed (weekend or holiday)."""
    if d.weekday() >= _SAT or is_market_holiday(d):
        return None
    return _EARLY_CLOSE if is_early_close(d) else _REGULAR_CLOSE


def is_new_entry_window(now: datetime | None = None, entry_cutoff: str = "15:00") -> bool:
    """True when it is RTH *and* before the new-entry cutoff time (ET).

    After the cutoff the intraday loop still runs profit-take checks, but should
    not surface or queue new short positions (last-hour gamma risk + wide spreads).

    *entry_cutoff* is an "HH:MM" string in ET, defaulting to "15:00".
    """
    if now is None:
        now = datetime.now(_ET)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=_ET)
    else:
        now = now.astimezone(_ET)

    if not is_rth(now):
        return False

    h, m = (int(p) for p in entry_cutoff.split(":"))
    cutoff = dtime(h, m)
    return now.timetz().replace(tzinfo=None) < cutoff


def is_rth(now: datetime | None = None) -> bool:
    """True during Regular Trading Hours in ET (weekday, not a holiday, before the close).

    *now* may be naive or tz-aware; it is interpreted/converted to US/Eastern. Defaults
    to the current moment.
    """
    if now is None:
        now = datetime.now(_ET)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=_ET)
    else:
        now = now.astimezone(_ET)

    close = session_close(now.date())
    if close is None:
        return False
    return _OPEN <= now.timetz().replace(tzinfo=None) < close


def seconds_until_time(hh: int, mm: int, now: datetime | None = None) -> float:
    """Seconds (ET wall-clock) until the next occurrence of HH:MM — today if still
    ahead, else tomorrow. Mirrors seconds_until_next_aligned_mark's tz handling."""
    if now is None:
        now = datetime.now(_ET)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=_ET)
    else:
        now = now.astimezone(_ET)

    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def seconds_until_next_aligned_mark(interval_minutes: int, now: datetime | None = None) -> float:
    """Seconds (ET wall-clock) until the next :00/:15/:30/:45-style mark.

    For ``interval_minutes=15`` this lands on :00/:15/:30/:45 past the hour — since the
    market opens at 9:30 ET, that schedule produces 9:30, 9:45, 10:00, 10:15, ... so the
    intraday loop's cycles line up with the marks an operator expects.

    *now* may be naive or tz-aware; it is interpreted/converted to US/Eastern. Defaults
    to the current moment.
    """
    if now is None:
        now = datetime.now(_ET)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=_ET)
    else:
        now = now.astimezone(_ET)

    minutes_since_midnight = now.hour * 60 + now.minute + now.second / 60 + now.microsecond / 6e7
    next_mark = (minutes_since_midnight // interval_minutes + 1) * interval_minutes
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    target = midnight + timedelta(minutes=next_mark)
    return (target - now).total_seconds()


def now_et_hhmm() -> str:
    """Current wall-clock time as 'HH:MM ET', for operator-facing cycle messages."""
    return datetime.now(_ET).strftime("%H:%M ET")
