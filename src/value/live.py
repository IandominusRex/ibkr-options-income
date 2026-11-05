"""The value book's money, in paper (spec §9; revision 4): the night's proposals and the RTH cycle.

**The night** (``plan_night``, after scoring): each held position's live-policy plan is stepped
and a sale it signals becomes a sell proposal (Python's: auto when ``auto_close`` is on; Claude's:
always a tap); Claude's BROKEN review or NO on a held name is a tap-only sell; each effective READY
trading name with a tranche due is sized and gated on the close, and passes (or fails only for
cash) into a buy proposal, auto when the autonomy ladder allows. A margin above the review line
is a tap-only proposal, never an automatic one.

**The RTH cycle** (``cycle``, every ``book.cycle_minutes`` on clientId 31): reconcile both books'
shares, expire what is old, send approved sells (capped so no wheel call is uncovered), then each
approved buy: a fresh quote, the gate again; a pass sends; a buy short only of cash opens a
funding request (the wheel's ``capital_release`` closes CSPs at breakeven or better for it) and
waits, re-gated every cycle, until its own fresh snapshot shows the room: **close first, confirm,
then buy**. A buy that lapses or is refused leaves its request lapsed; nothing else happens.

``hourly_check`` (spec §7.1, held names): a raw move at or past ``raw_move_pct`` against the last
close, or a Major 8-K filed today, opens a held re-evaluation (``position_id``), which pauses adds,
and queues Claude's review.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.common.books import is_spreads_underlying, value_sell_cap
from src.common.config import ValueCfg
from src.common.value_commands import trim_episode, trim_offer_stale
from src.common.value_types import DayBar, FilingEvent, NewsVolume
from src.value import reevaluate, sizing
from src.value.book import (
    TRIM_STATE_KEYS,
    WORKING,
    open_position,
    propose,
    reconcile,
    sell_shares,
    set_state,
    step_held,
    totals,
)
from src.value.book import expire as expire_proposals
from src.value.book import get_state as book_state
from src.value.claude_reads import queue_read
from src.value.executor import ValueBroker, send_order
from src.value.exits import DayFacts
from src.value.residuals import Move
from src.value.risk import BuyContext, fundable_only, validate
from src.value.schemas import ValueScorecard
from src.value.store import (
    ValueAttributionRow,
    ValueEffectiveRow,
    ValueFundingRow,
    ValueOrderRow,
    ValuePositionRow,
    ValueProposalRow,
    ValueReevaluationRow,
    ValueShadowRow,
    ValueTickerFileRow,
)

log = logging.getLogger(__name__)
SessionFactory = Callable[[], AbstractContextManager[Session]]
SNAPSHOT = "snapshot"
LedgerFill = Callable[[str], tuple[float, float | None]]  # orderRef -> (shares filled, avg price)
PYTHON_STOPS = ("stop", "trail", "thesis", "catastrophe", "remark_below")
_SEVERITY_RANK = {"minor": 0, "major": 1}


@dataclass(frozen=True)
class Snapshot:
    """The account as clientId 31 saw it: both books' stock (the broker's truth)."""

    net_liq: float
    shares: dict[str, float] = field(default_factory=dict)
    marks: dict[str, float] = field(default_factory=dict)
    wheel_short_calls: dict[str, int] = field(default_factory=dict)
    csp_by_name: dict[str, float] = field(default_factory=dict)
    adv: dict[str, float] = field(default_factory=dict)  # 20-day dollar volume, from the cards

    @property
    def stock_value(self) -> float:
        return sum(q * self.marks.get(s, 0.0) for s, q in self.shares.items())

    @property
    def csp_collateral(self) -> float:
        return sum(self.csp_by_name.values())


def _card(vs: Session, symbol: str) -> ValueScorecard | None:
    row = vs.get(ValueTickerFileRow, symbol)
    return None if row is None else ValueScorecard.model_validate_json(row.scorecard_json)


def _earnings_in_window(card: ValueScorecard, list_name: str) -> bool | None:
    ev = card.lists.get(list_name)
    check = next((c for c in (ev.timing_checks if ev else []) if c.id == "timing.earnings"), None)
    if check is None or check.state == "unknown":
        return None
    return check.state == "fail"


def adds_paused(vs: Session, symbol: str, today: date, debounce_sessions: int) -> bool:
    """§7.1 step 1: no tranche while a held re-evaluation is open: its last trigger within the
    debounce window, or Claude's review queued, WEAKENED or BROKEN."""
    pos_ids = list(
        vs.scalars(
            select(ValuePositionRow.id).where(
                ValuePositionRow.symbol == symbol, ValuePositionRow.status == "open"
            )
        )
    )
    if not pos_ids:
        return False
    for r in vs.scalars(
        select(ValueReevaluationRow).where(ValueReevaluationRow.position_id.in_(pos_ids))
    ):
        # sessions approximated by calendar days (5 sessions a week), rounded up
        recent = (today - r.last_session).days <= debounce_sessions * 7 // 5 + 1
        if recent or r.review_state in ("WEAKENED", "BROKEN"):
            return True
    return False


