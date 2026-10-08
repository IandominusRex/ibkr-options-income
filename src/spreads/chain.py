"""IBKR I/O for the spreads system — chains, quotes, spot, account, broker legs.

Every subscription goes through ``req_fresh_mkt_data`` and is cancelled before the next batch,
so at most ``max_market_data_lines`` lines are ever open from this clientId (the ~100-line cap
is shared by every clientId on the login — CLAUDE.md "Safety"). ib_async objects become
``ChainOption`` / ``ChainSnapshot`` here and nowhere else in ``src/spreads``.
"""

from __future__ import annotations

import asyncio
import logging
import math
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, date, datetime
from typing import Any

from ib_async import Index, Option, Stock

from src.common.books import is_spreads_underlying
from src.common.config import SpreadsCfg
from src.common.market_hours import is_rth
from src.common.schemas import ChainOption, ChainSnapshot, SessionSnapshot
from src.ibkr.contracts import qualify_options_async
from src.ibkr.market_data import req_fresh_mkt_data
from src.spreads.pricing import ET

log = logging.getLogger(__name__)

_SENTINEL = 1e300  # IB reports "no value" as sys.float_info.max


def _num(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if math.isnan(v) or math.isinf(v) or abs(v) >= _SENTINEL:
        return None
    return v


def to_chain_option(contract: Any, ticker: Any) -> ChainOption:
    right = "C" if str(contract.right).upper().startswith("C") else "P"
    exp = str(contract.lastTradeDateOrContractMonth)[:8]
    g = getattr(ticker, "modelGreeks", None)
    bid = _num(getattr(ticker, "bid", None))
    ask = _num(getattr(ticker, "ask", None))
    # A missing bid stays None here even beside a live ask: ib_async writes NaN both for a
    # size-0 bid (no buyers) and for one whose tick hasn't arrived, and can't say which. The
    # exit math (manager.debit_to_close) reads a missing bid as a no-bid market; ``quote``
    # gives a late bid a short grace first.
    oi = _num(getattr(ticker, "callOpenInterest" if right == "C" else "putOpenInterest", None))
    return ChainOption(
        strike=float(contract.strike),
        right=right,  # type: ignore[arg-type]
        expiry=date(int(exp[:4]), int(exp[4:6]), int(exp[6:8])),
        bid=bid if bid is not None and bid >= 0 else None,
        ask=ask if ask is not None and ask > 0 else None,
        iv=_num(getattr(g, "impliedVol", None)) if g is not None else None,
        delta=_num(getattr(g, "delta", None)) if g is not None else None,
        open_interest=int(oi) if oi is not None and oi >= 0 else None,
        con_id=int(getattr(contract, "conId", 0) or 0) or None,
    )


def band_strikes(strikes: Iterable[float], spot: float, band_pct: float) -> list[float]:
    return sorted(float(k) for k in strikes if abs(float(k) - spot) <= spot * band_pct)


def next_expiries(expirations: Iterable[str], today: date, n: int) -> list[str]:
    floor = today.strftime("%Y%m%d")
    return sorted(e for e in expirations if e >= floor)[: max(n, 0)]


def pick_chain(chains: Sequence[Any], trading_class: str) -> Any | None:
    matches = [c for c in chains if c.tradingClass == trading_class and c.expirations]
    if not matches:
        return None
    return max(matches, key=lambda c: (c.exchange == "SMART", len(c.expirations), len(c.strikes)))


def parity_spot(options: list[ChainOption], guess: float) -> float | None:
    """Put-call parity (r≈0 intraday): S ≈ K + C − P at the fully quoted strike nearest *guess*."""
    if not options:
        return None
    earliest = min(o.expiry for o in options)
    mids: dict[float, dict[str, float]] = {}
    for o in options:
        m = o.mid
        if o.expiry == earliest and m is not None:
            mids.setdefault(o.strike, {})[o.right] = m
    both = [k for k, v in mids.items() if "C" in v and "P" in v]
    if not both:
        return None
    k = min(both, key=lambda s: abs(s - guess))
    return k + mids[k]["C"] - mids[k]["P"]


async def _wait(predicate: Callable[[], bool], ceiling: float) -> None:
    deadline = asyncio.get_running_loop().time() + ceiling
    while not predicate() and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.05)


def _all_asked(pairs: list[tuple[Any, Any]]) -> Callable[[], bool]:
    """A predicate bound to this batch (a lambda in the batch loop trips ruff B023)."""
    return lambda: all(_num(getattr(t, "ask", None)) is not None for _, t in pairs)


