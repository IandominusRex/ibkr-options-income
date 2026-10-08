"""Shadow/paper/backtest performance — the numbers that decide whether this strategy lives.

A high win rate is not an edge. ``breakeven_win_rate`` (|avg loss| / (avg win + |avg loss|))
is printed beside the actual win rate so the gap — or its absence — is the first thing read.
``tag_breakdowns`` splits the same numbers by the entry tags every trade carries (gamma regime,
side, trigger, gap day, exit reason), for live trade logs and backtests alike.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from statistics import mean
from typing import Protocol


@dataclass(frozen=True)
class SpreadStats:
    n: int
    wins: int
    losses: int
    win_rate: float | None
    avg_win: float | None
    avg_loss: float | None
    expectancy: float | None
    breakeven_win_rate: float | None
    total_pnl: float
    max_drawdown: float


def compute_stats(pnls: list[float]) -> SpreadStats:
    n = len(pnls)
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    avg_win = mean(wins) if wins else None
    avg_loss = mean(losses) if losses else None
    breakeven = None
    if avg_win is not None and avg_loss is not None and avg_win + abs(avg_loss) > 0:
        breakeven = abs(avg_loss) / (avg_win + abs(avg_loss))
    equity = peak = drawdown = 0.0
    for p in pnls:
        equity += p
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return SpreadStats(
        n=n,
        wins=len(wins),
        losses=len(losses),
        win_rate=len(wins) / n if n else None,
        avg_win=avg_win,
        avg_loss=avg_loss,
        expectancy=sum(pnls) / n if n else None,
        breakeven_win_rate=breakeven,
        total_pnl=float(sum(pnls)),
        max_drawdown=drawdown,
    )


def group_stats(rows: list[tuple[str, float]]) -> dict[str, SpreadStats]:
    by: dict[str, list[float]] = defaultdict(list)
    for key, pnl in rows:
        by[key].append(pnl)
    return {k: compute_stats(v) for k, v in sorted(by.items())}


def _pct(v: float | None) -> str:
    return "n/a" if v is None else f"{v * 100:.1f}%"


def _usd(v: float | None) -> str:
    return "n/a" if v is None else f"${v:,.2f}"


def format_stats(title: str, s: SpreadStats) -> str:
    return (
        f"{title}: {s.n} trades · win rate {_pct(s.win_rate)} (break-even {_pct(s.breakeven_win_rate)})"
        f" · avg win {_usd(s.avg_win)} · avg loss {_usd(s.avg_loss)} · expectancy {_usd(s.expectancy)}"
        f" · total {_usd(s.total_pnl)} · max drawdown {_usd(s.max_drawdown)}"
    )


class TaggedTrade(Protocol):
    """What a breakdown needs from a trade: ``SpreadTradeRecord`` and ``BacktestTrade`` both fit."""

    @property
    def side(self) -> str: ...
    @property
    def regime(self) -> str: ...
    @property
    def trigger(self) -> str: ...
    @property
    def gap_day(self) -> bool: ...
    @property
    def exit_reason(self) -> str | None: ...
    @property
    def pnl_usd(self) -> float: ...
    @property
    def hold_minutes(self) -> float | None: ...
    @property
    def mae_usd(self) -> float | None: ...


_TAGS: dict[str, Callable[[TaggedTrade], str]] = {
    "regime": lambda t: t.regime,
    "side": lambda t: t.side,
    "trigger": lambda t: t.trigger,
    "gap": lambda t: "gap day" if t.gap_day else "normal open",
    "exit": lambda t: t.exit_reason or "open",
}


def tag_breakdowns(trades: Sequence[TaggedTrade]) -> dict[str, dict[str, SpreadStats]]:
    """Stats per tag value: negative vs positive gamma, puts vs calls, gap days, exit reasons."""
    return {name: group_stats([(key(t), t.pnl_usd) for t in trades]) for name, key in _TAGS.items()}


def format_extras(trades: Sequence[TaggedTrade]) -> str:
    holds = [t.hold_minutes for t in trades if t.hold_minutes is not None]
    maes = [t.mae_usd for t in trades if t.mae_usd is not None]
    hold = f"{mean(holds):.0f} min" if holds else "n/a"
    return (
        f"avg hold {hold} · avg MAE {_usd(mean(maes) if maes else None)}"
        f" · worst MAE {_usd(max(maes) if maes else None)}"
    )
