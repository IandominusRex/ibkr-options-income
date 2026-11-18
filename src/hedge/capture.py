"""Hedge-menu quote capture (risk-envelope Task 16; spec §3.10.8 item 3, ruling H7).

Twice a session, at the fixed ET times in ``hedge.capture_times_et``, every candidate instrument
(XND, QQQ) is quoted: spot, the listed chain (``reqSecDefOptParams``), the contracts worth quoting
(``menu.candidate_strikes``, qualified with ``qualifyContractsAsync`` through the contract cache) and
bid / ask / size / model delta of each, into ``hedge_quotes`` (``store.record_capture``). The H4
report (``scripts/hedge_capture_report.py``) reads them after 20 sessions.

Capture only: this module places no order. ``quote_menu`` (Task 36) quotes the same menu for the
bridge's buy and roll, on the hedge's own connection; the order goes through ``executor.py``.

Market data: every subscription goes through ``req_fresh_mkt_data`` (never ``ib.reqMktData``), in
chunks of at most ``hedge.capture_max_lines`` (10) lines, each chunk cancelled before the next opens.
``run_due_capture`` is called from ``approval_service``'s intraday loop on the scan connection and
only while no scan is running, so it takes a chain batch's place and never adds to one (the budget
``chain_batch_size + spreads.max_market_data_lines + reserved_monitor_lines <= max_concurrent_lines``
is checked at config load with the capture's lines in the batch's place).

Deterministic tier: imports no enrichment.
"""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from ib_async import IB, Index, Option, Stock

from src.common.config import HedgeCfg, HedgeInstrumentCfg, get_hedge_cfg
from src.hedge import store
from src.hedge.menu import (
    HedgeMenuItem,
    HedgeQuote,
    build_menu,
    candidate_strikes,
    default_item,
)
from src.ibkr.contracts import qualify_options_async
from src.ibkr.market_data import req_fresh_mkt_data
from src.storage.system_settings import get_setting, set_setting

log = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")
LAST_KEY = "hedge_capture_last"  # system_settings: the slot ("YYYY-MM-DD HH:MM", ET) last attempted
_POLL_SECONDS = 0.1
_CHUNK_TIMEOUT_SECONDS = (
    6.0  # a chunk waits this long for bid/ask/size/delta, then reads what it has
)
_SPOT_TIMEOUT_SECONDS = 8.0
_RUN_TIMEOUT_SECONDS = 240.0  # the whole capture, both instruments


