"""Tests for AUTOMATED-mode circuit breakers + the /halt kill switch (SYSTEM_REVIEW Phase 2)."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

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

    token = acquire_scan_lease()
    assert token is not None
    assert acquire_scan_lease() is None  # already held by the (unexpired) first lease
    release_scan_lease(token)
    assert acquire_scan_lease() is not None  # freed → re-acquirable


def test_scan_lease_reacquired_after_expiry(tmp_path, monkeypatch) -> None:
    _db_setup(tmp_path, monkeypatch)
    from src.storage.system_settings import acquire_scan_lease

    assert acquire_scan_lease(ttl_seconds=0) is not None  # expires immediately
    assert acquire_scan_lease() is not None  # prior lease already expired → acquirable


def test_scan_lease_release_is_compare_and_swap(tmp_path, monkeypatch) -> None:
    """N7: a stale holder's release must not clear a lease another process has re-claimed."""
    _db_setup(tmp_path, monkeypatch)
    from src.storage.system_settings import acquire_scan_lease, release_scan_lease

    stale = acquire_scan_lease(ttl_seconds=0)  # acquired but already expired
    assert stale is not None
    fresh = acquire_scan_lease()  # second process claims the now-free lease
    assert fresh is not None
    release_scan_lease(stale)  # stale holder finishes — must NOT free the fresh lease
    assert acquire_scan_lease() is None  # fresh lease still held
    release_scan_lease(fresh)
    assert acquire_scan_lease() is not None  # real holder's release frees it


def test_scan_lease_renew_extends_and_is_owner_scoped(tmp_path, monkeypatch) -> None:
    """N7: renew extends the holder's lease; a non-owner renew is rejected."""
    _db_setup(tmp_path, monkeypatch)
    from src.storage.system_settings import acquire_scan_lease, renew_scan_lease

    token = acquire_scan_lease(ttl_seconds=0)  # immediately expired
    assert token is not None
    assert renew_scan_lease(token) is True  # owner renews → lease now in the future
    assert acquire_scan_lease() is None  # renewed lease is held, not free
    assert renew_scan_lease("not-the-owner") is False


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


# --------------------------------------------------------------------------- #
# mark_based_loss / drawdown_breached (D3: mark-to-market kill switches)
# --------------------------------------------------------------------------- #


def test_mark_based_loss_sees_a_drawdown_that_cashflow_misses(tmp_path, monkeypatch):
    """D3: selling premium into a 15% drawdown reads as a PROFIT to the cashflow breaker."""
    from datetime import date, timedelta

    from src.common.schemas import PositionSnapshot
    from src.execution.circuit_breakers import mark_based_loss
    from src.storage.positions import save_position_snapshot

    _db_setup(tmp_path, monkeypatch)  # existing helper in this file
    yesterday = [
        PositionSnapshot(
            symbol="AAPL",
            sec_type="STK",
            position=100,
            avg_cost=200.0,
            underlying="AAPL",
            unrealized_pnl=0.0,
        )
    ]
    save_position_snapshot(date.today() - timedelta(days=1), yesterday)

    today = [
        PositionSnapshot(
            symbol="AAPL",
            sec_type="STK",
            position=100,
            avg_cost=200.0,
            underlying="AAPL",
            unrealized_pnl=-12_000.0,
        )
    ]
    loss = mark_based_loss(today, net_liquidation=300_000.0)
    assert loss is not None and loss == pytest.approx(12_000.0)


def test_mark_based_loss_returns_none_below_the_threshold(tmp_path, monkeypatch):
    from datetime import date, timedelta

    from src.common.schemas import PositionSnapshot
    from src.execution.circuit_breakers import mark_based_loss
    from src.storage.positions import save_position_snapshot

    _db_setup(tmp_path, monkeypatch)
    save_position_snapshot(
        date.today() - timedelta(days=1),
        [
            PositionSnapshot(
                symbol="AAPL",
                sec_type="STK",
                position=100,
                avg_cost=200.0,
                underlying="AAPL",
                unrealized_pnl=0.0,
            )
        ],
    )
    today = [
        PositionSnapshot(
            symbol="AAPL",
            sec_type="STK",
            position=100,
            avg_cost=200.0,
            underlying="AAPL",
            unrealized_pnl=-1_000.0,
        )
    ]
    assert mark_based_loss(today, net_liquidation=300_000.0) is None


