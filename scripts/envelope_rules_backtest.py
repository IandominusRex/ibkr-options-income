"""Backtest the tech-linked cap and the stacking rule (risk-envelope plan Task 27; spec §3.4.4, ruling E15).

    python -m scripts.envelope_rules_backtest [--db PATH] [--start 2026-10-13] [--end 2026-11-12] [--dry-run]

Reads the trading database **read-only** and replays each rule against two sets of cash-secured-put
opens made between ``--start`` and ``--end``:

* the ``claude_cut`` rows in ``sizing_actions`` (the puts Claude cut: the 10 the spec names), at the
  size the system proposed before the cut; and
* every other system CSP open (``orders`` with fills, not a close or a roll) that **closed at a
  profit** (bought back above the commissions, or expired with its premium beating the intrinsic
  value at the expiry close).

For each open, the situation at its decision time is rebuilt from the newest ``portfolio_snapshots``
row at or before it (positions, net liquidation), the spot on the candidate's card (else the day's
close) and the same-day CSP opens already made on the name, and the rule's own functions in
``src/engine/regime_limits.py`` (``tech_cap_contracts``, ``stacking_action``) say what it would have done:
``none``, ``trim`` (fewer contracts, including the stacking rule's halve) or ``block``.

**E15 PASS, each rule separately:** it trims or blocks at least 60% of the cut rows (6 of 10) **and**
blocks at most 25% of the profitable uncut opens. Fewer than 10 cut rows, or no profitable uncut open,
is no result. Writes ``data/envelope_reports/E15_tech_cap.json`` (switch ``tech_cap``) and
``E15_stacking.json`` (switch ``stacking_rule``) plus ``E15_report.txt``; the EOD run applies a PASS in
paper. The value book's stock is not in the tech exposure (it is not in the portfolio snapshot).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Literal

from src.analytics.shock_inputs import leverage_map
from src.common.config import get_envelope_cfg, get_regime_cfg
from src.common.schemas import EnvelopeReportResult, OptionRight, PositionSnapshot, SizingContext
from src.engine import regime_limits as rl
from src.reporting.legs import fill_economics
from src.reporting.replay import (
    Closes,
    close_on,
    et_day,
    load_closes,
    load_snapshot_at,
    make_result,
    open_ro,
    parse_stamp,
    trading_db_path,
    verdict_word,
    write_report,
    write_result,
)
from src.storage.models import FillRow

START = date(2026, 10, 13)
END = date(2026, 11, 12)
MIN_CUT_ROWS = 10
HIT_SHARE = 0.60  # 6 of 10
FALSE_BLOCK_MAX = 0.25
CRITERION = (
    "E15: the rule trims or blocks >= 6 of the 10 claude_cut rows and blocks <= 25% of the uncut system "
    "CSP opens (Oct 13-Nov 12) that closed at a profit"
)

Action = Literal["none", "trim", "block"]


@dataclass(frozen=True)
class Situation:
    """One CSP open as the rules would have seen it at its decision time."""

    key: str
    symbol: str
    strike: float
    expiry: date
    contracts: int  # what the system proposed (a cut row: the size before Claude's cut)
    spot: float | None
    nlv: float
    positions: tuple[PositionSnapshot, ...]
    same_day_fills: int  # the name's CSP opens already made that ET day


@dataclass(frozen=True)
class Opening:
    situation: Situation
    cut: bool  # a claude_cut row, else an uncut system open
    profitable: bool | None = None  # an uncut open: closed at a profit (None = not closed yet)


# --- the two rules, through the production functions ----------------------------------------


def _context() -> SizingContext:
    return SizingContext(
        regimes={},
        tech_linked=[s.upper() for s in get_regime_cfg().tech_linked],
        leverage=leverage_map(),
    )


def tech_exposure(positions: tuple[PositionSnapshot, ...], ctx: SizingContext) -> float:
    """The tech-linked exposure of a position list: stock market value plus short-put strike x 100,
    each at its leverage, summed over ``regime.tech_linked`` (the tally ``Budgets.ticker_collateral``
    keeps, without the value book's stock)."""
    tech = {t.upper() for t in ctx.tech_linked}
    total = 0.0
    for p in positions:
        name = (p.underlying or p.symbol).upper()
        if name not in tech:
            continue
        lev = ctx.leverage.get(name, 1)
        if p.sec_type == "STK":
            mv = (
                p.market_value if p.market_value is not None else p.position * (p.market_price or 0)
            )
            total += abs(mv) * lev
        elif p.sec_type == "OPT" and p.right == OptionRight.PUT and p.position < 0 and p.strike:
            total += p.strike * 100.0 * abs(p.position) * lev
    return total


def tech_cap_action(s: Situation, ctx: SizingContext, cap_pct: float) -> Action:
    """The tech-linked cap on *s*: ``block`` when no lot fits, ``trim`` when fewer than proposed."""
    lev = ctx.leverage.get(s.symbol.upper(), 1)
    fits = rl.tech_cap_contracts(
        ctx,
        s.symbol,
        tech_exposure=tech_exposure(s.positions, ctx),
        unit_weighted=s.strike * 100.0 * lev,
        net_liq=s.nlv,
        cap_pct=cap_pct,
    )
    if fits is None or fits >= s.contracts:
        return "none"
    return "block" if fits <= 0 else "trim"


def stacking_rule_action(s: Situation, overlap_days: int, fills_limit: int) -> Action:
    """The stacking rule on *s* (``halve`` is a trim)."""
    got = rl.stacking_action(
        expiry=s.expiry,
        spot=s.spot,
        shorts=rl.open_short_puts(list(s.positions), s.symbol),
        same_day_fills=s.same_day_fills,
        overlap_days=overlap_days,
        fills_limit=fills_limit,
    )
    return "trim" if got == "halve" else got


# --- the verdict ----------------------------------------------------------------------------


def judge(
    rule_id: str,
    switch: str,
    openings: list[Opening],
    act: Callable[[Situation], Action],
    *,
    now: datetime | None = None,
) -> EnvelopeReportResult:
    """One rule's E15 verdict over *openings*."""
    cuts = [o for o in openings if o.cut]
    wins = [o for o in openings if not o.cut and o.profitable is True]
    hits = sum(1 for o in cuts if act(o.situation) != "none")
    blocked = sum(1 for o in wins if act(o.situation) == "block")
    trimmed = sum(1 for o in wins if act(o.situation) == "trim")
    needed = math.ceil(HIT_SHARE * len(cuts) - 1e-9)
    rate = blocked / len(wins) if wins else None
    metrics: dict[str, float | str | None] = {
        "cut_rows": float(len(cuts)),
        "cut_rows_trimmed_or_blocked": float(hits),
        "cut_rows_needed": float(needed),
        "profitable_uncut_opens": float(len(wins)),
        "profitable_blocked": float(blocked),
        "profitable_trimmed": float(trimmed),
        "false_block_rate": None if rate is None else round(rate, 4),
    }
    if len(cuts) < MIN_CUT_ROWS:
        metrics["note"] = f"{len(cuts)} claude_cut rows, the criterion is set on {MIN_CUT_ROWS}"
        passed: bool | None = None
    elif not wins:
        metrics["note"] = "no profitable uncut system CSP open in the window"
        passed = None
    else:
        assert rate is not None
        passed = hits >= needed and rate <= FALSE_BLOCK_MAX
    return make_result(
        rule_id,
        passed=passed,
        criterion=CRITERION,
        metrics=metrics,
        switch=switch,
        value_on_pass="on",
        now=now,
    )


# --- reading the estate ---------------------------------------------------------------------


def realised_profit(
    fills: list[FillRow],
    strike: float,
    expiry: date,
    closes: list[tuple[date, float]],
    today: date,
) -> bool | None:
    """Whether a short put closed at a profit: bought back for less than it was sold for (the
    shared ``fill_economics`` rule, commissions in), or expired with its premium beating the
    intrinsic value at the expiry close. None while it is still open or cannot be valued."""
    econ = fill_economics(fills)
    if econ.entry_qty <= 0:
        return None
    bought = sum(f.filled_qty for f in fills if (f.action or "SELL").upper() == "BUY")
    if bought + 1e-9 >= econ.entry_qty:
        return econ.credit - econ.debit - econ.commissions > 0
    if expiry >= today:
        return None
    close = close_on(closes, expiry)
    if close is None:
        return None
    pnl = (econ.entry_premium - max(strike - close, 0.0)) * 100.0 * econ.entry_qty
    return pnl - econ.commissions > 0


def _json(raw: object) -> dict:
    try:
        got = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return {}
    return got if isinstance(got, dict) else {}


def load_openings(
    con, start: date, end: date, closes: Closes, *, today: date | None = None
) -> list[Opening]:
    """Every claude_cut row and uncut system CSP open between *start* and *end*, each as a
    ``Situation`` at its decision time. A row with no portfolio snapshot before it is left out
    (it cannot be rebuilt); the loader counts nothing it cannot rebuild."""
    today = today or end
    cut_rows = con.execute(
        "SELECT candidate_id, underlying, strike, expiry, deterministic_contracts, created_at, "
        "order_id FROM sizing_actions WHERE kind = 'claude_cut' AND action_day BETWEEN ? AND ? "
        "ORDER BY created_at",
        (start.isoformat(), end.isoformat()),
    ).fetchall()
    cut_candidates = {str(r["candidate_id"]) for r in cut_rows}
    order_rows = con.execute(
        "SELECT id, candidate_id, filled_qty, snapshot, created_at FROM orders "
        "WHERE close_reason IS NULL AND filled_qty > 0 ORDER BY created_at"
    ).fetchall()
    system_opens: list[
        tuple[int, str, str, date, datetime]
    ] = []  # (order id, candidate, symbol, day, at)
    parsed: dict[int, dict] = {}
    for r in order_rows:
        snap = _json(r["snapshot"])
        if snap.get("strategy") != "cash_secured_put" or snap.get("roll_from"):
            continue
        at = parse_stamp(r["created_at"])
        day = et_day(at)
        if not start <= day <= end:
            continue
        parsed[int(r["id"])] = snap
        system_opens.append(
            (int(r["id"]), str(r["candidate_id"]), str(snap.get("underlying", "")).upper(), day, at)
        )

    def same_day(symbol: str, day: date, before: datetime) -> int:
        return sum(
            1 for _, _, sym, d, at in system_opens if sym == symbol and d == day and at < before
        )

    def spot_of(candidate_id: str, symbol: str, day: date) -> float | None:
        row = con.execute(
            "SELECT payload FROM candidates WHERE candidate_id = ?", (candidate_id,)
        ).fetchone()
        px = _json(row["payload"]).get("underlying_price") if row else None
        if px:
            return float(px)
        series = closes.get(symbol)
        return close_on(series, day) if series else None

    def situation(
        key: str, symbol: str, strike: float, expiry: date, contracts: int, at: datetime, day: date
    ) -> Situation | None:
        got = load_snapshot_at(con, at)
        if got is None:
            return None
        positions, account, _ = got
        return Situation(
            key=key,
            symbol=symbol,
            strike=strike,
            expiry=expiry,
            contracts=contracts,
            spot=spot_of(key, symbol, day),
            nlv=account.net_liquidation,
            positions=tuple(positions),
            same_day_fills=same_day(symbol, day, at),
        )

    out: list[Opening] = []
    for r in cut_rows:
        at = parse_stamp(r["created_at"])
        sit = situation(
            str(r["candidate_id"]),
            str(r["underlying"]).upper(),
            float(r["strike"]),
            date.fromisoformat(str(r["expiry"])[:10]),
            int(r["deterministic_contracts"]),
            at,
            et_day(at),
        )
        if sit is not None:
            out.append(Opening(sit, cut=True))
    for order_id, candidate_id, symbol, day, at in system_opens:
        if candidate_id in cut_candidates:
            continue
        snap = parsed[order_id]
        expiry = date.fromisoformat(str(snap.get("expiry"))[:10])
        strike = float(snap.get("strike", 0.0))
        fills = [
            FillRow(
                order_id=order_id,
                candidate_id=candidate_id,
                action=str(f["action"]),
                filled_qty=float(f["filled_qty"]),
                avg_price=float(f["avg_price"]),
                commission=None if f["commission"] is None else float(f["commission"]),
            )
            for f in con.execute(
                "SELECT action, filled_qty, avg_price, commission FROM fills WHERE candidate_id = ?",
                (candidate_id,),
            )
        ]
        sit = situation(
            candidate_id, symbol, strike, expiry, int(snap.get("contracts", 1)), at, day
        )
        if sit is not None:
            out.append(
                Opening(
                    sit,
                    cut=False,
                    profitable=realised_profit(
                        fills, strike, expiry, closes.get(symbol, []), today
                    ),
                )
            )
    return out


def _report(openings: list[Opening], results: dict[str, EnvelopeReportResult], acts: dict) -> str:
    lines = [
        f"{'cut row':<26} {'size':>4} {'tech cap':>9} {'stacking':>9}",
    ]
    for o in (o for o in openings if o.cut):
        s = o.situation
        name = f"{s.symbol} {s.strike:g}P {s.expiry:%m-%d}"
        lines.append(f"{name:<26} {s.contracts:>4} {acts['tech'](s):>9} {acts['stack'](s):>9}")
    wins = [o for o in openings if not o.cut and o.profitable is True]
    lines.append(f"\nprofitable uncut system opens: {len(wins)}")
    for key, label in (("E15_tech_cap", "tech cap"), ("E15_stacking", "stacking")):
        r = results[key]
        m = r.metrics
        lines.append(
            f"{label:<9} trims/blocks {m['cut_rows_trimmed_or_blocked']:.0f} of "
            f"{m['cut_rows']:.0f} cut rows (need {m['cut_rows_needed']:.0f}); blocks "
            f"{m['profitable_blocked']:.0f} of {len(wins)} profitable opens "
            f"(rate {m['false_block_rate']}, max {FALSE_BLOCK_MAX}): {verdict_word(r.passed)}"
        )
        if "note" in m:
            lines.append(f"  {m['note']}")
    return "\n".join(lines)


def run(
    db_path: Path, start: date = START, end: date = END
) -> tuple[str, dict[str, EnvelopeReportResult] | None]:
    """The report text and the two results (None when the database cannot be read)."""
    try:
        con = open_ro(db_path)
    except FileNotFoundError:
        return f"No trading database at {db_path}: nothing to replay.", None
    try:
        symbols = sorted(
            {
                str(r[0]).upper()
                for r in con.execute(
                    "SELECT DISTINCT underlying FROM sizing_actions WHERE kind = 'claude_cut'"
                )
            }
            | {
                str(_json(r[0]).get("underlying", "")).upper()
                for r in con.execute("SELECT snapshot FROM orders WHERE close_reason IS NULL")
            }
        )
        closes = load_closes(con, [s for s in symbols if s])
        openings = load_openings(con, start, end, closes)
    finally:
        con.close()
    ctx = _context()
    cfg = get_envelope_cfg()
    acts = {
        "tech": lambda s: tech_cap_action(s, ctx, cfg.tech_cap_pct),
        "stack": lambda s: stacking_rule_action(
            s, cfg.stacking.overlap_days, cfg.stacking.same_day_fills
        ),
    }
    results = {
        "E15_tech_cap": judge("E15_tech_cap", "tech_cap", openings, acts["tech"]),
        "E15_stacking": judge("E15_stacking", "stacking_rule", openings, acts["stack"]),
    }
    return _report(openings, results, acts), results


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="E15: backtest the tech-linked cap and the stacking rule"
    )
    ap.add_argument("--db", type=Path, default=None, help="trading DB or a copy (default: config)")
    ap.add_argument("--start", type=date.fromisoformat, default=START)
    ap.add_argument("--end", type=date.fromisoformat, default=END)
    ap.add_argument("--dry-run", action="store_true", help="print, write nothing")
    args = ap.parse_args(argv)
    text, results = run(args.db or trading_db_path(), args.start, args.end)
    print(text)
    if results is None:
        return 2
    if not args.dry_run:
        for r in results.values():
            print(f"wrote {write_result(r)}")
        print(f"wrote {write_report('E15', text)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
