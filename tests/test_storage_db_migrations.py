"""The one-time ``app_commands`` dedupe-key migration (``_ensure_app_commands_pending_only_dedupe``).

Builds a DB file with the *pre-fix* schema by hand (global ``UNIQUE(dedupe_key)``, exactly what
every DB created before this fix shipped still has on disk), then runs ``init_db()`` against it
and asserts: the old global constraint is gone, the new pending-scoped partial index is in place
and actually enforces "one pending row per key", and every pre-existing row survives the rebuild
untouched (same id, same values).
"""

from __future__ import annotations

from sqlalchemy import create_engine, inspect, text


def _create_legacy_app_commands(db_path) -> None:
    """The exact original DDL (see git history of ``src/storage/models.py``): a full
    ``UNIQUE`` constraint on ``dedupe_key`` with no status scoping."""
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE app_commands ("
                "id INTEGER NOT NULL, "
                "kind VARCHAR(24) NOT NULL, "
                "payload JSON NOT NULL, "
                "dedupe_key VARCHAR(96), "
                "status VARCHAR(10) NOT NULL, "
                "result JSON, "
                "requested_by VARCHAR(64) NOT NULL, "
                "confirm_token VARCHAR(128), "
                "created_at DATETIME NOT NULL, "
                "applied_at DATETIME, "
                "PRIMARY KEY (id), "
                "CONSTRAINT uq_app_commands_dedupe_key UNIQUE (dedupe_key)"
                ")"
            )
        )
        conn.execute(text("CREATE INDEX ix_app_commands_kind ON app_commands (kind)"))
        conn.execute(text("CREATE INDEX ix_app_commands_status ON app_commands (status)"))
        # An already-applied promote from before the fix — the exact row shape that used to
        # permanently block a fresh re-promote of the same candidate.
        conn.execute(
            text(
                "INSERT INTO app_commands "
                "(id, kind, payload, dedupe_key, status, result, requested_by, "
                "confirm_token, created_at, applied_at) VALUES "
                "(1, 'promote', '{}', 'promote:cand-1', 'applied', '{}', 'owner', "
                "NULL, '2026-01-01 00:00:00', '2026-01-01 00:01:00')"
            )
        )
    engine.dispose()


def _fresh_db(tmp_path, monkeypatch):
    import src.storage.db as dbmod
    from src.common.config import Config

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    db_path = tmp_path / "legacy.db"
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{db_path}")
    return db_path, dbmod


def test_legacy_global_unique_constraint_is_replaced_by_a_pending_scoped_index(
    tmp_path, monkeypatch
) -> None:
    db_path, dbmod = _fresh_db(tmp_path, monkeypatch)
    _create_legacy_app_commands(db_path)

    dbmod.init_db()

    inspector = inspect(dbmod._engine)
    assert inspector.get_unique_constraints("app_commands") == []
    index_names = {ix["name"] for ix in inspector.get_indexes("app_commands")}
    assert "uq_app_commands_dedupe_key_pending" in index_names


def test_the_pre_existing_row_survives_the_rebuild_unchanged(tmp_path, monkeypatch) -> None:
    db_path, dbmod = _fresh_db(tmp_path, monkeypatch)
    _create_legacy_app_commands(db_path)

    dbmod.init_db()

    with dbmod.session_scope() as s:
        from src.storage.models import AppCommandRow

        row = s.get(AppCommandRow, 1)
        assert row is not None
        assert row.kind == "promote"
        assert row.dedupe_key == "promote:cand-1"
        assert row.status == "applied"
        assert row.requested_by == "owner"


def test_a_re_promote_after_the_migration_gets_a_fresh_row_not_the_old_applied_one(
    tmp_path, monkeypatch
) -> None:
    """The exact regression this migration exists for: a DB carried over from before the
    fix must let a new promote/roll_request for a previously-applied key through, not
    permanently dedupe to the stale row."""
    db_path, dbmod = _fresh_db(tmp_path, monkeypatch)
    _create_legacy_app_commands(db_path)
    dbmod.init_db()

    from src.storage.app_commands import enqueue_command

    with dbmod.session_scope() as s:
        row, created = enqueue_command(
            s,
            kind="promote",
            payload={},
            requested_by="owner",
            dedupe_key="promote:cand-1",
        )
        assert created is True
        assert row.id != 1


def test_running_init_db_twice_on_an_already_migrated_db_is_a_no_op(tmp_path, monkeypatch) -> None:
    db_path, dbmod = _fresh_db(tmp_path, monkeypatch)
    _create_legacy_app_commands(db_path)

    dbmod.init_db()
    dbmod._engine = None
    dbmod._SessionLocal = None
    dbmod.init_db()  # second pass must not error on the already-rebuilt table

    with dbmod.session_scope() as s:
        from src.storage.models import AppCommandRow

        assert s.get(AppCommandRow, 1) is not None
