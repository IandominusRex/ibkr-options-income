"""Tests for scripts/launchd.py — plist rendering + the small parsing helpers the
`status` subcommand uses.

`render_plists` is pure (no launchctl, no filesystem writes) so it's fully unit-testable;
the subprocess-driving `cmd_*` handlers (install/uninstall/start/stop/status) are exercised
live in Task 6's manual verification (which labels start/stop/uninstall touch is pinned below
against a fake `launchctl`, final review I3), the same way scripts/start.py's own supervision loop
is — see tests/test_start_launcher.py for the parallel (parser + pure-function tests only,
no mocked subprocess plumbing).
"""

from __future__ import annotations

import plistlib
from pathlib import Path

from scripts.launchd import render_plists


def test_render_supervisor_and_watchdog(tmp_path):
    out = render_plists(
        tmp_path, tmp_path / ".venv/bin/python", with_gateway=False, watchdog_interval=300
    )
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
    out = render_plists(
        tmp_path, tmp_path / ".venv/bin/python", with_gateway=False, watchdog_interval=300
    )
    sup = plistlib.loads(out["com.ibkr.supervisor"])
    assert sup["ThrottleInterval"] == 30
    wd = plistlib.loads(out["com.ibkr.watchdog"])
    assert wd["WorkingDirectory"] == str(tmp_path)
    assert wd["RunAtLoad"] is True


def test_render_supervisor_path_includes_homebrew_bins(tmp_path):
    out = render_plists(
        tmp_path, tmp_path / ".venv/bin/python", with_gateway=False, watchdog_interval=300
    )
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


# --- Fix round 1: preflight (the install conflict guard) ------------------------------
#
# `./ibkr install` must refuse to run over a terminal-launched `scripts.start`, but the
# original bash-only guard only ran the check when the supervisor label wasn't already
# loaded — so a *re*-install (label already loaded from a prior `./ibkr install`) never
# caught a second, terminal-launched `scripts.start` running alongside it. The fix moves
# the decision into Python (`conflicting_scripts_start_pids`, a pure function) so it can be
# unit-tested against fake pgrep/ps/launchctl output — no real subprocess call in any test
# below.


def test_parse_pgrep_pids_basic():
    from scripts.launchd import _parse_pgrep_pids

    assert _parse_pgrep_pids("123\n456\n") == [123, 456]


def test_parse_pgrep_pids_ignores_blank_lines_and_garbage():
    from scripts.launchd import _parse_pgrep_pids

    assert _parse_pgrep_pids("\n123\n\nnotapid\n") == [123]


def test_parse_pgrep_pids_empty_output_is_no_pids():
    from scripts.launchd import _parse_pgrep_pids

    assert _parse_pgrep_pids("") == []


def test_parse_ps_ppid_map_skips_header():
    from scripts.launchd import _parse_ps_ppid_map

    text = "  PID  PPID\n   100     1\n   101   100\n   999     1\n"
    assert _parse_ps_ppid_map(text) == {100: 1, 101: 100, 999: 1}


def test_parse_ps_ppid_map_empty_output():
    from scripts.launchd import _parse_ps_ppid_map

    assert _parse_ps_ppid_map("") == {}


def test_parse_launchctl_print_job_pid_present():
    from scripts.launchd import _parse_launchctl_print_job_pid

    text = "com.ibkr.supervisor = {\n\tstate = running\n\tpid = 22138\n}\n"
    assert _parse_launchctl_print_job_pid(text) == 22138


def test_parse_launchctl_print_job_pid_absent_when_not_loaded():
    from scripts.launchd import _parse_launchctl_print_job_pid

    assert _parse_launchctl_print_job_pid("") is None
    assert _parse_launchctl_print_job_pid("Could not find service") is None


def test_descendants_multi_level_tree():
    from scripts.launchd import _descendants

    # 100 -> 101 -> 102 ; 100 -> 103 ; 999 unrelated (parented under a different pid, 1).
    ppid_map = {101: 100, 102: 101, 103: 100, 999: 1}
    assert _descendants(100, ppid_map) == {100, 101, 102, 103}


def test_descendants_leaf_pid_is_just_itself():
    from scripts.launchd import _descendants

    assert _descendants(50, {}) == {50}


def test_conflicting_pids_no_label_with_stray():
    from scripts.launchd import conflicting_scripts_start_pids

    # Supervisor label not loaded at all (job_pid=None) -- there is no launchd-managed tree
    # to exclude, so any pgrep match for "scripts.start" is a stray.
    assert conflicting_scripts_start_pids([555], None, {}) == [555]


def test_conflicting_pids_label_loaded_only_its_own_tree():
    from scripts.launchd import conflicting_scripts_start_pids

    # job pid 100 (the supervisor label's own pid per `launchctl print`) plus 101, its own
    # child (the caffeinate/python pair, in whichever direction the OS actually parents
    # them) -- both belong to the launchd-managed tree, so this is not a conflict.
    ppid_map = {101: 100}
    assert conflicting_scripts_start_pids([100, 101], 100, ppid_map) == []


