from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from src.common.config import get_config
from src.spreads.backtest.engine import (
    DayData,
    backtest_cfg,
    load_day,
    run_backtest,
    run_day,
    with_overrides,
)

DAY = date(2026, 10, 7)
M0931 = datetime(2026, 10, 7, 13, 31, tzinfo=UTC)
M0935 = datetime(2026, 10, 7, 13, 35, tzinfo=UTC)
M0940 = datetime(2026, 10, 7, 13, 40, tzinfo=UTC)
M0945 = datetime(2026, 10, 7, 13, 45, tzinfo=UTC)
M0950 = datetime(2026, 10, 7, 13, 50, tzinfo=UTC)
M1000 = datetime(2026, 10, 7, 14, 0, tzinfo=UTC)
M1100 = datetime(2026, 10, 7, 15, 0, tzinfo=UTC)
M1546 = datetime(2026, 10, 7, 19, 46, tzinfo=UTC)

_BASE = get_config().spreads
# The mechanics tests pin the original rule (map 09:45, entries from 10:00, every check, both
# sides) and one contract; MOVE_CFG below replays the amendment's trigger, and the sizing tests
# lift the contract cap.
CFG = _BASE.model_copy(
    update={
        "schedule": _BASE.schedule.model_copy(
            update={
                "map_time": "09:45",
                "entry_start": "10:00",
                "entry_end": "13:30",
                "entry_check_minutes": 5,
                "map_refresh_minutes": 60,
                "force_close": "15:45",
            }
        ),
        "entry": _BASE.entry.model_copy(update={"trigger": "always"}),
        "selection": _BASE.selection.model_copy(
            update={
                "sides": ["put", "call"],
                "width": 5.0,
                "min_credit_pct_of_width": 0.05,
                "short_delta_max": 0.15,
                "max_leg_spread_pct": 0.30,
                "em_multiple": 1.0,
                "wall_buffer_pct": 0.001,
                "em_straddle_factor": 1.0,
            }
        ),
        "risk": _BASE.risk.model_copy(
            update={
                "max_contracts": 1,
                "starting_capital_usd": 100_000.0,
                "max_loss_pct_of_capital": 0.10,
                "max_total_risk_pct_of_capital": 0.10,
                "max_daily_loss_pct_of_capital": 0.10,
                "max_open_spreads": 2,
                "max_trades_per_day": 2,
                "one_side_per_day": True,
                "events": [],
                "ex_dividend_dates": [],
            }
        ),
        "exits": _BASE.exits.model_copy(
            update={
                "profit_take_pct": 50.0,
                "stop_debit_multiple": 2.0,
                "max_hold_minutes": 150,
                "let_expire_max_debit": 0.05,
            }
        ),
        "execution": _BASE.execution.model_copy(update={"commission_per_contract": 0.65}),
        "backtest": _BASE.backtest.model_copy(update={"trade_scale": 10.0, "fill_haircut": 0.5}),
        "gex": _BASE.gex.model_copy(
            update={"negative_gamma_action": "skip", "flip_buffer_pct": 0.002}
        ),
    }
)

MORNING = {
    (6900.0, "C"): (19.9, 20.1),
    (6900.0, "P"): (19.9, 20.1),  # expected move 40 SPX points
    (6800.0, "P"): (4.8, 5.2),  # put OI carrier → put wall 6800
    (6950.0, "C"): (7.8, 8.2),  # call OI carrier → call wall 6950, positive gamma at 6900
    (6790.0, "P"): (4.0, 4.4),
    (6740.0, "P"): (1.0, 1.2),
}
OI = {(6800.0, "P"): 1_000, (6950.0, "C"): 40_000}


def _day(later: dict[datetime, dict]) -> DayData:
    quotes = {M0945: MORNING, M1000: MORNING, **later}
    return DayData(day=DAY, spot={m: 6900.0 for m in quotes}, quotes=quotes, oi=OI)


def test_backtest_cfg_restates_the_rules_in_spx_units() -> None:
    b = backtest_cfg(CFG)
    assert b.selection.width == 50.0 and b.gex.scale_to_underlying == 1.0
    assert b.exits.let_expire_max_debit == pytest.approx(0.5)
    assert (
        b.risk.max_loss_pct_of_capital == CFG.risk.max_loss_pct_of_capital
    )  # shares need no scaling
    assert b.enabled and b.mode == "shadow"


def test_a_day_that_takes_profit() -> None:
    later = {M1100: {(6790.0, "P"): (1.0, 1.2), (6740.0, "P"): (0.2, 0.3)}}
    (t,) = run_day(_day(later), CFG)
    assert (t.side, t.short_strike, t.long_strike) == ("put", 6790.0, 6740.0)
    assert t.entry_credit == pytest.approx(2.95)  # 3.10 mid, half-way to the 2.80 natural
    assert t.exit_reason == "profit_take" and t.exit_debit == pytest.approx(0.925)
    assert t.regime == "positive"
    assert t.pnl_usd == pytest.approx((2.95 - 0.925) * 100 / 10 - 4 * 0.65)
    assert (t.trigger, t.entry_time) == ("always", M1000)
    assert t.hold_minutes == pytest.approx(60.0) and t.mae_usd == pytest.approx(0.0)


def test_a_cash_settled_day_left_to_expire_settles_at_intrinsic() -> None:
    later = {M1546: {(6790.0, "P"): (0.02, 0.05), (6740.0, "P"): (0.0, 0.02)}}
    cash_settled = CFG.model_copy(
        update={"exits": CFG.exits.model_copy(update={"let_expire": True})}
    )
    (t,) = run_day(_day(later), cash_settled)
    assert t.exit_reason == "expired" and t.exit_debit == 0.0
    assert t.pnl_usd == pytest.approx(2.95 * 100 / 10 - 2 * 0.65)