def buy_context(
    vs: Session,
    *,
    symbol: str,
    list_name: str,
    shares: int,
    price: float,
    snapshot: Snapshot,
    cfg: ValueCfg,
    portfolio: dict,
    today: date,
    halted: bool,
    is_live: bool,
    trend_brake: bool,
    drawdown_stop: bool,
    exclude_proposal: int | None = None,
    quote_age_seconds: float | None = None,
) -> BuyContext | None:
    """Everything the gate reads for one buy; None when the name has no ticker file or no
    effective verdict (the gate then never runs: nothing is proposed).

    ``gross_used`` is read from *snapshot*, the account as it is **now**: stock of both books and
    the CSP collateral still held, plus the other approved buys' cost. A capital release that has
    already closed a put is therefore already reflected in it and is never subtracted again here.
    """
    eff = vs.get(ValueEffectiveRow, (symbol, list_name))
    card = _card(vs, symbol)
    if eff is None or card is None:
        return None
    ev = card.lists.get(list_name)
    t = totals(vs)
    name = t.names.get(symbol)
    earmark = sum(
        p.cost_usd
        for p in vs.scalars(
            select(ValueProposalRow).where(
                ValueProposalRow.kind == "buy",
                ValueProposalRow.status.in_(("approved", "funding")),
            )
        )
        if p.id != exclude_proposal
    )
    att = vs.get(ValueAttributionRow, symbol)
    wheel_stock = max(
        0.0,
        snapshot.shares.get(symbol, 0.0) - (name.filled if name else 0.0),
    ) * snapshot.marks.get(symbol, price)
    return BuyContext(
        symbol=symbol,
        list_name=list_name,
        shares=shares,
        price=price,
        verdict=eff.verdict,
        mos=(eff.fair_value - price) / eff.fair_value if eff.fair_value else None,
        required_mos_pct=ev.required_mos_pct if ev else 100.0,
        mos_review=eff.mos_review,
        health=card.health,
        data_quality=card.data_quality,
        timing=ev.timing if ev else "unknown",
        earnings_in_window=_earnings_in_window(card, list_name),
        net_liq=snapshot.net_liq,
        ceiling=sizing.ceiling_usd(snapshot.net_liq, cfg.book, trend_brake=trend_brake),
        book_cost=t.cost,
        list_cost=t.list_cost(list_name),
        name_cost=(name.cost + name.working_buy_cost) if name else 0.0,
        holds_name=bool(name and (name.filled > 0 or name.working_buy_cost > 0)),
        positions_open=t.positions_open,
        wheel_name_exposure=snapshot.csp_by_name.get(symbol, 0.0) + wheel_stock,
        gross_used=snapshot.stock_value + snapshot.csp_collateral + earmark,
        adv_dollar_20=snapshot.adv.get(symbol, card.metrics.get("adv_dollar_20")),
        attribution="ok" if att is None else att.state,
        adds_paused=adds_paused(vs, symbol, today, cfg.rules.reevaluation.debounce_sessions),
        trend_brake=trend_brake,
        drawdown_stop=drawdown_stop,
        is_live=is_live,
        halted=halted,
        spreads_underlying=is_spreads_underlying(symbol),
        quote_age_seconds=quote_age_seconds,
    )


def _gate(ctx: BuyContext, cfg: ValueCfg, portfolio: dict) -> list[str]:
    return validate(
        ctx,
        cfg.book,
        max_gross_notional_pct=float(portfolio.get("max_gross_notional_pct", 100.0)),
        max_combined_name_pct=float(portfolio.get("max_combined_name_pct", 15.0)),
    )


@dataclass
class NightSummary:
    sells: int = 0
    buys: int = 0
    tap: int = 0
    refused: dict[str, list[str]] = field(default_factory=dict)
    skipped: str = ""


