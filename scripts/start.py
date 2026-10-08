"""Single-command launcher for every long-running service in this repo.

Starts the long-running services as subprocesses and supervises them —
auto-restarting any that crash with exponential back-off. Also schedules the
end-of-day report itself: at the configured ET time on each trading day it
spawns a one-shot ``scripts.run_eod`` subprocess. **No cron job is required.**

Covers the two IBKR daemons (approval service, intraday monitor) plus the web
API and research worker, which hold no ``ib_async`` connection or clientId and
are just as supervisable. The one thing this does *not* start is the Next.js
frontend (``cd web && npm run dev``) — that's a Node process, not a Python
script, and you may not always want the dev server up.

Usage:
    python -m scripts.start              # approval + monitor + API + research worker + EOD scheduler
    python -m scripts.start --no-monitor   # skip the intraday monitor
    python -m scripts.start --no-approval  # skip the approval service
    python -m scripts.start --no-api       # skip the web API
    python -m scripts.start --no-research  # skip the research worker
    python -m scripts.start --no-spreads   # skip the daily credit-spread service
    python -m scripts.start --no-eod       # skip the built-in EOD scheduler

The EOD report fires at ``scheduler.eod_report`` (config/settings.yaml, default
16:15 ET) on NYSE trading days only. The last-run date is persisted to
``data/eod_scheduler_state.json`` so a launcher restart after the report has
already run does not fire it a second time (which would duplicate the journal
row + Telegram summary). If the launcher starts *after* the EOD time on a
trading day and the report has not yet run, it fires immediately (catch-up).

A running EOD report is itself bounded by ``scheduler.eod_timeout_minutes`` (default 60,
config/settings.yaml). Past that, the launcher kills it (SIGTERM, then SIGKILL after
`STOP_GRACE_SECONDS`) and logs an ERROR — a hung EOD (e.g. an account-summary fetch stuck
looping through an IBKR connectivity flap) used to block every later EOD indefinitely, since
a new one only ever spawned once ``eod_proc.poll()`` was not None (2026-09-29 incident: one
run was still alive >11h after it started). See `_supervise_eod` / `_eod_tick`.

Stop with Ctrl-C or SIGTERM — every child is sent SIGTERM, given `STOP_GRACE_SECONDS` to exit,
then SIGKILLed if it hasn't (2026-08-27: a hung `run_approval_service` shutdown ignored SIGTERM
and was orphaned when the launcher's old `sys.exit(0)`-right-after-`terminate()` didn't wait to
check — it kept polling Telegram for 30+ minutes and fought the next restart's process over both
the bot token and its clientIds). On startup, before launching anything, the launcher also scans
for and kills any stray process still running one of this project's own daemon modules — a
belt-and-suspenders guarantee against exactly that scenario (or a laptop sleep/crash, a terminal
closed without Ctrl-C, or a second `scripts.start` started by accident) leaving the new session
contending with a leftover one.
"""

import argparse
import contextlib
import json
import logging
import os
import signal
import subprocess
import sys
import time
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable

SERVICES = {
    "approval": {
        "label": "approval_service",
        "module": "scripts.run_approval_service",
        "log": PROJECT_ROOT / "logs" / "approval.log",
    },
    "monitor": {
        "label": "intraday_monitor",
        "module": "scripts.run_monitor",
        "log": PROJECT_ROOT / "logs" / "monitor.log",
    },
    "api": {
        "label": "web_api",
        "module": "scripts.run_api",
        "log": PROJECT_ROOT / "logs" / "api.log",
    },
    "research": {
        "label": "research_worker",
        "module": "scripts.run_research_worker",
        "log": PROJECT_ROOT / "logs" / "research.log",
    },
    "spreads": {
        "label": "spreads_service",
        "module": "scripts.run_spreads",
        "log": PROJECT_ROOT / "logs" / "spreads.log",
    },
}

EOD_LABEL = "eod_report"
EOD_MODULE = "scripts.run_eod"
EOD_LOG = PROJECT_ROOT / "logs" / "eod.log"
EOD_STATE_FILE = PROJECT_ROOT / "data" / "eod_scheduler_state.json"

