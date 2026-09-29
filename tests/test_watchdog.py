"""Tests for the out-of-process watchdog (src/ops/watchdog.py).

Every check is a pure function over its inputs (heartbeat ISO strings, RTH/trading-day
booleans, a fixed ``now``) so it is testable without a DB or IBKR connection — the whole
point of this module is that it must keep working when everything else in the stack is
already broken.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from src.ops.watchdog import (
    Check,
    decide_alerts,
    eod_check,
    heartbeat_check,
    iv_history_check,
    scan_loop_check,
)

_ET = ZoneInfo("America/New_York")

NOW = datetime(2026, 9, 29, 15, 0, tzinfo=UTC)  # 11:00 ET, a Tuesday


def test_heartbeat_check_fails_when_stale():
    c = heartbeat_check("monitor", (NOW - timedelta(minutes=30)).isoformat(), NOW, max_age_min=10)
    assert c.ok is False and "30 min" in c.detail


def test_heartbeat_check_fails_when_missing():
    assert heartbeat_check("monitor", None, NOW, max_age_min=10).ok is False


def test_heartbeat_check_ok_when_fresh():
    c = heartbeat_check("monitor", (NOW - timedelta(minutes=2)).isoformat(), NOW, max_age_min=10)
    assert c.ok is True


def test_scan_loop_check_only_applies_in_rth():
    stale = (NOW - timedelta(hours=3)).isoformat()
    assert (
        scan_loop_check(
            stale, NOW, in_rth=True, minutes_since_open=90, max_age_min=35, grace_min=20
        ).ok
        is False
    )
    assert (
        scan_loop_check(
            stale, NOW, in_rth=False, minutes_since_open=0, max_age_min=35, grace_min=20
        ).ok
        is True
    )
    assert (
        scan_loop_check(
            stale, NOW, in_rth=True, minutes_since_open=10, max_age_min=35, grace_min=20
        ).ok
        is True
    )  # inside the post-open grace window


def test_scan_loop_check_ok_when_fresh_in_rth():
    fresh = (NOW - timedelta(minutes=5)).isoformat()
    c = scan_loop_check(
        fresh, NOW, in_rth=True, minutes_since_open=90, max_age_min=35, grace_min=20
    )
    assert c.ok is True


def test_decide_alerts_transition_realert_and_recovery():
    # decide_alerts is pure: it returns (alerts, candidate_state) where candidate_state is what
    # each check's state *would* become if every alert this cycle is actually delivered. These
    # tests simulate every send succeeding (main()'s job to only commit on real success is
    # covered separately below), so chaining `state = candidate_state` between cycles here
    # mirrors what main() would persist after a successful send.
    fail = [Check("scan_loop", False, "no completed scan for 40 min")]
    alerts, state = decide_alerts(fail, {}, NOW, realert_minutes=60)
    assert len(alerts) == 1
    name, msg = alerts[0]
    assert name == "scan_loop" and "scan_loop" in msg
    alerts, state = decide_alerts(fail, state, NOW + timedelta(minutes=10), realert_minutes=60)
    assert alerts == []  # still failing, inside the re-alert window
    alerts, state = decide_alerts(fail, state, NOW + timedelta(minutes=61), realert_minutes=60)
    assert len(alerts) == 1
    ok = [Check("scan_loop", True, "")]
    alerts, state = decide_alerts(ok, state, NOW + timedelta(minutes=70), realert_minutes=60)
    assert len(alerts) == 1 and "recovered" in alerts[0][1]


def test_decide_alerts_no_message_while_check_stays_ok():
    ok = [Check("scan_loop", True, "")]
    alerts, state = decide_alerts(ok, {}, NOW, realert_minutes=60)
    assert alerts == []
    alerts, state = decide_alerts(ok, state, NOW + timedelta(minutes=5), realert_minutes=60)
    assert alerts == []


def test_decide_alerts_state_round_trips_through_json():
    fail = [Check("gateway_port", False, "gateway_port: unreachable")]
    _, state = decide_alerts(fail, {}, NOW, realert_minutes=60)
    reloaded = json.loads(json.dumps(state))
    alerts, _ = decide_alerts(fail, reloaded, NOW + timedelta(minutes=5), realert_minutes=60)
    assert alerts == []  # still inside the re-alert window after a JSON round trip


def test_decide_alerts_iv_history_realerts_once_per_et_day_not_hourly():
    """Controller ruling, review round 1, finding 2: iv_history's brief entry says "evaluated
    once per day" — the shared realert_minutes (default 60) would otherwise re-fire it roughly
    hourly. Two failing cycles an hour+ apart on the same ET day must produce only the first
    alert; the next ET day must produce a new one. Every other check keeps the realert_minutes
    cadence (covered by test_decide_alerts_transition_realert_and_recovery above)."""
    fail = [Check("iv_history", False, "iv_history: stale/missing IV — AAPL(missing)")]
    alerts, state = decide_alerts(fail, {}, NOW, realert_minutes=60)
    assert len(alerts) == 1  # ok -> fail always alerts

    # More than realert_minutes later (2h), but the same ET calendar day: no second alert.
    alerts, state = decide_alerts(fail, state, NOW + timedelta(hours=2), realert_minutes=60)
    assert alerts == []
    # Still later, still the same ET day: still nothing.
    alerts, state = decide_alerts(fail, state, NOW + timedelta(hours=8), realert_minutes=60)
    assert alerts == []

    # The next ET calendar day: alerts again.
    alerts, state = decide_alerts(fail, state, NOW + timedelta(days=1), realert_minutes=60)
    assert len(alerts) == 1
    assert alerts[0][0] == "iv_history"


def test_send_telegram_uses_plain_text(monkeypatch):
    from src.ops import watchdog

    sent = {}

    class _Resp:
        status_code = 200

    def fake_post(url, json, timeout):
        sent.update(json)
        return _Resp()

    monkeypatch.setattr(watchdog.httpx, "post", fake_post)
    monkeypatch.setattr(watchdog, "_telegram_target", lambda: ("TOKEN", "CHAT", "2"))
    assert watchdog.send_telegram("hello (world).") is True
    assert "parse_mode" not in sent and sent["text"].startswith("🐕")


# ---------------------------------------------------------------------------
# eod_check — Task 5 addition (moved from Task 4b's controller ruling).
#
# 2026-09-29 is a Tuesday (a regular trading day); due = 16:15 ET + 90 min grace = 17:45 ET.
# ---------------------------------------------------------------------------

_TRADING_DAY = datetime(2026, 9, 29, 17, 0, tzinfo=_ET)  # before the 17:45 due time
_AFTER_DUE = datetime(2026, 9, 29, 18, 0, tzinfo=_ET)  # after the 17:45 due time
_WEEKEND = datetime(2026, 9, 26, 20, 0, tzinfo=_ET)  # Saturday, long after any due time


def test_eod_check_ok_before_due_time():
    c = eod_check(None, _TRADING_DAY, "16:15", 90)
    assert c.ok is True


def test_eod_check_fails_after_due_when_missing():
    c = eod_check(None, _AFTER_DUE, "16:15", 90)
    assert c.ok is False


def test_eod_check_fails_after_due_when_stale():
    yesterday_iso = datetime(2026, 9, 28, 20, 20, tzinfo=UTC).isoformat()
    c = eod_check(yesterday_iso, _AFTER_DUE, "16:15", 90)
    assert c.ok is False


def test_eod_check_ok_after_due_with_todays_key():
    today_iso = datetime(2026, 9, 29, 16, 20, tzinfo=UTC).isoformat()  # 12:20 ET, same ET date
    c = eod_check(today_iso, _AFTER_DUE, "16:15", 90)
    assert c.ok is True


def test_eod_check_ok_on_non_trading_day_regardless_of_time():
    c = eod_check(None, _WEEKEND, "16:15", 90)
    assert c.ok is True


# ---------------------------------------------------------------------------
# iv_history_check
# ---------------------------------------------------------------------------


def test_iv_history_check_ok_when_no_symbols(monkeypatch):
    from src.ops import watchdog

    monkeypatch.setattr(watchdog, "_universe_symbols", lambda: set())
    monkeypatch.setattr(watchdog, "_held_symbols", lambda: set())
    c = iv_history_check(NOW, 3)
    assert c.ok is True


def test_iv_history_check_fails_and_lists_stale_symbols(monkeypatch):
    from src.ops import watchdog

    monkeypatch.setattr(watchdog, "_universe_symbols", lambda: {"AAPL", "MSFT"})
    monkeypatch.setattr(watchdog, "_held_symbols", lambda: set())
    monkeypatch.setattr(
        watchdog,
        "latest_obs_dates",
        lambda symbols: {"AAPL": (NOW - timedelta(days=10)).date()},  # MSFT missing entirely
    )
    c = iv_history_check(NOW, 3)
    assert c.ok is False
    assert "AAPL" in c.detail and "MSFT" in c.detail


def test_iv_history_check_ok_when_fresh(monkeypatch):
    from src.ops import watchdog

    monkeypatch.setattr(watchdog, "_universe_symbols", lambda: {"AAPL"})
    monkeypatch.setattr(watchdog, "_held_symbols", lambda: set())
    monkeypatch.setattr(watchdog, "latest_obs_dates", lambda symbols: {"AAPL": NOW.date()})
    c = iv_history_check(NOW, 3)
    assert c.ok is True


# ---------------------------------------------------------------------------
# run_checks / main — composition and the alert-write side effect. Everything that would
# hit a real process, socket, or DB is monkeypatched; the live smoke test covers the rest.
# ---------------------------------------------------------------------------


def test_run_checks_composes_all_seven_checks_and_gates_monitor_outside_rth(monkeypatch):
    from src.common.config import get_config
    from src.ops import watchdog

    monkeypatch.setattr(watchdog, "supervisor_check", lambda: Check("supervisor", True, ""))
    monkeypatch.setattr(watchdog, "port_check", lambda port: Check("gateway_port", True, ""))
    monkeypatch.setattr(watchdog, "get_setting", lambda key, default="": "")
    monkeypatch.setattr(watchdog, "is_rth", lambda now: False)
    monkeypatch.setattr(watchdog, "iv_history_check", lambda now, n: Check("iv_history", True, ""))
    monkeypatch.setattr(watchdog, "eod_check", lambda *a, **k: Check("eod", True, ""))

    cfg = get_config().watchdog
    checks = watchdog.run_checks(NOW, cfg)

    names = [c.name for c in checks]
    assert names == [
        "supervisor",
        "gateway_port",
        "command_drain",
        "monitor",
        "scan_loop",
        "eod",
        "iv_history",
    ]
    monitor = next(c for c in checks if c.name == "monitor")
    assert monitor.ok is True  # outside RTH the monitor heartbeat is never checked
    scan_loop = next(c for c in checks if c.name == "scan_loop")
    assert scan_loop.ok is True  # scan_loop_check itself no-ops outside RTH


def test_main_writes_state_and_sends_telegram_for_a_failing_check(monkeypatch, tmp_path):
    from src.ops import watchdog

    state_path = tmp_path / "watchdog_state.json"
    monkeypatch.setattr(watchdog, "STATE_PATH", state_path)
    monkeypatch.setattr(
        watchdog,
        "run_checks",
        lambda now, cfg: [Check("supervisor", False, "supervisor: scripts.start is not running")],
    )
    sent = []
    monkeypatch.setattr(watchdog, "send_telegram", lambda text: sent.append(text) or True)

    rc = watchdog.main()

    assert rc == 0
    assert len(sent) == 1 and "supervisor" in sent[0]
    saved = json.loads(state_path.read_text())
    assert saved["supervisor"]["failing"] is True


def test_main_pings_deadman_url_only_when_every_check_passes(monkeypatch, tmp_path):
    from src.common.config import get_config
    from src.ops import watchdog

    state_path = tmp_path / "watchdog_state.json"
    monkeypatch.setattr(watchdog, "STATE_PATH", state_path)
    monkeypatch.setattr(watchdog, "run_checks", lambda now, cfg: [Check("supervisor", True, "")])

    pinged = []
    monkeypatch.setattr(watchdog.httpx, "get", lambda url, timeout: pinged.append(url))

    get_config.cache_clear()
    cfg = get_config()
    cfg.watchdog.deadman_url = "https://example.invalid/ping/abc"
    try:
        rc = watchdog.main()
    finally:
        get_config.cache_clear()

    assert rc == 0
    assert pinged == ["https://example.invalid/ping/abc"]


def test_main_does_not_persist_last_alert_when_telegram_send_fails(monkeypatch, tmp_path):
    """Controller ruling, review round 1, finding 1: an unsent alert must not be recorded as
    sent. If send_telegram returns False, that check's state must stay exactly as it was
    before this cycle, so the very next cycle (not realert_minutes later) tries again."""
    from src.ops import watchdog

    state_path = tmp_path / "watchdog_state.json"
    monkeypatch.setattr(watchdog, "STATE_PATH", state_path)
    monkeypatch.setattr(
        watchdog,
        "run_checks",
        lambda now, cfg: [Check("supervisor", False, "supervisor: scripts.start is not running")],
    )
    monkeypatch.setattr(watchdog, "send_telegram", lambda text: False)

    rc1 = watchdog.main()
    assert rc1 == 0
    saved1 = json.loads(state_path.read_text())
    # Nothing was ever actually delivered, so nothing was committed for this check.
    assert saved1.get("supervisor", {}) == {}

    # Next cycle: still failing, and still nothing was ever successfully delivered — this must
    # alert immediately (not wait out realert_minutes), since there is nothing to "re"-alert.
    sent = []
    monkeypatch.setattr(watchdog, "send_telegram", lambda text: sent.append(text) or True)
    rc2 = watchdog.main()
    assert rc2 == 0
    assert len(sent) == 1 and "supervisor" in sent[0]
    saved2 = json.loads(state_path.read_text())
    assert saved2["supervisor"]["failing"] is True
    assert "last_alert" in saved2["supervisor"]  # now actually recorded as delivered


def test_main_keeps_failing_state_when_recovery_send_fails(monkeypatch, tmp_path):
    """The recovery ("recovered") message is subject to the same delivered-or-it-didn't-happen
    rule: if the recovery notice fails to send, the check must stay marked failing so the
    recovery is retried, rather than silently going quiet."""
    from src.ops import watchdog

    state_path = tmp_path / "watchdog_state.json"
    state_path.write_text(
        json.dumps({"supervisor": {"failing": True, "last_alert": NOW.isoformat()}})
    )
    monkeypatch.setattr(watchdog, "STATE_PATH", state_path)
    monkeypatch.setattr(watchdog, "run_checks", lambda now, cfg: [Check("supervisor", True, "")])
    monkeypatch.setattr(watchdog, "send_telegram", lambda text: False)

    rc = watchdog.main()

    assert rc == 0
    saved = json.loads(state_path.read_text())
    # The recovery notice never actually sent, so the check must still read as failing.
    assert saved["supervisor"]["failing"] is True


def test_main_never_raises_and_alerts_on_crash(monkeypatch, tmp_path):
    from src.ops import watchdog

    monkeypatch.setattr(watchdog, "STATE_PATH", tmp_path / "watchdog_state.json")

    def boom(now, cfg):
        raise RuntimeError("boom")

    monkeypatch.setattr(watchdog, "run_checks", boom)
    sent = []
    monkeypatch.setattr(watchdog, "send_telegram", lambda text: sent.append(text) or True)

    rc = watchdog.main()

    assert rc == 1
    assert len(sent) == 1 and "watchdog crashed" in sent[0]
