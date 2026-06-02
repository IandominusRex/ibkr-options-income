"""Market data layer: option chains, live quotes + Greeks, and IV history backfill.

Public surface:
  get_option_chain_quotes(ib, symbol) -> list[OptionQuote]
  persist_chain_quotes(symbol, quotes, run_id) -> None

Internal helpers are module-private (_prefix) but importable by tests.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Iterable
from datetime import date
from typing import Any

from ib_async import IB, Option

from src.common.config import get_config
from src.common.logging import get_logger
from src.common.schemas import OptionQuote, OptionRight
from src.ibkr.contracts import (
    build_option,
    qualify_options,
    qualify_options_async,
    qualify_stock,
    qualify_stock_async,
)
from src.storage.db import session_scope
from src.storage.models import OptionQuoteRow

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Scalar safety helpers — NaN and None arrive from ib_async interchangeably.
# ---------------------------------------------------------------------------


def _safe(val: Any) -> float | None:
    if val is None:
        return None
    try:
        f = float(val)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def _safe_int(val: Any) -> int | None:
    f = _safe(val)
    return int(f) if f is not None else None


# ---------------------------------------------------------------------------
# Spot price (needed to build the strike band)
# ---------------------------------------------------------------------------


def _get_spot(ib: IB, stock: Any) -> float:
    ticker = ib.reqMktData(stock, snapshot=True)
    ib.sleep(1)
    price = ticker.marketPrice()
    ib.cancelMktData(stock)
    p = _safe(price)
    if p is None or math.isnan(p) or p <= 0:
        # Snapshot can return a stale cached tick (or NaN pre-market).
        # Fall back to the last daily close bar for a reliable price.
        bars = ib.reqHistoricalData(
            stock,
            endDateTime="",
            durationStr="1 D",
            barSizeSetting="1 day",
            whatToShow="TRADES",
            useRTH=True,
            keepUpToDate=False,
        )
        if bars:
            p = _safe(bars[-1].close)
    if p is None or p <= 0:
        raise ValueError(f"Could not get spot price for {stock.symbol!r}")
    return p


async def _get_spot_async(ib: IB, stock: Any) -> float:
    """Async variant of _get_spot — awaits on the loop instead of ib.sleep."""
    ticker = ib.reqMktData(stock, snapshot=True)
    await asyncio.sleep(get_config().market_data.quote_sleep_seconds)
    price = ticker.marketPrice()
    ib.cancelMktData(stock)
    p = _safe(price)
    if p is None or math.isnan(p) or p <= 0:
        # Snapshot can return a stale cached tick (or NaN pre-market).
        # Fall back to the last daily close bar for a reliable price.
        bars = await ib.reqHistoricalDataAsync(
            stock,
            endDateTime="",
            durationStr="1 D",
            barSizeSetting="1 day",
            whatToShow="TRADES",
            useRTH=True,
            keepUpToDate=False,
        )
        if bars:
            p = _safe(bars[-1].close)
    if p is None or p <= 0:
        raise ValueError(f"Could not get spot price for {stock.symbol!r}")
    return p


# ---------------------------------------------------------------------------
# Chain filtering
# ---------------------------------------------------------------------------


def _filter_expirations(expirations: Iterable[str], dte_min: int, dte_max: int) -> list[str]:
    today = date.today()
    result = []
    for exp_str in sorted(expirations):
        exp = date(int(exp_str[:4]), int(exp_str[4:6]), int(exp_str[6:]))
        dte = (exp - today).days
        if dte_min <= dte <= dte_max:
            result.append(exp_str)
    return result


def _filter_strikes(strikes: Iterable[float], spot: float, band_pct: float = 0.15) -> list[float]:
    lo, hi = spot * (1 - band_pct), spot * (1 + band_pct)
    return sorted(s for s in strikes if lo <= s <= hi)


# ---------------------------------------------------------------------------
# Batched quote fetcher — the heart of Phase 1
# ---------------------------------------------------------------------------


def _clean_bid(raw: Any) -> float | None:
    """Sanitise raw bid tick. IBKR uses -1.0 as a sentinel for 'no bid data'.
    A bid of -1.0 with a real ask would produce a wildly wrong mid-price."""
    v = _safe(raw)
    return None if (v is not None and v < 0) else v


def _ticker_to_quote(c: Option, ticker: Any) -> OptionQuote:
    """Map a (contract, ticker) pair to an OptionQuote. Pure — shared by sync + async."""
    exp_str = c.lastTradeDateOrContractMonth
    exp_date = date(int(exp_str[:4]), int(exp_str[4:6]), int(exp_str[6:]))
    right = OptionRight.CALL if c.right == "C" else OptionRight.PUT
    g = ticker.modelGreeks
    oi = _safe_int(ticker.callOpenInterest if c.right == "C" else ticker.putOpenInterest)
    return OptionQuote(
        underlying=c.symbol,
        right=right,
        strike=float(c.strike),
        expiry=exp_date,
        bid=_clean_bid(ticker.bid),
        ask=_safe(ticker.ask),
        last=_safe(ticker.last),
        volume=_safe_int(ticker.volume),
        open_interest=oi,
        iv=_safe(g.impliedVol) if g else None,
        delta=_safe(g.delta) if g else None,
        gamma=_safe(g.gamma) if g else None,
        theta=_safe(g.theta) if g else None,
        vega=_safe(g.vega) if g else None,
        greeks_source="ibkr",
    )


def _batch_quotes(
    ib: IB,
    contracts: list[Option],
    batch_size: int,
    throttle: float,
) -> list[OptionQuote]:
    """Fetch live quotes + Greeks for *contracts* in batches, respecting the line cap.

    Synchronous variant (used by the standalone backfill/healthcheck paths and tests).
    Always cancels every market-data line before opening the next batch.
    Waits at least 2 s per batch (regardless of throttle) so modelGreeks populate.
    """
    quotes: list[OptionQuote] = []
    wait = max(throttle, 2.0)

    for i in range(0, len(contracts), batch_size):
        batch = contracts[i : i + batch_size]

        tickers = [
            ib.reqMktData(c, genericTickList="101", snapshot=False, regulatorySnapshot=False)
            for c in batch
        ]
        try:
            ib.sleep(wait)

            for c, ticker in zip(batch, tickers, strict=True):
                quotes.append(_ticker_to_quote(c, ticker))
        finally:
            # Always cancel subscriptions — an exception mid-batch must not leak lines
            # against the ~100-line cap, which would break every subsequent scan.
            for c in batch:
                ib.cancelMktData(c)

        log.debug(
            "chain batch %d-%d complete (%d quotes accumulated)",
            i,
            min(i + batch_size, len(contracts)),
            len(quotes),
        )

    return quotes


async def _batch_quotes_async(
    ib: IB,
    contracts: list[Option],
    batch_size: int,
    throttle: float,
) -> list[OptionQuote]:
    """Async variant of _batch_quotes — runs on the ib_async event loop thread.

    Uses ``await asyncio.sleep`` instead of ``ib.sleep`` so it never blocks (or
    cross-threads) the loop. ``reqMktData`` is non-blocking; ticks populate via the
    loop while we await. Same batching + cancel discipline as the sync version.
    """
    quotes: list[OptionQuote] = []
    wait = max(throttle, 2.0)

    for i in range(0, len(contracts), batch_size):
        batch = contracts[i : i + batch_size]
        tickers = [
            ib.reqMktData(c, genericTickList="101", snapshot=False, regulatorySnapshot=False)
            for c in batch
        ]
        try:
            await asyncio.sleep(wait)
            for c, ticker in zip(batch, tickers, strict=True):
                quotes.append(_ticker_to_quote(c, ticker))
        finally:
            for c in batch:
                ib.cancelMktData(c)
        log.debug(
            "chain batch %d-%d complete (%d quotes accumulated)",
            i,
            min(i + batch_size, len(contracts)),
            len(quotes),
        )

    return quotes


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_option_chain_quotes(ib: IB, symbol: str) -> list[OptionQuote]:
    """Fetch the full in-scope option chain for *symbol* and return live quotes.

    Scope = expirations within the DTE window from risk_limits.yaml,
    strikes within ±15% of current spot.
    """
    cfg = get_config()
    md = cfg.market_data
    risk = cfg.risk

    dte_min = min(risk["covered_call"]["dte_min"], risk["cash_secured_put"]["dte_min"])
    dte_max = max(risk["covered_call"]["dte_max"], risk["cash_secured_put"]["dte_max"])

    stock = qualify_stock(ib, symbol)
    spot = _get_spot(ib, stock)
    log.info("get_option_chain_quotes: symbol=%s spot=%.2f", symbol, spot)

    chains = ib.reqSecDefOptParams(stock.symbol, "", stock.secType, stock.conId)
    smart = next((c for c in chains if c.exchange == "SMART"), None)
    if smart is None:
        smart = next(iter(chains), None)
    if smart is None:
        log.warning("No option chain params returned for %s", symbol)
        return []

    expirations = _filter_expirations(smart.expirations, dte_min, dte_max)
    strikes = _filter_strikes(smart.strikes, spot)
    log.info(
        "symbol=%s expirations=%s strikes=%d",
        symbol,
        expirations,
        len(strikes),
    )

    raw: list[Option] = [
        build_option(symbol, date(int(e[:4]), int(e[4:6]), int(e[6:])), st, right)
        for e in expirations
        for st in strikes
        for right in ("C", "P")
    ]

    qualified = qualify_options(ib, raw)
    if not qualified:
        log.warning("No qualified option contracts for %s", symbol)
        return []

    quotes = _batch_quotes(ib, qualified, md.chain_batch_size, md.request_throttle_seconds)
    log.info("get_option_chain_quotes: %d quotes for %s", len(quotes), symbol)
    return quotes


async def get_option_chain_quotes_async(ib: IB, symbol: str) -> list[OptionQuote]:
    """Async sibling of get_option_chain_quotes — runs every IB call on the loop thread.

    This is what the orchestrator uses: calling the sync version from a thread-pool
    executor cross-threads the ib_async event loop (the cross-thread bug ARCHITECTURE.md warns about).
    Same scope/filters as the sync version; only the await/qualify mechanics differ.
    """
    cfg = get_config()
    md = cfg.market_data
    risk = cfg.risk

    dte_min = min(risk["covered_call"]["dte_min"], risk["cash_secured_put"]["dte_min"])
    dte_max = max(risk["covered_call"]["dte_max"], risk["cash_secured_put"]["dte_max"])

    stock = await qualify_stock_async(ib, symbol)
    spot = await _get_spot_async(ib, stock)
    log.info("get_option_chain_quotes_async: symbol=%s spot=%.2f", symbol, spot)

    chains = await ib.reqSecDefOptParamsAsync(stock.symbol, "", stock.secType, stock.conId)
    smart = next((c for c in chains if c.exchange == "SMART"), None)
    if smart is None:
        smart = next(iter(chains), None)
    if smart is None:
        log.warning("No option chain params returned for %s", symbol)
        return []

    expirations = _filter_expirations(smart.expirations, dte_min, dte_max)
    strikes = _filter_strikes(smart.strikes, spot)
    log.info("symbol=%s expirations=%s strikes=%d", symbol, expirations, len(strikes))

    raw: list[Option] = [
        build_option(symbol, date(int(e[:4]), int(e[4:6]), int(e[6:])), st, right)
        for e in expirations
        for st in strikes
        for right in ("C", "P")
    ]

    qualified = await qualify_options_async(ib, raw)
    if not qualified:
        log.warning("No qualified option contracts for %s", symbol)
        return []

    quotes = await _batch_quotes_async(
        ib, qualified, md.chain_batch_size, md.request_throttle_seconds
    )
    log.info("get_option_chain_quotes_async: %d quotes for %s", len(quotes), symbol)
    return quotes


def persist_chain_quotes(symbol: str, quotes: list[OptionQuote], run_id: str) -> None:
    """Write the option chain snapshot to SQLite (one row per symbol/run)."""
    payload = [q.model_dump(mode="json") for q in quotes]
    with session_scope() as s:
        s.add(OptionQuoteRow(run_id=run_id, symbol=symbol, payload=payload))
    log.debug("persisted %d option quotes for %s (run_id=%s)", len(quotes), symbol, run_id)