# Grace pause before launching daemons, so a fast stop→start cycle gives IB Gateway time to
# release the previous session's client IDs. Without it, the new exec/scan/monitor connects can
# race the old sockets' teardown and hit Error 326 ("client id is already in use") — observed
# 2026-06-24 03:42, where the scan connection (clientId 15) lost the race and /account, /status,
# /scan, /positions went dark for the whole session. The connect-retry in connection.py is the
# real backstop; this just makes the collision unlikely in the first place. 0 disables.
STARTUP_GRACE_SECONDS = 4.0

# How long a child gets to exit cleanly after SIGTERM before _stop_all escalates to SIGKILL.
STOP_GRACE_SECONDS = 10.0

# Same idea, applied to a stray process found at startup (see _kill_stale_processes) —
# shorter, since there's no reason to wait long for a process this session didn't just ask
# to shut down gracefully a moment ago.
STALE_KILL_GRACE_SECONDS = 5.0

# Add project root to path so src.common is importable before any install
sys.path.insert(0, str(PROJECT_ROOT))
from src.common.logging import setup_logging  # noqa: E402

setup_logging()
log = logging.getLogger("launcher")


def _open_log(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    return open(path, "a")  # noqa: SIM115  — intentionally kept open


def _check_ollama() -> None:
    """Warn (don't block) if the configured Ollama backend isn't ready.

    The pipeline fails soft without Ollama — it ships the deterministic Rules-Engine
    list with no LLM enrichment — so a failed probe is a loud warning, not a fatal
    error. Skipped entirely when the backend doesn't use Ollama.
    """
    from src.claude.ollama_runner import probe_ollama
    from src.common.config import get_config

    backend = get_config().claude.backend
    if backend not in ("ollama", "cli_then_ollama"):
        return
    ok, msg = probe_ollama()
    if ok:
        log.info("Ollama backend (%s): %s", backend, msg)
    else:
        log.warning(
            "Ollama backend (%s) NOT ready — %s. Daemons will still run, but Claude "
            "enrichment will be SKIPPED (deterministic list only) until Ollama recovers.",
            backend,
            msg,
        )


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _find_stale_pids() -> list[int]:
    """PIDs of any *other* process currently running one of this project's own daemon modules.

    Matches on the command line via ``ps`` rather than a pidfile, so it catches a stray
    survivor regardless of how it was orphaned (this launcher's own bug, a crash, a laptop
    sleep, or a second `scripts.start` started by hand) — there's no state file that can go
    missing or go stale itself.

    Never returned (C1, 2026-09-30): this process, **any of its ancestors**, and any process
    whose argv[0] is ``caffeinate``. Under launchd the job is
    ``caffeinate -i -s <python> -m scripts.start``; the wrapper's own command line contains
    "scripts.start", so without these exclusions every start killed its own caffeinate parent
    and sleep prevention was silently off. A stray *child* of some other caffeinate wrapper
    is still caught — killing it lets that wrapper exit on its own.
    """
    own_pid = os.getpid()
    patterns: set[str] = {
        "scripts.start",
        EOD_MODULE,
        *(str(cfg["module"]) for cfg in SERVICES.values()),
    }
    try:
        out = subprocess.run(
            ["ps", "-eo", "pid,ppid,command"], capture_output=True, text=True, check=True
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        log.warning("Could not scan for stale processes (%s) — skipping the check", exc)
        return []

    procs: dict[int, tuple[int, str]] = {}
    for line in out.splitlines()[1:]:
        parts = line.strip().split(None, 2)
        if len(parts) != 3:
            continue
        pid_str, ppid_str, cmd = parts
        try:
            procs[int(pid_str)] = (int(ppid_str), cmd)
        except ValueError:
            continue

    # Walk our own ancestry: os.getppid() first (authoritative for the direct parent), then
    # the ps table for everything above it. Bounded against a malformed/cyclic table.
    ancestors: set[int] = set()
    cur = os.getppid()
    while cur > 1 and cur not in ancestors and len(ancestors) < 64:
        ancestors.add(cur)
        cur = procs.get(cur, (0, ""))[0]

    stale = []
    for pid, (_ppid, cmd) in procs.items():
        if pid == own_pid or pid in ancestors:
            continue
        if os.path.basename(cmd.split(None, 1)[0]) == "caffeinate":
            continue
        if any(pat in cmd for pat in patterns):
            stale.append(pid)
    return stale


def _kill_stale_processes() -> None:
    """Terminate any leftover daemon process from a prior session before we launch new ones.

    Without this, a survivor left behind by a hung/skipped shutdown (see the module
    docstring — 2026-08-27) fights the new session over the Telegram bot token
    (`telegram.error.Conflict`) and clientIds (Error 326), leaving /status, /scan, and the
    intraday loop dark until someone finds and kills it by hand.
    """
    stale = _find_stale_pids()
    if not stale:
        return
    log.warning(
        "Found %d stale process(es) from a prior session still running (%s) — terminating "
        "before startup",
        len(stale),
        stale,
    )
    for pid in stale:
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGTERM)

    deadline = time.monotonic() + STALE_KILL_GRACE_SECONDS
    remaining = set(stale)
    while remaining and time.monotonic() < deadline:
        time.sleep(0.5)
        remaining = {pid for pid in remaining if _pid_alive(pid)}
    for pid in remaining:
        log.warning("Stale PID %d did not exit after SIGTERM — sending SIGKILL", pid)
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)


