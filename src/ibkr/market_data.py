"""Market data layer: option chains, live quotes + Greeks, and IV history backfill.

Public surface:
  get_option_chain_quotes(ib, symbol) -> list[OptionQuote]

Internal helpers are module-private (_prefix) but importable by tests.
"""

from __future__ import annotations

import asyncio
import math
import time
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import yfinance as yf
from ib_async import IB, Option

from src.analytics.black_scholes import bs_delta, bs_gamma, bs_theta, bs_vega
from src.analytics.price_data import get_ohlcv
from src.common.config import get_config
from src.common.logging import get_logger
from src.common.market_hours import today_et
from src.common.schemas import OptionQuote, OptionRight
from src.ibkr.contracts import (
    build_option,
    qualify_options,
    qualify_options_async,
    qualify_stock,
    qualify_stock_async,
)

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Health-probe result (probe_market_data_health)
# ---------------------------------------------------------------------------


@dataclass
class ProbeHealth:
    """Outcome of one pre-scan data-farm health probe.

    ``healthy`` is the old boolean verdict everything downstream keys on. On failure the
    remaining fields separate *what actually happened* from *what to do about it* —
    ``diagnosis`` names the most likely root cause (from the IBKR error codes observed
    during the probe window), ``action_hint`` tells the operator the fix that actually helps.
    This exists because the pre-2026-09-09 probe collapsed every failure into "half-dead
    socket / Error 1100", which on 2026-09-08 mislabelled an Error 10197
    competing-live-session block (another login held the live-data entitlement) — a case
    where a reconnect does nothing and the operator's real fix is closing the other session.
    """

    healthy: bool
    diagnosis: str = ""
    action_hint: str = ""
    # IBKR error codes observed during the probe window, de-duplicated, sorted.
    error_codes: list[int] = field(default_factory=list)
    # The symbol the probe quoted and the timeout it waited — echoed into operator
    # messages so the numbers are traceable to config.
    probe_symbol: str = ""
    probe_timeout: float = 0.0

    def __bool__(self) -> bool:
        """Truthiness is health, so existing `if not await probe(...)` call sites stay valid."""
        return self.healthy


# ---------------------------------------------------------------------------
# Market-data line registry — guards the ~100-line cap against leaks.
# ---------------------------------------------------------------------------
#
# Every reqMktData line opened for an option chain or spot snapshot is registered here and
# removed on cancel, so a fetch interrupted between "open the line" and "cancel the line"
# (a CancelledError from the outer symbol_timeout, an exception mid-batch) can't leak the line
# against the account's ~100-line cap. A leaked line is invisible and permanent until the
# session reconnects; enough of them and every subsequent reqMktData silently never ticks —
# the failure mode behind the 2026-06-22 scan stall. The orchestrator calls
# ``drain_market_data_lines`` after any symbol times out or errors to reclaim stragglers
# before the next symbol opens its own lines.
_OPEN_LINES: dict[int, Any] = {}


def _open_line(ib: IB, contract: Any, **kwargs: Any) -> Any:
    """reqMktData for *contract* and register the open line. Returns the ticker."""
    ticker = ib.reqMktData(contract, **kwargs)
    key = getattr(contract, "conId", None) or id(contract)
    _OPEN_LINES[key] = contract
    return ticker


def _close_line(ib: IB, contract: Any) -> None:
    """cancelMktData for *contract* and deregister the line (idempotent, never raises)."""
    try:
        ib.cancelMktData(contract)
    except Exception:
        log.debug("cancelMktData failed for %s", getattr(contract, "symbol", contract))
    _OPEN_LINES.pop(getattr(contract, "conId", None) or id(contract), None)


def drain_market_data_lines(ib: IB) -> int:
    """Cancel every still-open registered market-data line. Returns the count reclaimed.

    Defence-in-depth for the ~100-line cap: called by the orchestrator after a symbol's chain
    fetch is cancelled (symbol_timeout) or errors, so a partially-cancelled batch can't leak
    lines into the next symbol's budget. Safe to call when nothing is open (returns 0)."""
    if not _OPEN_LINES:
        return 0
    n = len(_OPEN_LINES)
    for contract in list(_OPEN_LINES.values()):
        try:
            ib.cancelMktData(contract)
        except Exception:
            pass
    _OPEN_LINES.clear()
    log.warning("drain_market_data_lines: reclaimed %d leaked market-data line(s)", n)
    return n