def plan_night(
    vs: Session,
    *,
    cards: dict[str, ValueScorecard],
    tags: dict[str, str],
    bars: dict[str, list[DayBar]],
    facts: dict[tuple[str, str], DayFacts],
    cfg: ValueCfg,
    portfolio: dict,
    now: datetime,
    today: date,
    may_auto_open: Callable[[str], bool],
    auto_close: bool,
    halted: bool,
    is_live: bool,
    trend_brake: bool,
) -> NightSummary:
    out = NightSummary()
    t = totals(vs)
    ttl = cfg.book.proposal_ttl_hours
    for sig in step_held(vs, bars, facts, cfg):
        held = t.names.get(sig.symbol)
        shares = sell_shares(held.filled if held else 0.0, sig.fraction)
        if shares < 1:
            continue
        row = propose(
            vs,
            kind="sell",
            symbol=sig.symbol,
            list_name=sig.list_name,
            shares=shares,
            price=None,
            reason=sig.reason,
            cause=sig.cause,
            auto=auto_close and sig.cause == "python",
            now=now,
            ttl_hours=ttl,
            position_id=sig.position_id,
        )
        if row is not None:
            out.sells += 1
            out.tap += int(row.needs_tap)
    for pos in vs.scalars(select(ValuePositionRow).where(ValuePositionRow.status == "open")):
        eff = vs.get(ValueEffectiveRow, (pos.symbol, pos.list_name))
        broken = vs.scalars(
            select(ValueReevaluationRow).where(
                ValueReevaluationRow.position_id == pos.id,
                ValueReevaluationRow.review_state == "BROKEN",
            )
        ).first()
        claude_no = eff is not None and eff.decided_by == "claude" and eff.verdict == "NO"
        held = t.names.get(pos.symbol)
        if (broken is not None or claude_no) and held and held.filled >= 1:
            row = propose(
                vs,
                kind="sell",
                symbol=pos.symbol,
                list_name=pos.list_name,
                shares=sell_shares(held.filled, 1.0),
                price=None,
                reason="claude_broken" if broken is not None else "claude_no",
                cause="claude",
                auto=False,
                now=now,
                ttl_hours=ttl,
                position_id=pos.id,
            )
            if row is not None:
                out.sells += 1
                out.tap += 1
    snap_raw = book_state(vs, SNAPSHOT)
    if snap_raw is None:
        out.skipped = "no account snapshot yet (the RTH cycle writes one)"
        return out
    snap = Snapshot(**snap_raw)
    peak = book_state(vs, "high_water") or {}
    drawdown_stop = bool(peak.get("stop", False))
    for eff in vs.scalars(select(ValueEffectiveRow).where(ValueEffectiveRow.verdict == "READY")):
        if tags.get(eff.symbol) != "trading":
            continue
        card = cards.get(eff.symbol)
        if card is None or card.price is None:
            continue
        held_pos = vs.scalars(
            select(ValuePositionRow).where(
                ValuePositionRow.symbol == eff.symbol,
                ValuePositionRow.list_name == eff.list_name,
                ValuePositionRow.status == "open",
            )
        ).first()
        done = held_pos.tranches_done if held_pos else 0
        b = bars.get(eff.symbol, [])
        since = [
            x
            for x in b
            if held_pos and held_pos.last_tranche_on and x.date > held_pos.last_tranche_on
        ]
        lows = [x.low for x in since if x.low is not None]
        if not sizing.tranche_due(
            done,
            len(since) if held_pos else None,
            lows,
            card.price,
            b[-1].sma50 if b else None,
            cfg.book,
        ):
            continue
        mos = (eff.fair_value - card.price) / eff.fair_value if eff.fair_value else None
        target = sizing.target_cost(
            eff.list_name, mos, snap.net_liq, cfg.book, trend_brake=trend_brake
        )
        name = t.names.get(eff.symbol)
        shares = sizing.tranche_shares(
            target, cfg.book.tranches, card.price, name.cost if name else 0.0
        )
        ctx = buy_context(
            vs,
            symbol=eff.symbol,
            list_name=eff.list_name,
            shares=shares,
            price=card.price,
            snapshot=snap,
            cfg=cfg,
            portfolio=portfolio,
            today=today,
            halted=halted,
            is_live=is_live,
            trend_brake=trend_brake,
            drawdown_stop=drawdown_stop,
        )
        if ctx is None:
            continue
        reasons = _gate(ctx, cfg, portfolio)
        review_only = reasons == ["data_unreliable"] and ctx.data_quality == "pass"
        if reasons and not fundable_only(reasons) and not review_only:
            out.refused[f"{eff.symbol}:{eff.list_name}"] = reasons
            continue
        row = propose(
            vs,
            kind="buy",
            symbol=eff.symbol,
            list_name=eff.list_name,
            shares=shares,
            price=card.price,
            reason=f"tranche {done + 1}",
            cause=eff.decided_by,
            auto=may_auto_open(eff.symbol) and not halted and not review_only,
            now=now,
            ttl_hours=ttl,
            tranche=done + 1,
            position_id=held_pos.id if held_pos else None,
            gate=reasons,
        )
        if row is not None:
            out.buys += 1
            out.tap += int(row.needs_tap)
    return out