def _all_bid(pairs: list[tuple[Any, Any]]) -> Callable[[], bool]:
    """Every leg with a live ask also has its bid — the bid tick usually lands first, but not
    always, and a late one would otherwise read as nobody bidding."""

    def ready() -> bool:
        for _, t in pairs:
            ask, bid = _num(getattr(t, "ask", None)), _num(getattr(t, "bid", None))
            if ask is not None and ask > 0 and (bid is None or bid < 0):
                return False
        return True

    return ready


def _contract_key(c: Any) -> Any:
    con_id = int(getattr(c, "conId", 0) or 0)
    return con_id or id(c)


class IbkrSpreadsBroker:
    def __init__(
        self,
        ib: Any,
        cfg: SpreadsCfg,
        account: str,
        *,
        quote_wait_seconds: float = 3.0,
        bid_grace_seconds: float = 0.75,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.ib = ib
        self.cfg = cfg
        self.account = account
        self.max_lines = max(1, cfg.max_market_data_lines)
        self.quote_wait = quote_wait_seconds
        self.bid_grace = bid_grace_seconds
        self.now = now
        self._indexes: dict[str, Any] = {}

    async def _index(self, symbol: str, exchange: str, sec_type: str = "IND") -> Any:
        """The qualified underlying: an ``Index`` (SPX, XSP) or a ``Stock`` (SPY), cached once
        qualified — a qualification that failed (a Gateway hiccup) is retried next time, never
        cached with ``conId=0`` for the rest of the session."""
        if symbol not in self._indexes:
            idx = (
                Stock(symbol, exchange, "USD")
                if sec_type == "STK"
                else Index(symbol, exchange, "USD")
            )
            try:
                await self.ib.qualifyContractsAsync(idx)
            except Exception:
                log.exception("spreads: could not qualify %s", symbol)
            if not getattr(idx, "conId", 0):
                return idx
            self._indexes[symbol] = idx
        return self._indexes[symbol]

    async def index_spot(self, symbol: str, exchange: str, sec_type: str = "IND") -> float | None:
        """Last print. Outside regular hours the prior close stands in; during them a missing
        print is None, never yesterday's close passed off as the live spot. None without the
        data entitlement or an unqualified contract."""
        idx = await self._index(symbol, exchange, sec_type)
        if not getattr(idx, "conId", 0):
            return None
        t = req_fresh_mkt_data(self.ib, idx, "", False, False)
        try:
            await _wait(
                lambda: (
                    _num(getattr(t, "last", None)) is not None
                    or _num(getattr(t, "close", None)) is not None
                ),
                self.quote_wait,
            )
            value = _num(getattr(t, "last", None))
            if value is None and not is_rth(self.now()):
                value = _num(getattr(t, "close", None))
            return value if value is not None and value > 0 else None
        finally:
            self.ib.cancelMktData(idx)

    async def spot(self) -> float | None:
        return await self.index_spot(
            self.cfg.underlying, self.cfg.exchange, self.cfg.underlying_sec_type
        )

    async def session_quote(self) -> SessionSnapshot | None:
        """The traded index now, with IBKR's session stats (open/high/low/prior close ticks).

        The entry trigger's tape (``tape.SessionTape``) is fed from here every tick. A missing
        stat stays ``None``; the tape keeps the last known value.
        """
        idx = await self._index(
            self.cfg.underlying, self.cfg.exchange, self.cfg.underlying_sec_type
        )
        if not getattr(idx, "conId", 0):
            return None
        t = req_fresh_mkt_data(self.ib, idx, "", False, False)
        try:
            await _wait(
                lambda: all(_num(getattr(t, f, None)) is not None for f in ("last", "high", "low")),
                self.quote_wait,
            )
            last = _num(getattr(t, "last", None))
            if last is None or last <= 0:
                return None

            def stat(name: str) -> float | None:
                v = _num(getattr(t, name, None))
                return v if v is not None and v > 0 else None

            return SessionSnapshot(
                as_of=self.now(),
                last=last,
                open=stat("open"),
                high=stat("high"),
                low=stat("low"),
                prior_close=stat("close"),
            )
        finally:
            self.ib.cancelMktData(idx)

    async def quote(self, contracts: list[Any]) -> list[ChainOption]:
        """One quote per input contract, in order. Each distinct contract is subscribed once:
        ib_async keys a ticker's reqId by ticker, so a second subscription to the same contract
        overwrites the first's and one ``cancelMktData`` would leave a line open for good."""
        unique: dict[Any, Any] = {}
        for c in contracts:
            unique.setdefault(_contract_key(c), c)
        distinct = list(unique.values())
        quoted: dict[Any, ChainOption] = {}
        for i in range(0, len(distinct), self.max_lines):
            batch = distinct[i : i + self.max_lines]
            pairs = [(c, req_fresh_mkt_data(self.ib, c, "101,106", False, False)) for c in batch]
            try:
                await _wait(_all_asked(pairs), self.quote_wait)
                await _wait(_all_bid(pairs), self.bid_grace)
                for c, t in pairs:
                    quoted[_contract_key(c)] = to_chain_option(c, t)
            finally:
                for c, _ in pairs:
                    self.ib.cancelMktData(c)
        return [quoted[_contract_key(c)] for c in contracts]

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
    ) -> ChainSnapshot | None:
        idx = await self._index(symbol, exchange, sec_type)
        if not getattr(idx, "conId", 0):
            log.warning("spreads: %s is not qualified yet — no chain this pass", symbol)
            return None
        spot = await self.index_spot(symbol, exchange, sec_type)
        if spot is None:
            spot = spot_hint
        if spot is None:
            log.warning("spreads: no %s index price (index-data subscription?) and no hint", symbol)
            return None
        params = await self.ib.reqSecDefOptParamsAsync(symbol, "", sec_type, idx.conId)
        chain = pick_chain(params, trading_class)
        if chain is None:
            log.warning("spreads: no %s option chain with tradingClass %s", symbol, trading_class)
            return None
        today = self.now().astimezone(ET).date()
        exps = next_expiries(chain.expirations, today, expiries)
        strikes = band_strikes(chain.strikes, spot, band_pct)
        contracts = [
            Option(symbol, e, k, r, "SMART", tradingClass=trading_class)
            for e in exps
            for k in strikes
            for r in ("C", "P")
        ]
        qualified = await qualify_options_async(self.ib, contracts, chunk_size=self.max_lines)
        options = await self.quote(qualified)
        implied = parity_spot(options, spot)
        if implied is not None and abs(implied - spot) / spot > 0.002:
            log.warning("spreads: %s index %.2f vs parity-implied %.2f", symbol, spot, implied)
        return ChainSnapshot(symbol=symbol, spot=spot, as_of=self.now(), options=options)

    async def requote(self, legs: list[ChainOption]) -> list[ChainOption]:
        contracts = []
        for leg in legs:
            c = Option(
                self.cfg.underlying,
                f"{leg.expiry:%Y%m%d}",
                leg.strike,
                leg.right,
                "SMART",
                tradingClass=self.cfg.trading_class,
            )
            if leg.con_id:
                c.conId = leg.con_id
            contracts.append(c)
        unknown = [c for c in contracts if not c.conId]
        if unknown:
            await qualify_options_async(self.ib, unknown, chunk_size=self.max_lines)
        return await self.quote([c for c in contracts if c.conId])

    async def excess_liquidity(self) -> float | None:
        """In USD, from the account-update stream ib_async keeps (no reqAccountSummary: Error
        322). A non-USD base account reports it in its base currency; that is converted with
        the stream's own ``ExchangeRate`` for USD (base units per USD). None if it can't be."""
        excess: dict[str, float] = {}
        usd_rate: float | None = None
        for v in self.ib.accountValues(self.account):
            if getattr(v, "account", self.account) != self.account:
                continue
            num = _num(v.value)
            if num is None:
                continue
            if v.tag == "ExcessLiquidity":
                excess[v.currency] = num
            elif v.tag == "ExchangeRate" and v.currency == "USD" and num > 0:
                usd_rate = num
        if "USD" in excess:
            return excess["USD"]
        local = {c: x for c, x in excess.items() if c != "BASE"}
        base = excess.get("BASE", next(iter(local.values())) if len(local) == 1 else None)
        if base is None or usd_rate is None:
            return None
        return base / usd_rate

    def working_refs(self) -> set[str]:
        """``orderRef`` of every spreads order IBKR still shows working for this clientId."""
        prefix = self.cfg.order_ref_prefix
        refs: set[str] = set()
        for t in self.ib.openTrades():
            ref = str(getattr(t.order, "orderRef", "") or "")
            if ref.startswith(prefix):
                refs.add(ref)
        return refs

    def broker_legs(self) -> dict[int, float]:
        legs: dict[int, float] = defaultdict(float)
        for p in self.ib.positions():
            c = p.contract
            if p.account == self.account and c.secType == "OPT" and is_spreads_underlying(c.symbol):
                legs[int(c.conId)] += float(p.position)
        return {k: v for k, v in legs.items() if v}
