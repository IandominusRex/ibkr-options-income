"""LES share buys and trend-break sells (risk-envelope Task 32a; spec §3.5.1, rulings L1-L7).

The one automatic stock path: TQQQ and SOXL shares on the Leveraged Entry Signal of their
governing index (QQQ, SOXX), **paper only**, behind the ``leveraged_entry`` switch (ships
``record``). Deterministic: no LLM output reaches any of it. Once per intraday cycle after 10:00 ET
(``run_les_cycle``, hooked beside the capital release in the approval service's loop):

* ``off``: nothing. ``record``: every would-be buy and sell, with its Rules Engine verdict (the
  envelope result for a buy), is written to ``sizing_actions`` as kind ``les_record`` and nothing
  is sent. ``on`` (paper): a passing order goes through the stock order path
  (``stock_orders.execute_stock_order``, re-gated at send time on a fresh quote) and is recorded
  as kind ``les_order``; one Telegram notice per order names the signal's reasons and the tier.
  In live the switch reads its default and ``validate_stock_order`` refuses every LES order
  ``les_paper_only``, tapped or not (L7).
* **Sell** (L6): the stored signal is a trend break (2 closes under the 200-day) and LES shares
  of that ETF are held: one SELL of every LES share, at the next session's first cycle. A sale
  lowers risk, so the envelope never blocks it; it is capped at the LES shares held.
* **Buy** (L5): the signal's trend holds (close above the 200-day: no LES share is bought below
  it, L3) with a tier above zero (3% on a pullback, 6% with the washout), no LES buy of the ETF in
  the last 3 sessions, and the sleeve's room (``regime_limits.sleeve_room_usd``: the tier's share
  of net liquidation, leverage-weighted, less the sleeve's puts and LES shares already held) worth
  at least one share: ``floor(room / (mid x leverage))`` shares, never rounded up to one. The
  Rules Engine admits it only when S10_gross <= L(t) and U_ew <= L_ew(t) after the buy.

Fail closed: a missing or stale signal (older than 5 calendar days), an unreadable LES book, no
sizing context, or no quote is no order.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from src.common.books import LesExposure, les_exposure
from src.common.config import get_config, get_regime_cfg
from src.common.market_hours import is_trading_day
from src.common.schemas import (
    AccountSnapshot,
    LesSignal,
    OrderState,
    PositionSnapshot,
    RiskVerdict,
    SizingContext,
    StockOrderIntent,
    Verdict,
)
from src.engine.regime_limits import sleeve_room_usd
from src.engine.risk_engine import validate_stock_order
from src.execution.stock_orders import (
    StockOrderResult,
    StockQuote,
    book_for,
    execute_stock_order,
    fetch_stock_quote,
    qualify_stock,
    resolve_stale_stock_orders,
)
from src.regime.actions import record_stock_action
from src.storage.db import session_scope
from src.storage.envelope_switches import get_switch
from src.storage.les_state import latest_signal
from src.storage.models import OrderRow, SizingActionRow
from src.storage.system_settings import is_halted

log = logging.getLogger(__name__)
_ET = ZoneInfo("America/New_York")

START_ET = time(10, 0)
PACE_SESSIONS = 3  # one buy per ETF per 3 sessions (L5)
MAX_SIGNAL_AGE_DAYS = 5  # as the sleeve reads it (regime/context.py): a long weekend is 4
KIND_RECORD = "les_record"
KIND_ORDER = "les_order"


@dataclass(frozen=True, slots=True)
class LesAction:
    """One would-be or sent LES order: what the cycle decided and why."""

    etf: str
    index: str
    intent: StockOrderIntent
    verdict: RiskVerdict
    mode: str
    result: StockOrderResult | None = None


def buy_shares(room_usd: float, mid: float, leverage: int) -> int:
    """Whole shares the tier's room buys at *mid*, leverage-weighted: floor, never up to one."""
    unit = mid * max(1, leverage)
    return 0 if unit <= 0 or room_usd <= 0 else max(0, math.floor(room_usd / unit + 1e-9))


def _sessions_between(day: date, today: date) -> int:
    n, d = 0, day
    while d < today:
        d += timedelta(days=1)
        if is_trading_day(d):
            n += 1
    return n


def _et_day(ts: datetime) -> date:
    aware = ts if ts.tzinfo else ts.replace(tzinfo=UTC)
    return aware.astimezone(_ET).date()


def bought_recently(etf: str, today: date, *, mode: str, sessions: int = PACE_SESSIONS) -> bool:
    """An LES buy of *etf* fewer than *sessions* sessions ago: a sent order (``on``), or a passing
    would-be buy on the record (``record``), so each mode keeps its own pace."""
    since = datetime.combine(today - timedelta(days=sessions * 3 + 7), time.min)
    with session_scope() as s:
        if mode == "on":
            rows = (
                s.query(OrderRow.snapshot, OrderRow.created_at)
                .filter(
                    OrderRow.candidate_id.like("les:%"),
                    OrderRow.created_at >= since,
                    OrderRow.state.in_(
                        [OrderState.SUBMITTED, OrderState.PARTIAL, OrderState.FILLED]
                    ),
                )
                .all()
            )
            for snap, created in rows:
                if (
                    isinstance(snap, dict)
                    and snap.get("strategy") == "stock_buy"
                    and str(snap.get("underlying", "")).upper() == etf.upper()
                    and _sessions_between(_et_day(created), today) < sessions
                ):
                    return True
            return False
        days = (
            s.query(SizingActionRow.action_day)
            .filter(
                SizingActionRow.kind == KIND_RECORD,
                SizingActionRow.strategy == "stock_buy",
                SizingActionRow.underlying == etf.upper(),
                SizingActionRow.sent_contracts > 0,
                SizingActionRow.action_day >= since.date(),
            )
            .all()
        )
        return any(_sessions_between(d, today) < sessions for (d,) in days)