async def cycle(
    session: SessionFactory,
    broker: ValueBroker,
    snap: Snapshot,
    *,
    wheel: dict[str, float],
    cfg: ValueCfg,
    portfolio: dict,
    now: datetime,
    halted: bool,
    is_live: bool,
    trend_brake: bool,
    ledger_fill: LedgerFill | None = None,
) -> list[str]:
    """One RTH cycle. Returns the messages to send (fills, freezes, funding). It starts by
    resolving any order a restart or an unconfirmed cancel left working (spec §9.2: V is rebuilt
    from the broker and the ledger, never from this process's memory)."""
    msgs: list[str] = await resolve_working_orders(
        session, broker, now=now, cfg=cfg, ledger_fill=ledger_fill
    )
    with session() as vs:
        frozen = reconcile(
            vs,
            snap.shares,
            wheel,
            snap.marks,
            now=now,
            grace_hours=cfg.book.attribution_grace_hours,
        )
        expire_proposals(vs, now)
        set_state(vs, SNAPSHOT, asdict(snap), now)
        _high_water(vs, snap, cfg, now)  # a new episode is posted as a card by src.value.outbox
        sells = [
            (p.id, p.symbol, p.list_name, p.shares, p.reason)
            for p in vs.scalars(
                select(ValueProposalRow)
                .where(ValueProposalRow.kind == "sell", ValueProposalRow.status == "approved")
                .order_by(ValueProposalRow.id)
            )
        ]
        buys = [
            p.id
            for p in vs.scalars(
                select(ValueProposalRow)
                .where(
                    ValueProposalRow.kind == "buy",
                    ValueProposalRow.status.in_(("approved", "funding")),
                )
                .order_by(ValueProposalRow.id)
            )
        ]
    msgs += [
        f"Value book: share attribution FROZEN on {s} (both books stop opening it)" for s in frozen
    ]
    for pid, symbol, list_name, shares, reason in sells:
        msgs += await _sell(session, broker, snap, pid, symbol, list_name, shares, reason, cfg, now)
    for pid in buys:
        msgs += await _buy(
            session,
            broker,
            snap,
            pid,
            cfg=cfg,
            portfolio=portfolio,
            now=now,
            halted=halted,
            is_live=is_live,
            trend_brake=trend_brake,
        )
    return msgs


async def resolve_working_orders(
    session: SessionFactory,
    broker: ValueBroker,
    *,
    now: datetime,
    cfg: ValueCfg,
    ledger_fill: LedgerFill | None = None,
) -> list[str]:
    """Recovery at cycle start (spec §9.2 "rebuild V from the ledger's value: rows / the broker").

    Cycles never overlap, so any order still ``pending``/``submitted``/``partial`` now was left by
    a restart or by a cancel the broker never confirmed. Each is looked up on the broker by its
    ``orderRef``: still open (so past its timeout) -> cancelled, and confirmed, before anything is
    recorded; done -> its executions; unknown to the broker -> the ledger's ``book="value"`` rows;
    found nowhere -> a DAY order cannot still be working, so it is closed out unfilled (a fill the
    broker no longer shows and the ledger has not yet brought freezes the name at the reconcile,
    for a human). A broker that cannot be asked leaves the row alone for the next cycle. Then every
    proposal still ``sent`` is settled: terminal orders end it (as the live path would have), and
    one with no order goes back to ``approved`` to be re-gated."""
    with session() as vs:
        working = [
            (o.id, o.order_ref, o.symbol, o.side)
            for o in vs.scalars(
                select(ValueOrderRow)
                .where(ValueOrderRow.status.in_(WORKING))
                .order_by(ValueOrderRow.id)
            )
        ]
    msgs: list[str] = []
    for oid, ref, symbol, side in working:
        try:
            found = await broker.lookup(ref)
            outcome = None if found is None else found.outcome
            if found is not None and found.placed is not None:
                outcome = await broker.cancel(found.placed)
                if not outcome.done:
                    log.warning("value order %s: cancel still unconfirmed; will retry", ref)
                    continue
        except Exception:  # noqa: BLE001 - the broker cannot be asked: leave the row as it is
            log.exception("value order %s: could not be resolved from the broker", ref)
            continue
        filled, avg = (outcome.filled, outcome.avg_price) if outcome is not None else (0.0, None)
        if ledger_fill is not None:
            l_filled, l_avg = ledger_fill(ref)
            if l_filled > filled:
                filled, avg = l_filled, l_avg
        with session() as vs:
            row = vs.get(ValueOrderRow, oid)
            assert row is not None
            row.filled, row.avg_price = filled, avg
            row.status = "filled" if filled >= row.shares - 1e-9 else "cancelled"
            row.done_at = now
            note = (
                "recovered at cycle start from the broker/ledger"
                if (outcome is not None or filled > 0)
                else "not found at the broker or the ledger: closed out unfilled"
            )
            row.detail = f"{row.detail} | {note}" if row.detail else note
        log.warning("value order %s %s %s: %s (filled %g)", ref, side, symbol, note, filled)
        if filled > 0:
            msgs.append(f"Value book: recovered a {side} of {filled:g} {symbol} (order {ref})")
    with session() as vs:
        for prop in vs.scalars(select(ValueProposalRow).where(ValueProposalRow.status == "sent")):
            orders = list(
                vs.scalars(
                    select(ValueOrderRow)
                    .where(ValueOrderRow.proposal_id == prop.id)
                    .order_by(ValueOrderRow.id)
                )
            )
            if any(o.status in WORKING for o in orders):
                continue  # still being resolved
            if not orders:
                prop.status = "approved"  # never reached the broker: re-gated and sent afresh
                continue
            msgs += (
                _finish_buy(vs, prop, orders[-1], cfg, now)
                if prop.kind == "buy"
                else _finish_sell(vs, prop, orders[-1], now)
            )
    return msgs


