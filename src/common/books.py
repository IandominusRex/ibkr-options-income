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


def spreads_underlyings() -> frozenset[str]:
    return frozenset(s.upper() for s in get_config().spreads.book_underlyings)


def is_spreads_underlying(symbol: str | None) -> bool:
    return symbol is not None and symbol.upper() in spreads_underlyings()