def test_a_spy_day_closes_at_the_time_stop_instead() -> None:
    later = {M1546: {(6790.0, "P"): (0.02, 0.05), (6740.0, "P"): (0.0, 0.02)}}
    (t,) = run_day(_day(later), CFG)  # exits.let_expire: false, the SPY default
    assert t.exit_reason == "time_stop"
    assert t.exit_debit == pytest.approx(0.0375)  # mid 0.025, half-way to the 0.05 natural


class FakeClient:
    def __init__(self) -> None:
        self.days: list[date] = []

    def index_prices(self, symbol, day, interval="1m"):
        self.days.append(day)
        return [{"timestamp": "2026-10-07T09:45:00.000", "price": "6900"}]

    def option_quotes(self, symbol, expiration, day, interval="1m"):
        return [
            {
                "strike": "6790",
                "right": "PUT",
                "timestamp": "2026-10-07T09:45:00.000",
                "bid": "4.0",
                "ask": "4.4",
            },
            {
                "strike": "6790",
                "right": "C",
                "timestamp": "2026-10-07T09:45:00.000",
                "bid": "0",
                "ask": "0",
            },
        ]

    def open_interest(self, symbol, expiration, day):
        return [{"strike": "6800", "right": "P", "open_interest": "1000"}]


def test_load_day_parses_et_timestamps_rights_and_drops_empty_asks() -> None:
    data = load_day(FakeClient(), CFG.backtest, DAY)
    assert data.spot == {M0945: 6900.0}
    assert data.quotes == {M0945: {(6790.0, "P"): (4.0, 4.4)}}
    assert data.oi == {(6800.0, "P"): 1000}
    assert data.prior_close == 6900.0  # the previous session's last print


def test_run_backtest_skips_non_trading_days() -> None:
    client = FakeClient()
    run_backtest(client, CFG, date(2026, 10, 9), date(2026, 10, 12))  # Fri, Sat, Sun, Mon
    # Each trading day reads its own index prices, then the previous session's for the prior close.
    assert client.days == [
        date(2026, 10, 9),
        date(2026, 10, 8),
        date(2026, 10, 12),
        date(2026, 10, 9),
    ]


MOVE_CFG = CFG.model_copy(
    update={
        "schedule": CFG.schedule.model_copy(update={"map_time": "09:31", "entry_start": "09:35"}),
        "entry": CFG.entry.model_copy(
            update={
                "trigger": "move",
                "min_move_em": 0.5,
                "max_move_em": 1.5,
                "stall_minutes": 10,
                "max_tape_age_seconds": 120.0,
                "gap_day_pct": 0.003,
            }
        ),
    }
)


def test_the_move_trigger_sells_puts_after_a_stalled_flush() -> None:
    path = {
        M0931: 6935.0,
        M0935: 6920.0,
        M0940: 6900.0,
        M0945: 6905.0,
        M0950: 6902.0,
        M1100: 6910.0,
    }
    quotes = {m: MORNING for m in path}
    quotes[M1100] = {(6790.0, "P"): (1.0, 1.2), (6740.0, "P"): (0.2, 0.3)}
    data = DayData(day=DAY, spot=path, quotes=quotes, oi=OI, prior_close=6935.0)
    (t,) = run_day(data, MOVE_CFG)
    assert (t.side, t.short_strike, t.long_strike, t.entry_time) == ("put", 6790.0, 6740.0, M0950)
    assert (t.trigger, t.gap_day, t.minutes_after_open) == ("move", False, 20)
    assert t.move_em == pytest.approx((6935.0 - 6902.0) / 40.0)
    assert t.exit_reason == "profit_take" and t.hold_minutes == pytest.approx(70.0)


def test_size_is_ten_percent_of_the_capital_it_is_given() -> None:
    roomy = CFG.model_copy(update={"risk": CFG.risk.model_copy(update={"max_contracts": 100})})
    later = {M1100: {(6790.0, "P"): (1.0, 1.2), (6740.0, "P"): (0.2, 0.3)}}
    (big,) = run_day(_day(later), roomy, capital_usd=100_000.0)
    (small,) = run_day(_day(later), roomy, capital_usd=10_000.0)
    # Max loss per SPY-equivalent contract = (50 − 2.95) × 100 / 10 = $470.50.
    assert (big.contracts, small.contracts) == (21, 2)
    assert big.pnl_usd == pytest.approx(21 * ((2.95 - 0.925) * 100 / 10 - 4 * 0.65))


def test_run_backtest_compounds_realized_pnl_into_the_next_days_capital(monkeypatch) -> None:
    import src.spreads.backtest.engine as engine

    seen: list[float | None] = []

    def fake_run_day(data, cfg, capital_usd=None):
        seen.append(capital_usd)
        return [SimpleNamespace(pnl_usd=500.0)]

    monkeypatch.setattr(engine, "run_day", fake_run_day)
    engine.run_backtest(FakeClient(), CFG, date(2026, 10, 9), date(2026, 10, 12))
    assert seen == [100_000.0, 100_500.0]


def test_overrides_change_only_what_is_asked() -> None:
    o = with_overrides(CFG, profit_take_pct=80.0, entry_trigger="move", negative_gamma="allow")
    assert (o.exits.profit_take_pct, o.entry.trigger, o.gex.negative_gamma_action) == (
        80.0,
        "move",
        "allow",
    )
    assert o.exits.stop_debit_multiple == CFG.exits.stop_debit_multiple
    assert with_overrides(CFG) == CFG
