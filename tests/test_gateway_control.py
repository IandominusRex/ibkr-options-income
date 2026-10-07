"""Tests for src/ops/gateway_control.py — the automatic IB Gateway restart on Error 10197.

launchctl, signals, sleeps, the clock, and the port check are all injected fakes: nothing
here touches a real launchd job or Gateway.
"""

from __future__ import annotations

import signal
import subprocess
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from src.common.config import GatewayRecoveryCfg
from src.ops.gateway_control import GatewayRestarter

_ET = ZoneInfo("America/New_York")
_PRINT_RUNNING = "com.ibkr.gateway = {\n\tstate = running\n\tpid = 4242\n}\n"
_PRINT_STOPPED = "com.ibkr.gateway = {\n\tstate = not running\n\tlast exit code = 0\n}\n"


class FakeWorld:
    """A fake launchd job + Gateway process group, driven by the restarter's own calls."""

    def __init__(
        self,
        *,
        loaded: bool = True,
        running: bool = True,
        dies_on: int = signal.SIGTERM,
        kickstart_rc: int = 0,
        port_opens: bool = True,
    ) -> None:
        self.loaded = loaded
        self.running = running
        self.group_alive = running
        self.dies_on = dies_on
        self.kickstart_rc = kickstart_rc
        self.port_opens = port_opens
        self.signals: list[tuple[int, int]] = []
        self.commands: list[list[str]] = []
        self.clock = 0.0
        self.now = datetime(2026, 10, 2, 11, 0, tzinfo=_ET)

    def run(self, args: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        self.commands.append(args)
        if args[1] == "print":
            if not self.loaded:
                return subprocess.CompletedProcess(args, 113, "", "Could not find service")
            out = _PRINT_RUNNING if self.running else _PRINT_STOPPED
            return subprocess.CompletedProcess(args, 0, out, "")
        if args[1] == "kickstart":
            if self.kickstart_rc == 0:
                self.running = self.group_alive = True
            return subprocess.CompletedProcess(args, self.kickstart_rc, "", "boom")
        raise AssertionError(f"unexpected command {args}")

    def killpg(self, pgid: int, sig: int) -> None:
        if not self.group_alive:
            raise ProcessLookupError
        if sig == 0:
            return
        self.signals.append((pgid, sig))
        if sig in (self.dies_on, signal.SIGKILL):
            self.group_alive = self.running = False

    def getpgid(self, pid: int) -> int:
        return pid

    def sleep(self, s: float) -> None:
        self.clock += s

    def monotonic(self) -> float:
        return self.clock

    def port_open(self, port: int) -> bool:
        return self.port_opens

    def restarter(self, **cfg: object) -> GatewayRestarter:
        return GatewayRestarter(
            GatewayRecoveryCfg(**cfg),  # type: ignore[arg-type]
            port=4002,
            run=self.run,
            killpg=self.killpg,
            getpgid=self.getpgid,
            sleep=self.sleep,
            monotonic=self.monotonic,
            now=lambda: self.now,
            port_open=self.port_open,
            uid=501,
        )


def _kickstarts(w: FakeWorld) -> list[list[str]]:
    return [c for c in w.commands if c[1] == "kickstart"]


def test_happy_path_stops_group_then_starts_without_k():
    w = FakeWorld()
    out = w.restarter().restart()
    assert out.attempted and out.ok
    assert out.attempts_today == 1
    assert w.signals == [(4242, signal.SIGTERM)]
    # Plain kickstart, never `-k`: `-k` relaunches while the old Java is still exiting and
    # start_gateway.sh's duplicate guard then starts nothing (2026-10-02).
    assert _kickstarts(w) == [["launchctl", "kickstart", "gui/501/com.ibkr.gateway"]]
    assert "1/3" in out.message


def test_disabled_never_touches_launchd():
    w = FakeWorld()
    out = w.restarter(enabled=False).restart()
    assert not out.attempted
    assert w.commands == [] and w.signals == []


def test_agent_not_loaded_is_not_attempted_and_says_restart_by_hand():
    w = FakeWorld(loaded=False)
    out = w.restarter().restart()
    assert not out.attempted and not out.ok
    assert "by hand" in out.message
    assert w.signals == [] and _kickstarts(w) == []


def test_job_not_running_skips_the_kill_and_just_starts():
    w = FakeWorld(running=False)
    out = w.restarter().restart()
    assert out.ok
    assert w.signals == []
    assert len(_kickstarts(w)) == 1


def test_stuck_group_gets_sigkill_after_stop_timeout():
    w = FakeWorld(dies_on=-1)  # ignores SIGTERM
    out = w.restarter(stop_timeout_seconds=10).restart()
    assert out.ok
    assert w.signals == [(4242, signal.SIGTERM), (4242, signal.SIGKILL)]
    assert w.clock >= 10


def test_cooldown_blocks_a_second_restart_then_allows_it():
    w = FakeWorld()
    r = w.restarter(cooldown_minutes=30)
    assert r.restart().attempted
    w.now += timedelta(minutes=15)
    second = r.restart()
    assert not second.attempted
    assert "cooldown" in second.message.lower()
    w.now += timedelta(minutes=16)
    assert r.restart().attempted


def test_daily_cap_then_resets_next_et_day():
    w = FakeWorld()
    r = w.restarter(cooldown_minutes=0, max_restarts_per_day=2)
    assert r.restart().attempted
    assert r.restart().attempted
    capped = r.restart()
    assert not capped.attempted
    assert "2/2" in capped.message
    w.now += timedelta(days=1)
    assert r.restart().attempted


def test_kickstart_failure_counts_as_an_attempt_and_reports_not_ok():
    w = FakeWorld(kickstart_rc=5)
    r = w.restarter(cooldown_minutes=0)
    out = r.restart()
    assert out.attempted and not out.ok
    assert out.attempts_today == 1
    assert "kickstart" in out.message


def test_port_never_opens_reports_not_ok():
    w = FakeWorld(port_opens=False)
    out = w.restarter(port_wait_seconds=20).restart()
    assert out.attempted and not out.ok
    assert "4002" in out.message
