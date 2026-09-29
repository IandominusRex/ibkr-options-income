"""launchd agent management for the paper-trading stack (scan-loop remediation Task 6).

Three agents, all built with ``plistlib.dumps`` (no string templates, so quoting a repo
path with a space in it — this one lives under ``~/Desktop/IBKR Investments`` — is never a
hand-rolled XML-escaping problem):

- ``com.ibkr.supervisor`` — ``caffeinate -i -s <venv-python> -m scripts.start``. Keeps the
  whole supervised process tree (approval service, monitor, API, research worker, EOD
  scheduler — see ``scripts/start.py``) alive with ``KeepAlive``, and prevents idle/system
  sleep from freezing it mid-session (2026-09-11's research-worker sleep incident — see
  ``ARCHITECTURE.md``'s troubleshooting table) whenever the Mac is on AC power. launchd only
  has to keep *this one process* alive; ``scripts.start`` supervises everything under it.
- ``com.ibkr.watchdog`` — ``<venv-python> -m scripts.watchdog``, run every
  ``watchdog.interval_seconds`` (default 300) via ``StartInterval``, entirely outside the
  supervisor's process tree (see ``src/ops/watchdog.py``'s module docstring for why: the
  2026-09-15..22 outage went unnoticed because the only alerting lived in the stack that had
  stopped).
- ``com.ibkr.gateway`` — opt-in (``./ibkr install --with-gateway``), launches IB Gateway via
  IBC (``scripts/ibc/start_gateway.sh``). ``KeepAlive`` is deliberately ``false`` — IBC owns
  Gateway's own restart cycle (including the mandatory Sunday cold restart), so launchd
  restarting the wrapper script over IBC's back would just fight it.

The Python interpreter used in every plist is the repo's own ``.venv/bin/python`` — an
*unresolved* symlink chain (``.venv/bin/python -> python3.12 -> .../Python.framework/...``).
Do **not** call ``Path.resolve()`` on it: resolving through to the framework binary changes
``sys.prefix`` away from the venv (verified empirically during this task — the resolved
binary reports ``sys.prefix`` as the Framework path, not ``.venv``), which would drop every
third-party dependency (``ib_async``, SQLAlchemy, FastAPI, ...) off ``sys.path``. launchd
execs through symlinks itself at the OS level, same as any `exec()` — passing the plain
absolute ``.venv/bin/python`` path is both correct and sufficient.

CLI: ``install [--with-gateway]``, ``uninstall``, ``start``, ``stop``, ``status`` — see
``./ibkr`` (repo root) for the human-facing wrapper (adds the pre-install terminal-stack
guard, ``logs``, ``watchdog``, and ``autonomy`` dispatch). Every subcommand here operates on
whichever of the three labels are currently *installed* (a plist present under
``~/Library/LaunchAgents``), discovered from disk rather than requiring the caller to name
one explicitly.
"""

from __future__ import annotations

import argparse
import os
import plistlib
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"

LABEL_SUPERVISOR = "com.ibkr.supervisor"
LABEL_WATCHDOG = "com.ibkr.watchdog"
LABEL_GATEWAY = "com.ibkr.gateway"
ALL_LABELS = (LABEL_SUPERVISOR, LABEL_WATCHDOG, LABEL_GATEWAY)