def test_conflicting_pids_label_loaded_plus_a_stray():
    from scripts.launchd import conflicting_scripts_start_pids

    # Same launchd-managed tree as above, but pgrep also found a third pid (777) that is
    # NOT a descendant of the job pid -- a second, terminal-launched scripts.start running
    # alongside the (already-loaded) launchd-managed one. This is exactly the case the
    # original bash-only guard could never catch on a re-install.
    ppid_map = {101: 100}
    assert conflicting_scripts_start_pids([100, 101, 777], 100, ppid_map) == [777]


def test_build_parser_preflight_dispatches():
    from scripts.launchd import _build_parser, cmd_preflight

    parser = _build_parser()
    assert parser.parse_args(["preflight"]).func is cmd_preflight


# --- final review I3: stop/start/restart never touch the watchdog --------------------------
#
# `./ibkr stop` used to bootout every installed label, com.ibkr.watchdog included — so a
# stopped stack was exactly the state the out-of-process watchdog exists to alert on, and it
# was never running to do so. Ruling: stop/start/restart act on the supervisor (and gateway,
# if installed) only; the watchdog is loaded/unloaded solely by install/uninstall.


def _fake_launchctl(monkeypatch):
    import argparse
    import subprocess

    import scripts.launchd as launchd

    calls: list[list[str]] = []

    def fake_run(argv, *a, **k):
        calls.append(list(argv))
        # `launchctl print` fails (label not loaded) so stop's unload-wait returns at once.
        rc = 1 if argv[:2] == ["launchctl", "print"] else 0
        return subprocess.CompletedProcess(argv, rc, stdout="", stderr="")

    monkeypatch.setattr(launchd.subprocess, "run", fake_run)
    monkeypatch.setattr(
        launchd,
        "_installed_labels",
        lambda: [launchd.LABEL_SUPERVISOR, launchd.LABEL_WATCHDOG, launchd.LABEL_GATEWAY],
    )
    return launchd, calls, argparse.Namespace()


def _touched(calls: list[list[str]]) -> set[str]:
    return {arg.rsplit("/", 1)[-1] for argv in calls for arg in argv if "com.ibkr." in arg}


def test_stop_leaves_the_watchdog_loaded(monkeypatch):
    launchd, calls, ns = _fake_launchctl(monkeypatch)
    assert launchd.cmd_stop(ns) == 0
    assert all(argv[:2] in (["launchctl", "bootout"], ["launchctl", "print"]) for argv in calls)
    assert _touched(calls) == {launchd.LABEL_SUPERVISOR, launchd.LABEL_GATEWAY}


def test_start_does_not_kickstart_the_watchdog(monkeypatch):
    launchd, calls, ns = _fake_launchctl(monkeypatch)
    assert launchd.cmd_start(ns) == 0
    assert _touched(calls) == {launchd.LABEL_SUPERVISOR, launchd.LABEL_GATEWAY}


def test_uninstall_still_removes_the_watchdog(monkeypatch, tmp_path):
    launchd, calls, ns = _fake_launchctl(monkeypatch)
    monkeypatch.setattr(launchd, "LAUNCH_AGENTS_DIR", tmp_path)
    assert launchd.cmd_uninstall(ns) == 0
    assert launchd.LABEL_WATCHDOG in _touched(calls)


def test_stop_waits_until_the_label_is_actually_unloaded(monkeypatch):
    """`launchctl bootout` returns before launchd has finished tearing the job down (the
    supervisor spends up to STOP_GRACE_SECONDS stopping its daemons). `./ibkr restart` runs
    `start` straight after, and a `bootstrap` issued while the old job is still being removed
    fails with "Bootstrap failed: 5: Input/output error" — observed live during the final
    review's C1 verification (2026-09-30). `stop` must not return until the label is gone."""
    launchd, calls, ns = _fake_launchctl(monkeypatch)
    polls = {"n": 0}

    def fake_is_loaded(label):
        polls["n"] += 1
        return polls["n"] < 3  # still loaded for the first two polls

    monkeypatch.setattr(launchd, "_is_loaded", fake_is_loaded)
    monkeypatch.setattr(launchd.time, "sleep", lambda s: None)
    assert launchd.cmd_stop(ns) == 0
    assert polls["n"] >= 3


def test_stop_reports_failure_if_a_label_never_unloads(monkeypatch):
    launchd, calls, ns = _fake_launchctl(monkeypatch)
    monkeypatch.setattr(launchd, "_is_loaded", lambda label: True)
    monkeypatch.setattr(launchd, "BOOTOUT_WAIT_SECONDS", 0.0)
    monkeypatch.setattr(launchd.time, "sleep", lambda s: None)
    assert launchd.cmd_stop(ns) == 1
