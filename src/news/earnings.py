"""Earnings calendar: merge three sources, persist, and report each release exactly once."""

from __future__ import annotations

from datetime import date, datetime

from src.data.protocols import EarningsItem
from src.news.store.models import EarningsEventRow
from src.news.store.queries import naive_utc
from src.news.store.session import news_session


def merge_earnings(
    nasdaq: list[EarningsItem], finnhub: list[EarningsItem], yf_next: dict[str, date]
) -> list[EarningsItem]:
    """Nasdaq wins timing and consensus EPS; Finnhub wins actuals and revenue; yfinance only
    supplies a date when neither calendar lists the symbol."""
    merged: dict[tuple[str, date], EarningsItem] = {}
    for it in finnhub:
        merged[(it.symbol, it.report_date)] = it
    for it in nasdaq:
        key = (it.symbol, it.report_date)
        base = merged.get(key)
        if base is None:
            merged[key] = it
            continue
        merged[key] = base.model_copy(
            update={
                "timing": it.timing if it.timing != "unknown" else base.timing,
                "eps_est": it.eps_est if it.eps_est is not None else base.eps_est,
                "source": "nasdaq+finnhub",
            }
        )
    listed = {s for s, _ in merged}
    for sym, d in yf_next.items():
        if sym not in listed:
            merged[(sym, d)] = EarningsItem(symbol=sym, report_date=d, source="yfinance")
    return list(merged.values())


def upsert_earnings(items: list[EarningsItem], *, now: datetime) -> list[tuple[str, date]]:
    released: list[tuple[str, date]] = []
    now_n = naive_utc(now)
    with news_session() as s:
        for it in items:
            row = s.get(EarningsEventRow, (it.symbol, it.report_date))
            if row is None:
                row = EarningsEventRow(
                    symbol=it.symbol,
                    report_date=it.report_date,
                    timing="unknown",
                    status="scheduled",
                    alerted=False,
                )
                s.add(row)
            if it.timing != "unknown":
                row.timing = it.timing
            for f in ("eps_est", "eps_actual", "rev_est", "rev_actual"):
                v = getattr(it, f)
                if v is not None:
                    setattr(row, f, v)
            if row.eps_actual is not None and row.status != "released":
                row.status = "released"
                row.released_seen_at = now_n
                released.append((it.symbol, it.report_date))
    return released
