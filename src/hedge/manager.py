"""The bridge hedge, run by Python for the glide only (risk-envelope Task 36; spec §3.10.2-§3.10.6,
§3.10.10 items 8 and 11; rulings H2-H6, H9, H10, P9).

``run_hedge_cycle(cfg, now)`` is called once per intraday cycle from ``approval_service``'s loop,
after the capital release. It **idles in live** (``Config.is_live``), and it connects (clientId 32,
``ibkr.client_ids.hedge``) only when there is something to do, for that cycle alone, then
disconnects (ruling P9, the value book's Stage 3 pattern).

* **Start** (H2): the first cycle on which ``envelope_enforce`` reads ``on`` and the H4 switch
  ``hedge_instrument`` names XND or QQQ, with the ``bridge`` switch ``off`` and no programme yet:
  the programme row is written with NLV0 = net liquidation that day, fixed once, and the switch
  goes ``on``.
* **Schedule, not trigger** (H5): with no position open, buy the default item (``sizing``); one
  position at a time; at 30 DTE or fewer, roll (sell the old item, buy the current default). Under
  the stress block, a halt or a slow-breaker trip (H6) a roll goes ahead only when it is
  self-funding (the sale's proceeds cover the new debit, no added contracts); otherwise the
  position is held.
* **QQQ route** (§3.10.4): an open QQQ position is closed by T-2 sessions before expiry; a close
  that does not fill sends a lapse instruction (``ib.exerciseOptions``, action 2) so the put is not
  exercised into shares. **XND** settles in cash: after expiry the settlement is booked at the last
  captured spot (an estimate; the broker ledger holds the true cash).
* **Monetisation** only when the ``hedge_monetisation`` switch reads ``2x`` (the E1 replay's
  ruling): a position marked at 2x its cost is sold.
* **End** (H2): at the glide's end (L(t) at the target) the switch goes ``ended``; nothing new is
  bought or rolled, and the open position is sold at its roll date.
* **Review** (H2): at the end, or after 20 sessions in which the size rule asked for nothing, the
  one-page record (``src/reporting/hedge.py``) is posted once, "default: off".
* **Marks** (H7): each open position is marked from today's captured quotes (``hedge_quotes``), else
  Black-Scholes on the last captured spot and IV, labelled ``bs``.

Every order is gated by ``risk_engine.validate_hedge`` at decision time and again at send time on a
fresh quote (``executor.execute_hedge``). Python sizes, prices, selects and gates everything; no
LLM output reaches any of it. Deterministic tier: imports no enrichment.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from src.common import hedge_view
from src.common.config import Config, HedgeCfg, get_config, get_envelope_cfg, get_hedge_cfg
from src.common.schemas import HedgeCandidate, HedgeLeg, RiskVerdict, Verdict
from src.hedge import executor, sizing, store

log = logging.getLogger(__name__)
_ET = ZoneInfo("America/New_York")

ROLL_DTE = 30  # H5: roll at 30 days to expiry or fewer
REVIEW_ZERO_SESSIONS = 20  # H2: the review record after 20 sessions of zero size
MONETISE_MULTIPLE = 2.0  # the leading candidate, applied only behind ``hedge_monetisation``
MARK_EVERY = timedelta(minutes=60)
NEEDED_KEY = store.NEEDED_KEY

Notify = Callable[[str], Awaitable[Any]]
ActionKind = Literal["end", "settle", "lapse", "close", "roll", "buy", "review"]


@dataclass(frozen=True, slots=True)
class Position:
    """One open hedge position as the plan reads it."""

    hedge: hedge_view.OpenHedge
    dte: int
    sessions_left: int
    mark: float | None  # per share, net (the structure's value)
    unit_cost: float  # per share paid
    index: bool  # cash-settled (XND) rather than physically settled (QQQ)


@dataclass(frozen=True, slots=True)
class Action:
    kind: ActionKind
    hedge_id: str | None = None
    reason: str = ""


@dataclass(frozen=True, slots=True)
class PlanState:
    today: date
    programme: store.Programme | None
    bridge: str  # the bridge switch
    monetise: bool
    positions: tuple[Position, ...]
    working: bool  # an order is still working somewhere in the book
    t_minus: int


@dataclass
class HedgeCycle:
    """What one cycle did: ``live`` | ``idle`` | ``no_client_id`` | ``unreadable`` |
    ``scan_running`` | ``ran`` | ``error``."""

    status: str
    actions: list[str] = field(default_factory=list)
    notices: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# The plan (pure)
# --------------------------------------------------------------------------- #


def review_due(programme: store.Programme | None) -> bool:
    """H2's review gate: once, at the end or after 20 zero-size sessions."""
    if programme is None or programme.review_posted_on is not None:
        return False
    return programme.state == "ended" or programme.zero_size_sessions >= REVIEW_ZERO_SESSIONS


