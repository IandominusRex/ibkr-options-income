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
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.common.config import get_config
from src.common.value_view import ValueHolding, read_book

VALUE_ORDER_PREFIX = "value:"

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


@dataclass(frozen=True, slots=True)
class Attribution:
    """One name's shares by book. ``wheel_view`` is what the wheel may write calls against and
    count as its own; ``unexplained`` is broker - (W + V filled): anything but zero is a reconcile
    failure (spec §9.2)."""

    broker: float
    wheel: float
    value_filled: float
    value_claimed: float
    wheel_view: float
    unexplained: float


def attribute(broker: float, wheel: float, holding: ValueHolding | None) -> Attribution:
    """Spec §9.2. *holding* None means value.db could not be read: the wheel then uses W alone,
    and only where the broker agrees with W (no covered call on unexplained shares)."""
    if holding is None:
        view = wheel if abs(broker - wheel) < 1e-6 else 0.0
        return Attribution(broker, wheel, 0.0, 0.0, max(0.0, view), broker - wheel)
    view = max(0.0, min(wheel, broker - holding.claimed))
    return Attribution(
        broker=broker,
        wheel=wheel,
        value_filled=holding.filled,
        value_claimed=holding.claimed,
        wheel_view=view,
        unexplained=broker - (wheel + holding.filled),
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
    Off (and free of I/O) while ``value.book.enabled`` is false."""
    cfg = get_config()
    if not cfg.value.book.enabled:
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
