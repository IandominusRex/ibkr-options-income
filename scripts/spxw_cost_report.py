"""The E3 cost report over the SPXW wing capture (risk-envelope Task 17; spec §3.3, ruling E3).

    python -m scripts.spxw_cost_report [--db data/spreads.db] [--dry-run]

Reads ``data/spreads.db`` read-only (SQLite ``mode=ro``, plain SQL; ``spread_wing_quotes``) and prints,
for SPY 5-wide (6 lots at today's caps), SPXW 10- and 25-wide and XSP 5-wide, the **median all-in
round-trip cost per $1,000 of max loss**: commission plus the exchange fee on 4 leg fills, plus the
measured crossing (``credit_mid - credit_natural``, the full mid-to-natural gap) paid on the way in and
on the way out. Every observation pairs the wing quotes with the SPY baseline candidate captured beside
them, so SPY's cost is measured on the same samples. A wing with a leg nobody bids or asks counts as an
infinite cost (it cannot be traded); an instrument whose exchange fee is not yet filled from IBKR's
schedule is blocked.

**E3 PASS**: SPXW 25-wide if its median cost is at most SPY's over at least 15 capture sessions **and**
the spreads paper bar has passed (``data/envelope_reports/spreads_paper.json``); else XSP 5-wide if it
passes the same test (settlement only: your call); else stay on SPY. Writes
``data/envelope_reports/E3.json`` (``switch="spxw_ready"``, ``value_on_pass`` ``spxw`` or ``xsp``; a
recorded fail has ``passed: false`` and ``value_on_pass: "stay"``; anything not yet decidable is
``passed: null``). A PASS **only notifies**: ``apply_reports`` sets ``spxw_ready`` at the next EOD and the
notice says to run Task 39 of the risk-envelope plan at a flat-book cutover. Nothing else changes.
"""

from __future__ import annotations

import argparse
import sqlite3
import statistics
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from src.common.config import ROOT, SpreadsCfg, get_config
from src.common.schemas import EnvelopeReportResult
from src.storage.envelope_switches import REPORTS_DIR

MIN_SESSIONS = 15
SWITCH = "spxw_ready"
CRITERION = (
    "E3: SPXW 25-wide if its median all-in round-trip cost per $1k of max loss is <= SPY's over "
    ">= 15 shadow capture sessions and the spreads paper bar passed; else XSP 5-wide if it passes the "
    "same test; else stay on SPY"
)
_LEGS = 4  # fills per round trip: two to open, two to close


@dataclass(frozen=True)
class WingObs:
    """One capture: a wing spread's quotes beside the SPY candidate they mirror."""

    session_date: date
    instrument: str  # SPXW | XSP
    width: float
    spy_width: float
    spy_credit_mid: float  # per share
    spy_credit_natural: float
    short_bid: float | None
    short_ask: float | None
    long_bid: float | None
    long_ask: float | None


def fee_per_contract(cfg: SpreadsCfg, instrument: str) -> float | None:
    """The exchange fee per contract per leg of *instrument*, None while it is not filled in
    (the same lookup as ``src/spreads/menu.fee_per_contract``; this script stays outside the
    spreads fence, which only the spreads scripts may cross)."""
    return cfg.execution.exchange_fees.get(instrument)


def _round_trip_per_1k(
    crossing: float, credit_mid: float, width: float, per_leg_usd: float
) -> float:
    """All-in cost of one spread's round trip per $1,000 of its max loss (USD)."""
    cost = 2.0 * crossing * 100.0 + _LEGS * per_leg_usd
    max_loss = (width - max(credit_mid, 0.0)) * 100.0
    return cost * 1000.0 / max_loss if max_loss > 0 else float("inf")


def spy_cost_per_1k(o: WingObs, cfg: SpreadsCfg) -> float | None:
    fee = fee_per_contract(cfg, "SPY")
    if fee is None:
        return None
    return _round_trip_per_1k(
        o.spy_credit_mid - o.spy_credit_natural,
        o.spy_credit_mid,
        o.spy_width,
        cfg.execution.commission_per_contract + fee,
    )


