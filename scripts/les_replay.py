"""The Leveraged Entry Signal replay (risk-envelope plan Task 29a; spec §2.7 and §3.5.1, ruling L8).

    python -m scripts.les_replay [--fill-lag 1] [--refresh] [--ignore-reproduction] [--dry-run]

Daily closes of QQQ, SOXX, TQQQ and SOXL from 1999 come through ``src/data/factory.py``'s price provider
(never ``yfinance`` directly) and are cached as CSV under ``data/envelope_reports/les_cache/``; with a
warm cache the replay needs no network. The signal is ``src/analytics/leveraged_entry.py::les_signal``
itself, called on each session's trailing bars (no second implementation).

**The four cells of L8:** {QQQ -> TQQQ, SOXX -> SOXL} x {synthetic 3x, 2000-06-01..2016-12-31; the real
ETF, 2017-01-01 on}. The synthetic 3x is ``3 x the index's daily return - 3% a year`` (the 3% spread
taken daily). In each cell three strategies run: **buy and hold**; the **200-day filter** (long while the
index closes above its 200-day average); and **LES** (enter on a pullback with the index above its
200-day, hold the whole position to a trend break: two consecutive closes under it). A signal is read on
a close and **filled at the next close** (``--fill-lag 1``, the default; 0 fills on the signal's own
close); flat days earn nothing and costs beyond the ETF's own are ignored. The table prints CAGR, max
drawdown, Sharpe (daily mean over standard deviation, x sqrt(252), no risk-free rate) and time in market.

**L8 PASS (plan; a reproduction check, not an independent test: the parameters were chosen after seeing
these numbers):** LES's Sharpe is at least the 200-day filter's in at least 3 of the 4 cells **and** its
max drawdown is no worse than buy-and-hold's in all 4. The figures in spec §2.7 are the expected output
to within 0.5 points: a larger gap is printed as a STOP and, unless ``--ignore-reproduction`` is given,
writes no verdict. Also printed, for the record: from 2016-11 (the breadth history), LES entries split into
pullback-only and washout entries (Nasdaq-100 breadth oscillator at or under -40 in the last 5 sessions)
with the real ETF's mean 20-session return after each. Writes ``data/envelope_reports/LES.json``
(``switch="leveraged_entry"``, ``value_on_pass="on"``; the EOD run applies a PASS in paper) and
``LES_report.txt``. A series that cannot be fetched writes nothing.
"""

from __future__ import annotations

import argparse
import math
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from src.analytics.breadth import merge_counts, oscillator
from src.analytics.leveraged_entry import les_signal
from src.common.config import LesCfg, get_regime_cfg
from src.common.schemas import BreadthCount, EnvelopeReportResult
from src.reporting.replay import REPORTS_DIR, make_result, verdict_word, write_report, write_result

CACHE_DIR = REPORTS_DIR / "les_cache"
SYMBOLS = ("QQQ", "SOXX", "TQQQ", "SOXL")
SYNTH_WINDOW = (date(2000, 6, 1), date(2016, 12, 31))
REAL_START = date(2017, 1, 1)
LOOKBACK_DAYS = 40_000  # "everything the provider has": the price provider's "max" period
SPREAD_PER_YEAR = 0.03
TRADING_DAYS = 252
WINDOW_BARS = 300  # trailing bars handed to the signal (>= 201 for the 200-day and the break test)
GAP_POINTS = 0.5  # the reproduction tolerance (CAGR and drawdown points)
GAP_SHARPE = 0.05
BREADTH_FROM = date(2016, 11, 1)
STRATEGIES = ("buy_and_hold", "filter_200d", "les")
CRITERION = (
    "L8 (plan): over the four cells {QQQ->TQQQ, SOXX->SOXL} x {synthetic 3x 2000-06-01..2016-12-31, real ETF "
    "2017-01-01..}, LES has Sharpe >= the 200-day filter's in >= 3 of 4 cells and max drawdown <= buy-and-hold's "
    "in all 4"
)

