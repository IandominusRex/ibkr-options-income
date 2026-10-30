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
- (Part 3) a leg's absolute levels are **rebased** mechanically when the provider rewrote the
  bars (a split, a special or ordinary dividend adjustment): the bar now on a leg's last stepped
  session against the close the leg saw there (the entry bar for an entry not yet stepped) gives
  the ratio, and every recorded price level of the entry and its legs is multiplied by it. Part 2's
  ``rebase_needed`` entries are rebased and re-opened the same way;
- (Part 3) every session a READY entry's main legs step is checked for §7.1's triggers; a
  re-evaluation is recorded in ``value_reevaluations``, applies its plan actions to the main legs,
  and from the first one on the entry also carries an ``original`` twin of each leg, stepped with
  no re-evaluation, so the report can say whether re-evaluating saved money or only churned;
- (review M1) tonight's scorecard facts are read only on the session dated tonight's as_of: a
  catch-up night steps the earlier sessions on price alone.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.common.config import ValueCfg
from src.common.value_inputs import (
    build_day_bars,
    closes_on,
    filings_between,
    going_concern_flags,
    read_bars,
)
from src.common.value_types import DayBar, FilingEvent, NewsVolume
from src.value import reevaluate
from src.value.exits import (
    POLICIES,
    DayFacts,
    ExitEvent,
    LegState,
    Reeval,
    benchmark_return,
    open_leg,
    step,
)
from src.value.rank import rank_list
from src.value.ranked import BUCKETS, buckets, equal_weight_return, is_new_month
from src.value.report import HORIZONS
from src.value.residuals import Move, moves
from src.value.schemas import LISTS, ValueScorecard
from src.value.store import (
    ValueRankedRow,
    ValueReevaluationRow,
    ValueShadowEventRow,
    ValueShadowLegRow,
    ValueShadowRow,
)

BENCHMARK = "SPY"
TRACK = "baseline"
GRACE_SESSIONS = 5
SHADOW_UNIVERSES = ("trading", "evidence")
HELD = ("pending", "open", "rebase_needed")  # entries the record still carries
REBASE_TOLERANCE = 1e-4  # a ratio this close to 1 is float noise, not a rewrite
MAIN, ORIGINAL = "main", "original"


@dataclass(slots=True)
class ShadowSummary:
    opened: dict[str, int] = field(default_factory=dict)
    filled: int = 0
    voided: int = 0
    events: int = 0
    marked: int = 0
    closed: int = 0
    rebased: int = 0
    rebase_needed: int = 0  # entries still frozen: no bar left to measure a rebase against
    reevaluations: int = 0
    ranked_formed: int = 0
    ranked_closed: int = 0


@dataclass(slots=True)
class ReevalContext:
    """What tonight's re-evaluations read beyond the bars (spec §7.1): filings and going-concern
    reads from research.db, and the plain data the value process hands in."""

    filings: dict[str, list[FilingEvent]] = field(default_factory=dict)
    going_concern: dict[str, bool] = field(default_factory=dict)
    earnings: dict[str, list[date]] = field(default_factory=dict)
    news: dict[str, NewsVolume] = field(default_factory=dict)
    regime_stepped: bool = False
    etf_for: dict[str, str] = field(default_factory=dict)  # symbol -> its sector ETF


def _actual(card: ValueScorecard, check_id: str) -> float | None:
    for c in card.health_checks:
        if c.id == check_id:
            return c.actual
    return None


def _missing_components(card: ValueScorecard, check_id: str) -> int:
    """How many F-score components were unknown (the check's detail lists them, comma-joined)."""
    for c in card.health_checks:
        if c.id == check_id and c.actual is not None:
            return len([p for p in c.detail.split(", ") if p])
    return 0


def day_facts(
    card: ValueScorecard | None, list_name: str, going_concern: bool | None = None
) -> DayFacts | None:
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
        piotroski_missing=_missing_components(card, "health.piotroski"),
        altman_z=_actual(card, "health.altman_z"),
        going_concern=going_concern,
    )