def _high_water(vs: Session, snap: Snapshot, cfg: ValueCfg, now: datetime) -> str | None:
    """The book's value (filled shares at their marks) against its high: the drawdown breaker
    (spec §9.6) stops entries past ``drawdown_stop_pct``; a human resets it. At
    ``drawdown_trim_pct`` the trim to half is offered once per episode (Part 6, ruling 11): the
    new episode's id is returned the first time, and ``None`` after (and until a reset).

    Unknown is not zero (final review I-B): a held name with no positive mark this cycle makes the
    whole reading unknown, and nothing is updated. An offer that has gone stale (older than
    ``TRIM_TTL_HOURS``, or the drawdown eased below ``drawdown_trim_pct``) with nothing trimmed
    ends its episode, so the next breach opens a new offer with a new id (spec §22, final review
    I-A); a trimmed episode stays until a human reset."""
    t = totals(vs)
    held = {s: n.filled for s, n in t.names.items() if n.filled > 0}
    if any(snap.marks.get(s, 0.0) <= 0.0 for s in held):
        log.warning("value book: a held name has no mark; the drawdown reading waits")
        return None
    value = sum(q * snap.marks[s] for s, q in held.items())
    state = book_state(vs, "high_water") or {"high": 0.0, "stop": False}
    high = max(float(state.get("high", 0.0)), value)
    stop = bool(state.get("stop")) or (
        high > 0 and (high - value) / high * 100.0 >= cfg.book.drawdown_stop_pct
    )
    trim = high > 0 and (high - value) / high * 100.0 >= cfg.book.drawdown_trim_pct
    episode = {k: state[k] for k in TRIM_STATE_KEYS if k in state}
    if (
        episode.get("trim_offered_at")
        and not episode.get("trimmed")
        and trim_offer_stale(
            {**state, "high": high, "value": value}, cfg.book.drawdown_trim_pct, now
        )
    ):
        episode = {}  # the old card is dead; the high, the stop latch and `trimmed` are untouched
    offered: str | None = None
    if trim and not episode.get("trim_offered_at"):
        offered = trim_episode(high, now)
        episode |= {"trim_offered_at": now.isoformat(), "episode": offered}
    set_state(vs, "high_water", {"high": high, "value": value, "stop": stop, **episode}, now)
    return offered


async def _sell(
    session: SessionFactory,
    broker: ValueBroker,
    snap: Snapshot,
    pid: int,
    symbol: str,
    list_name: str,
    shares: float,
    reason: str,
    cfg: ValueCfg,
    now: datetime,
) -> list[str]:
    with session() as vs:
        held = totals(vs).names.get(symbol)
        cap = value_sell_cap(
            held.filled if held else 0.0,
            snap.shares.get(symbol, 0.0),
            snap.wheel_short_calls.get(symbol, 0),
        )
        prop = vs.get(ValueProposalRow, pid)
        assert prop is not None
        att = vs.get(ValueAttributionRow, symbol)
        if att is not None and att.state == "frozen" and prop.reason not in PYTHON_STOPS:
            return []  # frozen: only a stop or a thesis sale may send (spec §9.2); it waits
        qty = float(int(min(shares, cap)))
        if qty < 1:
            prop.status, prop.detail = "refused", "sell cap: no value share is free to sell"
            return [f"Value book: {symbol} sell refused, the sell cap leaves nothing (spec §9.2)"]
        prop.status = "sent"
    quote = await broker.quote(symbol)
    if quote is None:
        with session() as vs:
            prop = vs.get(ValueProposalRow, pid)
            assert prop is not None
            prop.status = "approved"  # try again next cycle
        return []
    order_id = await send_order(
        session,
        broker,
        symbol=symbol,
        list_name=list_name,
        side="sell",
        shares=qty,
        limit=quote.mid,
        reason=reason,
        proposal_id=pid,
        tranche=None,
        timeout=cfg.book.fill_timeout_seconds,
    )
    with session() as vs:
        order = vs.get(ValueOrderRow, order_id)
        prop = vs.get(ValueProposalRow, pid)
        assert order is not None and prop is not None
        return _finish_sell(vs, prop, order, now)


def _finish_sell(
    vs: Session, prop: ValueProposalRow, order: ValueOrderRow, now: datetime
) -> list[str]:
    symbol = prop.symbol
    prop.order_id = order.id
    if order.status in WORKING:
        return [
            f"Value book: {symbol} sell not confirmed cancelled; resolved from the broker next cycle"
        ]
    prop.status = "done" if order.filled > 0 else "approved"
    left = totals(vs).names.get(symbol)
    if left is not None and left.filled < 1:
        for pos in vs.scalars(
            select(ValuePositionRow).where(
                ValuePositionRow.symbol == symbol, ValuePositionRow.status == "open"
            )
        ):
            pos.status, pos.closed_on = "closed", now.date()
    return [f"Value book: sold {order.filled:g} {symbol} ({prop.reason}) at {order.avg_price}"]


