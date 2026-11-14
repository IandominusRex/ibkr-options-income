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
        # The fill mechanics are the haircut's: the cost standard's slippage is pinned at 0 here
        # and exercised by its own test below.
        "execution": _BASE.execution.model_copy(
            update={
                "commission_per_contract": 0.65,
                "shadow_slippage_per_leg": 0.0,
                "slippage_margin_per_leg": 0.0,
            }
        ),
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


def test_the_backtest_sizes_at_half_a_percent_of_the_stated_nlv() -> None:
    roomy = CFG.model_copy(update={"risk": CFG.risk.model_copy(update={"max_contracts": 100})})
    later = {M1100: {(6790.0, "P"): (1.0, 1.2), (6740.0, "P"): (0.2, 0.3)}}
    (big,) = run_day(_day(later), roomy, nlv_usd=2_000_000.0)
    (small,) = run_day(_day(later), roomy, nlv_usd=650_000.0)
    # Max loss per SPY-equivalent contract = (50 − 2.95) × 100 / 10 = $470.50.
    assert (big.contracts, small.contracts) == (21, 6)  # ⌊0.5% × NLV ÷ $470.50⌋
    assert big.pnl_usd == pytest.approx(21 * ((2.95 - 0.925) * 100 / 10 - 4 * 0.65))
    # The book's notional starting capital no longer sizes anything.
    rich = roomy.model_copy(
        update={"risk": roomy.risk.model_copy(update={"starting_capital_usd": 10_000_000.0})}
    )
    (same,) = run_day(_day(later), rich, nlv_usd=650_000.0)
    assert same.contracts == 6


def test_run_backtest_compounds_realized_pnl_into_the_next_days_nlv(monkeypatch) -> None:
    import src.spreads.backtest.engine as engine

    seen: list[float | None] = []

    def fake_run_day(data, cfg, nlv_usd=None):
        seen.append(nlv_usd)
        return [SimpleNamespace(pnl_usd=500.0)]

    monkeypatch.setattr(engine, "run_day", fake_run_day)
    sessions: list[date] = []
    engine.run_backtest(
        FakeClient(),
        CFG,
        date(2026, 10, 9),
        date(2026, 10, 12),
        nlv_usd=650_000.0,
        sessions=sessions,
    )
    assert seen == [650_000.0, 650_500.0]
    assert sessions == [date(2026, 10, 9), date(2026, 10, 12)]


def test_the_backtest_pays_the_cost_standard_when_it_is_wider_than_the_haircut() -> None:
    # $0.025 + $0.025 a leg on SPY = 0.5 SPX point a leg, 1.0 a side (two legs); the 0.5
    # haircut of the 0.30 entry gap is only 0.15.
    wide = CFG.model_copy(
        update={
            "execution": CFG.execution.model_copy(
                update={"shadow_slippage_per_leg": 0.025, "slippage_margin_per_leg": 0.025}
            )
        }
    )
    later = {M1100: {(6790.0, "P"): (1.0, 1.2), (6740.0, "P"): (0.2, 0.3)}}
    (t,) = run_day(_day(later), wide)
    assert t.entry_credit == pytest.approx(3.10 - 1.0)  # mid less the standard, not 2.95
    assert t.exit_debit == pytest.approx(0.85 + 1.0)


def _bt_trade(day: date, pnl: float):
    return SimpleNamespace(
        day=day,
        pnl_usd=pnl,
        regime="positive",
        side="put",
        trigger="move",
        gap_day=False,
        exit_reason="profit_take" if pnl > 0 else "stop_loss",
        hold_minutes=30.0,
        mae_usd=0.0,
    )


def _sessions(n: int) -> list[date]:
    from src.common.market_hours import is_trading_day

    out, d = [], date(2025, 1, 2)
    while len(out) < n:
        if is_trading_day(d):
            out.append(d)
        d = d.fromordinal(d.toordinal() + 1)
    return out


