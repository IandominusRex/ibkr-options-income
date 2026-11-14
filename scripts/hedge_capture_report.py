"""The H4 hedge-instrument report over the captured quotes (risk-envelope Task 16; spec §3.10.4, H4).

    python -m scripts.hedge_capture_report            # compute H4 and write data/envelope_reports/H4.json
    python -m scripts.hedge_capture_report --dry-run  # compute and print, write nothing
    python -m scripts.hedge_capture_report --probe    # one-off: print XND's/QQQ's contract fields

H4 (ruling): over at least 20 capture sessions, XND is the hedge instrument if, on the default
item's legs, the **median quoted spread is at most ``hedge.quote_max_spread_pct`` (8%) of mid**,
**displayed size is at least the bridge's contract count on at least 80% of captures** (at least one
contract while Task 36's size rule does not exist, so a missing size fails), and the **all-in cost
per protected point is at most 1.5x QQQ's**. Otherwise QQQ: the report then also writes
``H4_fallback.json`` (``passed: true``, ``value_on_pass: "QQQ"``). Fewer than 20 sessions is
insufficient (``passed: null``, nothing changes). A PASS sets switch ``hedge_instrument`` through
``apply_reports`` at the next EOD (paper only; reverse with ``python -m scripts.envelope switch``).

The default item is the one with the best minimum intrinsic protection per premium dollar across the
five envelope scenarios (``src/hedge/menu.py``); it is marked at capture. The all-in cost per
protected point is (mid debit + the round trip's half-spread crossings and commissions) divided by
the item's intrinsic payoff at the S10 index move, a dimensionless ratio of dollars paid to dollars of
S10 protection, so the two instruments compare. Exchange fees are not in it (not yet taken from IBKR's
schedule). A leg nobody bids or asks counts as an infinite spread, so a thin market fails the bar.

The ``--probe`` mode connects to the paper Gateway with the healthcheck clientId and prints what IBKR
says about each configured instrument (qualification, option chains); record the result by hand.
"""

from __future__ import annotations

import argparse
import statistics
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.common.config import HedgeCfg, get_hedge_cfg
from src.common.logging import setup_logging
from src.common.schemas import EnvelopeReportResult
from src.hedge import menu, store
from src.storage.db import init_db
from src.storage.envelope_switches import REPORTS_DIR

MIN_SESSIONS = 20
SIZE_SHARE = 0.80
COST_RATIO = 1.5
SWITCH = "hedge_instrument"
CRITERION = (
    "H4: over >= 20 capture sessions XND's median quoted spread is <= 8% of mid on the default "
    "item's legs, displayed size >= the bridge's contract count on >= 80% of captures, and its "
    "all-in cost per protected point is <= 1.5x QQQ's; else QQQ"
)
FALLBACK_CRITERION = (
    "H4 failed over >= 20 capture sessions: the hedge instrument is QQQ (spec 3.10.0)"
)


@dataclass(frozen=True)
class InstrumentH4:
    instrument: str
    captures: int  # captures that produced a default item
    median_spread_pct: float | None  # across the default item's legs (inf = a one-sided leg)
    size_share: float | None  # share of captures whose displayed size covers the bridge
    median_cost_per_point: float | None


def _leg_spread_pct(q: store.QuoteRecord) -> float:
    if q.bid is None or q.ask is None or q.bid <= 0 or q.ask <= 0:
        return float("inf")
    return (q.ask - q.bid) / ((q.ask + q.bid) / 2.0) * 100.0


def _captures(quotes: list[store.QuoteRecord]) -> dict[datetime, dict[str, store.QuoteRecord]]:
    """The default item's legs per capture (``{captured_at: {"long": row, "short": row}}``)."""
    out: dict[datetime, dict[str, store.QuoteRecord]] = {}
    for q in quotes:
        if q.is_default:
            out.setdefault(q.captured_at, {})[q.leg] = q
    return {k: v for k, v in out.items() if "long" in v}