async def _buy(
    session: SessionFactory,
    broker: ValueBroker,
    snap: Snapshot,
    pid: int,
    *,
    cfg: ValueCfg,
    portfolio: dict,
    now: datetime,
    halted: bool,
    is_live: bool,
    trend_brake: bool,
) -> list[str]:
    with session() as vs:
        prop = vs.get(ValueProposalRow, pid)
        assert prop is not None
        symbol, list_name, shares, tranche = prop.symbol, prop.list_name, prop.shares, prop.tranche
    quote = await broker.quote(symbol)
    if quote is None:
        return []
    with session() as vs:
        prop = vs.get(ValueProposalRow, pid)
        assert prop is not None
        peak = book_state(vs, "high_water") or {}
        ctx = buy_context(
            vs,
            symbol=symbol,
            list_name=list_name,
            shares=int(shares),
            price=quote.ask,
            snapshot=snap,
            cfg=cfg,
            portfolio=portfolio,
            today=now.date(),
            halted=halted,
            is_live=is_live,
            trend_brake=trend_brake,
            drawdown_stop=bool(peak.get("stop")),
            exclude_proposal=pid,
            quote_age_seconds=quote.age_seconds,
        )
        reasons = ["no_effective_verdict"] if ctx is None else _gate(ctx, cfg, portfolio)
        if (
            ctx is not None
            and "data_unreliable" in reasons
            and ctx.data_quality == "pass"
            and prop.needs_tap
            and prop.decided_by not in (None, "system")
        ):
            # The night made this a tap-only proposal precisely because the margin of safety is
            # above the review line (data quality itself passes); a human has tapped it, so the
            # send-time gate may not refuse it for the reason the tap was asked for (ruling 10).
            reasons = [r for r in reasons if r != "data_unreliable"]
        prop.gate_json = json.dumps(reasons)
        if reasons and ctx is not None and fundable_only(reasons) and cfg.book.release.enabled:
            msg = _fund(vs, prop, ctx, cfg, portfolio, now)
            return [msg] if msg else []
        if reasons:
            prop.status, prop.detail = "refused", ",".join(reasons)
            for req in vs.scalars(
                select(ValueFundingRow).where(
                    ValueFundingRow.proposal_id == pid, ValueFundingRow.status == "open"
                )
            ):
                req.status, req.closed_at, req.detail = "lapsed", now, "the buy was refused"
            return [f"Value book: {symbol} buy refused at send time: {', '.join(reasons)}"]
        prop.status = "sent"
    order_id = await send_order(
        session,
        broker,
        symbol=symbol,
        list_name=list_name,
        side="buy",
        shares=shares,
        limit=quote.mid,
        reason=f"tranche {tranche}",
        proposal_id=pid,
        tranche=tranche,
        timeout=cfg.book.fill_timeout_seconds,
    )
    with session() as vs:
        order = vs.get(ValueOrderRow, order_id)
        prop = vs.get(ValueProposalRow, pid)
        assert order is not None and prop is not None
        return _finish_buy(vs, prop, order, cfg, now)


def _finish_buy(
    vs: Session, prop: ValueProposalRow, order: ValueOrderRow, cfg: ValueCfg, now: datetime
) -> list[str]:
    """A buy's order is over: settle the proposal, its funding request and the position. Also the
    end of a recovered order (``resolve_working_orders``). An order the broker has not confirmed
    cancelled is not over: the proposal stays ``sent`` until the next cycle resolves it."""
    symbol, list_name = prop.symbol, prop.list_name
    prop.order_id = order.id
    if order.status in WORKING:
        return [
            f"Value book: {symbol} buy not confirmed cancelled; resolved from the broker next cycle"
        ]
    prop.status = "done" if order.filled > 0 else "expired"
    # funded only by the buy's FILL: a limit that misses leaves the request lapsed, so the
    # cooldown holds and the freed cash is not asked for again at once (review I-4)
    for req in vs.scalars(
        select(ValueFundingRow).where(
            ValueFundingRow.proposal_id == prop.id, ValueFundingRow.status == "open"
        )
    ):
        req.status, req.closed_at = ("funded" if order.filled > 0 else "lapsed"), now
        if order.filled <= 0:
            req.detail = "the buy did not fill"
    if order.filled <= 0:
        return [f"Value book: {symbol} buy did not fill; the proposal is closed"]
    card = _card(vs, symbol)
    eff = vs.get(ValueEffectiveRow, (symbol, list_name))
    ev = card.lists.get(list_name) if card else None
    open_position(
        vs,
        order,
        day=now.date(),
        atr14=None,
        fair_value=ev.fair_value if ev else None,
        effective_fair_value=eff.fair_value if eff else None,
        fv_accn=card.fingerprint.latest_accn if card else None,
        cfg=cfg,
        decided_by=eff.decided_by if eff else "python",
    )
    return [f"Value book: bought {order.filled:g} {symbol} at {order.avg_price} ({list_name})"]