def test_the_report_writes_a_result_file(tmp_path) -> None:
    from scripts.spreads_backtest import write_report
    from src.common.schemas import EnvelopeReportResult
    from src.spreads.report import paper_bar

    days = _sessions(80)
    good = [_bt_trade(d, 120.0 if i % 5 else -150.0) for i, d in enumerate(days)]
    result = paper_bar(good, days, 650_000.0, seed=1)
    assert result.id == "spreads_paper" and result.switch == "spreads_paper"
    assert result.value_on_pass == "on" and result.passed is True
    m = result.metrics
    assert m["sessions"] == 80 and m["trades"] == 80
    assert m["mean_pnl_per_session"] == pytest.approx((64 * 120.0 - 16 * 150.0) / 80)
    assert m["bootstrap_p5_mean"] is not None and m["bootstrap_p5_mean"] > 0
    assert m["worst_day"] == -150.0 and m["worst_20_sessions"] > -0.02 * 650_000.0
    assert m["breakeven_win_rate"] == pytest.approx(150 / 270, abs=1e-3)
    assert "regime" in str(m["tags"])
    path = write_report(result, tmp_path)
    assert path == tmp_path / "spreads_paper.json"
    back = EnvelopeReportResult.model_validate_json(path.read_text())
    assert back.passed is True and back.metrics["sessions"] == 80
    # A book that loses on average fails the bar.
    bad = [_bt_trade(d, -40.0 if i % 2 else 30.0) for i, d in enumerate(days)]
    assert paper_bar(bad, days, 650_000.0, seed=1).passed is False
    # So does one whose worst 20 sessions lose more than 2% of NLV, however good the mean.
    deep = [_bt_trade(d, -1_000.0 if 10 <= i < 30 else 2_000.0) for i, d in enumerate(days)]
    deep_bar = paper_bar(deep, days, 650_000.0, seed=1)
    assert deep_bar.metrics["worst_20_sessions"] == pytest.approx(-20_000.0)
    assert deep_bar.passed is False


def test_too_few_sessions_is_insufficient() -> None:
    from src.spreads.report import paper_bar

    days = _sessions(59)
    result = paper_bar([_bt_trade(d, 100.0) for d in days], days, 650_000.0, seed=1)
    assert result.passed is None and result.metrics["sessions"] == 59
    # A session with no trade counts as a zero day, not as missing.
    quiet = paper_bar([_bt_trade(days[0], 100.0)], _sessions(60), 650_000.0, seed=1)
    assert quiet.metrics["sessions"] == 60
    assert quiet.metrics["mean_pnl_per_session"] == pytest.approx(100.0 / 60)


def test_overrides_change_only_what_is_asked() -> None:
    o = with_overrides(CFG, profit_take_pct=80.0, entry_trigger="move", negative_gamma="allow")
    assert (o.exits.profit_take_pct, o.entry.trigger, o.gex.negative_gamma_action) == (
        80.0,
        "move",
        "allow",
    )
    assert o.exits.stop_debit_multiple == CFG.exits.stop_debit_multiple
    assert with_overrides(CFG) == CFG


# Review minor — data that ends before the time stop closes at the last quote, with commissions,
# instead of a free "expiry" at intrinsic.
def test_data_ending_before_the_time_stop_closes_at_the_last_quote() -> None:
    later = {M1100: {(6790.0, "P"): (2.9, 3.1), (6740.0, "P"): (0.9, 1.1)}}
    (t,) = run_day(_day(later), CFG)
    assert t.exit_reason == "data_end" and t.exit_time == M1100
    assert t.exit_debit == pytest.approx(2.1)  # mid 2.0, half-way to the 2.2 natural
    assert t.pnl_usd == pytest.approx((2.95 - 2.1) * 100 / 10 - 4 * 0.65)


# Review minor — as live, the capital moves with every spread closed earlier the same day.
def test_capital_moves_with_trades_closed_earlier_the_same_day(monkeypatch) -> None:
    import src.spreads.backtest.engine as engine

    seen: list[float] = []
    real = engine.validate

    def spy(c, ctx, cfg):
        seen.append(ctx.capital_usd)
        return real(c, ctx, cfg)

    monkeypatch.setattr(engine, "validate", spy)
    m1105 = datetime(2026, 10, 7, 15, 5, tzinfo=UTC)
    later = {
        M1100: {(6790.0, "P"): (1.0, 1.2), (6740.0, "P"): (0.2, 0.3)},  # profit take
        m1105: MORNING,  # the next entry check
    }
    first, *_ = run_day(_day(later), CFG)
    assert seen[0] == pytest.approx(100_000.0 * 10)
    assert seen[-1] == pytest.approx(100_000.0 * 10 + first.pnl_usd * 10)


# Review minor — one bad day (a 4xx for missing data) is skipped, not the end of the run.
def test_a_day_that_fails_to_load_is_skipped_not_fatal() -> None:
    class Flaky(FakeClient):
        def index_prices(self, symbol, day, interval="1m"):
            if day == date(2026, 10, 12):
                raise RuntimeError("404 no data")
            return super().index_prices(symbol, day, interval)

    skipped: list[tuple[date, str]] = []
    run_backtest(Flaky(), CFG, date(2026, 10, 9), date(2026, 10, 12), skipped)
    assert [d for d, _ in skipped] == [date(2026, 10, 12)]

    class Down(FakeClient):
        def index_prices(self, symbol, day, interval="1m"):
            raise RuntimeError("connection refused")

    with pytest.raises(RuntimeError, match="connection refused"):
        run_backtest(Down(), CFG, date(2026, 10, 9), date(2026, 10, 12))
