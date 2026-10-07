"""Command schemas: every kind parses its payload, wrong shapes raise, and the
universe surface is narrowed at the type level (sectors/leveraged_etfs rejected)."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from src.api.models.commands import (
    PAYLOAD_FOR,
    ApprovePayload,
    CommandKind,
    CommandStatus,
    HaltPayload,
    PromotePayload,
    RejectPayload,
    RollRequestPayload,
    SetAutonomyPayload,
    UniversePayload,
    dedupe_key_for,
    validate_payload,
)
from src.common.schemas import AutonomyLevel


def test_every_kind_has_a_payload_model() -> None:
    """A kind without a model is a kind the API cannot accept — fail loud, not silent."""
    for kind in CommandKind:
        assert kind in PAYLOAD_FOR, f"{kind} has no payload model"


def test_approve_parses() -> None:
    m = validate_payload(CommandKind.APPROVE, {"approval_id": 7})
    assert isinstance(m, ApprovePayload)
    assert m.approval_id == 7


def test_reject_parses() -> None:
    m = validate_payload(CommandKind.REJECT, {"approval_id": 7})
    assert isinstance(m, RejectPayload)
    assert m.approval_id == 7


def test_promote_parses() -> None:
    m = validate_payload(
        CommandKind.PROMOTE,
        {
            "candidate_id": "abc",
            "symbol": "NVDA",
            "strategy": "covered_call",
            "strike": 105.0,
            "expiry": "2026-10-16",
        },
    )
    assert isinstance(m, PromotePayload)
    assert m.symbol == "NVDA"
    assert m.expiry == date(2026, 10, 16)


def test_roll_request_parses() -> None:
    m = validate_payload(CommandKind.ROLL_REQUEST, {"position_symbol": "NVDA"})
    assert isinstance(m, RollRequestPayload)
    assert m.position_symbol == "NVDA"


def test_halt_parses_with_default_reason() -> None:
    m = validate_payload(CommandKind.HALT, {})
    assert isinstance(m, HaltPayload)
    assert m.reason == ""


def test_resume_parses_empty() -> None:
    validate_payload(CommandKind.RESUME, {})


def test_refresh_parses_empty() -> None:
    validate_payload(CommandKind.REFRESH, {})


def test_set_autonomy_parses() -> None:
    m = validate_payload(CommandKind.SET_AUTONOMY, {"level": "manual"})
    assert isinstance(m, SetAutonomyPayload)
    assert m.level == AutonomyLevel.MANUAL


def test_set_autonomy_rejects_an_unknown_level() -> None:
    with pytest.raises(ValidationError):
        validate_payload(CommandKind.SET_AUTONOMY, {"level": "yolo"})


def test_universe_add_parses() -> None:
    m = validate_payload(CommandKind.UNIVERSE_ADD, {"symbol": "NVDA", "list_name": "watchlist"})
    assert isinstance(m, UniversePayload)
    assert m.symbol == "NVDA"
    assert m.list_name == "watchlist"


def test_universe_remove_parses() -> None:
    m = validate_payload(CommandKind.UNIVERSE_REMOVE, {"symbol": "META", "list_name": "would_own"})
    assert isinstance(m, UniversePayload)
    assert m.list_name == "would_own"


def test_universe_rejects_sectors_as_list_name() -> None:
    """§7.2: only would_own and watchlist may be edited from the web. sectors must fail."""
    with pytest.raises(ValidationError):
        validate_payload(CommandKind.UNIVERSE_ADD, {"symbol": "XLE", "list_name": "sectors"})


def test_universe_rejects_leveraged_etfs_as_list_name() -> None:
    with pytest.raises(ValidationError):
        validate_payload(
            CommandKind.UNIVERSE_REMOVE,
            {"symbol": "TQQQ", "list_name": "leveraged_etfs"},
        )


def test_a_wrong_shaped_payload_raises() -> None:
    with pytest.raises(ValidationError):
        validate_payload(CommandKind.APPROVE, {"not_approval_id": 7})


def test_a_missing_required_field_raises() -> None:
    with pytest.raises(ValidationError):
        validate_payload(CommandKind.PROMOTE, {"candidate_id": "abc"})


def test_dedupe_key_for_keyed_kinds() -> None:
    assert (
        dedupe_key_for(
            CommandKind.APPROVE, validate_payload(CommandKind.APPROVE, {"approval_id": 7})
        )
        == "approve:7"
    )
    assert (
        dedupe_key_for(CommandKind.REJECT, validate_payload(CommandKind.REJECT, {"approval_id": 7}))
        == "reject:7"
    )
    assert (
        dedupe_key_for(
            CommandKind.PROMOTE,
            validate_payload(
                CommandKind.PROMOTE,
                {
                    "candidate_id": "abc",
                    "symbol": "NVDA",
                    "strategy": "covered_call",
                    "strike": 105.0,
                    "expiry": "2026-10-16",
                },
            ),
        )
        == "promote:abc"
    )
    assert (
        dedupe_key_for(
            CommandKind.ROLL_REQUEST,
            validate_payload(CommandKind.ROLL_REQUEST, {"position_symbol": "NVDA"}),
        )
        == "roll_request:NVDA"
    )


def test_dedupe_key_for_unkeyed_kinds_is_none() -> None:
    """halt/resume/set_autonomy/refresh/universe_add/universe_remove are all repeatable —
    see dedupe_key_for's own docstring for why the universe kinds joined this set in the
    M7 final-review fix round (a stable key let a repeat request dedupe to a stale,
    already-applied row instead of creating a fresh one)."""
    assert dedupe_key_for(CommandKind.HALT, validate_payload(CommandKind.HALT, {})) is None
    assert dedupe_key_for(CommandKind.RESUME, validate_payload(CommandKind.RESUME, {})) is None
    assert (
        dedupe_key_for(
            CommandKind.SET_AUTONOMY,
            validate_payload(CommandKind.SET_AUTONOMY, {"level": "manual"}),
        )
        is None
    )
    assert dedupe_key_for(CommandKind.REFRESH, validate_payload(CommandKind.REFRESH, {})) is None
    assert (
        dedupe_key_for(
            CommandKind.UNIVERSE_ADD,
            validate_payload(
                CommandKind.UNIVERSE_ADD, {"symbol": "NVDA", "list_name": "watchlist"}
            ),
        )
        is None
    )
    assert (
        dedupe_key_for(
            CommandKind.UNIVERSE_REMOVE,
            validate_payload(
                CommandKind.UNIVERSE_REMOVE, {"symbol": "META", "list_name": "would_own"}
            ),
        )
        is None
    )


def test_command_status_constructs() -> None:
    s = CommandStatus(
        id=1,
        kind=CommandKind.REFRESH,
        status="pending",
        result=None,
        needs_confirmation=False,
        created_at=datetime.now(UTC),
        applied_at=None,
    )
    assert s.kind == CommandKind.REFRESH
    assert s.needs_confirmation is False


# ---------------------------------------------------------------------------
# M6 Task 6.2 — control-kind payload validation.
#
# The control kinds are the lightest in the queue, and their payloads are the
# most likely to be typed by hand (a client typo) or by a future tool, so the
# schemas are closed: unknown keys are a 422 at parse time, before a command
# row can exist. The reason cap exists because the reason is rendered by
# /status and the console's halt banner — an unbounded string in a settings
# value is a rendering bug waiting to happen.
# ---------------------------------------------------------------------------


def test_halt_reason_over_200_chars_is_rejected() -> None:
    with pytest.raises(ValidationError):
        validate_payload(CommandKind.HALT, {"reason": "x" * 201})


def test_halt_reason_at_exactly_200_chars_parses() -> None:
    m = validate_payload(CommandKind.HALT, {"reason": "x" * 200})
    assert m.reason == "x" * 200


def test_resume_rejects_unknown_keys() -> None:
    """A typo in a client is caught rather than ignored."""
    with pytest.raises(ValidationError):
        validate_payload(CommandKind.RESUME, {"reason": "oops"})


def test_refresh_rejects_unknown_keys() -> None:
    with pytest.raises(ValidationError):
        validate_payload(CommandKind.REFRESH, {"force": True})


def test_halt_rejects_unknown_keys() -> None:
    with pytest.raises(ValidationError):
        validate_payload(CommandKind.HALT, {"reson": "typo"})


def test_set_autonomy_rejects_unknown_keys() -> None:
    with pytest.raises(ValidationError):
        validate_payload(CommandKind.SET_AUTONOMY, {"level": "manual", "force": True})


# ---------------------------------------------------------------------------
# Task 8 — ledger_import / ledger_annotate / ledger_ca_reviewed payload validation.
# ---------------------------------------------------------------------------


def test_ledger_payloads_validate_and_are_never_deduped() -> None:
    from src.api.models.commands import (
        LedgerAnnotatePayload,
        LedgerCaReviewedPayload,
        LedgerImportPayload,
    )

    imp = validate_payload(CommandKind.LEDGER_IMPORT, {"filename": "s.csv", "content": "x"})
    assert isinstance(imp, LedgerImportPayload)
    ann = validate_payload(CommandKind.LEDGER_ANNOTATE, {"order_key": "a" * 16, "notes": "hi"})
    assert isinstance(ann, LedgerAnnotatePayload) and ann.model_fields_set == {"order_key", "notes"}
    ca = validate_payload(CommandKind.LEDGER_CA_REVIEWED, {"corporate_action_id": 3})
    assert isinstance(ca, LedgerCaReviewedPayload)
    for kind, p in (
        (CommandKind.LEDGER_IMPORT, imp),
        (CommandKind.LEDGER_ANNOTATE, ann),
        (CommandKind.LEDGER_CA_REVIEWED, ca),
    ):
        assert dedupe_key_for(kind, p) is None


def test_ledger_annotate_rejects_unknown_outcome_and_bad_key() -> None:
    with pytest.raises(ValidationError):
        validate_payload(
            CommandKind.LEDGER_ANNOTATE, {"order_key": "a" * 16, "outcome_override": "Won"}
        )
    with pytest.raises(ValidationError):
        validate_payload(CommandKind.LEDGER_ANNOTATE, {"order_key": "short"})


def test_ledger_import_content_over_the_configured_limit_is_rejected(monkeypatch) -> None:
    """F6: ``ledger.upload_max_bytes`` is enforced server-side, not just a fixed Field cap."""
    from src.common.config import get_config

    monkeypatch.setattr(get_config().ledger, "upload_max_bytes", 10)
    with pytest.raises(ValidationError):
        validate_payload(CommandKind.LEDGER_IMPORT, {"filename": "s.csv", "content": "x" * 11})
    # Still accepts content at or under the (lowered) limit.
    m = validate_payload(CommandKind.LEDGER_IMPORT, {"filename": "s.csv", "content": "x" * 10})
    assert m.content == "x" * 10
