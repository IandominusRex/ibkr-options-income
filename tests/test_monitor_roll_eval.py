"""Monitor: RTH-gated alerts, info-only timers, breach evaluation loop (roll redesign Task 10)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from src.common.schemas import OptionQuote, OptionRight, PositionSnapshot, RollAlert, RollDecision

_ET = ZoneInfo("America/New_York")
_MON = date(2026, 10, 12)  # a Monday, not a holiday


def _at(hh: int, mm: int) -> datetime:
    return datetime(_MON.year, _MON.month, _MON.day, hh, mm, tzinfo=_ET)


def test_minutes_since_open() -> None:
    from src.common.market_hours import minutes_since_open

    assert minutes_since_open(_at(10, 0)) == pytest.approx(30.0)
    assert minutes_since_open(_at(1, 0)) is None
    assert minutes_since_open(_at(16, 30)) is None


def test_the_alert_window_opens_fifteen_minutes_after_the_bell() -> None:
    from src.common.config import get_config
    from src.monitor.intraday import _alert_window_open

    cfg = get_config()
    assert not _alert_window_open(cfg, _at(1, 0))
    assert not _alert_window_open(cfg, _at(9, 40))
    assert _alert_window_open(cfg, _at(10, 0))


def _pos(strike: float = 100.0, days: int = 5, symbol: str = "X") -> PositionSnapshot:
    return PositionSnapshot(
        symbol=f"{symbol} put",
        sec_type="OPT",
        position=-1,
        avg_cost=1.0,
        right=OptionRight.PUT,
        strike=strike,
        expiry=date.today() + timedelta(days=days),
        underlying=symbol,
        con_id=9,
    )


def _quote(spot: float, delta: float = -0.7, days: int = 5) -> OptionQuote:
    return OptionQuote(
        underlying="X",
        right=OptionRight.PUT,
        strike=100.0,
        expiry=date.today() + timedelta(days=days),
        bid=5.4,
        ask=5.6,
        delta=delta,
        underlying_price=spot,
    )


async def test_alerts_outside_the_window_are_not_sent(db) -> None:
    from src.common.config import get_config
    from src.monitor import intraday

    bot = AsyncMock()
    alert = RollAlert(
        position_symbol="X put", underlying="X", trigger="manage_dte", detail="d", dte=5
    )
    with patch.object(intraday, "_alert_window_open", return_value=False):
        await intraday.fire_alerts(
            [alert],
            _pos(),
            _quote(105.0),
            bot,
            "1",
            get_config(),
            ThreadPoolExecutor(1),
            ib=MagicMock(),
        )
    bot.send_message.assert_not_awaited()


async def test_info_alerts_never_carry_buttons_or_evaluate_a_roll(db) -> None:
    from src.common.config import get_config
    from src.monitor import intraday

    cfg = get_config().model_copy(deep=True)
    cfg.claude.enabled = False
    bot = AsyncMock()
    alert = RollAlert(
        position_symbol="X put", underlying="X", trigger="manage_dte", detail="d", dte=5
    )
    with (
        patch.object(intraday, "_alert_window_open", return_value=True),
        patch("src.execution.roll_pipeline.evaluate_roll", new=AsyncMock()) as ev,
    ):
        await intraday.fire_alerts(
            [alert], _pos(), _quote(105.0), bot, "1", cfg, ThreadPoolExecutor(1), ib=MagicMock()
        )
    assert bot.send_message.await_args.kwargs["reply_markup"] is None
    ev.assert_not_awaited()


def _roll_decision() -> RollDecision:
    return RollDecision(action="assign", reason="net_below_floor", detail="No credit roll.")


async def _handle(pos, quote, state, now, *, decision=None, approval_id=None):
    from src.common.config import get_config
    from src.monitor import intraday

    bot = AsyncMock()
    ev = AsyncMock(return_value=(decision or _roll_decision(), approval_id))
    with (
        patch.object(intraday, "_alert_window_open", return_value=True),
        patch("src.execution.roll_pipeline.evaluate_roll", new=ev),
        patch.object(intraday, "review_roll", return_value=None),  # never shell out to claude
    ):
        await intraday.handle_roll_trigger(
            pos,
            quote,
            ib=MagicMock(),
            bot=bot,
            chat_id="1",
            cfg=get_config(),
            fund=None,
            state=state,
            now=now,
        )
    return ev, bot


async def test_a_breached_short_is_evaluated_on_a_thirty_minute_cadence(db) -> None:
    from src.monitor.intraday import RollEvalState

    state = RollEvalState()
    roll = RollDecision(action="roll", reason="credit_roll", detail="Roll it.")
    ev, _ = await _handle(_pos(), _quote(95.0), state, now=0.0, decision=roll)
    assert ev.await_count == 1
    ev, _ = await _handle(_pos(), _quote(95.0), state, now=10 * 60.0, decision=roll)
    assert ev.await_count == 0
    ev, _ = await _handle(_pos(), _quote(95.0), state, now=31 * 60.0, decision=roll)
    assert ev.await_count == 1


async def test_the_same_decision_is_sent_once_per_day(db) -> None:
    from src.monitor.intraday import RollEvalState

    state = RollEvalState()
    roll = RollDecision(action="roll", reason="credit_roll", detail="Roll it.")
    _, bot1 = await _handle(_pos(), _quote(95.0), state, now=0.0, decision=roll, approval_id=1)
    # 2026-11-10: the same roll re-queued under a new approval every 30 minutes sent a new card
    _, bot2 = await _handle(
        _pos(), _quote(95.0), state, now=31 * 60.0, decision=roll, approval_id=2
    )
    changed = RollDecision(action="close", reason="not_would_own", detail="Close it.")
    _, bot3 = await _handle(_pos(), _quote(95.0), state, now=62 * 60.0, decision=changed)
    assert (
        bot1.send_message.await_count,
        bot2.send_message.await_count,
        bot3.send_message.await_count,
    ) == (1, 0, 1)


async def test_a_standing_answer_is_not_re_evaluated_the_same_day(db) -> None:
    """NVDA 205P flipped assign <-> roll on quote noise every 30 minutes (2026-11-05..12)."""
    from src.monitor.intraday import RollEvalState

    state = RollEvalState()
    ev1, bot1 = await _handle(_pos(), _quote(95.0), state, now=0.0)  # assign
    roll = RollDecision(action="roll", reason="credit_roll", detail="Roll it.")
    ev2, bot2 = await _handle(_pos(), _quote(95.0), state, now=31 * 60.0, decision=roll)
    assert (ev1.await_count, ev2.await_count) == (1, 0)
    assert (bot1.send_message.await_count, bot2.send_message.await_count) == (1, 0)


async def test_a_queued_roll_card_carries_approve_buttons_and_a_close_card_a_close_button(
    db,
) -> None:
    from src.monitor.intraday import RollEvalState

    roll = RollDecision(action="roll", reason="credit_roll", detail="Roll it.")
    _, bot = await _handle(
        _pos(), _quote(95.0), RollEvalState(), now=0.0, decision=roll, approval_id=77
    )
    buttons = bot.send_message.await_args.kwargs["reply_markup"].inline_keyboard[0]
    assert [b.callback_data for b in buttons] == ["approve:77", "reject:77"]

    close = RollDecision(action="close", reason="not_would_own", detail="Close it.")
    _, bot = await _handle(_pos(symbol="Y"), _quote(95.0), RollEvalState(), now=0.0, decision=close)
    (button,) = bot.send_message.await_args.kwargs["reply_markup"].inline_keyboard[0]
    assert button.callback_data == "close_short:9"


async def test_deferrals_send_nothing(db) -> None:
    from src.monitor.intraday import RollEvalState

    defer = RollDecision(action="defer", reason="roll_pending", detail="pending")
    _, bot = await _handle(_pos(), _quote(95.0), RollEvalState(), now=0.0, decision=defer)
    bot.send_message.assert_not_awaited()


async def test_a_leveraged_etf_is_evaluated_like_any_other_short(db) -> None:
    # 2026-10-14 ruling: leveraged ETFs roll where possible (was: always hold, no fetch).
    from src.monitor.intraday import RollEvalState

    with patch("src.common.universe.is_leveraged_etf", return_value=True):
        ev, _ = await _handle(_pos(), _quote(95.0), RollEvalState(), now=0.0)
    ev.assert_awaited_once()


async def test_an_auto_approved_roll_card_has_no_buttons(db) -> None:
    from src.common.schemas import ApprovalStatus
    from src.monitor.intraday import RollEvalState
    from src.storage.db import session_scope
    from src.storage.models import ApprovalRow

    with session_scope() as s:
        row = ApprovalRow(candidate_id="r1", status=ApprovalStatus.APPROVED, chat_id="1")
        s.add(row)
        s.flush()
        approval_id = row.id
    decision = RollDecision(action="roll", reason="credit_roll", detail="Roll for a credit.")
    _, bot = await _handle(
        _pos(), _quote(95.0), RollEvalState(), now=0.0, decision=decision, approval_id=approval_id
    )
    kwargs = bot.send_message.await_args.kwargs
    assert kwargs["reply_markup"] is None
    assert "Auto" in kwargs["text"] or "Roll for a credit" in kwargs["text"]


async def test_an_unbreached_short_is_not_evaluated(db) -> None:
    from src.monitor.intraday import RollEvalState

    ev, bot = await _handle(_pos(), _quote(104.0, delta=-0.25), RollEvalState(), now=0.0)
    ev.assert_not_awaited()
    bot.send_message.assert_not_awaited()


@pytest.fixture(autouse=True)
def _no_roll_down_rule(monkeypatch):
    """These tests predate the ITM roll-down rule (2026-11-12) and use same-strike rolls of an
    in-the-money put; the rule has its own tests (tests/test_roll_down_rule.py)."""
    from src.common.config import get_config

    monkeypatch.setattr(get_config().roll.csp, "itm_min_basis_drop_pct", None)
