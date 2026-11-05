"""The spreads process: GEX map → price tape → exits → entries → end of day, on the ET clock.

Entries follow the amendment's rules (Design → "Entry rules borrowed from OPG"): the traded
index is sampled into a ``SessionTape`` every tick, and the traded chain is fetched only when
``tape.trigger`` allows a side (one side, against a stalled move). Every opened spread is stored
with its ``SpreadEntryContext`` tags, and each open spread's worst mark is recorded every tick,
so the trade log can be split by regime, side, trigger and gap day later.

``SpreadsService.tick()`` is one pass and owns every scheduling decision; ``run()`` is the
process loop around it (connect, reconcile, tick every ``manage_interval_seconds``, reconnect
after a Gateway drop). Exits run whenever spreads are open, even with entries blocked — a halt
file, a reconcile mismatch, or a disconnect only ever stops NEW risk. Each phase is guarded so
one failing phase (a dropped socket mid-requote) never takes the others down.

In paper mode the broker is the truth for what can be closed: every tick re-reconciles
spreads.db with IBKR's positions (a local cache, so it is free) and keeps entries blocked
while they disagree or an opening order is still working; every close is capped at the
contracts the broker still holds, and none is sent while an earlier close order for the same
spread is still live. While the Gateway is down, ``while_disconnected`` keeps alerting about
open spreads — the "still open after the time stop" alert can't wait for a reconnect.

This is the only ``src/spreads`` module that may import ``src.ledger`` / ``src.storage``: in
paper mode it attaches the ledger's live commission-report hook so spreads fills land in the
trade ledger (``src/ledger`` dedupes by execId and tags them ``book="spreads"``).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Literal, Protocol

from src.common.config import Config, SpreadsCfg, get_config
from src.common.market_hours import is_trading_day, next_session
from src.common.schemas import (
    ChainOption,
    ChainSnapshot,
    GexLevels,
    SessionSnapshot,
    SpreadBookStats,
    SpreadBriefRequest,
    SpreadBriefResult,
    SpreadCandidate,
    SpreadDayPlan,
    SpreadEntryContext,
    SpreadExitRules,
    SpreadLlmCall,
    SpreadMarketSnapshot,
    SpreadMenuItem,
    SpreadMenuPosition,
    SpreadPick,
    SpreadPickRequest,
    SpreadPickSnapshot,
    SpreadPosition,
    SpreadRiskContext,
    SpreadSide,
    SpreadTapeStats,
    SpreadTrigger,
    SpreadVerdict,
)
from src.spreads import store
from src.spreads.executor import UNRESOLVED, FillResult, SpreadExecutor, close_ref
from src.spreads.gex import build_levels, expected_move, regime_at
from src.spreads.manager import debit_to_close, evaluate_exit, intrinsic_debit, reconcile
from src.spreads.menu import build_menu, round_trip_cost
from src.spreads.notify import (
    DayCard,
    SpreadsNotifier,
    entry_card_line,
    exit_card_line,
    fmt_alert,
    fmt_books,
    fmt_day_card,
    fmt_entry,
    fmt_eod,
    fmt_exit,
    fmt_pick,
    status_nothing_to_sell,
)
from src.spreads.pricing import ET, day_schedule
from src.spreads.report import compute_stats
from src.spreads.risk import validate
from src.spreads.selector import refresh_candidate, select_candidates, select_menu, why_nothing
from src.spreads.tape import SessionTape, trigger

log = logging.getLogger(__name__)

_MAP_RETRY = timedelta(minutes=5)
_CARD_BEAT = timedelta(minutes=5)  # the day card's clock moves at least this often while live


class Broker(Protocol):
    async def fetch_chain(
        self,
        *,
        symbol: str,
        trading_class: str,
        exchange: str,
        expiries: int,
        band_pct: float,
        spot_hint: float | None = None,
        sec_type: str = "IND",
    ) -> ChainSnapshot | None: ...
    async def requote(self, legs: list[ChainOption]) -> list[ChainOption]: ...
    async def spot(self) -> float | None: ...
    async def session_quote(self) -> SessionSnapshot | None: ...
    async def excess_liquidity(self) -> float | None: ...
    def broker_legs(self) -> dict[int, float]: ...
    def working_refs(self) -> set[str]: ...


class Executor(Protocol):
    async def open(
        self,
        c: SpreadCandidate,
        contracts: int,
        recheck: Callable[[SpreadCandidate], SpreadVerdict],
    ) -> FillResult: ...
    async def close(
        self,
        pos: SpreadPosition,
        short_q: ChainOption | None,
        long_q: ChainOption | None,
        *,
        urgent: bool,
    ) -> FillResult: ...


class Notifier(Protocol):
    async def send(self, text: str) -> int | None: ...  # Telegram HTML; the message id

    async def edit(self, message_id: int, text: str) -> bool: ...


class Picker(Protocol):
    """Chooses from the gate-approved menu (src/spreads_ai/picker.py::ClaudePicker, wired in
    by scripts/run_spreads.py). Must never raise; the service still guards every call."""

    async def brief(self, req: SpreadBriefRequest) -> SpreadBriefResult: ...
    async def pick(self, req: SpreadPickRequest) -> SpreadPick: ...


# Builds the picker for run(); supplied by scripts/run_spreads.py so this package never imports
# src.spreads_ai.
PickerFactory = Callable[[Config], Picker]


# A baseline-book spread is the same spread as the main book's under another id: spread_id is
# unique in spread_positions, and both books may hold the baseline strike at once.
BASELINE_SUFFIX = "-BL"

# How long past ai.pick_timeout_seconds the service waits before giving up on a pick itself —
# the picker's own CLI timeout normally answers first; this is the backstop.
_PICK_GRACE_SECONDS = 30.0


@dataclass
class _PendingPick:
    """A pick in flight: the menu and the world as the main book's gate saw them."""

    task: asyncio.Task[SpreadPick]
    started: datetime
    episode: str
    menu: list[SpreadMenuItem]
    levels: GexLevels
    gex_chain: ChainSnapshot
    snapshot: SpreadPickSnapshot


def _right(side: str) -> Literal["C", "P"]:
    return "P" if side == "put" else "C"


