"""src/api/settings_read.py — the shared system_settings reader both /options/controls
and /system/status use."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.api.settings_read import parse_setting_dt, read_setting


@pytest.fixture
def trading_db_session(monkeypatch, tmp_path):
    import src.storage.db as dbmod
    from src.common.config import Config

    trading_db = tmp_path / "settings_read.db"
    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{trading_db}")
    dbmod.init_db()

    monkeypatch.setattr("src.api.trading_db._engine", None)
    monkeypatch.setattr("src.api.trading_db._SessionLocal", None)
    monkeypatch.setattr("src.api.trading_db._resolve_path", lambda: trading_db.as_posix())

    from src.storage.models import SystemSettingRow

    with dbmod.session_scope() as s:
        s.add(SystemSettingRow(key="known_key", value="hello"))

    from src.api.trading_db import trading_session

    with trading_session() as session:
        yield session


def test_read_setting_returns_the_stored_value(trading_db_session) -> None:
    assert read_setting(trading_db_session, "known_key") == "hello"


def test_read_setting_returns_none_for_an_unknown_key(trading_db_session) -> None:
    assert read_setting(trading_db_session, "no_such_key") is None


def test_parse_setting_dt_returns_none_for_none() -> None:
    assert parse_setting_dt(None) is None


def test_parse_setting_dt_returns_none_for_empty_string() -> None:
    assert parse_setting_dt("") is None


def test_parse_setting_dt_returns_none_for_garbage() -> None:
    assert parse_setting_dt("not-a-date") is None


def test_parse_setting_dt_parses_an_iso_timestamp_as_utc() -> None:
    raw = datetime(2026, 9, 23, 12, 0, 0, tzinfo=UTC).isoformat()
    parsed = parse_setting_dt(raw)
    assert parsed is not None
    assert parsed.tzinfo is not None
    assert parsed.year == 2026
    assert parsed.month == 9
    assert parsed.day == 23