def test_drawdown_breaker_tracks_the_high_water_mark(tmp_path, monkeypatch):
    from src.execution.circuit_breakers import drawdown_breached
    from src.storage.system_settings import get_high_water_mark

    _db_setup(tmp_path, monkeypatch)
    assert drawdown_breached(300_000.0) is None  # first call seeds the HWM
    assert get_high_water_mark() == pytest.approx(300_000.0)
    assert drawdown_breached(310_000.0) is None  # new high
    assert get_high_water_mark() == pytest.approx(310_000.0)
    breach = drawdown_breached(270_000.0)  # -12.9% from 310k, cap 10%
    assert breach is not None and breach == pytest.approx(40_000.0)


def test_a_base_currency_high_water_mark_never_trips_the_usd_breaker(tmp_path, monkeypatch):
    """2026-10-12: the HWM was stored as S$1,044,124 (SGD base, before 099fd0a made net liq
    USD); against US$786,836 it read as a 24.6% drawdown and halted every scan all day. The
    pre-USD key is never read: the breaker re-seeds from the first USD figure."""
    from src.execution.circuit_breakers import drawdown_breached
    from src.storage.system_settings import get_high_water_mark, set_setting

    _db_setup(tmp_path, monkeypatch)
    set_setting("nlv_high_water_mark", "1044124.49")  # the legacy, base-currency row
    assert drawdown_breached(786_836.0) is None
    assert get_high_water_mark() == pytest.approx(786_836.0)
    assert drawdown_breached(700_000.0) == pytest.approx(86_836.0)  # -11% in USD still trips


def test_a_halt_records_its_source_and_resume_clears_it(tmp_path, monkeypatch):
    from src.storage.system_settings import get_halt_source, set_halted

    _db_setup(tmp_path, monkeypatch)
    set_halted(True, "manual /halt")
    assert get_halt_source() == "operator"
    set_halted(True, "Drawdown $1 from high-water mark", source="breaker")
    assert get_halt_source() == "breaker"
    set_halted(False)
    assert get_halt_source() == ""


def test_the_drawdown_window_forgets_a_peak_older_than_three_sessions(tmp_path, monkeypatch):
    """2026-11-05: an all-time peak left the breaker in breach every morning for two weeks.
    The drawdown now measures from the highest of the last 3 sessions only."""
    from src.execution.circuit_breakers import drawdown_breached
    from src.storage.system_settings import get_high_water_mark, set_high_water_mark

    _db_setup(tmp_path, monkeypatch)
    for day, high in [(1, 800_000.0), (2, 700_000.0), (3, 690_000.0), (4, 680_000.0)]:
        set_high_water_mark(high, today=date(2026, 11, day))
    # The 800k peak is 3 sessions back: out of a 3-session window ending Nov 4.
    assert get_high_water_mark(3, today=date(2026, 11, 4)) == pytest.approx(700_000.0)
    assert get_high_water_mark(4, today=date(2026, 11, 4)) == pytest.approx(800_000.0)
    # Standing 5% below the window's high is not a breach at the 6% line.
    assert drawdown_breached(665_000.0) is None


def test_a_lower_print_never_lowers_the_days_high(tmp_path, monkeypatch):
    from src.storage.system_settings import get_high_water_mark, set_high_water_mark

    _db_setup(tmp_path, monkeypatch)
    set_high_water_mark(500_000.0, today=date(2026, 11, 2))
    set_high_water_mark(480_000.0, today=date(2026, 11, 2))
    assert get_high_water_mark(3, today=date(2026, 11, 2)) == pytest.approx(500_000.0)