def _fund(
    vs: Session,
    prop: ValueProposalRow,
    ctx: BuyContext,
    cfg: ValueCfg,
    portfolio: dict,
    now: datetime,
) -> str | None:
    """A buy short only of cash: open (or keep) its funding request for the shortfall. The
    cooldown keeps a name whose request lapsed from asking again at once (no churn).

    The shortfall is recomputed from the fresh account every cycle (``ctx.gross_used`` was built
    from this cycle's broker snapshot) and overwrites the stored ``needed_usd``: it is never the
    old figure less the closes made since, because those closes are already out of the snapshot's
    CSP collateral. Subtracting them again would count the same freed dollars twice. ``as_of``
    records which cycle wrote the figure: the wheel subtracts only closes made after it, and
    stops serving a request whose ``as_of`` has gone stale (this process is not running)."""
    room = ctx.net_liq * float(portfolio.get("max_gross_notional_pct", 100.0)) / 100.0
    needed = round(ctx.cost - (room - ctx.gross_used), 2)
    prop.status = "funding"
    open_req = vs.scalars(
        select(ValueFundingRow).where(
            ValueFundingRow.proposal_id == prop.id, ValueFundingRow.status == "open"
        )
    ).first()
    if open_req is not None:
        open_req.needed_usd, open_req.as_of = needed, now
        return None
    cool = now - timedelta(days=cfg.book.release.cooldown_days)
    lapsed = vs.scalars(
        select(ValueFundingRow).where(
            ValueFundingRow.symbol == prop.symbol,
            ValueFundingRow.status == "lapsed",
            ValueFundingRow.closed_at >= cool,
        )
    ).first()
    if lapsed is not None:
        prop.status, prop.detail = "refused", "a funding request for this name lapsed recently"
        return f"Value book: {prop.symbol} not funded (cooldown after a lapsed request)"
    vs.add(
        ValueFundingRow(
            proposal_id=prop.id,
            symbol=prop.symbol,
            needed_usd=needed,
            status="open",
            created_at=now,
            expires_at=now + timedelta(hours=cfg.book.release.request_ttl_hours),
            as_of=now,
        )
    )
    return f"Value book: {prop.symbol} needs ${needed:,.0f} released (capital release requested)"


def hourly_check(
    vs: Session,
    snap: Snapshot,
    last_close: dict[str, float],
    major_8k: set[str],
    *,
    cfg: ValueCfg,
    now: datetime,
    ruleset_version: str,
    ruleset_hash: str,
) -> list[str]:
    """Spec §7.1 for held names during RTH: a raw move past ``raw_move_pct`` against the last
    close, or a Major 8-K filed today, opens a held re-evaluation (adds pause) and queues Claude's
    review. Levels wait for the close: nothing here moves a stop or sells."""
    opened: list[str] = []
    for pos in vs.scalars(select(ValuePositionRow).where(ValuePositionRow.status == "open")):
        mark, close = snap.marks.get(pos.symbol), last_close.get(pos.symbol)
        move = None if not mark or not close else mark / close - 1.0
        big = move is not None and abs(move) * 100.0 >= cfg.rules.reevaluation.raw_move_pct
        if not big and pos.symbol not in major_8k:
            continue
        today = now.date()
        seen = vs.scalars(
            select(ValueReevaluationRow).where(
                ValueReevaluationRow.position_id == pos.id, ValueReevaluationRow.session == today
            )
        ).first()
        if seen is not None:
            continue
        kind = "move" if big else "filing"
        detail = f"raw move {move:+.1%} intraday" if big and move is not None else "Major 8-K"
        row = ValueReevaluationRow(
            shadow_id=0,
            position_id=pos.id,
            symbol=pos.symbol,
            list_name=pos.list_name,
            session=today,
            last_session=today,
            severity="major",
            triggers_json=json.dumps([{"day": today.isoformat(), "kind": kind, "detail": detail}]),
            plan_before_json=pos.plan_json or "{}",
            plan_after_json=pos.plan_json or "{}",
            verdict_at_entry="READY",
            ruleset_version=ruleset_version,
            ruleset_hash=ruleset_hash,
            created_at=now,
        )
        vs.add(row)
        vs.flush()
        if cfg.claude.enabled:
            queue_read(
                vs, pos.symbol, kind="review", reason="review", now=now, reevaluation_id=row.id
            )
        opened.append(pos.symbol)
    return opened


def mirror_reevaluations(vs: Session, day: date, now: datetime) -> int:
    """Each night: a shadow entry's re-evaluation tonight (spec §7.1's full trigger set, any
    track) on a name and list the book holds opens or joins that position's held re-evaluation,
    so adds pause and Claude's review is queued as for the hourly check."""
    n = 0
    for pos in vs.scalars(select(ValuePositionRow).where(ValuePositionRow.status == "open")):
        shadow_rows = vs.scalars(
            select(ValueReevaluationRow).where(
                ValueReevaluationRow.symbol == pos.symbol,
                ValueReevaluationRow.list_name == pos.list_name,
                ValueReevaluationRow.shadow_id > 0,
                ValueReevaluationRow.last_session == day,
            )
        ).all()
        if not shadow_rows:
            continue
        held = vs.scalars(
            select(ValueReevaluationRow).where(
                ValueReevaluationRow.position_id == pos.id,
                ValueReevaluationRow.last_session == day,
            )
        ).first()
        if held is not None:
            continue
        src = shadow_rows[0]
        row = ValueReevaluationRow(
            shadow_id=0,
            position_id=pos.id,
            symbol=pos.symbol,
            list_name=pos.list_name,
            session=day,
            last_session=day,
            severity=max((r.severity for r in shadow_rows), key=_SEVERITY_RANK.__getitem__),
            triggers_json=src.triggers_json,
            plan_before_json=pos.plan_json or "{}",
            plan_after_json=pos.plan_json or "{}",
            verdict_at_entry="READY",
            verdict_now=src.verdict_now,
            ruleset_version=src.ruleset_version,
            ruleset_hash=src.ruleset_hash,
            created_at=now,
        )
        vs.add(row)
        vs.flush()
        queue_read(vs, pos.symbol, kind="review", reason="review", now=now, reevaluation_id=row.id)
        n += 1
    return n


