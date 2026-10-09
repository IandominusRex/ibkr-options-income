"""Ticker → company-name aliases for headline tagging, cached 30 days in ticker_aliases."""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from src.data.factory import get_fundamentals_provider
from src.news.store.models import TickerAliasRow
from src.news.store.queries import naive_utc
from src.news.store.session import news_session

_SUFFIX = re.compile(
    r"[,.]?\s+(inc|corp|corporation|co|company|holdings?|group|plc|ltd|limited|n\.?v|s\.?a|class [a-c]|ord|adr)\.?\b.*$",
    re.I,
)
_FUND = re.compile(
    r"\b(etf|trust|fund|proshares|direxion|spdr|ishares|invesco|ultra|bull|bear|2x|3x)\b", re.I
)
_TTL = timedelta(days=30)


def clean_company_name(name: str) -> str | None:
    if not name or _FUND.search(name):
        return None
    t = _SUFFIX.sub("", name.strip()).strip(" ,.")
    return t if len(t) >= 3 else None


def _fetch_aliases(symbol: str) -> list[str]:
    info = get_fundamentals_provider().get_info(symbol) or {}
    names = {clean_company_name(str(info.get(k) or "")) for k in ("shortName", "longName")}
    return sorted(n for n in names if n)


def load_aliases(
    symbols: list[str], *, overrides: dict[str, list[str]], now: datetime
) -> dict[str, list[str]]:
    """Cached aliases per symbol; stale or missing ones are fetched from the fundamentals
    provider with no transaction open (a first build is ~one get_info call per symbol, and
    holding news.db's write lock across them would stall every other writer)."""
    now_n = naive_utc(now)
    with news_session() as s:
        cached: dict[str, list[str]] = {}
        for sym in symbols:
            row = s.get(TickerAliasRow, sym)
            if row is not None and now_n - row.fetched_at <= _TTL:
                cached[sym] = list(row.aliases or [])
    fetched = {sym: _fetch_aliases(sym) for sym in symbols if sym not in cached}
    if fetched:
        with news_session() as s:
            for sym, aliases in fetched.items():
                s.merge(TickerAliasRow(symbol=sym, aliases=aliases, fetched_at=now_n))
    found = {**cached, **fetched}
    return {sym: sorted(set(found[sym]) | set(overrides.get(sym, []))) for sym in symbols}
