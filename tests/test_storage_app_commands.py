"""app_commands round-trips, and a duplicate intent can never become two rows."""

from __future__ import annotations

import pytest

from src.storage.app_commands import (
    enqueue_command,
    mark_applied,
    mark_failed,
    pending_commands,
)


@pytest.fixture
def db_session(tmp_path, monkeypatch):
    """A fresh trading DB session, matching the pattern in test_storage_buy_candidates."""
    import src.storage.db as dbmod
    from src.common.config import Config

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{tmp_path / 't.db'}")
    dbmod.init_db()
    session = dbmod._SessionLocal()
    try:
        yield session
    finally:
        session.close()


def test_enqueue_returns_the_row_and_created_true(db_session) -> None:
    row, created = enqueue_command(
        db_session,
        kind="approve",
        payload={"approval_id": 7},
        requested_by="owner",
        dedupe_key="approve:7",
    )
    db_session.commit()
    assert created is True
    assert row.status == "pending"
    assert row.payload == {"approval_id": 7}


def test_a_duplicate_dedupe_key_returns_the_existing_row(db_session) -> None:
    """Two clicks on Approve must produce one command, not two."""
    first, _ = enqueue_command(
        db_session,
        kind="approve",
        payload={"approval_id": 7},
        requested_by="owner",
        dedupe_key="approve:7",
    )
    db_session.commit()
    second, created = enqueue_command(
        db_session,
        kind="approve",
        payload={"approval_id": 7},
        requested_by="owner",
        dedupe_key="approve:7",
    )
    db_session.commit()
    assert created is False
    assert second.id == first.id
    assert len(pending_commands(db_session)) == 1


def test_a_null_dedupe_key_may_repeat(db_session) -> None:
    """refresh and halt are harmless to repeat, so they are not deduped."""
    enqueue_command(db_session, kind="refresh", payload={}, requested_by="owner")
    enqueue_command(db_session, kind="refresh", payload={}, requested_by="owner")
    db_session.commit()
    assert len(pending_commands(db_session)) == 2


def test_pending_excludes_applied_and_failed(db_session) -> None:
    a, _ = enqueue_command(db_session, kind="refresh", payload={}, requested_by="owner")
    b, _ = enqueue_command(db_session, kind="refresh", payload={}, requested_by="owner")
    db_session.commit()
    mark_applied(db_session, a.id, {"ok": True})
    mark_failed(db_session, b.id, "no_qualifying_roll")
    db_session.commit()
    assert pending_commands(db_session) == []


def test_mark_failed_records_the_reason(db_session) -> None:
    row, _ = enqueue_command(db_session, kind="promote", payload={}, requested_by="owner")
    db_session.commit()
    mark_failed(db_session, row.id, "gate_rejected", {"reasons": ["delta_out_of_band"]})
    db_session.commit()
    db_session.refresh(row)
    assert row.status == "failed"
    assert row.result["reason"] == "gate_rejected"
    assert row.result["detail"]["reasons"] == ["delta_out_of_band"]