def _num(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if math.isnan(v) or math.isinf(v) or abs(v) >= 1e300:
        return None
    return v


def _pos(x: Any) -> float | None:
    v = _num(x)
    return v if v is not None and v > 0 else None


def _size(x: Any) -> float | None:
    v = _num(x)
    return v if v is not None and v >= 0 else None


def to_quote(contract: Any, ticker: Any) -> HedgeQuote:
    """One qualified option contract and its ticker as a ``HedgeQuote`` (no ib_async object leaves
    this function). A missing, NaN or non-positive bid/ask stays None."""
    exp = str(contract.lastTradeDateOrContractMonth)[:8]
    greeks = getattr(ticker, "modelGreeks", None)
    return HedgeQuote(
        strike=float(contract.strike),
        right="P" if str(contract.right).upper().startswith("P") else "C",
        expiry=date(int(exp[:4]), int(exp[4:6]), int(exp[6:8])),
        bid=_pos(getattr(ticker, "bid", None)),
        ask=_pos(getattr(ticker, "ask", None)),
        bid_size=_size(getattr(ticker, "bidSize", None)),
        ask_size=_size(getattr(ticker, "askSize", None)),
        delta=_num(getattr(greeks, "delta", None)) if greeks is not None else None,
        con_id=int(getattr(contract, "conId", 0) or 0) or None,
        iv=_pos(getattr(greeks, "impliedVol", None)) if greeks is not None else None,
    )


def _ready(pairs: list[tuple[Any, Any]]) -> bool:
    """Every ticker that has an ask also has its bid, both sizes and (for options) its delta."""
    for _, t in pairs:
        if _pos(getattr(t, "ask", None)) is None:
            return False
        g = getattr(t, "modelGreeks", None)
        if (
            _pos(getattr(t, "bid", None)) is None
            or _size(getattr(t, "bidSize", None)) is None
            or _size(getattr(t, "askSize", None)) is None
            or g is None
            or _num(getattr(g, "delta", None)) is None
        ):
            return False
    return True


def _ready_fn(pairs: list[tuple[Any, Any]]) -> Callable[[], bool]:
    """A predicate bound to this chunk (a lambda in the chunk loop trips ruff B023)."""
    return lambda: _ready(pairs)


async def _wait(ready: Callable[[], bool], timeout: float) -> None:
    """Poll until *ready()*, bounded by poll count so a patched sleep cannot spin."""
    for _ in range(max(1, int(timeout / _POLL_SECONDS))):
        if ready():
            return
        await asyncio.sleep(_POLL_SECONDS)


def _cancel(ib: IB, contract: Any) -> None:
    try:
        ib.cancelMktData(contract)
    except Exception:
        log.debug("hedge capture: cancelMktData failed for %s", getattr(contract, "conId", ""))


async def _spot(ib: IB, underlying: Any) -> float | None:
    """The underlying's last print (else the mid of a two-sided quote), one subscription."""
    t = req_fresh_mkt_data(ib, underlying, "", False, False)
    try:

        def have() -> bool:
            return _pos(getattr(t, "last", None)) is not None or (
                _pos(getattr(t, "bid", None)) is not None
                and _pos(getattr(t, "ask", None)) is not None
            )

        await _wait(have, _SPOT_TIMEOUT_SECONDS)
        last = _pos(getattr(t, "last", None))
        if last is not None:
            return last
        bid, ask = _pos(getattr(t, "bid", None)), _pos(getattr(t, "ask", None))
        return (bid + ask) / 2.0 if bid is not None and ask is not None else None
    finally:
        _cancel(ib, underlying)


async def quote_contracts(ib: IB, contracts: list[Any], *, max_lines: int) -> list[HedgeQuote]:
    """A ``HedgeQuote`` per qualified contract, in order, in chunks of at most *max_lines* (never
    over 10), each cancelled before the next chunk opens."""
    batch = max(1, min(10, max_lines))
    out: list[HedgeQuote] = []
    for i in range(0, len(contracts), batch):
        chunk = contracts[i : i + batch]
        pairs: list[tuple[Any, Any]] = []
        try:
            for c in chunk:
                pairs.append((c, req_fresh_mkt_data(ib, c, "", False, False)))
            await _wait(_ready_fn(pairs), _CHUNK_TIMEOUT_SECONDS)
            out.extend(to_quote(c, t) for c, t in pairs)
        finally:
            for c, _ in pairs:
                _cancel(ib, c)
    return out


def _pick_chain(params: list[Any], trading_class: str) -> Any | None:
    matches = [p for p in params if p.tradingClass == trading_class and p.expirations]
    if not matches:
        return None
    return max(matches, key=lambda p: (p.exchange == "SMART", len(p.expirations), len(p.strikes)))


def underlying_contract(name: str, icfg: HedgeInstrumentCfg) -> Any:
    if icfg.sec_type == "STK":
        return Stock(name, icfg.exchange, "USD")
    return Index(name, icfg.exchange, "USD")


def _records(
    instrument: str,
    items: list[HedgeMenuItem],
    default: HedgeMenuItem | None,
    spot: float,
    captured_at: datetime,
    needed: int,
) -> list[store.QuoteRecord]:
    session = captured_at.astimezone(_ET).date()
    out: list[store.QuoteRecord] = []
    for it in items:
        for leg, q in it.legs:
            out.append(
                store.QuoteRecord(
                    captured_at=captured_at,
                    session_date=session,
                    instrument=instrument,
                    item_key=it.item_key,
                    leg=leg,
                    is_default=default is not None and it.item_key == default.item_key,
                    con_id=q.con_id,
                    strike=q.strike,
                    right=q.right,
                    expiry=q.expiry,
                    spot=spot,
                    bid=q.bid,
                    ask=q.ask,
                    bid_size=q.bid_size,
                    ask_size=q.ask_size,
                    mid=q.mid,
                    delta=q.delta,
                    needed_contracts=needed,
                    iv=q.iv,
                )
            )
    return out


async def capture_instrument(
    ib: IB, name: str, icfg: HedgeInstrumentCfg, cfg: HedgeCfg, now: datetime
) -> list[store.QuoteRecord]:
    """One instrument's capture: spot, chain, the menu's legs quoted, the menu's rows. Raises on a
    failure (the caller logs it and moves on to the next instrument)."""
    spot, items = await _menu(ib, name, icfg, cfg, now)
    return _records(
        name, items, default_item(items, spot), spot, now.astimezone(UTC), store.needed_contracts()
    )


async def quote_menu(
    ib: IB, name: str, icfg: HedgeInstrumentCfg, cfg: HedgeCfg, now: datetime
) -> tuple[float, list[HedgeMenuItem]] | None:
    """The instrument's spot and its menu quoted now, for the bridge's buy and roll (Task 36), on
    the hedge's own connection; None on any failure (logged)."""
    try:
        return await _menu(ib, name, icfg, cfg, now)
    except Exception:
        log.warning("hedge menu: %s could not be quoted", name, exc_info=True)
        return None


async def _menu(
    ib: IB, name: str, icfg: HedgeInstrumentCfg, cfg: HedgeCfg, now: datetime
) -> tuple[float, list[HedgeMenuItem]]:
    und = underlying_contract(name, icfg)
    qualified = await ib.qualifyContractsAsync(und)
    if not qualified or not getattr(und, "conId", 0):
        raise RuntimeError(f"{name}: the underlying did not qualify")
    spot = await _spot(ib, und)
    if spot is None:
        raise RuntimeError(f"{name}: no spot")
    params = await ib.reqSecDefOptParamsAsync(name, "", icfg.sec_type, und.conId)
    chain = _pick_chain(list(params), icfg.trading_class)
    if chain is None:
        raise RuntimeError(f"{name}: no option chain with tradingClass {icfg.trading_class}")
    today = now.astimezone(_ET).date()
    expirations = [
        date(int(e[:4]), int(e[4:6]), int(e[6:8])) for e in chain.expirations if len(e) == 8
    ]
    wanted = candidate_strikes(chain.strikes, expirations, spot, cfg, today=today)
    if not wanted:
        raise RuntimeError(f"{name}: no expiry in the {list(cfg.dte_window)}-day window")
    contracts = [
        Option(
            name,
            f"{e:%Y%m%d}",
            k,
            "P",
            "SMART",
            multiplier=str(icfg.multiplier),
            tradingClass=icfg.trading_class,
        )
        for e, k in wanted
    ]
    good = await qualify_options_async(ib, contracts, chunk_size=cfg.capture_max_lines)
    quotes = await quote_contracts(ib, list(good), max_lines=cfg.capture_max_lines)
    return spot, build_menu(quotes, spot, cfg, today=today)


@dataclass
class CaptureOutcome:
    slot: str
    rows: dict[str, int] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)