class SpreadsService:
    def __init__(
        self,
        broker: Broker,
        executor: Executor,
        notifier: Notifier,
        cfg: SpreadsCfg,
        *,
        halt_path: Path,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        picker: Picker | None = None,
        baseline_executor: Executor | None = None,
    ) -> None:
        self.broker = broker
        self.executor = executor
        self.notifier = notifier
        self.cfg = cfg
        self.halt_path = halt_path
        self.now = now
        self.gex_chain: ChainSnapshot | None = None
        self.levels: GexLevels | None = None
        self.tape: SessionTape | None = None
        self.map_at: datetime | None = None
        self.map_failed_at: datetime | None = None
        self.last_entry_check: datetime | None = None
        self.last_spot: float | None = None
        self.entries_blocked: str | None = None
        self.eod_sent_for: date | None = None
        self._alerted: set[tuple[date, str]] = set()
        self.map_down_since: datetime | None = None  # start of the current map outage
        self._mismatch_ticks = 0
        self.picker = picker
        # The baseline book (ai.enabled): always the deterministic pick, always simulated —
        # a shadow-mode executor never touches IBKR, so it needs no ib handle.
        self.baseline_executor: Executor | None = None
        if picker is not None:
            self.baseline_executor = baseline_executor or SpreadExecutor(
                None, broker, cfg.model_copy(update={"mode": "shadow"}), now=now
            )
        self._pending: _PendingPick | None = None
        self._brief_task: asyncio.Task[SpreadBriefResult] | None = None
        self._brief_day: date | None = None
        self._card: DayCard | None = None  # the day's edited-in-place card (notify.py)

    @property
    def books(self) -> list[tuple[str, Executor]]:
        """(mode, executor) per book: the main book, plus the baseline book when Claude picks."""
        out: list[tuple[str, Executor]] = [(self.cfg.mode, self.executor)]
        if self.baseline_executor is not None:
            out.append(("baseline", self.baseline_executor))
        return out

    # ------------------------------------------------------------------ lifecycle

    async def start(self) -> None:
        """Reconcile open paper spreads with the broker; block entries on any mismatch."""
        mode = self.cfg.mode
        problems: list[str] = []
        if mode == "paper":
            expected = store.open_positions(mode) + store.expiring_positions(mode)
            problems = reconcile(expected, self.broker.broker_legs())
        if problems:
            self.entries_blocked = "reconcile: " + "; ".join(problems)
            await self._alert_mismatch(problems)
        else:
            self.entries_blocked = None
        log.info("spreads service started (mode=%s, blocked=%s)", mode, self.entries_blocked)

    def on_disconnect(self) -> None:
        self.entries_blocked = "disconnected"

    async def while_disconnected(self) -> None:
        """Called by ``run()`` on every pass the Gateway is down: exits can't run, so say so."""
        self.on_disconnect()
        mode = self.cfg.mode
        held = store.open_positions(mode) + store.expiring_positions(mode)
        if not held:
            return
        et = self.now().astimezone(ET)
        await self.alert_once(
            "disconnected_open",
            f"[SPREADS] IB Gateway is disconnected with {len(held)} {mode} spread(s) open — "
            "exits are paused until it reconnects",
        )
        force_close = day_schedule(self.cfg.schedule, et.date()).force_close
        if (
            is_trading_day(et.date())
            and et.strftime("%H:%M") >= force_close
            and not self.cfg.exits.let_expire
        ):
            await self.alert_once(
                "disconnected_after_time_stop",
                f"[SPREADS] URGENT: {len(held)} {self.cfg.underlying} spread(s) still open past "
                f"the {force_close} ET time stop and the Gateway is down — close them by hand "
                "in TWS before the bell or risk assignment",
            )

    async def _check_broker(self) -> None:
        """Paper only: re-reconcile every tick and hold entries while broker and DB disagree."""
        if self.cfg.mode != "paper" or self.entries_blocked == "disconnected":
            return
        mode = self.cfg.mode
        problems = reconcile(
            store.open_positions(mode) + store.expiring_positions(mode), self.broker.broker_legs()
        )
        opening = sorted(r for r in self.broker.working_refs() if not r.endswith(":X"))
        if opening:
            problems.append("opening order(s) still working: " + ", ".join(opening))
        if problems:
            self.entries_blocked = "reconcile: " + "; ".join(problems)
            self._mismatch_ticks += 1
            log.warning("spreads: entries blocked — %s", "; ".join(problems))
            if self._mismatch_ticks >= 2:  # one tick of fill-to-position lag is normal
                await self._alert_mismatch(problems)
            return
        self._mismatch_ticks = 0
        if self.entries_blocked is not None:
            log.info("spreads: broker and spreads.db agree again — entries unblocked")
            self.entries_blocked = None

    async def _alert_mismatch(self, problems: list[str]) -> None:
        """Once per day per distinct set of problems: a second, different mismatch the same day
        is news, the same one seen again on every tick is not."""
        await self.alert_once(
            "reconcile:" + "|".join(sorted(problems)),
            "[SPREADS] entries blocked — broker and spreads.db disagree:\n" + "\n".join(problems),
        )

    def _broker_holdings(self, positions: list[SpreadPosition]) -> dict[str, int]:
        """Contracts of each spread the broker still holds, as a cap on what a close may send.

        When the broker's legs match the book exactly, every spread is held in full. That has
        to be decided on the whole book first: IBKR nets a conId two spreads share in opposite
        directions (A short 679 / long 674, B short 674 / long 669 → no 674 line at all), so a
        per-leg count would find neither spread held and never close either. Only when the book
        and the broker disagree are legs allocated in DB order, which can under-allocate (and
        alert) but never lets two spreads claim the same contracts."""
        legs = self.broker.broker_legs()
        if not reconcile(positions, legs):
            return {p.spread_id: p.contracts for p in positions}
        remaining = dict(legs)
        held: dict[str, int] = {}
        for p in positions:
            if p.short_con_id is None or p.long_con_id is None:
                held[p.spread_id] = 0
                continue
            short_held = max(0.0, -remaining.get(p.short_con_id, 0.0))
            long_held = max(0.0, remaining.get(p.long_con_id, 0.0))
            n = int(min(p.contracts, short_held, long_held))
            remaining[p.short_con_id] = remaining.get(p.short_con_id, 0.0) + n
            remaining[p.long_con_id] = remaining.get(p.long_con_id, 0.0) - n
            held[p.spread_id] = n
        return held

    @staticmethod
    def _not_held_text(p: SpreadPosition, qty: int, legs: dict[int, float]) -> str:
        """The operator's next step depends on what the broker still shows: a leg that is
        still there is live risk to close in TWS, not a spread to mark settled."""
        shown = [c for c in (p.short_con_id, p.long_con_id) if c and legs.get(c, 0.0)]
        if not shown:
            return (
                f"[SPREADS] the broker shows neither leg of {p.spread_id} — if it was closed or "
                "settled outside the service, record that with python -m scripts.spreads_resolve"
            )
        return (
            f"[SPREADS] the broker does not hold all of {p.spread_id}: closing {qty} of "
            f"{p.contracts} contract(s). A leg is still at IBKR — check the position in TWS "
            "and close the rest by hand; do not mark it settled while a leg is live"
        )

    async def _after_order(self, spread_id: str, kind: str, result: FillResult) -> None:
        """Block entries on an order that may still be live; flag a fill whose price surprised."""
        reason = result.reason or ""
        if reason in UNRESOLVED:
            self.entries_blocked = f"{kind} order {result.order_ref}: {reason}"
            await self.alert_once(
                f"unresolved:{result.order_ref}",
                f"[SPREADS] the {kind} order for {spread_id} may still be live at IBKR ({reason}) "
                "— entries blocked until the broker shows it gone",
            )
        elif reason.startswith("check_fill") and result.filled_qty > 0:
            await self.alert_once(
                f"check_fill:{result.order_ref}",
                f"[SPREADS] {spread_id} {kind} filled at {result.price} but {reason} — check the "
                "fill in TWS (the combo price sign is not yet verified, plan Task 11 Step 9)",
            )

    async def alert_once(self, key: str, text: str) -> None:
        mark = (self.now().astimezone(ET).date(), key)
        if mark in self._alerted:
            return
        self._alerted.add(mark)
        await self.notifier.send(fmt_alert(text))

    def _card_for(self, now: datetime) -> DayCard:
        """Today's day card, started fresh on the first call of an ET day."""
        day = now.astimezone(ET).date()
        if self._card is None or self._card.day != day:
            self._card = DayCard(
                day=day,
                mode=self.cfg.mode,
                underlying=self.cfg.underlying,
                map_retry_min=int(_MAP_RETRY.total_seconds() // 60),
            )
        return self._card

    async def _card_update(self, now: datetime, **changes: Any) -> None:
        """Apply *changes* to today's day card and show it: the first update of an ET day posts
        the card, later ones edit it in place (a refused edit posts a fresh one). Never raises."""
        try:
            card = self._card_for(now)
            for k, v in changes.items():
                setattr(card, k, v)
            card.updated_at = now
            text = fmt_day_card(card)
            if card.message_id is not None and await self.notifier.edit(card.message_id, text):
                return
            card.message_id = await self.notifier.send(text)
        except Exception:
            log.exception("spreads: day card update failed")

    async def _guard(self, phase: str, work: Awaitable[None]) -> None:
        try:
            await work
        except Exception:
            log.exception("spreads %s phase failed", phase)
            await self.alert_once(
                phase, f"[SPREADS] the {phase} phase failed — see logs/spreads.log"
            )

    # ------------------------------------------------------------------ the pass

    async def tick(self) -> None:
        now = self.now()
        et = now.astimezone(ET)
        today = et.date()
        if not is_trading_day(today):
            return
        hhmm = et.strftime("%H:%M")
        s = day_schedule(self.cfg.schedule, today)
        await self._guard("broker", self._check_broker())
        if self._map_due(now, hhmm):
            await self._guard("map", self._build_map(now))
        if s.map_time <= hhmm < s.force_close:
            await self._guard("tape", self._sample(now))
        await self._manage(now)
        if self.picker is not None:
            await self._guard("brief", self._brief(now))
            if self._pending is not None:
                await self._guard("pick", self._resolve_pick(now))
        if s.entry_start <= hhmm < s.entry_end:
            await self._guard("entries", self._entries(now))
        await self._guard("card", self._heartbeat(now, hhmm, s))
        if hhmm >= s.eod_summary and self.eod_sent_for != today:
            await self._guard("eod", self._eod(now))

    async def _heartbeat(self, now: datetime, hhmm: str, s: Any) -> None:
        """Keep the day card's clock moving while the session is live: one edit per `_CARD_BEAT`,
        so "is the map building, are trades being assessed" reads off the one message."""
        if not (s.map_time <= hhmm < s.force_close):
            return
        card = self._card_for(now)
        if hhmm < s.entry_start:
            card.watch_note = f"entry window opens {s.entry_start} ET"
        elif hhmm >= s.entry_end:
            card.watch_note = "entry window closed, managing open spreads"
        if card.updated_at is None or now - card.updated_at >= _CARD_BEAT:
            await self._card_update(now)

    def _watch(self, now: datetime, note: str) -> None:
        self._card_for(now).watch_note = note

    def _map_due(self, now: datetime, hhmm: str) -> bool:
        s = day_schedule(self.cfg.schedule, now.astimezone(ET).date())
        if not (s.map_time <= hhmm < s.force_close):
            return False
        if self.map_failed_at is not None and now - self.map_failed_at < _MAP_RETRY:
            return False
        if self.map_at is None or self.map_at.astimezone(ET).date() != now.astimezone(ET).date():
            return True
        return now - self.map_at >= timedelta(minutes=s.map_refresh_minutes)

    def _entry_due(self, now: datetime) -> bool:
        if self.last_entry_check is None:
            return True
        return now - self.last_entry_check >= timedelta(
            minutes=self.cfg.schedule.entry_check_minutes
        )

    async def _traded_chain(self, spot_hint: float | None = None) -> ChainSnapshot | None:
        return await self.broker.fetch_chain(
            symbol=self.cfg.underlying,
            trading_class=self.cfg.trading_class,
            exchange=self.cfg.exchange,
            expiries=1,
            band_pct=self.cfg.selection.strike_band_pct,
            spot_hint=spot_hint,
            sec_type=self.cfg.underlying_sec_type,
        )

    async def _build_map(self, now: datetime) -> None:
        g = self.cfg.gex
        gex_chain = await self.broker.fetch_chain(
            symbol=g.symbol,
            trading_class=g.trading_class,
            exchange=g.exchange,
            expiries=g.expiries,
            band_pct=g.strike_band_pct,
            sec_type=g.sec_type,
        )
        traded = await self._traded_chain()
        if gex_chain is None or traded is None:
            self.map_failed_at = now
            self.levels = None
            self.map_down_since = self.map_down_since or now
            await self._card_update(
                now,
                map_failed_since=self.map_down_since,
                map_error="no chain or index price",
            )
            return
        try:
            # The gamma-flip search is scipy-heavy: keep it off the loop so the heartbeat runs.
            levels = await asyncio.to_thread(build_levels, gex_chain, traded, self.cfg, now)
        except Exception:
            # Never trade on the previous map for another hour: no map, no entries, retry soon.
            self.levels = None
            self.map_failed_at = now
            self.map_down_since = self.map_down_since or now
            await self._card_update(
                now, map_failed_since=self.map_down_since, map_error="the map build raised"
            )
            raise
        self.map_failed_at = None
        self.map_down_since = None
        self.map_at = now
        self.gex_chain = gex_chain
        self.levels = levels
        store.record_map(self.levels)
        tape = self._tape_for(now)
        if tape.day_em is None:
            # The day's FIRST expected move, from spreads.db: a restart must not swap in the
            # smaller straddle it sees later in the day.
            tape.day_em = store.first_map_em(now.astimezone(ET).date())
        card = self._card_for(now)
        await self._card_update(
            now,
            levels=self.levels,
            map_at=now,
            map_builds=card.map_builds + 1,
            map_failed_since=None,
            map_error=None,
        )

    def _tape_for(self, now: datetime) -> SessionTape:
        today = now.astimezone(ET).date()
        if self.tape is None or self.tape.day != today:
            self.tape = SessionTape(day=today, day_em=store.first_map_em(today))
        return self.tape

    async def _sample(self, now: datetime) -> None:
        snap = await self.broker.session_quote()
        if snap is None:
            return  # the tape goes stale and the trigger stops arming (max_tape_age_seconds)
        self._tape_for(now).observe(snap)

    def _context(
        self, now: datetime, levels: GexLevels, excess: float | None, mode: str | None = None
    ) -> SpreadRiskContext:
        mode = mode or self.cfg.mode
        today = now.astimezone(ET).date()
        trades, realized = store.day_stats(today, mode)
        open_count = len(store.open_positions(mode)) + len(store.expiring_positions(mode))
        return SpreadRiskContext(
            now=now,
            levels=levels,
            open_spreads=open_count,
            open_risk_usd=store.open_risk_usd(mode),
            trades_today=trades,
            realized_pnl_today_usd=realized,
            excess_liquidity_usd=excess,
            capital_usd=self.capital(mode),
            sides_today=store.sides_opened(today, mode),  # type: ignore[arg-type]
        )

    def capital(self, mode: str | None = None) -> float:
        """A book's sizing capital: starting capital plus everything that book has realized."""
        return self.cfg.risk.starting_capital_usd + store.realized_pnl_total(mode or self.cfg.mode)

    def _entry_context(
        self, side: SpreadSide, levels: GexLevels, now: datetime
    ) -> SpreadEntryContext:
        tape = self.tape
        gap = tape.gap_pct() if tape is not None else None
        bell = datetime.combine(now.astimezone(ET).date(), time(9, 30), tzinfo=ET)
        return SpreadEntryContext(
            trigger=self.cfg.entry.trigger,
            move_em=tape.move_em(side) if tape is not None else None,
            gap_pct=gap,
            gap_day=gap is not None and abs(gap) >= self.cfg.entry.gap_day_pct,
            regime=levels.regime,
            net_gex=levels.net_gex,
            flip=levels.flip,
            call_wall=levels.call_wall,
            put_wall=levels.put_wall,
            expected_move=levels.expected_move,
            day_em=tape.day_em if tape is not None else None,
            spot=levels.spot,
            minutes_after_open=max(0, int((now - bell).total_seconds() // 60)),
        )

    async def _entries(self, now: datetime) -> None:
        if self._pending is not None:
            self._watch(now, "a pick is in flight")
            return  # one decision at a time: the pick in flight resolves first
        if self.entries_blocked:
            self._watch(now, f"entries blocked: {self.entries_blocked}")
            return
        if self.halt_path.exists():
            self._watch(now, "halt file present, no new entries")
            await self.alert_once(
                "halt", f"[SPREADS] halt file {self.halt_path} present — no new entries"
            )
            return
        if self.levels is None or self.gex_chain is None:
            self._watch(now, "no GEX map, not assessing")
            return
        allowed = trigger(self.tape, now, self.cfg)
        if not allowed.sides:
            log.debug("spreads trigger: %s (move %s)", allowed.reason, allowed.move_em)
            self._watch(now, f"waiting for the trigger ({allowed.reason})")
            return
        if not self._entry_due(now):
            return
        self.last_entry_check = now
        chain = await self._traded_chain(spot_hint=self.levels.spot)
        if chain is None:
            self._watch(now, "armed, but the traded chain did not load")
            return
        card = self._card_for(now)
        card.assessments += 1
        card.assessed_at = now
        self._watch(now, f"armed ({allowed.reason}), weighing candidates")
        today = now.astimezone(ET).date()
        levels = self.levels.model_copy(
            update={
                "as_of": now,
                "spot": chain.spot,
                "regime": regime_at(self.gex_chain, chain.spot, self.levels.scale, now),
                "expected_move": expected_move(
                    chain.options, chain.spot, today, self.cfg.selection.em_straddle_factor
                ),
            }
        )
        excess = await self.broker.excess_liquidity()
        gex_chain = self.gex_chain
        if self.picker is not None:
            await self._decide(now, chain, levels, excess, allowed)
            return
        cands = select_candidates(chain, levels, self.cfg, now, sides=allowed.sides)
        await self._nothing_to_sell(now, chain, levels, allowed, {c.side for c in cands})
        for cand in cands:
            # Validated on the clock it runs at, so the quote's age (chain.as_of) is real.
            verdict = validate(cand, self._context(self.now(), levels, excess), self.cfg)
            store.record_candidate(cand, verdict, levels.regime, now)
            if not verdict.approved:
                continue
            await self._open_candidate(
                cand,
                verdict.contracts,
                levels,
                excess,
                now,
                mode=self.cfg.mode,
                executor=self.executor,
                gex_chain=gex_chain,
            )
            if self.entries_blocked:
                return

    async def _nothing_to_sell(
        self,
        now: datetime,
        chain: ChainSnapshot,
        levels: GexLevels,
        allowed: SpreadTrigger,
        offered: set[str],
    ) -> None:
        """An armed check that found no strike to sell on a side says why: in the log every
        time, and on the day card's status line (edited in place, 2026-10-14 — it used to post
        a message per side per day)."""
        statuses: list[str] = []
        for side in allowed.sides:
            if side in offered or side not in self.cfg.selection.sides:
                continue
            why = why_nothing(side, chain, levels, self.cfg, now)
            log.info("spreads: %s armed (%s), nothing to sell — %s", side, allowed.reason, why)
            statuses.append(status_nothing_to_sell(side, why))
        if statuses:
            checks = self._card.checks + 1 if self._card is not None else 1
            await self._card_update(now, status=" · ".join(statuses), status_at=now, checks=checks)

    async def _open_candidate(
        self,
        cand: SpreadCandidate,
        contracts: int,
        levels: GexLevels,
        excess: float | None,
        now: datetime,
        *,
        mode: str,
        executor: Executor,
        gex_chain: ChainSnapshot,
        pick_id: int | None = None,
        episode_key: str | None = None,
    ) -> tuple[SpreadPosition | None, str | None]:
        """Send one approved spread through *executor* (whose paper path re-gates it on fresh
        quotes against *mode*'s book) and record it. Returns (position, why not filled)."""

        def recheck(fresh: SpreadCandidate) -> SpreadVerdict:
            at = self.now()
            moved = levels.model_copy(
                update={
                    "spot": fresh.spot,
                    "regime": regime_at(gex_chain, fresh.spot, levels.scale, at),
                }
            )
            return validate(fresh, self._context(at, moved, excess, mode), self.cfg)

        result = await executor.open(cand, contracts, recheck)
        store.record_order(
            spread_id=cand.spread_id,
            kind="open",
            order_ref=result.order_ref,
            ib_order_id=result.ib_order_id,
            perm_id=result.perm_id,
            filled_qty=result.filled_qty,
            price=result.price,
            commission=result.commission,
            reason=result.reason,
            now=now,
        )
        await self._after_order(cand.spread_id, "open", result)
        if result.filled_qty < 1 or result.price is None:
            log.info("spreads entry %s not filled: %s", cand.spread_id, result.reason)
            return None, result.reason or "not_filled"
        tags = self._entry_context(cand.side, levels, now)
        pos = store.open_position(
            cand,
            mode=mode,
            contracts=result.filled_qty,
            credit=result.price,
            commission=result.commission,
            now=now,
            perm_id=result.perm_id,
            context=tags,
            pick_id=pick_id,
            episode_key=episode_key,
        )
        await self.notifier.send(fmt_entry(pos, mode, tags))
        if mode == self.cfg.mode:
            await self._card_trade(now, entry_card_line(pos), status=f"opened {pos.spread_id}")
        return pos, None

    async def _card_trade(self, now: datetime, line: str, *, status: str) -> None:
        trades = [*(self._card.trades if self._card is not None else []), line]
        await self._card_update(now, trades=trades, status=status, status_at=now, checks=0)

    def _tape_stats(self, sides: list[SpreadSide], now: datetime) -> SpreadTapeStats:
        t = self.tape
        if t is None:
            return SpreadTapeStats()
        side = sides[0] if len(sides) == 1 else None
        at = t.extreme_at(side) if side is not None else None
        return SpreadTapeStats(
            prior_close=t.prior_close,
            open=t.open,
            high=t.high,
            low=t.low,
            last=t.last,
            high_at=t.high_at,
            low_at=t.low_at,
            move_em=t.move_em(side) if side is not None else None,
            stall_minutes=(now - at).total_seconds() / 60.0 if at is not None else None,
            gap_pct=t.gap_pct(),
            day_em=t.day_em,
        )

    def _book_stats(self, mode: str) -> SpreadBookStats:
        s = compute_stats([pnl for _, _, pnl in store.closed_results(mode)])
        return SpreadBookStats(
            mode=mode,
            closed_trades=s.n,
            win_rate=s.win_rate,
            breakeven_win_rate=s.breakeven_win_rate,
            expectancy_usd=s.expectancy,
            total_pnl_usd=s.total_pnl,
        )

    def _events_today(self, now: datetime) -> list[str]:
        et = now.astimezone(ET)
        out = []
        for ev in self.cfg.risk.events:
            if ev.day == et.date():
                when = "all day" if ev.until is None else f"until {ev.until} ET"
                out.append(f"{ev.label or 'event'} ({when})")
        return out

    def _ex_div_window(self, today: date) -> bool:
        exdiv = set(self.cfg.risk.ex_dividend_dates)
        return today in exdiv or next_session(today) in exdiv

    def _request_fields(
        self, now: datetime, levels: GexLevels, sides: list[SpreadSide]
    ) -> dict[str, Any]:
        today = now.astimezone(ET).date()
        ex = self.cfg.exits
        return {
            "now": now,
            "levels": levels,
            "tape": self._tape_stats(sides, now),
            "events": self._events_today(now),
            "ex_dividend_window": self._ex_div_window(today),
            "exits": SpreadExitRules(
                profit_take_pct=ex.profit_take_pct,
                stop_debit_multiple=ex.stop_debit_multiple,
                close_on_short_strike_touch=ex.close_on_short_strike_touch,
                max_hold_minutes=ex.max_hold_minutes,
                force_close=day_schedule(self.cfg.schedule, today).force_close,
            ),
            "books": [self._book_stats(m) for m, _ in self.books],
        }

    def _snapshot(
        self,
        levels: GexLevels,
        allowed: SpreadTrigger,
        now: datetime,
        plan: SpreadDayPlan | None,
    ) -> SpreadPickSnapshot:
        tape = self._tape_stats(allowed.sides, now)
        gap = tape.gap_pct
        return SpreadPickSnapshot(
            regime=levels.regime,
            flip_distance_pct=(levels.spot - levels.flip) / levels.spot if levels.flip else None,
            expected_move=levels.expected_move,
            move_em=allowed.move_em,
            stall_minutes=tape.stall_minutes,
            gap_pct=gap,
            gap_day=gap is not None and abs(gap) >= self.cfg.entry.gap_day_pct,
            side=",".join(allowed.sides),
            event_flag=bool(self._events_today(now)),
            plan_bias=plan.bias if plan is not None else None,
        )

    def _episode_key(self, allowed: SpreadTrigger, now: datetime) -> str:
        """One arming of the trigger: (ET day, side, the session extreme that armed it). The
        extreme comes from IBKR's session stats, so a restart rebuilds the same key. In
        ``always`` mode every entry check is its own episode."""
        et = now.astimezone(ET)
        t = self.tape
        if allowed.reason != "armed" or t is None or len(allowed.sides) != 1:
            return f"{et.date()}:{allowed.reason}:{et:%H%M}"
        side = allowed.sides[0]
        extreme = t.low if side == "put" else t.high
        return f"{et.date()}:{side}:{extreme:.2f}"

    async def _brief(self, now: datetime) -> None:
        """Once a day, after the first map: Claude's day plan, without blocking the tick."""
        assert self.picker is not None
        today = now.astimezone(ET).date()
        if self._brief_task is not None:
            if not self._brief_task.done():
                return
            task, self._brief_task = self._brief_task, None
            try:
                result = task.result()
            except (Exception, asyncio.CancelledError):
                log.exception("spreads: the morning brief raised")
                return
            store.record_day_plan(today, result, now)
            await self._card_update(now, plan=result)
            return
        if self.levels is None or self.map_at is None:
            return
        if self.map_at.astimezone(ET).date() != today or self._brief_day == today:
            return
        if store.day_plan_attempted(today):
            return
        self._brief_day = today
        request = SpreadBriefRequest(**self._request_fields(now, self.levels, []))
        self._brief_task = asyncio.create_task(self.picker.brief(request))

    async def _decide(
        self,
        now: datetime,
        chain: ChainSnapshot,
        levels: GexLevels,
        excess: float | None,
        allowed: SpreadTrigger,
    ) -> None:
        """ai.enabled: the baseline book takes the baseline item on its own gate; the main book
        hands the items ITS gate approved to the picker. At most one spread per episode each."""
        assert self.picker is not None and self.gex_chain is not None
        gex_chain = self.gex_chain
        episode = self._episode_key(allowed, now)
        main_ctx = self._context(self.now(), levels, excess)
        approved: list[tuple[SpreadCandidate, SpreadMenuPosition, int]] = []
        baseline_item: SpreadCandidate | None = None
        items = select_menu(chain, levels, self.cfg, now, sides=allowed.sides)
        await self._nothing_to_sell(now, chain, levels, allowed, {c.side for c, _ in items})
        for cand, position in items:
            verdict = validate(cand, main_ctx, self.cfg)
            store.record_candidate(cand, verdict, levels.regime, now)
            if position == "baseline" and baseline_item is None:
                baseline_item = cand
            if verdict.approved:
                approved.append((cand, position, verdict.contracts))
        if baseline_item is not None and store.episode_trade(episode, "baseline") is None:
            bl = baseline_item.model_copy(
                update={"spread_id": baseline_item.spread_id + BASELINE_SUFFIX}
            )
            v = validate(bl, self._context(self.now(), levels, excess, "baseline"), self.cfg)
            if v.approved and self.baseline_executor is not None:
                await self._open_candidate(
                    bl,
                    v.contracts,
                    levels,
                    excess,
                    now,
                    mode="baseline",
                    executor=self.baseline_executor,
                    gex_chain=gex_chain,
                    episode_key=episode,
                )
        if not approved or store.pick_exists(episode):
            return
        today = now.astimezone(ET).date()
        cap = self.cfg.ai.max_pick_calls_per_day
        if store.pick_calls_today(today) >= cap:
            await self.alert_once(
                "pick_cap",
                f"[SPREADS] {cap} pick calls used today — no more {self.cfg.mode} entries until "
                "tomorrow (the baseline book continues)",
            )
            return
        menu = build_menu(approved, levels, self.cfg)
        plan = store.day_plan(today)
        request = SpreadPickRequest(
            **self._request_fields(now, levels, allowed.sides),
            sides=allowed.sides,
            menu=menu,
            plan=plan,
            round_trip_cost_per_share=round_trip_cost(self.cfg),
        )
        self._pending = _PendingPick(
            task=asyncio.create_task(self.picker.pick(request)),
            # not the tick's start: a map refresh, manage requotes and the chain fetch may
            # already have used much of the grace before the task exists
            started=self.now(),
            episode=episode,
            menu=menu,
            levels=levels,
            gex_chain=gex_chain,
            snapshot=self._snapshot(levels, allowed, now, plan),
        )

    async def _fresh_candidate(
        self, c: SpreadCandidate
    ) -> tuple[SpreadCandidate | None, str | None]:
        """*c* repriced on fresh leg quotes and spot — the pick is up to 75 s old by now.
        Returns (candidate, None), or (None, why not): a send is never gated on the menu's spot."""
        right = _right(c.side)
        spot = await self.broker.spot()
        if spot is None:
            return None, "no_fresh_spot"
        quotes = await self.broker.requote(
            [
                ChainOption(
                    strike=c.short_strike, right=right, expiry=c.expiry, con_id=c.short_con_id
                ),
                ChainOption(
                    strike=c.long_strike, right=right, expiry=c.expiry, con_id=c.long_con_id
                ),
            ]
        )
        book = {(round(q.strike, 2), q.right): q for q in quotes}
        short_q = book.get((round(c.short_strike, 2), right))
        long_q = book.get((round(c.long_strike, 2), right))
        if short_q is None or long_q is None:
            return None, "no_fresh_quote"
        return refresh_candidate(c, short_q, long_q, self.now(), spot), None

    async def _resolve_pick(self, now: datetime) -> None:
        p = self._pending
        if p is None:
            return
        pick: SpreadPick | None = None
        fallback: str | None = None
        waited = (now - p.started).total_seconds()
        if not p.task.done():
            if waited <= self.cfg.ai.pick_timeout_seconds + _PICK_GRACE_SECONDS:
                return
            p.task.cancel()
            fallback = "timeout"
        else:
            try:
                pick = p.task.result()
                fallback = pick.fallback_reason
            except (Exception, asyncio.CancelledError):
                log.exception("spreads: the picker raised")
                fallback = "picker_error"
        self._pending = None
        if pick is None:
            ai = self.cfg.ai
            pick = SpreadPick(
                choice="skip",
                fallback_reason=fallback,
                market=SpreadMarketSnapshot(),
                call=SpreadLlmCall(
                    model=ai.pick_model,
                    effort=ai.pick_effort,
                    latency_ms=int(waited * 1000),
                    error=fallback,
                ),
            )
        by_letter = {i.letter: i for i in p.menu}
        baseline = next((i for i in p.menu if i.position == "baseline"), None)
        if fallback is None and pick.choice != "skip" and pick.choice not in by_letter:
            fallback = "off_menu"
        chosen: SpreadMenuItem | None
        if fallback is not None:
            chosen = baseline
        elif pick.choice == "skip":
            chosen = None
        else:
            chosen = by_letter[pick.choice]
        pick_id = store.record_pick(
            now=now,
            episode_key=p.episode,
            book_mode=self.cfg.mode,
            menu=p.menu,
            pick=pick,
            fallback_reason=fallback,
            executed_letter=chosen.letter if chosen is not None else None,
            snapshot=p.snapshot,
        )
        await self.notifier.send(
            fmt_pick(
                p.menu,
                pick,
                fallback,
                chosen,
                store.episode_trade(p.episode, "baseline"),
                self.cfg.mode,
            )
        )
        if fallback is not None:
            await self.alert_once(
                f"pick_fallback:{fallback}",
                f"[SPREADS] the picker failed ({fallback}) — "
                + (
                    "trading the baseline item"
                    if chosen
                    else "no baseline item on the menu, no trade"
                ),
            )
        if chosen is None:
            if fallback is not None:
                store.mark_pick_sent(
                    pick_id, send_rejected=True, send_reasons=["no_baseline_item"], filled=False
                )
            return
        try:
            await self._send_pick(p, pick_id, chosen, now)
        except Exception:
            # An exception past this point must not leave the row looking unattempted.
            store.mark_pick_sent(
                pick_id, send_rejected=True, send_reasons=["send_error"], filled=False
            )
            raise

    async def _send_pick(
        self, p: _PendingPick, pick_id: int, chosen: SpreadMenuItem, now: datetime
    ) -> None:
        """Re-quote, re-gate and send the chosen item; the pick row records what happened."""
        ai = self.cfg.ai
        if (now - p.started).total_seconds() > 2 * (ai.pick_timeout_seconds + _PICK_GRACE_SECONDS):
            # The choice was made on a market that is minutes old (the process was away, e.g. a
            # Gateway drop): record it, send nothing. The next episode asks again.
            store.mark_pick_sent(
                pick_id, send_rejected=True, send_reasons=["stale_pick"], filled=False
            )
            return
        blocked = [
            reason
            for reason, on in (
                ("entries_blocked", bool(self.entries_blocked)),
                ("halted", self.halt_path.exists()),
            )
            if on
        ]
        if blocked:
            store.mark_pick_sent(pick_id, send_rejected=True, send_reasons=blocked, filled=False)
            return
        fresh, why_not = await self._fresh_candidate(chosen.candidate)
        if fresh is None:
            store.mark_pick_sent(
                pick_id,
                send_rejected=True,
                send_reasons=[why_not or "no_fresh_quote"],
                filled=False,
            )
            return
        at = self.now()
        moved = p.levels.model_copy(
            update={
                "as_of": at,
                "spot": fresh.spot,
                "regime": regime_at(p.gex_chain, fresh.spot, p.levels.scale, at),
            }
        )
        # Excess liquidity is the one gate input the re-quote does not refresh: read it again, and
        # let an unreadable account hit the gate's own ``account_unknown`` rule.
        excess = await self.broker.excess_liquidity()
        verdict = validate(fresh, self._context(at, moved, excess), self.cfg)
        if not verdict.approved:
            store.mark_pick_sent(
                pick_id, send_rejected=True, send_reasons=list(verdict.reasons), filled=False
            )
            await self.notifier.send(
                fmt_alert(
                    f"pick {chosen.letter} not sent — the re-gate refused it: "
                    f"{', '.join(verdict.reasons)}"
                )
            )
            return
        pos, why = await self._open_candidate(
            fresh,
            verdict.contracts,
            moved,
            excess,
            now,
            mode=self.cfg.mode,
            executor=self.executor,
            gex_chain=p.gex_chain,
            pick_id=pick_id,
            episode_key=p.episode,
        )
        store.mark_pick_sent(
            pick_id,
            send_rejected=pos is None,
            send_reasons=[] if pos is not None else [why or "not_filled"],
            filled=pos is not None,
        )

    async def _manage(self, now: datetime) -> None:
        # Each book on its own guard: the baseline is the measuring stick, so a failure in the
        # main book (a dropped socket, a bad row) must not stop the baseline's exits — or the
        # reverse. The main book keeps the plain "manage" alert key.
        for i, (mode, executor) in enumerate(self.books):
            await self._guard(
                "manage" if i == 0 else f"manage:{mode}", self._manage_book(now, mode, executor)
            )

    async def _manage_book(self, now: datetime, mode: str, executor: Executor) -> None:
        positions = store.open_positions(mode)
        if not positions and not store.expiring_positions(mode):
            return
        spot = await self.broker.spot()
        if spot is not None:
            self.last_spot = spot
        today = now.astimezone(ET).date()
        for p in positions:
            if p.expiry < today:  # nothing left to close: the broker has settled it already
                await self.alert_once(
                    f"expired_open:{p.spread_id}",
                    f"[SPREADS] {p.spread_id} expired on {p.expiry} but spreads.db still holds it "
                    "open — check the broker for an assignment, then settle it with "
                    "python -m scripts.spreads_resolve",
                )
        positions = [p for p in positions if p.expiry >= today]
        if not positions:
            return
        paper = mode == "paper"
        held = self._broker_holdings(store.expiring_positions(mode) + positions) if paper else {}
        legs_now = self.broker.broker_legs() if paper else {}
        working = self.broker.working_refs() if paper else set()
        legs: list[ChainOption] = []
        for p in positions:
            r = _right(p.side)
            legs.append(
                ChainOption(strike=p.short_strike, right=r, expiry=p.expiry, con_id=p.short_con_id)
            )
            legs.append(
                ChainOption(strike=p.long_strike, right=r, expiry=p.expiry, con_id=p.long_con_id)
            )
        book = {(round(q.strike, 2), q.right, q.expiry): q for q in await self.broker.requote(legs)}
        for p in positions:
            r = _right(p.side)
            short_q = book.get((round(p.short_strike, 2), r, p.expiry))
            long_q = book.get((round(p.long_strike, 2), r, p.expiry))
            mark, _ = debit_to_close(short_q, long_q)
            if mark is not None:
                store.note_mark(p.spread_id, mark)  # the trade log's MAE
            decision = evaluate_exit(p, short_q, long_q, spot, now, self.cfg)
            if decision is None:
                continue
            if not decision.close:
                store.mark_expiring(p.spread_id)
                await self.notifier.send(fmt_exit(p.spread_id, "left to expire", None, None, mode))
                continue
            urgent = decision.reason not in ("profit_take", "max_hold")
            target = p
            if paper:
                if close_ref(self.cfg, p.spread_id) in working:
                    log.info(
                        "spreads: a close of %s is still working — not sending another", p.spread_id
                    )
                    continue
                qty = held.get(p.spread_id, 0)
                if qty < p.contracts:
                    await self.alert_once(
                        f"not_held:{p.spread_id}",
                        self._not_held_text(p, qty, legs_now),
                    )
                    if qty < 1:
                        continue
                    target = p.model_copy(update={"contracts": qty})
            result = await executor.close(target, short_q, long_q, urgent=urgent)
            store.record_order(
                spread_id=p.spread_id,
                kind="close",
                order_ref=result.order_ref,
                ib_order_id=result.ib_order_id,
                perm_id=result.perm_id,
                filled_qty=result.filled_qty,
                price=result.price,
                commission=result.commission,
                reason=result.reason,
                now=now,
            )
            await self._after_order(p.spread_id, "close", result)
            if result.filled_qty < 1 or result.price is None:
                await self.alert_once(
                    f"close:{p.spread_id}:{decision.reason}",
                    f"[SPREADS] close of {p.spread_id} ({decision.reason}) did not fill — retrying every tick",
                )
                continue
            realized = store.close_position(
                p.spread_id,
                contracts=result.filled_qty,
                debit=result.price,
                commission=result.commission,
                reason=decision.reason,
                now=now,
            )
            await self.notifier.send(
                fmt_exit(p.spread_id, decision.reason, result.price, realized, mode)
            )
            if mode == self.cfg.mode:
                await self._card_trade(
                    now,
                    exit_card_line(p.spread_id, decision.reason, realized),
                    status=f"closed {p.spread_id}",
                )
        force_close = day_schedule(self.cfg.schedule, now.astimezone(ET).date()).force_close
        if (
            mode != "baseline"
            and now.astimezone(ET).strftime("%H:%M") >= force_close
            and not self.cfg.exits.let_expire
        ):
            still = store.open_positions(mode)
            if still:  # a time-stop close did not fill: SPY settles in shares
                await self.alert_once(
                    "open_after_time_stop",
                    f"[SPREADS] {len(still)} {self.cfg.underlying} spread(s) still open after "
                    f"{force_close} ET — close by hand before the bell or risk assignment",
                )

    async def _eod(self, now: datetime) -> None:
        today = now.astimezone(ET).date()
        for mode, _ in self.books:
            await self._settle_expiring(mode, today, now)
        mode = self.cfg.mode
        trades, realized_today = store.day_stats(today, mode)
        text = fmt_eod(today, mode, trades, realized_today, len(store.open_positions(mode)))
        if self.picker is not None:
            _, base_today = store.day_stats(today, "baseline")
            text += "\n" + fmt_books(
                mode,
                realized_today,
                base_today,
                store.realized_pnl_total(mode),
                store.realized_pnl_total("baseline"),
            )
        await self.notifier.send(text)
        if self._card is not None and self._card.day == today:
            await self._card_update(now, status="session over", status_at=now, checks=0)
        self.eod_sent_for = today

    async def _settle_expiring(self, mode: str, today: date, now: datetime) -> None:
        for p in store.expiring_positions(mode):
            if p.expiry > today:
                continue
            if self.last_spot is None:
                await self.alert_once(
                    "settle",
                    "[SPREADS] cannot settle expiring spreads: no closing spot seen — settle by hand",
                )
                continue
            debit = intrinsic_debit(p, self.last_spot)
            realized = store.close_position(
                p.spread_id,
                contracts=p.contracts,
                debit=debit,
                commission=0.0,
                reason="expire_worthless" if debit == 0 else "expired_itm",
                now=now,
            )
            await self.notifier.send(fmt_exit(p.spread_id, "expired", debit, realized, mode))


# ---------------------------------------------------------------------------- process


async def _sleep_or_stop(stop: asyncio.Event, seconds: float) -> None:
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
    except TimeoutError:
        pass


async def _note_ledger_account(account: str) -> None:
    """Say where paper fills go. The trade ledger is single-account and normally tracks the REAL
    account while trading runs on paper, so it ignores paper fills by design — that is not a
    problem to fix. Paper spreads results live in spreads.db (``scripts.spreads_report``)."""
    try:
        from src.ledger.state import ledger_account
        from src.storage.db import session_scope

        with session_scope() as s:
            tracked = ledger_account(s)
    except Exception:
        log.exception("spreads: could not read the ledger's tracked account")
        return
    if tracked != account:
        log.info(
            "spreads: the trade ledger tracks %s, not %s, so paper spread fills stay out of "
            "/ledger (by design); read them with python -m scripts.spreads_report --mode paper",
            tracked or "no account yet",
            account,
        )


def make_ib() -> Any:
    """The process's one IB handle. ib_async re-requests the account summary on every Error 1102,
    which IBKR refuses (Error 322) while the wheel's scan connection holds the one it allows; the
    spreads read ``accountValues`` and never the summary, so that request is dropped here."""
    from ib_async import IB

    from src.ibkr.connection import suppress_account_summary_on_reconnect

    ib = IB()
    suppress_account_summary_on_reconnect(ib)
    return ib


async def run(
    stop_event: asyncio.Event | None = None, picker_factory: PickerFactory | None = None
) -> None:
    cfg = get_config()
    stop = stop_event or asyncio.Event()
    sc = cfg.spreads
    if not sc.enabled:
        log.warning("spreads: disabled (config/spreads.yaml → enabled: false) — idling")
        await stop.wait()
        return
    if cfg.is_live:
        log.error(
            "spreads: refusing to run with LIVE_TRADING=true — shadow/paper only in this build"
        )
        await stop.wait()
        return

    from src.ibkr.connection import connect_with_retry
    from src.ledger.live import attach_live_hook
    from src.spreads.chain import IbkrSpreadsBroker
    from src.spreads.executor import SpreadExecutor

    store.init_spreads_db()
    client_id = cfg.ibkr.client_ids["spreads"]
    log.warning(
        "=" * 60 + "\n  SPREADS SERVICE  |  mode=%s  port=%s  clientId=%s  ai=%s\n" + "=" * 60,
        sc.mode,
        cfg.ibkr_port,
        client_id,
        sc.ai.enabled,
    )
    ib = make_ib()

    async def connect(retries: int | None = None) -> bool:
        try:
            await connect_with_retry(
                ib,
                cfg.ibkr.host,
                cfg.ibkr_port,
                client_id,
                timeout=cfg.ibkr.connect_timeout_seconds,
                label="spreads",
                retries=retries,
            )
        except Exception:
            log.exception("spreads: connect failed")
            return False
        ib.reqMarketDataType(cfg.ibkr.market_data_type)
        return True

    interval = sc.schedule.manage_interval_seconds
    # Built before the first connect so a Gateway that is down at startup still raises the
    # open-spreads alerts; the account is filled in once IBKR names it.
    broker = IbkrSpreadsBroker(ib, sc, cfg.secrets.ibkr_account or "")
    notifier = SpreadsNotifier.from_config(cfg)
    picker = picker_factory(cfg) if sc.ai.enabled and picker_factory is not None else None
    if sc.ai.enabled and picker is None:
        log.warning(
            "spreads: ai.enabled but no picker was supplied — the baseline rule trades alone"
        )
    service = SpreadsService(
        broker,
        SpreadExecutor(ib, broker, sc),
        notifier,
        sc,
        halt_path=cfg.spreads_halt_path(),
        picker=picker,
    )
    # One attempt per pass at startup: this loop is the retry, and the full backoff (about
    # 105 s with the defaults) would hold off the open-spreads alert for that long.
    while not await connect(retries=1):
        if stop.is_set():
            return
        await service.while_disconnected()
        await _sleep_or_stop(stop, interval)

    account = cfg.secrets.ibkr_account or ib.managedAccounts()[0]
    broker.account = account
    if sc.mode == "paper":
        attach_live_hook(ib)
        await _note_ledger_account(account)
    await service.start()

    while not stop.is_set():
        if not ib.isConnected():
            await service.while_disconnected()
            if await connect():
                await service.start()
            else:
                await _sleep_or_stop(stop, interval)
                continue
        try:
            await service.tick()
        except Exception:
            log.exception("spreads tick failed")
            await service.alert_once("tick", "[SPREADS] a tick failed — see logs/spreads.log")
        await _sleep_or_stop(stop, interval)
    ib.disconnect()
