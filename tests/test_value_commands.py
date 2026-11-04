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
