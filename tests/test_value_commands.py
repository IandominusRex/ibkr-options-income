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


def test_a_second_tap_is_an_idempotent_success(value_book_db) -> None:
    """Review M6: the decision the command asks for is already applied (a crash between the
    commit and the mark, a double tap): applied, not failed, and nothing is rewritten."""
    from datetime import timedelta

    pid, fp = _proposal()
    _apply("value_approve", {"proposal_id": pid, "fingerprint": fp})
    first = _row(pid).decided_at
    again = _apply(
        "value_approve", {"proposal_id": pid, "fingerprint": fp}, now=NOW + timedelta(minutes=1)
    )
    assert again["decision"] == "approved" and again["already"] is True
    assert _row(pid).decided_at == first
    from src.value import cards

    assert cards.outcome_line("value_approve", again, None).startswith("Already approved")


def test_a_rejected_proposal_rejects_idempotently_but_refuses_an_approve(value_book_db) -> None:
    from src.value.commands import ValueCommandFailed

    pid, fp = _proposal()
    _apply("value_reject", {"proposal_id": pid, "fingerprint": fp})
    assert _apply("value_reject", {"proposal_id": pid, "fingerprint": fp})["already"] is True
    with pytest.raises(ValueCommandFailed) as exc:
        _apply("value_approve", {"proposal_id": pid, "fingerprint": fp})
    assert exc.value.reason == "already_rejected"
    assert _row(pid).status == "rejected"


def test_a_crash_re_run_is_marked_applied(value_book_db) -> None:
    """The drain re-applies a command whose mark was lost; the second apply is a success."""
    from src.value import commands as vcmd
    from src.value.store import value_session

    pid, fp = _proposal()

    def apply_fn(kind: str, payload: dict, by: str) -> dict:
        with value_session() as vs:
            return vcmd.apply(vs, kind, payload, requested_by=by, now=NOW, live=False)

    rows = [(1, "value_approve", {"proposal_id": pid, "fingerprint": fp}, "telegram", None)]
    marked: list = []
    vcmd.drain(rows, apply_fn, lambda *a: marked.append(a))  # the mark is "lost" after this
    (out,) = vcmd.drain(rows, apply_fn, lambda *a: marked.append(a))
    assert out.reason is None and out.result and out.result["already"] is True
    assert marked[1][2] is None  # no failure reason on the re-run


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
        (2, "value_reject", {"proposal_id": pid, "fingerprint": fp}, "web", None),
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
        (2, "value_reject", "web", "already_approved"),
        (3, "value_reject", "web", "no_such_proposal"),
        (4, "value_reject", "web", "handler_error"),
    ]


def test_replies_cover_telegram_order_kinds_and_failed_reads_only() -> None:
    """Review I4: a failed read-side command asked from Telegram answers in the value thread."""
    from src.value.commands import DrainOutcome, replies

    out = [
        DrainOutcome(1, "value_approve", "telegram", {"decision": "approved", "kind": "buy"}, None),
        DrainOutcome(2, "value_approve", "web", None, "stale_proposal"),  # the web shows its own
        DrainOutcome(3, "value_analyse", "telegram", None, "claude_off"),
        DrainOutcome(4, "value_refresh", "telegram", None, "no_data"),
        DrainOutcome(5, "value_refresh", "telegram", None, "research_unavailable"),
        DrainOutcome(6, "value_refresh", "telegram", {"symbol": "X"}, None),  # its card speaks
        DrainOutcome(7, "value_snapshot", "web", None, "no_data"),
        DrainOutcome(8, "value_analyse", "telegram", {"symbol": "X", "queued": True}, None),
    ]
    lines = replies(out)
    assert len(lines) == 4
    assert lines[0].startswith("Approved")
    assert lines[1] == "Not done (analyse): Claude's reads are switched off (value.claude.enabled)."
    assert lines[2] == "Not done (refresh): there are no price bars for that name yet."
    assert lines[3] == "Not done (refresh): the research database could not be read."


def test_the_entrypoint_drains_between_the_slow_steps() -> None:
    """Review I3: a tap must not wait out the night, the Claude queue and the cycle (the trading
    side expires a pending value command after approval.ttl_minutes). Structural: the entrypoint
    is never imported by a test, so its source is read."""
    import ast
    from pathlib import Path

    src = Path("scripts/run_value.py").read_text()
    tree = ast.parse(src)
    forced = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and getattr(n.func, "id", "") == "_between"
        and any(k.arg == "force" for k in n.keywords)
    ]
    assert len(forced) == 3  # after the night, after the queue, after the cycle
    run_queue_calls = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "run_queue"
    ]
    assert run_queue_calls and any(k.arg == "between" for k in run_queue_calls[0].keywords)
    # the helper itself drains (final review M6): a `_between` that forgot the drain would pass
    # every check above and still leave taps waiting out the night
    between = next(
        n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_between"
    )
    called = {getattr(n.func, "id", "") for n in ast.walk(between) if isinstance(n, ast.Call)}
    assert {"_drain_commands", "_post_outbox"} <= called


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


