"""The forced full sweep runs once per ET trading day, not once per process start, and the
retry queue survives a restart (docs/superpowers/plans/2026-10-10-contract-cache.md, Task 4)."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch


def test_full_sweep_due_once_per_et_day(db, monkeypatch) -> None:
    import src.notify.approval_service as svc

    monkeypatch.setattr(svc, "_et_today", lambda: date(2026, 10, 12))
    assert svc._full_sweep_due() is True
    svc._mark_full_sweep_done()
    assert svc._full_sweep_due() is False  # same day, even from a fresh process

    monkeypatch.setattr(svc, "_et_today", lambda: date(2026, 10, 13))
    assert svc._full_sweep_due() is True


async def test_retry_queue_survives_a_restart(db) -> None:
    from src.notify.approval_service import _run_intraday_scan
    from src.orchestrator.scan import ScanResult

    ib_scan = MagicMock()
    ib_scan.isConnected.return_value = True
    cut_short = ScanResult(aborted_unhealthy=True, unreached_symbols=["NVDA", "PLTR"])
    with (
        patch("src.orchestrator.scan.run_scan", AsyncMock(return_value=cut_short)),
        patch("src.notify.approval_service._update_pending_order_notifications", AsyncMock()),
        patch("src.notify.approval_service._notify_scan_blocked", AsyncMock()),
        patch("src.notify.approval_service._force_scan_reconnect", AsyncMock()),
    ):
        await _run_intraday_scan(ib_scan, AsyncMock(), "123", {})

    restarted_bot_data: dict = {}  # a new process: empty bot_data
    run_scan = AsyncMock(return_value=ScanResult())
    with (
        patch("src.orchestrator.scan.run_scan", run_scan),
        patch("src.notify.approval_service._update_pending_order_notifications", AsyncMock()),
    ):
        await _run_intraday_scan(ib_scan, AsyncMock(), "123", restarted_bot_data)

    assert run_scan.call_args.kwargs["must_include_symbols"] == {"NVDA", "PLTR"}
