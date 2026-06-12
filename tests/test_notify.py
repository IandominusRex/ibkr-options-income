"""Tests for Phase 6: Telegram notification + approval loop.

All tests mock python-telegram-bot — no live Telegram API needed.
DB tests use tmp_path to avoid touching real state.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.common.schemas import (
    ClaudeReview,
    OptionRight,
    ScoreCard,
    Strategy,
    TradeCandidate,
)
from src.notify.formatters import _md, format_candidate
from src.notify.sender import send_candidates
from src.storage.models import ApprovalRow, OrderRow

# --------------------------------------------------------------------------- #
# Shared fixtures
# --------------------------------------------------------------------------- #


def _make_candidate(
    candidate_id: str = "test-001",
    underlying: str = "AAPL",
    strategy: Strategy = Strategy.COVERED_CALL,
    premium: float = 1.50,
    blended_score: float = 74.5,
    rationale_tags: list[str] | None = None,
) -> TradeCandidate:
    if rationale_tags is None:
        rationale_tags = ["high_iv_rank", "liquid"]
    scores = ScoreCard(
        symbol=underlying,
        iv_score=72.0,
        technical_score=65.0,
        fundamental_score=80.0,
        liquidity_score=90.0,
        assignment_safety_score=70.0,
    )
    return TradeCandidate(
        candidate_id=candidate_id,
        strategy=strategy,
        underlying=underlying,
        right=OptionRight.CALL,
        strike=185.0,
        expiry=date(2026, 7, 17),
        contracts=1,
        premium=premium,
        collateral=18_000.0,
        roc_pct=0.83,
        annualized_yield_pct=18.5,
        breakeven=183.50,
        prob_profit=0.72,
        delta=0.28,
        iv_rank=65.0,
        dte=48,
        scores=scores,
        blended_score=blended_score,
        rationale_tags=rationale_tags,
    )


def _make_review(candidate_id: str = "test-001") -> ClaudeReview:
    return ClaudeReview(
        candidate_id=candidate_id,
        priority=1,
        recommendation="sell",
        why_attractive="High IV rank provides above-average premium income.",
        risks="Earnings next quarter could cause a gap move.",
        tradeoffs="Caps upside above strike.",
        assignment_considerations="Low probability given 0.28 delta.",
        rolling_considerations="Could roll up-and-out if stock approaches strike.",
        confidence=0.82,
    )


def _db_setup(tmp_path, monkeypatch) -> None:
    """Redirect DB to a temp file and re-initialise the ORM engine."""
    import src.storage.db as dbmod
    from src.common.config import Config

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{tmp_path / 't.db'}")
    dbmod.init_db()


# --------------------------------------------------------------------------- #
# formatters — format_candidate
# --------------------------------------------------------------------------- #


def test_format_with_review_contains_symbol_and_recommendation():
    text = format_candidate(_make_candidate(), _make_review())
    assert "AAPL" in text
    assert "SELL" in text


def test_format_without_review_contains_symbol_and_score():
    text = format_candidate(_make_candidate(), None)
    assert "AAPL" in text
    assert r"74\.5" in text  # dot is escaped in MarkdownV2
    assert "Claude Review" not in text


def test_format_without_review_no_claude_section():
    text = format_candidate(_make_candidate(), None)
    assert "Why attractive" not in text
    assert "Risks" not in text


def test_format_with_review_contains_key_fields():
    review = _make_review()
    text = format_candidate(_make_candidate(), review)
    assert "High IV rank" in text
    assert "Earnings next quarter" in text
    assert "Caps upside" in text


def test_format_escapes_special_chars_in_symbol():
    candidate = _make_candidate(underlying="SPY.X")
    text = format_candidate(candidate, None)
    # The dot in "SPY.X" must be escaped as "\."
    assert "SPY\\.X" in text


def test_format_escapes_special_chars_in_tags():
    candidate = _make_candidate(rationale_tags=["high-iv", "near_support"])
    text = format_candidate(candidate, None)
    # Hyphen and underscore must be escaped
    assert "high\\-iv" in text
    assert "near\\_support" in text


def test_format_includes_dte_and_expiry():
    text = format_candidate(_make_candidate(), None)
    assert "48" in text
    assert "2026" in text


def test_format_includes_premium_and_contract_value():
    text = format_candidate(_make_candidate(premium=1.50), None)
    assert r"1\.50" in text  # dot escaped in MarkdownV2
    assert "150" in text


def test_format_empty_tags_no_tags_line():
    candidate = _make_candidate(rationale_tags=[])
    text = format_candidate(candidate, None)
    assert "Tags:" not in text


def test_format_truncates_long_message():
    review = ClaudeReview(
        candidate_id="test-001",
        priority=1,
        recommendation="sell",
        why_attractive="x" * 1500,
        risks="y" * 1500,
        tradeoffs="z" * 1500,
        assignment_considerations="",
    )
    text = format_candidate(_make_candidate(), review)
    assert len(text) <= 4010  # small buffer for escape sequences


def test_md_escapes_all_special_chars():
    special = r"_.[]()~`>#+-=|{}.!\\"
    escaped = _md(special)
    # Every char in the output must be preceded by a backslash
    assert "\\" in escaped
    # No unescaped special char sequence (the function adds backslashes)
    assert "_" not in escaped.replace("\\_", "")


# --------------------------------------------------------------------------- #
# sender — send_candidates
# --------------------------------------------------------------------------- #


@pytest.fixture()
def mock_bot_cls():
    """Fixture: a Bot class whose instances behave as async context managers."""
    mock_instance = AsyncMock()
    mock_instance.send_message.return_value = MagicMock(message_id=42)
    mock_cls = MagicMock()
    mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
    mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)
    return mock_cls, mock_instance


def _mock_cfg(monkeypatch, *, token: str = "tok", chat_id: str = "99999", ttl: int = 60):
    mock = MagicMock()
    mock.secrets.telegram_bot_token = token
    mock.secrets.telegram_chat_id = chat_id
    mock.approval.ttl_minutes = ttl
    monkeypatch.setattr("src.notify.sender.get_config", lambda: mock)
    return mock


async def test_send_candidates_empty_list_no_bot_calls(mock_bot_cls, monkeypatch, tmp_path):
    _db_setup(tmp_path, monkeypatch)
    _mock_cfg(monkeypatch)
    mock_cls, _ = mock_bot_cls

    import src.storage.db as dbmod

    with patch("src.notify.sender.Bot", mock_cls):
        with dbmod.session_scope() as session:
            await send_candidates([], [], session)

    mock_cls.assert_not_called()


async def test_send_candidates_missing_token_skips(mock_bot_cls, monkeypatch, tmp_path):
    _db_setup(tmp_path, monkeypatch)
    _mock_cfg(monkeypatch, token="")
    mock_cls, _ = mock_bot_cls

    import src.storage.db as dbmod

    with patch("src.notify.sender.Bot", mock_cls):
        with dbmod.session_scope() as session:
            await send_candidates([_make_candidate()], [], session)

    mock_cls.assert_not_called()


async def test_send_candidates_one_message_per_candidate(mock_bot_cls, monkeypatch, tmp_path):
    _db_setup(tmp_path, monkeypatch)
    _mock_cfg(monkeypatch)
    mock_cls, mock_instance = mock_bot_cls

    import src.storage.db as dbmod

    candidates = [_make_candidate("c-001"), _make_candidate("c-002", underlying="MSFT")]

    with patch("src.notify.sender.Bot", mock_cls):
        with dbmod.session_scope() as session:
            await send_candidates(candidates, [], session)

    assert mock_instance.send_message.call_count == 2


async def test_send_candidates_persists_approval_row(mock_bot_cls, monkeypatch, tmp_path):
    _db_setup(tmp_path, monkeypatch)
    _mock_cfg(monkeypatch, chat_id="12345")
    mock_cls, mock_instance = mock_bot_cls
    mock_instance.send_message.return_value = MagicMock(message_id=77)

    from sqlalchemy import select

    import src.storage.db as dbmod

    with patch("src.notify.sender.Bot", mock_cls):
        with dbmod.session_scope() as session:
            await send_candidates([_make_candidate("c-001")], [], session)

    with dbmod.session_scope() as s:
        rows = s.execute(select(ApprovalRow)).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.candidate_id == "c-001"
    assert row.status == "pending"
    assert row.telegram_message_id == 77
    assert row.chat_id == "12345"


async def test_send_candidates_approval_has_expires_at(mock_bot_cls, monkeypatch, tmp_path):
    _db_setup(tmp_path, monkeypatch)
    _mock_cfg(monkeypatch, ttl=30)
    mock_cls, _ = mock_bot_cls

    from sqlalchemy import select

    import src.storage.db as dbmod

    with patch("src.notify.sender.Bot", mock_cls):
        with dbmod.session_scope() as session:
            await send_candidates([_make_candidate()], [], session)

    with dbmod.session_scope() as s:
        row = s.execute(select(ApprovalRow)).scalar_one()
    assert row.expires_at is not None
    delta = row.expires_at - row.created_at
    assert 25 * 60 < delta.total_seconds() < 35 * 60  # ~30 min


async def test_send_candidates_uses_review_when_available(mock_bot_cls, monkeypatch, tmp_path):
    _db_setup(tmp_path, monkeypatch)
    _mock_cfg(monkeypatch)
    mock_cls, mock_instance = mock_bot_cls

    import src.storage.db as dbmod

    candidate = _make_candidate("c-001")
    review = _make_review("c-001")

    with patch("src.notify.sender.Bot", mock_cls):
        with dbmod.session_scope() as session:
            await send_candidates([candidate], [review], session)

    call_kwargs = mock_instance.send_message.call_args.kwargs
    assert "SELL" in call_kwargs["text"]  # recommendation from review


async def test_send_candidates_no_review_for_unmatched(mock_bot_cls, monkeypatch, tmp_path):
    _db_setup(tmp_path, monkeypatch)
    _mock_cfg(monkeypatch)
    mock_cls, mock_instance = mock_bot_cls

    import src.storage.db as dbmod

    candidate = _make_candidate("c-001")
    review = _make_review("other-id")  # doesn't match

    with patch("src.notify.sender.Bot", mock_cls):
        with dbmod.session_scope() as session:
            await send_candidates([candidate], [review], session)

    call_kwargs = mock_instance.send_message.call_args.kwargs
    assert "Claude Review" not in call_kwargs["text"]


async def test_send_candidates_keyboard_uses_approval_id(mock_bot_cls, monkeypatch, tmp_path):
    _db_setup(tmp_path, monkeypatch)
    _mock_cfg(monkeypatch)
    mock_cls, mock_instance = mock_bot_cls

    import src.storage.db as dbmod

    with patch("src.notify.sender.Bot", mock_cls):
        with dbmod.session_scope() as session:
            await send_candidates([_make_candidate("c-001")], [], session)

    keyboard = mock_instance.send_message.call_args.kwargs["reply_markup"]
    buttons = keyboard.inline_keyboard[0]
    assert buttons[0].callback_data.startswith("approve:")
    assert buttons[1].callback_data.startswith("reject:")
    # Callback data must be short enough for Telegram's 64-byte limit
    assert all(len(b.callback_data.encode()) <= 64 for b in buttons)


# --------------------------------------------------------------------------- #
# approval_service — handle_button
# --------------------------------------------------------------------------- #


def _make_update(chat_id: int, callback_data: str) -> MagicMock:
    update = MagicMock()
    update.effective_chat.id = chat_id
    update.callback_query = AsyncMock()
    update.callback_query.data = callback_data
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    return update


def _mock_svc_cfg(monkeypatch, chat_id: str = "99999"):
    mock = MagicMock()
    mock.secrets.telegram_chat_id = chat_id
    monkeypatch.setattr("src.notify.approval_service.get_config", lambda: mock)
    return mock


async def test_callback_ignores_wrong_chat_id(monkeypatch, tmp_path):
    _db_setup(tmp_path, monkeypatch)
    _mock_svc_cfg(monkeypatch, chat_id="99999")

    from src.notify.approval_service import handle_button

    update = _make_update(chat_id=11111, callback_data="approve:1")
    await handle_button(update, MagicMock())

    update.callback_query.edit_message_text.assert_not_called()


async def test_callback_approve_sets_status_and_queues_order(monkeypatch, tmp_path):
    _db_setup(tmp_path, monkeypatch)
    _mock_svc_cfg(monkeypatch, chat_id="99999")

    from sqlalchemy import select

    import src.storage.db as dbmod

    # Insert a pending approval row.
    with dbmod.session_scope() as session:
        approval = ApprovalRow(
            candidate_id="c-approve-001",
            status="pending",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        session.add(approval)
        session.flush()
        approval_id = approval.id

    from src.notify.approval_service import handle_button

    update = _make_update(chat_id=99999, callback_data=f"approve:{approval_id}")
    await handle_button(update, MagicMock())

    with dbmod.session_scope() as s:
        row = s.get(ApprovalRow, approval_id)
        assert row.status == "approved"
        assert row.decided_at is not None
        orders = (
            s.execute(select(OrderRow).where(OrderRow.approval_id == approval_id)).scalars().all()
        )
    assert len(orders) == 1
    assert orders[0].state == "queued"
    assert orders[0].candidate_id == "c-approve-001"

    update.callback_query.edit_message_text.assert_called_once()


async def test_callback_reject_sets_status_no_order(monkeypatch, tmp_path):
    _db_setup(tmp_path, monkeypatch)
    _mock_svc_cfg(monkeypatch, chat_id="99999")

    from sqlalchemy import select

    import src.storage.db as dbmod

    with dbmod.session_scope() as session:
        approval = ApprovalRow(
            candidate_id="c-reject-001",
            status="pending",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        session.add(approval)
        session.flush()
        approval_id = approval.id

    from src.notify.approval_service import handle_button

    update = _make_update(chat_id=99999, callback_data=f"reject:{approval_id}")
    await handle_button(update, MagicMock())

    with dbmod.session_scope() as s:
        row = s.get(ApprovalRow, approval_id)
        assert row.status == "rejected"
        assert row.decided_at is not None
        orders = (
            s.execute(select(OrderRow).where(OrderRow.approval_id == approval_id)).scalars().all()
        )
    assert len(orders) == 0

    update.callback_query.edit_message_text.assert_called_once()


async def test_callback_unknown_approval_id_does_not_crash(monkeypatch, tmp_path):
    _db_setup(tmp_path, monkeypatch)
    _mock_svc_cfg(monkeypatch, chat_id="99999")

    from src.notify.approval_service import handle_button

    update = _make_update(chat_id=99999, callback_data="approve:99999")
    await handle_button(update, MagicMock())  # must not raise

    update.callback_query.edit_message_text.assert_called_once()
    assert "not found" in update.callback_query.edit_message_text.call_args.args[0].lower()


async def test_callback_malformed_data_is_ignored(monkeypatch, tmp_path):
    _db_setup(tmp_path, monkeypatch)
    _mock_svc_cfg(monkeypatch, chat_id="99999")

    from src.notify.approval_service import handle_button

    for bad_data in ("", "approve", "approve:notanint", "unknown:1"):
        update = _make_update(chat_id=99999, callback_data=bad_data)
        await handle_button(update, MagicMock())
        update.callback_query.edit_message_text.assert_not_called()


# --------------------------------------------------------------------------- #
# Order-creation idempotency — has_active_order + dedup guards
# --------------------------------------------------------------------------- #


def test_has_active_order_true_for_open_and_filled(tmp_path, monkeypatch):
    _db_setup(tmp_path, monkeypatch)
    import src.storage.db as dbmod
    from src.storage.orders import has_active_order

    for state in ("queued", "submitted", "filled", "partial"):
        with dbmod.session_scope() as s:
            s.add(OrderRow(candidate_id=f"cand-{state}", approval_id=None, state=state))
        with dbmod.session_scope() as s:
            assert has_active_order(s, f"cand-{state}") is True


def test_has_active_order_false_for_terminal_failures(tmp_path, monkeypatch):
    _db_setup(tmp_path, monkeypatch)
    import src.storage.db as dbmod
    from src.storage.orders import has_active_order

    for state in ("cancelled", "rejected"):
        with dbmod.session_scope() as s:
            s.add(OrderRow(candidate_id=f"cand-{state}", approval_id=None, state=state))
        with dbmod.session_scope() as s:
            # A TTL-cancelled / re-gate-rejected candidate may be re-proposed later.
            assert has_active_order(s, f"cand-{state}") is False


def test_has_active_order_false_when_absent(tmp_path, monkeypatch):
    _db_setup(tmp_path, monkeypatch)
    import src.storage.db as dbmod
    from src.storage.orders import has_active_order

    with dbmod.session_scope() as s:
        assert has_active_order(s, "never-seen") is False


async def test_auto_queue_creates_order_then_skips_duplicate(mock_bot_cls, monkeypatch, tmp_path):
    """Automated mode: the deterministic candidate_id must not stack duplicate orders
    when the 15-min loop re-surfaces the same candidate."""
    _db_setup(tmp_path, monkeypatch)
    _mock_cfg(monkeypatch)
    monkeypatch.setattr("src.notify.sender.is_automated_mode", lambda: True)
    mock_cls, _ = mock_bot_cls

    from sqlalchemy import select

    import src.storage.db as dbmod

    candidate = _make_candidate("dup-001")

    with patch("src.notify.sender.Bot", mock_cls):
        await send_candidates([candidate], [])  # first scan
        await send_candidates([candidate], [])  # 15 min later — same candidate_id

    with dbmod.session_scope() as s:
        orders = s.execute(
            select(OrderRow).where(OrderRow.candidate_id == "dup-001")
        ).scalars().all()
        approvals = s.execute(
            select(ApprovalRow).where(ApprovalRow.candidate_id == "dup-001")
        ).scalars().all()

    assert len(orders) == 1  # exactly one order despite two scans
    assert orders[0].state == "queued"
    assert len(approvals) == 1


async def test_manual_approve_skips_duplicate_when_active_order_exists(monkeypatch, tmp_path):
    """A candidate surfaced by two scans (two approvals) must not create two orders."""
    _db_setup(tmp_path, monkeypatch)
    _mock_svc_cfg(monkeypatch, chat_id="99999")

    from sqlalchemy import select

    import src.storage.db as dbmod
    from src.notify.approval_service import handle_button

    # Two pending approvals for the SAME candidate (e.g. surfaced by two scans).
    ids = []
    with dbmod.session_scope() as session:
        for _ in range(2):
            approval = ApprovalRow(
                candidate_id="dup-approve",
                status="pending",
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
            session.add(approval)
            session.flush()
            ids.append(approval.id)

    for approval_id in ids:
        update = _make_update(chat_id=99999, callback_data=f"approve:{approval_id}")
        await handle_button(update, MagicMock())

    with dbmod.session_scope() as s:
        orders = s.execute(
            select(OrderRow).where(OrderRow.candidate_id == "dup-approve")
        ).scalars().all()
        approvals = s.execute(
            select(ApprovalRow).where(ApprovalRow.candidate_id == "dup-approve")
        ).scalars().all()

    assert len(orders) == 1  # second approve did not create a duplicate order
    # Both approvals are marked approved (decision recorded), only one order queued.
    assert all(a.status == "approved" for a in approvals)


def test_partial_index_blocks_two_working_orders(tmp_path, monkeypatch):
    _db_setup(tmp_path, monkeypatch)
    from sqlalchemy.exc import IntegrityError

    import src.storage.db as dbmod

    with dbmod.session_scope() as s:
        s.add(OrderRow(candidate_id="idx-1", approval_id=1, state="queued"))

    raised = False
    try:
        with dbmod.session_scope() as s:
            s.add(OrderRow(candidate_id="idx-1", approval_id=2, state="submitted"))
    except IntegrityError:
        raised = True
    assert raised  # the partial unique index rejects a second working order


def test_partial_index_allows_new_order_after_terminal(tmp_path, monkeypatch):
    _db_setup(tmp_path, monkeypatch)
    from sqlalchemy import func, select

    import src.storage.db as dbmod

    with dbmod.session_scope() as s:
        s.add(OrderRow(candidate_id="idx-2", approval_id=1, state="cancelled"))
    # A cancelled order does not occupy the slot — a fresh working order is allowed.
    with dbmod.session_scope() as s:
        s.add(OrderRow(candidate_id="idx-2", approval_id=2, state="queued"))

    with dbmod.session_scope() as s:
        n = s.execute(
            select(func.count()).select_from(OrderRow).where(OrderRow.candidate_id == "idx-2")
        ).scalar_one()
    assert n == 2


async def test_reconcile_recovers_missed_fill(monkeypatch, tmp_path):
    """A SUBMITTED order whose fill event was lost is recovered from reqExecutions."""
    _db_setup(tmp_path, monkeypatch)
    _mock_svc_cfg(monkeypatch, chat_id="99999")

    from datetime import date as _date
    from types import SimpleNamespace

    import src.storage.db as dbmod
    from src.execution.reconciliation import reconcile_orphan_fills
    from src.storage.models import CandidateRow, FillRow

    with dbmod.session_scope() as s:
        s.add(
            CandidateRow(
                candidate_id="recon-1",
                run_id="r",
                strategy="covered_call",
                underlying="AAPL",
                right="C",
                strike=200.0,
                expiry=_date(2026, 7, 17),
                blended_score=70.0,
                payload={"contracts": 2},
            )
        )
        s.add(OrderRow(candidate_id="recon-1", approval_id=1, state="submitted", ib_order_id=555))

    fill = SimpleNamespace(
        execution=SimpleNamespace(orderId=555, shares=2.0, price=2.50, side="SLD", execId="e1"),
        contract=SimpleNamespace(
            symbol="AAPL", right="C", strike=200.0, lastTradeDateOrContractMonth="20260717"
        ),
        commissionReport=SimpleNamespace(commission=1.30),
    )
    ib = MagicMock()
    ib.reqExecutionsAsync = AsyncMock(return_value=[fill])
    bot = AsyncMock()

    await reconcile_orphan_fills(ib, bot, "99999")

    with dbmod.session_scope() as s:
        order = s.query(OrderRow).filter_by(candidate_id="recon-1").one()
        fills = s.query(FillRow).filter_by(candidate_id="recon-1").all()
    assert order.state == "filled"
    assert len(fills) == 1
    assert fills[0].avg_price == 2.50
    bot.send_message.assert_awaited()  # operator was notified


def test_net_entry_credit_qty_weighted_and_commission_haircut(tmp_path, monkeypatch):
    """F8: entry credit is the qty-weighted SELL average, net of entry commission."""
    _db_setup(tmp_path, monkeypatch)

    from datetime import date as _date

    import src.storage.db as dbmod
    from src.notify.approval_service import _net_entry_credit_per_share
    from src.storage.models import CandidateRow, FillRow

    exp = _date(2026, 7, 17)
    with dbmod.session_scope() as s:
        s.add(
            CandidateRow(
                candidate_id="c8",
                run_id="r",
                strategy="cash_secured_put",
                underlying="AAPL",
                right="P",
                strike=180.0,
                expiry=exp,
                blended_score=70.0,
                payload={},
            )
        )
        # Two SELL fills: 1 @ $2.00, 3 @ $1.00 → gross qty-weighted = $500 / 400 sh = $1.25/sh.
        # Commission $1.00 + $3.00 = $4.00 → net = ($500 − $4) / 400 = $1.24/sh.
        s.add(
            FillRow(order_id=1, candidate_id="c8", action="SELL", filled_qty=1, avg_price=2.00, commission=1.00)
        )
        s.add(
            FillRow(order_id=2, candidate_id="c8", action="SELL", filled_qty=3, avg_price=1.00, commission=3.00)
        )
        # A BUY fill must be ignored (it's a close, not part of the entry credit).
        s.add(
            FillRow(order_id=3, candidate_id="c8", action="BUY", filled_qty=4, avg_price=0.50, commission=2.00)
        )

    with dbmod.session_scope() as s:
        net = _net_entry_credit_per_share(s, "AAPL", 180.0, exp, "P")
    assert net is not None and abs(net - 1.24) < 1e-9


def test_net_entry_credit_none_when_no_sell_fills(tmp_path, monkeypatch):
    """Position opened outside the system (no SELL fill) → None, so profit-take skips it safely."""
    _db_setup(tmp_path, monkeypatch)

    from datetime import date as _date

    import src.storage.db as dbmod
    from src.notify.approval_service import _net_entry_credit_per_share

    with dbmod.session_scope() as s:
        net = _net_entry_credit_per_share(s, "AAPL", 180.0, _date(2026, 7, 17), "P")
    assert net is None


async def test_reconcile_no_executions_leaves_order_submitted(monkeypatch, tmp_path):
    _db_setup(tmp_path, monkeypatch)
    _mock_svc_cfg(monkeypatch, chat_id="99999")

    import src.storage.db as dbmod
    from src.execution.reconciliation import reconcile_orphan_fills
    from src.storage.models import FillRow

    with dbmod.session_scope() as s:
        s.add(OrderRow(candidate_id="recon-2", approval_id=1, state="submitted", ib_order_id=999))

    ib = MagicMock()
    ib.reqExecutionsAsync = AsyncMock(return_value=[])  # no matching execution
    bot = AsyncMock()

    await reconcile_orphan_fills(ib, bot, "99999")

    with dbmod.session_scope() as s:
        order = s.query(OrderRow).filter_by(candidate_id="recon-2").one()
        fills = s.query(FillRow).filter_by(candidate_id="recon-2").all()
    assert order.state == "submitted"  # untouched — never fabricates a fill
    assert len(fills) == 0


# --------------------------------------------------------------------------- #
# F7: external (manual TWS) buy-to-close reconciliation
# --------------------------------------------------------------------------- #

from datetime import date as _date  # noqa: E402


def _open_short(s, *, candidate_id="cc-1", underlying="AAPL", right="C", strike=200.0,
                expiry=_date(2026, 7, 17), sell_qty=2.0, order_id=1):
    """Seed a candidate + its SELL entry fill (an open short position)."""
    from src.storage.models import CandidateRow, FillRow, OrderRow

    s.add(
        CandidateRow(
            candidate_id=candidate_id, run_id="r", strategy="covered_call",
            underlying=underlying, right=right, strike=strike, expiry=expiry,
            blended_score=70.0, payload={"contracts": int(sell_qty)},
        )
    )
    s.add(OrderRow(id=order_id, candidate_id=candidate_id, approval_id=order_id, state="filled"))
    s.add(
        FillRow(order_id=order_id, candidate_id=candidate_id, action="SELL",
                filled_qty=sell_qty, avg_price=2.50)
    )


def _buy_exec(*, exec_id, symbol="AAPL", right="C", strike=200.0, expiry="20260717",
              qty=2.0, price=0.80, side="BOT", sec_type="OPT", commission=1.30):
    from types import SimpleNamespace

    return SimpleNamespace(
        execution=SimpleNamespace(execId=exec_id, shares=qty, price=price, side=side),
        contract=SimpleNamespace(
            symbol=symbol, right=right, strike=strike,
            lastTradeDateOrContractMonth=expiry, secType=sec_type,
        ),
        commissionReport=SimpleNamespace(commission=commission),
    )


async def test_external_close_records_buy_fill_under_original_candidate(tmp_path, monkeypatch):
    """A manual buy-to-close in TWS is recorded as a BUY fill under the original short (F7)."""
    _db_setup(tmp_path, monkeypatch)

    import src.storage.db as dbmod
    from src.execution.reconciliation import reconcile_external_closes
    from src.storage.models import FillRow

    with dbmod.session_scope() as s:
        _open_short(s, candidate_id="cc-1")

    ib = MagicMock()
    ib.reqExecutionsAsync = AsyncMock(return_value=[_buy_exec(exec_id="x1", qty=2.0, price=0.80)])
    bot = AsyncMock()

    await reconcile_external_closes(ib, bot, "99999")

    with dbmod.session_scope() as s:
        buys = s.query(FillRow).filter_by(candidate_id="cc-1", action="BUY").all()
    assert len(buys) == 1
    assert buys[0].avg_price == 0.80 and buys[0].filled_qty == 2.0
    assert buys[0].ib_exec_id == "x1"
    bot.send_message.assert_awaited()


async def test_external_close_is_idempotent_on_exec_id(tmp_path, monkeypatch):
    _db_setup(tmp_path, monkeypatch)

    import src.storage.db as dbmod
    from src.execution.reconciliation import reconcile_external_closes
    from src.storage.models import FillRow

    with dbmod.session_scope() as s:
        _open_short(s, candidate_id="cc-1", sell_qty=2.0)

    ib = MagicMock()
    ib.reqExecutionsAsync = AsyncMock(return_value=[_buy_exec(exec_id="x1", qty=2.0)])
    bot = AsyncMock()

    await reconcile_external_closes(ib, bot, "99999")
    await reconcile_external_closes(ib, bot, "99999")  # second sweep sees the same execId

    with dbmod.session_scope() as s:
        buys = s.query(FillRow).filter_by(candidate_id="cc-1", action="BUY").all()
    assert len(buys) == 1  # not double-recorded


async def test_external_close_skips_contract_we_never_sold(tmp_path, monkeypatch):
    _db_setup(tmp_path, monkeypatch)

    import src.storage.db as dbmod
    from src.execution.reconciliation import reconcile_external_closes
    from src.storage.models import FillRow

    with dbmod.session_scope() as s:
        _open_short(s, candidate_id="cc-1", strike=200.0)

    ib = MagicMock()
    # BUY on a different strike we never sold → not one of our shorts.
    ib.reqExecutionsAsync = AsyncMock(return_value=[_buy_exec(exec_id="x9", strike=999.0)])
    bot = AsyncMock()

    await reconcile_external_closes(ib, bot, "99999")

    with dbmod.session_scope() as s:
        assert s.query(FillRow).filter_by(action="BUY").count() == 0


async def test_external_close_skips_already_closed_position(tmp_path, monkeypatch):
    _db_setup(tmp_path, monkeypatch)

    import src.storage.db as dbmod
    from src.execution.reconciliation import reconcile_external_closes
    from src.storage.models import FillRow

    with dbmod.session_scope() as s:
        _open_short(s, candidate_id="cc-1", sell_qty=2.0)
        # Already bought back the full 2 contracts (recorded under a prior execId).
        s.add(FillRow(order_id=1, candidate_id="cc-1", action="BUY", filled_qty=2.0,
                      avg_price=0.50, ib_exec_id="prior"))

    ib = MagicMock()
    ib.reqExecutionsAsync = AsyncMock(return_value=[_buy_exec(exec_id="x2", qty=2.0)])
    bot = AsyncMock()

    await reconcile_external_closes(ib, bot, "99999")

    with dbmod.session_scope() as s:
        buys = s.query(FillRow).filter_by(candidate_id="cc-1", action="BUY").all()
    assert len(buys) == 1  # the new exec is ignored — position was already flat


async def test_external_close_ignores_sell_side_executions(tmp_path, monkeypatch):
    _db_setup(tmp_path, monkeypatch)

    import src.storage.db as dbmod
    from src.execution.reconciliation import reconcile_external_closes
    from src.storage.models import FillRow

    with dbmod.session_scope() as s:
        _open_short(s, candidate_id="cc-1")

    ib = MagicMock()
    ib.reqExecutionsAsync = AsyncMock(return_value=[_buy_exec(exec_id="s1", side="SLD")])
    bot = AsyncMock()

    await reconcile_external_closes(ib, bot, "99999")

    with dbmod.session_scope() as s:
        assert s.query(FillRow).filter_by(action="BUY").count() == 0
