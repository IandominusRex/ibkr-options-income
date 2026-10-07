"""ledger_import / ledger_annotate / ledger_ca_reviewed drain handlers (spec §6.1, R7, R11)."""

from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

FIXTURE = Path(__file__).parent / "fixtures" / "ledger" / "activity_statement_sample.csv"


@pytest.fixture
def run_command(monkeypatch, tmp_path):
    import src.storage.db as dbmod
    from src.common.config import Config

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{tmp_path / 'drain.db'}")
    dbmod.init_db()

    from src.notify.command_drain import drain_once
    from src.storage.app_commands import enqueue_command
    from src.storage.models import AppCommandRow

    def run(kind: str, payload: dict):
        with dbmod.session_scope() as s:
            row, _ = enqueue_command(
                s, kind=kind, payload=payload, requested_by="owner", dedupe_key=None
            )
            cid = row.id
        asyncio.run(drain_once(None, MagicMock(), "chat"))
        with dbmod.session_scope() as s:
            r = s.get(AppCommandRow, cid)
            return r.status, r.result, r.payload

    return run


def test_import_applies_and_strips_the_file_from_the_command_row(run_command) -> None:
    status, result, payload = run_command(
        "ledger_import", {"filename": "stmt.csv", "content": FIXTURE.read_text()}
    )
    assert status == "applied"
    assert result["counts"]["new"] == 15
    assert "content" not in payload and payload["content_bytes"] > 1000


def test_pdf_upload_fails_with_a_pointer(run_command) -> None:
    status, result, _ = run_command(
        "ledger_import", {"filename": "stmt.pdf", "content": "%PDF-1.7"}
    )
    assert status == "failed" and result["reason"] == "pdf_not_supported"


def test_foreign_csv_fails(run_command) -> None:
    status, result, _ = run_command("ledger_import", {"filename": "x.csv", "content": "a,b\n1,2\n"})
    assert status == "failed" and result["reason"] == "not_an_activity_statement"


def test_annotate_sets_only_the_fields_sent(run_command) -> None:
    from src.storage.db import session_scope
    from src.storage.models import TradeAnnotationRow

    key = "b" * 16
    assert (
        run_command(
            "ledger_annotate", {"order_key": key, "notes": "first", "outcome_override": "Expired"}
        )[0]
        == "applied"
    )
    assert (
        run_command("ledger_annotate", {"order_key": key, "tags": ["earnings", " earnings ", ""]})[
            0
        ]
        == "applied"
    )
    with session_scope() as s:
        row = s.scalar(select(TradeAnnotationRow).where(TradeAnnotationRow.order_key == key))
        assert (row.notes, row.tags, row.outcome_override) == ("first", ["earnings"], "Expired")
    run_command("ledger_annotate", {"order_key": key, "outcome_override": ""})
    with session_scope() as s:
        assert (
            s.scalar(
                select(TradeAnnotationRow.outcome_override).where(
                    TradeAnnotationRow.order_key == key
                )
            )
            is None
        )


def test_corporate_action_reviewed(run_command) -> None:
    run_command("ledger_import", {"filename": "stmt.csv", "content": FIXTURE.read_text()})
    from src.storage.db import session_scope
    from src.storage.models import BrokerCorporateActionRow

    with session_scope() as s:
        ca_id = s.scalar(select(BrokerCorporateActionRow.id))
    assert run_command("ledger_ca_reviewed", {"corporate_action_id": ca_id})[0] == "applied"
    status, result, _ = run_command("ledger_ca_reviewed", {"corporate_action_id": 9999})
    assert status == "failed" and result["reason"] == "not_found"


# ---------------------------------------------------------------------------
# Controller ruling F8: ledger_import must not block the event loop. It is an async def
# handler that offloads the parse+ingest work via asyncio.to_thread.
# ---------------------------------------------------------------------------


def test_ledger_import_handler_is_a_coroutine_function() -> None:
    from src.notify.command_drain import HANDLERS

    assert inspect.iscoroutinefunction(HANDLERS["ledger_import"])


