"""Tests for AUTOMATED-mode circuit breakers + the /halt kill switch (SYSTEM_REVIEW Phase 2)."""

from __future__ import annotations

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


def test_drawdown_breaker_measures_from_the_window_high(tmp_path, monkeypatch):
    from src.execution.circuit_breakers import drawdown_breached
    from tests.conftest import seed_net_liq_high

    _db_setup(tmp_path, monkeypatch)
    assert drawdown_breached(270_000.0) is None  # no history yet: nothing to measure from
    seed_net_liq_high(300_000.0)
    seed_net_liq_high(310_000.0, days_ago=1)
    assert drawdown_breached(320_000.0) is None  # a new high is no drawdown
    breach = drawdown_breached(270_000.0)  # -12.9% from 310k, cap 6%
    assert breach is not None and breach == pytest.approx(40_000.0)


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
    The drawdown now measures from the highest of the last 3 sessions only, read from the
    monitor's snapshots (which exist on days the breaker never ran)."""
    from src.execution.circuit_breakers import drawdown_breached
    from src.storage.portfolio_snapshots import window_high_net_liq
    from tests.conftest import seed_net_liq_high

    _db_setup(tmp_path, monkeypatch)
    for days_ago, high in [(5, 800_000.0), (2, 700_000.0), (1, 690_000.0), (0, 680_000.0)]:
        seed_net_liq_high(high, days_ago=days_ago)
    # A 5-days-ago peak is outside a 3-session window; the weekend-safe "sessions on file" count
    # is the last three days that have snapshots, here days 2, 1 and 0.
    assert window_high_net_liq(3) == pytest.approx(700_000.0)
    assert window_high_net_liq(4) == pytest.approx(800_000.0)
    assert drawdown_breached(665_000.0) is None  # 5% under 700k: inside the 6% line
    assert drawdown_breached(655_000.0) == pytest.approx(45_000.0)  # 6.4%


# --------------------------------------------------------------------------- #
# Risk envelope Task 6 — the spreads book counts in the daily loss leg (spec §3.2c)
# --------------------------------------------------------------------------- #


def _wheel_loss_today(tmp_path, monkeypatch, wheel_pnl: float, spreads_pnl: float | None):
    """A wheel book down *wheel_pnl* on the day, the spreads book's real-mode P&L patched in, and
    a 5% daily line on $300k of NLV ($15,000)."""
    from datetime import date, timedelta

    import src.execution.circuit_breakers as cb
    from src.common.schemas import PositionSnapshot
    from src.storage.positions import save_position_snapshot

    _db_setup(tmp_path, monkeypatch)
    cfg = SimpleNamespace(
        automation=SimpleNamespace(
            max_auto_trades_per_day=10,
            daily_loss_halt_pct=5.0,
            drawdown_halt_pct=0.0,
            drawdown_window_days=3,
        )
    )
    monkeypatch.setattr(cb, "get_config", lambda: cfg)
    monkeypatch.setattr(cb, "spreads_pnl_today", lambda day: spreads_pnl)

    def snap(pnl: float) -> list[PositionSnapshot]:
        return [
            PositionSnapshot(
                symbol="AAPL",
                sec_type="STK",
                position=100,
                avg_cost=200.0,
                underlying="AAPL",
                unrealized_pnl=pnl,
            )
        ]

    save_position_snapshot(date.today() - timedelta(days=1), snap(0.0))
    return snap(wheel_pnl)


def test_the_daily_leg_adds_spreads_pnl(tmp_path, monkeypatch) -> None:
    from src.execution.circuit_breakers import evaluate_breakers, mark_based_loss

    today = _wheel_loss_today(tmp_path, monkeypatch, -9_000.0, -7_000.0)
    # Neither book alone reaches $15,000; together they do.
    reason = evaluate_breakers(today, net_liquidation=300_000.0)
    assert reason is not None and "16,000" in reason
    assert mark_based_loss(today, net_liquidation=300_000.0) == pytest.approx(16_000.0)