def blocking_keys(vs: Session, live_policy: str) -> set[tuple[str, str, str]]:
    """(kind, list, symbol) keys that may not enter again tonight."""
    out: set[tuple[str, str, str]] = set()
    rows = vs.scalars(
        select(ValueShadowRow).where(
            ValueShadowRow.track == TRACK,
            ValueShadowRow.status.in_(HELD),
        )
    )
    for row in rows:
        key = (row.kind, row.list_name, row.symbol)
        if row.kind != "ready" or row.status != "open":
            out.add(key)
            continue
        live = vs.scalar(
            select(ValueShadowLegRow.closed).where(
                ValueShadowLegRow.shadow_id == row.id,
                ValueShadowLegRow.policy == live_policy,
                ValueShadowLegRow.plan == MAIN,
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


def _ratio(row: ValueShadowRow, legs: list[ValueShadowLegRow], bars: list[DayBar]) -> float | None:
    """How far the provider rewrote this entry's bars: the bar now on the newest stepped session
    over the close a leg saw there; for an entry no leg has stepped yet, the entry bar over the
    recorded entry price. None when no reference bar is left."""
    stepped = [g for g in legs if g.last_step is not None]
    if stepped:
        leg = max(stepped, key=lambda g: (g.last_step, not g.closed))
        assert leg.last_step is not None
        seen = LegState.model_validate_json(leg.state_json).last_close
        bar = _bar_on(bars, leg.last_step)
        if seen and bar is not None:
            return bar.close / seen
    if row.entry_date is None or not row.entry_price:
        return None
    entry = _bar_on(bars, row.entry_date)
    return None if entry is None else _price(entry) / row.entry_price


def _times(v: float | None, ratio: float) -> float | None:
    return None if v is None else v * ratio


def rebase(vs: Session, market: dict[str, list[DayBar]], day: date) -> tuple[int, int]:
    """Spec §7.1: corporate actions are not triggers; levels are rebased mechanically and the
    rebase is recorded. Re-opens Part 2's ``rebase_needed`` entries. Returns (rebased, still
    frozen)."""
    rebased = frozen = 0
    rows = vs.scalars(
        select(ValueShadowRow).where(ValueShadowRow.status.in_(("open", "rebase_needed")))
    ).all()
    for row in rows:
        legs = vs.scalars(
            select(ValueShadowLegRow).where(ValueShadowLegRow.shadow_id == row.id)
        ).all()
        ratio = _ratio(row, list(legs), market.get(row.symbol, []))
        if ratio is None or ratio <= 0:
            if row.status == "rebase_needed":
                frozen += 1
            continue
        if abs(ratio - 1.0) > REBASE_TOLERANCE:
            assert row.entry_price is not None
            row.entry_price *= ratio
            row.signal_close = _times(row.signal_close, ratio)
            row.atr14 = _times(row.atr14, ratio)
            row.fair_value = _times(row.fair_value, ratio)
            row.effective_fair_value = _times(row.effective_fair_value, ratio)
            for leg in legs:
                state = LegState.model_validate_json(leg.state_json).rebased(ratio)
                leg.state_json = state.model_dump_json()
            vs.add(
                ValueShadowEventRow(
                    shadow_id=row.id,
                    policy="all",
                    plan=MAIN,
                    day=day,
                    kind="rebase",
                    fraction=0.0,
                    detail=f"every price level x {ratio:.6f}: the bars were rewritten "
                    "(a split or a dividend adjustment)",
                )
            )
            rebased += 1
        if row.status == "rebase_needed":
            row.status = "open"
            row.status_detail += " Rebased and re-opened (Part 3)."
    vs.flush()
    return rebased, frozen


def _plan(states: dict[int, LegState]) -> dict[str, dict[str, object]]:
    return {
        s.policy: {
            "stop": s.stop,
            "armed": s.armed,
            "fair_value": s.fair_value,
            "remaining": s.remaining,
            "pending": s.pending,
            "closed": s.closed,
        }
        for s in states.values()
    }


def _closes(bars: list[DayBar]) -> list[tuple[date, float]]:
    return [(b.date, b.close) for b in bars]


def _record_events(
    vs: Session, row: ValueShadowRow, leg: ValueShadowLegRow, events: list[ExitEvent]
) -> None:
    for e in events:
        vs.add(
            ValueShadowEventRow(
                shadow_id=row.id,
                policy=leg.policy,
                plan=leg.plan,
                day=e.day,
                kind=e.kind,
                price=e.price,
                fraction=e.fraction,
                detail=e.detail,
            )
        )


class _Reevaluator:
    """One READY entry's §7.1 bookkeeping across the sessions of one night."""

    def __init__(
        self, vs: Session, row: ValueShadowRow, cfg: ValueCfg, ctx: ReevalContext, now: datetime
    ) -> None:
        self.vs, self.row, self.cfg, self.ctx, self.now = vs, row, cfg, ctx, now
        self.open = vs.scalars(
            select(ValueReevaluationRow)
            .where(ValueReevaluationRow.shadow_id == row.id)
            .order_by(ValueReevaluationRow.session.desc(), ValueReevaluationRow.id.desc())
            .limit(1)
        ).first()
        assert row.entry_date is not None
        self.last_day: date = self.open.session if self.open is not None else row.entry_date
        self.count = 0

    def triggers(
        self,
        bar: DayBar,
        after: date,
        move: Move | None,
        tonight: bool,
    ) -> list[reevaluate.Trigger]:
        sym = self.row.symbol
        return reevaluate.session_triggers(
            day=bar.date,
            after=after,
            move=move,
            filings=self.ctx.filings.get(sym, []),
            earnings=self.ctx.earnings.get(sym, []),
            news=self.ctx.news.get(sym) if tonight else None,
            regime_stepped=self.ctx.regime_stepped and tonight,
            last_reevaluation=self.last_day,
            cfg=self.cfg.rules.reevaluation,
        )

    def record(
        self,
        day: date,
        fired: list[reevaluate.Trigger],
        before: dict[str, dict[str, object]],
        after: dict[str, dict[str, object]],
        sessions_since: int | None,
        verdict_now: str | None,
    ) -> None:
        sev = reevaluate.severity(fired)
        assert sev is not None
        items = [{"day": day.isoformat(), **t.model_dump()} for t in fired]
        current = self.open
        if current is not None and reevaluate.joins(
            current.severity,  # type: ignore[arg-type]
            sessions_since,
            sev,
            self.cfg.rules.reevaluation,
        ):
            current.triggers_json = json.dumps([*json.loads(current.triggers_json), *items])
            current.last_session = day
            current.plan_after_json = json.dumps(after)
            if verdict_now is not None:
                current.verdict_now = verdict_now
            return
        self.open = ValueReevaluationRow(
            shadow_id=self.row.id,
            symbol=self.row.symbol,
            list_name=self.row.list_name,
            session=day,
            last_session=day,
            severity=sev,
            triggers_json=json.dumps(items),
            plan_before_json=json.dumps(before),
            plan_after_json=json.dumps(after),
            verdict_at_entry=self.row.verdict,
            verdict_now=verdict_now,
            ruleset_version=self.row.ruleset_version,
            ruleset_hash=self.row.ruleset_hash,
            created_at=self.now,
        )
        self.vs.add(self.open)
        self.last_day = day
        self.count += 1


def step_legs(
    vs: Session,
    market: dict[str, list[DayBar]],
    cards: dict[str, ValueScorecard],
    cfg: ValueCfg,
    *,
    as_of: date | None = None,
    context: ReevalContext | None = None,
    now: datetime | None = None,
) -> tuple[int, int]:
    """Run every open leg over the sessions it has not seen. Tonight's facts are read on the
    session dated *as_of* only (the name's newest bar when None, review M1). With a *context*,
    each session of a READY entry's main legs is checked for §7.1's triggers. Returns (events,
    re-evaluations opened)."""
    spy_open = {b.date: _price(b) for b in market.get(BENCHMARK, [])}
    rcfg = cfg.rules.reevaluation
    n_events = n_reevals = 0
    rows = vs.scalars(
        select(ValueShadowRow).where(
            ValueShadowRow.status == "open", ValueShadowRow.kind == "ready"
        )
    ).all()
    for row in rows:
        bars = market.get(row.symbol, [])
        assert row.entry_date is not None and row.spy_entry_price is not None
        legs = list(
            vs.scalars(
                select(ValueShadowLegRow).where(
                    ValueShadowLegRow.shadow_id == row.id, ValueShadowLegRow.closed.is_(False)
                )
            )
        )
        if not legs or not bars:
            continue
        tonight = as_of if as_of is not None else bars[-1].date
        card = cards.get(row.symbol)
        facts = day_facts(
            card,
            row.list_name,
            None if context is None else context.going_concern.get(row.symbol),
        )
        states = {leg.id: LegState.model_validate_json(leg.state_json) for leg in legs}
        firsts = [leg.last_step for leg in legs]
        start = None if any(f is None for f in firsts) else min(f for f in firsts if f)
        days = [b for b in bars if b.date >= row.entry_date and (start is None or b.date > start)]
        reeval = None
        found: dict[date, Move] = {}
        if context is not None and days and any(leg.plan == MAIN for leg in legs):
            reeval = _Reevaluator(vs, row, cfg, context, now or datetime.now())
            etf = market.get(context.etf_for.get(row.symbol, rcfg.fallback_etf), [])
            found = moves(_closes(bars), _closes(etf), [b.date for b in days], rcfg)
        index = {b.date: i for i, b in enumerate(bars)}
        for b in days:
            i = index[b.date]
            previous = bars[i - 1] if i > 0 else None
            after = (
                previous.date if previous and previous.date >= row.entry_date else row.signal_date
            )
            mains = [leg for leg in legs if leg.plan == MAIN and not states[leg.id].closed]
            action: Reeval | None = None
            fired: list[reevaluate.Trigger] = []
            if reeval is not None and mains:
                fired = reeval.triggers(b, after, found.get(b.date), b.date == tonight)
                if fired:
                    action = reevaluate.plan_actions(fired, b, previous, rcfg)
                    if not any(leg.plan == ORIGINAL for leg in legs):
                        for leg in mains:  # the original plan, untouched from here on
                            twin = ValueShadowLegRow(
                                shadow_id=row.id,
                                policy=leg.policy,
                                plan=ORIGINAL,
                                state_json=states[leg.id].model_dump_json(),
                                last_step=leg.last_step,
                                closed=False,
                                sessions=leg.sessions,
                                sells=leg.sells,
                                max_drawdown=leg.max_drawdown,
                            )
                            vs.add(twin)
                            vs.flush()
                            legs.append(twin)
                            states[twin.id] = states[leg.id]
            before = _plan({leg.id: states[leg.id] for leg in mains})
            for leg in legs:
                if leg.last_step is not None and b.date <= leg.last_step:
                    continue
                state = states[leg.id]
                if state.closed:
                    continue
                state, events = step(
                    state,
                    b,
                    facts if b.date == tonight else None,
                    cfg.rules.exits,
                    action if leg.plan == MAIN else None,
                )
                states[leg.id] = state
                leg.last_step = b.date
                _record_events(vs, row, leg, events)
                n_events += len(events)
            if fired and reeval is not None:
                opened = reeval.open.session if reeval.open is not None else None
                since = (
                    None if opened is None else sum(1 for d in bars if opened < d.date <= b.date)
                )
                reeval.record(
                    b.date,
                    fired,
                    before,
                    _plan({leg.id: states[leg.id] for leg in mains}),
                    since,
                    card.verdict_for(row.list_name)
                    if card is not None and b.date == tonight
                    else None,
                )
        if reeval is not None:
            n_reevals += reeval.count
        spy_entry = spy_open.get(row.entry_date, row.spy_entry_price)  # one basis (review M8)
        for leg in legs:
            state = states[leg.id]
            leg.state_json = state.model_dump_json()
            leg.sessions, leg.sells = state.sessions, state.sells
            leg.max_drawdown = state.max_drawdown
            if state.closed and not leg.closed:
                vs.flush()
                fills = [
                    (d, f)
                    for d, f in vs.execute(
                        select(ValueShadowEventRow.day, ValueShadowEventRow.fraction).where(
                            ValueShadowEventRow.shadow_id == row.id,
                            ValueShadowEventRow.policy == leg.policy,
                            ValueShadowEventRow.plan == leg.plan,
                            ValueShadowEventRow.kind == "fill",
                        )
                    )
                ]
                leg.closed, leg.exit_date = True, state.exit_date
                leg.ret_exit = state.exit_return()
                leg.spy_ret_exit = benchmark_return(fills, spy_open, spy_entry)
    vs.flush()
    return n_events, n_reevals


def _close_on_or_before(bars: list[DayBar], day: date) -> float | None:
    before = [b for b in bars if b.date <= day]
    return before[-1].close if before else None


def mark_horizons(vs: Session, market: dict[str, list[DayBar]]) -> int:
    """Mark-to-market returns at 21/63/126 sessions (spec §12), against SPY, for every open
    entry: READY and control alike. Both ends are read from the bars as they stand, so a split
    or a dividend adjustment needs no rebase here (controls are never frozen: review M7)."""
    spy = market.get(BENCHMARK, [])
    marked = 0
    for row in vs.scalars(select(ValueShadowRow).where(ValueShadowRow.status == "open")).all():
        assert row.entry_date is not None and row.entry_price is not None
        bars = market.get(row.symbol, [])
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
    return marked


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
    earnings: dict[str, list[date]] | None = None,
    news: dict[str, NewsVolume] | None = None,
    regime_stepped: bool = False,
) -> ShadowSummary:
    """One night of the shadow record, in order: fill yesterday's signals, rebase what the
    provider rewrote, run the legs with §7.1's re-evaluations, mark the horizons, close what is
    finished, open tonight's signals, then the ranked record. *earnings* (each name's recent
    report dates) and *news* (trigger 5) are plain data from the value process."""
    out = ShadowSummary()
    by_symbol = {c.symbol: c for c in cards}
    live = cfg.rules.exits.live_policy
    rcfg = cfg.rules.reevaluation
    held = set(vs.scalars(select(ValueShadowRow.symbol).where(ValueShadowRow.status.in_(HELD))))
    etf_for = {
        s: rcfg.sector_etfs.get(
            (by_symbol[s].classification.sector or "") if s in by_symbol else "",
            rcfg.fallback_etf,
        )
        for s in held
    }
    market = load_bars(rs, held | {BENCHMARK} | set(etf_for.values()), as_of)
    out.filled, out.voided = fill_pending(vs, market, cfg)
    out.rebased, out.rebase_needed = rebase(vs, market, as_of)
    open_ready = vs.scalars(
        select(ValueShadowRow).where(
            ValueShadowRow.status == "open", ValueShadowRow.kind == "ready"
        )
    ).all()
    symbols = sorted({r.symbol for r in open_ready})
    oldest = min((r.signal_date for r in open_ready), default=as_of)
    context = ReevalContext(
        filings=filings_between(rs, symbols, oldest, as_of),
        going_concern=going_concern_flags(rs, symbols, as_of),
        earnings=earnings or {},
        news=news or {},
        regime_stepped=regime_stepped,
        etf_for=etf_for,
    )
    out.events, out.reevaluations = step_legs(
        vs, market, by_symbol, cfg, as_of=as_of, context=context, now=now
    )
    out.marked = mark_horizons(vs, market)
    vs.flush()
    out.closed = close_finished(vs, as_of)
    vs.flush()
    out.opened = open_signals(vs, cards, tags, atr, live_policy=live, now=now)
    out.ranked_formed, out.ranked_closed = run_ranked(
        vs, rs, cards, evidence, as_of=as_of, version=version, digest=digest
    )
    return out
