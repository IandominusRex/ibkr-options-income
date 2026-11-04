"""Part 6: the value command kinds (rulings 1-8). The value process drains them; nothing else does."""

from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from src.api.models.commands import (
    CommandKind,
    PromotePayload,
    dedupe_key_for,
    validate_payload,
)
from src.common import value_commands as vc

CREATED = datetime(2026, 11, 2, 14, 35, 0)


def test_the_fingerprint_is_ten_hex_and_moves_with_the_trade() -> None:
    fp = vc.proposal_fingerprint(12, "buy", "GOOGL", 10.0, CREATED)
    assert len(fp) == 10 and int(fp, 16) >= 0
    assert fp == vc.proposal_fingerprint(12, "buy", "GOOGL", 10.0, CREATED)
    assert fp != vc.proposal_fingerprint(12, "buy", "GOOGL", 11.0, CREATED)
    assert fp != vc.proposal_fingerprint(13, "buy", "GOOGL", 10.0, CREATED)


def test_callback_data_round_trips_and_fits_telegram() -> None:
    fp = vc.proposal_fingerprint(12, "buy", "GOOGL", 10.0, CREATED)
    for action in ("approve", "reject", "trim"):
        data = vc.callback_data(action, 12 if action != "trim" else 0, fp)
        assert len(data.encode()) <= 64
        assert vc.parse_callback(data) == (action, 12 if action != "trim" else 0, fp)


@pytest.mark.parametrize(
    "data", ["vbook:x:1:abcdef0123", "vbook:a:one:abcdef0123", "vbook:a:1:zz", "approve:1", ""]
)
def test_bad_callback_data_is_none(data: str) -> None:
    assert vc.parse_callback(data) is None


def test_every_value_kind_is_a_command_kind() -> None:
    assert {k.value for k in CommandKind if k.value.startswith("value_")} == set(vc.VALUE_KINDS)


def test_value_payloads_are_strict() -> None:
    ok = validate_payload(
        CommandKind.VALUE_APPROVE, {"proposal_id": 3, "fingerprint": "abcdef0123"}
    )
    assert dedupe_key_for(CommandKind.VALUE_APPROVE, ok) == "value_approve:3"
    with pytest.raises(ValidationError):
        validate_payload(CommandKind.VALUE_APPROVE, {"proposal_id": 3, "fingerprint": "nothex!!!!"})
    with pytest.raises(ValidationError):
        validate_payload(
            CommandKind.VALUE_REJECT, {"proposal_id": 3, "fingerprint": "abcdef0123", "shares": 5}
        )
    trim = validate_payload(CommandKind.VALUE_TRIM, {"episode": "0123456789"})
    assert dedupe_key_for(CommandKind.VALUE_TRIM, trim) == "value_trim:0123456789"
    snap = validate_payload(CommandKind.VALUE_SNAPSHOT, {"symbol": "googl", "fingerprint": {}})
    assert dedupe_key_for(CommandKind.VALUE_SNAPSHOT, snap) is None


def test_promote_declares_value_put() -> None:
    p = PromotePayload(
        candidate_id="c", symbol="X", strategy="cash_secured_put", strike=1.0, expiry="2026-12-18"
    )
    assert p.value_put is False


def test_the_trading_drain_never_reads_a_value_kind(db) -> None:
    from src.storage import app_commands as ac
    from src.storage.db import session_scope

    with session_scope() as s:
        ac.enqueue_command(
            s,
            kind="value_approve",
            payload={"proposal_id": 1, "fingerprint": "abcdef0123"},
            requested_by="web",
        )
        ac.enqueue_command(s, kind="halt", payload={}, requested_by="web")
        s.commit()
        kinds = [c.kind for c in ac.pending_commands(s, exclude_kinds=vc.VALUE_KINDS)]
        mine = [c.kind for c in ac.pending_commands(s, only_kinds=vc.VALUE_KINDS)]
    assert "value_approve" not in kinds and "halt" in kinds
    assert mine == ["value_approve"]


# --- Task 2: the value process applies its kinds inside value.db ------------------------------

NOW = datetime(2026, 11, 2, 15, 0)


def _proposal(*, shares: float = 10.0, ttl_hours: float = 30.0) -> tuple[int, str]:
    from src.value import book
    from src.value.store import value_session

    with value_session() as vs:
        row = book.propose(
            vs,
            kind="buy",
            symbol="STDY",
            list_name="deep_value",
            shares=shares,
            price=30.0,
            reason="tranche 1",
            cause="python",
            auto=False,
            now=NOW,
            ttl_hours=ttl_hours,
        )
        assert row is not None
        return row.id, vc.proposal_fingerprint(
            row.id, row.kind, row.symbol, row.shares, row.created_at
        )


def _apply(
    kind: str, payload: dict, *, by: str = "telegram", now: datetime = NOW, live: bool = False
):
    from src.value import commands as vcmd
    from src.value.store import value_session

    with value_session() as vs:
        return vcmd.apply(vs, kind, payload, requested_by=by, now=now, live=live)


def _row(pid: int):
    from src.value.store import ValueProposalRow, value_session

    with value_session() as vs:
        row = vs.get(ValueProposalRow, pid)
        assert row is not None
        vs.expunge(row)
        return row


def test_approve_needs_the_current_fingerprint(value_book_db) -> None:
    from src.value.commands import ValueCommandFailed

    pid, _ = _proposal()
    stale = vc.proposal_fingerprint(pid, "buy", "STDY", 11.0, NOW)
    with pytest.raises(ValueCommandFailed) as exc:
        _apply("value_approve", {"proposal_id": pid, "fingerprint": stale})
    assert exc.value.reason == "stale_proposal"
    assert _row(pid).status == "pending"