@dataclass(frozen=True)
class HeldInputs:
    """One held name's plain-data inputs to spec §7.1's triggers, built by the night (the same
    sources the shadow path reads): tonight's residual move, the filings since the last check,
    the report dates, the news volume, the regime step, the kill triggers near firing and the
    name's session dates (to count sessions since an open re-evaluation)."""

    move: Move | None = None
    filings: list[FilingEvent] = field(default_factory=list)
    earnings: list[date] = field(default_factory=list)
    news: NewsVolume | None = None
    regime_stepped: bool = False
    kill: list[str] = field(default_factory=list)
    sessions: list[date] = field(default_factory=list)
    verdict_now: str | None = None


def _sessions_between(opened: date, day: date, sessions: list[date]) -> int:
    """Sessions after *opened* up to and including *day*: counted on the name's bars, else on
    weekdays (a holiday makes the count one high, which only keeps a trigger out of the debounce)."""
    if sessions:
        return sum(1 for d in sessions if opened < d <= day)
    n, d = 0, opened
    while d < day:
        d += timedelta(days=1)
        n += d.weekday() < 5
    return n


def held_reevaluations(
    vs: Session,
    day: date,
    now: datetime,
    *,
    inputs: dict[str, HeldInputs],
    cfg: ValueCfg,
    ruleset_version: str,
    ruleset_hash: str,
) -> int:
    """Spec §7.1's whole trigger set for each open position with no open READY shadow entry on
    its name and list (the mirror covers the rest). A trigger opens, or joins within the debounce,
    the position's held re-evaluation and queues Claude's review of a new one. The plan is the
    position's own: no level and no stop moves here under the ``value`` policy (shock stops are
    ``full`` only). Returns the re-evaluations opened or extended."""
    rcfg = cfg.rules.reevaluation
    checked = dict(book_state(vs, "held_checked") or {})
    n = 0
    for pos in vs.scalars(select(ValuePositionRow).where(ValuePositionRow.status == "open")):
        covered = vs.scalars(
            select(ValueShadowRow.id).where(
                ValueShadowRow.symbol == pos.symbol,
                ValueShadowRow.list_name == pos.list_name,
                ValueShadowRow.status == "open",
                ValueShadowRow.kind == "ready",
            )
        ).first()
        if covered is not None:
            continue
        after = date.fromisoformat(checked.get(str(pos.id), pos.opened_on.isoformat()))
        checked[str(pos.id)] = day.isoformat()
        latest = vs.scalars(
            select(ValueReevaluationRow)
            .where(ValueReevaluationRow.position_id == pos.id)
            .order_by(ValueReevaluationRow.session.desc(), ValueReevaluationRow.id.desc())
            .limit(1)
        ).first()
        have = inputs.get(pos.symbol, HeldInputs())
        fired = reevaluate.session_triggers(
            day=day,
            after=after,
            move=have.move,
            filings=have.filings,
            earnings=have.earnings,
            news=have.news,
            regime_stepped=have.regime_stepped,
            last_reevaluation=latest.session if latest is not None else pos.opened_on,
            cfg=rcfg,
            kill=have.kill or None,
        )
        sev = reevaluate.severity(fired)
        if sev is None:
            continue
        items = [{"day": day.isoformat(), **t.model_dump()} for t in fired]
        since = None if latest is None else _sessions_between(latest.session, day, have.sessions)
        if latest is not None and reevaluate.joins(
            latest.severity,  # type: ignore[arg-type]
            since,
            sev,
            rcfg,
        ):
            latest.triggers_json = json.dumps([*json.loads(latest.triggers_json), *items])
            latest.last_session = day
            n += 1
            continue
        row = ValueReevaluationRow(
            shadow_id=0,
            position_id=pos.id,
            symbol=pos.symbol,
            list_name=pos.list_name,
            session=day,
            last_session=day,
            severity=sev,
            triggers_json=json.dumps(items),
            plan_before_json=pos.plan_json or "{}",
            plan_after_json=pos.plan_json or "{}",
            verdict_at_entry="READY",
            verdict_now=have.verdict_now,
            ruleset_version=ruleset_version,
            ruleset_hash=ruleset_hash,
            created_at=now,
        )
        vs.add(row)
        vs.flush()
        queue_read(vs, pos.symbol, kind="review", reason="review", now=now, reevaluation_id=row.id)
        n += 1
    set_state(vs, "held_checked", checked, now)
    return n
