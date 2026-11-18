"""Which book a contract belongs to: the wheel, the daily credit-spread system or the value book.

The two systems share one IBKR account and one Gateway. They never share an underlying —
``config/spreads.yaml → book_underlyings`` is disjoint from ``config/universe.yaml``, enforced
by ``Config._spreads_isolated`` at load — so the underlying alone decides the book for
positions (which carry no order tag), live fills, and statement rows alike. Order ids are not
used: they are unique only per clientId, and the two systems place orders from different ones.

This is the only module through which wheel code (portfolio, rules engine, ledger) learns that
the spreads book exists. It imports nothing from ``src.spreads``.

**The value book (spec §9.2, Part 5) may share a ticker with the wheel**, so there the underlying
decides nothing: every value order carries ``orderRef = "value:<id>"``, the value book keeps its own
count V (``src/common/value_view.py``) and the wheel its own count W (from the broker-truth ledger,
``src/storage/wheel_shares.py``), never "broker minus V". ``attribute`` is the one rule both books
apply: the wheel sees ``min(W, broker - V claimed)`` shares, never below zero, so a race errs short;
if value.db cannot be read the wheel uses W alone and nothing where the broker disagrees with it.
It imports nothing from ``src.value``.

**The hedge book (risk-envelope Task 33, H9)** trades an index only it holds (XND, attributed by
underlying: ``is_hedge_underlying``) or, on the fallback route, QQQ, a universe name: there every
hedge order carries ``orderRef = "hedge:<id>"`` (``is_hedge_order_ref``) and its contracts are
known by ``conId`` through ``src/common/hedge_view.py``. It imports nothing from ``src.hedge``.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field

from src.common.config import get_config, get_hedge_cfg, hedge_index_underlyings
from src.common.value_view import ValueHolding, read_book

log = logging.getLogger(__name__)

VALUE_ORDER_PREFIX = "value:"
# The LES share book (risk-envelope Task 32a, ruling L5): every LES order carries
# ``orderRef = "les:<id>"`` and its fills are ledger ``book="les"``, outside the wheel's count W.
LES_ORDER_PREFIX = "les:"
# The hedge book (risk-envelope Task 33, ruling H9): every hedge order carries
# ``orderRef = "hedge:<id>"`` (the programme) and its executions are ledger ``book="hedge"``.
# ``hedge:claude:<id>`` is reserved for the Mastermind's paper put budget: it is a hedge ref for
# attribution, and ``risk_engine.validate_hedge`` refuses it in this build.
HEDGE_ORDER_PREFIX = "hedge:"
HEDGE_CLAUDE_PREFIX = "hedge:claude:"

# Daily-option trading classes whose statement rows name the class, not the index: an Activity
# Statement prints an SPX daily as "SPXW 07OCT26 6800 P", so its root parses as SPXW.
_DAILY_ROOTS = {"SPX": ("SPXW",), "NDX": ("NDXP",), "RUT": ("RUTW",)}


def spreads_underlyings() -> frozenset[str]:
    return frozenset(s.upper() for s in get_config().spreads.book_underlyings)


def is_spreads_underlying(symbol: str | None) -> bool:
    """True for a book underlying, or a daily trading-class root standing in for one."""
    if symbol is None:
        return False
    book = spreads_underlyings()
    sym = symbol.upper()
    return sym in book or any(sym in _DAILY_ROOTS.get(b, ()) for b in book)


def is_value_order_ref(order_ref: str | None) -> bool:
    """True for an order the value book placed (``value:<id>``): its fills are value shares."""
    return bool(order_ref) and str(order_ref).startswith(VALUE_ORDER_PREFIX)


def is_les_order_ref(order_ref: str | None) -> bool:
    """True for an LES share order (``les:<id>``, Task 32a): its fills are LES shares."""
    return bool(order_ref) and str(order_ref).startswith(LES_ORDER_PREFIX)


def hedge_underlyings() -> frozenset[str]:
    """The hedge book's own underlyings: the index ones in ``hedge.underlyings`` (XND), which
    ``Config._hedge_isolated`` keeps out of the universe and the spreads book."""
    return frozenset(hedge_index_underlyings(get_hedge_cfg()))


def is_hedge_underlying(symbol: str | None) -> bool:
    """True for an underlying only the hedge book trades (XND): its positions and executions are
    the hedge book's by underlying alone. QQQ, a universe name, is never one: a QQQ hedge is
    attributed by its ``hedge:`` orderRef and its contracts' ``conId`` instead."""
    return symbol is not None and symbol.upper() in hedge_underlyings()


def is_hedge_order_ref(order_ref: str | None) -> bool:
    """True for a hedge order (``hedge:<id>``, and the reserved ``hedge:claude:<id>``)."""
    return bool(order_ref) and str(order_ref).startswith(HEDGE_ORDER_PREFIX)


@dataclass(frozen=True, slots=True)
class Attribution:
    """One name's shares by book. ``wheel_view`` is what the wheel may write calls against and
    count as its own; ``unexplained`` is broker - (W + V filled + L): anything but zero is a
    reconcile failure (spec §9.2). ``les`` is the LES share book's count L (Task 32a)."""

    broker: float
    wheel: float
    value_filled: float
    value_claimed: float
    wheel_view: float
    unexplained: float
    les: float = 0.0