def order_working(etf: str) -> bool:
    """An LES order of *etf* still working (``submitted`` / ``partial`` with no terminal state):
    no second order on the name until it resolves, so a sale never doubles."""
    with session_scope() as s:
        rows = (
            s.query(OrderRow.snapshot)
            .filter(
                OrderRow.candidate_id.like("les:%"),
                OrderRow.state.in_([OrderState.SUBMITTED, OrderState.PARTIAL]),
            )
            .all()
        )
    return any(
        isinstance(snap, dict) and str(snap.get("underlying", "")).upper() == etf.upper()
        for (snap,) in rows
    )


def fresh_signal(index: str, today: date) -> LesSignal | None:
    """The latest stored signal for *index* when it is recent enough, else None (fail closed)."""
    sig = latest_signal(index)
    if sig is None or sig.asof is None:
        return None
    age = (today - sig.asof).days
    return sig if 0 <= age <= MAX_SIGNAL_AGE_DAYS else None


def _les_context(ctx: SizingContext, index: str, sig: LesSignal) -> SizingContext:
    """The sizing context the LES room is measured in: the sleeve's arithmetic (its tier, its
    puts, its LES shares) with the sleeve open, because ``leveraged_entry`` (not
    ``leveraged_sleeve``) is the switch that gates an LES buy, and with the very signal this
    cycle read, so the tier and the decision cannot disagree."""
    return ctx.model_copy(
        update={
            "switches": {**ctx.switches, "leveraged_sleeve": "on"},
            "les": {**ctx.les, index: sig},
        }
    )


async def _quote(ib: Any, symbol: str) -> StockQuote | None:
    contract = await qualify_stock(ib, symbol)
    return await fetch_stock_quote(ib, contract) if contract is not None else None


def _default_ctx(now: datetime) -> SizingContext | None:
    from src.regime.context import build_sizing_context

    with session_scope() as s:
        return build_sizing_context(now=now, session=s, for_send=True)


async def _notify(text: str) -> None:
    from src.notify.notices import send_notice

    await send_notice(text)


def _describe(sig: LesSignal) -> str:
    return f"{sig.index} {sig.asof}: tier {sig.tier_pct:g}%; " + "; ".join(sig.reasons)


async def run_les_cycle(
    ib: Any,
    account: AccountSnapshot | None = None,
    positions: list[PositionSnapshot] | None = None,
    *,
    now: datetime | None = None,
    quote_fn: Callable[[Any, str], Awaitable[StockQuote | None]] | None = None,
    book_fn: Callable[[Any, StockOrderIntent, float], Awaitable[dict[str, Any]]] | None = None,
    send_fn: Callable[[Any, StockOrderIntent], Awaitable[StockOrderResult]] | None = None,
    les_fn: Callable[[], LesExposure] | None = None,
    ctx_fn: Callable[[datetime], SizingContext | None] | None = None,
    notify: Callable[[str], Awaitable[None]] | None = None,
) -> list[LesAction]:
    """One LES pass (see the module docstring). Returns what it decided; never raises."""
    try:
        return await _cycle(
            ib,
            account,
            positions,
            now=now or datetime.now(UTC),
            quote_fn=quote_fn or _quote,
            book_fn=book_fn or book_for,
            send_fn=send_fn or execute_stock_order,
            les_fn=les_fn or les_exposure,
            ctx_fn=ctx_fn or _default_ctx,
            notify=notify or _notify,
        )
    except Exception:
        log.exception("LES cycle failed (nothing sent this cycle)")
        return []


