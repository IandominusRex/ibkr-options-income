"""Part 6, Task 5: a tap on a value card becomes one intent; /value reads the value book read-only.

approval_service forwards and reads; it never decides, never edits value.db and imports nothing from
src.value (the fence test in tests/test_value_fence.py).
"""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from src.common import value_commands as vc
from tests.value_book_fixtures import NOW, order, proposal, ticker_file

EPISODE = vc.trim_episode(100_000.0, NOW)


@pytest.fixture()
def svc(monkeypatch, db):
    import src.notify.approval_service as s

    monkeypatch.setattr(s, "_is_authorized", lambda u: True)
    monkeypatch.setattr(s, "today_et", lambda: date(2026, 11, 3))  # the last settled session: Nov 2
    monkeypatch.setattr(s, "_value_now", lambda: NOW + timedelta(hours=3))
    return s


def _tap(data: str) -> SimpleNamespace:
    query = SimpleNamespace(data=data, answer=AsyncMock())
    return SimpleNamespace(callback_query=query, effective_chat=SimpleNamespace(id=-100))


def _msg() -> SimpleNamespace:
    message = SimpleNamespace(reply_text=AsyncMock())
    return SimpleNamespace(message=message, effective_chat=SimpleNamespace(id=-100))


def _commands() -> list:
    from src.storage.db import session_scope
    from src.storage.models import AppCommandRow

    with session_scope() as s:
        rows = list(s.scalars(select(AppCommandRow).order_by(AppCommandRow.id)))
        s.expunge_all()
    return rows


async def test_a_value_tap_becomes_one_intent(svc) -> None:
    fp = vc.proposal_fingerprint(12, "buy", "GOOGL", 10.0, NOW)
    first, second = (
        _tap(vc.callback_data("approve", 12, fp)),
        _tap(vc.callback_data("approve", 12, fp)),
    )
    await svc.handle_value_button(first, SimpleNamespace())
    await svc.handle_value_button(second, SimpleNamespace())
    rows = _commands()
    assert len(rows) == 1
    assert rows[0].kind == "value_approve" and rows[0].requested_by == "telegram"
    assert rows[0].payload == {"proposal_id": 12, "fingerprint": fp}
    assert rows[0].dedupe_key == "value_approve:12"
    assert first.callback_query.answer.await_args.args[0].startswith("Queued")
    assert second.callback_query.answer.await_args.args[0] == "Already queued."


async def test_a_trim_tap_carries_the_episode(svc) -> None:
    await svc.handle_value_button(_tap(vc.callback_data("trim", 0, EPISODE)), SimpleNamespace())
    (row,) = _commands()
    assert row.kind == "value_trim" and row.payload == {"episode": EPISODE}
    assert row.dedupe_key == f"value_trim:{EPISODE}"


async def test_a_bad_value_callback_is_refused(svc) -> None:
    update = _tap("vbook:x:1:zz")
    await svc.handle_value_button(update, SimpleNamespace())
    assert update.callback_query.answer.await_args.args[0] == "Not a value button."
    assert _commands() == []


async def test_an_unauthorised_tap_does_nothing(svc, monkeypatch) -> None:
    monkeypatch.setattr(svc, "_is_authorized", lambda u: False)
    update = _tap(
        vc.callback_data("approve", 12, vc.proposal_fingerprint(12, "buy", "G", 1.0, NOW))
    )
    await svc.handle_value_button(update, SimpleNamespace())
    update.callback_query.answer.assert_not_awaited()
    assert _commands() == []


async def test_value_lists_both_lists_and_proposals(svc, value_book_db) -> None:
    ticker_file("GOOGL", effective={"deep_value": ("READY", "claude")})
    ticker_file(
        "MSFT",
        verdict_deep="NO",
        verdict_growth="WATCH",
        rank_deep=None,
        rank_growth=70.0,
        effective={"quality_growth": ("WATCH", "python")},
    )
    pid = proposal("GOOGL", status="pending")
    update = _msg()
    await svc.handle_value_command(update, SimpleNamespace(args=[]))
    calls = update.message.reply_text.await_args_list
    text = calls[0].args[0]
    assert "Deep value" in text and "GOOGL" in text and "READY" in text and "Claude" in text
    assert "Quality growth" in text and "MSFT" in text and "WATCH" in text
    keyboard = calls[1].kwargs["reply_markup"].inline_keyboard[0]
    parsed = [vc.parse_callback(b.callback_data) for b in keyboard]
    fp = vc.proposal_fingerprint(pid, "buy", "GOOGL", 10.0, NOW)
    assert parsed == [("approve", pid, fp), ("reject", pid, fp)]
    assert [b.text for b in keyboard] == ["Approve", "Reject"]
    from src.notify.formatters import format_help

    assert "/value NAME" in format_help() and "analyse" in format_help()


async def test_value_name_shows_the_stored_file_and_its_age(svc, value_book_db) -> None:
    ticker_file("GOOGL", effective={"deep_value": ("READY", "claude")})
    order("GOOGL", shares=10, filled=10, avg=100.0)
    update = _msg()
    await svc.handle_value_command(update, SimpleNamespace(args=["googl"]))
    text = update.message.reply_text.await_args.args[0]
    assert "GOOGL" in text and "READY" in text and "$140.00" in text and "30%" in text
    assert "3 hours ago" in text and "holds 10 shares" in text
    assert _commands() == []  # fresh: nothing queued


async def test_a_stale_file_queues_a_refresh(svc, value_book_db) -> None:
    ticker_file("GOOGL", as_of=date(2026, 10, 28), effective={"deep_value": ("READY", "python")})
    update = _msg()
    await svc.handle_value_command(update, SimpleNamespace(args=["GOOGL"]))
    text = update.message.reply_text.await_args.args[0]
    assert "older than the last settled session" in text
    (row,) = _commands()
    assert row.kind == "value_refresh" and row.payload == {"symbol": "GOOGL"}
    assert row.requested_by == "telegram"


async def test_value_name_analyse_queues_a_read(svc, value_book_db) -> None:
    update = _msg()
    await svc.handle_value_command(update, SimpleNamespace(args=["googl", "analyse"]))
    (row,) = _commands()
    assert row.kind == "value_analyse" and row.payload == {"symbol": "GOOGL"}
    assert "analysis" in update.message.reply_text.await_args.args[0].lower()


async def test_value_without_a_value_db_says_so(svc) -> None:
    update = _msg()
    await svc.handle_value_command(update, SimpleNamespace(args=[]))
    assert "no value book" in update.message.reply_text.await_args.args[0].lower()
    assert _commands() == []
    bad = _msg()
    await svc.handle_value_command(bad, SimpleNamespace(args=["DROP;TABLE"]))
    assert "not a ticker" in bad.message.reply_text.await_args.args[0].lower()
