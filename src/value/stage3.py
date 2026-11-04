"""Stage 3's IBKR side (spec §9.7): one RTH cycle on clientId 31.

Connects (``ibkr.client_ids.value``), reads the account and every position as the broker holds
them (both books: ``get_positions(include_value=True)``), builds the plain ``Snapshot`` the book
reads, takes the wheel's own share count W from the ledger, runs ``live.cycle`` (reconcile, sells,
buys with their funding) and, once an hour, ``live.hourly_check``; then disconnects. Paper only:
the caller never runs it with ``LIVE_TRADING=true``. ib_async and ``src.ibkr`` are imported inside
the function, so importing ``src.value`` loads neither.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from src.common.config import Config
from src.common.schemas import OptionRight, PositionSnapshot
from src.value import live
from src.value.book import get_state, totals
from src.value.store import value_session

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
            msgs += [f"Value book: {s} re-evaluation opened (adds paused)" for s in opened]
        return msgs
    finally:
        ib.disconnect()


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