def plan(state: PlanState) -> list[Action]:
    """The cycle's actions, in order. The programme is active while its row reads ``on`` and the
    glide has not ended; new size (a buy or a roll) also needs the ``bridge`` switch ``on``."""
    acts: list[Action] = []
    prog = state.programme
    active = prog is not None and prog.state == "on"
    if active and prog is not None and prog.glide_end is not None and state.today >= prog.glide_end:
        acts.append(Action("end", reason="glide_end"))
        active = False
    may_add = active and state.bridge == "on"
    rolling = False
    for p in state.positions:
        h = p.hedge
        if h.working or h.contracts <= 0:
            continue  # an order on it is still working: wait for it
        expiry = h.expiry
        if expiry is not None and expiry < state.today:
            acts.append(Action("settle" if p.index else "lapse", h.hedge_id, "expired"))
            continue
        if not p.index and p.sessions_left <= state.t_minus:
            acts.append(Action("close", h.hedge_id, "t_minus_close"))
            continue
        if (
            state.monetise
            and p.mark is not None
            and p.unit_cost > 0
            and p.mark >= MONETISE_MULTIPLE * p.unit_cost
        ):
            acts.append(Action("close", h.hedge_id, "monetise"))
            continue
        if p.dte <= ROLL_DTE:
            if may_add:
                acts.append(Action("roll", h.hedge_id, "roll_date"))
                rolling = True
            else:
                acts.append(Action("close", h.hedge_id, "roll_date_after_end"))
    holding = state.working or any(p.hedge.contracts > 0 for p in state.positions)
    if may_add and not holding and not rolling:
        acts.append(Action("buy", reason="schedule"))
    if review_due(prog) or (prog is not None and any(a.kind == "end" for a in acts)):
        acts.append(Action("review"))
    return acts


# --------------------------------------------------------------------------- #
# Reading the book
# --------------------------------------------------------------------------- #


def sessions_until(today: date, expiry: date) -> int:
    """Trading sessions after *today* up to and including *expiry*."""
    from src.common.market_hours import is_trading_day

    n, d = 0, today
    while d < expiry:
        d += timedelta(days=1)
        if is_trading_day(d):
            n += 1
    return n


def _now_et(now: datetime) -> date:
    return now.astimezone(_ET).date()


def _leg_value(action: str, strike: float, spot: float) -> float:
    intrinsic = max(0.0, strike - spot)
    return intrinsic if action == "BUY" else -intrinsic


def settlement_value(h: hedge_view.OpenHedge, spot: float) -> float:
    """Per share: the long leg's intrinsic value less the short leg's at *spot*."""
    return sum(_leg_value(leg.action, leg.strike, spot) for leg in h.legs)


def mark_position(
    h: hedge_view.OpenHedge, quotes: dict[int, store.QuoteRecord], today: date
) -> tuple[float, str] | None:
    """(mark per share, source): the captured mids when every leg has one today, else Black-Scholes
    on the last captured spot and each leg's last captured IV (``bs``); None when neither."""
    from src.analytics.black_scholes import bs_price

    legs = [(leg, quotes.get(leg.con_id or -1)) for leg in h.legs]
    if all(q is not None and q.session_date == today and q.mid for _, q in legs):
        return sum((q.mid or 0.0) * (1 if leg.action == "BUY" else -1) for leg, q in legs if q), (
            "captured"
        )
    total = 0.0
    for leg, q in legs:
        if q is None or not q.iv or not q.spot:
            return None
        dte = (leg.expiry - today).days
        px = (
            max(0.0, leg.strike - q.spot)
            if dte <= 0
            else bs_price(q.spot, leg.strike, dte, q.iv, "P")
        )
        if px is None:
            return None
        total += px if leg.action == "BUY" else -px
    return total, "bs"