async def _cycle(
    ib: Any,
    account: AccountSnapshot | None,
    positions: list[PositionSnapshot] | None,
    *,
    now: datetime,
    quote_fn: Callable[[Any, str], Awaitable[StockQuote | None]],
    book_fn: Callable[[Any, StockOrderIntent, float], Awaitable[dict[str, Any]]],
    send_fn: Callable[[Any, StockOrderIntent], Awaitable[StockOrderResult]],
    les_fn: Callable[[], LesExposure],
    ctx_fn: Callable[[datetime], SizingContext | None],
    notify: Callable[[str], Awaitable[None]],
) -> list[LesAction]:
    mode = get_switch("leveraged_entry")
    if mode == "off":
        return []
    et = now.astimezone(_ET)
    today = et.date()
    if not is_trading_day(today) or et.time() < START_ET:
        return []
    resolve_stale_stock_orders(today)
    book = les_fn()
    if not book.readable:
        log.warning("LES: the LES share book is unreadable; no LES order this cycle")
        return []
    if positions is None or account is None:
        from src.ibkr.portfolio import get_account_snapshot_async, get_positions

        positions = positions if positions is not None else get_positions(ib)
        if account is None:
            account = await get_account_snapshot_async(ib, get_config().secrets.ibkr_account or "")
    halted = is_halted()
    governing = get_regime_cfg().leveraged_entry.governing
    actions: list[LesAction] = []
    ctx: SizingContext | None = None
    for etf, index in sorted(governing.items()):
        etf = etf.upper()
        sig = fresh_signal(index, today)
        if sig is None:
            continue
        held = float(book.shares.get(etf, 0.0))
        if mode == "on" and order_working(etf):
            continue  # the last order on the name has not resolved: never a second one
        quote = await quote_fn(ib, etf)
        mid = quote.mid if quote is not None else None
        if sig.trend_break:
            if held < 1:
                continue
            intent = StockOrderIntent(
                side="SELL",
                symbol=etf,
                qty=int(math.floor(held + 1e-9)),
                source="les",
                reason=f"trend break on {index}",
            )
        elif sig.trend_up and sig.tier_pct > 0:
            if halted or mid is None:
                continue
            if bought_recently(etf, today, mode=mode):
                continue
            if ctx is None:
                ctx = ctx_fn(now)
                if ctx is None:
                    log.warning("LES: no sizing context; no LES buy this cycle")
                    return actions
            les_ctx = _les_context(ctx, index, sig)
            room = sleeve_room_usd(les_ctx, etf, account, positions)
            lev = int(les_ctx.leverage.get(etf, 0) or 0)
            if lev < 1:
                continue  # leverage unknown: no size (fail closed)
            qty = buy_shares(room, mid, lev)
            if qty < 1:
                continue
            intent = StockOrderIntent(
                side="BUY",
                symbol=etf,
                qty=qty,
                source="les",
                reason=f"{'washout' if sig.washout else 'pullback'} on {index}, tier {sig.tier_pct:g}%",
            )
        else:
            continue
        verdict = await _decide(ib, intent, mid, account, positions, held, book_fn)
        action = LesAction(etf, index, intent, verdict, mode)
        if mode != "on":
            _record(KIND_RECORD, intent, verdict, mid, sig, sent=None)
            actions.append(action)
            continue
        if verdict.verdict != Verdict.PASS:
            _record(KIND_ORDER, intent, verdict, mid, sig, sent=0)
            actions.append(action)
            continue
        result = await send_fn(ib, intent)
        _record(KIND_ORDER, intent, verdict, mid, sig, sent=int(result.filled), result=result)
        actions.append(LesAction(etf, index, intent, verdict, mode, result))
        await notify(
            f"LES {intent.side} {intent.qty} {etf} (paper): {result.status}"
            f"{f', {result.filled:g} @ {result.avg_price:.2f}' if result.filled and result.avg_price else ''}"
            f"{f' ({chr(44).join(result.reasons)})' if result.reasons else ''}. "
            f"Signal {_describe(sig)}"
        )
    return actions


async def _decide(
    ib: Any,
    intent: StockOrderIntent,
    mid: float | None,
    account: AccountSnapshot,
    positions: list[PositionSnapshot],
    held: float,
    book_fn: Callable[[Any, StockOrderIntent, float], Awaitable[dict[str, Any]]],
) -> RiskVerdict:
    """The decision-time gate: the Rules Engine on the book now (the attribution for a sell, the
    envelope after a buy) and the quote's mid."""
    if mid is None:
        return validate_stock_order(
            intent, account, positions, envelope=None, mid=None, attribution=None
        )
    book = await book_fn(ib, intent, mid)
    return validate_stock_order(
        intent,
        book.get("account", account),
        book.get("positions", positions),
        envelope=book.get("envelope"),
        mid=mid,
        attribution=book.get("attribution"),
        les_shares=held,
    )


def _record(
    kind: str,
    intent: StockOrderIntent,
    verdict: RiskVerdict,
    mid: float | None,
    sig: LesSignal,
    *,
    sent: int | None,
    result: StockOrderResult | None = None,
) -> None:
    """One ``sizing_actions`` row: in ``record`` the would-be order and its verdict (``sent`` is
    what ``on`` would have sent: the shares when it passed, else 0); in ``on`` what was sent."""
    passed = verdict.verdict == Verdict.PASS
    would = intent.qty if passed else 0
    envelope = "admitted" if passed else f"refused: {', '.join(verdict.reasons)}"
    status = f"; {result.status}" if result is not None else ""
    record_stock_action(
        kind=kind,
        symbol=intent.symbol,
        side=intent.side,
        qty=intent.qty,
        sent=would if sent is None else sent,
        price=mid or 0.0,
        reason=(
            f"{'would ' if kind == KIND_RECORD else ''}{intent.side.lower()} {intent.qty} "
            f"{intent.symbol}: {envelope}{status}. {intent.reason}. Signal {_describe(sig)}"
        ),
        order_id=result.order_id if result is not None else None,
    )