def render_plists(
    repo: Path, python: Path, *, with_gateway: bool, watchdog_interval: int
) -> dict[str, bytes]:
    """Build every launchd agent plist as bytes, keyed by label.

    Pure — no filesystem writes, no launchctl calls. ``repo``/``python`` are taken exactly
    as given (never resolved), so the caller controls whether a symlink chain gets followed
    — see the module docstring for why the CLI passes the *unresolved* venv python path.
    """
    repo = Path(repo)
    python = Path(python)
    logs = repo / "logs"

    supervisor: dict[str, object] = {
        "Label": LABEL_SUPERVISOR,
        "ProgramArguments": [
            "/usr/bin/caffeinate",
            "-i",
            "-s",
            str(python),
            "-m",
            "scripts.start",
        ],
        "WorkingDirectory": str(repo),
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 30,
        "StandardOutPath": str(logs / "launchd-supervisor.log"),
        "StandardErrorPath": str(logs / "launchd-supervisor.log"),
        # So `ollama` resolves inside scripts.start's startup probe (probe_ollama()) —
        # launchd's own default PATH doesn't include Homebrew's bin dirs.
        "EnvironmentVariables": {
            "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        },
    }

    watchdog: dict[str, object] = {
        "Label": LABEL_WATCHDOG,
        "ProgramArguments": [str(python), "-m", "scripts.watchdog"],
        "WorkingDirectory": str(repo),
        "RunAtLoad": True,
        "StartInterval": watchdog_interval,
        "StandardOutPath": str(logs / "watchdog.log"),
        "StandardErrorPath": str(logs / "watchdog.log"),
    }

    out = {
        LABEL_SUPERVISOR: plistlib.dumps(supervisor),
        LABEL_WATCHDOG: plistlib.dumps(watchdog),
    }

    if with_gateway:
        gateway: dict[str, object] = {
            "Label": LABEL_GATEWAY,
            "ProgramArguments": [str(repo / "scripts" / "ibc" / "start_gateway.sh")],
            "WorkingDirectory": str(repo),
            "RunAtLoad": True,
            # IBC owns Gateway's own restart cycle — launchd restarting the wrapper over
            # IBC's back would fight it.
            "KeepAlive": False,
            "StandardOutPath": str(logs / "launchd-gateway.log"),
            "StandardErrorPath": str(logs / "launchd-gateway.log"),
        }
        out[LABEL_GATEWAY] = plistlib.dumps(gateway)

    return out


# --- launchctl plumbing -----------------------------------------------------------------


def _plist_path(label: str) -> Path:
    return LAUNCH_AGENTS_DIR / f"{label}.plist"


def _gui_domain() -> str:
    return f"gui/{os.getuid()}"


def _gui_target(label: str) -> str:
    return f"{_gui_domain()}/{label}"


def _is_loaded(label: str) -> bool:
    r = subprocess.run(
        ["launchctl", "print", _gui_target(label)], capture_output=True, text=True
    )
    return r.returncode == 0


def _bootout(label: str) -> None:
    # Idempotent from the caller's point of view: bootout-ing a label that isn't loaded
    # just fails quietly (non-zero exit), which every caller here already ignores.
    subprocess.run(["launchctl", "bootout", _gui_target(label)], capture_output=True, text=True)


def _bootstrap(label: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["launchctl", "bootstrap", _gui_domain(), str(_plist_path(label))],
        capture_output=True,
        text=True,
    )


def _installed_labels() -> list[str]:
    return [label for label in ALL_LABELS if _plist_path(label).exists()]


# --- subcommands -------------------------------------------------------------------------


def cmd_install(args: argparse.Namespace) -> int:
    from src.common.config import get_config

    python = REPO_ROOT / ".venv" / "bin" / "python"
    interval = get_config().watchdog.interval_seconds
    plists = render_plists(
        REPO_ROOT, python, with_gateway=args.with_gateway, watchdog_interval=interval
    )

    LAUNCH_AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    (REPO_ROOT / "logs").mkdir(parents=True, exist_ok=True)

    ok = True
    for label, data in plists.items():
        path = _plist_path(label)
        path.write_bytes(data)
        if _is_loaded(label):
            _bootout(label)
        r = _bootstrap(label)
        if r.returncode != 0:
            ok = False
            print(f"install {label}: FAILED — {r.stderr.strip()}", file=sys.stderr)
        else:
            print(f"install {label}: ok ({path})")
    return 0 if ok else 1


def cmd_uninstall(args: argparse.Namespace) -> int:
    labels = _installed_labels()
    if not labels:
        print("No launchd agents installed.")
        return 0
    for label in labels:
        _bootout(label)
        _plist_path(label).unlink(missing_ok=True)
        print(f"uninstall {label}: ok")
    return 0


def cmd_start(args: argparse.Namespace) -> int:
    labels = _installed_labels()
    if not labels:
        print("No launchd agents installed. Run `./ibkr install` first.", file=sys.stderr)
        return 1
    ok = True
    for label in labels:
        r = subprocess.run(
            ["launchctl", "kickstart", "-k", _gui_target(label)],
            capture_output=True,
            text=True,
        )
        if r.returncode == 0:
            print(f"start {label}: ok")
            continue
        # kickstart requires the job to already be loaded — a prior `stop` bootout's it
        # out of launchd entirely, so fall back to re-bootstrapping the on-disk plist
        # `install` wrote; RunAtLoad then starts it immediately.
        r2 = _bootstrap(label)
        if r2.returncode == 0:
            print(f"start {label}: ok (reloaded)")
        else:
            ok = False
            print(f"start {label}: FAILED — {r2.stderr.strip()}", file=sys.stderr)
    return 0 if ok else 1


def cmd_stop(args: argparse.Namespace) -> int:
    labels = _installed_labels()
    if not labels:
        print("No launchd agents installed.")
        return 0
    for label in labels:
        _bootout(label)
        print(f"stop {label}: ok")
    return 0


_STATE_RE = re.compile(r"^\s*state\s*=\s*(\S+)", re.MULTILINE)
_PID_RE = re.compile(r"^\s*pid\s*=\s*(\d+)", re.MULTILINE)


def _parse_launchctl_print(output: str) -> tuple[str, str | None]:
    """Pull ``state`` and ``pid`` out of ``launchctl print``'s free-form block output.

    Returns ``("unknown", None)`` if the output doesn't look like a print block at all
    (e.g. launchctl itself errored) rather than raising — ``status`` is a best-effort
    diagnostic, never something that should crash on an unexpected launchctl version's
    output format.
    """
    m_state = _STATE_RE.search(output)
    m_pid = _PID_RE.search(output)
    state = m_state.group(1) if m_state else "unknown"
    pid = m_pid.group(1) if m_pid else None
    return state, pid


def cmd_status(args: argparse.Namespace) -> int:
    labels = _installed_labels()
    if not labels:
        print("No launchd agents installed. Run `./ibkr install` first.")
    for label in labels:
        r = subprocess.run(
            ["launchctl", "print", _gui_target(label)], capture_output=True, text=True
        )
        if r.returncode != 0:
            print(f"{label}: not loaded")
            continue
        state, pid = _parse_launchctl_print(r.stdout)
        pid_str = f" pid={pid}" if pid else ""
        print(f"{label}: {state}{pid_str}")

    print()
    print("Health checks:")
    try:
        from src.common.config import get_config
        from src.ops.watchdog import run_checks

        cfg = get_config().watchdog
        checks = run_checks(datetime.now(UTC), cfg)
        for c in checks:
            mark = "OK" if c.ok else "FAIL"
            detail = f" — {c.detail}" if c.detail else ""
            print(f"  [{mark}] {c.name}{detail}")
    except Exception as exc:  # best-effort diagnostic — status must never crash on this
        print(f"  (health checks unavailable: {exc})")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="scripts.launchd", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)

    p_install = sub.add_parser("install", help="Write + load every launchd agent plist")
    p_install.add_argument(
        "--with-gateway",
        action="store_true",
        help="Also install com.ibkr.gateway (IB Gateway via IBC)",
    )
    p_install.set_defaults(func=cmd_install)

    sub.add_parser("uninstall", help="Unload + delete every installed agent plist").set_defaults(
        func=cmd_uninstall
    )
    sub.add_parser("start", help="(Re)start every installed agent").set_defaults(func=cmd_start)
    sub.add_parser("stop", help="Stop every installed agent").set_defaults(func=cmd_stop)
    sub.add_parser(
        "status", help="Show agent state/pid plus the watchdog's own health checks"
    ).set_defaults(func=cmd_status)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
