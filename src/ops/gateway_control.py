"""Restart the IBC-managed IB Gateway when an Error 10197 competing-session block sticks.

Why this exists (2026-10-02): another login on the IBKR username (IBKR Mobile, the Client
Portal, a second TWS) took the live market-data entitlement the paper account shares, and
every scan was blocked with Error 10197 for ~16 hours. Logging out of the other session did
**not** bring the data back — the running Gateway only regained it after a fresh login. The
intraday loop's own recovery (dropping the scan socket so AutoReconnect rebuilds it) never
touches the Gateway's upstream session, so it could not fix this.

So on a 10197-diagnosed block the intraday loop calls :meth:`GatewayRestarter.restart`,
which stops and relaunches the ``com.ibkr.gateway`` launchd job (``./ibkr install
--with-gateway`` → ``scripts/ibc/start_gateway.sh`` → IBC, which logs in from ``.env`` with
no human). The daemons' own reconnect logic then reattaches within about a minute.

The restart is deliberately **stop, wait, then start** — never ``launchctl kickstart -k``.
``-k`` relaunches the job immediately; the old Gateway JVM is still exiting at that point,
``start_gateway.sh``'s duplicate-instance guard sees it and exits 0, and Gateway is left
**down** (verified live 2026-10-02 23:40). Instead the job's process group (launchd makes
the job pid its group leader; the JVM is a grandchild in that group) gets SIGTERM, then
SIGKILL after ``stop_timeout_seconds``, and only once the group and the job are both gone
does a plain ``kickstart`` start it again.

Bounded by ``gateway_recovery`` in ``config/settings.yaml``: a cooldown between restarts and
a per-ET-day cap, so a session that is genuinely still holding the data can't make this loop
— once the cap is spent the caller tells the operator to find that session instead. State
is in-memory; it resets when the approval service restarts, which is rare and harmless.

Ops-only: no IBKR API connection, no clientId, no trading state. Nothing in the engine,
execution or strategy path imports this — it can restart Gateway, never gate or size an
order.
"""

from __future__ import annotations

import logging
import os
import re
import signal
import socket
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from src.common.config import GatewayRecoveryCfg

log = logging.getLogger(__name__)

GATEWAY_LABEL = "com.ibkr.gateway"
_ET = ZoneInfo("America/New_York")
_PID_RE = re.compile(r"^\s*pid = (\d+)\s*$", re.MULTILINE)
_POLL_SECONDS = 1.0


@dataclass
class RestartOutcome:
    attempted: bool
    ok: bool
    # One plain-text sentence for the operator, e.g. the Telegram scan-blocked message.
    message: str
    attempts_today: int = 0


def _run_cmd(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
    """The real launchctl call. Module-level (not a default argument) so tests/conftest.py
    can replace it suite-wide: on 2026-10-02 a loop test that fed a 10197 probe through the
    intraday loop without mocking the restarter restarted the operator's live Gateway twice.
    """
    return subprocess.run(args, **kwargs)  # type: ignore[call-overload]


def _killpg(pgid: int, sig: int) -> None:
    """The real process-group signal — module-level for the same reason as ``_run_cmd``."""
    os.killpg(pgid, sig)


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=2):
            return True
    except OSError:
        return False


