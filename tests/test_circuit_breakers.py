"""Tests for AUTOMATED-mode circuit breakers + the /halt kill switch (SYSTEM_REVIEW Phase 2)."""

from __future__ import annotations

from types import SimpleNamespace

from src.common.schemas import OrderState
from src.storage.models import FillRow, OrderRow


def _db_setup(tmp_path, monkeypatch) -> None:
    import src.storage.db as dbmod
    from src.common.config import Config

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{tmp_path / 't.db'}")
    dbmod.init_db()


def _automation_cfg(monkeypatch, *, max_trades=10, loss_pct=5.0) -> None:
    import src.execution.circuit_breakers as cb

    cfg = SimpleNamespace(
        automation=SimpleNamespace(max_auto_trades_per_day=max_trades, daily_loss_halt_pct=loss_pct)
    )
    monkeypatch.setattr(cb, "get_config", lambda: cfg)


# --------------------------------------------------------------------------- #
# Kill switch
# --------------------------------------------------------------------------- #


def test_scan_lease_serialises(tmp_path, monkeypatch) -> None:
    _db_setup(tmp_path, monkeypatch)
    from src.storage.system_settings import (
        acquire_scan_lease,
        release_scan_lease,
    )

    assert acquire_scan_lease() is True
    assert acquire_scan_lease() is False  # already held by the (unexpired) first lease
    release_scan_lease()
    assert acquire_scan_lease() is True  # freed → re-acquirable


def test_scan_lease_reacquired_after_expiry(tmp_path, monkeypatch) -> None:
    _db_setup(tmp_path, monkeypatch)
    from src.storage.system_settings import acquire_scan_lease

    assert acquire_scan_lease(ttl_seconds=0) is True  # expires immediately
    assert acquire_scan_lease() is True  # prior lease already expired → acquirable


def test_halt_round_trip(tmp_path, monkeypatch) -> None:
    _db_setup(tmp_path, monkeypatch)
    from src.storage.system_settings import get_halt_reason, is_halted, set_halted

    assert not is_halted()
    set_halted(True, "daily loss breach")
    assert is_halted()
    assert get_halt_reason() == "daily loss breach"

    set_halted(False)
    assert not is_halted()
    assert get_halt_reason() == ""


# --------------------------------------------------------------------------- #
# entry_orders_today / remaining_entry_allowance
# --------------------------------------------------------------------------- #


def test_entry_orders_today_excludes_closes_and_queued(tmp_path, monkeypatch) -> None:
    _db_setup(tmp_path, monkeypatch)
    from src.execution.circuit_breakers import entry_orders_today
    from src.storage.db import session_scope

    with session_scope() as s:
        s.add(OrderRow(candidate_id="c1", state=OrderState.SUBMITTED))
        s.add(OrderRow(candidate_id="c2", state=OrderState.FILLED))
        s.add(OrderRow(candidate_id="close:AAPL:x", state=OrderState.FILLED))  # close → excluded
        s.add(OrderRow(candidate_id="c3", state=OrderState.QUEUED))  # not opened yet → excluded
        s.add(OrderRow(candidate_id="c4", state=OrderState.CANCELLED))  # terminal-fail → excluded

    with session_scope() as s:
        assert entry_orders_today(s) == 2


def test_remaining_entry_allowance(tmp_path, monkeypatch) -> None:
    _db_setup(tmp_path, monkeypatch)
    _automation_cfg(monkeypatch, max_trades=3)
    from src.execution.circuit_breakers import remaining_entry_allowance
    from src.storage.db import session_scope

    with session_scope() as s:
        s.add(OrderRow(candidate_id="c1", state=OrderState.FILLED))

    with session_scope() as s:
        assert remaining_entry_allowance(s) == 2


def test_remaining_entry_allowance_never_negative(tmp_path, monkeypatch) -> None:
    _db_setup(tmp_path, monkeypatch)
    _automation_cfg(monkeypatch, max_trades=1)
    from src.execution.circuit_breakers import remaining_entry_allowance
    from src.storage.db import session_scope

    with session_scope() as s:
        s.add(OrderRow(candidate_id="c1", state=OrderState.FILLED))
        s.add(OrderRow(candidate_id="c2", state=OrderState.FILLED))

    with session_scope() as s:
        assert remaining_entry_allowance(s) == 0


def test_remaining_entry_allowance_disabled_when_cap_zero(tmp_path, monkeypatch) -> None:
    _db_setup(tmp_path, monkeypatch)
    _automation_cfg(monkeypatch, max_trades=0)
    from src.execution.circuit_breakers import remaining_entry_allowance
    from src.storage.db import session_scope

    with session_scope() as s:
        assert remaining_entry_allowance(s) is None


# --------------------------------------------------------------------------- #
# daily_loss_breached
# --------------------------------------------------------------------------- #


def test_daily_loss_breached_trips_on_net_debit(tmp_path, monkeypatch) -> None:
    _db_setup(tmp_path, monkeypatch)
    _automation_cfg(monkeypatch, loss_pct=5.0)
    from src.execution.circuit_breakers import daily_loss_breached
    from src.storage.db import session_scope

    # A buy-to-close debit of 0.60 × 100 × 100 = $6,000 (loss) vs 5% of 100k = $5,000 floor.
    with session_scope() as s:
        s.add(FillRow(order_id=1, candidate_id="x", action="BUY", filled_qty=100, avg_price=0.60))

    with session_scope() as s:
        loss = daily_loss_breached(s, 100_000.0)
    assert loss is not None and abs(loss - 6_000.0) < 1e-6


def test_daily_loss_not_breached_when_within_floor(tmp_path, monkeypatch) -> None:
    _db_setup(tmp_path, monkeypatch)
    _automation_cfg(monkeypatch, loss_pct=5.0)
    from src.execution.circuit_breakers import daily_loss_breached
    from src.storage.db import session_scope

    with session_scope() as s:
        s.add(FillRow(order_id=1, candidate_id="x", action="BUY", filled_qty=10, avg_price=0.60))

    with session_scope() as s:
        assert daily_loss_breached(s, 100_000.0) is None  # $600 loss < $5,000 floor


def test_daily_loss_not_breached_on_credit_day(tmp_path, monkeypatch) -> None:
    _db_setup(tmp_path, monkeypatch)
    _automation_cfg(monkeypatch, loss_pct=5.0)
    from src.execution.circuit_breakers import daily_loss_breached
    from src.storage.db import session_scope

    with session_scope() as s:
        s.add(FillRow(order_id=1, candidate_id="x", action="SELL", filled_qty=100, avg_price=2.00))

    with session_scope() as s:
        assert daily_loss_breached(s, 100_000.0) is None  # net credit → never a loss


def test_daily_loss_disabled_when_pct_zero(tmp_path, monkeypatch) -> None:
    _db_setup(tmp_path, monkeypatch)
    _automation_cfg(monkeypatch, loss_pct=0.0)
    from src.execution.circuit_breakers import daily_loss_breached
    from src.storage.db import session_scope

    with session_scope() as s:
        s.add(FillRow(order_id=1, candidate_id="x", action="BUY", filled_qty=1000, avg_price=5.00))

    with session_scope() as s:
        assert daily_loss_breached(s, 100_000.0) is None