def wing_cost_per_1k(o: WingObs, cfg: SpreadsCfg) -> float | None:
    """The wing's cost per $1k of max loss: ``inf`` when a leg is one-sided, ``None`` when the
    instrument's exchange fee is unknown."""
    fee = fee_per_contract(cfg, o.instrument)
    if fee is None:
        return None
    sb, sa, lb, la = o.short_bid, o.short_ask, o.long_bid, o.long_ask
    if any(v is None or v <= 0 for v in (sb, sa, lb, la)):
        return float("inf")
    assert sb is not None and sa is not None and lb is not None and la is not None
    credit_mid = (sb + sa) / 2.0 - (lb + la) / 2.0
    credit_natural = sb - la
    return _round_trip_per_1k(
        credit_mid - credit_natural,
        credit_mid,
        o.width,
        cfg.execution.commission_per_contract + fee,
    )


@dataclass(frozen=True)
class WingStats:
    instrument: str
    width: float
    sessions: int
    observations: int
    median_wing: float | None
    median_spy: float | None
    blocked: bool  # the exchange fee is unknown

    @property
    def passes(self) -> bool:
        return (
            not self.blocked
            and self.median_wing is not None
            and self.median_spy is not None
            and self.median_wing <= self.median_spy
        )


def wing_stats(obs: list[WingObs], instrument: str, width: float, cfg: SpreadsCfg) -> WingStats:
    mine = [o for o in obs if o.instrument == instrument and o.width == width]
    wing = [wing_cost_per_1k(o, cfg) for o in mine]
    blocked = bool(mine) and all(c is None for c in wing)
    pairs = [
        (w, s)
        for o, w in zip(mine, wing, strict=True)
        if w is not None and (s := spy_cost_per_1k(o, cfg)) is not None
    ]
    return WingStats(
        instrument,
        width,
        len({o.session_date for o in mine}),
        len(mine),
        statistics.median(w for w, _ in pairs) if pairs else None,
        statistics.median(s for _, s in pairs) if pairs else None,
        blocked or (not mine and fee_per_contract(cfg, instrument) is None),
    )


def _fmt(x: float | None) -> float | str | None:
    if x is None:
        return None
    return "inf" if x == float("inf") else round(x, 3)


def e3_result(
    obs: list[WingObs],
    cfg: SpreadsCfg,
    *,
    paper_bar_passed: bool,
    now: datetime | None = None,
    min_sessions: int = MIN_SESSIONS,
) -> EnvelopeReportResult:
    """The E3 verdict: ``passed`` True (``spxw`` or ``xsp``), False (``stay``) or None (not yet)."""
    now = now or datetime.now(UTC)
    wc = cfg.wing_capture
    spxw = wing_stats(obs, wc.trading_class, max(wc.widths), cfg)
    xsp = wing_stats(obs, "XSP", wc.xsp_width, cfg)
    metrics: dict[str, float | str | None] = {
        "sessions": spxw.sessions,
        "xsp_sessions": xsp.sessions,
        "spxw_width": spxw.width,
        "spxw_median_cost_per_1k": _fmt(spxw.median_wing),
        "spy_median_cost_per_1k_vs_spxw": _fmt(spxw.median_spy),
        "xsp_width": xsp.width,
        "xsp_median_cost_per_1k": _fmt(xsp.median_wing),
        "spy_median_cost_per_1k_vs_xsp": _fmt(xsp.median_spy),
        "spreads_paper_bar": "passed" if paper_bar_passed else "not passed",
    }

    def done(passed: bool | None, value: str, note: str | None = None) -> EnvelopeReportResult:
        if note:
            metrics["note"] = note
        return EnvelopeReportResult(
            id="E3",
            passed=passed,
            criterion=CRITERION,
            metrics=metrics,
            switch=SWITCH,
            value_on_pass=value,
            written_at=now,
        )

    def ready(s: WingStats) -> bool:
        return not s.blocked and s.sessions >= min_sessions and s.median_wing is not None

    winner = next(
        (name for name, s in (("spxw", spxw), ("xsp", xsp)) if ready(s) and s.passes), None
    )
    if winner is not None:
        if not paper_bar_passed:
            return done(
                None,
                winner,
                f"{winner} passes the cost test but the spreads paper bar has not passed yet",
            )
        return done(True, winner)
    if all(ready(s) for s in (spxw, xsp)):
        return done(False, "stay", "neither SPXW nor XSP is cheaper than SPY per $1k of max loss")
    notes = []
    for name, s in (("SPXW", spxw), ("XSP", xsp)):
        if s.blocked:
            notes.append(
                f"{name}: the exchange fee is not filled in spreads.execution.exchange_fees"
            )
        elif s.sessions < min_sessions:
            notes.append(f"{name}: {s.sessions} of {min_sessions} capture sessions")
    return done(None, "spxw", "; ".join(notes) or "not enough data")


