"""Stage 3's IBKR side (spec §9.7): one RTH cycle on clientId 31.

Connects (``ibkr.client_ids.value``), reads the account and every position as the broker holds
them (both books: ``get_positions(include_value=True)``), builds the plain ``Snapshot`` the book
reads, takes the wheel's own share count W from the ledger, runs ``live.cycle`` (reconcile, sells,
buys with their funding) and, once an hour, ``live.hourly_check``; then disconnects. Paper only:
the caller never runs it with ``LIVE_TRADING=true``. ib_async and ``src.ibkr`` are imported inside
the function, so importing ``src.value`` loads neither.

**The risk envelope (risk-envelope Task 20, C8).** Each cycle measures the whole book (both books'
stock as the broker holds it, every option at its live IBKR model IV) and hands ``live.cycle`` a
``risk.ValueEnvelope``: the room and each pending buy's linear S10 / U_ew rates. The value fence
forbids ``src.engine``, so it is built from the pure shock engine (``src.analytics.shock``), its
inputs (``src.analytics.shock_inputs``), the shared room arithmetic and the glide
(``src.storage.envelope_state``), the switches (``src.storage.envelope_switches``) and the live
IV reader (``src.ibkr.live_iv``), all imported inside the function. The value book never starts the
glide (the wheel's live measurement does); while the switch is ``on`` a failed measurement is an
unmeasured room, so every buy is refused ``envelope_unmeasured`` (fail closed).
"""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import date, datetime, timedelta

from src.common.config import Config
from src.common.envelope_types import EnvelopeRoom
from src.common.schemas import AccountSnapshot, OptionRight, PositionSnapshot
from src.value import live
from src.value.book import get_state, totals
from src.value.risk import ValueEnvelope
from src.value.store import ValueProposalRow, value_session

log = logging.getLogger(__name__)


def ledger_fill(order_ref: str) -> tuple[float, float | None]:
    """Shares and average price the broker-truth ledger holds for one value order (its
    ``book="value"`` rows, matched by ``orderRef``), for resolving an order a restart left
    working. Read-only; ``(0, None)`` when the ledger has none (yet: Flex lags)."""
    from sqlalchemy import select

    from src.storage.db import session_scope
    from src.storage.models import BrokerExecutionRow as Row

    with session_scope() as s:
        rows = s.execute(
            select(Row.source_kind, Row.quantity, Row.price).where(
                Row.order_ref == order_ref,
                Row.sec_type == "STK",
                Row.superseded_by.is_(None),
            )
        ).all()
    execs = [r for r in rows if r[0] == "exec"] or list(rows)
    qty = sum(abs(float(q)) for _, q, _ in execs)
    if qty <= 0:
        return 0.0, None
    return qty, sum(abs(float(q)) * float(p) for _, q, p in execs) / qty


def build_snapshot(positions: list[PositionSnapshot], net_liq: float) -> live.Snapshot:
    """The broker's view as plain numbers: stock shares and marks (both books), the wheel's short
    calls per name (the sell cap) and its short puts' collateral per name."""
    shares: dict[str, float] = {}
    marks: dict[str, float] = {}
    calls: dict[str, int] = {}
    puts: dict[str, float] = {}
    for p in positions:
        sym = (p.underlying or p.symbol).upper()
        if p.sec_type == "STK":
            shares[sym] = shares.get(sym, 0.0) + p.position
            if p.market_price:
                marks[sym] = float(p.market_price)
        elif p.sec_type == "OPT" and p.position < 0:
            if p.right == OptionRight.CALL:
                calls[sym] = calls.get(sym, 0) + int(-p.position)
            elif p.right == OptionRight.PUT and p.strike:
                puts[sym] = puts.get(sym, 0.0) + p.strike * 100.0 * -p.position
    return live.Snapshot(
        net_liq=net_liq, shares=shares, marks=marks, wheel_short_calls=calls, csp_by_name=puts
    )