def _start(name: str) -> subprocess.Popen:
    cfg = SERVICES[name]
    log_fh = _open_log(cfg["log"])
    proc = subprocess.Popen(
        [PYTHON, "-m", cfg["module"]],
        cwd=PROJECT_ROOT,
        stdout=log_fh,
        stderr=log_fh,
    )
    log.info("Started %s  PID=%d  → %s", cfg["label"], proc.pid, cfg["log"])
    return proc


# --- EOD scheduling -------------------------------------------------------


def _eod_time() -> tuple[int, int, ZoneInfo]:
    """Parse ``scheduler.eod_report`` (HH:MM) and timezone from config."""
    from src.common.config import get_config

    sched = get_config().scheduler
    hh, mm = (int(p) for p in sched.eod_report.split(":"))
    return hh, mm, ZoneInfo(sched.timezone)


def _read_eod_last_run() -> date | None:
    """Last date the EOD report was launched, or None. Tolerant of a missing/corrupt file."""
    try:
        raw = json.loads(EOD_STATE_FILE.read_text())
        return date.fromisoformat(raw["last_run"])
    except (FileNotFoundError, ValueError, KeyError, TypeError):
        return None


def _write_eod_last_run(d: date) -> None:
    EOD_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    EOD_STATE_FILE.write_text(json.dumps({"last_run": d.isoformat()}))


def _eod_should_fire(now: datetime, last_run: date | None, hh: int, mm: int) -> bool:
    """Pure decision: fire the EOD report iff *now* is a trading day, at/after HH:MM ET,
    and it has not already fired today. *now* must be timezone-aware (ET)."""
    from src.common.market_hours import is_trading_day

    today = now.date()
    if last_run == today:
        return False
    if not is_trading_day(today):
        return False
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    return now >= target


def _eod_timeout_minutes() -> int:
    """``scheduler.eod_timeout_minutes`` — the hard ceiling on a single EOD run."""
    from src.common.config import get_config

    return get_config().scheduler.eod_timeout_minutes


def _kill_hung_eod(proc: subprocess.Popen, grace_seconds: float) -> None:
    """Escalate a hung EOD subprocess: SIGTERM, then SIGKILL if it hasn't exited after
    *grace_seconds*. Mirrors ``_stop_all``'s termination sequence for the supervised daemons."""
    proc.terminate()
    try:
        proc.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        log.warning(
            "EOD PID %d did not exit within %.0fs of SIGTERM — sending SIGKILL",
            proc.pid,
            grace_seconds,
        )
        proc.kill()
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=5)


