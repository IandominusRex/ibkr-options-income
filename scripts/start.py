"""Launcher for the always-on IBKR daemons + the daily EOD report.

Starts the long-running services as subprocesses and supervises them —
auto-restarting any that crash with exponential back-off. Also schedules the
end-of-day report itself: at the configured ET time on each trading day it
spawns a one-shot ``scripts.run_eod`` subprocess. **No cron job is required.**

Usage:
    python -m scripts.start              # approval service + monitor + EOD scheduler
    python -m scripts.start --no-monitor   # skip the intraday monitor
    python -m scripts.start --no-approval  # skip the approval service
    python -m scripts.start --no-eod       # skip the built-in EOD scheduler

The EOD report fires at ``scheduler.eod_report`` (config/settings.yaml, default
16:15 ET) on NYSE trading days only. The last-run date is persisted to
``data/eod_scheduler_state.json`` so a launcher restart after the report has
already run does not fire it a second time (which would duplicate the journal
row + Telegram summary). If the launcher starts *after* the EOD time on a
trading day and the report has not yet run, it fires immediately (catch-up).

Stop with Ctrl-C or SIGTERM — all child processes are cleanly terminated.
"""

import argparse
import json
import logging
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


def main() -> None:
    parser = argparse.ArgumentParser(description="IBKR daemon launcher")
    parser.add_argument("--no-monitor", action="store_true", help="Skip intraday monitor")
    parser.add_argument("--no-approval", action="store_true", help="Skip approval service")
    parser.add_argument("--no-eod", action="store_true", help="Skip the built-in EOD scheduler")
    args = parser.parse_args()

    active = [k for k in SERVICES if not getattr(args, f"no_{k}", False)]
    if not active and args.no_eod:
        log.error("No services selected — nothing to start.")
        sys.exit(1)

    procs: dict[str, subprocess.Popen | None] = {k: None for k in active}
    restart_delays: dict[str, float] = {k: 5.0 for k in active}

    # One-shot EOD report subprocess (not supervised/restarted — it exits when done).
    eod_proc: subprocess.Popen | None = None
    eod_last_run = _read_eod_last_run()
    eod_hh, eod_mm, eod_tz = (None, None, None)
    if not args.no_eod:
        eod_hh, eod_mm, eod_tz = _eod_time()

    def _stop_all(signum, frame):
        log.info("Received signal %s — stopping all daemons…", signum)
        for name, proc in procs.items():
            if proc and proc.poll() is None:
                log.info("Terminating %s (PID %d)", name, proc.pid)
                proc.terminate()
        if eod_proc and eod_proc.poll() is None:
            log.info("Terminating %s (PID %d)", EOD_LABEL, eod_proc.pid)
            eod_proc.terminate()
        sys.exit(0)

    signal.signal(signal.SIGINT, _stop_all)
    signal.signal(signal.SIGTERM, _stop_all)

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

        # EOD scheduler: fire once per trading day at the configured ET time.
        if not args.no_eod:
            if eod_proc is not None and eod_proc.poll() is not None:
                log.info("%s finished (rc=%d)", EOD_LABEL, eod_proc.returncode)
                eod_proc = None
            if eod_proc is None and _eod_should_fire(
                datetime.now(eod_tz), eod_last_run, eod_hh, eod_mm
            ):
                eod_proc = _start_eod()
                eod_last_run = datetime.now(eod_tz).date()
                _write_eod_last_run(eod_last_run)


if __name__ == "__main__":
    main()
