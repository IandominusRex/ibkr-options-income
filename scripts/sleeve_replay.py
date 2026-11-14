"""The leveraged-sleeve replay (risk-envelope plan Task 29; spec §3.5 and §3.5.1, rulings E7, L1-L4).

    python -m scripts.sleeve_replay [--db PATH] [--since DATE] [--dry-run]

Reads the trading database **read-only**. On the ``price_history`` panel it replays the lots the
leveraged sleeve (``regime_limits.sleeve_lot``) would have opened on each leveraged ETF in the leverage
map whose governing index (QQQ for TQQQ, SOXX for SOXL, SMH standing in for SOXX until it has its own
history) has a panel:

* **Above the 200-day** (the trend path, L3): the Leveraged Entry Signal, from the very function
  ``analytics.leveraged_entry.les_signal`` recomputed on the panel each session, fires a pullback (RSI(2)
  under 5 or the close under the 50-day): tier 3.0, or 6.0 with the Nasdaq-100 breadth washout when the
  database holds breadth counts (``breadth_counts``, merged and smoothed as the nightly run does).
* **Below the 200-day** (the bottoming path): the half tier (1.5) when the sigma-drawdown holds
  (``sigma_drawdown``, 1.0 x sigma-60), a name RSI(14) turn and a higher close hold (an approximation of
  ``name_bottoming``: the support condition is not replayed), and the name's IV rank is at least 50 on its
  ``iv_history`` (an IV rank that cannot be computed fails closed).

A lot is a 7-14 DTE (10 targeted) put at the sleeve's delta window (0.175), sized to whole lots under the
tier's cap (``sleeve_contracts``: the tier's share of the **2026-11-12 NLV** less what the sleeve holds,
each lot at its leverage, rounding down, never up to one), at most 2 open at once and one per name per 3
sessions. It is valued daily by Black-Scholes at its entry IV: closed at the profit-take line, held to
expiry, or at the 2x loss line **rolled first** (to a later expiry, down, for a net credit of at least
``roll.new_leg.min_net_credit``, once) and otherwise **bought back at the line**. Commissions are not
counted.

**E7 PASS (plan):** total P&L at least 0, no lot losing over 1% of the NLV, never more than 2 open at
once. No lot opened is no result. Writes ``data/envelope_reports/E7.json`` (``switch="leveraged_sleeve"``,
``value_on_pass="on"``) and ``E7_report.txt``; the EOD run applies a PASS (paper only).
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from src.analytics.black_scholes import bs_price
from src.analytics.breadth import oscillator
from src.analytics.leveraged_entry import les_signal, rsi_series, sigma_drawdown
from src.analytics.shock_inputs import leverage_map
from src.common.config import (
    LesCfg,
    get_config,
    get_envelope_cfg,
    get_leveraged_sizing_cfg,
    get_regime_cfg,
)
from src.common.schemas import BreadthCount, EnvelopeReportResult, OptionRight
from src.engine.regime_limits import sleeve_contracts
from src.execution.profit_take import resolve_profit_take_pct
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

LOSS_NLV_SHARE = 1.0  # percent of NLV: no lot may lose more
MAX_OPEN = 2
SLEEVE_DTE = 10  # the middle of the 7-14 window
SLEEVE_DELTA = 0.175  # the middle of the 0.15-0.20 window
ROLL_EXTENSION_DAYS = 14
ROLL_STRIKE_STEP_PCT = 2.0
CRITERION = (
    "E7 (plan): the lots the sleeve would have opened on the panel, valued under the wheel's leveraged rules "
    "(roll first; buy back at the 2x line if no roll), total P&L >= 0, no lot loss > 1% of the 2026-11-12 NLV, "
    "<= 2 open at once"
)
_NEED_BARS = 201 + 1


@dataclass
class Lot:
    name: str
    path: str  # trend | below_trend
    tier: float
    opened: date
    strike: float
    expiry: date
    iv: float
    contracts: int
    premium: float  # per share, the current leg's entry credit
    leverage: int
    entry_dte: int
    realised: float = 0.0  # dollars booked so far (a rolled chain's earlier legs)
    rolled: bool = False
    closed: date | None = None
    how: str = "open"

    @property
    def collateral_weighted(self) -> float:
        return self.strike * 100.0 * self.contracts * self.leverage


@dataclass(frozen=True)
class ReplayOut:
    lots: list[Lot]
    peak_open: int
    skipped: list[str]  # names that could not be replayed, and why
    washout_available: bool

    @property
    def total_pnl(self) -> float:
        return sum(lot.realised for lot in self.lots)


def _frame(series: Sequence[tuple[date, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        {"Close": [c for _, c in series]}, index=pd.DatetimeIndex([d for d, _ in series])
    )


def load_oscillator(con: sqlite3.Connection, cfg: LesCfg) -> dict[date, float]:
    """The breadth oscillator by day from the stored counts (the nightly merge: the history is kept
    unless the two sources disagree by more than the flag gap, when our own count is used)."""
    from src.analytics.breadth import merge_counts

    try:
        rows = con.execute(
            "SELECT day, source, adv, dec FROM breadth_counts ORDER BY day"
        ).fetchall()
    except sqlite3.OperationalError:
        return {}
    tt = [
        BreadthCount(day=date.fromisoformat(str(r[0])[:10]), adv=r[2], dec=r[3], source="tt")
        for r in rows
        if r[1] == "tt"
    ]
    own = [
        BreadthCount(day=date.fromisoformat(str(r[0])[:10]), adv=r[2], dec=r[3], source="own")
        for r in rows
        if r[1] == "own"
    ]
    merged, _flagged = merge_counts(tt, own, gap=cfg.source_gap_flag)
    ordered = sorted(merged, key=lambda c: c.day)
    return {c.day: v for c, v in zip(ordered, oscillator(ordered), strict=True) if v is not None}


def load_iv_series(con: sqlite3.Connection, symbol: str) -> list[tuple[date, float]]:
    """The name's unflagged ``iv_history`` ascending (a decimal)."""
    try:
        rows = con.execute(
            "SELECT obs_date, iv FROM iv_history WHERE symbol = ? AND (flagged IS NULL OR flagged = 0) "
            "ORDER BY obs_date",
            (symbol,),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [(date.fromisoformat(str(r[0])[:10]), float(r[1])) for r in rows if r[1]]


def iv_rank(series: Sequence[tuple[date, float]], day: date, lookback: int = 252) -> float | None:
    """The IV rank on *day*: where its IV sits between the lowest and highest of the last *lookback*
    readings, 0-100; None with fewer than 20 readings or no range."""
    upto = [v for d, v in series if d <= day][-lookback:]
    if len(upto) < 20:
        return None
    lo, hi = min(upto), max(upto)
    return None if hi <= lo else (upto[-1] - lo) / (hi - lo) * 100.0


def _mark(lot: Lot, spot: float, day: date) -> float:
    dte = (lot.expiry - day).days
    if dte <= 0:
        return max(lot.strike - spot, 0.0)
    return bs_price(spot, lot.strike, dte, lot.iv, "P") or 0.0


def _below_trend_holds(bars: pd.DataFrame, name_bars: pd.DataFrame, k: float) -> bool:
    """The bottoming-path conditions the panel can replay: the sigma-drawdown on the governing index, a
    name RSI(14) turn (under 30 within the last 10 sessions, rising today) and a close over the
    previous close."""
    holds, _why = sigma_drawdown(bars, k)
    if not holds or len(name_bars) < 20:
        return False
    close = name_bars["Close"].astype(float)
    rsi = rsi_series(close, 14)
    turn = bool((rsi.iloc[-10:] < 30).any()) and float(rsi.iloc[-1]) > float(rsi.iloc[-2])
    return turn and float(close.iloc[-1]) > float(close.iloc[-2])


def replay(
    closes: Closes,
    ivs: Mapping[str, float],
    *,
    nlv: float,
    start: date | None = None,
    names: Mapping[str, str] | None = None,
    leverage: Mapping[str, int] | None = None,
    osc: Mapping[date, float] | None = None,
    iv_series: Mapping[str, Sequence[tuple[date, float]]] | None = None,
    window: int = 300,
) -> ReplayOut:
    """The sleeve's lots on *closes* (see the module docstring). *names* maps a leveraged ETF to the
    index that governs it; *leverage* its daily factor."""
    les_cfg = get_regime_cfg().leveraged_entry
    sleeve = get_leveraged_sizing_cfg().sleeve
    cfg = get_config()
    soxx_proxy = get_envelope_cfg().soxx_proxy.upper()
    governing = {k.upper(): v.upper() for k, v in (names or les_cfg.governing).items()}
    lev_map = {k.upper(): v for k, v in (leverage or leverage_map()).items()}
    loss_multiple = float(getattr(cfg.automation, "max_loss_multiple", 2.0) or 2.0)
    roll_min = cfg.roll.new_leg.min_net_credit
    osc = osc or {}
    iv_series = iv_series or {}

    skipped: list[str] = []
    todo: dict[str, str] = {}
    gov_frames: dict[str, pd.DataFrame] = {}
    for sym, gov in sorted(governing.items()):
        series = closes.get(gov)
        if (not series or len(series) < _NEED_BARS) and gov == "SOXX":
            series = closes.get(soxx_proxy)  # SOXX has too little history: its proxy governs
        if not series or len(series) < _NEED_BARS:
            skipped.append(f"{sym}: {gov} has under {_NEED_BARS} bars")
            continue
        if sym not in closes or (sym not in ivs and not iv_series.get(sym)):
            skipped.append(f"{sym}: no closes or implied volatility")
            continue
        todo[sym] = gov
        gov_frames[gov] = _frame(series)
    if not todo:
        return ReplayOut([], 0, skipped, bool(osc))

    ref = next(iter(gov_frames.values()))
    days = [d.date() for d in ref.index]
    if start is not None:
        days = [d for d in days if d >= start]
    lots: list[Lot] = []
    open_lots: list[Lot] = []
    last_open: dict[str, int] = {}
    peak = 0
    for i, day in enumerate(days):
        # 1. manage the open lots
        for lot in list(open_lots):
            series = closes.get(lot.name)
            spot = close_on(series, day) if series else None
            if spot is None:
                continue
            value = _mark(lot, spot, day)
            pt = resolve_profit_take_pct(cfg.scheduler, OptionRight.PUT, lot.entry_dte)
            done = False
            if day >= lot.expiry:
                done, lot.how = True, ("rolled_expired" if lot.rolled else "expiry")
            elif value <= (1.0 - pt / 100.0) * lot.premium:
                done, lot.how = True, "profit_take"
            elif loss_multiple > 0 and value >= loss_multiple * lot.premium:
                if not lot.rolled:
                    rolled = _try_roll(lot, spot, day, value, roll_min)
                    if rolled:
                        continue
                done, lot.how = True, "loss_line"
            if done:
                lot.realised += (lot.premium - value) * 100.0 * lot.contracts
                lot.closed = day
                open_lots.remove(lot)
        # 2. entries
        for sym, gov in todo.items():
            if len(open_lots) >= min(MAX_OPEN, sleeve.max_open_lots):
                break
            if i - last_open.get(sym, -10_000) < sleeve.every_sessions:
                continue
            frame = gov_frames[gov]
            idx = frame.index.get_indexer([pd.Timestamp(day)])[0]
            if idx < _NEED_BARS - 1:
                continue
            bars = frame.iloc[max(0, idx - window + 1) : idx + 1]
            recent = [(d, v) for d, v in osc.items() if day - timedelta(days=12) <= d <= day]
            sig = les_signal(bars, recent, les_cfg, index=gov)
            path: str | None
            tier = 0.0
            if sig.trend_up:
                path, tier = ("trend", sig.tier_pct) if sig.tier_pct > 0 else (None, 0.0)
            else:
                name_series = closes.get(sym, [])
                name_bars = _frame([(d, c) for d, c in name_series if d <= day])
                rank = iv_rank(iv_series.get(sym, []), day)
                ok = (
                    rank is not None
                    and rank >= sleeve.iv_rank_min
                    and _below_trend_holds(bars, name_bars, sleeve.sigma_drawdown)
                )
                path, tier = ("below_trend", les_cfg.tiers.below_trend) if ok else (None, 0.0)
            if path is None or tier <= 0:
                continue
            spot = close_on(closes[sym], day)
            iv = _iv_on(iv_series.get(sym, []), day) or ivs.get(sym)
            if spot is None or iv is None:
                continue
            strike = strike_for_delta(spot, SLEEVE_DTE, iv, SLEEVE_DELTA, "P")
            if strike is None:
                continue
            lev = lev_map.get(sym, 3)
            used = sum(lot.collateral_weighted for lot in open_lots)
            room = max(0.0, tier / 100.0 * nlv - used)
            n = sleeve_contracts(room, strike, lev)
            if n < 1:
                continue
            premium = bs_price(spot, strike, SLEEVE_DTE, iv, "P")
            if premium is None or premium <= 0:
                continue
            lot = Lot(
                sym,
                path,
                tier,
                day,
                strike,
                day + timedelta(days=SLEEVE_DTE),
                iv,
                n,
                premium,
                lev,
                SLEEVE_DTE,
            )
            lots.append(lot)
            open_lots.append(lot)
            last_open[sym] = i
        peak = max(peak, len(open_lots))
    # still open at the panel's end: marked to the last close
    for lot in open_lots:
        series = closes.get(lot.name)
        spot = series[-1][1] if series else None
        if spot is not None:
            lot.realised += (lot.premium - _mark(lot, spot, days[-1])) * 100.0 * lot.contracts
    return ReplayOut(lots, peak, skipped, bool(osc))


def _iv_on(series: Sequence[tuple[date, float]], day: date) -> float | None:
    got = [v for d, v in series if d <= day]
    return got[-1] if got else None


def _try_roll(lot: Lot, spot: float, day: date, value: float, min_credit: float) -> bool:
    """Roll *lot* once at the loss line: later expiry, down, for a net credit of at least
    *min_credit* a share. Books the old leg and carries on with the new one."""
    new_expiry = lot.expiry + timedelta(days=ROLL_EXTENSION_DAYS)
    new_dte = (new_expiry - day).days
    step = lot.strike * ROLL_STRIKE_STEP_PCT / 100.0
    for k in range(0, 6):
        strike = lot.strike - k * step
        if strike <= 0:
            break
        new_premium = bs_price(spot, strike, new_dte, lot.iv, "P")
        if new_premium is not None and new_premium - value >= min_credit:
            lot.realised += (lot.premium - value) * 100.0 * lot.contracts
            lot.strike, lot.expiry, lot.premium = strike, new_expiry, new_premium
            lot.entry_dte, lot.rolled = new_dte, True
            return True
    return False


def e7_result(out: ReplayOut, nlv: float, *, now: datetime | None = None) -> EnvelopeReportResult:
    """The E7 verdict (plan): total P&L at least 0, no lot's loss over 1% of the NLV, at most 2 open."""
    metrics: dict[str, float | str | None] = {
        "lots": float(len(out.lots)),
        "trend_lots": float(sum(1 for lot in out.lots if lot.path == "trend")),
        "below_trend_lots": float(sum(1 for lot in out.lots if lot.path == "below_trend")),
        "peak_open": float(out.peak_open),
        "washout_available": "yes" if out.washout_available else "no",
    }
    if out.skipped:
        metrics["skipped"] = "; ".join(out.skipped)
    if not out.lots:
        metrics["note"] = "the sleeve would have opened no lot on the panel"
        return make_result(
            "E7",
            passed=None,
            criterion=CRITERION,
            metrics=metrics,
            switch="leveraged_sleeve",
            value_on_pass="on",
            now=now,
        )
    worst = min(lot.realised for lot in out.lots)
    metrics.update(
        total_pnl=round(out.total_pnl, 2),
        worst_lot_pnl=round(worst, 2),
        worst_lot_pct_of_nlv=round(-worst / nlv * 100.0, 3) if nlv > 0 else None,
        nlv=round(nlv, 2),
    )
    passed = (
        out.total_pnl >= 0 and -worst <= LOSS_NLV_SHARE / 100.0 * nlv and out.peak_open <= MAX_OPEN
    )
    return make_result(
        "E7",
        passed=passed,
        criterion=CRITERION,
        metrics=metrics,
        switch="leveraged_sleeve",
        value_on_pass="on",
        now=now,
    )


def _text(out: ReplayOut, result: EnvelopeReportResult, nlv: float) -> str:
    lines = [
        f"NLV ${nlv:,.0f}; breadth washout "
        + (
            "replayed from stored counts"
            if out.washout_available
            else "not available (pullback tier only)"
        )
    ]
    lines += [f"skipped: {s}" for s in out.skipped]
    lines.append(
        f"{'opened':<11} {'name':<6} {'path':<12} {'n':>2} {'strike':>8} {'how':<14} {'P&L $':>10}"
    )
    for lot in out.lots:
        lines.append(
            f"{lot.opened!s:<11} {lot.name:<6} {lot.path:<12} {lot.contracts:>2} {lot.strike:>8.2f} "
            f"{lot.how:<14} {lot.realised:>10,.0f}"
        )
    lines.append(
        f"\nlots {len(out.lots)}, peak open {out.peak_open}, total P&L ${out.total_pnl:,.0f}"
    )
    lines.append(f"E7: {verdict_word(result.passed)}")
    if "note" in result.metrics:
        lines.append(f"  {result.metrics['note']}")
    return "\n".join(lines)


def run(db_path: Path, *, since: date | None = None) -> tuple[str, EnvelopeReportResult | None]:
    """The report text and the result (None when nothing could be read)."""
    try:
        con = open_ro(db_path)
    except FileNotFoundError:
        return f"No trading database at {db_path}: nothing to replay.", None
    try:
        try:
            # the whole panel: the 200-day needs the bars before *since*, which only starts the lots
            ctx: BookContext = load_book_context(con, extra_symbols=list(leverage_map()))
        except LookupError as exc:
            return f"{exc}: nothing to replay.", None
        osc = load_oscillator(con, get_regime_cfg().leveraged_entry)
        ivs = {s: load_iv_series(con, s) for s in leverage_map()}
    finally:
        con.close()
    nlv = ctx.account.net_liquidation
    out = replay(ctx.closes, ctx.ivs, nlv=nlv, start=since, osc=osc, iv_series=ivs)
    result = e7_result(out, nlv)
    return _text(out, result, nlv), result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="E7: the leveraged-sleeve replay")
    ap.add_argument("--db", type=Path, default=None, help="trading DB or a copy (default: config)")
    ap.add_argument("--since", type=date.fromisoformat, default=None, help="panel start")
    ap.add_argument("--dry-run", action="store_true", help="print, write nothing")
    args = ap.parse_args(argv)
    text, result = run(args.db or trading_db_path(), since=args.since)
    print(text)
    if result is None:
        return 2
    if not args.dry_run:
        print(f"wrote {write_result(result)} and {write_report('E7', text)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
