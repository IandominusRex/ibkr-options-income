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


def load_aliases(
    symbols: list[str], *, overrides: dict[str, list[str]], now: datetime
) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    now_n = naive_utc(now)
    with news_session() as s:
        for sym in symbols:
            row = s.get(TickerAliasRow, sym)
            if row is None or now_n - row.fetched_at > _TTL:
                info = get_fundamentals_provider().get_info(sym) or {}
                names = {
                    clean_company_name(str(info.get(k) or "")) for k in ("shortName", "longName")
                }
                aliases = sorted(n for n in names if n)
                if row is None:
                    s.add(TickerAliasRow(symbol=sym, aliases=aliases, fetched_at=now_n))
                else:
                    row.aliases, row.fetched_at = aliases, now_n
            else:
                aliases = list(row.aliases or [])
            out[sym] = sorted(set(aliases) | set(overrides.get(sym, [])))
    return out
