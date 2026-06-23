"""Tests for Phase 6: Telegram notification + approval loop.

All tests mock python-telegram-bot — no live Telegram API needed.
DB tests use tmp_path to avoid touching real state.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.common.schemas import (
    AccountSnapshot,
    BuyCandidate,
    ClaudeReview,
    OptionRight,
    PositionSnapshot,
    ScoreCard,
    Strategy,
    TradeCandidate,
)
from src.notify.formatters import (
    _md,
    format_account_snapshot,
    format_candidate,
    format_screen_empty,
    format_screen_unchanged,
    format_status,
)
from src.notify.sender import send_buy_list, send_candidates, thread_id
from src.storage.models import ApprovalRow, OrderRow

# --------------------------------------------------------------------------- #
# Shared fixtures
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# thread_id helper
# --------------------------------------------------------------------------- #


def test_thread_id_parses_numeric_string():
    assert thread_id("52") == 52


def test_thread_id_empty_string_is_none():
    assert thread_id("") is None


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
        prob_otm=0.72,
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


def test_format_candidate_includes_premium_read():
    # _make_candidate has iv_rank=65 → "elevated — rich premium" 💡 line on the card.
    text = format_candidate(_make_candidate(), None)
    assert "💡" in text
    assert "elevated" in text


def test_format_near_miss_line_is_plain_text_with_reason():
    from src.notify.formatters import format_near_miss_line

    cand = _make_candidate(candidate_id="nm-1", underlying="NVDA")
    line = format_near_miss_line(cand, ["yield_below_minimum"])
    assert "closest: NVDA" in line
    assert "annualized yield below floor" in line
    # Plain text — no MarkdownV2 escaping.
    assert "\\" not in line


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
    # Body is truncated to _MAX_MESSAGE_LEN; footer is appended after, so allow a small overage.
    assert len(text) <= 4100
    assert "Sources:" in text


def test_md_escapes_all_special_chars():
    special = r"_.[]()~`>#+-=|{}.!\\"
    escaped = _md(special)
    # Every char in the output must be preceded by a backslash
    assert "\\" in escaped
    # No unescaped special char sequence (the function adds backslashes)
    assert "_" not in escaped.replace("\\_", "")


def test_format_quiet_cycle_renders_and_escapes():
    from src.notify.formatters import format_quiet_cycle

    text = format_quiet_cycle(skipped=42, total=50, move_pct=0.005, vix=14.2, at="11:30 ET")
    assert "Quiet cycle" in text
    assert "42/50" in text
    assert "0\\.5%" in text  # 0.5% with the period escaped for MarkdownV2
    assert "VIX 14\\.2" in text


def test_format_quiet_cycle_omits_vix_when_unknown():
    from src.notify.formatters import format_quiet_cycle

    text = format_quiet_cycle(skipped=1, total=3, move_pct=0.01, vix=None, at="09:50 ET")
    assert "VIX" not in text
    assert "1/3" in text


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
    mock.secrets.telegram_thread_scan = ""
    mock.secrets.telegram_thread_csp = "52"
    mock.secrets.telegram_thread_cc = "54"
    mock.secrets.telegram_thread_buy = "56"
    mock.secrets.telegram_thread_account = "58"
    mock.approval.ttl_minutes = ttl
    monkeypatch.setattr("src.notify.sender.get_config", lambda: mock)
    return mock


def _cc_kwargs(**overrides) -> dict:
    """Default send_candidates required kwargs for test calls (CC screen)."""
    kw: dict = dict(
        thread_id=54,
        label="Covered Calls",
        icon="🔵",
        hash_key="last_cc_hash",
        time_key="last_cc_time",
    )
    kw.update(overrides)
    return kw


async def test_send_candidates_empty_list_sends_diagnostic(mock_bot_cls, monkeypatch, tmp_path):
    """Empty candidate list → diagnostic 'no candidates' message sent (always-send-something rule)."""
    _db_setup(tmp_path, monkeypatch)
    _mock_cfg(monkeypatch)
    mock_cls, mock_instance = mock_bot_cls

    with patch("src.notify.sender.Bot", mock_cls):
        sent = await send_candidates([], [], **_cc_kwargs(empty_reason="0/4 passed the risk gate"))

    mock_instance.send_message.assert_called_once()
    text = mock_instance.send_message.call_args.kwargs["text"]
    assert "no candidates this cycle" in text
    assert "0/4 passed the risk gate" in text
    assert sent is True


async def test_send_candidates_empty_with_near_miss_appends_closest(
    mock_bot_cls, monkeypatch, tmp_path
):
    """Empty screen + a near-miss candidate → diagnostic names the closest failed contract."""
    _db_setup(tmp_path, monkeypatch)
    _mock_cfg(monkeypatch)
    mock_cls, mock_instance = mock_bot_cls

    near = _make_candidate(candidate_id="nm-1", underlying="NVDA")
    with patch("src.notify.sender.Bot", mock_cls):
        sent = await send_candidates(
            [],
            [],
            **_cc_kwargs(
                empty_reason="0/4 passed the risk gate",
                near_misses=[(near, ["yield_below_minimum"])],
            ),
        )

    text = mock_instance.send_message.call_args.kwargs["text"]
    assert "no candidates this cycle" in text
    assert "closest: NVDA" in text
    assert "annualized yield below floor" in text
    assert sent is True


async def test_send_candidates_empty_near_misses_top3_with_more(
    mock_bot_cls, monkeypatch, tmp_path
):
    """Up to 3 near-misses are listed; a trailing '…and N more' signals the truncated rest."""
    _db_setup(tmp_path, monkeypatch)
    _mock_cfg(monkeypatch)
    mock_cls, mock_instance = mock_bot_cls

    near_misses = [
        (_make_candidate(candidate_id="nm-1", underlying="NVDA"), ["yield_below_minimum"]),
        (_make_candidate(candidate_id="nm-2", underlying="AAPL"), ["delta_out_of_range"]),
        (_make_candidate(candidate_id="nm-3", underlying="MSFT"), ["iv_rank_below_minimum"]),
    ]
    with patch("src.notify.sender.Bot", mock_cls):
        await send_candidates(
            [],
            [],
            **_cc_kwargs(near_misses=near_misses, near_miss_more=5),
        )

    text = mock_instance.send_message.call_args.kwargs["text"]
    assert text.count("closest:") == 3
    assert "closest: NVDA" in text
    assert "closest: MSFT" in text
    assert "…and 5 more that didn't pass" in text


async def test_send_candidates_missing_token_skips(mock_bot_cls, monkeypatch, tmp_path):
    _db_setup(tmp_path, monkeypatch)
    _mock_cfg(monkeypatch, token="")
    mock_cls, _ = mock_bot_cls

    with patch("src.notify.sender.Bot", mock_cls):
        await send_candidates([_make_candidate()], [], **_cc_kwargs())

    mock_cls.assert_not_called()


async def test_send_candidates_one_message_per_candidate(mock_bot_cls, monkeypatch, tmp_path):
    _db_setup(tmp_path, monkeypatch)
    _mock_cfg(monkeypatch)
    mock_cls, mock_instance = mock_bot_cls

    import src.storage.db as dbmod

    candidates = [_make_candidate("c-001"), _make_candidate("c-002", underlying="MSFT")]

    with patch("src.notify.sender.Bot", mock_cls):
        with dbmod.session_scope() as session:
            await send_candidates(candidates, [], session=session, **_cc_kwargs())

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
            await send_candidates([_make_candidate("c-001")], [], session=session, **_cc_kwargs())

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
            await send_candidates([_make_candidate()], [], session=session, **_cc_kwargs())

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
            await send_candidates([candidate], [review], session=session, **_cc_kwargs())

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
            await send_candidates([candidate], [review], session=session, **_cc_kwargs())

    call_kwargs = mock_instance.send_message.call_args.kwargs
    assert "Claude Review" not in call_kwargs["text"]


async def test_send_candidates_keyboard_uses_approval_id(mock_bot_cls, monkeypatch, tmp_path):
    _db_setup(tmp_path, monkeypatch)
    _mock_cfg(monkeypatch)
    mock_cls, mock_instance = mock_bot_cls

    import src.storage.db as dbmod

    with patch("src.notify.sender.Bot", mock_cls):
        with dbmod.session_scope() as session:
            await send_candidates([_make_candidate("c-001")], [], session=session, **_cc_kwargs())

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
        await send_candidates([candidate], [], **_cc_kwargs())  # first scan
        await send_candidates([candidate], [], **_cc_kwargs())  # 15 min later — same candidate_id

    with dbmod.session_scope() as s:
        orders = (
            s.execute(select(OrderRow).where(OrderRow.candidate_id == "dup-001")).scalars().all()
        )
        approvals = (
            s.execute(select(ApprovalRow).where(ApprovalRow.candidate_id == "dup-001"))
            .scalars()
            .all()
        )

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
        orders = (
            s.execute(select(OrderRow).where(OrderRow.candidate_id == "dup-approve"))
            .scalars()
            .all()
        )
        approvals = (
            s.execute(select(ApprovalRow).where(ApprovalRow.candidate_id == "dup-approve"))
            .scalars()
            .all()
        )

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


async def test_reconcile_orphan_fills_does_not_hang_on_dead_socket(monkeypatch, tmp_path):
    """Regression (2026-06-22): a half-dead TWS socket makes reqExecutions never return.

    The bare ``await`` used to hang the approval-service startup forever, which silently
    stopped the 15-min intraday scan loop from ever being created. reqExecutions is now
    bounded, so reconcile must return promptly (skipping the pass) instead of blocking.
    """
    import asyncio
    from datetime import date as _date

    _db_setup(tmp_path, monkeypatch)
    _mock_svc_cfg(monkeypatch, chat_id="99999")

    import src.execution.reconciliation as recon
    import src.storage.db as dbmod
    from src.execution.reconciliation import reconcile_orphan_fills
    from src.storage.models import CandidateRow, FillRow

    # Shrink the bound so the test is fast; the real value is 30s.
    monkeypatch.setattr(recon, "_REQ_EXECUTIONS_TIMEOUT_SECONDS", 0.2)

    with dbmod.session_scope() as s:
        s.add(
            CandidateRow(
                candidate_id="recon-hang",
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
        s.add(
            OrderRow(candidate_id="recon-hang", approval_id=1, state="submitted", ib_order_id=555)
        )

    async def _never_returns():
        await asyncio.Event().wait()  # simulates execDetailsEnd that never arrives

    ib = MagicMock()
    ib.reqExecutionsAsync = MagicMock(side_effect=lambda: _never_returns())
    bot = AsyncMock()

    # Must complete well within the outer guard — i.e. it did NOT hang.
    await asyncio.wait_for(reconcile_orphan_fills(ib, bot, "99999"), timeout=5.0)

    # The pass was skipped: the order is untouched, no fill recorded.
    with dbmod.session_scope() as s:
        order = s.query(OrderRow).filter_by(candidate_id="recon-hang").one()
        fills = s.query(FillRow).filter_by(candidate_id="recon-hang").all()
    assert order.state == "submitted"
    assert fills == []


async def test_reconcile_recovers_fill_for_rejected_order_with_order_id(monkeypatch, tmp_path):
    """N8: a REJECTED order (executor except path) whose SELL actually filled at the broker is
    still recovered, because it carries an ib_order_id. A pre-placement cancel (no ib_order_id)
    must be left alone."""
    _db_setup(tmp_path, monkeypatch)
    _mock_svc_cfg(monkeypatch, chat_id="99999")

    from datetime import date as _date
    from types import SimpleNamespace

    import src.storage.db as dbmod
    from src.execution.reconciliation import reconcile_orphan_fills
    from src.storage.models import CandidateRow, FillRow

    with dbmod.session_scope() as s:
        for cid in ("recon-rej", "recon-ttl"):
            s.add(
                CandidateRow(
                    candidate_id=cid,
                    run_id="r",
                    strategy="cash_secured_put",
                    underlying="AAPL",
                    right="P",
                    strike=180.0,
                    expiry=_date(2026, 7, 17),
                    blended_score=70.0,
                    payload={"contracts": 1},
                )
            )
        # Placed then the monitor loop threw → REJECTED, but it carries an ib_order_id.
        s.add(OrderRow(candidate_id="recon-rej", approval_id=1, state="rejected", ib_order_id=777))
        # Pre-placement cancel (TTL/re-validation) → no ib_order_id → must NOT be touched.
        s.add(OrderRow(candidate_id="recon-ttl", approval_id=2, state="cancelled"))

    fill = SimpleNamespace(
        execution=SimpleNamespace(orderId=777, shares=1.0, price=1.50, side="SLD", execId="e9"),
        contract=SimpleNamespace(
            symbol="AAPL", right="P", strike=180.0, lastTradeDateOrContractMonth="20260717"
        ),
        commissionReport=SimpleNamespace(commission=0.65),
    )
    ib = MagicMock()
    ib.reqExecutionsAsync = AsyncMock(return_value=[fill])
    bot = AsyncMock()

    await reconcile_orphan_fills(ib, bot, "99999")

    with dbmod.session_scope() as s:
        rej = s.query(OrderRow).filter_by(candidate_id="recon-rej").one()
        ttl = s.query(OrderRow).filter_by(candidate_id="recon-ttl").one()
        fills = s.query(FillRow).filter_by(candidate_id="recon-rej").all()
    assert rej.state == "filled"  # the real fill was recovered
    assert len(fills) == 1 and fills[0].avg_price == 1.50
    assert ttl.state == "cancelled"  # pre-placement cancel left untouched


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
            FillRow(
                order_id=1,
                candidate_id="c8",
                action="SELL",
                filled_qty=1,
                avg_price=2.00,
                commission=1.00,
            )
        )
        s.add(
            FillRow(
                order_id=2,
                candidate_id="c8",
                action="SELL",
                filled_qty=3,
                avg_price=1.00,
                commission=3.00,
            )
        )
        # A BUY fill must be ignored (it's a close, not part of the entry credit).
        s.add(
            FillRow(
                order_id=3,
                candidate_id="c8",
                action="BUY",
                filled_qty=4,
                avg_price=0.50,
                commission=2.00,
            )
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


def _open_short(
    s,
    *,
    candidate_id="cc-1",
    underlying="AAPL",
    right="C",
    strike=200.0,
    expiry=_date(2026, 7, 17),
    sell_qty=2.0,
    order_id=1,
):
    """Seed a candidate + its SELL entry fill (an open short position)."""
    from src.storage.models import CandidateRow, FillRow, OrderRow

    s.add(
        CandidateRow(
            candidate_id=candidate_id,
            run_id="r",
            strategy="covered_call",
            underlying=underlying,
            right=right,
            strike=strike,
            expiry=expiry,
            blended_score=70.0,
            payload={"contracts": int(sell_qty)},
        )
    )
    s.add(OrderRow(id=order_id, candidate_id=candidate_id, approval_id=order_id, state="filled"))
    s.add(
        FillRow(
            order_id=order_id,
            candidate_id=candidate_id,
            action="SELL",
            filled_qty=sell_qty,
            avg_price=2.50,
        )
    )


def _buy_exec(
    *,
    exec_id,
    symbol="AAPL",
    right="C",
    strike=200.0,
    expiry="20260717",
    qty=2.0,
    price=0.80,
    side="BOT",
    sec_type="OPT",
    commission=1.30,
):
    from types import SimpleNamespace

    return SimpleNamespace(
        execution=SimpleNamespace(execId=exec_id, shares=qty, price=price, side=side),
        contract=SimpleNamespace(
            symbol=symbol,
            right=right,
            strike=strike,
            lastTradeDateOrContractMonth=expiry,
            secType=sec_type,
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
        s.add(
            FillRow(
                order_id=1,
                candidate_id="cc-1",
                action="BUY",
                filled_qty=2.0,
                avg_price=0.50,
                ib_exec_id="prior",
            )
        )

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


# --------------------------------------------------------------------------- #
# send_buy_list — MarkdownV2 escaping
# --------------------------------------------------------------------------- #


async def test_send_buy_list_escapes_pipes_and_special_chars(monkeypatch):
    cfg = MagicMock()
    cfg.secrets.telegram_bot_token = "tok"
    cfg.secrets.telegram_thread_buy = ""
    monkeypatch.setattr("src.notify.sender.get_config", lambda: cfg)

    mock_instance = AsyncMock()
    mock_cls = MagicMock()
    mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
    mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)

    candidates = [
        BuyCandidate(
            symbol="AAPL",
            score=85.0,
            iv_rank=42.0,
            quality_flag=True,
            technical_regime="up_trend",
            rationale="Strong fundamentals (P/E < 30) | momentum intact.",
        )
    ]

    with patch("src.notify.sender.Bot", mock_cls):
        await send_buy_list(candidates, chat_id="99999")

    mock_instance.send_message.assert_called_once()
    text = mock_instance.send_message.call_args.kwargs["text"]
    # Every literal '|' must be escaped — Telegram rejects a bare '|' in MarkdownV2.
    # '||' is the spoiler syntax and is intentionally unescaped; strip those first.
    assert "|" not in text.replace("\\|", "").replace("||", "")
    assert "85/100" in text
    assert "AAPL" in text


# --------------------------------------------------------------------------- #
# S6 — output-frequency suppression (intraday loop only)
# --------------------------------------------------------------------------- #


async def test_send_candidates_suppresses_unchanged_pending(mock_bot_cls, monkeypatch, tmp_path):
    """Second intraday cycle with a still-pending same-band card → digest, no new approval row."""
    _db_setup(tmp_path, monkeypatch)
    _mock_cfg(monkeypatch)
    mock_cls, mock_instance = mock_bot_cls

    from sqlalchemy import select

    import src.storage.db as dbmod

    cand = _make_candidate("c-001")
    kw = _cc_kwargs(suppress_unchanged=True)
    with patch("src.notify.sender.Bot", mock_cls):
        # First cycle: full card sent, one PENDING approval persisted.
        with dbmod.session_scope() as s:
            await send_candidates([cand], [], session=s, **kw)
        assert mock_instance.send_message.call_count == 1

        mock_instance.send_message.reset_mock()
        # Second cycle: unchanged → suppressed to a single digest, still no second approval.
        with dbmod.session_scope() as s:
            await send_candidates([cand], [], session=s, **kw)

    assert mock_instance.send_message.call_count == 1
    digest_text = mock_instance.send_message.call_args.kwargs["text"]
    assert "unchanged" in digest_text.lower()
    with dbmod.session_scope() as s:
        rows = s.execute(select(ApprovalRow)).scalars().all()
    assert len(rows) == 1  # no duplicate approval created for the suppressed cycle


async def test_suppress_sends_full_card_without_prior(mock_bot_cls, monkeypatch, tmp_path):
    """suppress_unchanged=True but no prior pending card → normal full card + approval row."""
    _db_setup(tmp_path, monkeypatch)
    _mock_cfg(monkeypatch)
    mock_cls, mock_instance = mock_bot_cls

    from sqlalchemy import select

    import src.storage.db as dbmod

    with patch("src.notify.sender.Bot", mock_cls):
        with dbmod.session_scope() as s:
            await send_candidates(
                [_make_candidate("c-xyz")], [], session=s, **_cc_kwargs(suppress_unchanged=True)
            )

    assert mock_instance.send_message.call_count == 1
    with dbmod.session_scope() as s:
        assert len(s.execute(select(ApprovalRow)).scalars().all()) == 1


async def test_manual_send_ignores_suppression(mock_bot_cls, monkeypatch, tmp_path):
    """Manual /scan (suppress_unchanged=False) re-sends a full card even with a pending one."""
    _db_setup(tmp_path, monkeypatch)
    _mock_cfg(monkeypatch)
    mock_cls, mock_instance = mock_bot_cls

    from sqlalchemy import select

    import src.storage.db as dbmod

    cand = _make_candidate("c-001")
    with patch("src.notify.sender.Bot", mock_cls):
        with dbmod.session_scope() as s:
            await send_candidates([cand], [], session=s, **_cc_kwargs(suppress_unchanged=True))
        mock_instance.send_message.reset_mock()
        with dbmod.session_scope() as s:
            await send_candidates([cand], [], session=s, **_cc_kwargs())  # suppress_unchanged=False

    assert mock_instance.send_message.call_count == 1
    with dbmod.session_scope() as s:
        assert len(s.execute(select(ApprovalRow)).scalars().all()) == 2  # fresh card each time


async def test_score_band_change_resends_full_card(mock_bot_cls, monkeypatch, tmp_path):
    """A materially different blended score (new band) is not suppressed."""
    _db_setup(tmp_path, monkeypatch)
    _mock_cfg(monkeypatch)
    mock_cls, mock_instance = mock_bot_cls

    from sqlalchemy import select

    import src.storage.db as dbmod

    with patch("src.notify.sender.Bot", mock_cls):
        with dbmod.session_scope() as s:
            await send_candidates(
                [_make_candidate("c-001", blended_score=74.5)],
                [],
                session=s,
                **_cc_kwargs(suppress_unchanged=True),
            )
        mock_instance.send_message.reset_mock()
        with dbmod.session_scope() as s:
            await send_candidates(
                [_make_candidate("c-001", blended_score=92.0)],
                [],
                session=s,
                **_cc_kwargs(suppress_unchanged=True),
            )

    # New score band (14 → 18) → fresh full card, not a digest.
    text = mock_instance.send_message.call_args.kwargs["text"]
    assert "unchanged" not in text.lower()
    with dbmod.session_scope() as s:
        assert len(s.execute(select(ApprovalRow)).scalars().all()) == 2


def _buy_cfg(monkeypatch):
    cfg = MagicMock()
    cfg.secrets.telegram_bot_token = "tok"
    cfg.secrets.telegram_thread_buy = ""
    monkeypatch.setattr("src.notify.sender.get_config", lambda: cfg)
    return cfg


async def test_send_buy_list_digest_when_unchanged(monkeypatch, tmp_path):
    _db_setup(tmp_path, monkeypatch)
    _buy_cfg(monkeypatch)

    mock_instance = AsyncMock()
    mock_cls = MagicMock()
    mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
    mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)

    cands = [BuyCandidate(symbol="AAPL", score=85.0), BuyCandidate(symbol="MSFT", score=70.0)]

    with patch("src.notify.sender.Bot", mock_cls):
        # First send: full list, hash stored.
        await send_buy_list(cands, chat_id="99999", suppress_unchanged=True)
        first_text = mock_instance.send_message.call_args.kwargs["text"]
        assert "Buy\\-to\\-Own Candidates" in first_text

        mock_instance.send_message.reset_mock()
        # Second send, identical → compact digest.
        await send_buy_list(cands, chat_id="99999", suppress_unchanged=True)

    digest = mock_instance.send_message.call_args.kwargs["text"]
    assert "unchanged" in digest.lower()
    assert "Candidates" not in digest  # not the full screen


async def test_send_buy_list_full_when_changed(monkeypatch, tmp_path):
    _db_setup(tmp_path, monkeypatch)
    _buy_cfg(monkeypatch)

    mock_instance = AsyncMock()
    mock_cls = MagicMock()
    mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
    mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)

    with patch("src.notify.sender.Bot", mock_cls):
        await send_buy_list([BuyCandidate(symbol="AAPL", score=85.0)], "9", suppress_unchanged=True)
        mock_instance.send_message.reset_mock()
        # Different symbol set → full list again, not a digest.
        await send_buy_list([BuyCandidate(symbol="NVDA", score=88.0)], "9", suppress_unchanged=True)

    text = mock_instance.send_message.call_args.kwargs["text"]
    assert "Buy\\-to\\-Own Candidates" in text


# --------------------------------------------------------------------------- #
# S9 — scan-overrun observability (counters in /status + throttled warning)
# --------------------------------------------------------------------------- #


def test_format_status_omits_scan_line_when_not_tracked():
    text = format_status([], None, 0, 0)
    assert "intraday scan" not in text


def test_format_status_shows_run_count():
    text = format_status([], None, 0, 0, scans_run=24, scans_skipped=0)
    assert "24 intraday scans run" in text
    assert "skipped" not in text


def test_format_status_flags_skipped_cycles():
    text = format_status([], None, 0, 0, scans_run=20, scans_skipped=6)
    assert "20 intraday scans run" in text
    assert "6 skipped" in text


async def test_note_intraday_skip_counts_and_throttles():
    from src.notify.approval_service import _note_intraday_skip

    bot = AsyncMock()
    bot_data: dict = {}

    # First skip: counts to 1 and sends a warning.
    await _note_intraday_skip(bot_data, bot, "123", "overran")
    assert bot_data["intraday_scans_skipped"] == 1
    assert bot.send_message.call_count == 1

    # Second skip immediately after: counts to 2 but warning is throttled (no new send).
    await _note_intraday_skip(bot_data, bot, "123", "overran")
    assert bot_data["intraday_scans_skipped"] == 2
    assert bot.send_message.call_count == 1


async def test_note_intraday_skip_warns_again_after_interval():
    from src.notify.approval_service import _OVERRUN_WARN_INTERVAL, _note_intraday_skip

    bot = AsyncMock()
    bot_data: dict = {}

    await _note_intraday_skip(bot_data, bot, "123", "overran")
    assert bot.send_message.call_count == 1

    # Backdate the last-warn time past the throttle interval → next skip warns again.
    bot_data["_overrun_warn_at"] = datetime.now(UTC) - _OVERRUN_WARN_INTERVAL - timedelta(seconds=1)
    await _note_intraday_skip(bot_data, bot, "123", "overran")
    assert bot.send_message.call_count == 2


async def test_notify_scan_blocked_always_sends_with_detail():
    """A half-dead-socket block is rare and actionable — unlike skips it is never throttled,
    and the message must carry the specific reason + detail so the operator knows what blocked."""
    from src.notify.approval_service import _notify_scan_blocked

    bot = AsyncMock()
    await _notify_scan_blocked(bot, "123", "data farm not responding", "probe timed out on SPY")
    assert bot.send_message.call_count == 1
    text = bot.send_message.call_args.kwargs["text"]
    assert "Scan blocked" in text
    assert "data farm not responding" in text
    assert "probe timed out on SPY" in text

    # No throttling: a second block sends again immediately.
    await _notify_scan_blocked(bot, "123", "still down", "second probe failed")
    assert bot.send_message.call_count == 2


async def test_notify_scan_blocked_swallows_send_failure():
    from src.notify.approval_service import _notify_scan_blocked

    bot = AsyncMock()
    bot.send_message.side_effect = RuntimeError("telegram down")
    # Must not raise — a Telegram outage cannot be allowed to crash the intraday loop.
    await _notify_scan_blocked(bot, "123", "reason", "detail")


async def test_force_scan_reconnect_disconnects_and_swallows():
    from src.notify.approval_service import _force_scan_reconnect

    ib = MagicMock()
    await _force_scan_reconnect(ib)
    ib.disconnect.assert_called_once()

    # A disconnect that itself raises must not propagate (best-effort recovery).
    ib.disconnect.side_effect = RuntimeError("already gone")
    await _force_scan_reconnect(ib)


# --------------------------------------------------------------------------- #
# format_screen_unchanged / format_screen_empty
# --------------------------------------------------------------------------- #


def test_format_screen_unchanged_pluralizes_and_escapes():
    text = format_screen_unchanged("🟢", "Buy-to-Own", 8, "12:33", "name")
    assert text == "🟢 *Buy\\-to\\-Own* — 8 names unchanged since 12:33 \\(no new screens\\)"


def test_format_screen_unchanged_singular_no_plural():
    text = format_screen_unchanged("🟣", "Cash-Secured Puts", 1, "09:15", "candidate")
    assert (
        text == "🟣 *Cash\\-Secured Puts* — 1 candidate unchanged since 09:15 \\(no new screens\\)"
    )


def test_format_screen_empty():
    text = format_screen_empty("🔵", "Covered Calls", "0/4 candidates passed the risk gate")
    assert (
        text
        == "🔵 *Covered Calls* — no candidates this cycle\n_0/4 candidates passed the risk gate_"
    )


# --------------------------------------------------------------------------- #
# format_account_snapshot
# --------------------------------------------------------------------------- #


def _snapshot_account(net_liq: float = 100_000.0) -> AccountSnapshot:
    return AccountSnapshot(
        account="DU123456",
        net_liquidation=net_liq,
        total_cash=50_000.0,
        buying_power=80_000.0,
        maintenance_margin=5_000.0,
        excess_liquidity=75_000.0,
    )


def _snapshot_stock(
    symbol: str = "AAPL",
    position: float = 100.0,
    avg_cost: float = 180.0,
    market_value: float | None = 18_200.0,
    unrealized_pnl: float | None = 200.0,
) -> PositionSnapshot:
    return PositionSnapshot(
        symbol=symbol,
        sec_type="STK",
        position=position,
        avg_cost=avg_cost,
        market_value=market_value,
        unrealized_pnl=unrealized_pnl,
        underlying=symbol,
    )


def _snapshot_option(
    underlying: str,
    right: OptionRight,
    strike: float,
    avg_cost: float,
    unrealized_pnl: float,
    position: float = -1.0,
    dte: int = 14,
) -> PositionSnapshot:
    return PositionSnapshot(
        symbol=f"{underlying}  OPT",
        sec_type="OPT",
        position=position,
        avg_cost=avg_cost,
        right=right,
        strike=strike,
        expiry=date.today() + timedelta(days=dte),
        underlying=underlying,
        unrealized_pnl=unrealized_pnl,
    )


def test_format_account_snapshot_stocks_only():
    account = _snapshot_account()
    positions = [_snapshot_stock()]
    text = format_account_snapshot(account, positions, "09:30 ET")

    assert "📊 *Account Snapshot*" in text
    assert "Net Liq \\$100,000" in text
    assert f"*{_md('Stocks')}*" in text
    assert "AAPL: 100 shares" in text
    assert "+1\\.1%" in text  # 200 / (180 * 100) * 100
    assert "Source: IBKR" in text
    assert "last updated 09:30 ET" in text


def test_format_account_snapshot_nested_covered_call():
    account = _snapshot_account()
    positions = [
        _snapshot_stock(),
        _snapshot_option("AAPL", OptionRight.CALL, 190.0, avg_cost=3.0, unrealized_pnl=50.0),
    ]
    text = format_account_snapshot(account, positions, "09:30 ET")

    # Nested CC line follows the stock line, prefixed with the tree marker.
    lines = text.splitlines()
    aapl_idx = next(i for i, ln in enumerate(lines) if ln.startswith("AAPL: 100 shares"))
    assert lines[aapl_idx + 1].startswith("  └ ")
    assert "C " in lines[aapl_idx + 1]
    assert "+16\\.7%" in lines[aapl_idx + 1]  # 50 / (3 * 1 * 100) * 100
    assert "Cash\\-Secured Puts" not in text


def test_format_account_snapshot_standalone_csp():
    account = _snapshot_account()
    positions = [
        _snapshot_stock(),
        _snapshot_option("MSFT", OptionRight.PUT, 300.0, avg_cost=4.0, unrealized_pnl=-20.0),
    ]
    text = format_account_snapshot(account, positions, "09:30 ET")

    assert f"*{_md('Cash-Secured Puts')}*" in text
    csp_line = next(ln for ln in text.splitlines() if ln.strip().startswith("MSFT"))
    assert "P " in csp_line
    assert "\\-5\\.0%" in csp_line  # -20 / (4 * 1 * 100) * 100


def test_format_account_snapshot_zero_cost_basis_is_na():
    account = _snapshot_account()
    positions = [_snapshot_stock(avg_cost=0.0, unrealized_pnl=0.0)]
    text = format_account_snapshot(account, positions, "09:30 ET")

    assert "N/A" in text
    # Total P&L % also falls back to N/A when total cost basis is zero.
    assert "\\(N/A\\)" in text


def test_format_account_snapshot_truncates_long_message():
    account = _snapshot_account()
    positions = [_snapshot_stock(symbol=f"SYM{i}") for i in range(200)]
    text = format_account_snapshot(account, positions, "09:30 ET")

    # Body is truncated; source footer is appended after the truncation marker.
    assert "\\.\\.\\." in text
    assert "Source: IBKR" in text


# --------------------------------------------------------------------------- #
# sender — send_candidates per-thread routing + empty/unchanged behaviour
# --------------------------------------------------------------------------- #


async def test_send_candidates_routes_to_provided_thread_id(mock_bot_cls, monkeypatch, tmp_path):
    """send_candidates passes the caller-provided thread_id to Telegram, not a hardcoded config."""
    _db_setup(tmp_path, monkeypatch)
    _mock_cfg(monkeypatch)
    mock_cls, mock_instance = mock_bot_cls

    import src.storage.db as dbmod

    with patch("src.notify.sender.Bot", mock_cls):
        with dbmod.session_scope() as s:
            await send_candidates(
                [_make_candidate("c-001")], [], session=s, **_cc_kwargs(thread_id=54)
            )

    call_kwargs = mock_instance.send_message.call_args.kwargs
    assert call_kwargs["message_thread_id"] == 54


async def test_send_candidates_empty_sends_with_thread(mock_bot_cls, monkeypatch, tmp_path):
    """Empty list diagnostic message uses the caller-provided thread_id."""
    _db_setup(tmp_path, monkeypatch)
    _mock_cfg(monkeypatch)
    mock_cls, mock_instance = mock_bot_cls

    with patch("src.notify.sender.Bot", mock_cls):
        sent = await send_candidates(
            [], [], **_cc_kwargs(thread_id=52, label="Cash-Secured Puts", icon="🟣")
        )

    assert sent is True
    call_kwargs = mock_instance.send_message.call_args.kwargs
    assert call_kwargs["message_thread_id"] == 52
    assert "no candidates this cycle" in call_kwargs["text"]


async def test_send_candidates_hash_unchanged_all_suppressed_sends_screen_digest(
    mock_bot_cls, monkeypatch, tmp_path
):
    """Hash matches + all candidates have live pending approvals → format_screen_unchanged.

    Calls send_candidates without a session (matching production usage) so that set_setting
    can open its own session after the approval-row session commits — no DB lock conflict.
    """
    _db_setup(tmp_path, monkeypatch)
    _mock_cfg(monkeypatch)
    mock_cls, mock_instance = mock_bot_cls

    cand = _make_candidate("c-001")
    kw = _cc_kwargs(suppress_unchanged=True)
    with patch("src.notify.sender.Bot", mock_cls):
        # First send: opens its own session, commits, then stores hash.
        await send_candidates([cand], [], **kw)
        mock_instance.send_message.reset_mock()
        # Second send: hash matches + live pending card → screen-level unchanged digest.
        await send_candidates([cand], [], **kw)

    assert mock_instance.send_message.call_count == 1
    text = mock_instance.send_message.call_args.kwargs["text"]
    # _append_status plain-text output: timestamped "unchanged" line, no MarkdownV2
    assert "Covered Calls" in text
    assert "unchanged" in text
    # plain text — no MarkdownV2 escaping or "no new screens" suffix
    assert "parse_mode" not in (mock_instance.send_message.call_args.kwargs or {})


# --------------------------------------------------------------------------- #
# _edit_or_send — edit-in-place behaviour for status messages
# --------------------------------------------------------------------------- #


async def test_empty_screen_edits_existing_message_on_repeat(mock_bot_cls, monkeypatch, tmp_path):
    """Second empty-screen cycle edits the previous status message instead of sending a new one."""
    _db_setup(tmp_path, monkeypatch)
    _mock_cfg(monkeypatch)
    mock_cls, mock_instance = mock_bot_cls
    mock_instance.send_message.return_value = MagicMock(message_id=55)

    with patch("src.notify.sender.Bot", mock_cls):
        # First call: no stored msg_id → send_message, stores id=55.
        await send_candidates([], [], **_cc_kwargs(empty_reason="0/4 passed the risk gate"))
        assert mock_instance.send_message.call_count == 1
        mock_instance.send_message.reset_mock()

        # Second call: stored id=55 → edit_message_text, NOT send_message.
        await send_candidates([], [], **_cc_kwargs(empty_reason="0/4 passed the risk gate"))

    mock_instance.edit_message_text.assert_called_once()
    mock_instance.send_message.assert_not_called()
    call_kw = mock_instance.edit_message_text.call_args.kwargs
    assert call_kw["message_id"] == 55


async def test_empty_screen_falls_back_to_send_when_edit_fails(mock_bot_cls, monkeypatch, tmp_path):
    """If edit_message_text raises, _edit_or_send falls back to send_message and stores new id."""
    _db_setup(tmp_path, monkeypatch)
    _mock_cfg(monkeypatch)
    mock_cls, mock_instance = mock_bot_cls
    mock_instance.send_message.return_value = MagicMock(message_id=55)

    with patch("src.notify.sender.Bot", mock_cls):
        await send_candidates([], [], **_cc_kwargs())  # stores id=55
        mock_instance.send_message.reset_mock()
        mock_instance.edit_message_text.side_effect = Exception("message deleted")
        mock_instance.send_message.return_value = MagicMock(message_id=66)

        await send_candidates([], [], **_cc_kwargs())

    # Edit was attempted but failed → fell back to send_message with new id.
    mock_instance.edit_message_text.assert_called_once()
    mock_instance.send_message.assert_called_once()

    from src.storage.system_settings import get_setting

    assert get_setting("last_cc_status_msg_id") == "66"


async def test_full_candidate_send_clears_status_msg_id(mock_bot_cls, monkeypatch, tmp_path):
    """When actual candidates are sent, status_msg_id is cleared so next empty cycle sends fresh.

    Uses no explicit session (let send_candidates open its own) so that set_setting can write
    after the approval-row session commits — same pattern as the hash/time keys (avoids DB lock).
    """
    _db_setup(tmp_path, monkeypatch)
    _mock_cfg(monkeypatch)
    mock_cls, mock_instance = mock_bot_cls
    mock_instance.send_message.return_value = MagicMock(message_id=55)

    from src.storage.system_settings import get_setting, set_setting

    # Prime a stored status msg id (as if a previous empty cycle ran).
    set_setting("last_cc_status_msg_id", "42")

    with patch("src.notify.sender.Bot", mock_cls):
        # No session= arg: send_candidates opens+commits its own session, then set_setting succeeds.
        await send_candidates([_make_candidate("c-001")], [], **_cc_kwargs())

    # After a real candidate send, the status msg id must be cleared.
    assert get_setting("last_cc_status_msg_id") == ""


async def test_buy_list_empty_edits_on_repeat(monkeypatch, tmp_path):
    """Second empty buy-list cycle edits the previous status message."""
    _db_setup(tmp_path, monkeypatch)

    cfg = MagicMock()
    cfg.secrets.telegram_bot_token = "tok"
    cfg.secrets.telegram_thread_buy = ""
    monkeypatch.setattr("src.notify.sender.get_config", lambda: cfg)

    mock_instance = AsyncMock()
    mock_instance.send_message.return_value = MagicMock(message_id=77)
    mock_cls = MagicMock()
    mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
    mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)

    with patch("src.notify.sender.Bot", mock_cls):
        await send_buy_list([], chat_id="99999")  # first: send, stores id=77
        assert mock_instance.send_message.call_count == 1
        mock_instance.send_message.reset_mock()

        await send_buy_list([], chat_id="99999")  # second: edit

    mock_instance.edit_message_text.assert_called_once()
    mock_instance.send_message.assert_not_called()
    assert mock_instance.edit_message_text.call_args.kwargs["message_id"] == 77


async def test_buy_list_full_send_clears_status_msg_id(monkeypatch, tmp_path):
    """Full buy-list send clears the status msg id so the next empty cycle sends fresh."""
    _db_setup(tmp_path, monkeypatch)

    cfg = MagicMock()
    cfg.secrets.telegram_bot_token = "tok"
    cfg.secrets.telegram_thread_buy = ""
    monkeypatch.setattr("src.notify.sender.get_config", lambda: cfg)

    from src.storage.system_settings import get_setting, set_setting

    set_setting("last_buy_list_status_msg_id", "42")

    mock_instance = AsyncMock()
    mock_instance.send_message.return_value = MagicMock(message_id=99)
    mock_cls = MagicMock()
    mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
    mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)

    cands = [BuyCandidate(symbol="AAPL", score=85.0)]
    with patch("src.notify.sender.Bot", mock_cls):
        await send_buy_list(cands, chat_id="99999")

    assert get_setting("last_buy_list_status_msg_id") == ""


# --------------------------------------------------------------------------- #
# sender — send_buy_list empty-state + thread routing
# --------------------------------------------------------------------------- #


async def test_send_buy_list_empty_sends_diagnostic(monkeypatch, tmp_path):
    """Empty buy list sends a format_screen_empty diagnostic to telegram_thread_buy."""
    _db_setup(tmp_path, monkeypatch)

    cfg = MagicMock()
    cfg.secrets.telegram_bot_token = "tok"
    cfg.secrets.telegram_thread_buy = "56"
    monkeypatch.setattr("src.notify.sender.get_config", lambda: cfg)

    mock_instance = AsyncMock()
    mock_cls = MagicMock()
    mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
    mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)

    with patch("src.notify.sender.Bot", mock_cls):
        sent = await send_buy_list([], chat_id="99999")

    assert sent is True
    mock_instance.send_message.assert_called_once()
    text = mock_instance.send_message.call_args.kwargs["text"]
    assert "Buy-to-Own" in text
    assert "would_own" in text  # the plain-text empty line contains this phrase
    assert mock_instance.send_message.call_args.kwargs["message_thread_id"] == 56


async def test_send_buy_list_routes_to_thread_buy(monkeypatch, tmp_path):
    """send_buy_list always uses telegram_thread_buy, not telegram_thread_scan."""
    _db_setup(tmp_path, monkeypatch)
    _buy_cfg(monkeypatch)

    mock_instance = AsyncMock()
    mock_cls = MagicMock()
    mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
    mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)

    cands = [BuyCandidate(symbol="AAPL", score=85.0)]
    with patch("src.notify.sender.Bot", mock_cls):
        await send_buy_list(cands, chat_id="99999")

    call_kwargs = mock_instance.send_message.call_args.kwargs
    # telegram_thread_buy = "" → thread_id("") = None
    assert call_kwargs["message_thread_id"] is None


# --------------------------------------------------------------------------- #
# sender — send_account_snapshot
# --------------------------------------------------------------------------- #


def _mock_account_cfg(monkeypatch):
    cfg = MagicMock()
    cfg.secrets.telegram_bot_token = "tok"
    cfg.secrets.telegram_chat_id = "99999"
    cfg.secrets.telegram_thread_account = "58"
    monkeypatch.setattr("src.notify.sender.get_config", lambda: cfg)
    return cfg


async def test_send_account_snapshot_first_send(monkeypatch, tmp_path):
    """No stored message → send_message called, message_id and date stored."""
    _db_setup(tmp_path, monkeypatch)
    _mock_account_cfg(monkeypatch)

    from src.notify.sender import send_account_snapshot

    mock_instance = AsyncMock()
    mock_instance.send_message.return_value = MagicMock(message_id=99)
    mock_cls = MagicMock()
    mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
    mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)

    account = _snapshot_account()
    with patch("src.notify.sender.Bot", mock_cls):
        result = await send_account_snapshot(account, [_snapshot_stock()])

    assert result is True
    mock_instance.send_message.assert_called_once()
    mock_instance.edit_message_text.assert_not_called()

    from src.storage.system_settings import get_setting

    assert get_setting("account_snapshot_message_id") == "99"
    assert get_setting("account_snapshot_date") is not None


async def test_send_account_snapshot_edits_same_day(monkeypatch, tmp_path):
    """Stored message from today → edit_message_text called, no new send."""
    _db_setup(tmp_path, monkeypatch)
    _mock_account_cfg(monkeypatch)

    from zoneinfo import ZoneInfo

    from src.notify.sender import send_account_snapshot
    from src.storage.system_settings import set_setting

    today = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    set_setting("account_snapshot_message_id", "77")
    set_setting("account_snapshot_date", today)

    mock_instance = AsyncMock()
    mock_cls = MagicMock()
    mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
    mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)

    account = _snapshot_account()
    with patch("src.notify.sender.Bot", mock_cls):
        result = await send_account_snapshot(account, [])

    assert result is True
    mock_instance.edit_message_text.assert_called_once()
    call_kw = mock_instance.edit_message_text.call_args.kwargs
    assert call_kw["message_id"] == 77
    mock_instance.send_message.assert_not_called()


async def test_send_account_snapshot_edit_fails_falls_back_to_send(monkeypatch, tmp_path):
    """edit_message_text raises (e.g. message deleted) → fallback send_message + overwrite id."""
    _db_setup(tmp_path, monkeypatch)
    _mock_account_cfg(monkeypatch)

    from zoneinfo import ZoneInfo

    from src.notify.sender import send_account_snapshot
    from src.storage.system_settings import get_setting, set_setting

    today = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    set_setting("account_snapshot_message_id", "77")
    set_setting("account_snapshot_date", today)

    mock_instance = AsyncMock()
    mock_instance.edit_message_text.side_effect = Exception("message not found")
    mock_instance.send_message.return_value = MagicMock(message_id=88)
    mock_cls = MagicMock()
    mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
    mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)

    account = _snapshot_account()
    with patch("src.notify.sender.Bot", mock_cls):
        result = await send_account_snapshot(account, [])

    assert result is True
    mock_instance.send_message.assert_called_once()
    assert get_setting("account_snapshot_message_id") == "88"


async def test_send_account_snapshot_new_day_resends(monkeypatch, tmp_path):
    """Stored date is yesterday → send_message (not edit) and overwrite stored date."""
    _db_setup(tmp_path, monkeypatch)
    _mock_account_cfg(monkeypatch)

    from src.notify.sender import send_account_snapshot
    from src.storage.system_settings import get_setting, set_setting

    set_setting("account_snapshot_message_id", "55")
    set_setting("account_snapshot_date", "2020-01-01")  # old date

    mock_instance = AsyncMock()
    mock_instance.send_message.return_value = MagicMock(message_id=100)
    mock_cls = MagicMock()
    mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
    mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)

    account = _snapshot_account()
    with patch("src.notify.sender.Bot", mock_cls):
        result = await send_account_snapshot(account, [])

    assert result is True
    mock_instance.send_message.assert_called_once()
    mock_instance.edit_message_text.assert_not_called()
    assert get_setting("account_snapshot_message_id") == "100"
    assert get_setting("account_snapshot_date") != "2020-01-01"