def _cost_per_point(
    legs: dict[str, store.QuoteRecord], multiplier: int, commission: float
) -> float | None:
    long = legs["long"]
    short = legs.get("short")
    if long.mid is None or (short is not None and short.mid is None):
        return None
    debit = long.mid - (short.mid if short is not None and short.mid is not None else 0.0)
    crossing = sum(
        (q.ask - q.bid) / 2.0 for q in legs.values() if q.bid is not None and q.ask is not None
    )
    friction = 2.0 * (crossing + len(legs) * commission / multiplier)  # in and out
    floor = long.spot * (1.0 - menu.SCENARIO_MOVES["S10"])
    payoff = max(0.0, long.strike - floor) - (max(0.0, short.strike - floor) if short else 0.0)
    return (debit + friction) / payoff if payoff > 0 else None


def instrument_stats(
    instrument: str, quotes: list[store.QuoteRecord], cfg: HedgeCfg
) -> InstrumentH4:
    multiplier = cfg.instruments[instrument].multiplier if instrument in cfg.instruments else 100
    caps = _captures([q for q in quotes if q.instrument == instrument])
    spreads: list[float] = []
    sized = 0
    costs: list[float] = []
    for legs in caps.values():
        spreads.extend(_leg_spread_pct(q) for q in legs.values())
        need = max(1, *(q.needed_contracts for q in legs.values()))
        long, short = legs["long"], legs.get("short")
        ok = long.ask_size is not None and long.ask_size >= need
        if short is not None:
            ok = ok and short.bid_size is not None and short.bid_size >= need
        sized += 1 if ok else 0
        c = _cost_per_point(legs, multiplier, cfg.commission_per_contract)
        if c is not None:
            costs.append(c)
    return InstrumentH4(
        instrument,
        len(caps),
        statistics.median(spreads) if spreads else None,
        sized / len(caps) if caps else None,
        statistics.median(costs) if costs else None,
    )


def _fmt(x: float | None) -> float | str | None:
    if x is None:
        return None
    return "inf" if x == float("inf") else round(x, 4)


def h4_results(
    quotes: list[store.QuoteRecord],
    cfg: HedgeCfg,
    *,
    now: datetime | None = None,
    min_sessions: int = MIN_SESSIONS,
) -> list[EnvelopeReportResult]:
    """``[H4]``, or ``[H4, H4_fallback]`` when XND fails with enough sessions."""
    now = now or datetime.now(UTC)
    sessions = len({q.session_date for q in quotes})
    xnd = instrument_stats("XND", quotes, cfg)
    qqq = instrument_stats("QQQ", quotes, cfg)
    metrics: dict[str, float | str | None] = {
        "sessions": sessions,
        "xnd_captures": xnd.captures,
        "qqq_captures": qqq.captures,
        "xnd_median_spread_pct": _fmt(xnd.median_spread_pct),
        "xnd_size_share": _fmt(xnd.size_share),
        "xnd_cost_per_point": _fmt(xnd.median_cost_per_point),
        "qqq_median_spread_pct": _fmt(qqq.median_spread_pct),
        "qqq_size_share": _fmt(qqq.size_share),
        "qqq_cost_per_point": _fmt(qqq.median_cost_per_point),
    }

    def result(rid: str, passed: bool | None, value: str, criterion: str) -> EnvelopeReportResult:
        return EnvelopeReportResult(
            id=rid,
            passed=passed,
            criterion=criterion,
            metrics=metrics,
            switch=SWITCH,
            value_on_pass=value,
            written_at=now,
        )

    if sessions < min_sessions:
        return [result("H4", None, "XND", CRITERION)]
    spread_ok = (
        xnd.median_spread_pct is not None and xnd.median_spread_pct <= cfg.quote_max_spread_pct
    )
    size_ok = xnd.size_share is not None and xnd.size_share >= SIZE_SHARE
    xnd_cost, qqq_cost = xnd.median_cost_per_point, qqq.median_cost_per_point
    if spread_ok and size_ok and xnd_cost is not None and qqq_cost is None:
        metrics["note"] = "QQQ's cost was not measured, so XND's cost bar cannot be applied"
        return [result("H4", None, "XND", CRITERION)]
    cost_ok = xnd_cost is not None and qqq_cost is not None and xnd_cost <= COST_RATIO * qqq_cost
    if spread_ok and size_ok and cost_ok:
        return [result("H4", True, "XND", CRITERION)]
    return [
        result("H4", False, "XND", CRITERION),
        result("H4_fallback", True, "QQQ", FALLBACK_CRITERION),
    ]


