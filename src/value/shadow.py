"""The shadow record (spec §6.8, §7, §12): hypothetical entries, the exit engine's three policies,
fixed-horizon returns against SPY, and the ranked monthly record. Writes value.db only; reads
research.db through the neutral read-only loader.

Part 2 runs Python's **baseline** track alone; Part 4 adds Claude's track beside it. Nothing here
can place, size or gate an order: every row is hypothetical.

The rules this module applies (the plan's rulings say why):
- a READY signal on the night of session D enters at the open of the next session after D;
- control groups enter on the nights a list gets a new READY entry: every name on that list that
  is healthy but too dear (WAIT), and every name cheap enough whose health failed;
- a key (kind, list, symbol) re-enters only once its previous entry stops blocking: a READY
  entry blocks while its live-policy leg holds, a control entry until its horizons are marked;
- horizon h is marked at the close of the h-th session after the entry session (SPY's sessions),
  from the bars as they stand that night, so a split adjusts both ends alike;
- a leg's absolute levels cannot survive a split: an entry whose entry bar moved by more than 25%
  is frozen as ``rebase_needed`` (Part 3 rebases).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.common.config import ValueCfg
from src.common.value_inputs import build_day_bars, closes_on, read_bars
from src.common.value_types import DayBar
from src.value.exits import POLICIES, DayFacts, LegState, benchmark_return, open_leg, step
from src.value.rank import rank_list
from src.value.ranked import BUCKETS, buckets, equal_weight_return, is_new_month
from src.value.report import HORIZONS
from src.value.schemas import LISTS, ValueScorecard
from src.value.store import (
    ValueRankedRow,
    ValueShadowEventRow,
    ValueShadowLegRow,
    ValueShadowRow,
)

BENCHMARK = "SPY"
TRACK = "baseline"
SPLIT_GUARD = 0.25
GRACE_SESSIONS = 5
SHADOW_UNIVERSES = ("trading", "evidence")


@dataclass(slots=True)
class ShadowSummary:
    opened: dict[str, int] = field(default_factory=dict)
    filled: int = 0
    voided: int = 0
    events: int = 0
    marked: int = 0
    closed: int = 0
    rebase_needed: int = 0
    ranked_formed: int = 0
    ranked_closed: int = 0


def _actual(card: ValueScorecard, check_id: str) -> float | None:
    for c in card.health_checks:
        if c.id == check_id:
            return c.actual
    return None


def day_facts(card: ValueScorecard | None, list_name: str) -> DayFacts | None:
    """The night's Python numbers for one list (baseline track: effective = Python's)."""
    if card is None:
        return None
    ev = card.lists.get(list_name)
    fv = ev.fair_value if ev is not None else None
    return DayFacts(
        python_fair_value=fv,
        effective_fair_value=fv,
        latest_accn=card.fingerprint.latest_accn,
        piotroski=_actual(card, "health.piotroski"),
        altman_z=_actual(card, "health.altman_z"),
    )


def blocking_keys(vs: Session, live_policy: str) -> set[tuple[str, str, str]]:
    """(kind, list, symbol) keys that may not enter again tonight."""
    out: set[tuple[str, str, str]] = set()
    rows = vs.scalars(
        select(ValueShadowRow).where(
            ValueShadowRow.track == TRACK,
            ValueShadowRow.status.in_(("pending", "open", "rebase_needed")),
        )
    )
    for row in rows:
        key = (row.kind, row.list_name, row.symbol)
        if row.kind != "ready" or row.status != "open":
            out.add(key)
            continue
        live = vs.scalar(
            select(ValueShadowLegRow.closed).where(
                ValueShadowLegRow.shadow_id == row.id, ValueShadowLegRow.policy == live_policy
            )
        )
        if not live:
            out.add(key)
    return out


def _entry(
    card: ValueScorecard,
    list_name: str,
    kind: str,
    universe: str,
    atr14: float | None,
    now: datetime,
) -> ValueShadowRow:
    ev = card.lists[list_name]
    return ValueShadowRow(
        track=TRACK,
        kind=kind,
        list_name=list_name,
        symbol=card.symbol,
        universe=universe,
        signal_date=card.as_of,
        status="pending",
        status_detail="",
        verdict=ev.verdict,
        signal_close=card.price,
        atr14=atr14,
        fair_value=ev.fair_value,
        effective_fair_value=ev.fair_value,
        margin_of_safety=ev.margin_of_safety,
        required_mos_pct=ev.required_mos_pct,
        fv_accn=card.fingerprint.latest_accn,
        fingerprint_key=card.fingerprint.key(),
        ruleset_version=card.ruleset_version,
        ruleset_hash=card.ruleset_hash,
        scorecard_json=card.model_dump_json(),
        created_at=now,
    )


def open_signals(
    vs: Session,
    cards: list[ValueScorecard],
    tags: dict[str, str],
    atr: dict[str, float | None],
    *,
    live_policy: str,
    now: datetime,
) -> dict[str, int]:
    """Tonight's READY signals, then the control groups for every list that got one. Only the
    trading and evidence universes enter (a followed lookup does not)."""
    blocked = blocking_keys(vs, live_policy)
    counts = {"ready": 0, "control_valuation": 0, "control_health": 0}
    eligible = [
        c
        for c in cards
        if tags.get(c.symbol) in SHADOW_UNIVERSES
        and c.data_quality == "pass"
        and c.not_applicable_reason is None
    ]

    def add(card: ValueScorecard, list_name: str, kind: str) -> None:
        key = (kind, list_name, card.symbol)
        if key in blocked:
            return
        vs.add(_entry(card, list_name, kind, tags[card.symbol], atr.get(card.symbol), now))
        blocked.add(key)
        counts[kind] += 1

    ready_lists: set[str] = set()
    for card in eligible:
        for name in LISTS:
            if card.verdict_for(name) == "READY":
                before = counts["ready"]
                add(card, name, "ready")
                if counts["ready"] > before:
                    ready_lists.add(name)
    for name in (n for n in LISTS if n in ready_lists):
        for card in eligible:
            ev = card.lists.get(name)
            if ev is None:
                continue
            if ev.verdict == "WAIT":
                add(card, name, "control_valuation")
            elif (
                card.health == "fail"
                and ev.entry_ceiling is not None
                and card.price is not None
                and card.price <= ev.entry_ceiling
            ):
                add(card, name, "control_health")
    return counts


def load_bars(rs: Session, symbols: set[str], as_of: date) -> dict[str, list[DayBar]]:
    return {s: build_day_bars(read_bars(rs, s, as_of)) for s in sorted(symbols)}


def _bar_on(bars: list[DayBar], day: date) -> DayBar | None:
    return next((b for b in bars if b.date == day), None)


def _price(bar: DayBar) -> float:
    return bar.open if bar.open is not None else bar.close


def fill_pending(vs: Session, market: dict[str, list[DayBar]], cfg: ValueCfg) -> tuple[int, int]:
    """Enter yesterday's signals at the next session's open; void one that gets no bar within
    ``GRACE_SESSIONS`` of SPY's sessions."""
    spy = market.get(BENCHMARK, [])
    filled = voided = 0
    for row in vs.scalars(select(ValueShadowRow).where(ValueShadowRow.status == "pending")):
        after = [b for b in market.get(row.symbol, []) if b.date > row.signal_date]
        spy_bar = _bar_on(spy, after[0].date) if after else None
        if after and spy_bar is not None:
            first = after[0]
            row.entry_date = first.date
            row.entry_price = _price(first)
            row.spy_entry_price = _price(spy_bar)
            row.status = "open"
            filled += 1
            if row.kind == "ready":
                for policy in POLICIES:
                    state = open_leg(
                        policy,
                        entry_date=first.date,
                        entry_price=row.entry_price,
                        atr14=row.atr14,
                        fair_value=row.fair_value,
                        effective_fair_value=row.effective_fair_value,
                        fv_accn=row.fv_accn,
                        cfg=cfg.rules.exits,
                    )
                    vs.add(
                        ValueShadowLegRow(
                            shadow_id=row.id, policy=policy, state_json=state.model_dump_json()
                        )
                    )
        elif sum(1 for b in spy if b.date > row.signal_date) >= GRACE_SESSIONS:
            row.status = "void"
            row.status_detail = f"no {row.symbol} bar within {GRACE_SESSIONS} sessions"
            voided += 1
    vs.flush()
    return filled, voided