# ---------------------------------------------------------------------------
# Black-Scholes fallback — fills delta when IBKR returns no modelGreeks.
# ---------------------------------------------------------------------------


def _enrich_greeks_from_ibkr_iv(symbol: str, spot: float, quotes: list[OptionQuote]) -> int:
    """Black-Scholes-fill missing Greeks from the **IBKR-quoted IV** for quotes missing
    a delta (S2).

    Runs *before* the yfinance fallback: whenever a quote already carries an IBKR implied vol
    (per-contract ``OptionComputation.impliedVol``, captured by ``_ticker_to_quote`` even when
    the model greeks lagged, or the generic-tick-106 underlying IV), we can compute the delta
    locally instead of pulling a second full option chain from Yahoo. Per-contract IBKR IV
    already reflects skew, so this matches the model delta closely when only the *delta* tick
    was missing.

    ``greeks_source`` becomes ``"black_scholes"`` — a BS-derived delta is not trustworthy live
    greeks, so the F6 live-execution gate must still treat it as non-IBKR. Returns the count
    enriched. Pure/cheap; never raises.
    """
    enriched = 0
    for q in quotes:
        # Skip if we already have any greek or no IV to compute.
        if (
            (
                q.delta is not None
                and q.gamma is not None
                and q.theta is not None
                and q.vega is not None
            )
            or q.iv is None
            or q.iv <= 0
        ):
            continue
        right_key = "C" if q.right == OptionRight.CALL else "P"
        # Compute missing greeks individually.
        if q.delta is None:
            delta = bs_delta(spot, q.strike, q.dte, q.iv, right_key)
            if delta is not None:
                q.delta = round(delta, 4)
        if q.gamma is None:
            gamma = bs_gamma(spot, q.strike, q.dte, q.iv, right_key)
            if gamma is not None:
                q.gamma = round(gamma, 8)
        if q.theta is None:
            theta = bs_theta(spot, q.strike, q.dte, q.iv, right_key)
            if theta is not None:
                q.theta = round(theta, 8)
        if q.vega is None:
            vega = bs_vega(spot, q.strike, q.dte, q.iv, right_key)
            if vega is not None:
                q.vega = round(vega, 8)
        # If we filled any greek, count as enriched.
        if any(v is not None for v in (q.delta, q.gamma, q.theta, q.vega)):
            q.greeks_source = "black_scholes"
            enriched += 1
    if enriched:
        log.info(
            "greeks: filled %d/%d greek(s) for %s from IBKR IV — no Yahoo fetch needed (S2)",
            enriched,
            sum(1 for q in quotes if q.greeks_source != "ibkr" or q.delta is None) + enriched,
            symbol,
        )
    return enriched


def _enrich_greeks_yf(symbol: str, spot: float, quotes: list[OptionQuote]) -> None:
    """Back-fill delta (and IV) on quotes where IBKR returned no greeks **and** no IV.

    Last-resort fallback (after IBKR per-contract greeks and ``_enrich_greeks_from_ibkr_iv``):
    pulls the yfinance option chain's implied-volatility + Black-Scholes delta. This is the
    expensive path — a second full chain download per symbol — so it only fires for quotes that
    IBKR could not value at all (delayed-data paper accounts without a market-data subscription:
    errors 354/10091 → no modelGreeks and no IV). Mutates quotes in-place; sets
    greeks_source="black_scholes". Never raises. Instrumented (S2): logs how many quotes forced
    a Yahoo fetch and how long it took, so a real paper scan reveals how often this fires.
    """
    missing = [q for q in quotes if q.delta is None]
    if not missing:
        return

    started = time.monotonic()
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
                # Compute remaining greeks via Black‑Scholes if missing.
                if q.gamma is None:
                    gamma = bs_gamma(spot, q.strike, q.dte, iv, right_key)
                    if gamma is not None:
                        q.gamma = round(gamma, 8)
                if q.theta is None:
                    theta = bs_theta(spot, q.strike, q.dte, iv, right_key)
                    if theta is not None:
                        q.theta = round(theta, 8)
                if q.vega is None:
                    vega = bs_vega(spot, q.strike, q.dte, iv, right_key)
                    if vega is not None:
                        q.vega = round(vega, 8)
                q.greeks_source = "black_scholes"
                enriched += 1

        elapsed = time.monotonic() - started
        if enriched:
            log.info(
                "greeks_fallback: Yahoo enriched %d/%d quotes for %s in %.2fs "
                "(%d expiry-chain download(s))",
                enriched,
                len(missing),
                symbol,
                elapsed,
                len(by_expiry),
            )
        else:
            log.warning(
                "greeks_fallback: %d quotes for %s have no delta after a %.2fs yfinance fallback"
                " — candidates will be empty (check market-data subscription or IV=0 entries)",
                len(missing),
                symbol,
                elapsed,
            )
    except Exception:
        log.exception(
            "greeks_fallback: yfinance lookup failed for %s after %.2fs — skipping BS enrichment",
            symbol,
            time.monotonic() - started,
        )


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
# Event-driven wait — return as soon as ticks arrive, with a hard ceiling.
# ---------------------------------------------------------------------------

