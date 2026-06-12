"""Tests for the nightly DB backup + rotation (SYSTEM_REVIEW Phase 2)."""

from __future__ import annotations

import sqlite3
from types import SimpleNamespace

from src.storage import maintenance


def _make_db(path) -> None:
    with sqlite3.connect(str(path)) as c:
        c.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
        c.execute("INSERT INTO t (v) VALUES ('hello')")


def _point_config_at(monkeypatch, db_path) -> None:
    cfg = SimpleNamespace(db_url_abs=lambda: f"sqlite:///{db_path}")
    monkeypatch.setattr(maintenance, "get_config", lambda: cfg)


def test_backup_creates_snapshot(tmp_path, monkeypatch) -> None:
    db = tmp_path / "income_system.db"
    _make_db(db)
    _point_config_at(monkeypatch, db)

    dest = maintenance.backup_database()

    assert dest is not None and dest.exists()
    assert dest.parent == tmp_path / "backups"
    # The snapshot is a real, readable SQLite DB with the source data.
    with sqlite3.connect(str(dest)) as c:
        assert c.execute("SELECT v FROM t").fetchone()[0] == "hello"


def test_backup_rotation_keeps_n(tmp_path, monkeypatch) -> None:
    db = tmp_path / "income_system.db"
    _make_db(db)
    _point_config_at(monkeypatch, db)

    for _ in range(4):
        maintenance.backup_database(keep=2)

    snapshots = list((tmp_path / "backups").glob("income_system_*.db"))
    assert len(snapshots) == 2


def test_backup_noop_when_db_missing(tmp_path, monkeypatch) -> None:
    _point_config_at(monkeypatch, tmp_path / "does_not_exist.db")
    assert maintenance.backup_database() is None