async def capture_once(ib: IB, now: datetime, *, cfg: HedgeCfg | None = None) -> CaptureOutcome:
    """Capture every configured instrument at *now*; one instrument's failure never stops the
    next. Writes the rows through ``store.record_capture`` and returns what happened."""
    cfg = cfg or get_hedge_cfg()
    out = CaptureOutcome(slot=now.astimezone(_ET).strftime("%Y-%m-%d %H:%M"))
    for name, icfg in cfg.instruments.items():
        try:
            records = await capture_instrument(ib, name, icfg, cfg, now)
            out.rows[name] = store.record_capture(records)
            if not records:
                out.errors[name] = "the menu was empty (no put in the delta band was quoted)"
        except Exception as exc:
            log.warning("hedge capture: %s failed", name, exc_info=True)
            out.errors[name] = f"{type(exc).__name__}: {exc}"
    return out


def due_slot(now: datetime, times: list[str], last: str) -> str | None:
    """The newest capture time that has passed today (ET) and is not the one last attempted, as
    ``"YYYY-MM-DD HH:MM"``; None when nothing is due. A restart late in the session therefore
    runs one capture, never one per missed time."""
    et = now.astimezone(_ET)
    passed = [t for t in times if t <= et.strftime("%H:%M")]
    if not passed:
        return None
    slot = f"{et:%Y-%m-%d} {max(passed)}"
    return None if slot == last else slot


async def run_due_capture(
    ib: IB, now: datetime | None = None, *, scan_running: bool = False
) -> CaptureOutcome | None:
    """Run the capture when a slot is due and no scan holds the chain lines. The slot is marked
    attempted when it runs, so a failed capture is not retried every cycle (the next slot, or
    tomorrow's, is the next sample). Never raises."""
    if scan_running:
        return None
    try:
        cfg = get_hedge_cfg()
        now = now or datetime.now(UTC)
        slot = due_slot(now, cfg.capture_times_et, get_setting(LAST_KEY))
        if slot is None:
            return None
        set_setting(LAST_KEY, slot)
        outcome = await asyncio.wait_for(
            capture_once(ib, now, cfg=cfg), timeout=_RUN_TIMEOUT_SECONDS
        )
        log.info("hedge capture %s: rows=%s errors=%s", slot, outcome.rows, outcome.errors)
        return outcome
    except Exception:
        log.warning("hedge capture failed", exc_info=True)
        return None