def _supervise_eod(
    eod_proc: subprocess.Popen | None,
    eod_start_time: float | None,
    eod_timeout_minutes: float,
    now_monotonic: float,
) -> tuple[subprocess.Popen | None, float | None]:
    """One scheduler-loop tick's worth of EOD-subprocess supervision.

    Returns ``(None, None)`` once the run is no longer occupying the slot — either it exited
    on its own (logged at INFO), or it exceeded *eod_timeout_minutes* and was killed (logged
    at ERROR). A hung EOD used to block every later EOD forever, since the launcher only ever
    spawned a new one once ``eod_proc.poll()`` was not None (2026-09-29: one run was still
    alive >11h after it started). Otherwise returns the pair unchanged so the caller keeps
    waiting.
    """
    if eod_proc is None:
        return None, None
    rc = eod_proc.poll()
    if rc is not None:
        log.info("%s finished (rc=%d)", EOD_LABEL, rc)
        return None, None
    started_at = eod_start_time if eod_start_time is not None else now_monotonic
    elapsed_min = (now_monotonic - started_at) / 60.0
    if elapsed_min > eod_timeout_minutes:
        log.error("EOD exceeded %d min — killed", eod_timeout_minutes)
        _kill_hung_eod(eod_proc, STOP_GRACE_SECONDS)
        return None, None
    return eod_proc, eod_start_time


def _eod_tick(
    eod_proc: subprocess.Popen | None,
    eod_start_time: float | None,
    eod_last_run: date | None,
    *,
    now_et: datetime,
    now_monotonic: float,
    eod_hh: int,
    eod_mm: int,
    eod_timeout_minutes: float,
    start_fn=None,
) -> tuple[subprocess.Popen | None, float | None, date | None]:
    """The scheduler loop's full per-iteration EOD decision: supervise any running EOD (killing
    one that hung past *eod_timeout_minutes*), then start a new one if none is running and one
    is due. Killing a hung run frees ``eod_proc`` in the very same tick, but that alone does not
    respawn one today: a live ``eod_proc`` only ever exists because *some* earlier tick already
    set ``eod_last_run`` to today when it spawned it, and ``_eod_should_fire`` refuses to fire
    twice in one day — so the freed slot sits empty for the rest of today and the next run
    fires normally on the next trading day. This is deliberate: without the same-day
    suppression, a run that keeps hanging past the timeout would kill and respawn in a tight
    loop for the rest of the day instead of giving up until tomorrow.
    """
    if start_fn is None:
        start_fn = _start_eod
    eod_proc, eod_start_time = _supervise_eod(
        eod_proc, eod_start_time, eod_timeout_minutes, now_monotonic
    )
    if eod_proc is None and _eod_should_fire(now_et, eod_last_run, eod_hh, eod_mm):
        eod_proc = start_fn()
        eod_start_time = now_monotonic
        eod_last_run = now_et.date()
        _write_eod_last_run(eod_last_run)
    return eod_proc, eod_start_time, eod_last_run


def _start_eod() -> subprocess.Popen:
    log_fh = _open_log(EOD_LOG)
    proc = subprocess.Popen(
        [PYTHON, "-m", EOD_MODULE],
        cwd=PROJECT_ROOT,
        stdout=log_fh,
        stderr=log_fh,
    )
    log.info("Started %s  PID=%d  → %s", EOD_LABEL, proc.pid, EOD_LOG)
    return proc


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="IBKR daemon launcher")
    parser.add_argument("--no-monitor", action="store_true", help="Skip intraday monitor")
    parser.add_argument("--no-approval", action="store_true", help="Skip approval service")
    parser.add_argument("--no-api", action="store_true", help="Skip the web API")
    parser.add_argument("--no-research", action="store_true", help="Skip the research worker")
    parser.add_argument(
        "--no-spreads", action="store_true", help="Skip the daily credit-spread service"
    )
    parser.add_argument("--no-eod", action="store_true", help="Skip the built-in EOD scheduler")
    return parser


def _active_services(args: argparse.Namespace) -> list[str]:
    return [k for k in SERVICES if not getattr(args, f"no_{k}", False)]