def _split_moved(row: ValueShadowRow, bars: list[DayBar]) -> bool:
    if row.entry_date is None or not row.entry_price:
        return False
    bar = _bar_on(bars, row.entry_date)
    return bar is not None and abs(_price(bar) / row.entry_price - 1.0) > SPLIT_GUARD


def _freeze(row: ValueShadowRow) -> None:
    row.status = "rebase_needed"
    row.status_detail = (
        f"the {row.entry_date} bar no longer matches the entry price {row.entry_price:.2f} "
        "(a split?): frozen until Part 3's rebase"
    )


def step_legs(
    vs: Session,
    market: dict[str, list[DayBar]],
    cards: dict[str, ValueScorecard],
    cfg: ValueCfg,
) -> tuple[int, int]:
    """Run every open leg over the sessions it has not seen, with tonight's facts."""
    spy_open = {b.date: _price(b) for b in market.get(BENCHMARK, [])}
    n_events = frozen = 0
    rows = vs.scalars(
        select(ValueShadowRow).where(
            ValueShadowRow.status == "open", ValueShadowRow.kind == "ready"
        )
    ).all()
    for row in rows:
        bars = market.get(row.symbol, [])
        if _split_moved(row, bars):
            _freeze(row)
            frozen += 1
            continue
        assert row.entry_date is not None and row.spy_entry_price is not None
        facts = day_facts(cards.get(row.symbol), row.list_name)
        legs = vs.scalars(
            select(ValueShadowLegRow).where(
                ValueShadowLegRow.shadow_id == row.id, ValueShadowLegRow.closed.is_(False)
            )
        )
        for leg in legs:
            state = LegState.model_validate_json(leg.state_json)
            days = [
                b
                for b in bars
                if b.date >= row.entry_date and (leg.last_step is None or b.date > leg.last_step)
            ]
            for b in days:
                state, events = step(state, b, facts, cfg.rules.exits)
                for e in events:
                    vs.add(
                        ValueShadowEventRow(
                            shadow_id=row.id,
                            policy=leg.policy,
                            day=e.day,
                            kind=e.kind,
                            price=e.price,
                            fraction=e.fraction,
                            detail=e.detail,
                        )
                    )
                n_events += len(events)
            if days:
                leg.last_step = days[-1].date
            leg.state_json = state.model_dump_json()
            leg.sessions, leg.sells = state.sessions, state.sells
            leg.max_drawdown = state.max_drawdown
            if state.closed:
                vs.flush()
                fills = [
                    (d, f)
                    for d, f in vs.execute(
                        select(ValueShadowEventRow.day, ValueShadowEventRow.fraction).where(
                            ValueShadowEventRow.shadow_id == row.id,
                            ValueShadowEventRow.policy == leg.policy,
                            ValueShadowEventRow.kind == "fill",
                        )
                    )
                ]
                leg.closed, leg.exit_date = True, state.exit_date
                leg.ret_exit = state.exit_return()
                leg.spy_ret_exit = benchmark_return(fills, spy_open, row.spy_entry_price)
    vs.flush()
    return n_events, frozen


