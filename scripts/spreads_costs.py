"""Measure the spreads cost standard against the record (risk-envelope Task 5, spec §3.2f).

    python -m scripts.spreads_costs [--db data/spreads.db]

Reads ``data/spreads.db`` read-only (SQLite ``mode=ro``, plain SQL) and prints, per instrument,
the median and 90th percentile of the entry crossing (``credit_mid − credit_natural`` of every
gated candidate, per spread side) beside the modelled slippage per leg, and the modelled
commission per leg (IBKR's commission plus the exchange fee) beside what paper fills were
actually charged per leg. An instrument whose exchange fee is not yet filled from IBKR's
schedule is reported as blocked. The candidates carry no instrument column, so every candidate
is attributed to the configured ``trading_class`` (the book trades one class at a time).
"""

from __future__ import annotations

import argparse
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from src.common.config import ROOT, SpreadsCfg, get_config
from src.spreads.menu import fee_per_contract, slippage_per_leg


@dataclass(frozen=True)
class InstrumentCosts:
    instrument: str
    candidates: int
    median_crossing: float | None  # per spread side, per share
    p90_crossing: float | None
    modelled_slippage_per_leg: float
    modelled_commission_per_leg: float | None  # None: the exchange fee is unknown
    blocked: bool


@dataclass(frozen=True)
class CostReport:
    instruments: list[InstrumentCosts]
    paper_commission_per_leg: float | None
    paper_legs: int


def connect_ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def _quantile(values: list[float], q: float) -> float | None:
    """Linear interpolation between order statistics (numpy's default)."""
    if not values:
        return None
    xs = sorted(values)
    pos = q * (len(xs) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (pos - lo) * (xs[hi] - xs[lo])


def measure(path: Path, cfg: SpreadsCfg) -> CostReport:
    con = connect_ro(path)
    try:
        crossings = [
            float(mid) - float(nat)
            for mid, nat in con.execute(
                "SELECT credit_mid, credit_natural FROM spread_candidates "
                "WHERE credit_mid IS NOT NULL AND credit_natural IS NOT NULL"
            )
        ]
        paid, legs = con.execute(
            "SELECT COALESCE(SUM(o.commission), 0), COALESCE(SUM(2 * o.filled_qty), 0) "
            "FROM spread_orders o JOIN spread_positions p ON p.spread_id = o.spread_id "
            "WHERE p.mode = 'paper' AND o.filled_qty > 0"
        ).fetchone()
    finally:
        con.close()
    fee = fee_per_contract(cfg)
    instrument = InstrumentCosts(
        instrument=cfg.trading_class,
        candidates=len(crossings),
        median_crossing=_quantile(crossings, 0.5),
        p90_crossing=_quantile(crossings, 0.9),
        modelled_slippage_per_leg=slippage_per_leg(cfg),
        modelled_commission_per_leg=(
            None if fee is None else cfg.execution.commission_per_contract + fee
        ),
        blocked=fee is None,
    )
    return CostReport(
        instruments=[instrument],
        paper_commission_per_leg=float(paid) / legs if legs else None,
        paper_legs=int(legs),
    )


def _usd(x: float | None) -> str:
    return "n/a" if x is None else f"${x:.3f}"


def print_report(report: CostReport) -> None:
    for r in report.instruments:
        if r.blocked:
            print(
                f"{r.instrument}: BLOCKED, no exchange fee yet (fill execution.exchange_fees "
                "from IBKR's published schedule)"
            )
            continue
        print(
            f"{r.instrument}: {r.candidates} candidates, median crossing "
            f"{_usd(r.median_crossing)}, p90 {_usd(r.p90_crossing)} per spread side; the "
            f"standard charges {_usd(r.modelled_slippage_per_leg)} per leg "
            f"({_usd(2 * r.modelled_slippage_per_leg)} per spread side)"
        )
        print(
            f"  commission: modelled {_usd(r.modelled_commission_per_leg)} per leg, paper "
            f"commission {_usd(report.paper_commission_per_leg)} per leg over "
            f"{report.paper_legs} filled legs"
        )


def main(argv: list[str] | None = None) -> None:
    cfg = get_config().spreads
    default = Path(cfg.db_url.removeprefix("sqlite:///"))
    p = argparse.ArgumentParser(description="Measure the spreads cost standard")
    p.add_argument("--db", type=Path, default=default)
    a = p.parse_args(argv)
    path = a.db if a.db.is_absolute() else ROOT / a.db
    if not path.exists():
        print(f"{path} does not exist: nothing to measure")
        return
    print_report(measure(path, cfg))


if __name__ == "__main__":
    main()