def main() -> None:
    args = _build_parser().parse_args()

    active = _active_services(args)
    if not active and args.no_eod:
        log.error("No services selected — nothing to start.")
        sys.exit(1)

    procs: dict[str, subprocess.Popen | None] = {k: None for k in active}
    restart_delays: dict[str, float] = {k: 5.0 for k in active}

    # One-shot EOD report subprocess (not supervised/restarted — it exits when done, or is
    # killed by _supervise_eod after eod_timeout_minutes).
    eod_proc: subprocess.Popen | None = None
    eod_start_time: float | None = None
    eod_last_run = _read_eod_last_run()
    eod_hh, eod_mm, eod_tz = (None, None, None)
    eod_timeout_minutes: float | None = None
    if not args.no_eod:
        eod_hh, eod_mm, eod_tz = _eod_time()
        eod_timeout_minutes = _eod_timeout_minutes()

    def _stop_all(signum, frame):
        log.info("Received signal %s — stopping all daemons…", signum)
        targets: list[subprocess.Popen] = []
        for name, proc in procs.items():
            if proc and proc.poll() is None:
                log.info("Terminating %s (PID %d)", name, proc.pid)
                proc.terminate()
                targets.append(proc)
        if eod_proc and eod_proc.poll() is None:
            log.info("Terminating %s (PID %d)", EOD_LABEL, eod_proc.pid)
            eod_proc.terminate()
            targets.append(eod_proc)

        # SIGTERM alone doesn't guarantee an exit — a hung shutdown (e.g. an unbounded await
        # in cleanup) can ignore it indefinitely. Wait up to STOP_GRACE_SECONDS total (shared
        # across all targets, not per-process) and SIGKILL anything still alive after that, so
        # this process never exits leaving an orphaned survivor behind (2026-08-27 incident).
        deadline = time.monotonic() + STOP_GRACE_SECONDS
        for proc in targets:
            remaining = max(0.0, deadline - time.monotonic())
            try:
                proc.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                log.warning(
                    "PID %d did not exit within %.0fs of SIGTERM — sending SIGKILL",
                    proc.pid,
                    STOP_GRACE_SECONDS,
                )
                proc.kill()
                with contextlib.suppress(subprocess.TimeoutExpired):
                    proc.wait(timeout=5)
        sys.exit(0)

    signal.signal(signal.SIGINT, _stop_all)
    signal.signal(signal.SIGTERM, _stop_all)

    _kill_stale_processes()
    _check_ollama()

    if STARTUP_GRACE_SECONDS > 0:
        log.info(
            "Waiting %.0fs before starting daemons so IB Gateway can release any client IDs "
            "held by a prior session…",
            STARTUP_GRACE_SECONDS,
        )
        time.sleep(STARTUP_GRACE_SECONDS)

    for name in active:
        procs[name] = _start(name)

    if args.no_eod:
        log.info("All daemons running. EOD scheduler DISABLED (--no-eod).")
    else:
        log.info(
            "All daemons running. EOD report scheduled for %02d:%02d %s on trading days.",
            eod_hh,
            eod_mm,
            eod_tz.key,
        )

    while True:
        time.sleep(10)
        for name in active:
            proc = procs[name]
            if proc is None:
                continue
            rc = proc.poll()
            if rc is not None:
                delay = restart_delays[name]
                log.warning(
                    "%s exited (rc=%d) — restarting in %.0fs…",
                    SERVICES[name]["label"],
                    rc,
                    delay,
                )
                time.sleep(delay)
                restart_delays[name] = min(delay * 2, 120)
                procs[name] = _start(name)
            else:
                restart_delays[name] = 5.0

        # EOD scheduler: fire once per trading day at the configured ET time. Also kills a
        # run that has exceeded eod_timeout_minutes so one hung EOD can't block every later
        # one (2026-09-29).
        if not args.no_eod:
            eod_proc, eod_start_time, eod_last_run = _eod_tick(
                eod_proc,
                eod_start_time,
                eod_last_run,
                now_et=datetime.now(eod_tz),
                now_monotonic=time.monotonic(),
                eod_hh=eod_hh,
                eod_mm=eod_mm,
                eod_timeout_minutes=eod_timeout_minutes,
            )


if __name__ == "__main__":
    main()
