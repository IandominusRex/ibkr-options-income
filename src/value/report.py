"""The shadow record's report (spec §6.8, §7, §11, §12). Pure: no I/O.

``scripts/value_report.py`` reads value.db and hands plain views in. Returns are measured at
fixed horizons on every entry, marked to market, with standard errors clustered by entry date
(spec §12); the three exit policies side by side on the same READY entries (spec §7); the
ranked monthly record (spec §6.8); a postmortem per closed position (spec §11); and (Part 3) the
re-evaluations of §7.1 with the re-evaluated plan beside the original one. The report proves
nothing on its own: it is what a human reads before any go-live decision.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from statistics import mean

from pydantic import BaseModel, Field

from src.value.schemas import Check, ValueScorecard

HORIZONS = (21, 63, 126)  # sessions after the entry session (spec §6.8, §12)
SURVIVORSHIP = (
    "Prices carry yfinance's survivorship bias: delisted names are absent, so every return "
    "here flatters the rules (spec §6.2)."
)
GO_LIVE_ENTRIES = 30  # spec §12: the live track needs at least 30 entries
GO_LIVE_HORIZON = 63


class EntryView(BaseModel):
    id: int
    track: str
    kind: str
    list_name: str
    symbol: str
    universe: str
    status: str
    signal_date: date
    entry_date: date | None = None
    entry_price: float | None = None
    fair_value: float | None = None
    margin_of_safety: float | None = None
    ruleset_version: str
    returns: dict[int, float | None] = Field(default_factory=dict)
    spy: dict[int, float | None] = Field(default_factory=dict)
    scorecard_json: str = ""


class LegView(BaseModel):
    shadow_id: int
    policy: str
    plan: str = "main"  # main | original (the twin carried untouched from the first trigger)
    closed: bool
    exit_date: date | None = None
    ret: float | None = None
    spy_ret: float | None = None
    max_drawdown: float | None = None
    sessions: int = 0
    sells: int = 0


class EventView(BaseModel):
    shadow_id: int
    policy: str
    plan: str = "main"
    day: date
    kind: str
    price: float | None = None
    fraction: float = 0.0
    detail: str = ""


class ReevaluationView(BaseModel):
    shadow_id: int
    list_name: str
    severity: str
    kinds: list[str] = Field(default_factory=list)


class RankedView(BaseModel):
    formed_on: date
    list_name: str
    bucket: str
    n: int
    closed_on: date | None = None
    ret: float | None = None
    spy_ret: float | None = None
    missing: int = 0


@dataclass(frozen=True, slots=True)
class Stat:
    n: int
    clusters: int
    mean: float | None
    se: float | None  # clustered by entry date; None below two clusters

    @property
    def t(self) -> float | None:
        if self.mean is None or not self.se:
            return None
        return self.mean / self.se


def clustered_mean(points: list[tuple[date, float]]) -> Stat:
    """The mean of *points* and its standard error clustered by date: entries made on one day
    share that day's market, so they are not independent (spec §12). With G clusters,
    SE^2 = G / (G - 1) x sum over clusters of (sum of residuals)^2 / n^2."""
    n = len(points)
    if n == 0:
        return Stat(0, 0, None, None)
    m = sum(x for _, x in points) / n
    sums: dict[date, float] = defaultdict(float)
    for d, x in points:
        sums[d] += x - m
    g = len(sums)
    if g < 2:
        return Stat(n, g, m, None)
    var = g / (g - 1) * sum(s * s for s in sums.values()) / (n * n)
    return Stat(n, g, m, math.sqrt(var))


def _pct(v: float | None) -> str:
    return "n/a" if v is None else f"{v * 100:+.1f}%"


def _stat_line(label: str, rets: list[float], spys: list[float], s: Stat) -> str:
    t = "n/a" if s.t is None else f"{s.t:.2f}"
    se = "n/a" if s.se is None else f"{s.se * 100:.1f}%"
    return (
        f"  {label:<12} n {s.n:>4} ({s.clusters} dates)  return {_pct(mean(rets))}  "
        f"SPY {_pct(mean(spys))}  excess {_pct(s.mean)} ± {se}  t {t}"
    )


def horizon_section(entries: list[EntryView]) -> list[str]:
    """Every entry, READY and control alike, at 21/63/126 sessions against SPY."""
    lines = ["-- Fixed horizons (marked to market; errors clustered by entry date) --"]
    groups: dict[tuple[str, str, str], list[EntryView]] = defaultdict(list)
    for e in entries:
        groups[(e.track, e.list_name, e.kind)].append(e)
    if not groups:
        return [*lines, "  no entries yet"]
    for (track, list_name, kind), group in sorted(groups.items()):
        lines.append(f"[{track} · {list_name} · {kind}] {len(group)} entries")
        for h in HORIZONS:
            marked = [
                e
                for e in group
                if e.returns.get(h) is not None and e.spy.get(h) is not None and e.entry_date
            ]
            if not marked:
                lines.append(f"  {h:>3} sessions: none marked yet")
                continue
            rets = [e.returns[h] or 0.0 for e in marked]
            spys = [e.spy[h] or 0.0 for e in marked]
            excess = [
                (e.entry_date, (e.returns[h] or 0.0) - (e.spy[h] or 0.0))
                for e in marked
                if e.entry_date is not None
            ]
            lines.append(_stat_line(f"{h} sessions", rets, spys, clustered_mean(excess)))
    return lines


def go_live_line(entries: list[EntryView], track: str) -> str:
    """Spec §12's first go-live line for the track that would run live (the value policy reads
    the same entries; fixed horizons do not depend on the exit policy)."""
    marked: list[tuple[date, float]] = []
    for e in entries:
        ret, spy = e.returns.get(GO_LIVE_HORIZON), e.spy.get(GO_LIVE_HORIZON)
        if (
            e.track == track
            and e.kind == "ready"
            and e.entry_date
            and ret is not None
            and spy is not None
        ):
            marked.append((e.entry_date, ret - spy))
    s = clustered_mean(marked)
    verdict = (
        "not enough entries yet"
        if s.n < GO_LIVE_ENTRIES
        else ("above zero" if (s.mean or 0.0) > 0 else "at or below zero: do not go live")
    )
    return (
        f"Go-live check ({track}, READY, {GO_LIVE_HORIZON}-session excess over SPY): "
        f"n {s.n} of {GO_LIVE_ENTRIES} needed, mean {_pct(s.mean)}: {verdict} (spec §12)"
    )


def policy_section(entries: list[EntryView], legs: list[LegView], live_policy: str) -> list[str]:
    """The three exit policies side by side on the same READY entries (spec §7)."""
    lines = ["-- Exit policies on the same READY entries (closed legs) --"]
    by_id = {e.id: e for e in entries if e.kind == "ready"}
    groups: dict[tuple[str, str], list[LegView]] = defaultdict(list)
    for leg in legs:
        e = by_id.get(leg.shadow_id)
        if e is not None and leg.plan == "main":
            groups[(e.list_name, leg.policy)].append(leg)
    if not groups:
        return [*lines, "  no READY entries yet"]
    for (list_name, policy), group in sorted(groups.items()):
        done = [g for g in group if g.closed and g.ret is not None]
        tag = " (live)" if policy == live_policy else " (diagnostic)"
        if not done:
            lines.append(f"  {list_name:<15} {policy + tag:<20} {len(group)} held, none closed")
            continue
        vs = [g.ret - g.spy_ret for g in done if g.ret is not None and g.spy_ret is not None]
        dd = [g.max_drawdown for g in done if g.max_drawdown is not None]
        lines.append(
            f"  {list_name:<15} {policy + tag:<20} closed {len(done)}/{len(group)}  "
            f"return {_pct(mean(g.ret for g in done if g.ret is not None))}  "
            f"vs SPY {_pct(mean(vs) if vs else None)}  max DD {_pct(mean(dd) if dd else None)}  "
            f"held {mean(g.sessions for g in done):.0f} sessions  "
            f"sells/entry {mean(g.sells for g in done):.1f}"
        )
    return lines


def reevaluation_section(
    legs: list[LegView], reevaluations: list[ReevaluationView], rebases: int
) -> list[str]:
    """Spec §7.1, "measured like everything else": how often each trigger fired, and per policy
    the re-evaluated plan against the original one on the entries that have both, closed."""
    lines = ["-- Re-evaluations (spec §7.1; the original plan carried beside the re-evaluated) --"]
    if not reevaluations:
        return [*lines, f"  none yet; {rebases} rebase(s) of a split or a dividend adjustment"]
    kinds: dict[str, int] = defaultdict(int)
    for r in reevaluations:
        for k in r.kinds:
            kinds[k] += 1
    major = sum(1 for r in reevaluations if r.severity == "major")
    lines.append(
        f"  {len(reevaluations)} re-evaluation(s), {major} major; triggers "
        + ", ".join(f"{k} {n}" for k, n in sorted(kinds.items()))
        + f"; {rebases} rebase(s)"
    )
    pairs: dict[str, list[tuple[float, float]]] = defaultdict(list)
    main = {(g.shadow_id, g.policy): g for g in legs if g.plan == "main"}
    for twin in (g for g in legs if g.plan == "original"):
        m = main.get((twin.shadow_id, twin.policy))
        if m is not None and m.ret is not None and twin.ret is not None:
            pairs[twin.policy].append((m.ret, twin.ret))
    for policy in sorted({g.policy for g in legs if g.plan == "original"}):
        done = pairs.get(policy, [])
        if not done:
            lines.append(f"  {policy:<8} no entry with both plans closed yet")
            continue
        saved = mean(a - b for a, b in done)
        lines.append(
            f"  {policy:<8} {len(done)} closed pair(s): re-evaluated {_pct(mean(a for a, _ in done))}"
            f" vs original {_pct(mean(b for _, b in done))}: re-evaluation "
            f"{'saved' if saved > 0 else 'cost'} {_pct(abs(saved))} an entry"
        )
    return lines


def ranked_section(rows: list[RankedView]) -> list[str]:
    """Top tenth, bottom tenth and the whole scored universe per list, month by month (spec
    §6.8): the decile test of whether the method picks better companies."""
    lines = ["-- Ranked monthly record (equal weight, held to the next formation) --"]
    closed = [r for r in rows if r.closed_on is not None and r.ret is not None]
    if not closed:
        open_n = len({r.formed_on for r in rows})
        return [*lines, f"  no month closed yet ({open_n} formation(s) open)"]
    by: dict[tuple[str, str], list[RankedView]] = defaultdict(list)
    for r in closed:
        by[(r.list_name, r.bucket)].append(r)
    for list_name in sorted({k[0] for k in by}):
        for bucket in ("top", "bottom", "all"):
            group = by.get((list_name, bucket), [])
            if not group:
                continue
            rets = [r.ret for r in group if r.ret is not None]
            spys = [r.spy_ret for r in group if r.spy_ret is not None]
            missing = sum(r.missing for r in group)
            lines.append(
                f"  {list_name:<15} {bucket:<7} months {len(group):>3}  "
                f"mean {_pct(mean(rets))}/month  SPY {_pct(mean(spys) if spys else None)}/month"
                f"  members dropped {missing}"
            )
        tops = {r.formed_on: r.ret for r in by.get((list_name, "top"), [])}
        bottoms = {r.formed_on: r.ret for r in by.get((list_name, "bottom"), [])}
        spread = [
            (d, (tops[d] or 0.0) - (bottoms[d] or 0.0)) for d in sorted(set(tops) & set(bottoms))
        ]
        s = clustered_mean(spread)
        lines.append(f"  {list_name:<15} top - bottom: mean {_pct(s.mean)}/month over {s.n}")
    return lines


def closest_gate(card: ValueScorecard, list_name: str) -> Check | None:
    """The passing check with the least room to its bar at entry (spec §11: "which gate was
    closest to wrong"): relative distance |actual - bar| / |bar|, absolute when the bar is 0."""
    ev = card.lists.get(list_name)
    checks = [
        *card.health_checks,
        *(ev.entry_checks if ev else []),
        *(ev.timing_checks if ev else []),
    ]
    best: tuple[float, Check] | None = None
    for c in checks:
        if c.state != "pass" or c.actual is None or c.threshold is None:
            continue
        gap = abs(c.actual - c.threshold)
        room = gap / abs(c.threshold) if c.threshold else gap
        if best is None or room < best[0]:
            best = (room, c)
    return best[1] if best else None


def postmortem(
    entry: EntryView,
    legs: list[LegView],
    events: list[EventView],
    fair_value_now: float | None,
) -> list[str]:
    """One closed position, for a human (spec §11)."""
    lines = [
        f"## {entry.symbol} {entry.list_name} #{entry.id} ({entry.track}, {entry.universe}, "
        f"{entry.ruleset_version}) signal {entry.signal_date}, entered {entry.entry_date} at "
        f"{entry.entry_price}",
        f"   fair value then {entry.fair_value} (margin of safety {_pct(entry.margin_of_safety)}),"
        f" now {fair_value_now}",
    ]
    for leg in sorted(legs, key=lambda g: g.policy):
        mine = [e for e in events if e.policy == leg.policy and e.plan == leg.plan]
        story = "; ".join(
            f"{e.day} {e.kind}"
            + (f" {e.fraction:.0%} @ {e.price:.2f}" if e.kind == "fill" and e.price else "")
            for e in mine
        )
        lines.append(
            f"   {leg.policy}: exit {leg.exit_date} return {_pct(leg.ret)} (SPY {_pct(leg.spy_ret)})"
            f", max DD {_pct(leg.max_drawdown)}: {story or 'no events'}"
        )
    for e in events:
        if e.kind == "rebase":  # recorded under policy ``all``: every leg's levels moved
            lines.append(f"   rebased {e.day}: {e.detail or 'every price level'}")
    marks = " · ".join(
        f"{h}: {_pct(entry.returns.get(h))} (SPY {_pct(entry.spy.get(h))})" for h in HORIZONS
    )
    lines.append(f"   horizons {marks}")
    if entry.scorecard_json:
        card = ValueScorecard.model_validate_json(entry.scorecard_json)
        c = closest_gate(card, entry.list_name)
        lines.append(
            "   closest to wrong: none measurable"
            if c is None
            else f"   closest to wrong: {c.id} {c.actual:.2f} vs bar {c.threshold:.2f}"
        )
    return lines


def render(
    entries: list[EntryView],
    legs: list[LegView],
    events: list[EventView],
    ranked: list[RankedView],
    *,
    fair_values_now: dict[tuple[str, str], float | None],
    live_policy: str,
    track: str,
    postmortems: bool,
    reevaluations: list[ReevaluationView] | None = None,
    rebases: int = 0,
) -> str:
    versions = sorted({e.ruleset_version for e in entries})
    lines = [
        f"== Value book shadow record: {len(entries)} entries, ruleset(s) {', '.join(versions) or 'n/a'} ==",
        SURVIVORSHIP,
        go_live_line(entries, track),
        "",
        *horizon_section(entries),
        "",
        *policy_section(entries, legs, live_policy),
        "",
        *reevaluation_section(legs, reevaluations or [], rebases),
        "",
        *ranked_section(ranked),
    ]
    if postmortems:
        lines += ["", "-- Postmortems (closed positions) --"]
        closed = [e for e in entries if e.kind == "ready" and e.status == "closed"]
        for e in closed:
            lines += postmortem(
                e,
                [g for g in legs if g.shadow_id == e.id and g.plan == "main"],
                [v for v in events if v.shadow_id == e.id],
                fair_values_now.get((e.symbol, e.list_name)),
            )
        if not closed:
            lines.append("  none closed yet")
    return "\n".join(lines)