def attribute(
    broker: float, wheel: float, holding: ValueHolding | None, les: float = 0.0
) -> Attribution:
    """Spec §9.2. *holding* None means value.db could not be read: the wheel then uses W alone,
    and only where the broker agrees with W (no covered call on unexplained shares). *les* is the
    LES book's shares of the name (risk-envelope Task 32a): set aside before the wheel's view, so
    the wheel never writes a call against, counts, or trims an LES share."""
    lesq = max(0.0, les)
    if holding is None:
        view = wheel if abs(broker - lesq - wheel) < 1e-6 else 0.0
        return Attribution(broker, wheel, 0.0, 0.0, max(0.0, view), broker - lesq - wheel, lesq)
    view = max(0.0, min(wheel, broker - holding.claimed - lesq))
    return Attribution(
        broker=broker,
        wheel=wheel,
        value_filled=holding.filled,
        value_claimed=holding.claimed,
        wheel_view=view,
        unexplained=broker - (wheel + holding.filled + lesq),
        les=lesq,
    )


def value_sell_cap(value_filled: float, broker: float, wheel_short_calls: int) -> float:
    """Spec §9.2: a value sale never crosses books: at most the value lots, and never so many that
    the wheel's open short calls (100 shares each) are left uncovered, even when attribution is in
    doubt."""
    return max(0.0, min(value_filled, broker - 100.0 * max(0, wheel_short_calls)))


@dataclass(frozen=True, slots=True)
class ValueExposure:
    """What the wheel's caps must count of the value book (spec §9.3 as amended by revision 4:
    no cash is reserved; the book's actual holdings and approved-but-unfilled buys are)."""

    active: bool  # value book.enabled: otherwise nothing below applies and the wheel is unchanged
    readable: bool  # False: value.db could not be read and the book is on (fail closed)
    claim: float = 0.0  # subtracted from excess liquidity before the wheel's reserve
    by_name: dict[str, float] = field(default_factory=dict)  # value market value per name
    earmarked: float = 0.0  # approved value buys not yet filled
    frozen: frozenset[str] = frozenset()

    @property
    def gross(self) -> float:
        return sum(self.by_name.values()) + self.earmarked


def value_exposure() -> ValueExposure:
    """Spec §9.3 item 1: ``claim = Σ value market value x (1 - m) + earmarked buys``, m the
    maintenance rate (``portfolio.value_maintenance_pct``, 25%: buying $X of stock with cash
    lowers excess liquidity by only m x X, so subtracting less would hand the wheel the rest).
    Off (and free of I/O) while ``value.book.enabled`` is false, and in live: the book is paper
    only, so a paper value.db may never feed a live gate."""
    cfg = get_config()
    if not cfg.value.book.enabled or cfg.is_live:
        return ValueExposure(active=False, readable=True)
    book = read_book()
    if book is None:
        return ValueExposure(active=True, readable=False)
    m = float(cfg.risk.get("portfolio", {}).get("value_maintenance_pct", 25.0)) / 100.0
    by_name = {s: h.market_value for s, h in book.holdings.items() if h.market_value > 0}
    return ValueExposure(
        active=True,
        readable=True,
        claim=sum(by_name.values()) * (1.0 - m) + book.earmarked_usd,
        by_name=by_name,
        earmarked=book.earmarked_usd,
        frozen=book.frozen,
    )


@dataclass(frozen=True, slots=True)
class LesExposure:
    """The LES share book's holdings (risk-envelope Tasks 23, 32a): per ETF the shares bought under
    ``les:<id>`` orders (ledger ``book="les"``, ``shares``) and their market value (``by_name``),
    outside the wheel's share count. The sleeve cap counts them, leverage-weighted, with the
    sleeve's puts; the envelope counts them at leverage x the governing index's beta.
    ``readable`` False: the ledger or a price could not be read (every reader fails closed)."""

    by_name: dict[str, float] = field(default_factory=dict)
    shares: dict[str, float] = field(default_factory=dict)
    readable: bool = True

    @property
    def gross(self) -> float:
        return sum(self.by_name.values())


def les_exposure(prices: Mapping[str, float] | None = None) -> LesExposure:
    """The LES share book from the broker-truth ledger (``wheel_shares.les_shares``), each ETF
    marked at *prices*, else its latest stored close (``price_history``). Empty (and free of I/O)
    in live: the LES path is paper only, so a paper book never feeds a live gate. A ledger read
    that fails, or a held ETF with no price, is ``readable=False``."""
    if get_config().is_live:
        return LesExposure()
    try:
        from src.storage.price_history import load_bars
        from src.storage.wheel_shares import les_shares

        shares = {s: q for s, q in les_shares().items() if q > 1e-9}
        by_name: dict[str, float] = {}
        for sym, qty in shares.items():
            px = (prices or {}).get(sym)
            if not px or px <= 0:
                bars = load_bars(sym, limit=1)
                px = bars[-1].close if bars and bars[-1].close > 0 else None
            if not px:
                log.warning("LES book: no price for %s; the book reads unreadable", sym)
                return LesExposure(shares=shares, readable=False)
            by_name[sym] = qty * px
        return LesExposure(by_name=by_name, shares=shares)
    except Exception:
        log.warning("LES book unreadable (fail closed)", exc_info=True)
        return LesExposure(readable=False)


def les_by_name_for_envelope(book: LesExposure | None = None) -> dict[str, float] | None:
    """The LES book's market values for ``shock_inputs.build_inputs(les_by_name=...)``, or None
    when the book is unreadable (the envelope then reads unmeasured: fail closed)."""
    b = book if book is not None else les_exposure()
    return dict(b.by_name) if b.readable else None
