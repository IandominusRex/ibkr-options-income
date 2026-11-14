"""Shadow/paper/backtest performance — the numbers that decide whether this strategy lives.

A high win rate is not an edge. ``breakeven_win_rate`` (|avg loss| / (avg win + |avg loss|))
is printed beside the actual win rate so the gap — or its absence — is the first thing read.
``tag_breakdowns`` splits the same numbers by the entry tags every trade carries (gamma regime,
side, trigger, gap day, exit reason), for live trade logs and backtests alike.
"""

from __future__ import annotations

import random
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from statistics import mean
from typing import Protocol

from src.common.schemas import (
    EnvelopeReportResult,
    SpreadMenuItem,
    SpreadPickRecord,
    SpreadTradeRecord,
)


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


# --- The spreads paper bar (risk-envelope Task 7, ruling P8): the backtest decides paper.

PAPER_BAR_CRITERION = (
    "P8: the 5th percentile of 10,000 session-clustered bootstrap means of per-session P&L "
    "after measured costs > 0, and the worst 20-session loss <= 2% of the stated NLV "
    "(fewer than 60 sessions: insufficient data)"
)
PAPER_BAR_MIN_SESSIONS = 60


class _DatedTrade(TaggedTrade, Protocol):
    @property
    def day(self) -> date: ...


def paper_bar(
    trades: Sequence[_DatedTrade],
    sessions: Sequence[date],
    nlv_usd: float,
    *,
    draws: int = 10_000,
    seed: int = 0,
    now: datetime | None = None,
) -> EnvelopeReportResult:
    """The P8 verdict on a backtest, as the result file ``scripts.envelope`` applies: a PASS sets
    switch ``spreads_paper`` on (paper only). *sessions* are every day the backtest replayed,
    traded or not (a session with no trade is a zero day, never a missing one). Deterministic
    for a given *seed*."""
    days = sorted(set(sessions))
    by_day: dict[date, float] = dict.fromkeys(days, 0.0)
    for t in trades:
        by_day[t.day] = by_day.get(t.day, 0.0) + t.pnl_usd
    series = [by_day[d] for d in sorted(by_day)]
    n = len(series)
    stats = compute_stats([t.pnl_usd for t in trades])
    p5: float | None = None
    if n:
        rng = random.Random(seed)
        means = sorted(sum(rng.choices(series, k=n)) / n for _ in range(draws))
        p5 = means[int(0.05 * (draws - 1))]
    window = min(20, n)
    worst_20 = min((sum(series[i : i + window]) for i in range(n - window + 1)), default=None)
    limit = -0.02 * nlv_usd
    passed: bool | None
    if n < PAPER_BAR_MIN_SESSIONS:
        passed = None
    else:
        passed = p5 is not None and p5 > 0 and worst_20 is not None and worst_20 >= limit
    tags = "; ".join(
        f"{name}: "
        + ", ".join(f"{v}={s.n} trades exp {_usd(s.expectancy)}" for v, s in groups.items())
        for name, groups in tag_breakdowns(trades).items()
    )
    metrics: dict[str, float | str | None] = {
        "sessions": n,
        "trades": len(trades),
        "nlv_usd": nlv_usd,
        "mean_pnl_per_session": sum(series) / n if n else None,
        "bootstrap_p5_mean": p5,
        "bootstrap_draws": draws,
        "win_rate": stats.win_rate,
        "breakeven_win_rate": stats.breakeven_win_rate,
        "worst_day": min(series) if series else None,
        "worst_20_sessions": worst_20,
        "worst_20_limit": limit,
        "first_session": days[0].isoformat() if days else None,
        "last_session": days[-1].isoformat() if days else None,
        "tags": tags,
    }
    return EnvelopeReportResult(
        id="spreads_paper",
        passed=passed,
        criterion=PAPER_BAR_CRITERION,
        metrics=metrics,
        switch="spreads_paper",
        value_on_pass="on",
        written_at=now or datetime.now(UTC),
    )