# --- Task 3: the 25% drawdown's "trim to half" (spec §9.6, rulings 3 and 11) ------------------

EPISODE = vc.trim_episode(100_000.0, NOW)


def _held(symbol: str, filled: float) -> int:
    from datetime import date

    from src.value.store import ValuePositionRow, value_session
    from tests.value_book_fixtures import order

    order(symbol, shares=filled, filled=filled)
    with value_session() as vs:
        pos = ValuePositionRow(
            symbol=symbol, list_name="deep_value", status="open", opened_on=date(2026, 10, 1)
        )
        vs.add(pos)
        vs.flush()
        return pos.id


def _offer(episode: str | None = EPISODE, **extra) -> None:
    from src.value.book import set_state
    from src.value.store import value_session

    state: dict = {"high": 100_000.0, "value": 74_000.0, "stop": True}
    if episode is not None:
        state |= {"trim_offered_at": NOW.isoformat(), "episode": episode}
    state |= extra
    with value_session() as vs:
        set_state(vs, "high_water", state, NOW)


def _sells() -> list:
    from sqlalchemy import select

    from src.value.store import ValueProposalRow, value_session

    with value_session() as vs:
        rows = list(
            vs.scalars(
                select(ValueProposalRow)
                .where(ValueProposalRow.kind == "sell")
                .order_by(ValueProposalRow.id)
            )
        )
        for r in rows:
            vs.expunge(r)
        return rows


def test_trim_halves_every_filled_position(value_book_db) -> None:
    _held("AAA", 10)
    _held("BBB", 7)
    _offer()
    result = _apply("value_trim", {"episode": EPISODE}, by="telegram")
    sells = _sells()
    assert [(s.symbol, s.shares) for s in sells] == [("AAA", 5.0), ("BBB", 3.0)]
    assert result == {"episode": EPISODE, "proposals": [s.id for s in sells]}
    for s in sells:
        assert s.status == "approved" and not s.needs_tap
        assert (s.reason, s.cause, s.decided_by) == ("drawdown_trim", "python", "telegram")


def test_trim_skips_a_name_with_an_open_sell(value_book_db) -> None:
    from tests.value_book_fixtures import proposal

    _held("AAA", 10)
    _held("BBB", 7)
    already = proposal("AAA", status="pending", kind="sell")
    _offer()
    _apply("value_trim", {"episode": EPISODE})
    sells = _sells()
    assert [(s.id, s.symbol, s.reason) for s in sells][0] == (already, "AAA", "tranche 1")
    assert [(s.symbol, s.shares, s.reason) for s in sells[1:]] == [("BBB", 3.0, "drawdown_trim")]


def test_trim_needs_the_current_episode(value_book_db) -> None:
    from src.value.commands import ValueCommandFailed

    _held("AAA", 10)
    with pytest.raises(ValueCommandFailed) as exc:
        _apply("value_trim", {"episode": EPISODE})
    assert exc.value.reason == "no_trim_offered"
    _offer()
    with pytest.raises(ValueCommandFailed) as exc:
        _apply("value_trim", {"episode": vc.trim_episode(99_000.0, NOW)})
    assert exc.value.reason == "stale_proposal"
    assert _sells() == []


def test_a_recovered_drawdown_refuses_the_trim_card(value_book_db) -> None:
    """Review I5 (operator ruling): the card stays actionable only while the book is still down
    by drawdown_trim_pct (25) from its high."""
    from src.value.commands import ValueCommandFailed

    _held("AAA", 10)
    _offer(value=80_000.0)  # 20% under the high: recovered since the offer
    with pytest.raises(ValueCommandFailed) as exc:
        _apply("value_trim", {"episode": EPISODE})
    assert exc.value.reason == "stale_proposal"
    assert _sells() == []