def latest_leg_quotes(con_ids: list[int]) -> dict[int, store.QuoteRecord]:
    """The newest captured quote of each contract."""
    out: dict[int, store.QuoteRecord] = {}
    if not con_ids:
        return out
    for q in store.load_quotes():
        if q.con_id in con_ids:
            out[q.con_id] = q  # oldest first: the last one wins
    return out


def positions_for(
    book: list[hedge_view.OpenHedge], cfg: HedgeCfg, today: date
) -> tuple[Position, ...]:
    from src.common.config import hedge_index_underlyings

    index = set(hedge_index_underlyings(cfg))
    quotes = latest_leg_quotes([leg.con_id for h in book for leg in h.legs if leg.con_id])
    out: list[Position] = []
    for h in book:
        expiry = h.expiry or today
        m = mark_position(h, quotes, today)
        out.append(
            Position(
                hedge=h,
                dte=(expiry - today).days,
                sessions_left=sessions_until(today, expiry),
                mark=m[0] if m else None,
                unit_cost=h.cost / (h.contracts * h.multiplier) if h.contracts > 0 else 0.0,
                index=h.instrument in index,
            )
        )
    return tuple(out)


def write_marks(positions: tuple[Position, ...], today: date, now: datetime) -> int:
    """One mark per open position per hour (``hedge_marks``); returns the marks written."""
    marked = {m["hedge_id"]: m for m in hedge_view.marks_today(today) or []}
    quotes = latest_leg_quotes(
        [leg.con_id for p in positions for leg in p.hedge.legs if leg.con_id]
    )
    n = 0
    for p in positions:
        h = p.hedge
        if h.contracts <= 0:
            continue
        last = store.last_mark_at(h.hedge_id)
        if h.hedge_id in marked and last is not None and now - last < MARK_EVERY:
            continue
        m = mark_position(h, quotes, today)
        if m is None:
            log.warning("hedge %s: no captured quote or IV to mark it", h.hedge_id)
            continue
        store.record_mark(
            session_date=today,
            hedge_id=h.hedge_id,
            contracts=h.contracts,
            mark=m[0],
            multiplier=h.multiplier,
            source=m[1],
            marked_at=now,
        )
        n += 1
    return n


def update_zero_sessions(
    programme: store.Programme, *, today: date, s10_gross: float | None, budget: float
) -> int:
    """Once per session: count the sessions in which the size rule asked for nothing (no gap to
    the target, or no budget left), reset on any other. Returns the count."""
    if programme.state != "on" or programme.last_session == today:
        return programme.zero_size_sessions
    target = get_envelope_cfg().s10_target_pct
    zero = s10_gross is None or sizing.points_needed(s10_gross, target) <= 0 or budget <= 0
    count = programme.zero_size_sessions + 1 if zero else 0
    store.update_programme(programme.id, zero_size_sessions=count, last_session=today)
    return count


# --------------------------------------------------------------------------- #
# The cycle
# --------------------------------------------------------------------------- #


async def _default_notify(text: str) -> Any:
    from src.notify.notices import send_notice

    return await send_notice(text)


async def _connect(cfg: Config) -> Any:
    from ib_async import IB

    from src.ibkr.connection import connect_with_retry

    ib = IB()
    await connect_with_retry(
        ib,
        cfg.ibkr.host,
        cfg.ibkr_port,
        cfg.ibkr.client_ids["hedge"],
        timeout=cfg.ibkr.connect_timeout_seconds,
        label="hedge",
    )
    ib.reqMarketDataType(cfg.ibkr.market_data_type)
    return ib