def _close_on_or_before(bars: list[DayBar], day: date) -> float | None:
    before = [b for b in bars if b.date <= day]
    return before[-1].close if before else None


def mark_horizons(vs: Session, market: dict[str, list[DayBar]]) -> tuple[int, int]:
    """Mark-to-market returns at 21/63/126 sessions (spec §12), against SPY, for every open
    entry: READY and control alike."""
    spy = market.get(BENCHMARK, [])
    marked = frozen = 0
    for row in vs.scalars(select(ValueShadowRow).where(ValueShadowRow.status == "open")).all():
        assert row.entry_date is not None and row.entry_price is not None
        bars = market.get(row.symbol, [])
        if _split_moved(row, bars):
            _freeze(row)
            frozen += 1
            continue
        sessions = [b for b in spy if b.date >= row.entry_date]
        entry_bar = _bar_on(bars, row.entry_date)
        entry_px = _price(entry_bar) if entry_bar is not None else row.entry_price
        spy_entry = _price(sessions[0]) if sessions else row.spy_entry_price
        for h in HORIZONS:
            if getattr(row, f"ret_{h}") is not None or len(sessions) <= h:
                continue
            mark = sessions[h]
            seen_since = any(b.date >= mark.date for b in bars)
            late = sum(1 for b in spy if b.date > mark.date) >= GRACE_SESSIONS
            if not seen_since and not late:
                continue  # the name's bars may still arrive
            close = _close_on_or_before(bars, mark.date)
            if close is None or not spy_entry:
                continue
            setattr(row, f"ret_{h}", close / entry_px - 1.0)
            setattr(row, f"spy_{h}", mark.close / spy_entry - 1.0)
            if not seen_since:
                row.status_detail += f" h{h}: no bar since; last close used."
            marked += 1
    vs.flush()
    return marked, frozen