def test_ledger_import_offloads_parse_and_ingest_to_a_thread(run_command, monkeypatch) -> None:
    """The handler must actually hand the CPU-bound work to asyncio.to_thread, not merely
    be declared async — an async def that awaits nothing still blocks the loop for the
    duration of a synchronous parse+ingest call."""
    calls: list[object] = []
    real_to_thread = asyncio.to_thread

    async def spy_to_thread(func, *args, **kwargs):
        calls.append(func)
        return await real_to_thread(func, *args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", spy_to_thread)

    status, result, _ = run_command(
        "ledger_import", {"filename": "stmt.csv", "content": FIXTURE.read_text()}
    )

    assert status == "applied"
    assert result["counts"]["new"] == 15
    assert calls, "parse_activity_csv/ingest must run via asyncio.to_thread"


# ---------------------------------------------------------------------------
# Controller ruling F21: _strip_upload runs in a `finally`; a failure inside it must never
# mask the handler's real result or a CommandFailed it raised.
# ---------------------------------------------------------------------------


def test_strip_upload_swallows_its_own_failure_and_logs(monkeypatch) -> None:
    """Unit-level: force the internal DB write _strip_upload performs to fail, and assert
    the function itself never raises — it is the thing standing in `_ledger_import`'s
    `finally`, so an unswallowed exception here would replace whatever was in flight.

    Patches `_write_stripped_payload` — the narrow seam `_strip_upload` delegates its one
    DB write to — rather than `session_scope` itself. Patching `session_scope` globally
    (on `src.storage.db` or on `command_drain`'s own module-level name) would also poison
    any other module's first *lazy* import of it for the rest of the process (e.g.
    `src.ledger.ingest`'s own module-level binding, captured once at its first import and
    never re-read), and `command_drain`'s own name is shared with `_applied`/`_fail`/
    `drain_once` besides. `_write_stripped_payload` is called from nowhere else.

    Asserts the log call directly on `command_drain`'s own `log` object rather than via
    `caplog`: this repo's `src.common.logging.setup_logging()` does `root.handlers.clear()`
    the first time anything calls `get_logger()`, which — depending on which other module
    happens to trigger that first call, and when — can race with pytest's caplog handler
    and silently drop the record. Patching `log.exception` itself sidesteps the stdlib
    logging plumbing (and that race) entirely.
    """
    import src.notify.command_drain as drain
    from src.notify.command_drain import _strip_upload

    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("disk full")

    monkeypatch.setattr(drain, "_write_stripped_payload", boom)

    logged: list[tuple[object, ...]] = []
    monkeypatch.setattr(drain.log, "exception", lambda *a, **k: logged.append(a))

    _strip_upload(123, "stmt.csv", 999)  # must not raise

    assert logged, "a failure inside _strip_upload must be logged, not silently dropped"
    assert "strip" in str(logged[0]).lower()


def test_a_strip_failure_does_not_mask_a_successful_import(run_command, monkeypatch) -> None:
    """End-to-end: even when the finally-block's own DB write fails, the import's real
    result (status=applied, counts) must still land on the command row — not
    handler_error. See `test_strip_upload_swallows_its_own_failure_and_logs` for why the
    failure is injected via `_write_stripped_payload` and not `session_scope` itself."""

    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("disk full")

    monkeypatch.setattr("src.notify.command_drain._write_stripped_payload", boom)

    status, result, payload = run_command(
        "ledger_import", {"filename": "stmt.csv", "content": FIXTURE.read_text()}
    )

    assert status == "applied"
    assert result["counts"]["new"] == 15
    # The strip itself failed, so the raw content is still sitting on the row — proving the
    # finally's own failure was swallowed rather than silently "succeeding".
    assert payload["content"] == FIXTURE.read_text()


def test_a_strip_failure_does_not_mask_a_failed_import(run_command, monkeypatch) -> None:
    """Same as above, but on the CommandFailed path: a foreign CSV still reports
    not_an_activity_statement, not handler_error, even when the finally's own write fails."""

    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("disk full")

    monkeypatch.setattr("src.notify.command_drain._write_stripped_payload", boom)

    status, result, _ = run_command("ledger_import", {"filename": "x.csv", "content": "a,b\n1,2\n"})

    assert status == "failed"
    assert result["reason"] == "not_an_activity_statement"