def _new_id(today: date) -> str:
    return f"h{today:%Y%m%d}-{uuid.uuid4().hex[:6]}"


async def run_hedge_cycle(
    cfg: Config | None = None,
    now: datetime | None = None,
    *,
    notify: Notify | None = None,
    connect: Callable[[Config], Awaitable[Any]] | None = None,
    scan_running: bool = False,
) -> HedgeCycle:
    """One hedge cycle. Never raises; idles in live and while a scan holds the chain lines."""
    from src.storage.envelope_switches import get_switch

    cfg = cfg or get_config()
    if cfg.is_live:
        return HedgeCycle("live")
    now = now or datetime.now(UTC)
    say = notify or _default_notify
    try:
        hcfg = get_hedge_cfg()
        today = _now_et(now)
        programme = store.load_programme()
        book = hedge_view.open_hedges()
        if book is None:
            log.warning("hedge: the hedge book is unreadable; the cycle does nothing")
            return HedgeCycle("unreadable")
        enforce = get_switch("envelope_enforce")
        instrument = get_switch("hedge_instrument")
        bridge = get_switch("bridge")
        start = (
            programme is None
            and bridge == "off"
            and enforce == "on"
            and instrument in ("XND", "QQQ")
        )
        busy = bool(book) or (
            programme is not None and (programme.state == "on" or review_due(programme))
        )
        if not start and not busy:
            return HedgeCycle("idle")
        if "hedge" not in cfg.ibkr.client_ids:
            log.warning("hedge: ibkr.client_ids.hedge is not set; the bridge cannot connect")
            return HedgeCycle("no_client_id")
        if scan_running:
            return HedgeCycle("scan_running")
        positions = positions_for([h for h in book if h.contracts > 0 or h.working], hcfg, today)
        write_marks(positions, today, now)
        ib = await (connect or _connect)(cfg)
        try:
            return await _cycle(
                ib, cfg, hcfg, now, today, programme, instrument, bridge, positions, say, start
            )
        finally:
            try:
                ib.disconnect()
            except Exception:
                log.debug("hedge: disconnect failed", exc_info=True)
    except Exception:
        log.exception("hedge cycle failed")
        return HedgeCycle("error")


async def _cycle(
    ib: Any,
    cfg: Config,
    hcfg: HedgeCfg,
    now: datetime,
    today: date,
    programme: store.Programme | None,
    instrument: str,
    bridge: str,
    positions: tuple[Position, ...],
    say: Notify,
    start: bool,
) -> HedgeCycle:
    from src.ibkr.portfolio import get_account_snapshot_async
    from src.storage.envelope_state import glide_end, load_glide
    from src.storage.envelope_switches import get_switch, set_switch

    out = HedgeCycle("ran")
    await executor.resolve_working(ib, today=today)
    account = await get_account_snapshot_async(ib, cfg.secrets.ibkr_account or "")
    if programme is None and start:
        glide = load_glide()
        programme = store.start_programme(
            instrument=instrument,
            started_on=today,
            nlv0=account.net_liquidation,
            glide_end=glide_end(glide) if glide is not None else None,
        )
        set_switch("bridge", "on", source="hedge")
        bridge = "on"
        text = (
            f"Bridge hedge started ({programme.instrument}): NLV0 ${programme.nlv0:,.0f}, "
            f"budget {hcfg.budget.net_pct_nlv0:.2f}% of NLV0 net, paper only. "
            f"Ends at the glide end ({programme.glide_end or 'not yet set'})."
        )
        out.notices.append(text)
        await say(text)
    book_now = hedge_view.open_hedges() or []
    working = any(h.working for h in book_now)
    state = PlanState(
        today=today,
        programme=programme,
        bridge=bridge,
        monetise=get_switch("hedge_monetisation") == "2x",
        positions=positions,
        working=working,
        t_minus=hcfg.t_minus_close_sessions,
    )
    shared = _Shared(ib, cfg, hcfg, now, today, programme, account)
    for action in plan(state):
        out.actions.append(f"{action.kind}:{action.hedge_id or ''}:{action.reason}")
        line: str | None
        try:
            line = await _act(action, shared)
        except Exception:
            log.exception("hedge: %s failed", action)
            line = f"Bridge hedge: {action.kind} failed ({action.reason}); see the log."
        if line:
            out.notices.append(line)
            await say(line)
        if action.kind == "end" and programme is not None:
            set_switch("bridge", "ended", source="hedge")
            store.update_programme(programme.id, state="ended", ended_on=today)
            programme = store.load_programme() or programme
            shared.programme = programme
    if programme is not None and programme.state == "on":
        s10 = await shared.s10_gross()
        update_zero_sessions(programme, today=today, s10_gross=s10, budget=shared.budget_left())
        programme = store.load_programme() or programme
        if review_due(programme) and not any(a.startswith("review") for a in out.actions):
            text = await _review(shared)
            out.notices.append(text)
            await say(text)
    return out