def close_finished(vs: Session, as_of: date) -> int:
    """An entry closes once all three horizons are marked and every leg has exited."""
    closed = 0
    for row in vs.scalars(select(ValueShadowRow).where(ValueShadowRow.status == "open")).all():
        if any(getattr(row, f"ret_{h}") is None for h in HORIZONS):
            continue
        open_legs = vs.scalar(
            select(func.count())
            .select_from(ValueShadowLegRow)
            .where(ValueShadowLegRow.shadow_id == row.id, ValueShadowLegRow.closed.is_(False))
        )
        if open_legs:
            continue
        row.status, row.closed_on = "closed", as_of
        closed += 1
    return closed


def run_ranked(
    vs: Session,
    rs: Session,
    cards: list[ValueScorecard],
    evidence: set[str],
    *,
    as_of: date,
    version: str,
    digest: str,
) -> tuple[int, int]:
    """On the first run of a new month: close the open portfolios at tonight's closes and form
    the next ones from tonight's ranks (spec §6.8)."""
    last = vs.scalar(select(func.max(ValueRankedRow.formed_on)))
    if not is_new_month(last, as_of):
        return 0, 0
    closed = 0
    spy_end = closes_on(rs, [BENCHMARK], as_of).get(BENCHMARK)
    open_rows = vs.scalars(select(ValueRankedRow).where(ValueRankedRow.closed_on.is_(None))).all()
    for row in open_rows:
        members = json.loads(row.members_json)
        start = closes_on(rs, members, row.formed_on)
        end = closes_on(rs, members, as_of)
        row.ret, row.missing = equal_weight_return(members, start, end)
        spy_start = closes_on(rs, [BENCHMARK], row.formed_on).get(BENCHMARK)
        row.spy_ret = spy_end / spy_start - 1.0 if spy_end and spy_start else None
        row.closed_on = as_of
        closed += 1
    formed = 0
    population = [c for c in cards if c.symbol in evidence]
    for name in LISTS:
        ranks = rank_list(population, name)
        picked = buckets({s: e.score for s, e in ranks.items()})
        if picked is None:
            continue
        for bucket in BUCKETS:
            vs.add(
                ValueRankedRow(
                    formed_on=as_of,
                    list_name=name,
                    bucket=bucket,
                    members_json=json.dumps(picked[bucket]),
                    n=len(picked[bucket]),
                    ruleset_version=version,
                    ruleset_hash=digest,
                )
            )
            formed += 1
    return formed, closed


def process(
    vs: Session,
    rs: Session,
    cards: list[ValueScorecard],
    *,
    tags: dict[str, str],
    atr: dict[str, float | None],
    evidence: set[str],
    as_of: date,
    cfg: ValueCfg,
    version: str,
    digest: str,
    now: datetime,
) -> ShadowSummary:
    """One night of the shadow record, in order: fill yesterday's signals, run the legs, mark
    the horizons, close what is finished, open tonight's signals, then the ranked record."""
    out = ShadowSummary()
    by_symbol = {c.symbol: c for c in cards}
    live = cfg.rules.exits.live_policy
    held = set(
        vs.scalars(
            select(ValueShadowRow.symbol).where(ValueShadowRow.status.in_(("pending", "open")))
        )
    )
    market = load_bars(rs, held | {BENCHMARK}, as_of)
    out.filled, out.voided = fill_pending(vs, market, cfg)
    out.events, frozen_legs = step_legs(vs, market, by_symbol, cfg)
    out.marked, frozen_marks = mark_horizons(vs, market)
    out.rebase_needed = frozen_legs + frozen_marks
    vs.flush()
    out.closed = close_finished(vs, as_of)
    vs.flush()
    out.opened = open_signals(vs, cards, tags, atr, live_policy=live, now=now)
    out.ranked_formed, out.ranked_closed = run_ranked(
        vs, rs, cards, evidence, as_of=as_of, version=version, digest=digest
    )
    return out