def paper_bar_passed(directory: Path = REPORTS_DIR) -> bool:
    """Whether ``spreads_paper.json`` (the paper bar, ruling P8) records a PASS."""
    try:
        result = EnvelopeReportResult.model_validate_json(
            (directory / "spreads_paper.json").read_text()
        )
    except Exception:
        return False
    return result.passed is True


def write_result(result: EnvelopeReportResult, directory: Path = REPORTS_DIR) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{result.id}.json"
    path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    return path


def load_observations(path: Path) -> list[WingObs]:
    """Every captured wing spread from the spreads database, opened read-only."""
    if not path.exists():
        return []  # nothing captured yet
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT session_date, instrument, width, spy_width, spy_credit_mid, "
            "spy_credit_natural, short_bid, short_ask, long_bid, long_ask "
            "FROM spread_wing_quotes ORDER BY id"
        ).fetchall()
    except sqlite3.OperationalError:
        return []  # no table yet: nothing captured
    finally:
        con.close()
    return [
        WingObs(date.fromisoformat(str(r[0])), r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9])
        for r in rows
    ]


def _print(obs: list[WingObs], cfg: SpreadsCfg, result: EnvelopeReportResult) -> None:
    wc = cfg.wing_capture
    print(f"Wing observations: {len(obs)}")
    print(
        f"{'instrument':<14} {'sessions':>8} {'obs':>5} {'median $/1k':>12} {'SPY $/1k':>10}  verdict"
    )
    for inst, width in [
        *[(wc.trading_class, w) for w in sorted(wc.widths, reverse=True)],
        ("XSP", wc.xsp_width),
    ]:
        s = wing_stats(obs, inst, width, cfg)
        cost = _fmt(s.median_wing) if not s.blocked else "BLOCKED"
        spy = _fmt(s.median_spy)
        verdict = (
            "cheaper" if s.passes else ("blocked: no exchange fee" if s.blocked else "not cheaper")
        )
        print(
            f"{f'{inst} {width:g}-wide':<14} {s.sessions:>8} {s.observations:>5} {cost!s:>12} {spy!s:>10}  {verdict}"
        )
    state = {True: "PASS", False: "FAIL (stay on SPY)", None: "not yet decidable"}[result.passed]
    print(f"\nE3: {state}" + (f" -> {result.value_on_pass}" if result.passed else ""))
    if "note" in result.metrics:
        print(f"  {result.metrics['note']}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="E3 cost report over the SPXW wing capture")
    ap.add_argument(
        "--db", type=Path, default=None, help="spreads.db (default: the configured one)"
    )
    ap.add_argument("--dry-run", action="store_true", help="print the verdict, write nothing")
    args = ap.parse_args(argv)
    cfg = get_config().spreads
    path = args.db or Path(cfg.db_url.removeprefix("sqlite:///"))
    if not path.is_absolute():
        path = ROOT / path
    obs = load_observations(path)
    result = e3_result(obs, cfg, paper_bar_passed=paper_bar_passed())
    _print(obs, cfg, result)
    if not args.dry_run:
        print(f"wrote {write_result(result)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