class GatewayRestarter:
    """Rate-limited stop-then-start of the ``com.ibkr.gateway`` launchd job.

    Every OS touchpoint is injectable so the tests never run launchctl or send a signal.
    :meth:`restart` blocks (up to ``stop_timeout_seconds + port_wait_seconds``) — call it
    via ``asyncio.to_thread`` from async code.
    """

    def __init__(
        self,
        cfg: GatewayRecoveryCfg,
        *,
        port: int,
        run: Callable[..., subprocess.CompletedProcess[str]] | None = None,
        killpg: Callable[[int, int], None] | None = None,
        getpgid: Callable[[int], int] = os.getpgid,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = lambda: datetime.now(_ET),
        port_open: Callable[[int], bool] = _port_open,
        uid: int | None = None,
    ) -> None:
        self._cfg = cfg
        self._port = port
        # Resolved here, not as default arguments, so a patched _run_cmd/_killpg (the test
        # suite's guard) is what an un-injected restarter actually calls.
        self._run = run if run is not None else _run_cmd
        self._killpg = killpg if killpg is not None else _killpg
        self._getpgid = getpgid
        self._sleep = sleep
        self._monotonic = monotonic
        self._now = now
        self._port_open = port_open
        self._target = f"gui/{os.getuid() if uid is None else uid}/{GATEWAY_LABEL}"
        self._last_restart: datetime | None = None
        self._day: date | None = None
        self._count = 0

    # --- public ------------------------------------------------------------------------

    def restart(self) -> RestartOutcome:
        cfg = self._cfg
        if not cfg.enabled:
            return RestartOutcome(False, False, "Automatic Gateway restart is disabled.")

        now = self._now()
        today = now.astimezone(_ET).date()
        if self._day != today:
            self._day, self._count = today, 0

        if self._count >= cfg.max_restarts_per_day:
            return RestartOutcome(
                False,
                False,
                f"Gateway already restarted {self._count}/{cfg.max_restarts_per_day} times "
                "today and the block keeps coming back, so another session is still holding "
                "the market data. Find and log out of it (IBKR Mobile, the IBKR website, "
                "another TWS/Gateway), then restart IB Gateway.",
                self._count,
            )
        if self._last_restart is not None:
            elapsed_min = (now - self._last_restart).total_seconds() / 60
            if elapsed_min < cfg.cooldown_minutes:
                return RestartOutcome(
                    False,
                    False,
                    f"Gateway was restarted {elapsed_min:.0f} min ago; holding off "
                    f"({cfg.cooldown_minutes}-min cooldown) before trying again.",
                    self._count,
                )

        pid = self._job_pid()
        if pid is None and not self._is_loaded():
            return RestartOutcome(
                False,
                False,
                f"Can't restart automatically: the {GATEWAY_LABEL} launchd agent isn't "
                "loaded (Gateway wasn't started by `./ibkr install --with-gateway`). "
                "Restart IB Gateway by hand.",
                self._count,
            )

        self._count += 1
        self._last_restart = now
        attempt = f"attempt {self._count}/{cfg.max_restarts_per_day} today"
        log.warning("gateway restart: restarting %s (%s)", GATEWAY_LABEL, attempt)

        ok, detail = self.stop_and_start()
        if ok:
            msg = f"Restarted IB Gateway with a fresh login ({attempt})."
            log.warning("gateway restart: %s", msg)
        else:
            msg = f"Gateway restart failed: {detail} ({attempt})."
            log.error("gateway restart: %s", msg)
        return RestartOutcome(True, ok, msg, self._count)

    def stop_and_start(self) -> tuple[bool, str]:
        """The unthrottled mechanics: stop the job's process group, wait until it and the job
        are gone, plain ``kickstart``, wait for the API port. Returns ``(ok, detail)``.

        Also what ``./ibkr start`` uses for the gateway label (``scripts/launchd.py``), which
        used ``kickstart -k`` for every agent and so left Gateway down the same way.
        Assumes the job is loaded — a ``kickstart`` of an unloaded label fails, reported as
        ``ok=False``.
        """
        self.stop()

        r = self._run(["launchctl", "kickstart", self._target], capture_output=True, text=True)
        if r.returncode != 0:
            return False, (
                f"launchctl kickstart exited {r.returncode} ({(r.stderr or '').strip()})"
            )
        return self.wait_for_port()

    def stop(self) -> tuple[bool, str]:
        """Stop the job's process group and wait until it and the job are both gone.

        Also what ``./ibkr stop`` uses before ``launchctl bootout`` (``scripts/launchd.py``):
        bootout alone returns as soon as the job's own pid exits, while the Gateway JVM — a
        grandchild in the job's group — is still shutting down, so ``./ibkr restart``'s
        bootstrap hit ``start_gateway.sh``'s duplicate guard and left Gateway down
        (2026-10-09). A label that isn't loaded, or a job that isn't running, is already
        stopped.
        """
        pid = self._job_pid()
        if pid is None:
            return True, "not running"
        log.warning("gateway restart: stopping %s (pid=%d)", GATEWAY_LABEL, pid)
        if self._stop_group(pid):
            return True, f"stopped (pid={pid})"
        return False, f"process group of pid {pid} still alive after SIGKILL"

    def wait_for_port(self) -> tuple[bool, str]:
        """Wait up to ``port_wait_seconds`` for the relaunched Gateway's API port."""
        deadline = self._monotonic() + self._cfg.port_wait_seconds
        while self._monotonic() < deadline:
            if self._port_open(self._port):
                return True, f"API port {self._port} accepting connections"
            self._sleep(_POLL_SECONDS)
        return False, (
            f"relaunched, but API port {self._port} wasn't accepting connections after "
            f"{self._cfg.port_wait_seconds}s — check the Gateway window / ~/Applications/ibc/logs"
        )

    # --- launchd / process plumbing ----------------------------------------------------

    def _print(self) -> subprocess.CompletedProcess[str]:
        return self._run(["launchctl", "print", self._target], capture_output=True, text=True)

    def _is_loaded(self) -> bool:
        return self._print().returncode == 0

    def _job_pid(self) -> int | None:
        r = self._print()
        if r.returncode != 0:
            return None
        m = _PID_RE.search(r.stdout or "")
        return int(m.group(1)) if m else None

    def _group_alive(self, pgid: int) -> bool:
        try:
            self._killpg(pgid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def _wait_stopped(self, pgid: int, seconds: float) -> bool:
        deadline = self._monotonic() + seconds
        while self._monotonic() < deadline:
            if not self._group_alive(pgid) and self._job_pid() is None:
                return True
            self._sleep(_POLL_SECONDS)
        return not self._group_alive(pgid) and self._job_pid() is None

    def _stop_group(self, pid: int) -> bool:
        """SIGTERM, then SIGKILL, the job's process group. True once the group and job are gone."""
        try:
            pgid = self._getpgid(pid)
        except ProcessLookupError:
            return True
        try:
            self._killpg(pgid, signal.SIGTERM)
        except ProcessLookupError:
            return True
        if self._wait_stopped(pgid, self._cfg.stop_timeout_seconds):
            return True
        log.warning("gateway restart: group %d ignored SIGTERM — sending SIGKILL", pgid)
        try:
            self._killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            return True
        return self._wait_stopped(pgid, 10)