def test_the_daily_leg_is_the_wheel_alone_without_a_spreads_loss(tmp_path, monkeypatch) -> None:
    from src.execution.circuit_breakers import evaluate_breakers, mark_based_loss

    for spreads in (None, 0.0, 20_000.0):  # no file, a flat day, a spreads gain
        today = _wheel_loss_today(tmp_path, monkeypatch, -9_000.0, spreads)
        assert evaluate_breakers(today, net_liquidation=300_000.0) is None
        assert mark_based_loss(today, net_liquidation=300_000.0) is None
    # A spreads gain never hides a wheel loss past the line.
    today = _wheel_loss_today(tmp_path, monkeypatch, -16_000.0, 20_000.0)
    assert evaluate_breakers(today, net_liquidation=300_000.0) is not None


def test_a_trip_card_shows_the_loss_by_book(tmp_path, monkeypatch) -> None:
    from src.execution.circuit_breakers import evaluate_breakers
    from src.notify.formatters import format_breaker_halt

    today = _wheel_loss_today(tmp_path, monkeypatch, -9_000.0, -7_000.0)
    reason = evaluate_breakers(today, net_liquidation=300_000.0)
    assert reason == "Daily mark-to-market loss $16,000 (wheel -$9,000, spreads -$7,000, hedge $0)"
    card = format_breaker_halt(reason)
    assert "HALTED" in card and "wheel -$9,000, spreads -$7,000" in card and "/resume" in card


# --------------------------------------------------------------------------- #
# The slow drawdown breaker spanning books (risk-envelope Task 22; spec §3.4.5, ruling E14)
# --------------------------------------------------------------------------- #


def _slow_history() -> None:
    """A 20-session high of 1,000k ten days back; the 3-session window sits at 950k."""
    from tests.conftest import seed_net_liq_high

    seed_net_liq_high(1_000_000.0, days_ago=10)
    seed_net_liq_high(950_000.0, days_ago=2)
    seed_net_liq_high(950_000.0, days_ago=1)
    seed_net_liq_high(900_000.0, days_ago=0)


def _slow_on(threshold: str = "10") -> None:
    from src.storage.envelope_switches import set_switch

    set_switch("slow_breaker", threshold, source="cli")


def test_slow_leg_trips_at_the_switch_threshold(tmp_path, monkeypatch) -> None:
    import json

    from src.execution.circuit_breakers import evaluate_slow_breaker, slow_drawdown
    from src.storage.system_settings import get_setting_strict

    _db_setup(tmp_path, monkeypatch)
    _slow_history()
    _slow_on("10")
    assert slow_drawdown(900_000.0) == pytest.approx(10.0)
    assert evaluate_slow_breaker(901_000.0) is None  # 9.9%: under the line
    assert get_setting_strict("slow_breaker_tripped") is None
    notice = evaluate_slow_breaker(900_000.0)  # exactly 10%
    assert notice is not None and "TRIPPED" in notice and "reset-slow-breaker" in notice
    state = json.loads(get_setting_strict("slow_breaker_tripped") or "{}")
    assert state["tripped"] is True and state["drawdown_pct"] == pytest.approx(10.0)
    assert state["threshold_pct"] == 10.0
    assert evaluate_slow_breaker(850_000.0) is None  # notifies once, on the call that trips it


def test_slow_leg_off_never_trips(tmp_path, monkeypatch) -> None:
    from src.common.config import Config
    from src.execution.circuit_breakers import evaluate_slow_breaker
    from src.storage.system_settings import get_setting_strict

    _db_setup(tmp_path, monkeypatch)
    _slow_history()
    assert evaluate_slow_breaker(500_000.0) is None  # the default: off
    assert get_setting_strict("slow_breaker_tripped") is None
    _slow_on("15")
    assert evaluate_slow_breaker(900_000.0) is None  # 10% is under a 15% threshold
    _slow_on("8")
    # live reads every switch as its default (off) whatever is stored
    monkeypatch.setattr(Config, "is_live", property(lambda self: True))
    assert evaluate_slow_breaker(500_000.0) is None
    assert get_setting_strict("slow_breaker_tripped") is None


