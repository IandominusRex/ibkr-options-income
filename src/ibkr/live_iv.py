"""Live implied volatility for the envelope's gates (risk-envelope plan Task 12; spec §3.4.1,
§3.10.8 item 1; rulings H7, Q4).

Admission-time S10_gross reprices each option at the **live IV from IBKR model greeks**, not
from ``iv_history`` (stored IV collapsed on the worst days: QQQ read 14.6% against a VXN of 38.3
on Nov 5). These functions read ``modelGreeks.impliedVol`` from a fresh subscription and nothing
else:

* every subscription goes through ``req_fresh_mkt_data`` (never ``ib.reqMktData``), so a stale
  ticker from an earlier subscription can never answer;
* lines are opened in chunks of at most ``envelope.live_iv_batch`` (10), each chunk waited on for
  at most ``envelope.live_iv_timeout_seconds`` and **cancelled before the next opens**, so the
  envelope never holds more than ten of the account's ~100 lines;
* a contract whose model IV does not arrive is ``None`` (the envelope then reads
  ``envelope_unmeasured`` and fails closed); nothing here writes to ``iv_history``.
"""

from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass
from typing import Any

from ib_async import IB

from src.common.config import get_envelope_cfg
from src.common.schemas import PositionSnapshot
from src.ibkr.contracts import build_option, qualify_options_async
from src.ibkr.market_data import req_fresh_mkt_data

log = logging.getLogger(__name__)

_POLL_SECONDS = 0.1
_MAX_BATCH = 10  # the plan's line budget for any new quote fetch


def _model_iv(ticker: Any) -> float | None:
    """``modelGreeks.impliedVol`` as a positive decimal, else None."""
    greeks = getattr(ticker, "modelGreeks", None)
    raw = getattr(greeks, "impliedVol", None) if greeks is not None else None
    try:
        iv = float(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None
    if iv is None or math.isnan(iv) or iv <= 0:
        return None
    return iv


def _und_price(ticker: Any) -> float | None:
    """``modelGreeks.undPrice`` (the underlying's price the model IV was computed against) as a
    positive number, else None."""
    greeks = getattr(ticker, "modelGreeks", None)
    raw = getattr(greeks, "undPrice", None) if greeks is not None else None
    try:
        px = float(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None
    if px is None or math.isnan(px) or px <= 0:
        return None
    return px


async def _await_ivs(tickers: list[Any], timeout: float) -> None:
    """Poll until every ticker carries a model IV, bounded by poll count (a patched sleep
    cannot spin)."""
    polls = max(1, int(timeout / _POLL_SECONDS))
    for _ in range(polls):
        if all(_model_iv(t) is not None for t in tickers):
            return
        await asyncio.sleep(_POLL_SECONDS)


def _cancel(ib: IB, contract: Any) -> None:
    try:
        ib.cancelMktData(contract)
    except Exception:
        log.debug("live_iv: cancelMktData failed for %s", getattr(contract, "localSymbol", ""))


async def _read_chunked(ib: IB, contracts: list[Any]) -> list[float | None]:
    """Model IV for each qualified contract, in order, chunked and cancelled per chunk."""
    return [iv for iv, _und in await _read_chunked_full(ib, contracts)]


async def _read_chunked_full(
    ib: IB, contracts: list[Any]
) -> list[tuple[float | None, float | None]]:
    """(model IV, underlying price) for each qualified contract, in order, chunked and cancelled
    per chunk. The underlying price is the one the same subscription's model greeks carry, so a
    caller that wants a live spot pays for no further line."""
    cfg = get_envelope_cfg()
    batch = max(1, min(_MAX_BATCH, int(cfg.live_iv_batch)))
    out: list[tuple[float | None, float | None]] = []
    for i in range(0, len(contracts), batch):
        chunk = contracts[i : i + batch]
        opened: list[tuple[Any, Any]] = []
        try:
            for c in chunk:
                try:
                    opened.append((c, req_fresh_mkt_data(ib, c, "", False, False)))
                except Exception:
                    log.warning("live_iv: subscription failed for %s", getattr(c, "conId", c))
                    opened.append((c, None))
            await _await_ivs([t for _, t in opened if t is not None], cfg.live_iv_timeout_seconds)
            out.extend(
                (_model_iv(t), _und_price(t)) if t is not None else (None, None) for _, t in opened
            )
        finally:
            for c, t in opened:
                if t is not None:
                    _cancel(ib, c)
    return out


@dataclass(frozen=True)
class LiveReads:
    """What one pass over the option lines read: model IV by ``con_id`` and the underlying's live
    price by symbol (``spots``; an underlying with no valid ``undPrice`` is simply absent)."""

    ivs: dict[int, float | None]
    spots: dict[str, float]


async def live_option_reads(ib: IB, positions: list[PositionSnapshot]) -> LiveReads:
    """Live model IV for every option position (keyed by the position's ``con_id``) and the
    underlying's live price from the same subscriptions (review fix 3: the send-time envelope
    must not price the book's options against a stale close).

    Each option is qualified (``qualify_options_async``, through the contract cache), then read
    with ``req_fresh_mkt_data`` in chunks. An option that fails to qualify, or whose model IV
    does not arrive in time, maps to None. A position with no ``con_id`` is keyed by the
    qualified contract's id when one comes back. Never raises.
    """
    opts = [
        p
        for p in positions
        if p.sec_type == "OPT" and p.strike and p.expiry is not None and p.right is not None
    ]
    if not opts:
        return LiveReads({}, {})
    out: dict[int, float | None] = {p.con_id: None for p in opts if p.con_id}
    spots: dict[str, float] = {}
    try:
        pairs = []
        for p in opts:
            assert p.expiry is not None and p.strike is not None and p.right is not None
            pairs.append(
                (p, build_option(p.underlying or p.symbol, p.expiry, p.strike, p.right.value))
            )
        await qualify_options_async(ib, [c for _, c in pairs])
        ready = [(p, c) for p, c in pairs if getattr(c, "conId", 0)]
        reads = await _read_chunked_full(ib, [c for _, c in ready])
        for (p, c), (iv, und) in zip(ready, reads, strict=True):
            out[int(p.con_id or c.conId)] = iv
            if und is not None:
                spots.setdefault((p.underlying or p.symbol).upper(), und)
    except Exception:
        log.warning(
            "live_iv: live option IV fetch failed; every option reads unmeasured", exc_info=True
        )
        return LiveReads({k: None for k in out}, {})
    missing = sum(1 for v in out.values() if v is None)
    if missing:
        log.info("live_iv: %d of %d option position(s) have no live model IV", missing, len(out))
    return LiveReads(out, spots)


async def live_option_ivs(ib: IB, positions: list[PositionSnapshot]) -> dict[int, float | None]:
    """Live model IV for every option position, keyed by ``con_id`` (see ``live_option_reads``)."""
    return (await live_option_reads(ib, positions)).ivs


async def live_iv_for(ib: IB, contract: Any) -> float | None:
    """Live model IV for one option contract (a candidate at decision or send time), or None.

    Qualified first when it carries no ``conId``. Never raises."""
    try:
        if not getattr(contract, "conId", 0):
            await qualify_options_async(ib, [contract])
            if not getattr(contract, "conId", 0):
                return None
        return (await _read_chunked(ib, [contract]))[0]
    except Exception:
        log.warning("live_iv: live IV for one contract failed", exc_info=True)
        return None
