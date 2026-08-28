"""Tests for the once-per-day buy-to-own send gate (2026-08-28).

The buy-to-own screen is scored every intraday cycle (cheap — reuses analytics already
fetched for CC/CSP), but it should only be *sent* to Telegram once per calendar day from
the automatic 15-min loop, on whichever cycle first completes that day. Manual /scan is
unaffected — it always sends the full buy list immediately.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

from src.common.schemas import AccountSnapshot, BuyCandidate

_ET = ZoneInfo("America/New_York")


def _db_setup(tmp_path, monkeypatch) -> None:
    import src.storage.db as dbmod
    from src.common.config import Config

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{tmp_path / 't.db'}")
    dbmod.init_db()


def _account() -> AccountSnapshot:
    return AccountSnapshot(
        account="DU123456",
        net_liquidation=200_000.0,
        total_cash=150_000.0,
        buying_power=120_000.0,
        maintenance_margin=10_000.0,
        excess_liquidity=110_000.0,
    )


# --------------------------------------------------------------------------- #
# send_scan_results — include_buy_list gate
# --------------------------------------------------------------------------- #


async def test_send_scan_results_skips_buy_list_when_disabled(monkeypatch):
    from src.orchestrator.scan import ScanResult, SendDeps, _Tracker, send_scan_results

    cfg = MagicMock()
    cfg.secrets.telegram_thread_cc = ""
    cfg.secrets.telegram_thread_csp = ""
    monkeypatch.setattr("src.orchestrator.scan_progress.get_config", lambda: cfg)

    result = ScanResult(buy_candidates=[BuyCandidate(symbol="AAPL", score=85.0)])
    send_candidates_mock = AsyncMock(return_value=True)
    send_buy_list_mock = AsyncMock(return_value=True)

    await send_scan_results(
        _Tracker(None, None),
        result,
        bot=None,
        chat_id="123",
        intraday=True,
        account=_account(),
        positions=[],
        cc_empty_reason="",
        csp_empty_reason="",
        cc_near_misses=[],
        cc_near_miss_more=0,
        csp_near_misses=[],
        csp_near_miss_more=0,
        per_symbol_skip={},
        sends=SendDeps(
            send_candidates=send_candidates_mock,
            send_buy_list=send_buy_list_mock,
            send_account_snapshot=AsyncMock(return_value=True),
        ),
        include_buy_list=False,
    )

    send_buy_list_mock.assert_not_called()
    assert send_candidates_mock.call_count == 2  # CC + CSP screens still sent


async def test_send_scan_results_sends_buy_list_by_default(monkeypatch):
    from src.orchestrator.scan import ScanResult, SendDeps, _Tracker, send_scan_results

    cfg = MagicMock()
    cfg.secrets.telegram_thread_cc = ""
    cfg.secrets.telegram_thread_csp = ""
    monkeypatch.setattr("src.orchestrator.scan_progress.get_config", lambda: cfg)

    result = ScanResult(buy_candidates=[BuyCandidate(symbol="AAPL", score=85.0)])
    send_buy_list_mock = AsyncMock(return_value=True)

    await send_scan_results(
        _Tracker(None, None),
        result,
        bot=None,
        chat_id="123",
        intraday=True,
        account=_account(),
        positions=[],
        cc_empty_reason="",
        csp_empty_reason="",
        cc_near_misses=[],
        cc_near_miss_more=0,
        csp_near_misses=[],
        csp_near_miss_more=0,
        per_symbol_skip={},
        sends=SendDeps(
            send_candidates=AsyncMock(return_value=True),
            send_buy_list=send_buy_list_mock,
            send_account_snapshot=AsyncMock(return_value=True),
        ),
    )

    send_buy_list_mock.assert_called_once()


# --------------------------------------------------------------------------- #
# _run_intraday_scan — forwards + records the gate
# --------------------------------------------------------------------------- #


async def test_run_intraday_scan_forwards_include_buy_list():
    from src.notify.approval_service import _run_intraday_scan
    from src.orchestrator.scan import ScanResult

    ib_scan = MagicMock()
    ib_scan.isConnected.return_value = True
    bot = AsyncMock()
    bot_data: dict = {}
    mock_run_scan = AsyncMock(return_value=ScanResult())

    with (
        patch("src.orchestrator.scan.run_scan", mock_run_scan),
        patch("src.notify.approval_service._update_pending_order_notifications", AsyncMock()),
    ):
        await _run_intraday_scan(ib_scan, bot, "123", bot_data, include_buy_list=False)

    assert mock_run_scan.call_args.kwargs["include_buy_list"] is False


async def test_run_intraday_scan_marks_buy_list_sent_after_success(tmp_path, monkeypatch):
    _db_setup(tmp_path, monkeypatch)
    from src.notify.approval_service import _BUY_LIST_SENT_DATE_KEY, _run_intraday_scan
    from src.orchestrator.scan import ScanResult
    from src.storage.system_settings import get_setting

    ib_scan = MagicMock()
    ib_scan.isConnected.return_value = True
    bot = AsyncMock()
    bot_data: dict = {}

    with (
        patch("src.orchestrator.scan.run_scan", AsyncMock(return_value=ScanResult())),
        patch("src.notify.approval_service._update_pending_order_notifications", AsyncMock()),
    ):
        await _run_intraday_scan(ib_scan, bot, "123", bot_data, include_buy_list=True)

    today = datetime.now(_ET).date().isoformat()
    assert get_setting(_BUY_LIST_SENT_DATE_KEY) == today


async def test_run_intraday_scan_does_not_mark_sent_when_buy_list_disabled(tmp_path, monkeypatch):
    _db_setup(tmp_path, monkeypatch)
    from src.notify.approval_service import _BUY_LIST_SENT_DATE_KEY, _run_intraday_scan
    from src.orchestrator.scan import ScanResult
    from src.storage.system_settings import get_setting

    ib_scan = MagicMock()
    ib_scan.isConnected.return_value = True
    bot = AsyncMock()
    bot_data: dict = {}

    with (
        patch("src.orchestrator.scan.run_scan", AsyncMock(return_value=ScanResult())),
        patch("src.notify.approval_service._update_pending_order_notifications", AsyncMock()),
    ):
        await _run_intraday_scan(ib_scan, bot, "123", bot_data, include_buy_list=False)

    assert get_setting(_BUY_LIST_SENT_DATE_KEY) == ""


async def test_run_intraday_scan_does_not_mark_sent_on_lease_skip(tmp_path, monkeypatch):
    """A lease-skipped cycle produced no real result — must not falsely mark the day 'done',
    or the buy list would never fire that day at all."""
    _db_setup(tmp_path, monkeypatch)
    from src.notify.approval_service import _BUY_LIST_SENT_DATE_KEY, _run_intraday_scan
    from src.orchestrator.scan import ScanResult
    from src.storage.system_settings import get_setting

    ib_scan = MagicMock()
    ib_scan.isConnected.return_value = True
    bot = AsyncMock()
    bot_data: dict = {}
    result = ScanResult(lease_skipped=True)

    with patch("src.orchestrator.scan.run_scan", AsyncMock(return_value=result)):
        await _run_intraday_scan(ib_scan, bot, "123", bot_data, include_buy_list=True)

    assert get_setting(_BUY_LIST_SENT_DATE_KEY) == ""


# --------------------------------------------------------------------------- #
# _intraday_scan_loop — once per day, end to end
# --------------------------------------------------------------------------- #


async def test_intraday_loop_sends_buy_list_once_per_day(tmp_path, monkeypatch):
    """First cycle of the day includes the buy list; the next cycle (same day) does not."""
    _db_setup(tmp_path, monkeypatch)
    import src.notify.approval_service as approval_service

    ib_scan = MagicMock()
    ib_scan.isConnected.return_value = True
    bot = AsyncMock()
    app = SimpleNamespace(bot=bot, bot_data={})

    include_flags: list[bool] = []

    async def _capture_run_scan(*args, **kwargs):
        from src.orchestrator.scan import ScanResult

        include_flags.append(kwargs.get("include_buy_list"))
        return ScanResult()

    with (
        patch.object(approval_service, "is_rth", return_value=True),
        patch.object(approval_service, "is_halted", return_value=False),
        patch.object(approval_service, "is_new_entry_window", return_value=True),
        patch.object(approval_service, "seconds_until_next_aligned_mark", return_value=0.01),
        patch.object(approval_service, "_check_profit_takes", AsyncMock()),
        patch.object(approval_service, "_check_loss_exits", AsyncMock()),
        patch.object(approval_service, "_update_pending_order_notifications", AsyncMock()),
        patch("src.ibkr.market_data.probe_market_data_health", AsyncMock(return_value=True)),
        patch("src.orchestrator.scan.run_scan", _capture_run_scan),
    ):
        loop_task = asyncio.create_task(
            approval_service._intraday_scan_loop(app, ib_scan, None, "123")
        )
        try:
            for _ in range(200):
                if len(include_flags) >= 2:
                    break
                await asyncio.sleep(0.01)
        finally:
            loop_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await loop_task

    assert len(include_flags) >= 2, "loop did not spawn two scan cycles in time"
    assert include_flags[0] is True
    assert include_flags[1] is False