# --- Claude's book against the baseline (docs/superpowers/specs/2026-10-12-spreads-claude-picker-design.md §9)

NOISE_N = 5
SAMPLE_NOTE_N = 50
NON_JUDGMENT_KINDS = ("not_sent", "fallback")


@dataclass(frozen=True)
class Decision:
    pick: SpreadPickRecord
    kind: str  # took_inside | took_baseline | took_outer | skipped | fallback | not_sent
    main_pnl: float | None  # None = the main book traded nothing on this decision
    base_pnl: float | None  # None = the baseline traded nothing in this episode
    settled: bool  # every trade either book opened on it is closed

    @property
    def diff(self) -> float:
        return (self.main_pnl or 0.0) - (self.base_pnl or 0.0)


def decision_kind(p: SpreadPickRecord) -> str:
    if p.fallback_reason:
        return "fallback"
    if p.choice == "skip":
        return "skipped"
    item = next((i for i in p.menu if i.letter == p.executed_letter), None)
    return "not_sent" if item is None else f"took_{item.position}"


def scope_compare(
    picks: Sequence[SpreadPickRecord],
    main_log: Sequence[SpreadTradeRecord],
    base_log: Sequence[SpreadTradeRecord],
    main_mode: str,
) -> tuple[
    list[SpreadPickRecord], list[SpreadTradeRecord], list[SpreadTradeRecord], datetime | None
]:
    """Restrict a comparison to the main mode and to the AI era.

    Picks are filtered to ``book_mode == main_mode``; Claude's trades to pick trades (a
    ``pick_id``) opened at or after the first such pick, so main-book trades from a stretch with
    ``ai.enabled: false`` are never counted as Claude's. The baseline trade of an episode opens in ``_decide``, 15-75 s *before*
    its pick row is written, so the baseline is cut at the earliest baseline trade belonging to a
    scoped pick's episode instead (pre-AI trades, and a baseline from another era, stay out).
    Returns the first pick's time too (``None`` when there are no picks, in which case there is
    nothing to compare).
    """
    mine = sorted((p for p in picks if p.book_mode == main_mode), key=lambda p: p.created_at)
    if not mine:
        return [], [], [], None
    since = mine[0].created_at
    episodes = {p.episode_key for p in mine}
    base_since = min((t.opened_at for t in base_log if t.episode_key in episodes), default=since)
    return (
        mine,
        [t for t in main_log if t.opened_at >= since and t.pick_id is not None],
        [t for t in base_log if t.opened_at >= min(since, base_since)],
        since,
    )


def _label(d: Decision) -> str:
    """The choice-distribution key: ``took_outer`` is split by its order among the outer items."""
    if d.kind != "took_outer":
        return d.kind
    outers = [i.letter for i in d.pick.menu if i.position == "outer"]
    if len(outers) < 2 or d.pick.executed_letter not in outers:
        return d.kind
    return f"{d.kind}_{outers.index(d.pick.executed_letter) + 1}"


def build_decisions(
    picks: Sequence[SpreadPickRecord],
    main_log: Sequence[SpreadTradeRecord],
    base_log: Sequence[SpreadTradeRecord],
) -> list[Decision]:
    main_by_pick = {t.pick_id: t for t in main_log if t.pick_id is not None}
    base_by_episode = {t.episode_key: t for t in base_log if t.episode_key is not None}
    out: list[Decision] = []
    for p in picks:
        m, b = main_by_pick.get(p.pick_id), base_by_episode.get(p.episode_key)
        settled = all(t is None or t.status == "closed" for t in (m, b))
        kind = decision_kind(p)
        if kind.startswith("took_") and m is None:
            # Recorded but never opened (stale, refused by the re-gate, no fresh quote, not
            # filled...): joined on the main-book trade, so a crash between the fill and
            # ``mark_pick_sent`` still reads correctly.
            kind = "not_sent"
        out.append(
            Decision(
                p,
                kind,
                m.pnl_usd if m is not None else None,
                b.pnl_usd if b is not None else None,
                settled,
            )
        )
    return out


