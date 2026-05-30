"""Fundamental stats from yfinance: earnings dates, quality screen, dividend safety.

Designed to degrade gracefully — yfinance returns incomplete data for ETFs and
some symbols. Every field read is wrapped defensively. ETFs pass quality by default.
"""

from __future__ import annotations

from datetime import date, datetime

import yfinance as yf

from src.common.schemas import FundamentalStats

_PAYOUT_RATIO_SAFE = 0.60
_MAX_DEBT_TO_EQUITY = 150.0


def get_fundamental_stats(symbol: str) -> FundamentalStats:
    """Return FundamentalStats for *symbol*. Never raises — always returns a valid object."""
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info or {}
    except Exception:
        return FundamentalStats(symbol=symbol)

    # ETF shortcut — almost no fundamental data available
    if info.get("quoteType") == "ETF":
        return FundamentalStats(symbol=symbol, quality_flag=True)

    next_earnings = _next_earnings_date(ticker)
    pe_ratio = _safe_float(info.get("trailingPE"))
    free_cash_flow = _safe_float(info.get("freeCashflow"))
    debt_to_equity = _safe_float(info.get("debtToEquity"))
    dividend_yield = _safe_float(info.get("dividendYield"))
    ex_div_date = _ex_dividend_date(info)
    dividend_safe = _dividend_safety(info, free_cash_flow)
    quality_flag = _quality_screen(pe_ratio, debt_to_equity, free_cash_flow)

    return FundamentalStats(
        symbol=symbol,
        next_earnings=next_earnings,
        pe_ratio=pe_ratio,
        free_cash_flow=free_cash_flow,
        debt_to_equity=debt_to_equity,
        dividend_yield=dividend_yield,
        ex_dividend_date=ex_div_date,
        dividend_safe=dividend_safe,
        quality_flag=quality_flag,
    )


# --------------------------------------------------------------------------- #
# Field helpers
# --------------------------------------------------------------------------- #


def _next_earnings_date(ticker: yf.Ticker) -> date | None:
    try:
        cal = ticker.calendar
        if not cal:
            return None
        earnings_dates = cal.get("Earnings Date", [])
        if not earnings_dates:
            return None
        today = date.today()
        for ts in earnings_dates:
            d = ts.date() if hasattr(ts, "date") else ts
            if isinstance(d, date) and d >= today:
                return d
    except Exception:
        pass
    return None


def _ex_dividend_date(info: dict) -> date | None:
    try:
        ts = info.get("exDividendDate")
        if ts is None:
            return None
        return datetime.fromtimestamp(int(ts)).date()
    except Exception:
        return None


def _dividend_safety(info: dict, free_cash_flow: float | None) -> bool | None:
    payout = _safe_float(info.get("payoutRatio"))
    if payout is None or free_cash_flow is None:
        return None
    return payout < _PAYOUT_RATIO_SAFE and free_cash_flow > 0


def _quality_screen(
    pe_ratio: float | None,
    debt_to_equity: float | None,
    free_cash_flow: float | None,
) -> bool | None:
    if pe_ratio is None and debt_to_equity is None and free_cash_flow is None:
        return None
    if pe_ratio is None or debt_to_equity is None or free_cash_flow is None:
        return None
    return pe_ratio > 0 and debt_to_equity < _MAX_DEBT_TO_EQUITY and free_cash_flow > 0


def _safe_float(value: object) -> float | None:
    import math

    try:
        if value is None:
            return None
        f = float(str(value))
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None