@dataclass
class _Shared:
    ib: Any
    cfg: Config
    hcfg: HedgeCfg
    now: datetime
    today: date
    programme: store.Programme | None
    account: Any
    _book: Any = None
    _book_read: bool = False

    async def book(self) -> Any:
        from src.hedge.context import book_inputs

        if not self._book_read:
            self._book = await book_inputs(self.ib, self.account.net_liquidation)
            self._book_read = True
        return self._book

    async def s10_gross(self) -> float | None:
        from src.analytics.shock import measure

        b = await self.book()
        if b is None:
            return None
        result = measure(b)
        return result.s10 if result.measured else None

    def months(self) -> float:
        if self.programme is None:
            return 0.0
        return sizing.months_elapsed(self.programme.started_on, self.today)

    @property
    def nlv0(self) -> float:
        return self.programme.nlv0 if self.programme is not None else 0.0

    @property
    def instrument(self) -> str:
        return self.programme.instrument if self.programme is not None else ""

    def budget_left(self) -> float:
        hedges = hedge_view.open_hedges() or []
        return sizing.budget_room(
            self.hcfg,
            nlv0=self.nlv0,
            spent=hedge_view.spend() or 0.0,
            open_at_cost=sum(h.cost for h in hedges),
            months=self.months(),
        )

    async def beta(self) -> float | None:
        b = await self.book()
        if b is None:
            return None
        return sizing.instrument_beta(b, self.instrument)

    async def context(self) -> Any:
        from src.hedge.context import build_context

        return await build_context(
            self.ib,
            cfg=self.hcfg,
            now=datetime.now(UTC),
            nlv0=self.nlv0,
            months=self.months(),
            book=await self.book(),
            instrument_beta=await self.beta(),
        )

    async def gate(self, cand: HedgeCandidate) -> RiskVerdict:
        from src.hedge.context import gate

        return gate(await self.context(), cand)


async def _act(action: Action, sh: _Shared) -> str | None:
    if action.kind == "end":
        return (
            "Bridge hedge ended at the glide's end: nothing new is bought or rolled; the open "
            "position is sold at its roll date."
        )
    if action.kind == "review":
        return await _review(sh)
    if action.kind == "buy":
        return await _buy(sh)
    h = next((x for x in hedge_view.open_hedges() or [] if x.hedge_id == action.hedge_id), None)
    if h is None:
        return None
    if action.kind == "settle":
        return _settle(h, sh.today)
    if action.kind == "lapse":
        return await _book_lapse(h, sh)
    if action.kind == "close":
        return await _close(h, sh, action.reason)
    if action.kind == "roll":
        return await _roll(h, sh)
    return None