# How often to re-check a ticker between reqMktData and the ceiling. ib_async populates
# ticks asynchronously on the loop while we await; a short poll lets a well-behaved symbol
# return in ~0.2-0.5s instead of always sleeping the full ceiling (the old fixed floor).
_POLL_INTERVAL_SECONDS = 0.1


async def _await_ready(predicate: Callable[[], bool], ceiling: float) -> None:
    """Await until *predicate* holds, bounded by *ceiling* seconds (a ceiling, not a floor).

    Polls every ``_POLL_INTERVAL_SECONDS`` and returns the instant *predicate* is true, so
    well-behaved symbols no longer pay the full fixed wait. Iteration count is bounded by
    ``ceiling`` (not wall-clock), so it can't spin even when ``asyncio.sleep`` is patched in
    tests. On timeout it returns silently — the caller reads whatever ticks did populate,
    exactly as the old fixed-sleep path did.
    """
    polls = max(1, int(ceiling / _POLL_INTERVAL_SECONDS))
    for _ in range(polls):
        if predicate():
            return
        await asyncio.sleep(_POLL_INTERVAL_SECONDS)


def _quote_ready(ticker: Any, right: str | None = None) -> bool:
    """True once a ticker carries a usable quote (a non-sentinel bid or an ask).

    When *right* ('C' or 'P') is given, also requires that side's open-interest tick
    (genericTick 101) to have arrived. OI streams in after the initial bid/ask tick, so
    without this a batch races ahead as soon as bid/ask populate and cancels the line before
    OI ever ticks — leaving ``open_interest`` ``None`` on most quotes even on a healthy
    connection. ``passes_liquidity_gates`` treats a missing OI as an automatic fail (a
    deliberate conservative default), so that gap alone was rejecting near-100% of quotes as
    "illiquid" regardless of how liquid the option actually was.
    """
    has_market = _clean_bid(getattr(ticker, "bid", None)) is not None or (
        _safe(getattr(ticker, "ask", None)) is not None
    )
    if not has_market or right is None:
        return has_market
    oi = ticker.callOpenInterest if right == "C" else ticker.putOpenInterest
    return _safe(oi) is not None


def _spot_ready(ticker: Any) -> bool:
    """True once a stock ticker exposes a usable price (live mark or prior close)."""
    mark = _safe(ticker.marketPrice()) if hasattr(ticker, "marketPrice") else None
    return (mark is not None and mark > 0) or (_safe(getattr(ticker, "close", None)) or 0) > 0


# ---------------------------------------------------------------------------
# Spot price (needed to build the strike band)
# ---------------------------------------------------------------------------


