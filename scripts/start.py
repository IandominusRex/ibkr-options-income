"""Launcher for the two always-on IBKR daemons.

Starts both long-running services as subprocesses and supervises them —
auto-restarting any that crash with exponential back-off.

Usage:
    python -m scripts.start           # start approval service + monitor
    python -m scripts.start --no-monitor   # approval service only
    python -m scripts.start --no-approval  # monitor only

Cron jobs (morning scan, EOD report) are NOT started here — they must be
scheduled via cron so they fire at exact market-hours times. See SETUP.md §8.

Stop with Ctrl-C or SIGTERM — both child processes are cleanly terminated.
"""

import argparse
import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
)
log = logging.getLogger("launcher")


def _open_log(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    return open(path, "a")  # noqa: SIM115  — intentionally kept open


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


def main() -> None:
    parser = argparse.ArgumentParser(description="IBKR daemon launcher")
    parser.add_argument("--no-monitor", action="store_true", help="Skip intraday monitor")
    parser.add_argument("--no-approval", action="store_true", help="Skip approval service")
    args = parser.parse_args()

    active = [k for k in SERVICES if not getattr(args, f"no_{k}", False)]
    if not active:
        log.error("No services selected — nothing to start.")
        sys.exit(1)

    procs: dict[str, subprocess.Popen | None] = {k: None for k in active}
    restart_delays: dict[str, float] = {k: 5.0 for k in active}

    def _stop_all(signum, frame):
        log.info("Received signal %s — stopping all daemons…", signum)
        for name, proc in procs.items():
            if proc and proc.poll() is None:
                log.info("Terminating %s (PID %d)", name, proc.pid)
                proc.terminate()
        sys.exit(0)

    signal.signal(signal.SIGINT, _stop_all)
    signal.signal(signal.SIGTERM, _stop_all)

    for name in active:
        procs[name] = _start(name)

    log.info(
        "All daemons running. Cron jobs (morning scan, EOD) are NOT managed here — "
        "set them up with `crontab -e` per SETUP.md §8."
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


if __name__ == "__main__":
    main()