def write_results(results: list[EnvelopeReportResult], directory: Path = REPORTS_DIR) -> list[Path]:
    """Write each result; a ``H4_fallback.json`` left from an earlier FAIL is removed unless this run
    writes one (a stale QQQ fallback would otherwise override a later XND PASS at the next EOD)."""
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    for r in results:
        path = directory / f"{r.id}.json"
        path.write_text(r.model_dump_json(indent=2), encoding="utf-8")
        paths.append(path)
    if not any(r.id == "H4_fallback" for r in results):
        (directory / "H4_fallback.json").unlink(missing_ok=True)
    return paths


def _print(results: list[EnvelopeReportResult]) -> None:
    h4 = results[0]
    verdict = {True: "PASS (XND)", False: "FAIL (QQQ)", None: "insufficient data"}[h4.passed]
    print(f"H4: {verdict}")
    for k, v in h4.metrics.items():
        print(f"  {k:<24} {v}")


def probe() -> int:
    """Print what IBKR says about each configured hedge instrument. Needs the paper Gateway."""
    from ib_async import Option

    from src.hedge.capture import underlying_contract
    from src.ibkr.connection import IBKRConnection

    cfg = get_hedge_cfg()
    conn = IBKRConnection("healthcheck")
    try:
        ib: Any = conn.connect()
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] Could not connect to IBKR: {exc}")
        return 1
    try:
        for name, ic in cfg.instruments.items():
            print(f"\n== {name} (config: {ic.sec_type} on {ic.exchange}, class {ic.trading_class})")
            und = underlying_contract(name, ic)
            ib.qualifyContracts(und)
            print(
                f"  underlying: conId={und.conId} exchange={und.exchange} "
                f"primary={getattr(und, 'primaryExchange', '')} currency={und.currency}"
            )
            if not und.conId:
                print(
                    "  [FAIL] the underlying did not qualify: fix hedge.instruments in risk_limits.yaml"
                )
                continue
            for p in ib.reqSecDefOptParams(name, "", ic.sec_type, und.conId):
                mark = "  <-- configured class" if p.tradingClass == ic.trading_class else ""
                exps = sorted(p.expirations)
                print(
                    f"  chain: class={p.tradingClass} exchange={p.exchange} multiplier={p.multiplier} "
                    f"expirations={len(exps)} ({exps[:1]}..{exps[-1:]}) strikes={len(p.strikes)}{mark}"
                )
            details = ib.reqContractDetails(
                Option(name, "", 0, "P", "SMART", tradingClass=ic.trading_class)
            )
            print(
                f"  option contract details: {len(details)} contract(s) for class {ic.trading_class}"
            )
            for d in details[:3]:
                c = d.contract
                print(
                    f"    {c.localSymbol} exchange={c.exchange} multiplier={c.multiplier} "
                    f"currency={c.currency} minTick={d.minTick} validExchanges={d.validExchanges}"
                )
    finally:
        conn.disconnect()
    print("\nRecord this output in the plan's Progress log (Task 16).")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="H4 hedge-instrument report over captured quotes")
    ap.add_argument("--dry-run", action="store_true", help="print the verdict, write nothing")
    ap.add_argument(
        "--probe", action="store_true", help="print the instruments' IBKR contract fields"
    )
    args = ap.parse_args(argv)
    setup_logging()
    if args.probe:
        return probe()
    init_db()
    results = h4_results(store.load_quotes(), get_hedge_cfg())
    _print(results)
    if not args.dry_run:
        for path in write_results(results):
            print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