def close_candidate(h: hedge_view.OpenHedge, contracts: float, reason: str) -> HedgeCandidate:
    """The sale of *contracts* of position *h* (its own legs, as opened)."""
    cid = f"{h.hedge_id}x{uuid.uuid4().hex[:4]}"
    return HedgeCandidate(
        hedge_id=cid,
        order_ref=f"hedge:{cid}",
        instrument=h.instrument,
        intent="close",
        kind="vertical" if len(h.legs) > 1 else "outright",
        legs=[
            HedgeLeg(
                action="BUY" if leg.action == "BUY" else "SELL",
                right="P" if leg.right == "P" else "C",
                strike=leg.strike,
                expiry=leg.expiry,
                con_id=leg.con_id,
            )
            for leg in h.legs
        ],
        contracts=int(contracts),
        multiplier=h.multiplier,
        debit=0.0,
        closes=h.hedge_id,
        reason=reason,
    )


async def _send(cand: HedgeCandidate, sh: _Shared) -> executor.HedgeOrderResult:
    """Decision-time gate on fresh quotes, then the executor (which quotes and gates again)."""
    priced = await executor.quote_candidate(sh.ib, cand)
    if priced is None:
        return executor.HedgeOrderResult("refused", cand, reasons=["hedge_no_quote"])
    verdict = await sh.gate(priced)
    if verdict.verdict != Verdict.PASS:
        return executor.HedgeOrderResult("refused", priced, reasons=list(verdict.reasons))
    return await executor.execute_hedge(sh.ib, priced, gate=sh.gate)


def _order_line(res: executor.HedgeOrderResult, what: str) -> str:
    c = res.cand
    if res.status in ("filled", "partial", "working"):
        return (
            f"Bridge hedge {what}: {c.instrument} {c.kind} {res.filled:g}/{c.contracts} "
            f"@ {res.avg_price or 0:.2f} ({res.status}; ref {c.order_ref})."
        )
    return f"Bridge hedge {what} not sent: {', '.join(res.reasons) or res.status}."


async def _close(h: hedge_view.OpenHedge, sh: _Shared, reason: str) -> str:
    ctx = await sh.context()
    held = ctx.held_contracts.get(h.hedge_id, 0.0)
    if held < 1:
        return f"Bridge hedge {h.hedge_id}: the broker holds none to sell ({reason})."
    res = await _send(close_candidate(h, held, reason), sh)
    text = _order_line(res, f"sale ({reason})")
    if reason == "t_minus_close" and res.status != "filled":
        text += " " + await _lapse_instruction(h, held - res.filled, sh)
    return text


async def _lapse_instruction(h: hedge_view.OpenHedge, qty: float, sh: _Shared) -> str:
    """A failed QQQ close by T-2: tell IBKR not to exercise the long put (action 2, override 1).
    A vertical whose short leg is also in the money is left to natural exercise and assignment,
    which net to no shares (lapsing the long alone would leave the short's shares)."""
    from src.storage.system_settings import get_setting, set_setting

    if qty < 1:
        return ""
    key = f"hedge_lapse_sent:{h.hedge_id}"
    if get_setting(key) == sh.today.isoformat():
        return "The lapse instruction was already sent today."
    long_leg = next((leg for leg in h.legs if leg.action == "BUY"), None)
    short_leg = next((leg for leg in h.legs if leg.action == "SELL"), None)
    if long_leg is None:
        return ""
    quotes = latest_leg_quotes([long_leg.con_id] if long_leg.con_id else [])
    spot = quotes[long_leg.con_id].spot if long_leg.con_id in quotes else None
    if spot is None:
        # the instrument's newest captured quote, when the long leg has none of its own
        recent = [q for q in store.load_quotes(instrument=h.instrument) if q.spot and q.spot > 0]
        spot = recent[-1].spot if recent else None
    if short_leg is not None:
        if spot is None:
            return (
                f"No spot for {h.instrument} to check the short {short_leg.strike:g}P: no lapse "
                "instruction sent (lapsing the long alone could leave the short's shares). Left "
                f"to the operator before expiry {h.expiry}."
            )
        if spot < short_leg.strike:
            return "Both legs are in the money: left to exercise and assignment (no net shares)."
    contract = executor.leg_contract(
        close_candidate(h, qty, "lapse"),
        HedgeLeg(action="BUY", strike=long_leg.strike, expiry=long_leg.expiry),
    )
    qualified = await sh.ib.qualifyContractsAsync(contract)
    if (
        not qualified
        or any(c is None for c in qualified)
        or not int(getattr(contract, "conId", 0) or 0)
    ):
        return (
            f"The {h.instrument} {long_leg.strike:g}P could not be qualified: no lapse instruction "
            "sent. Check the position by hand before expiry."
        )
    sh.ib.exerciseOptions(contract, 2, int(qty), sh.cfg.secrets.ibkr_account or "", 1)
    set_setting(key, sh.today.isoformat())
    return f"Lapse instruction sent for {int(qty)} {h.instrument} {long_leg.strike:g}P."