def _band(v: float | None, edges: tuple[float, ...], labels: tuple[str, ...]) -> str:
    if v is None:
        return "n/a"
    for edge, label in zip(edges, labels, strict=False):
        if v < edge:
            return label
    return labels[-1]


def _trend(p: SpreadPickRecord) -> str:
    a, b = p.market.spy_vs_sma20_pct, p.market.spy_vs_sma50_pct
    if a is None or b is None:
        return "n/a"
    return "up" if a > 0 and b > 0 else "down" if a < 0 and b < 0 else "mixed"


CONDITIONS: dict[str, Callable[[SpreadPickRecord], str]] = {
    "regime": lambda p: p.snapshot.regime,
    "move": lambda p: _band(
        p.snapshot.move_em,
        (0.75, 1.0, 1.25),
        ("<0.75×EM", "0.75–1×EM", "1–1.25×EM", "≥1.25×EM"),
    ),
    "gap": lambda p: "gap day" if p.snapshot.gap_day else "normal open",
    "vix": lambda p: _band(p.market.vix, (15.0, 20.0, 30.0), ("<15", "15–20", "20–30", "≥30")),
    "trend": _trend,
    "event": lambda p: "event" if p.snapshot.event_flag else "normal",
    "side": lambda p: p.snapshot.side or "n/a",
    "plan": lambda p: p.snapshot.plan_bias or "no plan",
    # the model that answered: since the fallback, a decision may be Opus or the Sonnet retry
    "model": lambda p: f"{p.model}/{p.effort}",
}


@dataclass(frozen=True)
class CompareRow:
    n: int
    main_total: float
    base_total: float
    diff_mean: float
    noise: bool


def _compare_row(ds: Sequence[Decision]) -> CompareRow:
    return CompareRow(
        n=len(ds),
        main_total=sum(d.main_pnl or 0.0 for d in ds),
        base_total=sum(d.base_pnl or 0.0 for d in ds),
        diff_mean=mean(d.diff for d in ds),
        noise=len(ds) < NOISE_N,
    )


def compare_by(decisions: Sequence[Decision], key: str) -> dict[str, CompareRow]:
    """Main − baseline P&L per value of condition *key*, settled real decisions only.

    ``not_sent`` (Claude chose, nothing was opened) and ``fallback`` (the picker failed; credited
    to neither side) are not Claude's judgment, so they stay out of the by-condition tables.
    """
    by: dict[str, list[Decision]] = defaultdict(list)
    for d in decisions:
        if d.settled and d.kind not in NON_JUDGMENT_KINDS:
            by[CONDITIONS[key](d.pick)].append(d)
    return {k: _compare_row(ds) for k, ds in sorted(by.items())}


def _kind_rows(decisions: Sequence[Decision]) -> dict[str, CompareRow]:
    by: dict[str, list[Decision]] = defaultdict(list)
    for d in decisions:
        if d.settled:
            by[d.kind].append(d)
    return {k: _compare_row(ds) for k, ds in sorted(by.items())}


def _row_text(label: str, r: CompareRow) -> str:
    tag = "  (noise: n < 5)" if r.noise else ""
    return (
        f"  {label}: n={r.n} · Claude {_usd(r.main_total)} · baseline {_usd(r.base_total)} · "
        f"mean difference {_usd(r.diff_mean)}{tag}"
    )