# Health-probe diagnosis (2026-09-09). "No tick within Ns" is a symptom with several distinct
# root causes this account has actually hit, and they need different operator responses, so
# the probe classifies from the IBKR error codes it observed during its window:
#
#   1100  TWS/Gateway lost its upstream link to IBKR — the original "half-dead" socket
#         (isConnected() stays True; every data-farm request silently never ticks). Operator:
#         check the Gateway window's own connectivity banner; the forced reconnect usually
#         recovers once Gateway's link is back.
#   10197 "No market data during competing live session" — this account holds the live-data
#         entitlement in ANOTHER login (IBKR Mobile app, a second TWS, Client Portal web
#         session, or a just-restarted Gateway that lost the race to its own predecessor).
#         A reconnect does NOT fix this; the other session must be closed (or the bot moved
#         to a second username, which IBKR supports precisely for this). Mislabelled as 1100
#         on 2026-09-08; kept distinct ever since.
#   354 / 10089 / 10090 / 10091  No market-data subscription for the probe symbol — a config
#         or entitlement problem on this account, not a socket problem at all.
#   1101/1102 flaps observed during the window mean the farm connection is being (re)built
#         right now — treat as "not settled yet" rather than pinning a cause.
#   no codes + no tick  The data farm is unreachable without IBKR naming a reason — the
#         generic half-dead state (covers, e.g., a silently wedged socket).
_HEALTH_FATAL_CODES = {10197, 354, 10089, 10090, 10091}
_HEALTH_CONNECTIVITY_CODES = {1100, 1101, 1102}


async def probe_market_data_health(ib: IB, timeout: float | None = None) -> ProbeHealth:
    """Cheap, fully-bounded liveness check for the IBKR data farm before a full scan.

    ``ib.isConnected()`` only reflects the exec-socket/TCP handshake. On a *half-dead* socket
    (TWS lost its upstream link to IBKR, Error 1100) that handshake stays up and cached calls
    like account summary still return, but every data-farm request silently never ticks. A
    scan that trusts ``isConnected()`` then grinds the whole universe at
    ``symbol_timeout_seconds`` each (~115 min for 46 symbols), monopolising the single intraday
    loop so every subsequent 15-min cycle is starved (observed 2026-06-24 02:00 SGT).

    This fires one ``reqMktData`` snapshot on ``market_data.health_probe_symbol`` and waits up
    to *timeout* seconds for any usable tick or prior close. Returns a ``ProbeHealth`` record:
    ``healthy=True`` if data flows, else ``healthy=False`` plus a ``diagnosis`` naming the most
    likely root cause and an ``action_hint`` telling the operator what actually helps. Both
    the qualify and the tick wait are bounded, so the probe itself can never hang, and it
    always reclaims its market-data line. Any IBKR error codes observed during the probe
    window (on any reqId) are recorded in ``error_codes`` — 1100/10197/354 arriving for the
    probe's own snapshot is what lets the diagnosis distinguish the three failure modes
    instead of lumping them under "half-dead socket" (2026-09-08 misdiagnosis fix).
    """
    cfg = get_config()
    if timeout is None:
        timeout = cfg.market_data.health_probe_timeout_seconds
    symbol = cfg.market_data.health_probe_symbol

    # Capture every IBKR error fired during the probe window. errorEvent emits
    # (reqId, errorCode, errorString, contract) from ib_async's wrapper — 1100/10197 arrive
    # as errorEvent emissions, NOT exceptions, so the only way to see *why* the farm is
    # silent is to listen while the probe runs. Codes on any reqId count: a competing-session
    # or farm-lost error is global, not per-request.
    seen_codes: list[int] = []

    def _on_error(req_id: int, error_code: int, error_string: str, contract: Any) -> None:
        seen_codes.append(error_code)

    ib.errorEvent += _on_error
    try:
        try:
            # A half-dead socket can hang qualify (TimeoutError) or surface a transport
            # error; either way the farm isn't answering, so treat both as unhealthy.
            stock = await asyncio.wait_for(qualify_stock_async(ib, symbol), timeout)
        except Exception:
            log.error(
                "health probe: could not qualify %s within %.0fs — socket appears half-dead",
                symbol,
                timeout,
            )
            return ProbeHealth(
                healthy=False,
                diagnosis="probe could not qualify the probe symbol within the timeout",
                action_hint=(
                    "The TWS/Gateway socket accepted the handshake but is not answering "
                    "requests at all. Forcing a reconnect is the right move."
                ),
                error_codes=sorted(set(seen_codes)),
                probe_symbol=symbol,
                probe_timeout=timeout,
            )
        ticker = _open_line(ib, stock, snapshot=True)
        try:
            await _await_ready(lambda: _spot_ready(ticker), timeout)
            healthy = _spot_ready(ticker)
        finally:
            _close_line(ib, stock)
        if healthy:
            return ProbeHealth(
                healthy=True,
                diagnosis="ok",
                action_hint="",
                error_codes=sorted(set(seen_codes)),
                probe_symbol=symbol,
                probe_timeout=timeout,
            )
        diagnosis, action_hint = _diagnose_probe_failure(seen_codes, symbol)
        log.error(
            "health probe: no market-data tick for %s within %.0fs — %s",
            symbol,
            timeout,
            diagnosis,
        )
        return ProbeHealth(
            healthy=False,
            diagnosis=diagnosis,
            action_hint=action_hint,
            error_codes=sorted(set(seen_codes)),
            probe_symbol=symbol,
            probe_timeout=timeout,
        )
    finally:
        # Always unhook: a probe listener left attached would double-log every later IBKR
        # error and slowly leak closure refs for the life of the process.
        ib.errorEvent -= _on_error