def _settle(h: hedge_view.OpenHedge, today: date) -> str:
    """Book an expired XND position's cash settlement at the last captured spot on or before its
    expiry (an estimate: the broker ledger holds the true cash)."""
    expiry = h.expiry or today
    spots = [q for q in store.load_quotes(instrument=h.instrument) if q.session_date <= expiry]
    if not spots:
        return f"Bridge hedge {h.hedge_id}: expired, but no captured spot to book its settlement."
    spot = spots[-1].spot
    value = settlement_value(h, spot)
    store.record_fill(
        hedge_id=h.hedge_id,
        qty=-h.contracts,
        price=value,
        multiplier=h.multiplier,
        kind="settlement",
    )
    return (
        f"Bridge hedge {h.hedge_id}: {h.instrument} settled in cash at {spot:,.2f} (estimate), "
        f"{value:.2f} a share, ${value * h.multiplier * h.contracts:,.0f}."
    )


async def _book_lapse(h: hedge_view.OpenHedge, sh: _Shared) -> str:
    """An expired QQQ position the broker no longer holds lapsed worthless (or was closed by hand):
    book it at zero. One the broker still holds is left for a human."""
    ctx = await sh.context()
    if ctx.held_contracts.get(h.hedge_id, 0.0) > 0:
        return f"Bridge hedge {h.hedge_id}: past expiry and still held at IBKR; check it by hand."
    store.record_fill(
        hedge_id=h.hedge_id, qty=-h.contracts, price=0.0, multiplier=h.multiplier, kind="lapse"
    )
    return f"Bridge hedge {h.hedge_id}: expired and gone at IBKR; booked as lapsed."


async def _pick(sh: _Shared) -> tuple[sizing.Pick, float, int] | None:
    """The default item, the instrument's spot and the size rule's contracts (H5)."""
    from src.hedge.capture import quote_menu

    icfg = sh.hcfg.instruments.get(sh.instrument)
    book = await sh.book()
    if icfg is None or book is None:
        return None
    menu = await quote_menu(sh.ib, sh.instrument, icfg, sh.hcfg, sh.now)
    if menu is None:
        return None
    spot, items = menu
    pick = sizing.default_item(items, sh.instrument, spot, book, today=sh.today)
    if pick is None:
        return None
    result_s10 = await sh.s10_gross()
    beta = await sh.beta()
    points = (
        0.0
        if result_s10 is None
        else sizing.points_needed(result_s10, get_envelope_cfg().s10_target_pct)
    )
    n = sizing.contracts_for(
        pick,
        points=points,
        nlv=sh.account.net_liquidation,
        budget_left=sh.budget_left(),
        per_contract_delta=None if beta is None else sizing.item_beta_delta(pick.item, spot, beta),
        book_delta=sizing.book_beta_delta(book),
        hedge_delta=0.0,
        max_delta_share=sh.hcfg.max_hedge_delta_share,
    )
    from src.storage.system_settings import set_setting

    set_setting(NEEDED_KEY, str(n))
    return pick, spot, n


