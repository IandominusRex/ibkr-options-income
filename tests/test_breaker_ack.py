"""/resume on a circuit-breaker halt, rolls through a breaker halt, and the roll-mode setting
(2026-10-15).

The incident: the daily-loss breaker tripped on a $25K mark-to-market loss; /resume cleared the
flag, and the next 30-second poll re-measured the same loss against the same baseline and halted
again, for as long as the loss stood. A resume now records the loss the operator resumed through.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.common.schemas import AutonomyLevel, OrderState, PositionSnapshot
from src.storage.models import ApprovalRow, FillRow, OrderRow

NLV = 300_000.0  # 3% line = $9,000
LINE = 9_000.0


def _db_setup(tmp_path, monkeypatch) -> None:
    import src.storage.db as dbmod
    from src.common.config import Config

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{tmp_path / 't.db'}")
    dbmod.init_db()


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    _db_setup(tmp_path, monkeypatch)


def _stock(unrealized: float) -> PositionSnapshot:
    return PositionSnapshot(
        symbol="AAPL",
        sec_type="STK",
        position=100,
        avg_cost=200.0,
        underlying="AAPL",
        unrealized_pnl=unrealized,
    )


def _baseline(*positions: PositionSnapshot) -> None:
    from src.storage.positions import save_position_snapshot

    save_position_snapshot(date.today() - timedelta(days=1), list(positions))


def _breaker_halt() -> str:
    """Trip the breaker the way process_queued_orders does, then /resume."""
    from src.execution.circuit_breakers import evaluate_breakers
    from src.storage.system_settings import set_halted

    reason = evaluate_breakers([_stock(-12_000.0)], NLV)
    assert reason is not None
    set_halted(True, reason, source="breaker")
    return reason


# --------------------------------------------------------------------------- #
# /resume stops the same loss re-tripping the breaker
# --------------------------------------------------------------------------- #


def test_a_loss_over_the_line_trips_when_nobody_has_resumed() -> None:
    from src.execution.circuit_breakers import evaluate_breakers

    _baseline(_stock(0.0))
    reason = evaluate_breakers([_stock(-12_000.0)], NLV)
    assert reason == "Daily mark-to-market loss $12,000"


def test_resume_lets_the_loss_that_was_acknowledged_stand() -> None:
    from src.execution.circuit_breakers import evaluate_breakers
    from src.storage.system_settings import is_halted, set_halted

    _baseline(_stock(0.0))
    _breaker_halt()
    set_halted(False)
    assert not is_halted()
    # The very next poll — the one that used to re-trip — measures the same loss and stays quiet.
    assert evaluate_breakers([_stock(-12_000.0)], NLV) is None
    assert evaluate_breakers([_stock(-12_000.0)], NLV) is None
    assert evaluate_breakers([_stock(-20_900.0)], NLV) is None  # < 12,000 + 9,000


def test_a_further_full_step_of_loss_trips_it_again() -> None:
    from src.execution.circuit_breakers import evaluate_breakers
    from src.storage.system_settings import set_halted

    _baseline(_stock(0.0))
    _breaker_halt()
    set_halted(False)
    assert evaluate_breakers([_stock(-12_000.0)], NLV) is None
    assert evaluate_breakers([_stock(-21_000.0)], NLV) == "Daily mark-to-market loss $21,000"


def test_the_ack_lasts_one_et_day(monkeypatch) -> None:
    import src.execution.circuit_breakers as cb
    from src.storage.system_settings import set_halted

    _baseline(_stock(0.0))
    _breaker_halt()
    set_halted(False)
    assert cb.evaluate_breakers([_stock(-12_000.0)], NLV) is None

    tomorrow = date.today() + timedelta(days=1)
    monkeypatch.setattr(cb, "today_et", lambda: tomorrow)
    # A new day's baseline (yesterday's EOD) is whatever EOD saved; here the same -12K book is
    # simply a fresh breach with no acknowledgement behind it.
    _baseline(_stock(0.0))
    assert cb.evaluate_breakers([_stock(-12_000.0)], NLV) is not None


def test_an_operator_halt_resume_acknowledges_nothing() -> None:
    from src.execution.circuit_breakers import evaluate_breakers
    from src.storage.system_settings import get_breaker_ack, set_halted

    _baseline(_stock(0.0))
    set_halted(True, "manual /halt")  # source = operator
    set_halted(False)
    assert get_breaker_ack(date.today()) is None
    assert evaluate_breakers([_stock(-12_000.0)], NLV) is not None


def test_resuming_while_under_the_line_adds_no_head_room() -> None:
    """An ack armed when the loss is below the line is stored as 0, never as that small
    loss — otherwise it would raise the trip point above the normal line."""
    from src.execution.circuit_breakers import evaluate_breakers
    from src.storage.system_settings import arm_breaker_ack

    _baseline(_stock(0.0))
    arm_breaker_ack()
    assert evaluate_breakers([_stock(-2_000.0)], NLV) is None
    assert evaluate_breakers([_stock(-9_500.0)], NLV) is not None


def test_the_drawdown_breaker_honours_the_ack_too() -> None:
    from src.execution.circuit_breakers import evaluate_breakers
    from src.storage.system_settings import set_halted, set_high_water_mark

    set_high_water_mark(300_000.0)  # 6% line = $18,000
    reason = evaluate_breakers([], 265_000.0)
    assert reason == "Drawdown $35,000 from the 3-session high"
    set_halted(True, reason, source="breaker")
    set_halted(False)
    assert evaluate_breakers([], 265_000.0) is None
    assert evaluate_breakers([], 248_000.0) is None  # 52K < 35K + 18K
    assert evaluate_breakers([], 246_000.0) is not None


# --------------------------------------------------------------------------- #
# The loss measure counts what closing a position realized today
# --------------------------------------------------------------------------- #


def _short_put(unrealized: float = -500.0) -> PositionSnapshot:
    return PositionSnapshot(
        symbol="TQQQ  261016P00078000",
        sec_type="OPT",
        position=-10,
        avg_cost=122.0,
        market_price=1.50,  # the EOD mark
        unrealized_pnl=unrealized,
        right="P",
        strike=78.0,
        expiry=date(2026, 10, 16),
        underlying="TQQQ",
    )


def _close_fill(price: float, qty: float = 10) -> None:
    from src.storage.db import session_scope

    with session_scope() as s:
        s.add(
            FillRow(
                order_id=1,
                candidate_id="close:TQQQ:20261016:78:P",
                action="BUY",
                filled_qty=qty,
                avg_price=price,
                filled_at=datetime.now(UTC),
            )
        )


def test_a_loss_exit_close_counts_as_the_loss_it_realized() -> None:
    from src.execution.circuit_breakers import _mark_delta

    _baseline(_short_put())
    _close_fill(2.80)  # bought back $1.30 over the EOD mark, ten contracts
    assert _mark_delta([]) == pytest.approx(-1_300.0)


def test_a_profit_take_close_is_not_read_as_a_loss() -> None:
    """The old sum dropped the closed short's unrealized from the book and read a winner as a
    loss of exactly that much."""
    from src.execution.circuit_breakers import _mark_delta

    _baseline(_short_put(unrealized=+800.0))
    _close_fill(0.50)
    assert _mark_delta([]) == pytest.approx(+1_000.0)


def test_a_vanished_position_with_no_close_fill_is_neutral() -> None:
    from src.execution.circuit_breakers import _mark_delta

    _baseline(_short_put(unrealized=-5_000.0), _stock(0.0))
    assert _mark_delta([_stock(-100.0)]) == pytest.approx(-100.0)


# --------------------------------------------------------------------------- #
# roll mode and may_auto_roll
# --------------------------------------------------------------------------- #


def test_roll_mode_defaults_to_auto_and_rejects_garbage() -> None:
    from src.storage.system_settings import get_roll_mode, set_roll_mode, set_setting

    assert get_roll_mode() == "auto"
    set_roll_mode("propose")
    assert get_roll_mode() == "propose"
    with pytest.raises(ValueError):
        set_roll_mode("yolo")
    set_setting("roll_mode", "junk")
    assert get_roll_mode() == "auto"


def test_full_autonomy_auto_rolls_but_propose_mode_waits_for_a_tap() -> None:
    from src.storage.system_settings import may_auto_roll, set_autonomy_level, set_roll_mode

    set_autonomy_level(AutonomyLevel.FULL)
    assert may_auto_roll("GOOGL") is True
    set_roll_mode("propose")
    assert may_auto_roll("GOOGL") is False


@pytest.mark.parametrize("level", [AutonomyLevel.OBSERVE, AutonomyLevel.MANUAL])
def test_the_low_rungs_never_auto_roll(level) -> None:
    from src.storage.system_settings import may_auto_roll, set_autonomy_level

    set_autonomy_level(level)
    assert may_auto_roll("GOOGL") is False


def test_whitelist_auto_rolls_only_listed_symbols(monkeypatch) -> None:
    from src.storage.system_settings import may_auto_roll, set_autonomy_level

    set_autonomy_level(AutonomyLevel.WHITELIST)
    monkeypatch.setattr("src.storage.system_settings._autonomy_whitelist", lambda: {"GOOGL"})
    assert may_auto_roll("GOOGL") is True
    assert may_auto_roll("AMZN") is False


def test_a_breaker_halt_does_not_stop_an_auto_roll_but_an_operator_halt_does() -> None:
    from src.storage.system_settings import (
        may_auto_open,
        may_auto_roll,
        set_autonomy_level,
        set_halted,
    )

    set_autonomy_level(AutonomyLevel.FULL)
    set_halted(True, "Daily mark-to-market loss $25,011", source="breaker")
    assert may_auto_roll("GOOGL") is True
    assert may_auto_open("GOOGL") is False  # new exposure stays blocked
    set_halted(True, "manual /halt")
    assert may_auto_roll("GOOGL") is False


# --------------------------------------------------------------------------- #
# process_queued_orders: a breaker halt lets rolls (only) through
# --------------------------------------------------------------------------- #


def _queue(candidate_id: str, strategy: str) -> int:
    from src.storage.db import session_scope

    with session_scope() as s:
        approval = ApprovalRow(
            candidate_id=candidate_id,
            status="approved",
            expires_at=datetime.now(UTC) - timedelta(minutes=5),  # already stale → TTL path
        )
        s.add(approval)
        s.flush()
        order = OrderRow(
            candidate_id=candidate_id,
            approval_id=approval.id,
            state=OrderState.QUEUED,
            snapshot={"strategy": strategy},
        )
        s.add(order)
        s.flush()
        return order.id


async def _run_poll(monkeypatch) -> None:
    from src.execution.approval import process_queued_orders

    cfg = MagicMock()
    cfg.secrets.ibkr_account = ""
    cfg.execution.transmit_only_in_rth = False
    monkeypatch.setattr("src.execution.approval.get_config", lambda: cfg)
    monkeypatch.setattr("src.execution.approval.get_positions", lambda ib: [])
    monkeypatch.setattr(
        "src.execution.approval.get_account_snapshot_async",
        AsyncMock(return_value=MagicMock(net_liquidation=NLV)),
    )
    ib = MagicMock()
    ib.managedAccounts.return_value = ["DU1"]
    await process_queued_orders(ib, AsyncMock(), "1")


def _state(order_id: int) -> str:
    from src.storage.db import session_scope

    with session_scope() as s:
        return s.get(OrderRow, order_id).state


async def test_a_breaker_halt_processes_queued_rolls_and_nothing_else(monkeypatch) -> None:
    from src.storage.system_settings import set_halted

    roll = _queue("roll-1", "roll")
    entry = _queue("entry-1", "cash_secured_put")
    set_halted(True, "Daily mark-to-market loss $25,011", source="breaker")

    await _run_poll(monkeypatch)

    assert _state(roll) == OrderState.CANCELLED  # reached the TTL check: it was processed
    assert _state(entry) == OrderState.QUEUED  # untouched


async def test_an_operator_halt_blocks_queued_rolls(monkeypatch) -> None:
    from src.storage.system_settings import set_halted

    roll = _queue("roll-1", "roll")
    set_halted(True, "manual /halt")

    await _run_poll(monkeypatch)

    assert _state(roll) == OrderState.QUEUED


# --------------------------------------------------------------------------- #
# the set_roll_mode drain handler
# --------------------------------------------------------------------------- #


async def test_the_set_roll_mode_handler_flips_the_setting() -> None:
    from types import SimpleNamespace

    from src.notify.command_drain import HANDLERS
    from src.storage.system_settings import get_roll_mode

    command = SimpleNamespace(id=1, payload={"mode": "propose"}, requested_by="owner")
    result = HANDLERS["set_roll_mode"](command=command, bot=AsyncMock(), chat_id="1")
    assert result == {"mode": "propose", "previous": "auto"}
    assert get_roll_mode() == "propose"
    again = HANDLERS["set_roll_mode"](
        command=SimpleNamespace(id=2, payload={"mode": "auto"}, requested_by="owner"),
        bot=AsyncMock(),
        chat_id="1",
    )
    assert again == {"mode": "auto", "previous": "propose"}


def test_a_drawdown_ack_carries_across_the_window_but_a_loss_ack_does_not(
    tmp_path, monkeypatch
) -> None:
    """The 3-session window still holds the same drop tomorrow, so /resume on a drawdown halt
    must not re-halt at the next open; a daily-loss ack still lapses at the end of its ET day."""
    import json

    from src.storage.system_settings import BREAKER_ACK_KEY, get_breaker_ack, set_setting

    today = date(2026, 11, 5)
    ack = {"date": "2026-11-04", "loss": 7_000.0, "drawdown": 35_000.0}
    set_setting(BREAKER_ACK_KEY, json.dumps(ack))
    assert get_breaker_ack(today) is None  # default keep_days=1: lapsed
    carried = get_breaker_ack(today, keep_days=3)
    assert carried == {"loss": 0.0, "drawdown": 35_000.0}
    assert get_breaker_ack(date(2026, 11, 7), keep_days=3) is None  # past the window
    set_setting(BREAKER_ACK_KEY, json.dumps({**ack, "drawdown": None}))
    assert get_breaker_ack(today, keep_days=3) is None  # armed, never measured: do not carry
