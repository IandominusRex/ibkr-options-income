"""Loss-side exits (D3). The system could previously only add risk and take profits."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.common.schemas import OptionRight, PositionSnapshot


def _short_put(strike=100.0, qty=-1):
    from datetime import date, timedelta

    return PositionSnapshot(
        symbol="AAPL  260918P00100000",
        sec_type="OPT",
        position=qty,
        avg_cost=250.0,
        right=OptionRight.PUT,
        strike=strike,
        expiry=date.today() + timedelta(days=30),
        underlying="AAPL",
    )


@pytest.mark.asyncio
async def test_loss_exit_fires_at_the_configured_multiple():
    """Entry credit $2.50, cost-to-close $5.20 -> 2.08x, above the 2.0x threshold."""
    from src.execution.profit_take import check_loss_exits

    ib_scan, ib_exec = MagicMock(), MagicMock()
    bot = AsyncMock()
    close_result = MagicMock()
    close_result.status = "filled"
    close_result.qty = 1
    close_result.filled_qty = 1
    close_result.avg_price = 5.20
    close_result.limit_price = 5.20
    with (
        patch("src.ibkr.portfolio.get_positions", return_value=[_short_put()]),
        patch("src.execution.profit_take.net_entry_credit_per_share", return_value=2.50),
        patch("src.execution.profit_take._quote_short", new=AsyncMock(return_value=(5.10, 5.30))),
        patch("src.execution.profit_take.close_short_position", new=AsyncMock(return_value=close_result)) as close,
    ):
        await check_loss_exits(ib_scan, ib_exec, bot, "chat")
    close.assert_awaited_once()
    bot.send_message.assert_awaited_once()
    call_args = bot.send_message.call_args
    text = call_args.kwargs["text"]
    assert "Loss exit closed" in text
    assert "Entry credit" in text
    assert "closed at" in text


@pytest.mark.asyncio
async def test_loss_exit_does_not_fire_below_the_multiple():
    from src.execution.profit_take import check_loss_exits

    ib_scan, ib_exec, bot = MagicMock(), MagicMock(), MagicMock()
    with (
        patch("src.ibkr.portfolio.get_positions", return_value=[_short_put()]),
        patch("src.execution.profit_take.net_entry_credit_per_share", return_value=2.50),
        patch("src.execution.profit_take._quote_short", new=AsyncMock(return_value=(3.00, 3.20))),
        patch("src.execution.profit_take.close_short_position", new=AsyncMock()) as close,
    ):
        await check_loss_exits(ib_scan, ib_exec, bot, "chat")
    close.assert_not_awaited()


@pytest.mark.asyncio
async def test_loss_exit_is_skipped_when_auto_close_is_disabled():
    from src.execution.profit_take import check_loss_exits

    ib_scan, ib_exec = MagicMock(), MagicMock()
    bot = AsyncMock()
    cfg = MagicMock()
    cfg.automation.auto_close_enabled = False
    cfg.automation.max_loss_multiple = 2.0
    with (
        patch("src.execution.profit_take.get_config", return_value=cfg),
        patch("src.ibkr.portfolio.get_positions", return_value=[_short_put()]),
        patch("src.execution.profit_take.net_entry_credit_per_share", return_value=2.50),
        patch("src.execution.profit_take._quote_short", new=AsyncMock(return_value=(9.0, 9.2))),
        patch("src.execution.profit_take.close_short_position", new=AsyncMock()) as close,
    ):
        await check_loss_exits(ib_scan, ib_exec, bot, "chat")
    close.assert_not_awaited()


@pytest.mark.asyncio
async def test_loss_exit_sends_error_notification_on_close_failure():
    """When close_short_position returns an error, send an error alert, not a success message."""
    from src.execution.profit_take import check_loss_exits

    ib_scan, ib_exec = MagicMock(), MagicMock()
    bot = AsyncMock()
    close_result = MagicMock()
    close_result.status = "error"
    close_result.detail = "order placement failed"
    with (
        patch("src.ibkr.portfolio.get_positions", return_value=[_short_put()]),
        patch("src.execution.profit_take.net_entry_credit_per_share", return_value=2.50),
        patch("src.execution.profit_take._quote_short", new=AsyncMock(return_value=(5.10, 5.30))),
        patch("src.execution.profit_take.close_short_position", new=AsyncMock(return_value=close_result)) as close,
    ):
        await check_loss_exits(ib_scan, ib_exec, bot, "chat")
    close.assert_awaited_once()
    bot.send_message.assert_awaited_once()
    call_args = bot.send_message.call_args
    assert "error" in call_args.kwargs["text"].lower()
    assert "check IBKR manually" in call_args.kwargs["text"]


@pytest.mark.asyncio
async def test_loss_exit_skips_duplicate_close_attempt():
    """When close is already working (skipped), don't send a notification."""
    from src.execution.profit_take import check_loss_exits

    ib_scan, ib_exec = MagicMock(), MagicMock()
    bot = AsyncMock()
    close_result = MagicMock()
    close_result.status = "skipped"
    close_result.detail = "close already working"
    with (
        patch("src.ibkr.portfolio.get_positions", return_value=[_short_put()]),
        patch("src.execution.profit_take.net_entry_credit_per_share", return_value=2.50),
        patch("src.execution.profit_take._quote_short", new=AsyncMock(return_value=(5.10, 5.30))),
        patch("src.execution.profit_take.close_short_position", new=AsyncMock(return_value=close_result)) as close,
    ):
        await check_loss_exits(ib_scan, ib_exec, bot, "chat")
    close.assert_awaited_once()
    bot.send_message.assert_not_awaited()  # No notification for skipped closes
