from types import SimpleNamespace

import pytest

from src.spreads.report import (
    compute_stats,
    format_extras,
    format_stats,
    group_stats,
    tag_breakdowns,
)


def test_stats_expose_the_win_rate_trap() -> None:
    s = compute_stats([30.0, 30.0, -100.0, 30.0])
    assert (s.n, s.wins, s.losses) == (4, 3, 1)
    assert s.win_rate == pytest.approx(0.75)
    assert s.avg_win == pytest.approx(30.0) and s.avg_loss == pytest.approx(-100.0)
    assert s.expectancy == pytest.approx(-2.5)
    assert s.breakeven_win_rate == pytest.approx(100 / 130)
    assert s.total_pnl == pytest.approx(-10.0)
    assert s.max_drawdown == pytest.approx(100.0)


def test_empty_and_all_wins() -> None:
    e = compute_stats([])
    assert e.n == 0 and e.win_rate is None and e.expectancy is None and e.max_drawdown == 0.0
    w = compute_stats([10.0, 5.0])
    assert w.breakeven_win_rate is None and w.max_drawdown == 0.0


def test_group_and_format() -> None:
    g = group_stats([("positive", 20.0), ("negative", -50.0), ("positive", 10.0)])
    assert g["positive"].n == 2 and g["negative"].total_pnl == -50.0
    text = format_stats("shadow", compute_stats([30.0, -100.0]))
    assert "win rate 50.0%" in text and "break-even" in text and "expectancy" in text


def _t(**kw) -> SimpleNamespace:
    base = dict(
        side="put",
        regime="positive",
        trigger="move",
        gap_day=False,
        exit_reason="profit_take",
        pnl_usd=20.0,
        hold_minutes=40.0,
        mae_usd=5.0,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_tag_breakdowns_split_negative_gamma_gap_days_and_sides() -> None:
    trades = [
        _t(),
        _t(regime="negative", pnl_usd=-60.0, exit_reason="stop_loss", mae_usd=80.0),
        _t(regime="negative", gap_day=True, side="call"),
    ]
    b = tag_breakdowns(trades)
    assert set(b) == {"regime", "side", "trigger", "gap", "exit"}
    assert b["regime"]["negative"].n == 2 and b["regime"]["negative"].total_pnl == pytest.approx(
        -40.0
    )
    assert b["gap"]["gap day"].n == 1 and b["gap"]["normal open"].n == 2
    assert b["side"]["call"].n == 1 and b["exit"]["stop_loss"].losses == 1
    extras = format_extras(trades)
    assert "avg hold 40 min" in extras and "worst MAE $80.00" in extras
    assert "avg hold n/a" in format_extras([_t(hold_minutes=None, mae_usd=None)])