def test_approve_marks_who_decided(value_book_db) -> None:
    pid, fp = _proposal()
    result = _apply("value_approve", {"proposal_id": pid, "fingerprint": fp}, by="telegram")
    assert result["decision"] == "approved" and result["proposal_id"] == pid
    row = _row(pid)
    assert row.status == "approved" and row.decided_by == "telegram"


def test_a_second_tap_is_a_no_op_answer(value_book_db) -> None:
    from datetime import timedelta

    from src.value.commands import ValueCommandFailed

    pid, fp = _proposal()
    _apply("value_approve", {"proposal_id": pid, "fingerprint": fp})
    first = _row(pid).decided_at
    with pytest.raises(ValueCommandFailed) as exc:
        _apply(
            "value_approve", {"proposal_id": pid, "fingerprint": fp}, now=NOW + timedelta(minutes=1)
        )
    assert exc.value.reason == "already_approved"
    assert _row(pid).decided_at == first


def test_reject_after_approve_is_refused(value_book_db) -> None:
    from src.value.commands import ValueCommandFailed

    pid, fp = _proposal()
    _apply("value_approve", {"proposal_id": pid, "fingerprint": fp})
    with pytest.raises(ValueCommandFailed) as exc:
        _apply("value_reject", {"proposal_id": pid, "fingerprint": fp})
    assert exc.value.reason == "already_approved"
    assert _row(pid).status == "approved"


def test_an_expired_proposal_expires(value_book_db) -> None:
    from datetime import timedelta

    from src.value.commands import ValueCommandFailed

    pid, fp = _proposal(ttl_hours=1.0)
    with pytest.raises(ValueCommandFailed) as exc:
        _apply(
            "value_approve", {"proposal_id": pid, "fingerprint": fp}, now=NOW + timedelta(hours=2)
        )
    assert exc.value.reason == "expired"
    assert _row(pid).decided_by is None


def test_no_such_proposal(value_book_db) -> None:
    from src.value.commands import ValueCommandFailed

    with pytest.raises(ValueCommandFailed) as exc:
        _apply("value_reject", {"proposal_id": 99, "fingerprint": "abcdef0123"})
    assert exc.value.reason == "no_such_proposal"


def test_live_refuses_order_kinds(value_book_db) -> None:
    from sqlalchemy import select

    from src.value.commands import ValueCommandFailed
    from src.value.store import ValueBookStateRow, ValueProposalRow, value_session

    pid, fp = _proposal()
    for kind, payload in (
        ("value_approve", {"proposal_id": pid, "fingerprint": fp}),
        ("value_reject", {"proposal_id": pid, "fingerprint": fp}),
        ("value_trim", {"episode": "0123456789"}),
    ):
        with pytest.raises(ValueCommandFailed) as exc:
            _apply(kind, payload, live=True)
        assert exc.value.reason == "not_paper"
    with value_session() as vs:
        assert [r.status for r in vs.scalars(select(ValueProposalRow))] == ["pending"]
        assert list(vs.scalars(select(ValueBookStateRow))) == []


def test_unknown_requester_reads_as_web(value_book_db) -> None:
    pid, fp = _proposal()
    _apply("value_approve", {"proposal_id": pid, "fingerprint": fp}, by="owner-7f3a")
    assert _row(pid).decided_by == "web"


def test_drain_marks_applied_and_failed(value_book_db) -> None:
    from src.value import commands as vcmd

    pid, fp = _proposal()
    marks: list[tuple[int, dict | None, str | None, dict | None, str]] = []

    def apply_fn(kind: str, payload: dict, by: str) -> dict:
        return _apply(kind, payload, by=by)

    def mark_fn(cid: int, result: dict | None, reason: str | None, detail: dict | None) -> None:
        # value.db has committed before the command is marked (a crash between re-applies, idempotently)
        marks.append((cid, result, reason, detail, _row(pid).status))

    rows = [
        (1, "value_approve", {"proposal_id": pid, "fingerprint": fp}, "telegram", None),
        (2, "value_approve", {"proposal_id": pid, "fingerprint": fp}, "web", None),
        (3, "value_reject", {"proposal_id": 77, "fingerprint": fp}, "web", None),
        (4, "value_reject", {}, "web", None),
    ]
    outcomes = vcmd.drain(rows, apply_fn, mark_fn)
    assert [(m[0], m[2], m[4]) for m in marks] == [
        (1, None, "approved"),
        (2, "already_approved", "approved"),
        (3, "no_such_proposal", "approved"),
        (4, "handler_error", "approved"),
    ]
    assert marks[0][1] is not None and marks[0][1]["decision"] == "approved"
    assert [(o.cid, o.kind, o.requested_by, o.reason) for o in outcomes] == [
        (1, "value_approve", "telegram", None),
        (2, "value_approve", "web", "already_approved"),
        (3, "value_reject", "web", "no_such_proposal"),
        (4, "value_reject", "web", "handler_error"),
    ]


def test_drain_skips_a_command_awaiting_confirmation(value_book_db) -> None:
    from src.value import commands as vcmd

    pid, fp = _proposal()
    applied: list[str] = []
    marked: list[int] = []
    rows = [(5, "value_approve", {"proposal_id": pid, "fingerprint": fp}, "web", "tok-live")]
    outcomes = vcmd.drain(
        rows, lambda k, p, b: applied.append(k) or {}, lambda cid, *_: marked.append(cid)
    )
    assert outcomes == [] and applied == [] and marked == []
    assert _row(pid).status == "pending"
