"""Tests for scripts/launchd.py — plist rendering + the small parsing helpers the
`status` subcommand uses.

`render_plists` is pure (no launchctl, no filesystem writes) so it's fully unit-testable;
the subprocess-driving `cmd_*` handlers (install/uninstall/start/stop/status) are exercised
live in Task 6's manual verification, the same way scripts/start.py's own supervision loop
is — see tests/test_start_launcher.py for the parallel (parser + pure-function tests only,
no mocked subprocess plumbing).
"""

from __future__ import annotations

import plistlib
from pathlib import Path

from scripts.launchd import render_plists


def test_render_supervisor_and_watchdog(tmp_path):
    out = render_plists(tmp_path, tmp_path / ".venv/bin/python", with_gateway=False,
                        watchdog_interval=300)
    assert set(out) == {"com.ibkr.supervisor", "com.ibkr.watchdog"}
    sup = plistlib.loads(out["com.ibkr.supervisor"])
    assert sup["KeepAlive"] is True and sup["RunAtLoad"] is True
    assert sup["ProgramArguments"][:3] == ["/usr/bin/caffeinate", "-i", "-s"]
    assert sup["ProgramArguments"][-2:] == ["-m", "scripts.start"]
    assert sup["WorkingDirectory"] == str(tmp_path)
    wd = plistlib.loads(out["com.ibkr.watchdog"])
    assert wd["StartInterval"] == 300 and wd["ProgramArguments"][-1] == "scripts.watchdog"


def test_render_with_gateway_is_opt_in(tmp_path):
    out = render_plists(tmp_path, tmp_path / "py", with_gateway=True, watchdog_interval=300)
    gw = plistlib.loads(out["com.ibkr.gateway"])
    assert gw["KeepAlive"] is False
    assert gw["ProgramArguments"][0].endswith("scripts/ibc/start_gateway.sh")


def test_control_script_exists_and_is_executable():
    p = Path(__file__).resolve().parents[1] / "ibkr"
    assert p.exists() and p.stat().st_mode & 0o111


# --- Additional coverage beyond the brief's three tests -------------------------------


def test_render_supervisor_throttle_and_workingdir_for_watchdog(tmp_path):
    out = render_plists(tmp_path, tmp_path / ".venv/bin/python", with_gateway=False,
                        watchdog_interval=300)
    sup = plistlib.loads(out["com.ibkr.supervisor"])
    assert sup["ThrottleInterval"] == 30
    wd = plistlib.loads(out["com.ibkr.watchdog"])
    assert wd["WorkingDirectory"] == str(tmp_path)
    assert wd["RunAtLoad"] is True


def test_render_supervisor_path_includes_homebrew_bins(tmp_path):
    out = render_plists(tmp_path, tmp_path / ".venv/bin/python", with_gateway=False,
                        watchdog_interval=300)
    sup = plistlib.loads(out["com.ibkr.supervisor"])
    path = sup["EnvironmentVariables"]["PATH"]
    assert "/opt/homebrew/bin" in path
    assert "/usr/local/bin" in path


def test_render_gateway_worksdir_and_runatload(tmp_path):
    out = render_plists(tmp_path, tmp_path / "py", with_gateway=True, watchdog_interval=60)
    gw = plistlib.loads(out["com.ibkr.gateway"])
    assert gw["WorkingDirectory"] == str(tmp_path)
    assert gw["RunAtLoad"] is True


def test_build_parser_install_with_gateway_flag():
    from scripts.launchd import _build_parser

    parser = _build_parser()
    args = parser.parse_args(["install", "--with-gateway"])
    assert args.with_gateway is True
    args2 = parser.parse_args(["install"])
    assert args2.with_gateway is False


def test_build_parser_dispatches_every_subcommand():
    from scripts.launchd import (
        _build_parser,
        cmd_install,
        cmd_start,
        cmd_status,
        cmd_stop,
        cmd_uninstall,
    )

    parser = _build_parser()
    assert parser.parse_args(["install"]).func is cmd_install
    assert parser.parse_args(["uninstall"]).func is cmd_uninstall
    assert parser.parse_args(["start"]).func is cmd_start
    assert parser.parse_args(["stop"]).func is cmd_stop
    assert parser.parse_args(["status"]).func is cmd_status


def test_parse_launchctl_print_running_with_pid():
    from scripts.launchd import _parse_launchctl_print

    sample = """
    com.ibkr.supervisor = {
        active count = 1
        path = /Users/ianlim/Library/LaunchAgents/com.ibkr.supervisor.plist
        state = running

        program = /usr/bin/caffeinate
        arguments = {
        }

        pid = 12345
        immediate reason = something
    }
    """
    state, pid = _parse_launchctl_print(sample)
    assert state == "running"
    assert pid == "12345"


def test_parse_launchctl_print_waiting_has_no_pid():
    from scripts.launchd import _parse_launchctl_print

    sample = """
    com.ibkr.watchdog = {
        active count = 0
        state = waiting
    }
    """
    state, pid = _parse_launchctl_print(sample)
    assert state == "waiting"
    assert pid is None


def test_parse_launchctl_print_unparseable_defaults_to_unknown():
    from scripts.launchd import _parse_launchctl_print

    state, pid = _parse_launchctl_print("garbage output, no such service")
    assert state == "unknown"
    assert pid is None
