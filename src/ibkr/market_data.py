"""Market data layer: option chains, live quotes + Greeks, and IV history backfill.

Public surface:
  get_option_chain_quotes(ib, symbol) -> list[OptionQuote]
  persist_chain_quotes(symbol, quotes, run_id) -> None

Internal helpers are module-private (_prefix) but importable by tests.
"""

from __future__ import annotations

import asyncio
import math
from collections import defaultdict
from collections.abc import Iterable
from datetime import date
from typing import Any

import yfinance as yf
from ib_async import IB, Option

from src.analytics.black_scholes import bs_delta
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
# Black-Scholes fallback — fills delta when IBKR returns no modelGreeks.
# ---------------------------------------------------------------------------


def _enrich_greeks_yf(symbol: str, spot: float, quotes: list[OptionQuote]) -> None:
    """Back-fill delta (and IV) on quotes where IBKR returned no modelGreeks.

    Uses yfinance option chain implied-volatility + Black-Scholes delta.
    Mutates quotes in-place; sets greeks_source="black_scholes" on each enriched quote.
    Never raises — logs a warning on total failure and returns silently on partial failure.
    This is needed on paper accounts without a market-data subscription: delayed data
    (errors 354/10091) produces no modelGreeks, causing delta=None and zero candidates.
    """
    missing = [q for q in quotes if q.delta is None]
    if not missing:
        return

    try:
        ticker = yf.Ticker(symbol)
        available: set[str] = set(ticker.options)

        by_expiry: dict[date, list[OptionQuote]] = defaultdict(list)
        for q in missing:
            by_expiry[q.expiry].append(q)

        enriched = 0
        for exp_date, exp_quotes in by_expiry.items():
            exp_str = exp_date.strftime("%Y-%m-%d")
            if exp_str not in available:
                log.debug("greeks_fallback: %s expiry %s not in yfinance chain", symbol, exp_str)
                continue

            chain = ticker.option_chain(exp_str)
            iv_map: dict[tuple[str, float], float] = {}
            for row in chain.calls.itertuples(index=False):
                iv_map[("C", float(row.strike))] = float(row.impliedVolatility)
            for row in chain.puts.itertuples(index=False):
                iv_map[("P", float(row.strike))] = float(row.impliedVolatility)

            for q in exp_quotes:
                right_key = "C" if q.right == OptionRight.CALL else "P"
                iv = iv_map.get((right_key, q.strike))
                if iv is None or iv <= 0 or math.isnan(iv):
                    continue
                delta = bs_delta(spot, q.strike, q.dte, iv, right_key)
                if delta is None:
                    continue
                q.delta = round(delta, 4)
                if q.iv is None:
                    q.iv = round(iv, 6)
                q.greeks_source = "black_scholes"
                enriched += 1

        if enriched:
            log.info(
                "greeks_fallback: enriched %d/%d quotes for %s via Black-Scholes",
                enriched,
                len(missing),
                symbol,
            )
        else:
            log.warning(
                "greeks_fallback: %d quotes for %s have no delta after yfinance fallback"
                " — candidates will be empty (check market-data subscription or IV=0 entries)",
                len(missing),
                symbol,
            )
    except Exception:
        log.exception("greeks_fallback: yfinance lookup failed for %s — skipping BS enrichment", symbol)


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
    p = _safe(price)
    if p is None or math.isnan(p) or p <= 0:
        # No live/delayed tick (weekend, no subscription) — previous close is part of the
        # same snapshot and needs no extra round trip.
        p = _safe(ticker.close)
    ib.cancelMktData(stock)
    if p is None or p <= 0:
        # Last resort: a tightly-bounded historical bar. ib_async's reqHistoricalData
        # defaults to a 60s timeout — without spot_history_timeout_seconds, a symbol with
        # no live tick AND no previous close would stall this long.
        bars = ib.reqHistoricalData(
            stock,
            endDateTime="",
            durationStr="1 D",
            barSizeSetting="1 day",
            whatToShow="TRADES",
            useRTH=True,
            keepUpToDate=False,
            timeout=get_config().market_data.spot_history_timeout_seconds,
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
    p = _safe(price)
    if p is None or math.isnan(p) or p <= 0:
        # No live/delayed tick (weekend, no subscription) — previous close is part of the
        # same snapshot and needs no extra round trip.
        p = _safe(ticker.close)
    ib.cancelMktData(stock)
    if p is None or p <= 0:
        # Last resort: a tightly-bounded historical bar. ib_async's reqHistoricalDataAsync
        # defaults to a 60s timeout — without spot_history_timeout_seconds, a symbol with
        # no live tick AND no previous close would stall this long (this was the dominant
        # cost of /scan on weekends: ~60s x every symbol).
        bars = await ib.reqHistoricalDataAsync(
            stock,
            endDateTime="",
            durationStr="1 D",
            barSizeSetting="1 day",
            whatToShow="TRADES",
            useRTH=True,
            keepUpToDate=False,
            timeout=get_config().market_data.spot_history_timeout_seconds,
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


def _strike_band_pct(symbol: str, dte_days: int) -> float:
    """IV-scaled strike band for *symbol* (N6).

    Returns ``max(strike_band_pct, strike_band_iv_mult · IV · √(DTE/365))`` using the symbol's
    most recent stored IV, so a high-IV name widens enough to include its ~0.25-delta strike.
    A per-symbol override in ``universe.yaml → strike_bands`` wins (never below the floor); when
    no IV is stored yet the fixed floor applies. ``dte_days`` is the longest in-scope expiry so
    the band covers every expiration being scanned.
    """
    cfg = get_config()
    md = cfg.market_data
    floor = md.strike_band_pct

    override = cfg.universe.get("strike_bands", {}).get(symbol)
    if override is not None:
        return max(floor, float(override))

    from src.storage.iv_history import latest_iv

    iv = latest_iv(symbol)  # annualised vol as a fraction
    if iv and iv > 0 and dte_days > 0:
        return max(floor, md.strike_band_iv_mult * iv * math.sqrt(dte_days / 365.0))
    return floor


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
    band_pct = _strike_band_pct(symbol, dte_max)
    strikes = _filter_strikes(smart.strikes, spot, band_pct)
    log.info(
        "symbol=%s expirations=%s strikes=%d band=%.0f%%",
        symbol,
        expirations,
        len(strikes),
        band_pct * 100,
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
    _enrich_greeks_yf(symbol, spot, quotes)
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
    band_pct = _strike_band_pct(symbol, dte_max)
    strikes = _filter_strikes(smart.strikes, spot, band_pct)
    log.info(
        "symbol=%s expirations=%s strikes=%d band=%.0f%%",
        symbol,
        expirations,
        len(strikes),
        band_pct * 100,
    )

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
    # yfinance is blocking — run off the event loop so it doesn't stall ib_async.
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _enrich_greeks_yf, symbol, spot, quotes)
    log.info("get_option_chain_quotes_async: %d quotes for %s", len(quotes), symbol)
    return quotes


def persist_chain_quotes(symbol: str, quotes: list[OptionQuote], run_id: str) -> None:
    """Write the option chain snapshot to SQLite (one row per symbol/run)."""
    payload = [q.model_dump(mode="json") for q in quotes]
    with session_scope() as s:
        s.add(OptionQuoteRow(run_id=run_id, symbol=symbol, payload=payload))
    log.debug("persisted %d option quotes for %s (run_id=%s)", len(quotes), symbol, run_id)