# Spec §2.7: (CAGR %, max drawdown %, Sharpe), None where the table gives no figure.
EXPECTED: dict[tuple[str, str], tuple[float | None, float | None, float | None]] = {
    ("QQQ/TQQQ synthetic", "les"): (10.9, -65.0, 0.46),
    ("QQQ/TQQQ synthetic", "filter_200d"): (4.2, -84.0, 0.31),
    ("QQQ/TQQQ synthetic", "buy_and_hold"): (-15.7, -99.9, 0.20),
    ("SOXX/SOXL synthetic", "les"): (10.2, -77.0, 0.44),
    ("SOXX/SOXL synthetic", "filter_200d"): (4.7, -90.0, 0.35),
    ("QQQ/TQQQ real", "les"): (25.4, -62.0, 0.71),
    ("QQQ/TQQQ real", "filter_200d"): (35.0, -56.0, 0.85),
    ("QQQ/TQQQ real", "buy_and_hold"): (37.5, -82.0, 0.81),
    ("SOXX/SOXL real", "les"): (38.1, -77.0, 0.81),
}


@dataclass(frozen=True)
class Metrics:
    cagr: float  # percent
    max_dd: float  # percent, negative
    sharpe: float
    in_market: float  # percent of sessions
    sessions: int


@dataclass(frozen=True)
class Cell:
    name: str  # "QQQ/TQQQ synthetic"
    metrics: dict[str, Metrics]


# --- the data ---------------------------------------------------------------------------------