def _diagnose_probe_failure(seen_codes: list[int], symbol: str) -> tuple[str, str]:
    """Turn "the probe got no tick" + observed error codes into (diagnosis, action hint).

    Ordering matters — checked top to bottom, first match wins:
      1. 1100 seen          → the classic half-dead socket (Gateway lost its upstream link).
      2. competing-session / subscription codes → NOT a socket problem; a reconnect won't help.
      3. 1101/1102 seen    → connectivity flapping right now; retry next cycle.
      4. nothing seen      → farm unreachable, IBKR said nothing — the generic half-dead state.
    """
    codes = set(seen_codes)
    if 1100 in codes:
        return (
            "TWS/Gateway has lost its upstream link to IBKR (Error 1100) — the socket "
            "handshake stays up, but no market data can arrive",
            "Check the Gateway window: it should show a connectivity-lost banner. "
            "The forced reconnect below recovers it once Gateway's own link is back; "
            "if Gateway stays stuck, restart Gateway itself.",
        )
    fatal = codes & _HEALTH_FATAL_CODES
    if fatal:
        if 10197 in fatal:
            return (
                "Another login on this IBKR account is holding the live market-data "
                "entitlement (Error 10197: no market data during competing live session) — "
                "commonly the IBKR Mobile app, a second TWS/Gateway instance, or a Client "
                "Portal web session",
                "A reconnect will NOT fix this. Close the other logged-in session (or "
                "register a second username for the bot — IBKR supports this for exactly "
                "this case), then wait for the next cycle.",
            )
        return (
            "No market-data subscription for the probe symbol on this account "
            f"({', '.join(str(c) for c in sorted(fatal))}) — a config or entitlement "
            "problem, not a connectivity problem",
            "Check the market-data subscriptions on the account, or change "
            "market_data.health_probe_symbol in settings.yaml to something subscribed.",
        )
    if codes & _HEALTH_CONNECTIVITY_CODES:  # 1101/1102 only — 1100 was handled above
        return (
            "Gateway's data-farm connection is flapping (Errors 1101/1102 seen during the "
            "probe) — the link is being rebuilt right now",
            "Usually transient; the next 15-min cycle should recover on its own.",
        )
    return (
        "The data farm is not answering and IBKR reported no specific error — the socket "
        "appears half-dead (handshake up, no data flowing)",
        "Forcing a reconnect; the next 15-min cycle should recover. If it repeats "
        "back-to-back, restart Gateway.",
    )


def _get_spot(ib: IB, stock: Any) -> float:
    ticker = _open_line(ib, stock, snapshot=True)
    ib.sleep(1)
    price = ticker.marketPrice()
    p = _safe(price)
    if p is None or math.isnan(p) or p <= 0:
        # No live/delayed tick (weekend, no subscription) — previous close is part of the
        # same snapshot and needs no extra round trip.
        p = _safe(ticker.close)
    _close_line(ib, stock)
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
    """Async variant of _get_spot — awaits on the loop instead of ib.sleep.

    The fixed ``quote_sleep_seconds`` wait is now a *ceiling*: we return as soon as the
    snapshot exposes a price (S7), not after a flat 2s. Only reached when no cached daily
    close is available (see ``_resolve_spot_async``).
    """
    ticker = _open_line(ib, stock, snapshot=True)
    await _await_ready(lambda: _spot_ready(ticker), get_config().market_data.quote_sleep_seconds)
    price = ticker.marketPrice()
    p = _safe(price)
    if p is None or math.isnan(p) or p <= 0:
        # No live/delayed tick (weekend, no subscription) — previous close is part of the
        # same snapshot and needs no extra round trip.
        p = _safe(ticker.close)
    _close_line(ib, stock)
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


