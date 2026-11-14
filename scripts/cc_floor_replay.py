"""The covered-call floor replay (risk-envelope plan Task 29; spec §3.7.1, ruling E12).

    python -m scripts.cc_floor_replay [--db PATH] [--since DATE] [--dry-run]

Reads the trading database **read-only**. On the held stock names (shares of 100 or more, a basis
from the snapshot's ``avg_cost``), every 21 sessions of the ``price_history`` panel it sells a 30-day
covered call, valued by Black-Scholes at the name's stored IV, for each floor on the strike
(``covered_call.min_strike_vs_basis``): **1.00** (the live rule, delta 0.25), **0.95** (delta 0.25)
and **0.90** (delta 0.20). A floor leaves a name out for a month when the call's strike would sit
under ``basis x floor``. Per floor it reports the premium sold, the calls, the call-aways and the
upside forgone on them (the close over the strike at expiry), and the mean S10 of the book with
those calls on (full revaluation, ``src/analytics/shock.py``).

**E12 PASS for a floor below 1.00:** its extra premium over the 1.00 floor, less its extra upside
forgone over the 1.00 floor, is at least 0, **and** its mean S10 is not higher than at 1.00. The lowest
passing floor is applied: ``E12.json`` (``switch="cc_basis_floor"``, ``value_on_pass`` the floor; a
FAIL records ``1.00``). **The leveraged class** has its own result: no floor at delta 0.25 on the held
leveraged ETFs (every name in the leverage map); it passes when its premium less its upside forgone
nets at least 0 (``E12_leveraged.json``, switch ``leveraged_cc_auto``). Until it does, a leveraged
call is tap-only. The EOD run applies PASSes (paper only). Nothing readable, nothing written.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from pathlib import Path

from src.analytics.black_scholes import bs_price
from src.analytics.shock import measure
from src.analytics.shock_inputs import leverage_map
from src.common.envelope_types import BookLine, ShockInputs
from src.common.schemas import EnvelopeReportResult, PositionSnapshot
from src.reporting.replay import (
    BookContext,
    Closes,
    close_on,
    load_book_context,
    make_result,
    open_ro,
    strike_for_delta,
    trading_db_path,
    verdict_word,
    write_report,
    write_result,
)

FLOORS = (0.90, 0.95, 1.00)  # tried lowest first: the lowest passing one is applied
DELTA = {1.00: 0.25, 0.95: 0.25, 0.90: 0.20}
LEVERAGED_DELTA = 0.25
DTE = 30
EVERY_SESSIONS = 21
CRITERION = (
    "E12: for a floor below 1.00, extra premium vs 1.00 - extra upside forgone on call-aways >= 0 over the "
    "panel and mean S10 not higher than at 1.00; the lowest passing floor is applied"
)
CRITERION_LEVERAGED = (
    "E12 (leveraged class): no basis floor at call delta <= 0.25 on the held leveraged ETFs nets "
    "premium - upside forgone >= 0 over the panel"
)
_EPS = 1e-6


@dataclass(frozen=True)
class Holding:
    symbol: str
    shares: int
    basis: float


@dataclass(frozen=True)
class FloorResult:
    floor: float | None  # None = no floor
    premium: float  # dollars sold
    forgone: float  # dollars of upside given up on call-aways
    calls: int  # contracts sold
    called_away: int  # contracts called away
    mean_s10: float | None  # mean S10 over the sale dates (None when no date was measured)
    sale_dates: int


def holdings_of(positions: Sequence[PositionSnapshot], *, leveraged: bool) -> list[Holding]:
    """Held stock of 100 shares or more with a positive basis: the leveraged ETFs or the rest."""
    lev = set(leverage_map())
    out: dict[str, Holding] = {}
    for p in positions:
        if p.sec_type != "STK" or p.position < 100 or p.avg_cost <= 0:
            continue
        sym = (p.underlying or p.symbol).upper()
        if (sym in lev) != leveraged:
            continue
        out[sym] = Holding(sym, int(p.position // 100) * 100, float(p.avg_cost))
    return sorted(out.values(), key=lambda h: h.symbol) if out else []


def sale_days(closes: Closes, start: date | None = None) -> list[date]:
    """Every ``EVERY_SESSIONS``-th session of the panel (SPY's calendar, else the longest series),
    leaving room for the 30-day call to expire inside it."""
    ref = "SPY" if "SPY" in closes else max(closes, key=lambda s: len(closes[s]), default="")
    days = [d for d, _ in closes.get(ref, []) if start is None or d >= start]
    if not days:
        return []
    last = days[-1] - timedelta(days=DTE)
    return [d for d in days[::EVERY_SESSIONS] if d <= last]


def replay_floor(
    book: ShockInputs,
    holdings: Sequence[Holding],
    closes: Closes,
    ivs: dict[str, float],
    *,
    floor: float | None,
    delta: float,
    days: Sequence[date],
) -> FloorResult:
    """The covered calls sold each month under *floor* (None = no floor): premium, call-aways,
    upside forgone and the mean S10 of the book with the calls on."""
    premium = forgone = 0.0
    calls = away = 0
    s10: list[float] = []
    for d in days:
        lines: list[BookLine] = []
        measurable = True
        for h in holdings:
            series, iv = closes.get(h.symbol), ivs.get(h.symbol)
            spot = close_on(series, d) if series else None
            if spot is None or iv is None:
                measurable = False
                continue
            lines.append(BookLine(h.symbol, "stock", float(h.shares), spot))
            strike = strike_for_delta(spot, DTE, iv, delta, "C")
            if strike is None or (floor is not None and strike < h.basis * floor - _EPS):
                continue
            n = h.shares // 100
            px = bs_price(spot, strike, DTE, iv, "C")
            if px is None:
                continue
            premium += px * 100.0 * n
            calls += n
            lines.append(
                BookLine(h.symbol, "short_call", float(n), spot, strike=strike, dte=DTE, iv=iv)
            )
            final = close_on(series, d + timedelta(days=DTE))
            if final is not None and final > strike:
                away += n
                forgone += (final - strike) * 100.0 * n
        if measurable and lines:
            res = measure(replace(book, lines=tuple(lines)))
            if res.measured:
                s10.append(res.s10)
    return FloorResult(
        floor,
        premium,
        forgone,
        calls,
        away,
        sum(s10) / len(s10) if s10 else None,
        len(days),
    )


def e12_result(
    by_floor: dict[float, FloorResult], *, now: datetime | None = None
) -> EnvelopeReportResult:
    """The E12 verdict from the three floors' results: the lowest passing floor below 1.00, else a
    recorded FAIL carrying 1.00. No calls at the 1.00 floor *and* none below is no result."""
    base = by_floor[1.00]
    metrics: dict[str, float | str | None] = {}
    chosen: float | None = None
    for floor in FLOORS:
        r = by_floor[floor]
        extra_premium = r.premium - base.premium
        extra_forgone = r.forgone - base.forgone
        net = extra_premium - extra_forgone
        s10_ok = (
            r.mean_s10 is not None
            and base.mean_s10 is not None
            and r.mean_s10 <= base.mean_s10 + _EPS
        )
        key = f"floor_{floor:.2f}"
        metrics[f"{key}_premium"] = round(r.premium, 2)
        metrics[f"{key}_forgone"] = round(r.forgone, 2)
        metrics[f"{key}_calls"] = float(r.calls)
        metrics[f"{key}_called_away"] = float(r.called_away)
        metrics[f"{key}_mean_s10"] = None if r.mean_s10 is None else round(r.mean_s10, 3)
        if floor < 1.0:
            metrics[f"{key}_net_vs_1.00"] = round(net, 2)
            # a floor that sold nothing the 1.00 floor did not has no evidence behind it
            if chosen is None and r.calls > base.calls and net >= -_EPS and s10_ok:
                chosen = floor
    if base.sale_dates == 0 or (base.calls == 0 and all(by_floor[f].calls == 0 for f in FLOORS)):
        metrics["note"] = "no covered call could be sold on the panel at any floor"
        return make_result(
            "E12",
            passed=None,
            criterion=CRITERION,
            metrics=metrics,
            switch="cc_basis_floor",
            value_on_pass="1.00",
            now=now,
        )
    metrics["chosen_floor"] = f"{chosen:.2f}" if chosen is not None else "1.00"
    return make_result(
        "E12",
        passed=chosen is not None,
        criterion=CRITERION,
        metrics=metrics,
        switch="cc_basis_floor",
        value_on_pass=f"{chosen:.2f}" if chosen is not None else "1.00",
        now=now,
    )


def leveraged_result(r: FloorResult | None, *, now: datetime | None = None) -> EnvelopeReportResult:
    """The leveraged class's own verdict: premium less upside forgone at no floor, delta 0.25."""
    metrics: dict[str, float | str | None] = {}
    passed: bool | None = None
    if r is None or r.calls == 0:
        metrics["note"] = (
            "no leveraged ETF held (100 shares or more) with a call to sell on the panel"
        )
    else:
        net = r.premium - r.forgone
        metrics.update(
            premium=round(r.premium, 2),
            forgone=round(r.forgone, 2),
            net=round(net, 2),
            calls=float(r.calls),
            called_away=float(r.called_away),
        )
        passed = net >= -_EPS
    return make_result(
        "E12_leveraged",
        passed=passed,
        criterion=CRITERION_LEVERAGED,
        metrics=metrics,
        switch="leveraged_cc_auto",
        value_on_pass="on",
        now=now,
    )


def evaluate(
    ctx: BookContext, *, since: date | None = None
) -> tuple[dict[float, FloorResult], FloorResult | None, list[Holding], list[Holding]]:
    days = sale_days(ctx.closes, since)
    plain = holdings_of(ctx.positions, leveraged=False)
    lev = holdings_of(ctx.positions, leveraged=True)
    by_floor = {
        f: replay_floor(ctx.inputs, plain, ctx.closes, ctx.ivs, floor=f, delta=DELTA[f], days=days)
        for f in FLOORS
    }
    lev_result = (
        replay_floor(
            ctx.inputs, lev, ctx.closes, ctx.ivs, floor=None, delta=LEVERAGED_DELTA, days=days
        )
        if lev
        else None
    )
    return by_floor, lev_result, plain, lev


def _text(
    by_floor: dict[float, FloorResult],
    lev: FloorResult | None,
    plain: list[Holding],
    levs: list[Holding],
    e12: EnvelopeReportResult,
    e12l: EnvelopeReportResult,
) -> str:
    lines = [
        f"held stock names: {', '.join(h.symbol for h in plain) or 'none'}; "
        f"leveraged: {', '.join(h.symbol for h in levs) or 'none'}",
        f"{'floor':>6} {'delta':>5} {'calls':>6} {'away':>5} {'premium $':>11} {'forgone $':>11} "
        f"{'mean S10 %':>11}",
    ]
    for f in sorted(by_floor, reverse=True):
        r = by_floor[f]
        s10 = f"{r.mean_s10:.2f}" if r.mean_s10 is not None else "n/a"
        lines.append(
            f"{f:>6.2f} {DELTA[f]:>5.2f} {r.calls:>6} {r.called_away:>5} {r.premium:>11,.0f} "
            f"{r.forgone:>11,.0f} {s10:>11}"
        )
    if lev is not None:
        lines.append(
            f"{'none':>6} {LEVERAGED_DELTA:>5.2f} {lev.calls:>6} {lev.called_away:>5} "
            f"{lev.premium:>11,.0f} {lev.forgone:>11,.0f}   (leveraged ETFs)"
        )
    lines += [
        "",
        f"E12: {verdict_word(e12.passed)}"
        + (f" -> floor {e12.value_on_pass}" if e12.passed else ""),
        f"E12 leveraged: {verdict_word(e12l.passed)}",
    ]
    for r in (e12, e12l):
        if "note" in r.metrics:
            lines.append(f"  {r.id}: {r.metrics['note']}")
    return "\n".join(lines)


def run(
    db_path: Path, *, since: date | None = None
) -> tuple[str, tuple[EnvelopeReportResult, EnvelopeReportResult] | None]:
    """The report text and the two results (None when nothing could be read)."""
    try:
        con = open_ro(db_path)
    except FileNotFoundError:
        return f"No trading database at {db_path}: nothing to replay.", None
    try:
        try:
            ctx = load_book_context(con, since=since)
        except LookupError as exc:
            return f"{exc}: nothing to replay.", None
    finally:
        con.close()
    by_floor, lev, plain, levs = evaluate(ctx, since=since)
    e12, e12l = e12_result(by_floor), leveraged_result(lev)
    return _text(by_floor, lev, plain, levs, e12, e12l), (e12, e12l)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="E12: the covered-call floor replay")
    ap.add_argument("--db", type=Path, default=None, help="trading DB or a copy (default: config)")
    ap.add_argument("--since", type=date.fromisoformat, default=None, help="panel start")
    ap.add_argument("--dry-run", action="store_true", help="print, write nothing")
    args = ap.parse_args(argv)
    text, results = run(args.db or trading_db_path(), since=args.since)
    print(text)
    if results is None:
        return 2
    if not args.dry_run:
        for r in results:
            print(f"wrote {write_result(r)}")
        print(f"wrote {write_report('E12', text)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
