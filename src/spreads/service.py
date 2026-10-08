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
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Literal, Protocol

from src.common.config import SpreadsCfg, get_config
from src.common.market_hours import is_trading_day
from src.common.schemas import (
    ChainOption,
    ChainSnapshot,
    GexLevels,
    SessionSnapshot,
    SpreadCandidate,
    SpreadEntryContext,
    SpreadPosition,
    SpreadRiskContext,
    SpreadSide,
    SpreadVerdict,
)
from src.spreads import store
from src.spreads.executor import UNRESOLVED, FillResult, close_ref
from src.spreads.gex import build_levels, expected_move, regime_at
from src.spreads.manager import debit_to_close, evaluate_exit, intrinsic_debit, reconcile
from src.spreads.notify import SpreadsNotifier, fmt_entry, fmt_eod, fmt_exit, fmt_map
from src.spreads.pricing import ET, day_schedule
from src.spreads.risk import validate
from src.spreads.selector import select_candidates
from src.spreads.tape import SessionTape, trigger

log = logging.getLogger(__name__)

_MAP_RETRY = timedelta(minutes=5)


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
    async def send(self, text: str) -> None: ...


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
        self._mismatch_ticks = 0

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
            await self.notifier.send(
                "[SPREADS] entries blocked — broker and spreads.db disagree:\n"
                + "\n".join(problems)
            )
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
            if self._mismatch_ticks == 2:  # one tick of fill-to-position lag is normal
                await self.alert_once(
                    "reconcile",
                    "[SPREADS] entries blocked — broker and spreads.db disagree:\n"
                    + "\n".join(problems),
                )
            return
        self._mismatch_ticks = 0
        if self.entries_blocked is not None:
            log.info("spreads: broker and spreads.db agree again — entries unblocked")
            self.entries_blocked = None

    def _broker_holdings(self, positions: list[SpreadPosition]) -> dict[str, int]:
        """Contracts of each spread the broker still holds both legs of, allocated in DB order
        so two spreads sharing a leg can't both claim it."""
        remaining = dict(self.broker.broker_legs())
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
        await self.notifier.send(text)

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
        await self._guard("manage", self._manage(now))
        if s.entry_start <= hhmm < s.entry_end:
            await self._guard("entries", self._entries(now))
        if hhmm >= s.eod_summary and self.eod_sent_for != today:
            await self._guard("eod", self._eod(now))

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
            await self.alert_once(
                "map_missing",
                "[SPREADS] could not build the GEX map (no chain or no index price) — no entries until it builds",
            )
            return
        try:
            # The gamma-flip search is scipy-heavy: keep it off the loop so the heartbeat runs.
            levels = await asyncio.to_thread(build_levels, gex_chain, traded, self.cfg, now)
        except Exception:
            # Never trade on the previous map for another hour: no map, no entries, retry soon.
            self.levels = None
            self.map_failed_at = now
            raise
        self.map_failed_at = None
        self.map_at = now
        self.gex_chain = gex_chain
        self.levels = levels
        store.record_map(self.levels)
        tape = self._tape_for(now)
        if tape.day_em is None:
            # The day's FIRST expected move, from spreads.db: a restart must not swap in the
            # smaller straddle it sees later in the day.
            tape.day_em = store.first_map_em(now.astimezone(ET).date())
        await self.notifier.send(fmt_map(self.levels, self.cfg.mode))

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

    def _context(self, now: datetime, levels: GexLevels, excess: float | None) -> SpreadRiskContext:
        mode = self.cfg.mode
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
            capital_usd=self.capital(),
            sides_today=store.sides_opened(today, mode),  # type: ignore[arg-type]
        )

    def capital(self) -> float:
        """The book's sizing capital: starting capital plus everything it has realized (this mode)."""
        return self.cfg.risk.starting_capital_usd + store.realized_pnl_total(self.cfg.mode)

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
        if self.entries_blocked:
            return
        if self.halt_path.exists():
            await self.alert_once(
                "halt", f"[SPREADS] halt file {self.halt_path} present — no new entries"
            )
            return
        if self.levels is None or self.gex_chain is None:
            return
        allowed = trigger(self.tape, now, self.cfg)
        if not allowed.sides:
            log.debug("spreads trigger: %s (move %s)", allowed.reason, allowed.move_em)
            return
        if not self._entry_due(now):
            return
        self.last_entry_check = now
        chain = await self._traded_chain(spot_hint=self.levels.spot)
        if chain is None:
            return
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
        for cand in select_candidates(chain, levels, self.cfg, now, sides=allowed.sides):
            # Validated on the clock it runs at, so the quote's age (chain.as_of) is real.
            verdict = validate(cand, self._context(self.now(), levels, excess), self.cfg)
            store.record_candidate(cand, verdict, levels.regime, now)
            if not verdict.approved:
                continue

            def recheck(fresh: SpreadCandidate) -> SpreadVerdict:
                at = self.now()
                moved = levels.model_copy(
                    update={
                        "spot": fresh.spot,
                        "regime": regime_at(gex_chain, fresh.spot, levels.scale, at),
                    }
                )
                return validate(fresh, self._context(at, moved, excess), self.cfg)

            result = await self.executor.open(cand, verdict.contracts, recheck)
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
                if self.entries_blocked:
                    return
                continue
            tags = self._entry_context(cand.side, levels, now)
            pos = store.open_position(
                cand,
                mode=self.cfg.mode,
                contracts=result.filled_qty,
                credit=result.price,
                commission=result.commission,
                now=now,
                perm_id=result.perm_id,
                context=tags,
            )
            await self.notifier.send(fmt_entry(pos, self.cfg.mode, tags))
            if self.entries_blocked:
                return

    async def _manage(self, now: datetime) -> None:
        mode = self.cfg.mode
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
                        f"[SPREADS] the broker holds {qty} of {p.contracts} contract(s) of "
                        f"{p.spread_id} — closing only what it holds; settle the rest with "
                        "python -m scripts.spreads_resolve",
                    )
                    if qty < 1:
                        continue
                    target = p.model_copy(update={"contracts": qty})
            result = await self.executor.close(target, short_q, long_q, urgent=urgent)
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
        force_close = day_schedule(self.cfg.schedule, now.astimezone(ET).date()).force_close
        if now.astimezone(ET).strftime("%H:%M") >= force_close and not self.cfg.exits.let_expire:
            still = store.open_positions(mode)
            if still:  # a time-stop close did not fill: SPY settles in shares
                await self.alert_once(
                    "open_after_time_stop",
                    f"[SPREADS] {len(still)} {self.cfg.underlying} spread(s) still open after "
                    f"{force_close} ET — close by hand before the bell or risk assignment",
                )

    async def _eod(self, now: datetime) -> None:
        mode = self.cfg.mode
        today = now.astimezone(ET).date()
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
        trades, realized_today = store.day_stats(today, mode)
        await self.notifier.send(
            fmt_eod(today, mode, trades, realized_today, len(store.open_positions(mode)))
        )
        self.eod_sent_for = today


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


async def run(stop_event: asyncio.Event | None = None) -> None:
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

    from ib_async import IB

    from src.ibkr.connection import connect_with_retry
    from src.ledger.live import attach_live_hook
    from src.spreads.chain import IbkrSpreadsBroker
    from src.spreads.executor import SpreadExecutor

    store.init_spreads_db()
    client_id = cfg.ibkr.client_ids["spreads"]
    log.warning(
        "=" * 60 + "\n  SPREADS SERVICE  |  mode=%s  port=%s  clientId=%s\n" + "=" * 60,
        sc.mode,
        cfg.ibkr_port,
        client_id,
    )
    ib: Any = IB()

    async def connect() -> bool:
        try:
            await connect_with_retry(
                ib,
                cfg.ibkr.host,
                cfg.ibkr_port,
                client_id,
                timeout=cfg.ibkr.connect_timeout_seconds,
                label="spreads",
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
    service = SpreadsService(
        broker, SpreadExecutor(ib, broker, sc), notifier, sc, halt_path=cfg.spreads_halt_path()
    )
    while not await connect():
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
