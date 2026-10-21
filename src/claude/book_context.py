"""The trade reviewer's view of the book (spec section 9, operator decision 23).

In the week of 2026-10-13 the reviewer said "sell" on all twelve TQQQ and SOXL candidates with
nothing in its prompt about the positions already open on those names, the stop-outs of the last
few days, or the correlated names beside them. This block shows it: for each reviewed underlying
and the names related to it (the same ``sectors`` tag, or both tech-linked), the open short
options (strike, expiry, in or out of the money), the shares held and their cost, the stop-outs of
the last five days, and the book's net delta.

Enrichment tier: the block reaches the prompt and nothing else. It reads the positions it is
handed and, for stop-outs, the trading database (loss-exit fills), read-only; it writes nothing and
is never imported by ``engine/``, ``execution/``, ``strategies/`` or ``spreads/``.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from src.common.config import get_config, get_regime_cfg
from src.common.market_hours import today_et
from src.common.schemas import OptionRight, PositionSnapshot, TradeCandidate
from src.storage.db import session_scope
from src.storage.models import FillRow, OrderRow

log = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")
_HEADER = "=== YOUR BOOK ==="
_STOPOUT_DAYS = 5
# Bounds so the block stays a few hundred tokens however large the book is.
_MAX_OPTION_LINES_PER_NAME = 8
_MAX_STOPOUT_LINES_PER_NAME = 3
_MAX_LINES = 36


def _sym(position: PositionSnapshot) -> str:
    return (position.underlying or position.symbol).upper()


def _related(name: str, reviewed: str, sectors: dict[str, str], tech: set[str]) -> bool:
    if name == reviewed:
        return True
    if name in tech and reviewed in tech:
        return True
    sector = sectors.get(reviewed)
    return sector is not None and sectors.get(name) == sector


def _money(spot: float | None, strike: float, right: OptionRight) -> str:
    if spot is None:
        return ""
    itm = spot < strike if right == OptionRight.PUT else spot > strike
    return f" ({'ITM' if itm else 'OTM'}, spot ${spot:,.2f})"


def _strike(v: float) -> str:
    return f"{v:g}"


def _option_line(p: PositionSnapshot, spot: float | None) -> str:
    side = "short" if p.position < 0 else "long"
    qty = f"{abs(p.position):g}"
    if p.strike is None or p.right is None:
        return f"  {side} {qty} {p.symbol}"
    expiry = f" {p.expiry.isoformat()}" if p.expiry else ""
    return (
        f"  {side} {qty} {_strike(p.strike)}{p.right.value}{expiry}"
        f"{_money(spot, p.strike, p.right)}"
    )


def _share_line(p: PositionSnapshot) -> str:
    side = "short " if p.position < 0 else ""
    return f"  {side}{abs(p.position):g} shares @ ${p.avg_cost:,.2f} cost"


def render_book(
    candidates: list[TradeCandidate],
    positions: list[PositionSnapshot],
    *,
    stopouts: dict[str, list[str]],
    tech_linked: list[str],
    net_delta: float | None,
    spots: dict[str, float] | None = None,
) -> str:
    """The ``=== YOUR BOOK ===`` block for the reviewed *candidates*.

    *stopouts* maps an underlying to pre-rendered stop-out lines of the last few days (see
    ``load_stopouts``); *spots* maps an underlying to its current price so an option reads ITM or
    OTM (a candidate's own ideal-zone spot is the fallback). Only names with something to show are
    listed: an open position or a recent stop-out.
    """
    tech = {t.upper() for t in tech_linked}
    sectors = {
        str(k).upper(): str(v) for k, v in (get_config().universe.get("sectors") or {}).items()
    }
    reviewed: list[str] = []
    for c in candidates:
        if c.underlying.upper() not in reviewed:
            reviewed.append(c.underlying.upper())

    spot_of: dict[str, float] = {}
    for c in candidates:
        ideal_spot = getattr(c.ideal, "spot", None)
        if isinstance(ideal_spot, int | float) and ideal_spot > 0:
            spot_of.setdefault(c.underlying.upper(), float(ideal_spot))
    for k, v in (spots or {}).items():
        if v and v > 0:
            spot_of[k.upper()] = float(v)

    held: dict[str, list[PositionSnapshot]] = {}
    for p in positions:
        held.setdefault(_sym(p), []).append(p)
    out_names = {k.upper(): v for k, v in stopouts.items() if v}
    present = list(dict.fromkeys([*held, *out_names]))

    # The reviewed names first, then what is related to them, each once and in a stable order.
    scope: list[tuple[str, str | None]] = []
    for r in reviewed:
        if r in present and all(r != s for s, _ in scope):
            scope.append((r, None))
    for r in reviewed:
        for name in sorted(present):
            if name != r and all(name != s for s, _ in scope) and _related(name, r, sectors, tech):
                scope.append((name, r))

    lines: list[str] = [_HEADER]
    if net_delta is not None:
        lines.append(f"Net delta of the whole book: {net_delta:+,.0f} share-equivalents")
    if not scope:
        lines.append(
            "No open positions or recent stop-outs on the reviewed names or the names related to them."
        )
        return "\n".join(lines)

    omitted = 0
    for name, related_to in scope:
        block: list[str] = [name if related_to is None else f"{name} (related to {related_to})"]
        mine = held.get(name, [])
        shares = [p for p in mine if p.sec_type == "STK" and p.position != 0]
        options = sorted(
            (p for p in mine if p.sec_type == "OPT" and p.position != 0),
            key=lambda p: (p.expiry or date.max, p.strike or 0.0),
        )
        block += [_share_line(p) for p in shares]
        block += [_option_line(p, spot_of.get(name)) for p in options[:_MAX_OPTION_LINES_PER_NAME]]
        if len(options) > _MAX_OPTION_LINES_PER_NAME:
            block.append(f"  (+{len(options) - _MAX_OPTION_LINES_PER_NAME} more option positions)")
        block += [f"  stop-out {s}" for s in out_names.get(name, [])[:_MAX_STOPOUT_LINES_PER_NAME]]
        if len(block) == 1:
            continue
        if len(lines) + len(block) > _MAX_LINES:
            omitted += 1
            continue
        lines += block
    if omitted:
        lines.append(f"(+{omitted} more related names not shown)")
    return "\n".join(lines)


def _fallback_close_parts(candidate_id: str | None) -> tuple[str, float, str, date] | None:
    """``close:SOXL:20261016:130:P`` -> (underlying, strike, right, expiry), or None."""
    if not candidate_id or not candidate_id.startswith("close:"):
        return None
    parts = candidate_id.split(":")
    if len(parts) < 5:
        return None
    try:
        expiry = datetime.strptime(parts[2], "%Y%m%d").date()
        return parts[1].upper(), float(parts[3]), parts[4].upper(), expiry
    except ValueError:
        return None


def load_stopouts(*, days: int = _STOPOUT_DAYS, today: date | None = None) -> dict[str, list[str]]:
    """Loss-exit buy-to-close fills of the last *days* calendar days, by underlying, as lines like
    ``Oct 21: 78P Oct 23 x10 (sold $1.20, bought back $3.10)``. Read-only; never raises."""
    day = today or today_et()
    start = datetime.combine(day - timedelta(days=days), datetime.min.time(), tzinfo=_ET)
    since = start.astimezone(UTC).replace(tzinfo=None)
    out: dict[str, list[str]] = {}
    try:
        with session_scope() as s:
            fills = (
                s.query(FillRow)
                .filter(
                    FillRow.action == "BUY",
                    FillRow.close_reason == "loss_exit",
                    FillRow.filled_at >= since,
                )
                .order_by(FillRow.filled_at.desc())
                .all()
            )
            for fill in fills:
                snap = next(
                    (
                        snapshot
                        for (snapshot,) in s.query(OrderRow.snapshot).filter(
                            OrderRow.candidate_id == fill.candidate_id
                        )
                        if isinstance(snapshot, dict) and snapshot.get("underlying")
                    ),
                    None,
                )
                sold: float | None = None
                if snap is not None:
                    underlying = str(snap["underlying"]).upper()
                    strike = snap.get("strike")
                    right = snap.get("right")
                    try:
                        expiry: date | None = date.fromisoformat(str(snap.get("expiry"))[:10])
                    except ValueError:
                        expiry = None
                    sold = (
                        snap.get("premium")
                        if isinstance(snap.get("premium"), int | float)
                        else None
                    )
                else:
                    parsed = _fallback_close_parts(fill.candidate_id)
                    if parsed is None:
                        continue
                    underlying, strike, right, expiry = parsed
                when = fill.filled_at.replace(tzinfo=UTC).astimezone(_ET).date()
                contract = (
                    f"{_strike(float(strike))}{right} {expiry:%b %d}"
                    if isinstance(strike, int | float) and right and expiry
                    else "an option"
                )
                prices = f"bought back ${fill.avg_price:.2f}"
                if sold is not None:
                    prices = f"sold ${sold:.2f}, {prices}"
                out.setdefault(underlying, []).append(
                    f"{when:%b %d}: {contract} x{fill.filled_qty:g} ({prices})"
                )
    except Exception:  # noqa: BLE001 - a missing table or a locked file must not fail a review
        log.warning("book: could not read recent stop-outs", exc_info=True)
        return {}
    return out


def _net_delta(positions: list[PositionSnapshot]) -> float:
    """The book's net delta in share-equivalents (the same sum the EOD summary uses)."""
    options = sum((p.delta or 0.0) * p.position * 100 for p in positions if p.sec_type == "OPT")
    return options + sum(p.position for p in positions if p.sec_type == "STK")


def build_book_block(
    candidates: list[TradeCandidate],
    positions: list[PositionSnapshot],
    *,
    spots: dict[str, float] | None = None,
) -> str:
    """The reviewer's book block for this scan, or an empty string when it cannot be built."""
    try:
        try:
            tech_linked = get_regime_cfg().tech_linked
        except Exception:  # noqa: BLE001 - an invalid regime block must not blank the book
            tech_linked = []
        return render_book(
            candidates,
            positions,
            stopouts=load_stopouts(),
            tech_linked=tech_linked,
            net_delta=_net_delta(positions),
            spots=spots,
        )
    except Exception:  # noqa: BLE001
        log.warning("book: block not built", exc_info=True)
        return ""
