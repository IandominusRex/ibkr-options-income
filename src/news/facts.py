"""Deterministic fact sheet + overreaction/continuation flags (spec §6.1–6.2).

Reads only the deterministic analytics tier (technicals, iv, sector_context, price data)
and the read-side views. The LLM interprets these; it never computes them.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

import pandas as pd

from src.common.config import NewsCfg
from src.common.schemas import (
    IVStats,
    MarketConditions,
    OptionRight,
    PositionSnapshot,
    SectorContext,
    TechnicalStats,
)
from src.news.playbook import parse_value
from src.news.schemas import EarningsView, EconEventView, FactSheet
from src.news.tape import Quote


def _safe[T](fn: Callable[..., T], *a: object) -> T | None:
    try:
        return fn(*a)
    except Exception:
        return None


@dataclass
class Analytics:
    technicals: Callable[[str], TechnicalStats | None]
    iv: Callable[[str], IVStats | None]
    sector: Callable[[str], SectorContext | None]
    quote: Callable[[str], Quote]
    daily: Callable[[str], pd.DataFrame]
    past_earnings: Callable[[str], list[date]]

    @classmethod
    def live(cls) -> Analytics:
        from src.analytics.iv import get_iv_stats
        from src.analytics.sector_context import get_sector_context
        from src.analytics.technicals import get_technical_stats
        from src.data.factory import get_earnings_history, get_price_provider
        from src.news.tape import quote

        def daily(s: str) -> pd.DataFrame:
            # Not `_safe(...) or pd.DataFrame()`: a non-empty DataFrame has no truth value.
            # 400 days, not 260: the chart shows 130 bars and its SMA200 needs 200 more
            # before the first of them (260 days drew SMA200 for only the last ~50 bars).
            df = _safe(get_price_provider().get_ohlcv, s, 400)
            return df if df is not None else pd.DataFrame()

        return cls(
            technicals=lambda s: _safe(get_technical_stats, s),
            iv=lambda s: _safe(get_iv_stats, s),
            sector=lambda s: _safe(get_sector_context, s),
            quote=lambda s: _safe(quote, s) or Quote(symbol=s),
            daily=daily,
            past_earnings=lambda s: _safe(get_earnings_history().past_report_dates, s, 4) or [],
        )


def sigma_move(ret_pct: float | None, iv_pct: float | None) -> float | None:
    if ret_pct is None or not iv_pct:
        return None
    return abs(ret_pct) / (iv_pct / math.sqrt(252))


def expected_move(spot: float, iv_pct: float, dte: int) -> float:
    return spot * iv_pct / 100 * math.sqrt(max(dte, 1) / 365)


def post_earnings_moves(daily: pd.DataFrame, dates: list[date]) -> list[float]:
    """The 1-day reaction to each report (spec §6.1). Report dates carry no BMO/AMC timing,
    so both candidate days are measured (pre-report close → report-day close for a
    before-open report, report-day close → next close for an after-close one) and the larger
    move is the reaction. With no session on the report date, the bracketing closes are used."""
    if daily is None or daily.empty or "Close" not in daily:
        return []
    closes = daily["Close"].dropna()
    days = [pd.Timestamp(i).date() for i in closes.index]
    out: list[float] = []
    for d in dates:
        before = [i for i, x in enumerate(days) if x < d]
        on = [i for i, x in enumerate(days) if x == d]
        after = [i for i, x in enumerate(days) if x > d]
        if not (before and after):
            continue
        c_before, c_after = float(closes.iloc[before[-1]]), float(closes.iloc[after[0]])
        if not on:
            out.append((c_after / c_before - 1) * 100)
            continue
        c_on = float(closes.iloc[on[0]])
        bmo, amc = (c_on / c_before - 1) * 100, (c_after / c_on - 1) * 100
        out.append(max(bmo, amc, key=abs))
    return out


def _r1(x: float) -> float:
    return round(x, 1)


def build_ticker_facts(
    symbol: str,
    *,
    an: Analytics,
    positions: list[PositionSnapshot],
    lists: list[str],
    earnings: EarningsView | None,
    cluster_tags: set[str],
    today: date,
    cfg: NewsCfg,
) -> FactSheet:
    sh = FactSheet()
    q = an.quote(symbol)
    tech = an.technicals(symbol)
    iv = an.iv(symbol)
    sec = an.sector(symbol)
    chg = q.change_pct
    iv_pct = (iv.current_iv or iv.hv_30) if iv else None

    move = sh.add("Move today", _r1(chg), f"{chg:+.1f}%") if chg is not None else None
    sig_v = sigma_move(chg, iv_pct)
    sig = sh.add("Move in σ", _r1(sig_v), f"{sig_v:.1f}σ") if sig_v is not None else None
    if chg is not None and tech and tech.atr_14 and q.last:
        x = abs(chg / 100 * q.last) / tech.atr_14
        sh.add("Move ÷ ATR14", _r1(x), f"{x:.1f}× ATR")
    abn_sector = None
    if chg is not None and symbol != "SPY":
        spy = an.quote("SPY").change_pct
        if spy is not None:
            sh.add("SPY today", _r1(spy), f"{spy:+.1f}%")
            sh.add("Move vs SPY", _r1(chg - spy), f"{chg - spy:+.1f}% vs SPY")
        etf = sec.sector_etf if sec else None
        if etf and etf != symbol:
            e_chg = an.quote(etf).change_pct
            if e_chg is not None:
                abn_sector = sh.add(
                    f"Move vs {etf}", _r1(chg - e_chg), f"{chg - e_chg:+.1f}% vs {etf}"
                )

    rsi = support_f = None
    near_support = False
    if tech:
        if tech.rsi_14 is not None:
            rsi = sh.add("RSI14", _r1(tech.rsi_14), f"RSI {tech.rsi_14:.0f}")
        if tech.sma_200 and q.last:
            pct = (q.last / tech.sma_200 - 1) * 100
            sh.add("Price vs SMA200", _r1(pct), f"{pct:+.1f}% vs SMA200")
        if tech.phase is not None:
            sh.add("Phase", None, str(tech.phase))
        if q.last:
            below = [s for s in tech.support_levels if s <= q.last]
            above = [r for r in tech.resistance_levels if r >= q.last]
            atr = tech.atr_14 or 0
            if below:
                s = max(below)
                support_f = sh.add(
                    "Nearest support", s, f"${s:.2f} ({(s / q.last - 1) * 100:+.1f}%)"
                )
                near_support = (q.last - s) <= atr
            if tech.sma_200 is not None and abs(q.last - tech.sma_200) <= atr:
                near_support = True
            if above:
                r = min(above)
                sh.add("Nearest resistance", r, f"${r:.2f} ({(r / q.last - 1) * 100:+.1f}%)")
    if iv:
        if iv.iv_rank is not None:
            sh.add("IV rank", _r1(iv.iv_rank), f"IV rank {iv.iv_rank:.0f}")
        if iv.current_iv is not None and iv.hv_30 is not None:
            sh.add(
                "IV30 vs HV30",
                _r1(iv.current_iv - iv.hv_30),
                f"IV {iv.current_iv:.0f}% vs HV {iv.hv_30:.0f}%",
            )

    implied = None
    if iv_pct:
        im = iv_pct / math.sqrt(252)
        implied = sh.add("IV-implied 1-day move", _r1(im), f"±{im:.1f}%")
    if earnings:
        sh.add("Earnings date", None, f"{earnings.report_date:%Y-%m-%d} {earnings.timing.upper()}")
        if earnings.eps_actual is not None and earnings.eps_est is not None:
            sh.add(
                "EPS vs est",
                earnings.eps_actual,
                f"EPS {earnings.eps_actual:.2f} vs {earnings.eps_est:.2f} est",
            )
        if earnings.rev_actual is not None and earnings.rev_est is not None:
            sh.add(
                "Revenue vs est",
                earnings.rev_actual / 1e9,
                f"Rev {earnings.rev_actual / 1e9:.1f}B vs {earnings.rev_est / 1e9:.1f}B est",
            )
        past = post_earnings_moves(an.daily(symbol), an.past_earnings(symbol))
        if past:
            avg = sum(abs(x) for x in past) / len(past)
            sh.add("Avg post-earnings move", _r1(avg), f"±{avg:.1f}% avg over last {len(past)}")
        if (
            earnings.status == "released"
            and chg is not None
            and implied is not None
            and implied.value
        ):
            ratio = abs(chg) / implied.value
            ratio_f = sh.add("Move ÷ implied", round(ratio, 2), f"{ratio:.1f}× implied")
            if ratio >= cfg.flags.earnings_outsized:
                sh.flag("earnings_outsized", move, implied, ratio_f)
            elif ratio <= cfg.flags.earnings_muted:
                sh.flag("earnings_muted", move, implied, ratio_f)

    for p in positions:
        if (p.underlying or p.symbol).upper() != symbol.upper() or p.position == 0:
            continue
        if p.sec_type == "OPT" and p.strike and p.expiry and q.last:
            dte = (p.expiry - today).days
            right = "P" if p.right == OptionRight.PUT else "C"
            otm = (
                (q.last - p.strike) / q.last * 100
                if right == "P"
                else (p.strike - q.last) / q.last * 100
            )
            units = abs(q.last - p.strike) / expected_move(q.last, iv_pct, dte) if iv_pct else None
            word = "OTM" if otm >= 0 else "ITM"
            unit_txt = f" = {units:.1f} exp. moves" if units is not None else ""
            sh.add(
                f"Position {symbol} {p.strike:g}{right}",
                _r1(otm),
                f"{p.strike:g}{right} {dte} DTE · {abs(otm):.1f}% {word}{unit_txt}",
            )
        elif p.sec_type == "STK":
            sh.add(f"Shares {symbol}", p.position, f"{p.position:g} shares @ {p.avg_cost:.2f}")
    sh.add("Universe", None, ", ".join(lists) if lists else "not in universe")

    fl = cfg.flags
    if sig_v is not None and sig_v >= fl.large_move_sigma and "quantified" not in cluster_tags:
        sh.flag("large_move_no_hard_news", move, sig)
    if "rumor" in cluster_tags:
        sh.flag("rumor_driven")
    if abn_sector is not None and chg and abs(abn_sector.value or 0) < fl.sector_share * abs(chg):
        sh.flag("sector_move", move, abn_sector)
    if rsi is not None and (rsi.value or 100) < fl.oversold_rsi and near_support:
        sh.flag("oversold_at_support", rsi, support_f)
    if tech and tech.sma_200 and q.last is not None and q.prev_close is not None:
        if q.last < tech.sma_200 <= q.prev_close:
            sh.flag("trend_break", move)
    return sh


def build_macro_facts(
    events: list[EconEventView], *, reaction: object | None, backdrop: MarketConditions | None
) -> FactSheet:
    """Facts for a group of simultaneous releases. *reaction* is a ``reaction.Reaction`` (Task 14)."""
    sh = FactSheet()
    for e in events:
        exp = e.forecast or e.consensus
        sh.add(
            e.title,
            parse_value(e.actual),
            f"{e.actual or 'n/a'} vs {exp or 'n/a'} est (prev {e.previous or 'n/a'})",
        )
    moves = getattr(reaction, "moves", None) or []
    for m in moves:
        if m.move is not None:
            sh.add(
                f"{m.asset} reaction ({m.symbol})",
                round(m.move, 2),
                f"{m.symbol} {m.move:+.2f}{m.unit}",
            )
    _backdrop(sh, backdrop)
    return sh


def build_market_facts(tape: dict[str, Quote], backdrop: MarketConditions | None) -> FactSheet:
    sh = FactSheet()
    for sym, q in tape.items():
        if q.change_pct is not None:
            sh.add(f"{sym} today", _r1(q.change_pct), f"{sym} {q.change_pct:+.1f}%")
    _backdrop(sh, backdrop)
    return sh


def _backdrop(sh: FactSheet, b: MarketConditions | None) -> None:
    if b is None:
        return
    if b.vix is not None:
        sh.add("VIX", _r1(b.vix), f"VIX {b.vix:.1f}")
    if b.vix_term_ratio is not None:
        sh.add("VIX/VIX3M", round(b.vix_term_ratio, 2), f"VIX/VIX3M {b.vix_term_ratio:.2f}")
    if b.ten_year_yield is not None:
        sh.add("10y yield", round(b.ten_year_yield, 2), f"10y {b.ten_year_yield:.2f}%")
    if b.ten_year_change_5d_bp is not None:
        sh.add(
            "10y 5d change",
            round(b.ten_year_change_5d_bp),
            f"10y {b.ten_year_change_5d_bp:+.0f}bp 5d",
        )