def format_compare(
    decisions: Sequence[Decision],
    main_log: Sequence[SpreadTradeRecord],
    base_log: Sequence[SpreadTradeRecord],
    main_mode: str,
    slippage_per_leg: float,
) -> list[str]:
    def closed(log: Sequence[SpreadTradeRecord]) -> list[float]:
        return [t.pnl_usd for t in log if t.status == "closed"]

    lines = [
        format_stats(f"Claude ({main_mode}, closed)", compute_stats(closed(main_log))),
        format_stats("baseline (simulated, closed)", compute_stats(closed(base_log))),
        f"decisions: {len(decisions)} ({sum(d.settled for d in decisions)} settled)",
    ]
    if len(decisions) < SAMPLE_NOTE_N:
        lines.append(
            f"  note: fewer than {SAMPLE_NOTE_N} decisions — at 1–2 a day the comparison means "
            "little before ~2–3 months"
        )
    lines.append("by decision:")
    lines += [_row_text(k, r) for k, r in _kind_rows(decisions).items()]
    counts: dict[str, int] = defaultdict(int)
    for d in decisions:
        counts[_label(d)] += 1
    lines.append(
        "choice distribution: " + " · ".join(f"{k} {v}" for k, v in sorted(counts.items()))
    )
    for key in CONDITIONS:
        rows = compare_by(decisions, key)
        if rows:
            lines.append(f"by {key}:")
            lines += [_row_text(k, r) for k, r in rows.items()]
    gaps: list[float] = []
    by_pick = {t.pick_id: t for t in main_log if t.pick_id is not None}
    for d in decisions:
        t = by_pick.get(d.pick.pick_id)
        item = next((i for i in d.pick.menu if i.letter == d.pick.executed_letter), None)
        if t is not None and item is not None:
            gaps.append(t.entry_credit - (item.candidate.credit_mid - 2 * slippage_per_leg))
    lines.append(
        "fill bias: "
        + (
            "n/a"
            if not gaps
            else f"real entry credit − modelled fill averages {mean(gaps):+.3f}/share over {len(gaps)} entries"
        )
    )
    return lines


def _menu_text(menu: Sequence[SpreadMenuItem]) -> str:
    return "; ".join(
        f"{i.letter} {i.position} {i.candidate.short_strike:g}/{i.candidate.long_strike:g} "
        f"{i.candidate.credit_mid:.2f}"
        for i in menu
    )


def decision_rows(decisions: Sequence[Decision]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for d in decisions:
        p = d.pick
        rows.append(
            {
                "pick_id": p.pick_id,
                "day": p.day.isoformat(),
                "created_at": p.created_at.isoformat(),
                "episode_key": p.episode_key,
                "kind": d.kind,
                "choice": p.choice,
                "executed_letter": p.executed_letter,
                "fallback_reason": p.fallback_reason,
                "reason": p.reason,
                "model": p.model,
                "effort": p.effort,
                "latency_ms": p.latency_ms,
                "cost_usd": p.cost_usd,
                "main_pnl_usd": d.main_pnl,
                "base_pnl_usd": d.base_pnl,
                "diff_usd": d.diff,
                "settled": d.settled,
                **p.snapshot.model_dump(),
                **p.market.model_dump(exclude={"headlines", "econ_today", "unavailable"}),
                "menu": _menu_text(p.menu),
            }
        )
    return rows


def format_day(
    day: date,
    plan_text: str,
    picks: Sequence[SpreadPickRecord],
    main_log: Sequence[SpreadTradeRecord],
    base_log: Sequence[SpreadTradeRecord],
) -> list[str]:
    lines = [f"=== {day} ===", plan_text]
    for d in build_decisions(picks, main_log, base_log):
        p = d.pick
        lines += [
            f"--- pick {p.pick_id} · {p.created_at:%H:%M} UTC · {d.kind} · choice {p.choice} "
            f"(sent {p.executed_letter or '-'}) · fallback {p.fallback_reason or '-'}",
            f"conditions: {p.snapshot.model_dump()}",
            f"market: {p.market.model_dump(exclude={'headlines', 'econ_today'})}",
            f"outcome: Claude {_usd(d.main_pnl)} · baseline {_usd(d.base_pnl)} · difference {_usd(d.diff)}",
            f"menu: {_menu_text(p.menu)}",
            "prompt:",
            p.prompt_text,
            "reply:",
            p.raw_response or "(none)",
        ]
    return lines
