"""Tests for the launcher's built-in EOD scheduler (scripts/start.py).

The launcher fires `scripts.run_eod` as a one-shot subprocess at the configured ET
time on trading days — replacing the old crontab job. These tests cover the pure
firing decision and the last-run state-file persistence; the subprocess spawn itself
is the same `subprocess.Popen` pattern used for the supervised daemons.
"""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace
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


# --------------------------------------------------------------------------- #
# Stale-process guard (2026-08-27: a hung shutdown orphaned run_approval_service,
# which fought the next restart over the Telegram bot token and its clientIds).
# --------------------------------------------------------------------------- #


def test_find_stale_pids_matches_own_daemon_modules(monkeypatch):
    monkeypatch.setattr(start.os, "getpid", lambda: 100)
    fake_ps = (
        "  PID COMMAND\n"
        " 100 python -m scripts.start\n"
        " 200 python -m scripts.run_approval_service\n"
        " 300 python -m scripts.run_monitor\n"
        " 400 /usr/bin/some_unrelated_process\n"
    )
    monkeypatch.setattr(start.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=fake_ps))
    assert sorted(start._find_stale_pids()) == [200, 300]


def test_find_stale_pids_excludes_own_pid(monkeypatch):
    monkeypatch.setattr(start.os, "getpid", lambda: 200)
    fake_ps = " 200 python -m scripts.run_approval_service\n"
    monkeypatch.setattr(start.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=fake_ps))
    assert start._find_stale_pids() == []


def test_find_stale_pids_returns_empty_on_ps_failure(monkeypatch):
    def fake_run(*_a, **_k):
        raise OSError("no ps")

    monkeypatch.setattr(start.subprocess, "run", fake_run)
    assert start._find_stale_pids() == []


def test_kill_stale_processes_noop_when_none_found(monkeypatch):
    monkeypatch.setattr(start, "_find_stale_pids", lambda: [])
    calls = []
    monkeypatch.setattr(start.os, "kill", lambda *a: calls.append(a))
    start._kill_stale_processes()
    assert calls == []


def test_kill_stale_processes_sigkills_a_survivor_after_the_grace_window(monkeypatch):
    monkeypatch.setattr(start, "_find_stale_pids", lambda: [111])
    monkeypatch.setattr(start, "STALE_KILL_GRACE_SECONDS", 1.0)
    monkeypatch.setattr(start.time, "sleep", lambda _s: None)
    monkeypatch.setattr(start, "_pid_alive", lambda _pid: True)  # never exits on SIGTERM alone

    clock = [0.0]

    def fake_monotonic():
        clock[0] += 0.5
        return clock[0]

    monkeypatch.setattr(start.time, "monotonic", fake_monotonic)
    sent: list[tuple[int, int]] = []
    monkeypatch.setattr(start.os, "kill", lambda pid, sig: sent.append((pid, sig)))

    start._kill_stale_processes()

    assert (111, start.signal.SIGTERM) in sent
    assert (111, start.signal.SIGKILL) in sent


def test_kill_stale_processes_skips_sigkill_if_process_exits_in_time(monkeypatch):
    monkeypatch.setattr(start, "_find_stale_pids", lambda: [111])
    monkeypatch.setattr(start, "STALE_KILL_GRACE_SECONDS", 5.0)
    monkeypatch.setattr(start.time, "sleep", lambda _s: None)
    monkeypatch.setattr(start.time, "monotonic", lambda: 0.0)  # deadline never reached
    monkeypatch.setattr(start, "_pid_alive", lambda _pid: False)  # exits immediately

    sent: list[tuple[int, int]] = []
    monkeypatch.setattr(start.os, "kill", lambda pid, sig: sent.append((pid, sig)))

    start._kill_stale_processes()

    assert sent == [(111, start.signal.SIGTERM)]