def test_an_old_trim_card_is_refused(value_book_db) -> None:
    from datetime import timedelta

    from src.value.book import TRIM_TTL_HOURS
    from src.value.commands import ValueCommandFailed

    _held("AAA", 10)
    _offer()
    with pytest.raises(ValueCommandFailed) as exc:
        _apply("value_trim", {"episode": EPISODE}, now=NOW + timedelta(hours=TRIM_TTL_HOURS + 1))
    assert exc.value.reason == "stale_proposal"
    assert _sells() == []
    assert "out of date" in cards_words("stale_proposal")  # the reply says why


def test_a_refused_trim_is_a_failed_command_with_a_reply(value_book_db) -> None:
    from datetime import timedelta

    from src.value import commands as vcmd
    from src.value.store import value_session

    _held("AAA", 10)
    _offer()
    marked: list = []

    def apply_fn(kind: str, payload: dict, by: str) -> dict:
        with value_session() as vs:
            return vcmd.apply(
                vs, kind, payload, requested_by=by, now=NOW + timedelta(hours=40), live=False
            )

    (out,) = vcmd.drain(
        [(1, "value_trim", {"episode": EPISODE}, "telegram", None)],
        apply_fn,
        lambda *a: marked.append(a),
    )
    assert out.reason == "stale_proposal" and marked[0][2] == "stale_proposal"
    assert vcmd.outcome_line(out.kind, None, out.reason).startswith("Not done (trim)")


def cards_words(reason: str) -> str:
    from src.value import cards

    return cards.reason_words(reason)


def test_a_still_valid_trim_card_is_applied(value_book_db) -> None:
    from datetime import timedelta

    from src.value.book import TRIM_TTL_HOURS

    _held("AAA", 10)
    _offer()
    out = _apply("value_trim", {"episode": EPISODE}, now=NOW + timedelta(hours=TRIM_TTL_HOURS - 1))
    assert len(out["proposals"]) == 1


def test_a_second_trim_is_an_idempotent_success(value_book_db) -> None:
    from src.value import cards

    _held("AAA", 10)
    _offer()
    _apply("value_trim", {"episode": EPISODE})
    again = _apply("value_trim", {"episode": EPISODE})
    assert again == {"episode": EPISODE, "proposals": [], "already": True}
    assert len(_sells()) == 1  # no second set of sales
    assert cards.outcome_line("value_trim", again, None) == "Trim: already made for this drawdown."


def test_the_trim_is_offered_once_per_episode(value_book_db) -> None:
    from datetime import timedelta

    from src.common.config import get_config
    from src.value import book, live
    from src.value.store import value_session

    cfg = get_config().value
    _held("AAA", 10)
    with value_session() as vs:  # the high is 1,000 and nothing is offered yet
        book.set_state(vs, "high_water", {"high": 1_000.0, "value": 1_000.0, "stop": False}, NOW)
    snap = live.Snapshot(net_liq=100_000.0, marks={"AAA": 74.0})  # 740: 26% under the high
    with value_session() as vs:
        first = live._high_water(vs, snap, cfg, NOW)
    with value_session() as vs:
        state = book.get_state(vs, "high_water") or {}
    assert first == vc.trim_episode(1_000.0, NOW) == state["episode"]
    assert state["trim_offered_at"] == NOW.isoformat() and state["stop"] is True
    with value_session() as vs:
        again = live._high_water(vs, snap, cfg, NOW + timedelta(minutes=15))
    with value_session() as vs:
        kept = book.get_state(vs, "high_water") or {}
    assert again is None
    assert (kept["episode"], kept["trim_offered_at"]) == (
        state["episode"],
        state["trim_offered_at"],
    )
    reset = book.reset_drawdown({**kept, "trimmed": True, "trimmed_at": NOW.isoformat()})
    assert reset == {"high": kept["value"], "value": kept["value"], "stop": False}


# --- Task 8: the read-side kinds (snapshot, refresh, analyse) ---------------------------------