def buy_candidate(
    pick: sizing.Pick,
    *,
    instrument: str,
    spot: float,
    contracts: int,
    today: date,
    roll_of: str | None = None,
    roll_proceeds: float | None = None,
    roll_contracts: int | None = None,
) -> HedgeCandidate:
    it = pick.item
    hid = _new_id(today)
    legs = [
        HedgeLeg(
            action="BUY" if side == "long" else "SELL",
            strike=q.strike,
            expiry=q.expiry,
            con_id=q.con_id,
            bid=q.bid,
            ask=q.ask,
            delta=q.delta,
            iv=q.iv,
        )
        for side, q in it.legs
    ]
    debit = float(it.debit or 0.0)
    return HedgeCandidate(
        hedge_id=hid,
        order_ref=f"hedge:{hid}",
        instrument=instrument,
        kind=it.kind,
        legs=legs,
        contracts=contracts,
        debit=debit,
        max_loss=debit * 100 * contracts,
        spot=spot,
        dte=it.dte,
        scenario_credits=dict(pick.credits),
        roll_of=roll_of,
        roll_proceeds=roll_proceeds,
        roll_contracts=roll_contracts,
        reason="roll" if roll_of else "schedule",
    )


async def _buy(sh: _Shared) -> str | None:
    picked = await _pick(sh)
    if picked is None:
        return "Bridge hedge: no priced menu item today; nothing bought."
    pick, spot, n = picked
    if n < 1:
        log.info("hedge: the size rule asks for nothing today")
        return None
    cand = buy_candidate(pick, instrument=sh.instrument, spot=spot, contracts=n, today=sh.today)
    return _order_line(await _send(cand, sh), "buy")


async def _roll(h: hedge_view.OpenHedge, sh: _Shared) -> str:
    """Sell the old item, buy the current default. Under the stress block, a halt or a slow
    breaker trip only a self-funding roll goes ahead (the sale's proceeds at the bid cover the new
    debit, no added contracts); otherwise the position is held (H6)."""
    ctx = await sh.context()
    held = ctx.held_contracts.get(h.hedge_id, 0.0)
    picked = await _pick(sh)
    blocked = (
        ctx.halted
        or ctx.slow_breaker_tripped
        or ctx.vix_close is None
        or ctx.vxn_close is None
        or ctx.vxn_p90 is None  # unmeasured blocks, as validate_hedge's hedge_stress_unmeasured
        or ctx.vix_close >= sh.hcfg.stress.vix_close
        or ctx.vxn_close >= ctx.vxn_p90
    )
    sale = close_candidate(h, held, "roll")
    priced = await executor.quote_candidate(sh.ib, sale)
    proceeds_est = None
    if priced is not None:
        bid, _ask = executor.natural(priced.legs, "SELL")
        proceeds_est = None if bid is None else bid * h.multiplier * held
    if blocked:
        if picked is None or proceeds_est is None:
            return f"Bridge hedge {h.hedge_id}: roll held (stress block; nothing to compare)."
        pick, _spot, n = picked
        new_n = min(int(held), max(n, 0)) or int(held)
        cost = (pick.item.debit or 0.0) * h.multiplier * new_n
        if cost > proceeds_est:
            return (
                f"Bridge hedge {h.hedge_id}: roll held under the stress block (the new item "
                f"costs ${cost:,.0f}, the sale brings about ${proceeds_est:,.0f})."
            )
    sold = await _send(sale, sh)
    text = _order_line(sold, "roll sale")
    if sold.status != "filled":
        return text
    proceeds = (sold.avg_price or 0.0) * h.multiplier * sold.filled
    if picked is None:
        return text + " No new item priced; the bridge buys on a later cycle."
    pick, spot, n = picked
    new_n = min(int(held), n) if blocked else n
    if new_n < 1:
        return text + " The size rule asks for nothing: no new item."
    cand = buy_candidate(
        pick,
        instrument=sh.instrument,
        spot=spot,
        contracts=new_n,
        today=sh.today,
        roll_of=h.hedge_id,
        roll_proceeds=proceeds,
        roll_contracts=int(held),
    )
    return text + " " + _order_line(await _send(cand, sh), "roll buy")


async def _review(sh: _Shared) -> str:
    """Post H2's review record once (``src/reporting/hedge.py``), "default: off"."""
    from src.reporting.hedge import review_record

    text = review_record(today=sh.today)
    if sh.programme is not None:
        store.update_programme(sh.programme.id, review_posted_on=sh.today)
    return text
