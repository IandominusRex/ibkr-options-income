"""The hedge menu: which put legs are worth quoting, and what the allowed items are
(risk-envelope Task 16; spec §3.10.5, ruling H5).

Pure: plain data in, plain data out, no I/O. The allowed shapes are an outright long put and a put
vertical (one long, one short, same expiry, 1:1) at least ``vertical_min_width_pct`` of spot wide.
Never a ratio, a calendar, a diagonal or a short-only item. The floors (DTE >= ``dte_floor``,
long |delta| >= the band's low edge) stop the menu offering the short-dated far-OTM put that buys
S10 cheaply and decays to nothing on a slow slide.

Two steps, because the long leg's delta only arrives with its quote:

1. ``candidate_strikes`` picks which (expiry, strike) contracts to quote, from the listed chain;
2. ``build_menu`` turns the quotes into items, and ``default_item`` picks the one with the best
   *minimum* protection per premium dollar across the five scenarios (see ``SCENARIO_MOVES``).

Deterministic tier: imports no enrichment.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Literal

from src.common.config import HedgeCfg

# The index move each envelope scenario implies for the hedged index, as a fraction of spot: S10
# and G10 are -10%, S20, T20 and P20 are -20% (spec §3.10.5: the default item is the best minimum
# protection per premium dollar across {S10, S20, T20, G10, P20}). A put's intrinsic payoff at
# each move is the proxy; Task 36's size rule replaces this ranking with the full revaluation.
SCENARIO_MOVES: dict[str, float] = {"S10": 0.10, "S20": 0.20, "T20": 0.20, "G10": 0.10, "P20": 0.20}

# Long strikes worth quoting, as fractions of spot (a 0.15-0.30 delta put at 60-120 DTE sits
# around 0.88-0.96 of spot at 15-30% IV), and the widths the short legs are placed at.
_LONG_GRID: tuple[float, ...] = (0.87, 0.89, 0.91, 0.93, 0.95, 0.97)
_SHORT_WIDTH_PCTS: tuple[float, ...] = (10.0, 15.0)
_TARGET_DTE = 90
_MAX_EXPIRIES = 2


@dataclass(frozen=True, slots=True)
class HedgeQuote:
    """One quoted put, as plain data (the capture converts ib_async tickers into this)."""

    strike: float
    right: str
    expiry: date
    bid: float | None = None
    ask: float | None = None
    bid_size: float | None = None
    ask_size: float | None = None
    delta: float | None = None
    con_id: int | None = None
    iv: float | None = None  # the leg's model IV (decimal), when the quote carried one

    @property
    def mid(self) -> float | None:
        """The mid of a two-sided quote, else None (a leg nobody bids has no price)."""
        if self.bid is None or self.ask is None or self.bid <= 0 or self.ask <= 0:
            return None
        return (self.bid + self.ask) / 2.0

    @property
    def spread_pct(self) -> float | None:
        """(ask - bid) / mid in percent; None for a one-sided or missing quote."""
        m = self.mid
        if m is None or self.bid is None or self.ask is None:
            return None
        return (self.ask - self.bid) / m * 100.0


@dataclass(frozen=True, slots=True)
class HedgeMenuItem:
    item_key: str
    kind: Literal["outright", "vertical"]
    expiry: date
    dte: int
    long: HedgeQuote
    short: HedgeQuote | None
    debit: float | None  # mid debit per share; None when a leg has no two-sided price
    delta: float  # the long leg's |delta|
    width_pct: float | None  # the vertical's width, % of spot

    @property
    def legs(self) -> list[tuple[str, HedgeQuote]]:
        out = [("long", self.long)]
        if self.short is not None:
            out.append(("short", self.short))
        return out


def item_key(long: HedgeQuote, short: HedgeQuote | None) -> str:
    base = f"P{long.strike:g}"
    if short is not None:
        base += f"/{short.strike:g}"
    return f"{base}@{long.expiry:%Y%m%d}"


def _nearest(strikes: list[float], target: float) -> float:
    return min(strikes, key=lambda k: abs(k - target))


def candidate_strikes(
    strikes: Iterable[float],
    expirations: Iterable[date],
    spot: float,
    cfg: HedgeCfg,
    *,
    today: date,
) -> list[tuple[date, float]]:
    """The (expiry, strike) contracts to quote: for up to two expiries in the DTE window nearest
    90 days, the listed strikes nearest each long grid point and, below each, the listed strike at
    or just beyond ``vertical_min_width_pct`` and 15% of spot. Sorted, de-duplicated."""
    listed = sorted({float(k) for k in strikes if k > 0})
    if not listed or spot <= 0:
        return []
    lo, hi = cfg.dte_window
    in_window = sorted(
        (e for e in set(expirations) if max(lo, cfg.dte_floor) <= (e - today).days <= hi),
        key=lambda e: (abs((e - today).days - _TARGET_DTE), e),
    )[:_MAX_EXPIRIES]
    longs = sorted({_nearest(listed, spot * g) for g in _LONG_GRID})
    shorts: set[float] = set()
    for k in longs:
        for w in _SHORT_WIDTH_PCTS:
            w = max(w, cfg.vertical_min_width_pct)
            at_or_below = [s for s in listed if s <= k - spot * w / 100.0 + 1e-9]
            if at_or_below:
                shorts.add(max(at_or_below))
    return sorted((e, k) for e in in_window for k in sorted({*longs, *shorts}))


def build_menu(
    chain: Iterable[HedgeQuote], spot: float, cfg: HedgeCfg, *, today: date
) -> list[HedgeMenuItem]:
    """The allowed items over the quoted puts.

    An item needs a put long leg that expires in ``dte_window`` (never under ``dte_floor``) with a
    known |delta| in ``long_delta``. It is an outright, or a vertical with a lower-strike put short
    leg of the same expiry at least ``vertical_min_width_pct`` of spot below. Calls, calendars,
    ratios and short-only items cannot be built from this. ``debit`` is None when a leg has no
    two-sided quote (the item stays on the menu so the capture records its thin market).
    """
    if spot <= 0:
        return []
    lo, hi = cfg.dte_window
    dlo, dhi = cfg.long_delta
    puts = [q for q in chain if q.right.upper().startswith("P")]
    by_expiry: dict[date, list[HedgeQuote]] = {}
    for q in puts:
        by_expiry.setdefault(q.expiry, []).append(q)
    items: list[HedgeMenuItem] = []
    for expiry, legs in sorted(by_expiry.items()):
        dte = (expiry - today).days
        if dte < cfg.dte_floor or not lo <= dte <= hi:
            continue
        for long in sorted(legs, key=lambda q: q.strike):
            if long.delta is None:
                continue
            ld = abs(long.delta)
            if not (dlo - 1e-9 <= ld <= dhi + 1e-9) or ld < 0.15 - 1e-9:
                continue
            lmid = long.mid
            items.append(
                HedgeMenuItem(
                    item_key(long, None),
                    "outright",
                    expiry,
                    dte,
                    long,
                    None,
                    lmid,
                    ld,
                    None,
                )
            )
            for short in sorted(legs, key=lambda q: -q.strike):
                width_pct = (long.strike - short.strike) / spot * 100.0
                if short.strike >= long.strike or width_pct < cfg.vertical_min_width_pct - 1e-9:
                    continue
                smid = short.mid
                debit = lmid - smid if lmid is not None and smid is not None else None
                items.append(
                    HedgeMenuItem(
                        item_key(long, short),
                        "vertical",
                        expiry,
                        dte,
                        long,
                        short,
                        debit,
                        ld,
                        width_pct,
                    )
                )
    return items


def payoff_at(item: HedgeMenuItem, spot: float, move: float) -> float:
    """The item's intrinsic payoff per share if the index falls ``move`` (a fraction) from spot."""
    s = spot * (1.0 - move)
    pay = max(0.0, item.long.strike - s)
    if item.short is not None:
        pay -= max(0.0, item.short.strike - s)
    return pay


def protection_per_dollar(item: HedgeMenuItem, spot: float) -> float | None:
    """The minimum, over ``SCENARIO_MOVES``, of intrinsic payoff per premium dollar; None when the
    item has no positive mid debit."""
    if item.debit is None or item.debit <= 0:
        return None
    return min(payoff_at(item, spot, m) for m in SCENARIO_MOVES.values()) / item.debit


def default_item(items: Iterable[HedgeMenuItem], spot: float) -> HedgeMenuItem | None:
    """The priced item with the best minimum protection per premium dollar (ties: the lower
    debit, then the key). None when no item has a price."""
    best: tuple[float, float, str] | None = None
    pick: HedgeMenuItem | None = None
    for it in items:
        p = protection_per_dollar(it, spot)
        if p is None or p <= 0 or it.debit is None:
            continue
        rank = (-p, it.debit, it.item_key)
        if best is None or rank < best:
            best, pick = rank, it
    return pick


def protected_points(item: HedgeMenuItem, spot: float) -> float:
    """The S10 payoff per share, in index points (the denominator of the H4 cost comparison)."""
    return payoff_at(item, spot, SCENARIO_MOVES["S10"])
