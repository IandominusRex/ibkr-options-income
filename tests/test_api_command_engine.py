"""The API writes exactly one table, and the read path stays read-only.

Spec §4.2: the guarantee moves from "the API cannot write" to "the API can write
exactly one table, app_commands". The read-only engine still raises on any write;
the command engine can insert app_commands and nothing else, proven by a runtime
listener, not a comment.
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import OperationalError


@pytest.fixture
def api_dbs(monkeypatch, tmp_path):
    """A temp trading DB with both the read-only and command engines pointed at it."""
    trading_db = tmp_path / "income_system.db"

    # Reset the read-only engine + session and point them at the temp DB.
    monkeypatch.setattr("src.api.trading_db._engine", None)
    monkeypatch.setattr("src.api.trading_db._SessionLocal", None)
    monkeypatch.setattr("src.api.trading_db._resolve_path", lambda: trading_db.as_posix())

    # Reset the command engine + session too.
    monkeypatch.setattr("src.api.trading_db._cmd_engine", None)
    monkeypatch.setattr("src.api.trading_db._cmd_session_factory", None)

    # Build the trading DB with all tables (read-write via the storage engine).
    import src.storage.db as dbmod
    from src.common.config import Config

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{trading_db}")
    dbmod.init_db()
    return trading_db


def test_the_read_engine_still_refuses_a_write(api_dbs) -> None:
    """A route holding the read-only session must still be unable to mutate anything."""
    from src.api.trading_db import trading_session
    from src.storage.models import BuyCandidateRow

    with trading_session() as s:
        s.add(BuyCandidateRow(run_id="x", symbol="NVDA", score=1.0))
        with pytest.raises(OperationalError):
            s.commit()


def test_the_command_engine_can_insert_an_app_command(api_dbs) -> None:
    from src.api.auth import Role, User
    from src.api.commands import submit
    from src.api.models.commands import CommandKind

    cid, created = submit(
        kind=CommandKind.REFRESH,
        payload={},
        user=User(id="owner", role=Role.OWNER),
        dedupe_key=None,
    )
    assert created is True
    assert cid > 0


def test_the_command_engine_refuses_any_other_table(api_dbs) -> None:
    """The write handle exists for app_commands. Nothing else may reach it."""
    from src.api.trading_db import command_session
    from src.storage.models import OrderRow

    with pytest.raises(Exception):  # noqa: B017 — the listener raises a specific exception
        with command_session() as s:
            s.add(OrderRow(candidate_id="x", state="queued"))
