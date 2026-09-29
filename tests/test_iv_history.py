"""Tests for the iv_history accessors (N4): latest IV, idempotent daily append, staleness."""

from __future__ import annotations

from datetime import date, timedelta


def _db_setup(tmp_path, monkeypatch) -> None:
    import src.storage.db as dbmod
    from src.common.config import Config

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{tmp_path / 't.db'}")
    dbmod.init_db()


def test_append_observation_is_idempotent(tmp_path, monkeypatch):
    _db_setup(tmp_path, monkeypatch)
    from src.storage.iv_history import append_observation, latest_iv

    today = date.today()
    assert append_observation("SOXL", today, 1.05) is True
    assert append_observation("SOXL", today, 1.20) is False  # same (symbol, date) → skipped
    assert latest_iv("SOXL") == 1.05  # first write wins, not clobbered
    # Non-positive IV is rejected.
    assert append_observation("SOXL", today + timedelta(days=1), 0.0) is False


def test_latest_iv_returns_most_recent(tmp_path, monkeypatch):
    _db_setup(tmp_path, monkeypatch)
    from src.storage.iv_history import append_observation, latest_iv

    today = date.today()
    append_observation("AAPL", today - timedelta(days=2), 0.20)
    append_observation("AAPL", today, 0.28)
    assert latest_iv("AAPL") == 0.28
    assert latest_iv("NOPE") is None


def test_latest_obs_dates_omits_symbols_with_no_rows(tmp_path, monkeypatch):
    _db_setup(tmp_path, monkeypatch)
    from src.storage.iv_history import append_observation, latest_obs_dates

    today = date.today()
    append_observation("AMD", today - timedelta(days=1), 0.55)
    append_observation("AMD", today, 0.60)
    append_observation("BAC", today - timedelta(days=3), 0.22)

    out = latest_obs_dates(["AMD", "BAC", "NOPE"])
    assert out == {"AMD": today, "BAC": today - timedelta(days=3)}
    assert "NOPE" not in out


def test_stale_symbols_flags_old_and_missing(tmp_path, monkeypatch):
    _db_setup(tmp_path, monkeypatch)
    from src.common.market_hours import today_et
    from src.storage.iv_history import append_observation, stale_symbols

    # stale_symbols measures age against today_et() (exchange time), not the local
    # wall-clock date — anchor the fixture there so the exact-age assertion below holds
    # regardless of local timezone.
    today = today_et()
    append_observation("FRESH", today, 0.30)
    append_observation("OLD", today - timedelta(days=10), 0.40)
    # MISSING has no rows at all.
    stale = dict(stale_symbols(["FRESH", "OLD", "MISSING"], max_age_days=5))
    assert "FRESH" not in stale
    assert stale["OLD"] == 10
    assert stale["MISSING"] is None


def test_format_health_renders_iv_staleness_warning():
    from datetime import datetime

    from src.notify.formatters import format_health

    text = format_health(
        ib_exec_ok=True,
        ib_scan_ok=True,
        last_scan_at=datetime.now(),
        pending_approvals=0,
        open_orders=0,
        db_ok=True,
        iv_stale=[("OLD", 10), ("MISSING", None)],
    )
    assert "Stale IV history" in text
    assert "OLD" in text and "MISSING" in text


def test_format_health_no_warning_when_iv_fresh():
    from datetime import datetime

    from src.notify.formatters import format_health

    text = format_health(True, True, datetime.now(), 0, 0, True, iv_stale=[])
    assert "Stale IV history" not in text