async def run_cycle(cfg: Config, *, now: datetime, hourly: bool) -> list[str]:
    from ib_async import IB

    import src.common.value_inputs as vi
    from src.ibkr.connection import connect_with_retry
    from src.ibkr.portfolio import get_account_snapshot_async, get_positions
    from src.storage.system_settings import is_halted
    from src.storage.wheel_shares import wheel_shares

    ib = IB()
    await connect_with_retry(
        ib,
        cfg.ibkr.host,
        cfg.ibkr_port,
        cfg.ibkr.client_ids["value"],
        timeout=cfg.ibkr.connect_timeout_seconds,
        label="value",
    )
    try:
        ib.reqMarketDataType(cfg.ibkr.market_data_type)
        positions = get_positions(ib, include_value=True)  # account truth: both books
        account = await get_account_snapshot_async(ib, cfg.secrets.ibkr_account or "")
        snap = build_snapshot(positions, account.net_liquidation)
        with value_session() as vs:
            names = set(snap.shares) | set(totals(vs).names)
            trend = bool((get_state(vs, "trend") or {}).get("brake", False))
        w = {s: x.shares for s, x in wheel_shares(sorted(names)).items()}
        envelope = await value_envelope(ib, positions, account, pending_buy_symbols(), now=now)
        msgs = await live.cycle(
            value_session,
            _broker(ib),
            snap,
            wheel=w,
            cfg=cfg.value,
            portfolio=cfg.risk.get("portfolio", {}),
            now=now,
            halted=is_halted(),
            is_live=cfg.is_live,
            trend_brake=trend,
            ledger_fill=ledger_fill,
            envelope=envelope,
        )
        if hourly:
            with value_session() as vs:
                held = sorted(totals(vs).names)
            with vi.research_read() as rs:
                yesterday = now.date() - timedelta(days=1)
                closes = {} if rs is None else _last_closes(rs, held, now.date())
                filings = {} if rs is None else vi.filings_between(rs, held, yesterday, now.date())
            major = {
                s
                for s, fs in filings.items()
                for f in fs
                if set(f.items) & set(cfg.value.rules.reevaluation.major_8k_items)
            }
            from src.value.ruleset import ruleset_id

            version, digest = ruleset_id(cfg.value)
            with value_session() as vs:
                opened = live.hourly_check(
                    vs,
                    snap,
                    closes,
                    major,
                    cfg=cfg.value,
                    now=now,
                    ruleset_version=version,
                    ruleset_hash=digest,
                )
            log.info("value: re-evaluations opened on %s (the outbox posts the cards)", opened)
        return msgs
    finally:
        ib.disconnect()


def pending_buy_symbols() -> list[str]:
    """The names of the buys this cycle may send (approved or waiting for funding)."""
    from sqlalchemy import select

    with value_session() as vs:
        return sorted(
            {
                p.symbol.upper()
                for p in vs.scalars(
                    select(ValueProposalRow).where(
                        ValueProposalRow.kind == "buy",
                        ValueProposalRow.status.in_(("approved", "funding")),
                    )
                )
            }
        )


def _unmeasured(enforce: str, why: str) -> ValueEnvelope:
    return ValueEnvelope(
        room=EnvelopeRoom(
            s10_gross=0.0,
            s10_limit=0.0,
            uew=0.0,
            uew_limit=0.0,
            t20_gross=0.0,
            t20_limit=None,
            enforce=enforce,
            measured=False,
            reasons_if_unmeasured=(why,),
        )
    )


async def value_envelope(
    ib: object,
    positions: list[PositionSnapshot],
    account: AccountSnapshot,
    symbols: list[str],
    *,
    now: datetime,
) -> ValueEnvelope | None:
    """The risk envelope for this cycle's buys (Task 20): None while the switch is ``off`` (and
    when there is nothing to buy); an unmeasured room when the measurement fails (refuses while
    ``on``, recorded while ``record``). *positions* is the broker's whole book (both books'
    stock), so no value line is added a second time."""
    from src.analytics.shock import SCENARIOS, measure, name_move
    from src.analytics.shock_inputs import betas, build_inputs
    from src.ibkr.live_iv import live_option_ivs
    from src.storage.envelope_state import room_for
    from src.storage.envelope_switches import enforce_mode, get_switch

    enforce = enforce_mode()
    if enforce == "off" or not symbols:
        return None
    try:
        nlv = float(account.net_liquidation)
        live_ivs = await live_option_ivs(ib, positions)  # type: ignore[arg-type]
        inputs = build_inputs(positions, nlv=nlv, value_by_name={}, ivs=live_ivs)
        extra, _flagged = betas([s for s in symbols if s not in inputs.betas])
        inputs = replace(inputs, betas={**inputs.betas, **extra})
        room = room_for(
            measure(inputs),
            enforce=enforce,
            t20_on=get_switch("t20_limit") == "on",
            today=now.date(),
            may_start=False,  # only the wheel's live measurement starts the glide
        )
        s10: dict[str, float] = {}
        uew: dict[str, float] = {}
        for sym in symbols:
            try:
                move = name_move(sym, SCENARIOS["S10"]["index"], inputs, scenario="S10")
            except KeyError:
                continue  # no beta: the buy is unmeasured
            s10[sym] = max(0.0, -move) / nlv
            uew[sym] = float(inputs.leverage.get(sym, 1)) / nlv
        return ValueEnvelope(room=room, s10_per_dollar=s10, uew_per_dollar=uew)
    except Exception:
        log.warning(
            "value: the risk envelope could not be measured; buys fail closed", exc_info=True
        )
        return _unmeasured(enforce, "measurement_failed")


def _broker(ib: object) -> live.ValueBroker:
    from src.value.executor import IbkrValueBroker

    return IbkrValueBroker(ib)


def _last_closes(rs: object, symbols: list[str], today: date) -> dict[str, float]:
    import src.common.value_inputs as vi

    out: dict[str, float] = {}
    for s in symbols:
        day = vi.newest_bar_before(rs, s, today)  # type: ignore[arg-type]
        if day is not None:
            out.update(vi.closes_on(rs, [s], day))  # type: ignore[arg-type]
    return out