async def _resolve_spot_async(ib: IB, stock: Any, symbol: str) -> float:
    """Resolve a spot price for strike-band centring + the BS-greeks fallback (S3).

    The strike band (±15-42%) and the Black-Scholes delta back-fill don't need an exact
    RTH tick — the latest settled close from ``get_ohlcv`` (already ``@daily_cached``, so
    free after the first scan, and on a delayed/paper account essentially what the snapshot
    would return anyway) is accurate enough. Preferring it skips a dedicated
    ``reqMktData(snapshot=True)`` + ``quote_sleep_seconds`` round-trip per symbol per scan
    (~2s × ~50 symbols × ~26 intraday scans/day). Only when no cached close exists (new
    symbol, yfinance unavailable) do we fall back to the live snapshot chain in
    ``_get_spot_async`` — the ``46a21bf`` no-tick fallback is preserved intact.
    """
    try:
        df = get_ohlcv(symbol)
        if df is not None and not df.empty:
            close = _safe(df["Close"].iloc[-1])
            if close is not None and close > 0:
                return close
    except Exception:
        log.debug("resolve_spot: cached close unavailable for %s — live snapshot", symbol)
    return await _get_spot_async(ib, stock)


# ---------------------------------------------------------------------------
# Chain filtering
# ---------------------------------------------------------------------------


def _filter_expirations(expirations: Iterable[str], dte_min: int, dte_max: int) -> list[str]:
    today = today_et()
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


def _cap_strikes(strikes: list[float], spot: float, max_strikes: int) -> list[float]:
    """Keep at most *max_strikes* in-band strikes, the ones nearest *spot* (sorted ascending).

    A high-IV name at a wide band with dense ($2.50) spacing can leave 120+ in-band strikes;
    the full cartesian (strikes × expirations × 2 rights) becomes a several-hundred-contract
    qualification burst that floods IBKR with reqContractDetails for non-existent weekly strikes
    and trips a session-wedging pacing lockout (the 2026-06-22 SMH stall). The strikes nearest
    spot always cover the in-scope CC/CSP deltas, so trimming the wings is lossless for ranking.
    ``max_strikes <= 0`` disables the cap."""
    if max_strikes <= 0 or len(strikes) <= max_strikes:
        return strikes
    nearest = sorted(strikes, key=lambda s: abs(s - spot))[:max_strikes]
    return sorted(nearest)


def _build_chain_contracts(
    symbol: str, expirations: Iterable[str], strikes: Iterable[float], spot: float
) -> list[Option]:
    """Cartesian of *expirations* x in-band *strikes*, OTM side only per right.

    Builds calls only at strikes >= spot and puts only at strikes <= spot instead of both
    rights across the whole band. ``covered_call.py`` only ever keeps calls with delta in
    ``0.20-0.35`` (OTM by construction) and ``cash_secured_put.py`` only ever keeps puts with
    ``|delta|`` in ``0.15-0.30`` (also OTM by construction) — so the ITM half of the band was
    always qualified, quoted, and discarded. Skipping it here roughly halves the
    qualify/quote batch count per symbol, and therefore the wall-clock fetch time, since
    ``_batch_quotes``/``_batch_quotes_async`` cost is linear in contract count.
    """
    strikes = list(strikes)
    return [
        build_option(symbol, date(int(e[:4]), int(e[4:6]), int(e[6:])), st, right)
        for e in expirations
        for st in strikes
        for right in ("C", "P")
        if (right == "C" and st >= spot) or (right == "P" and st <= spot)
    ]