def normalise(frame: pd.DataFrame) -> pd.Series:
    """A provider frame's ``Close`` as a float series on a tz-naive, date-normalised index."""
    close = frame["Close"].astype(float).dropna()
    idx = pd.DatetimeIndex(close.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    out = pd.Series(close.to_numpy(), index=idx.normalize())
    return out[~out.index.duplicated(keep="last")].sort_index()


def load_series(
    symbol: str,
    fetch: Callable[[str], pd.DataFrame | None],
    cache_dir: Path,
    *,
    refresh: bool = False,
) -> pd.Series | None:
    """*symbol*'s daily closes: the cache when it exists, else *fetch* (then cached). None when the
    provider has nothing: the replay writes no verdict on a series it could not read."""
    path = cache_dir / f"{symbol}.csv"
    if path.exists() and not refresh:
        frame = pd.read_csv(path, index_col=0, parse_dates=True)
        if not frame.empty:
            return normalise(frame)
    got = fetch(symbol)
    if got is None or got.empty or "Close" not in got.columns:
        return None
    series = normalise(got)
    if series.empty:
        return None
    cache_dir.mkdir(parents=True, exist_ok=True)
    series.rename("Close").to_frame().to_csv(path)
    return series


def default_fetch(symbol: str) -> pd.DataFrame | None:
    """Everything the configured price provider has for *symbol* (through ``src/data/factory.py``)."""
    from src.data.factory import get_price_provider

    return get_price_provider().get_ohlcv(symbol, lookback_days=LOOKBACK_DAYS)


# --- the replay -------------------------------------------------------------------------------


def synthetic_3x(index_close: pd.Series) -> pd.Series:
    """The daily returns of a synthetic 3x fund: ``3 x the index's daily return - 3% / 252``."""
    return 3.0 * index_close.pct_change().dropna() - SPREAD_PER_YEAR / TRADING_DAYS


def signal_arrays(index_close: pd.Series, cfg: LesCfg) -> dict[str, np.ndarray]:
    """Per session: trend up, pullback and trend break from ``les_signal`` on the trailing bars."""
    frame = pd.DataFrame({"Close": index_close})
    n = len(frame)
    up, pull, brk = np.zeros(n, bool), np.zeros(n, bool), np.zeros(n, bool)
    need = cfg.sma_trend + cfg.break_closes - 1
    for i in range(need - 1, n):
        sig = les_signal(frame.iloc[max(0, i - WINDOW_BARS + 1) : i + 1], [], cfg)
        up[i], pull[i], brk[i] = sig.trend_up, sig.pullback, sig.trend_break
    return {"up": up, "pullback": pull, "break": brk}


def les_state(pullback: np.ndarray, trend_break: np.ndarray) -> np.ndarray:
    """LES: flat until a pullback (with the trend up), then the whole position until a trend break."""
    state = np.zeros(len(pullback), bool)
    pos = False
    for i in range(len(pullback)):
        if not pos and pullback[i]:
            pos = True
        elif pos and trend_break[i]:
            pos = False
        state[i] = pos
    return state


def exposure(state: np.ndarray, lag: int) -> np.ndarray:
    """The position held over each session's return: a state read on the close of session ``t`` is
    filled at the close of ``t + lag`` and first earns the return of ``t + lag + 1``."""
    out = np.zeros(len(state), bool)
    shift = 1 + lag
    if shift < len(state):
        out[shift:] = state[: len(state) - shift]
    return out


def metrics_of(returns: pd.Series, held: np.ndarray) -> Metrics:
    """CAGR, max drawdown, Sharpe and time in market of ``held x returns`` (cash earns nothing)."""
    r = returns.to_numpy() * held
    equity = np.cumprod(1.0 + r)
    peak = np.maximum.accumulate(equity)
    years = max((returns.index[-1] - returns.index[0]).days, 1) / 365.25
    cagr = (equity[-1] ** (1.0 / years) - 1.0) * 100.0 if equity[-1] > 0 else -100.0
    std = float(np.std(r, ddof=1)) if len(r) > 1 else 0.0
    sharpe = float(np.mean(r)) / std * math.sqrt(TRADING_DAYS) if std > 0 else 0.0
    return Metrics(
        cagr=cagr,
        max_dd=float(np.min(equity / peak - 1.0)) * 100.0,
        sharpe=sharpe,
        in_market=float(np.mean(held)) * 100.0,
        sessions=len(r),
    )


def run_cell(
    name: str,
    index_close: pd.Series,
    etf_returns: pd.Series,
    start: date,
    end: date | None,
    cfg: LesCfg,
    lag: int,
    arrays: dict[str, np.ndarray] | None = None,
) -> Cell | None:
    """One cell's three strategies over *etf_returns* from *start* to *end*, or None when the window
    holds no sessions. The signal comes from the whole index history (its warm-up is not trimmed)."""
    arrays = arrays or signal_arrays(index_close, cfg)
    states = {
        "buy_and_hold": np.ones(len(index_close), bool),
        "filter_200d": arrays["up"],
        "les": les_state(arrays["pullback"], arrays["break"]),
    }
    pos_of = {d: i for i, d in enumerate(index_close.index)}
    days = [
        d
        for d in etf_returns.index
        if d in pos_of and d.date() >= start and (end is None or d.date() <= end)
    ]
    if len(days) < 30:
        return None
    ret = etf_returns.loc[days]
    cols = np.array([pos_of[d] for d in days])
    out = {s: metrics_of(ret, exposure(state, lag)[cols]) for s, state in states.items()}
    return Cell(name, out)


def l8_verdict(cells: list[Cell]) -> tuple[bool | None, int, int]:
    """``(passed, sharpe cells, drawdown cells)``: None unless there are four cells."""
    if len(cells) != 4:
        return None, 0, 0
    sharpe = sum(1 for c in cells if c.metrics["les"].sharpe >= c.metrics["filter_200d"].sharpe)
    dd = sum(1 for c in cells if c.metrics["les"].max_dd >= c.metrics["buy_and_hold"].max_dd)
    return sharpe >= 3 and dd == 4, sharpe, dd


def reproduction_gaps(cells: list[Cell]) -> list[str]:
    """Where a cell's figure is further from spec §2.7's than the tolerance."""
    gaps: list[str] = []
    for c in cells:
        for strat, m in c.metrics.items():
            exp = EXPECTED.get((c.name, strat))
            if exp is None:
                continue
            for label, got, want, tol in (
                ("CAGR", m.cagr, exp[0], GAP_POINTS),
                ("max drawdown", m.max_dd, exp[1], GAP_POINTS),
                ("Sharpe", m.sharpe, exp[2], GAP_SHARPE),
            ):
                if want is not None and abs(got - want) > tol:
                    gaps.append(f"{c.name} {strat} {label}: {got:.2f} vs {want:.2f} in the spec")
    return gaps


# --- the breadth split, for the record -------------------------------------------------------


def breadth_split(
    index_close: pd.Series,
    etf_close: pd.Series,
    cfg: LesCfg,
    osc: dict[date, float],
    arrays: dict[str, np.ndarray],
) -> list[str]:
    """LES entries from 2016-11 split by tier (pullback only vs the breadth washout), each with the
    real ETF's mean 20-session return after it. Recorded, not part of the verdict."""
    state = les_state(arrays["pullback"], arrays["break"])
    entries = [i for i in range(1, len(state)) if state[i] and not state[i - 1]]
    frame = pd.DataFrame({"Close": index_close})
    tiers: dict[str, list[float]] = {"pullback only": [], "washout": []}
    for i in entries:
        day = index_close.index[i].date()
        if day < BREADTH_FROM:
            continue
        recent = [(d, v) for d, v in osc.items() if d <= day and (day - d).days <= 12]
        sig = les_signal(frame.iloc[max(0, i - WINDOW_BARS + 1) : i + 1], recent, cfg)
        px = etf_close.reindex(index_close.index)
        j = i + 1 + 20
        if j < len(px) and not np.isnan(px.iloc[i + 1]) and not np.isnan(px.iloc[j]):
            tiers["washout" if sig.washout else "pullback only"].append(
                float(px.iloc[j] / px.iloc[i + 1] - 1.0) * 100.0
            )
        else:
            tiers["washout" if sig.washout else "pullback only"].append(float("nan"))
    lines = []
    for tier, vals in tiers.items():
        good = [v for v in vals if not math.isnan(v)]
        mean = f"{sum(good) / len(good):+.1f}%" if good else "n/a"
        lines.append(
            f"  {tier:<14} entries {len(vals):>3}   mean 20-session return {mean} ({len(good)} valued)"
        )
    return lines


def oscillator_by_day(counts: list[BreadthCount], cfg: LesCfg) -> dict[date, float]:
    merged, _ = merge_counts(counts, [], gap=cfg.source_gap_flag)
    ordered = sorted(merged, key=lambda c: c.day)
    return {c.day: v for c, v in zip(ordered, oscillator(ordered), strict=True) if v is not None}


# --- the verdict and the report ---------------------------------------------------------------


def les_result(
    cells: list[Cell],
    gaps: list[str],
    *,
    ignore_reproduction: bool = False,
    now: datetime | None = None,
) -> EnvelopeReportResult:
    passed, sharpe, dd = l8_verdict(cells)
    metrics: dict[str, float | str | None] = {
        "sharpe_cells": float(sharpe),
        "drawdown_cells": float(dd),
        "reproduction_gaps": float(len(gaps)),
    }
    for c in cells:
        key = c.name.replace("/", "_").replace(" ", "_")
        for s, m in c.metrics.items():
            metrics[f"{key}_{s}"] = f"cagr={m.cagr:.1f} dd={m.max_dd:.1f} sharpe={m.sharpe:.2f}"
    if passed is not None and gaps and not ignore_reproduction:
        metrics["note"] = (
            f"STOP: {len(gaps)} figure(s) differ from spec 2.7 by more than the tolerance (first: {gaps[0]}); "
            "no verdict until a human has looked (or --ignore-reproduction)"
        )
        passed = None
    return make_result(
        "LES",
        passed=passed,
        criterion=CRITERION,
        metrics=metrics,
        switch="leveraged_entry",
        value_on_pass="on",
        now=now,
    )


def _table(cells: list[Cell], lag: int) -> list[str]:
    lines = [
        f"fill lag {lag} (a signal on a close is filled {lag} close(s) later; returns start the session after)",
        f"{'cell':<22} {'strategy':<13} {'CAGR %':>8} {'max DD %':>9} {'Sharpe':>7} {'in mkt %':>9} {'sessions':>8}",
    ]
    for c in cells:
        for s in STRATEGIES:
            m = c.metrics[s]
            lines.append(
                f"{c.name:<22} {s:<13} {m.cagr:>8.1f} {m.max_dd:>9.1f} {m.sharpe:>7.2f} "
                f"{m.in_market:>9.1f} {m.sessions:>8}"
            )
    return lines


def build_cells(
    series: dict[str, pd.Series], cfg: LesCfg, lag: int
) -> tuple[list[Cell], dict[str, dict[str, np.ndarray]]]:
    """The four L8 cells (those whose data exists) and the signal arrays per index."""
    arrays: dict[str, dict[str, np.ndarray]] = {}
    cells: list[Cell] = []
    for index, etf in (("QQQ", "TQQQ"), ("SOXX", "SOXL")):
        if index not in series:
            continue
        arrays[index] = signal_arrays(series[index], cfg)
        synth = run_cell(
            f"{index}/{etf} synthetic",
            series[index],
            synthetic_3x(series[index]),
            SYNTH_WINDOW[0],
            SYNTH_WINDOW[1],
            cfg,
            lag,
            arrays[index],
        )
        if synth is not None:
            cells.append(synth)
        if etf in series:
            real = run_cell(
                f"{index}/{etf} real",
                series[index],
                series[etf].pct_change().dropna(),
                REAL_START,
                None,
                cfg,
                lag,
                arrays[index],
            )
            if real is not None:
                cells.append(real)
    return cells, arrays


def run(
    *,
    fetch: Callable[[str], pd.DataFrame | None] = default_fetch,
    breadth: Callable[[], list[BreadthCount]] | None = None,
    cache_dir: Path = CACHE_DIR,
    fill_lag: int = 1,
    refresh: bool = False,
    ignore_reproduction: bool = False,
) -> tuple[str, EnvelopeReportResult | None]:
    """The report text and the result (None when a series could not be read: nothing is written)."""
    cfg = get_regime_cfg().leveraged_entry
    series: dict[str, pd.Series] = {}
    missing: list[str] = []
    for sym in SYMBOLS:
        got = load_series(sym, fetch, cache_dir, refresh=refresh)
        if got is None:
            missing.append(sym)
        else:
            series[sym] = got
    if missing:
        return (
            f"No daily closes for {', '.join(missing)}: the replay cannot run. Nothing written.",
            None,
        )

    cells, arrays = build_cells(series, cfg, fill_lag)
    lines = _table(cells, fill_lag)
    if len(cells) != 4:
        lines.append(f"\nOnly {len(cells)} of the 4 cells have data: no verdict. Nothing written.")
        return "\n".join(lines), None
    other = 0 if fill_lag else 1
    alt_cells, _ = build_cells(series, cfg, other)
    gaps = reproduction_gaps(cells)
    alt_gaps = reproduction_gaps(alt_cells)
    lines.append("")
    if gaps:
        lines.append(f"Reproduction (spec 2.7, +-{GAP_POINTS} points): STOP, {len(gaps)} gap(s):")
        lines += [f"  {g}" for g in gaps[:12]]
    else:
        lines.append(
            f"Reproduction (spec 2.7, +-{GAP_POINTS} points): every figure the spec gives matches."
        )
    lines.append(f"  (with fill lag {other} there would be {len(alt_gaps)} gap(s))")

    result = les_result(cells, gaps, ignore_reproduction=ignore_reproduction)
    _, sharpe, dd = l8_verdict(cells)
    lines.append(
        f"\nL8: LES Sharpe >= the 200-day filter's in {sharpe} of 4 cells (need 3); "
        f"max drawdown <= buy-and-hold's in {dd} of 4 (need 4)"
    )
    lines.append(f"LES replay: {verdict_word(result.passed)}")
    if "note" in result.metrics:
        lines.append(f"  {result.metrics['note']}")

    counts = (breadth or _default_breadth)()
    lines.append(f"\nBreadth tiers from {BREADTH_FROM} (for the record, not part of the verdict):")
    if not counts:
        lines.append("  breadth history unavailable: skipped")
    else:
        osc = oscillator_by_day(counts, cfg)
        for index, etf in (("QQQ", "TQQQ"), ("SOXX", "SOXL")):
            lines.append(f" {index} -> {etf}")
            lines += breadth_split(series[index], series[etf], cfg, osc, arrays[index])
    return "\n".join(lines), result


def _default_breadth() -> list[BreadthCount]:
    from src.data.factory import get_breadth_provider

    return get_breadth_provider().history()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="L8: the Leveraged Entry Signal replay")
    ap.add_argument("--fill-lag", type=int, choices=(0, 1), default=1)
    ap.add_argument("--refresh", action="store_true", help="refetch the closes (ignore the cache)")
    ap.add_argument(
        "--ignore-reproduction",
        action="store_true",
        help="write the verdict despite a reproduction gap",
    )
    ap.add_argument("--dry-run", action="store_true", help="print, write nothing")
    args = ap.parse_args(argv)
    text, result = run(
        fill_lag=args.fill_lag, refresh=args.refresh, ignore_reproduction=args.ignore_reproduction
    )
    print(text)
    if result is None:
        return 2
    if not args.dry_run:
        print(f"wrote {write_result(result)} and {write_report('LES', text)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