@pytest.fixture()
def research(tmp_path, monkeypatch):
    """A research.db with two companies (STDY in the universe, OUT outside it) and SPY."""
    import json

    import pandas as pd
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    import src.common.value_inputs as vi
    from src.common.value_universe import ValueUniverse
    from src.research.store.models import Base, CompanyFactsRawRow, DailyBarRow, SymbolRow
    from src.value import service
    from tests.value_fixtures import AS_OF, companyfacts, price

    path = tmp_path / "research.db"
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    closes = price(30.0).closes
    days = pd.bdate_range(end=AS_OF, periods=len(closes)).date
    with Session(engine) as s:
        for sym, cik in (("STDY", "0000000001"), ("OUT", "0000000002")):
            s.add(SymbolRow(symbol=sym, cik=cik, name=sym))
            s.add(
                CompanyFactsRawRow(
                    cik=cik,
                    payload_json=json.dumps(companyfacts()),
                    fetched_at=datetime(2026, 3, 30),
                )
            )
            for d, c in zip(days, closes, strict=True):
                s.add(
                    DailyBarRow(
                        symbol=sym, date=d, open=c, high=c * 1.01, low=c * 0.99, close=c, volume=1e6
                    )
                )
        for d in days:
            s.add(DailyBarRow(symbol="SPY", date=d, open=500, high=500, low=500, close=500.0))
        s.commit()
    monkeypatch.setattr(vi, "_resolve_path", lambda: str(path))
    vi.reset_engine()
    monkeypatch.setattr(vi, "load_regime", lambda: "normal")
    monkeypatch.setattr(
        service,
        "build_value_universe",
        lambda cfg, universe: ValueUniverse(trading=["STDY"], evidence=["STDY"]),
    )
    monkeypatch.setattr("src.common.universe.effective_universe", lambda: {})
    yield days
    vi.reset_engine()


def _read_apply(
    kind: str, payload: dict, *, by: str = "telegram", live: bool = False, now: datetime = NOW
):
    import src.common.value_inputs as vi
    from src.value import commands as vcmd
    from src.value.store import value_session

    with value_session() as vs:
        return vcmd.apply(
            vs, kind, payload, requested_by=by, now=now, live=live, research=vi.research_read
        )


def _file(symbol: str):
    from src.value.store import ValueTickerFileRow, value_session

    with value_session() as vs:
        row = vs.get(ValueTickerFileRow, symbol)
        if row is not None:
            vs.expunge(row)
        return row


def test_snapshot_sets_last_viewed_at(value_book_db) -> None:
    from src.value import service
    from src.value.store import value_session
    from tests.value_book_fixtures import ticker_file

    ticker_file("LKUP", universe="lookup")
    assert _file("LKUP").last_viewed_at is None
    with value_session() as vs:
        assert service.followed_names(vs, NOW, 30) == []
    out = _read_apply("value_snapshot", {"symbol": "lkup", "fingerprint": {}})
    assert out["symbol"] == "LKUP"
    assert _file("LKUP").last_viewed_at == NOW
    with value_session() as vs:
        assert service.followed_names(vs, NOW, 30) == ["LKUP"]


def _carried(days, *, regime: str = "cautious"):
    """The fingerprint the API would carry: the input set of a score as of an earlier session."""
    import src.common.value_inputs as vi
    from src.common.config import get_config
    from src.value import service
    from src.value.ruleset import ruleset_id
    from src.value.store import ValueTickerFileRow, value_session

    version, digest = ruleset_id(get_config().value)
    seed = {
        "price_date": days[-10].isoformat(),
        "regime": regime,
        "ruleset_version": version,
        "ruleset_hash": digest,
    }
    with value_session() as vs, vi.research_read() as rs:
        fp = service.score_one(vs, rs, "STDY", now=NOW, fingerprint=seed, tag="trading")
        vs.delete(vs.get(ValueTickerFileRow, "STDY"))  # the API's file is not stored yet
    return fp


def test_snapshot_persists_exactly_the_input_set_it_carries(value_book_db, research) -> None:
    fp = _carried(research)
    assert fp.price_date == research[-10] and fp.regime == "cautious"
    assert _file("STDY") is None
    out = _read_apply(
        "value_snapshot", {"symbol": "STDY", "fingerprint": fp.model_dump(mode="json")}
    )
    row = _file("STDY")
    assert row is not None and row.fingerprint_key == fp.key()  # not the newest bar's, not "normal"
    assert row.as_of == research[-10] and row.last_viewed_at == NOW
    assert out.get("detail") != "moved"
    assert row.freshness_json is not None  # Task 8's column: the cheap parts it was computed on


def test_snapshot_records_moved_when_inputs_moved(value_book_db, research) -> None:
    fp = _carried(research)
    carried = fp.model_dump(mode="json")
    carried["price_close"] = float(carried["price_close"]) + 1.0  # the research worker moved
    out = _read_apply("value_snapshot", {"symbol": "STDY", "fingerprint": carried})
    assert out["detail"] == "moved"
    row = _file("STDY")
    assert row is not None and row.fingerprint_key == fp.key()  # its own recomputation stands