def test_a_trip_scales_the_csp_budget(tmp_path, monkeypatch) -> None:
    from src.common.config import Config, get_config
    from src.common.schemas import Verdict
    from src.engine.capital import resolve_caps
    from src.engine.risk_engine import validate_candidates
    from src.execution.circuit_breakers import evaluate_slow_breaker
    from src.storage import slow_breaker
    from src.storage.envelope_switches import set_switch
    from tests.test_engine import _account, _candidate

    _db_setup(tmp_path, monkeypatch)
    account = _account(net_liq=500_000.0, cash=100_000.0)  # deployable 80k after the 20% reserve
    cand = _candidate(candidate_id="big", collateral=50_000.0)

    def verdict() -> list[str]:
        v = validate_candidates([cand], account, [])[0]
        return [] if v.verdict == Verdict.PASS else list(v.reasons)

    risk = get_config().risk
    assert resolve_caps(account, risk).max_csp_collateral == pytest.approx(80_000.0)
    half = resolve_caps(account, risk, csp_fraction=0.5)
    assert half.max_csp_collateral == pytest.approx(40_000.0)
    assert verdict() == []
    _slow_history()
    _slow_on("10")
    assert slow_breaker.csp_budget_fraction() == 1.0  # on, but not tripped
    assert evaluate_slow_breaker(900_000.0) is not None
    assert slow_breaker.csp_budget_fraction() == 0.5
    assert "csp_allocation_limit" in verdict()  # 50k fits 80k, not 40k
    # switched off, an old trip does not throttle the wheel; in live the same
    set_switch("slow_breaker", "off", source="cli")
    assert slow_breaker.csp_budget_fraction() == 1.0 and verdict() == []
    set_switch("slow_breaker", "10", source="cli")
    assert slow_breaker.csp_budget_fraction() == 0.5
    monkeypatch.setattr(Config, "is_live", property(lambda self: True))
    assert slow_breaker.csp_budget_fraction() == 1.0 and verdict() == []


def test_a_trip_stops_spreads_entries(tmp_path, monkeypatch) -> None:
    """The setting Task 3's spreads gate reads: the service's own reader sees the trip."""
    from types import SimpleNamespace

    from src.execution.circuit_breakers import evaluate_slow_breaker
    from src.spreads.service import SpreadsService

    _db_setup(tmp_path, monkeypatch)
    _slow_history()
    _slow_on("10")
    stub = SimpleNamespace(_account_unreadable=False)
    assert SpreadsService._account_state(stub) == (False, False)  # type: ignore[arg-type]
    assert evaluate_slow_breaker(900_000.0) is not None
    assert SpreadsService._account_state(stub) == (False, True)  # type: ignore[arg-type]


def test_only_a_human_resets_it(tmp_path, monkeypatch, capsys) -> None:
    from unittest.mock import AsyncMock

    from scripts import envelope as cli
    from src.execution.circuit_breakers import evaluate_slow_breaker
    from src.storage import slow_breaker
    from tests.conftest import seed_net_liq_high

    _db_setup(tmp_path, monkeypatch)
    _slow_history()
    _slow_on("10")
    assert evaluate_slow_breaker(900_000.0) is not None
    assert evaluate_slow_breaker(1_100_000.0) is None  # a recovery does not clear it
    assert slow_breaker.is_tripped()
    notice = AsyncMock(return_value=True)
    monkeypatch.setattr(cli, "send_notice", notice)
    assert cli.main(["show"]) == 0 and "TRIPPED" in capsys.readouterr().out
    assert cli.main(["reset-slow-breaker"]) == 0
    notice.assert_awaited_once()
    assert not slow_breaker.is_tripped()
    assert cli.main(["reset-slow-breaker"]) == 0  # nothing left to reset
    assert "nothing to reset" in capsys.readouterr().out
    # the window restarts at the reset: still 10% under the OLD high, but not tripped again at once
    assert evaluate_slow_breaker(900_000.0) is None
    assert not slow_breaker.is_tripped()
    # ...and a fresh 10% fall from the post-reset high trips it
    seed_net_liq_high(900_000.0, days_ago=0)
    assert evaluate_slow_breaker(810_000.0) is not None


def test_a_trip_is_not_a_halt(tmp_path, monkeypatch) -> None:
    from src.execution.circuit_breakers import evaluate_breakers, evaluate_slow_breaker
    from src.storage import slow_breaker
    from src.storage.system_settings import is_halted

    _db_setup(tmp_path, monkeypatch)
    _slow_history()
    _slow_on("10")
    # 5.3% under the 3-session high (950k): the 6% fast leg stays quiet
    assert evaluate_breakers([], net_liquidation=900_000.0) is None
    assert evaluate_slow_breaker(900_000.0) is not None
    assert slow_breaker.is_tripped()
    assert is_halted() is False
    assert evaluate_breakers([], net_liquidation=900_000.0) is None
