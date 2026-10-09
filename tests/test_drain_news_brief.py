from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.api.models.commands import (
    CommandKind,
    NewsBriefPayload,
    dedupe_key_for,
    validate_payload,
)


def test_payload_validation() -> None:
    assert validate_payload(CommandKind.NEWS_BRIEF, {"symbol": "nvda"}).symbol == "nvda"
    for bad in ({"symbol": "DROP;TABLE"}, {"symbol": ""}, {"symbol": "NVDA", "x": 1}):
        with pytest.raises(ValidationError):
            validate_payload(CommandKind.NEWS_BRIEF, bad)
    assert dedupe_key_for(CommandKind.NEWS_BRIEF, NewsBriefPayload(symbol="NVDA")) is None


async def test_drain_handler_enqueues(monkeypatch) -> None:
    from src.notify import command_drain

    monkeypatch.setattr("src.news.briefs.enqueue_brief", lambda sym, origin: 42)
    handler = command_drain.HANDLERS["news_brief"]
    out = handler(ib=None, bot=None, chat_id="x", command=None, payload={"symbol": "nvda"})
    assert out == {"request_id": 42, "symbol": "NVDA"}


def test_post_commands_accepts_news_brief(client) -> None:
    from tests.conftest import OWNER

    r = client.post(
        "/commands", headers=OWNER, json={"kind": "news_brief", "payload": {"symbol": "TSM"}}
    )
    assert r.status_code in (200, 201) and r.json()["kind"] == "news_brief"


@pytest.fixture
def run_command(monkeypatch, tmp_path, news_db):
    """Enqueue a command in a throwaway trading DB and drain it for real (news.db is `news_db`)."""
    import asyncio
    from unittest.mock import MagicMock

    import src.storage.db as dbmod
    from src.common.config import Config

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{tmp_path / 'drain.db'}")
    dbmod.init_db()

    from src.notify.command_drain import drain_once
    from src.storage.app_commands import enqueue_command
    from src.storage.models import AppCommandRow

    def run(payload: dict):
        with dbmod.session_scope() as s:
            row, _ = enqueue_command(
                s, kind="news_brief", payload=payload, requested_by="owner", dedupe_key=None
            )
            cid = row.id
        asyncio.run(drain_once(None, MagicMock(), "chat"))
        with dbmod.session_scope() as s:
            r = s.get(AppCommandRow, cid)
            return r.status, r.result

    return run


def test_drain_inserts_a_pending_request_and_nothing_else(run_command) -> None:
    from src.news.store.models import NewsRequestRow
    from src.news.store.session import news_session

    status, result = run_command({"symbol": "$tsm"})
    assert status == "applied" and result["symbol"] == "TSM"
    with news_session() as s:
        rows = s.query(NewsRequestRow).all()
    assert [(r.id, r.symbol, r.origin, r.status) for r in rows] == [
        (result["request_id"], "TSM", "web", "pending")
    ]


def test_a_repeat_click_reuses_the_pending_request(run_command) -> None:
    first = run_command({"symbol": "NVDA"})[1]["request_id"]
    assert run_command({"symbol": "nvda"})[1]["request_id"] == first


def test_an_unusable_symbol_fails_with_invalid_symbol(run_command) -> None:
    # The API's pattern normally stops this; a row written around it must fail, not enqueue.
    status, result = run_command({"symbol": "NV DA"})
    assert status == "failed" and result["reason"] == "invalid_symbol"