def _strike_band_pct(symbol: str, dte_days: int) -> float:
    """IV-scaled strike band for *symbol* (N6).

    Returns ``clamp(strike_band_iv_mult · IV · √(DTE/365), floor, strike_band_max_pct)`` using the
    symbol's most recent stored IV, so a high-IV name widens enough to include its ~0.25-delta
    strike but is capped (S8) so it can't explode the qualified-strike/batch count. A per-symbol
    override in ``universe.yaml → strike_bands`` wins (held to the floor, but **not** the cap — an
    explicit override is a deliberate choice); when no IV is stored the fixed floor applies.
    ``dte_days`` is the longest in-scope expiry so the band covers every expiration scanned.
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
        band = md.strike_band_iv_mult * iv * math.sqrt(dte_days / 365.0)
        return min(md.strike_band_max_pct, max(floor, band))
    return floor


# ---------------------------------------------------------------------------
# Batched quote fetcher — the heart of Phase 1
# ---------------------------------------------------------------------------


def _clean_bid(raw: Any) -> float | None:
    """Sanitise raw bid tick. IBKR uses -1.0 as a sentinel for 'no bid data'.
    A bid of -1.0 with a real ask would produce a wildly wrong mid-price."""
    v = _safe(raw)
    return None if (v is not None and v < 0) else v


# Per-contract IBKR option computations, in preference order. The model tick (13) is the
# standard source, but the bid/ask/last computation ticks (10/11/12) often arrive when the
# model tick lags — using them as a fallback gets genuine IBKR greeks onto more quotes and
# spares them the expensive Yahoo download (S2). All stream automatically; no genericTickList
# entry is needed.
_GREEK_TICK_FIELDS = ("modelGreeks", "lastGreeks", "askGreeks", "bidGreeks")


def _pick_greeks(ticker: Any) -> Any:
    """Return the first IBKR OptionComputation on *ticker* that carries a usable delta.

    Prefers ``modelGreeks``; falls back through last/ask/bid computations so a momentarily
    missing model tick doesn't force the Yahoo fallback. None if no computation has a delta.
    """
    for name in _GREEK_TICK_FIELDS:
        g = getattr(ticker, name, None)
        if g is not None and _safe(getattr(g, "delta", None)) is not None:
            return g
    return None


def _ticker_to_quote(c: Option, ticker: Any) -> OptionQuote:
    """Map a (contract, ticker) pair to an OptionQuote. Pure — shared by sync + async."""
    exp_str = c.lastTradeDateOrContractMonth
    exp_date = date(int(exp_str[:4]), int(exp_str[4:6]), int(exp_str[6:]))
    right = OptionRight.CALL if c.right == "C" else OptionRight.PUT
    g = _pick_greeks(ticker)
    # IV: prefer the per-contract computation's impliedVol; else the generic-tick-106 underlying
    # IV. Captured even when delta is absent so _enrich_greeks_from_ibkr_iv can BS-fill the delta
    # locally instead of hitting Yahoo (S2).
    iv = _safe(g.impliedVol) if g else _safe(getattr(ticker, "impliedVolatility", None))
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
        iv=iv,
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
            # 101 = option open interest; 106 = option implied volatility (S2: lets us BS-fill
            # delta from an IBKR IV instead of a second Yahoo chain download when greeks lag).
            _open_line(ib, c, genericTickList="101,106", snapshot=False, regulatorySnapshot=False)
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
                _close_line(ib, c)

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

    Uses an event-driven wait instead of ``ib.sleep``/a fixed floor: ``reqMktData`` is
    non-blocking and ticks populate via the loop, so we await until every ticker in the batch
    carries a usable bid/ask *and* its open-interest tick, bounded by the old 2s as a
    *ceiling* (S7). A well-behaved batch still returns early once both arrive. Greeks are not
    waited on — they're absent on delayed/paper data and the yfinance Black-Scholes fallback
    fills them; blocking on them would forfeit the speedup on exactly the target account.
    Same batching + cancel discipline as the sync version.

    OI (tick 101) was originally not part of the readiness check — only bid/ask — so a batch
    would race ahead and cancel the line the instant a quote appeared, before OI had a chance
    to stream in. That left ``open_interest`` ``None`` on most quotes, which
    ``passes_liquidity_gates`` treats as an automatic fail: near-100% of quotes were being
    marked illiquid regardless of real liquidity. Waiting on OI too (still bounded by the same
    ceiling) fixes that at the cost of some batches now using the full ceiling instead of
    returning at ~0.2-0.5s.
    """
    quotes: list[OptionQuote] = []
    ceiling = max(throttle, 2.0)

    for i in range(0, len(contracts), batch_size):
        batch = contracts[i : i + batch_size]
        tickers = [
            # 101 = option open interest; 106 = option implied volatility (S2: lets us BS-fill
            # delta from an IBKR IV instead of a second Yahoo chain download when greeks lag).
            _open_line(ib, c, genericTickList="101,106", snapshot=False, regulatorySnapshot=False)
            for c in batch
        ]
        try:
            # Bind the current batch's contracts/tickers (not the loop variables) for the
            # readiness check — each contract's `right` picks which OI field to wait on.
            def _batch_ready(cs: list[Option] = batch, ts: list[Any] = tickers) -> bool:
                return all(_quote_ready(t, right=c.right) for c, t in zip(cs, ts, strict=True))

            await _await_ready(_batch_ready, ceiling)
            for c, ticker in zip(batch, tickers, strict=True):
                quotes.append(_ticker_to_quote(c, ticker))
        finally:
            for c in batch:
                _close_line(ib, c)
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
    # Prefer SMART routing with non-empty expirations; some symbols return a SMART chain
    # with empty expirations (the real listings sit under a specific exchange like CBOE or
    # ARCA). Fall back to any chain that has expirations before giving up entirely.
    smart = next((c for c in chains if c.exchange == "SMART" and c.expirations), None)
    if smart is None:
        smart = next((c for c in chains if c.expirations), None)
    if smart is None:
        log.warning("No option chain params returned for %s", symbol)
        return []

    expirations = _filter_expirations(smart.expirations, dte_min, dte_max)
    band_pct = _strike_band_pct(symbol, dte_max)
    strikes = _cap_strikes(
        _filter_strikes(smart.strikes, spot, band_pct), spot, md.max_strikes_per_symbol
    )
    log.info(
        "symbol=%s expirations=%s strikes=%d band=%.0f%%",
        symbol,
        expirations,
        len(strikes),
        band_pct * 100,
    )

    raw: list[Option] = _build_chain_contracts(symbol, expirations, strikes, spot)

    qualified = qualify_options(ib, raw)
    if not qualified:
        log.warning("No qualified option contracts for %s", symbol)
        return []

    quotes = _batch_quotes(ib, qualified, md.chain_batch_size, md.request_throttle_seconds)
    # IBKR IV → Black-Scholes first (no network); Yahoo only for quotes IBKR couldn't value (S2).
    _enrich_greeks_from_ibkr_iv(symbol, spot, quotes)
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
    spot = await _resolve_spot_async(ib, stock, symbol)
    log.info("get_option_chain_quotes_async: symbol=%s spot=%.2f", symbol, spot)

    chains = await ib.reqSecDefOptParamsAsync(stock.symbol, "", stock.secType, stock.conId)
    # Prefer SMART routing with non-empty expirations; some symbols return a SMART chain
    # with empty expirations (the real listings sit under a specific exchange like CBOE or
    # ARCA). Fall back to any chain that has expirations before giving up entirely.
    smart = next((c for c in chains if c.exchange == "SMART" and c.expirations), None)
    if smart is None:
        smart = next((c for c in chains if c.expirations), None)
    if smart is None:
        log.warning("No option chain params returned for %s", symbol)
        return []

    expirations = _filter_expirations(smart.expirations, dte_min, dte_max)
    band_pct = _strike_band_pct(symbol, dte_max)
    strikes = _cap_strikes(
        _filter_strikes(smart.strikes, spot, band_pct), spot, md.max_strikes_per_symbol
    )
    log.info(
        "symbol=%s expirations=%s strikes=%d band=%.0f%%",
        symbol,
        expirations,
        len(strikes),
        band_pct * 100,
    )

    raw: list[Option] = _build_chain_contracts(symbol, expirations, strikes, spot)

    qualified = await qualify_options_async(
        ib,
        raw,
        chunk_size=md.chain_batch_size,
        throttle_seconds=md.request_throttle_seconds,
        chunk_timeout_seconds=md.qualify_timeout_seconds,
    )
    if not qualified:
        log.warning("No qualified option contracts for %s", symbol)
        return []

    quotes = await _batch_quotes_async(
        ib, qualified, md.chain_batch_size, md.request_throttle_seconds
    )
    # IBKR IV → Black-Scholes first (pure/cheap, on-loop); only quotes IBKR couldn't value at all
    # fall through to the expensive Yahoo download (S2).
    _enrich_greeks_from_ibkr_iv(symbol, spot, quotes)
    # yfinance is blocking — run off the event loop so it doesn't stall ib_async.
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _enrich_greeks_yf, symbol, spot, quotes)
    log.info("get_option_chain_quotes_async: %d quotes for %s", len(quotes), symbol)
    return quotes
