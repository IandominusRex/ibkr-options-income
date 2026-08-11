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

    ib_scan, ib_exec, bot = MagicMock(), MagicMock(), MagicMock()
    with (
        patch("src.ibkr.portfolio.get_positions", return_value=[_short_put()]),
        patch("src.execution.profit_take.net_entry_credit_per_share", return_value=2.50),
        patch("src.execution.profit_take._quote_short", new=AsyncMock(return_value=(5.10, 5.30))),
        patch("src.execution.profit_take.close_short_position", new=AsyncMock()) as close,
    ):
        await check_loss_exits(ib_scan, ib_exec, bot, "chat")
    close.assert_awaited_once()


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

    ib_scan, ib_exec, bot = MagicMock(), MagicMock(), MagicMock()
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
