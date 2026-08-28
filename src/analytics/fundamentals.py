"""Fundamental stats from yfinance: earnings dates, quality screen, dividend safety.

Designed to degrade gracefully — yfinance returns incomplete data for ETFs and
some symbols. Every field read is wrapped defensively. ETFs pass quality by default.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from src.common.cache import daily_cached
from src.common.market_hours import today_et
from src.common.schemas import FundamentalStats
from src.data.factory import get_fundamentals_provider
from src.storage.db import session_scope
from src.storage.models import FundamentalCacheRow

_PAYOUT_RATIO_SAFE = 0.60
_MAX_DEBT_TO_EQUITY = 150.0


@daily_cached
def get_fundamental_stats(symbol: str) -> FundamentalStats:
    """Return FundamentalStats for *symbol*. Never raises — always returns a valid object.

    The result is cached on disk in ``FundamentalCacheRow`` with an earnings-aware TTL:
    * If the next earnings date is within ±2 weeks of today → refresh after 1 day.
    * Otherwise → refresh after 30 days.
    The in-process ``@daily_cached`` layer remains for speed and as a fallback when the
    persistent cache cannot be accessed.
    """
    now_utc = datetime.now(UTC)
    today = today_et()

    # 1️⃣ Try persistent DB cache.
    try:
        with session_scope() as sess:
            row = sess.get(FundamentalCacheRow, symbol)
            if row:
                earnings = row.next_earnings_date
                ttl_days = 1 if (earnings and abs((earnings - today).days) <= 14) else 30
                age_days = (now_utc - row.fetched_at).days
                if age_days <= ttl_days:
                    return FundamentalStats.model_validate_json(row.data_json)
    except Exception:
        pass

    # 2️⃣ Fresh fetch from the configured fundamentals provider.
    try:
        provider = get_fundamentals_provider()
        info = provider.get_info(symbol) or {}
    except Exception:
        return FundamentalStats(symbol=symbol)

    if info.get("quoteType") == "ETF":
        stats = FundamentalStats(
            symbol=symbol,
            quality_flag=True,
            fifty_two_week_high=_safe_float(info.get("fiftyTwoWeekHigh")),
            fifty_two_week_low=_safe_float(info.get("fiftyTwoWeekLow")),
        )
    else:
        next_earnings = _next_earnings_date(provider.get_calendar(symbol))
        pe_ratio = _safe_float(info.get("trailingPE"))
        free_cash_flow = _safe_float(info.get("freeCashflow"))
        debt_to_equity = _safe_float(info.get("debtToEquity"))
        raw_dividend_yield = _safe_float(info.get("dividendYield"))
        dividend_yield = raw_dividend_yield / 100.0 if raw_dividend_yield is not None else None
        ex_div_date = _ex_dividend_date(info)
        dividend_safe = _dividend_safety(info, free_cash_flow)
        quality_flag = _quality_screen(pe_ratio, debt_to_equity, free_cash_flow)

        stats = FundamentalStats(
            symbol=symbol,
            next_earnings=next_earnings,
            pe_ratio=pe_ratio,
            free_cash_flow=free_cash_flow,
            debt_to_equity=debt_to_equity,
            dividend_yield=dividend_yield,
            ex_dividend_date=ex_div_date,
            dividend_safe=dividend_safe,
            quality_flag=quality_flag,
            target_mean_price=_safe_float(info.get("targetMeanPrice")),
            target_high_price=_safe_float(info.get("targetHighPrice")),
            target_low_price=_safe_float(info.get("targetLowPrice")),
            recommendation_key=_safe_str(info.get("recommendationKey")),
            fifty_two_week_high=_safe_float(info.get("fiftyTwoWeekHigh")),
            fifty_two_week_low=_safe_float(info.get("fiftyTwoWeekLow")),
        )

    # 3️⃣ Persist the fresh result for future runs.
    try:
        with session_scope() as sess:
            row = sess.get(FundamentalCacheRow, symbol)
            json_data = stats.model_dump_json()
            if row:
                row.data_json = json_data
                row.fetched_at = now_utc
                row.next_earnings_date = stats.next_earnings
            else:
                row = FundamentalCacheRow(
                    symbol=symbol,
                    data_json=json_data,
                    fetched_at=now_utc,
                    next_earnings_date=stats.next_earnings,
                )
                sess.add(row)
    except Exception:
        pass

    return stats


# --------------------------------------------------------------------------- #
# Field helpers
# --------------------------------------------------------------------------- #


def _next_earnings_date(calendar: dict) -> date | None:
    try:
        if not calendar:
            return None
        earnings_dates = calendar.get("Earnings Date", [])
        if not earnings_dates:
            return None
        today = today_et()
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


def _safe_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _safe_float(value: object) -> float | None:
    import math

    try:
        if value is None:
            return None
        f = float(str(value))
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None