def test_snapshot_of_an_unchanged_card_restamps_a_stale_freshness_key(
    value_book_db, research
) -> None:
    """Review I2: the API found the file stale by the cheap parts, but the card's fingerprint is
    the stored one. The snapshot rewrites the freshness key from the parts now (no recompute),
    so the next open is answered `stored` instead of recomputing for ever."""
    import json

    import src.common.value_inputs as vi
    from src.common.config import get_config
    from src.common.value_freshness import is_current, rules_digest
    from src.value.store import ValueTickerFileRow, value_session

    fp = _carried(research, regime="normal")
    payload = {"symbol": "STDY", "fingerprint": fp.model_dump(mode="json")}
    _read_apply("value_snapshot", payload)  # stores the file
    cfg = get_config().value
    digest = rules_digest(cfg.rules.model_dump(mode="json"))
    with vi.research_read() as rs:
        parts = vi.current_fingerprint_parts(rs, "STDY")
    assert is_current(_file("STDY").freshness_json, parts, "normal", cfg.ruleset_version, digest)
    with value_session() as vs:  # a cheap part the card does not carry moved since
        row = vs.get(ValueTickerFileRow, "STDY")
        row.freshness_json = json.dumps({"key": "0123456789abcdef", "parts": {}})
    stale = _file("STDY")
    assert not is_current(stale.freshness_json, parts, "normal", cfg.ruleset_version, digest)
    _read_apply("value_snapshot", payload)  # the same card again
    after = _file("STDY")
    assert is_current(after.freshness_json, parts, "normal", cfg.ruleset_version, digest)
    assert after.computed_at == stale.computed_at  # the card was not recomputed


def test_refresh_scores_a_name_outside_the_universe_as_lookup(value_book_db, research) -> None:
    from src.common import value_view
    from src.common.config import get_config
    from src.value import cards, outbox
    from src.value.store import value_session

    out = _read_apply("value_refresh", {"symbol": "OUT"})
    assert out["symbol"] == "OUT" and out["universe"] == "lookup"
    row = _file("OUT")
    assert row is not None and row.universe == "lookup" and row.freshness_json
    assert _read_apply("value_refresh", {"symbol": "STDY"})["universe"] == "trading"
    # a Telegram request posts a one-name card, once; the web's does not
    with value_session() as vs:
        due = [c for c in outbox.due(vs, NOW, get_config().value) if c.key.startswith("ticker:")]
    assert {c.key for c in due} == {"ticker:OUT", "ticker:STDY"}
    view = value_view.read_ticker_file("OUT")
    assert view is not None
    card = cards.ticker_card(view)
    assert card.key == "ticker:OUT" and card.buttons == ()
    assert (
        "OUT" in card.text and view.verdict_deep in card.text and len(card.text) <= cards.MAX_CHARS
    )
    with value_session() as vs:
        outbox.mark_posted(vs, ["ticker:OUT", "ticker:STDY"], NOW)
    with value_session() as vs:
        assert not [
            c for c in outbox.due(vs, NOW, get_config().value) if c.key.startswith("ticker:")
        ]
    _read_apply("value_refresh", {"symbol": "OUT"}, by="web")
    with value_session() as vs:
        assert not [
            c for c in outbox.due(vs, NOW, get_config().value) if c.key.startswith("ticker:")
        ]


def test_analyse_queues_a_request_read(value_book_db, monkeypatch) -> None:
    from sqlalchemy import select

    from src.common.config import get_config
    from src.value.commands import ValueCommandFailed
    from src.value.store import ValueClaudeReadRow, value_session

    with pytest.raises(ValueCommandFailed) as exc:
        _read_apply("value_analyse", {"symbol": "STDY"})
    assert exc.value.reason == "claude_off"
    monkeypatch.setattr(get_config().value.claude, "enabled", True)
    out = _read_apply("value_analyse", {"symbol": "stdy"})
    assert out["symbol"] == "STDY"
    with value_session() as vs:
        (read,) = vs.scalars(select(ValueClaudeReadRow)).all()
    assert (read.symbol, read.kind, read.reason, read.priority, read.status) == (
        "STDY",
        "standard",
        "request",
        0,
        "queued",
    )


def test_live_allows_read_kinds(value_book_db, monkeypatch) -> None:
    from src.common.config import get_config
    from tests.value_book_fixtures import ticker_file

    monkeypatch.setattr(get_config().value.claude, "enabled", True)
    ticker_file("STDY")
    assert _read_apply("value_analyse", {"symbol": "STDY"}, live=True)["symbol"] == "STDY"
    snap = _read_apply("value_snapshot", {"symbol": "STDY", "fingerprint": {}}, live=True)
    assert snap["symbol"] == "STDY"
