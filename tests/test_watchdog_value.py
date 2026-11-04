"""The watchdog checks the value book's nightly run (Part 6, ruling 15). Out of process: it reads
value.db through ``src.common.value_view`` only, never ``src.value``."""

from __future__ import annotations

from datetime import UTC, date, datetime

from src.ops import watchdog
from src.ops.watchdog import Check
from src.value.store import ValueRunRow, value_session

# Wednesday 2026-11-04, 13:00 ET (EST). With a 26 hour grace the newest close a night must
# follow is Monday's (16:00 ET = 21:00 UTC); Tuesday's close + 26 h is still ahead.
NOW = datetime(2026, 11, 4, 18, 0, tzinfo=UTC)


def _run(finished: datetime | None, *, kind: str = "nightly") -> None:
    with value_session() as vs:
        vs.add(
            ValueRunRow(
                kind=kind,
                started_at=datetime(2026, 11, 1, 10, 0),
                finished_at=finished,
                as_of=date(2026, 11, 3),
                ruleset_version="v4",
                ruleset_hash="be30d1eaa915",
            )
        )


def test_ok_when_the_newest_night_finished_after_the_last_close(value_book_db) -> None:
    _run(datetime(2026, 11, 4, 11, 30))  # this morning's, for Tuesday's session
    c = watchdog.value_check(NOW, grace_hours=26, expected=True)
    assert c is not None and c.ok and c.name == "value"
    # a night that last ran after Monday's close but before Tuesday's is still on time
    with value_session() as vs:
        vs.query(ValueRunRow).delete()
    _run(datetime(2026, 11, 3, 11, 0))
    c = watchdog.value_check(NOW, grace_hours=26, expected=True)
    assert c is not None and c.ok


def test_alert_when_the_last_run_is_two_sessions_old(value_book_db) -> None:
    _run(datetime(2026, 10, 30, 11, 0))  # Friday's morning: Monday's night never ran
    _run(datetime(2026, 11, 4, 9, 0), kind="dry_run")  # a dry run is not a night
    c = watchdog.value_check(NOW, grace_hours=26, expected=True)
    assert c is not None and not c.ok and c.name == "value"
    assert c.detail.startswith("value: ") and "nightly run" in c.detail and "5d" in c.detail


def test_never_ran_message_on_a_missing_value_db(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("src.common.value_view._path", lambda: tmp_path / "absent.db")
    c = watchdog.value_check(NOW, grace_hours=26, expected=True)
    assert c == Check("value", False, "value: data/value.db missing - the value service never ran")


def test_not_expected_means_no_check_at_all(value_book_db, monkeypatch) -> None:
    assert watchdog.value_check(NOW, grace_hours=26, expected=False) is None
    # run_checks: appended after the news check only while the private value.yaml exists
    from src.common.config import get_config

    monkeypatch.setattr(watchdog, "supervisor_check", lambda: Check("supervisor", True, ""))
    monkeypatch.setattr(watchdog, "port_check", lambda port: Check("gateway_port", True, ""))
    monkeypatch.setattr(watchdog, "get_setting", lambda key, default="": "")
    monkeypatch.setattr(watchdog, "is_rth", lambda now: False)
    monkeypatch.setattr(watchdog, "iv_history_check", lambda now, n: Check("iv_history", True, ""))
    monkeypatch.setattr(watchdog, "eod_check", lambda *a, **k: Check("eod", True, ""))
    monkeypatch.setattr(watchdog, "news_check", lambda now, max_age_min: Check("news", True, ""))
    cfg = get_config().watchdog
    monkeypatch.setattr(watchdog, "value_expected", lambda: False)
    assert "value" not in [c.name for c in watchdog.run_checks(NOW, cfg)]
    monkeypatch.setattr(watchdog, "value_expected", lambda: True)
    names = [c.name for c in watchdog.run_checks(NOW, cfg)]
    assert names.index("value") == names.index("news") + 1
