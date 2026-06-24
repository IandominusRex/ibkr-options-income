"""Sector/market backdrop for a single-ticker scan.

Answers "how is this name's industry — and the broad market — trading right now?" so the
reasoning layer (`/scan TICKER`) can place the ticker in context rather than judging it in a
vacuum. Looks up the ticker's GICS sector via yfinance, maps it to its SPDR sector ETF, and
computes recent returns for the sector ETF, SPY, and the ticker itself from the day-cached OHLCV
store (`price_data.get_ohlcv`). Everything is fail-soft: any missing piece degrades to None and
the rest still renders. Enrichment only — `SectorContext` never reaches the deterministic engine.
"""

from __future__ import annotations

import logging

import pandas as pd

from src.analytics.price_data import get_ohlcv
from src.common.cache import daily_cached
from src.common.schemas import SectorContext

log = logging.getLogger(__name__)

# yfinance GICS sector string → SPDR sector ETF proxy. Keys match Yahoo's `sector` field.
_SECTOR_ETF: dict[str, str] = {
    "Technology": "XLK",
    "Financial Services": "XLF",
    "Healthcare": "XLV",
    "Consumer Cyclical": "XLY",
    "Consumer Defensive": "XLP",
    "Energy": "XLE",
    "Industrials": "XLI",
    "Basic Materials": "XLB",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
    "Communication Services": "XLC",
}

_ONE_MONTH_SESSIONS = 21
_ONE_WEEK_SESSIONS = 5


@daily_cached
def _sector_industry(symbol: str) -> tuple[str | None, str | None]:
    """(sector, industry) from yfinance. ETFs/indices return (None, None). Never raises."""
    try:
        import yfinance as yf

        info = yf.Ticker(symbol).info or {}
    except Exception as exc:
        log.debug("sector_context: info lookup failed for %s: %s", symbol, exc)
        return None, None
    if info.get("quoteType") == "ETF":
        return None, None
    sector = info.get("sector") or None
    industry = info.get("industry") or None
    return sector, industry


def _pct_return(symbol: str, sessions: int) -> float | None:
    """Percent change of *symbol*'s close over the last *sessions* settled bars. None if short."""
    try:
        df = get_ohlcv(symbol)
    except Exception as exc:
        log.debug("sector_context: ohlcv failed for %s: %s", symbol, exc)
        return None
    if df is None or df.empty or "Close" not in df:
        return None
    close: pd.Series = df["Close"].dropna()
    if len(close) <= sessions:
        return None
    past = float(close.iloc[-1 - sessions])
    now = float(close.iloc[-1])
    if past <= 0:
        return None
    return round((now / past - 1.0) * 100.0, 2)


def get_sector_context(symbol: str) -> SectorContext:
    """Build the sector/market backdrop for *symbol*. Never raises — missing data → None fields.

    Cheap and day-cached at the source layer (`get_ohlcv` and the sector lookup are both cached),
    so a repeated `/scan TICKER` doesn't re-hit yfinance.
    """
    symbol = symbol.upper()
    sector, industry = _sector_industry(symbol)
    etf = _SECTOR_ETF.get(sector) if sector else None

    sector_1mo = _pct_return(etf, _ONE_MONTH_SESSIONS) if etf else None
    sector_5d = _pct_return(etf, _ONE_WEEK_SESSIONS) if etf else None
    spy_1mo = _pct_return("SPY", _ONE_MONTH_SESSIONS)
    sym_1mo = _pct_return(symbol, _ONE_MONTH_SESSIONS)
    rel = (
        round(sym_1mo - sector_1mo, 2)
        if sym_1mo is not None and sector_1mo is not None
        else None
    )

    return SectorContext(
        symbol=symbol,
        sector=sector,
        industry=industry,
        sector_etf=etf,
        sector_ret_1mo_pct=sector_1mo,
        sector_ret_5d_pct=sector_5d,
        spy_ret_1mo_pct=spy_1mo,
        symbol_ret_1mo_pct=sym_1mo,
        rel_strength_1mo_pct=rel,
    )


def render_sector_context(sc: SectorContext | None) -> str:
    """One compact multi-line prompt block, or '' when there's nothing useful to say."""
    if sc is None:
        return ""
    rows: list[str] = []
    if sc.sector:
        label = sc.sector + (f" / {sc.industry}" if sc.industry else "")
        etf = f" (proxy {sc.sector_etf})" if sc.sector_etf else ""
        rows.append(f"  Sector:        {label}{etf}")
    if sc.sector_ret_1mo_pct is not None:
        wk = f", {sc.sector_ret_5d_pct:+.1f}% 5d" if sc.sector_ret_5d_pct is not None else ""
        rows.append(f"  Sector 1mo:    {sc.sector_ret_1mo_pct:+.1f}%{wk}")
    if sc.spy_ret_1mo_pct is not None:
        rows.append(f"  SPY 1mo:       {sc.spy_ret_1mo_pct:+.1f}% (broad market)")
    if sc.symbol_ret_1mo_pct is not None:
        rel = (
            f"  ({sc.rel_strength_1mo_pct:+.1f}% vs sector — "
            f"{'out' if (sc.rel_strength_1mo_pct or 0) >= 0 else 'under'}performing)"
            if sc.rel_strength_1mo_pct is not None
            else ""
        )
        rows.append(f"  {sc.symbol} 1mo:{' ' * max(1, 7 - len(sc.symbol))}{sc.symbol_ret_1mo_pct:+.1f}%{rel}")
    if not rows:
        return ""
    return "=== SECTOR & MARKET BACKDROP (place the ticker in context) ===\n" + "\n".join(rows)
