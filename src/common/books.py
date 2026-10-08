"""Which book a contract belongs to: the wheel, or the daily credit-spread system.

The two systems share one IBKR account and one Gateway. They never share an underlying —
``config/spreads.yaml → book_underlyings`` is disjoint from ``config/universe.yaml``, enforced
by ``Config._spreads_isolated`` at load — so the underlying alone decides the book for
positions (which carry no order tag), live fills, and statement rows alike. Order ids are not
used: they are unique only per clientId, and the two systems place orders from different ones.

This is the only module through which wheel code (portfolio, rules engine, ledger) learns that
the spreads book exists. It imports nothing from ``src.spreads``.
"""

from __future__ import annotations

from src.common.config import get_config

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
