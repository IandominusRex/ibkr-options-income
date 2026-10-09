from __future__ import annotations

from datetime import UTC, datetime, timedelta

NOW = datetime(2026, 10, 14, 15, tzinfo=UTC)


def test_news_check_fresh_and_stale(news_db) -> None:
    from src.news.store.state import touch_heartbeat
    from src.ops.watchdog import news_check

    touch_heartbeat(NOW - timedelta(minutes=5))
    assert news_check(NOW, max_age_min=30).ok
    touch_heartbeat(NOW - timedelta(minutes=45))
    c = news_check(NOW, max_age_min=30)
    assert not c.ok and "45" in c.detail


def test_news_check_when_db_missing(tmp_path, monkeypatch) -> None:
    from src.news.store import readonly
    from src.ops.watchdog import news_check

    readonly.reset_engine()
    monkeypatch.setattr(readonly, "_resolve_path", lambda: str(tmp_path / "absent.db"))
    c = news_check(NOW, max_age_min=30)
    assert not c.ok and "missing" in c.detail


def _run_checks(monkeypatch, *, enabled: bool):
    from src.common.config import get_config
    from src.ops import watchdog
    from src.ops.watchdog import Check

    monkeypatch.setattr(watchdog, "supervisor_check", lambda: Check("supervisor", True, ""))
    monkeypatch.setattr(watchdog, "port_check", lambda port: Check("gateway_port", True, ""))
    monkeypatch.setattr(watchdog, "get_setting", lambda key, default="": "")
    monkeypatch.setattr(watchdog, "is_rth", lambda now: False)
    monkeypatch.setattr(watchdog, "iv_history_check", lambda now, n: Check("iv_history", True, ""))
    monkeypatch.setattr(watchdog, "eod_check", lambda *a, **k: Check("eod", True, ""))
    full = get_config()
    monkeypatch.setattr(full.news, "enabled", enabled)
    monkeypatch.setattr(full.watchdog, "news_max_age_minutes", 30)
    return {c.name: c for c in watchdog.run_checks(NOW, full.watchdog)}


def test_run_checks_reads_the_news_heartbeat_with_the_configured_limit(
    news_db, monkeypatch
) -> None:
    from src.news.store.state import touch_heartbeat

    touch_heartbeat(NOW - timedelta(minutes=45))
    news = _run_checks(monkeypatch, enabled=True)["news"]
    assert not news.ok and "limit 30" in news.detail


def test_run_checks_skips_news_when_the_service_is_disabled(monkeypatch) -> None:
    assert "news" not in _run_checks(monkeypatch, enabled=False)


def test_news_check_when_db_unreadable(tmp_path, monkeypatch) -> None:
    """A news.db that opens but cannot answer (no schema yet, locked) is a failed check, never
    an exception that would take every other watchdog check down with it."""
    import sqlite3

    from src.news.store import readonly
    from src.ops.watchdog import news_check

    path = tmp_path / "empty.db"
    sqlite3.connect(path).close()
    readonly.reset_engine()
    monkeypatch.setattr(readonly, "_resolve_path", lambda: str(path))
    c = news_check(NOW, max_age_min=30)
    assert not c.ok and c.name == "news" and "cannot read" in c.detail
