"""Tests for the launcher's built-in EOD scheduler (scripts/start.py).

The launcher fires `scripts.run_eod` as a one-shot subprocess at the configured ET
time on trading days — replacing the old crontab job. These tests cover the pure
firing decision and the last-run state-file persistence; the subprocess spawn itself
is the same `subprocess.Popen` pattern used for the supervised daemons.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import scripts.start as start

_ET = ZoneInfo("America/New_York")

# 2026-06-22 is a Monday (a normal NYSE trading day); 2026-06-20 is the Saturday before;
# 2026-12-25 is Christmas (a full-day NYSE holiday that falls on a Friday).
_MON = date(2026, 6, 22)
_SAT = date(2026, 6, 20)
_XMAS = date(2026, 12, 25)


def _at(d: date, hh: int, mm: int) -> datetime:
    return datetime(d.year, d.month, d.day, hh, mm, tzinfo=_ET)


def test_fires_at_or_after_eod_time_on_trading_day():
    assert start._eod_should_fire(_at(_MON, 16, 15), last_run=None, hh=16, mm=15) is True
    assert start._eod_should_fire(_at(_MON, 16, 30), last_run=None, hh=16, mm=15) is True


def test_does_not_fire_before_eod_time():
    assert start._eod_should_fire(_at(_MON, 16, 14), last_run=None, hh=16, mm=15) is False
    assert start._eod_should_fire(_at(_MON, 9, 30), last_run=None, hh=16, mm=15) is False


def test_does_not_fire_twice_same_day():
    # Already ran today → suppressed even though we're past the EOD time.
    assert start._eod_should_fire(_at(_MON, 16, 30), last_run=_MON, hh=16, mm=15) is False


def test_yesterdays_run_does_not_block_today():
    assert (
        start._eod_should_fire(_at(_MON, 16, 30), last_run=date(2026, 6, 19), hh=16, mm=15) is True
    )


def test_does_not_fire_on_weekend():
    assert start._eod_should_fire(_at(_SAT, 16, 30), last_run=None, hh=16, mm=15) is False


def test_does_not_fire_on_market_holiday():
    assert start._eod_should_fire(_at(_XMAS, 16, 30), last_run=None, hh=16, mm=15) is False


def test_state_file_round_trip(tmp_path, monkeypatch):
    state = tmp_path / "eod_scheduler_state.json"
    monkeypatch.setattr(start, "EOD_STATE_FILE", state)

    assert start._read_eod_last_run() is None  # missing file → None
    start._write_eod_last_run(_MON)
    assert start._read_eod_last_run() == _MON


def test_state_file_tolerates_corruption(tmp_path, monkeypatch):
    state = tmp_path / "eod_scheduler_state.json"
    state.write_text("not json{")
    monkeypatch.setattr(start, "EOD_STATE_FILE", state)
    assert start._read_eod_last_run() is None
