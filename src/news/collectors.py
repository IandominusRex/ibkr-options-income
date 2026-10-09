"""Poll every source into data/news.db (spec §5.1). Each method is one source, never raises
past its own boundary (sources already never raise), and is called from service loops."""

from __future__ import annotations

import logging
import math
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from src.common.books import is_spreads_underlying
from src.common.config import NewsCfg
from src.common.schemas import PositionSnapshot
from src.common.universe import effective_universe
from src.data.factory import (
    get_earnings_calendar_provider,
    get_econ_actuals_provider,
    get_econ_schedule_provider,
    get_feed_provider,
    get_finnhub_client,
    get_news_provider,
    get_news_search_provider,
)
from src.data.protocols import NewsItem
from src.news.aliases import load_aliases
from src.news.earnings import merge_earnings, upsert_earnings
from src.news.ingest import IngestResult, ingest
from src.news.playbook import load_playbook, norm_event_title, surprise_dir
from src.news.store.models import EconEventRow, FeedStateRow
from src.news.store.queries import naive_utc
from src.news.store.session import news_session
from src.news.store.state import record_source_ok
from src.news.tagging import AliasIndex, build_alias_index
from src.storage.portfolio_snapshots import load_latest_portfolio_snapshot

log = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")
_UNIVERSE_LISTS = ("indexes", "watchlist", "would_own", "actively_wheeling")


def held_positions() -> list[PositionSnapshot]:
    snap = load_latest_portfolio_snapshot()
    return list(snap.positions) if snap else []


def held_underlyings() -> set[str]:
    return {(p.underlying or p.symbol).upper() for p in held_positions() if p.position != 0}


def universe_lists(symbol: str) -> list[str]:
    u = effective_universe()
    return [
        name
        for name in _UNIVERSE_LISTS
        if symbol.upper() in {str(x).upper() for x in (u.get(name) or [])}
    ]


def watch_symbols() -> list[str]:
    u = effective_universe()
    syms = {str(x).upper() for name in _UNIVERSE_LISTS for x in (u.get(name) or [])}
    syms |= held_underlyings()
    return sorted(s for s in syms if not is_spreads_underlying(s))


def _yf_items(raw: list[dict]) -> list[NewsItem]:
    from src.claude.news_context import _news_item_from_yfinance

    return [i for i in (_news_item_from_yfinance(r) for r in raw) if i is not None]


def _event_key(scheduled_at: datetime, title: str) -> str:
    return f"{scheduled_at.astimezone(UTC):%Y-%m-%dT%H:%M}|{title}"


class Collector:
    def __init__(self, cfg: NewsCfg) -> None:
        self.cfg = cfg
        self._cursor = 0
        self._alias: AliasIndex | None = None
        self._alias_at: datetime | None = None

    # -- tagging context ---------------------------------------------------------------
    def alias_index(self, now: datetime) -> AliasIndex:
        if (
            self._alias is None
            or self._alias_at is None
            or now - self._alias_at > timedelta(hours=1)
        ):
            syms = watch_symbols()
            self._alias = build_alias_index(
                syms, load_aliases(syms, overrides=self.cfg.tagging.aliases, now=now)
            )
            self._alias_at = now
        return self._alias

    def _scheduled(self, now: datetime) -> tuple[frozenset[str], tuple[str, ...]]:
        lo, hi = naive_utc(now - timedelta(days=1)), naive_utc(now + timedelta(days=1))
        with news_session() as s:
            titles = s.scalars(
                select(EconEventRow.title).where(EconEventRow.scheduled_at.between(lo, hi))
            )
            terms = tuple(sorted({norm_event_title(t) for t in titles if norm_event_title(t)}))
        from src.news.store.models import EarningsEventRow

        with news_session() as s:
            syms = frozenset(
                s.scalars(
                    select(EarningsEventRow.symbol).where(
                        EarningsEventRow.report_date.between(
                            (now - timedelta(days=1)).date(), (now + timedelta(days=1)).date()
                        )
                    )
                )
            )
        return syms, terms

    def _ingest(
        self, items: list[NewsItem], *, category: str, origin: str, now: datetime
    ) -> IngestResult:
        if not items:
            return IngestResult()
        syms, terms = self._scheduled(now)
        return ingest(
            items,
            category=category,
            origin=origin,
            alias_index=self.alias_index(now),
            cfg=self.cfg,
            now=now,
            scheduled_symbols=syms,
            scheduled_terms=terms,
        )

    # -- sources -----------------------------------------------------------------------
    def collect_rss(self, now: datetime) -> int:
        total = 0
        provider = get_feed_provider()
        for feed in self.cfg.sources.rss_feeds:
            with news_session() as s:
                st = s.get(FeedStateRow, feed.url)
                etag, lm = (st.etag, st.last_modified) if st else (None, None)
            res = provider.fetch(feed.url, etag=etag, last_modified=lm)
            with news_session() as s:
                st = s.get(FeedStateRow, feed.url) or FeedStateRow(feed_url=feed.url)
                st.last_polled = naive_utc(now)
                if res.items or res.not_modified:
                    st.etag, st.last_modified, st.last_ok = (
                        res.etag,
                        res.last_modified,
                        naive_utc(now),
                    )
                s.merge(st)
            total += self._ingest(
                res.items, category=feed.category, origin="rss", now=now
            ).new_items
        record_source_ok("rss", now)
        return total

    def collect_macro(self, now: datetime) -> int:
        total = 0
        search = get_news_search_provider()
        for q in self.cfg.sources.macro_queries:
            items = search.search(q, days=self.cfg.sources.google_news_days, limit=15)
            total += self._ingest(items, category="macro", origin="google", now=now).new_items
        fh = get_finnhub_client()
        if fh is not None:
            total += self._ingest(
                fh.general_news(), category="markets", origin="finnhub", now=now
            ).new_items
        record_source_ok("macro", now)
        return total

    def collect_symbol(self, symbol: str, now: datetime) -> IngestResult:
        items: list[NewsItem] = []
        items += get_news_search_provider().search(
            symbol, days=self.cfg.sources.google_news_days, limit=10
        )
        items += _yf_items(get_news_provider().get_headlines(symbol, limit=15) or [])
        fh = get_finnhub_client()
        if fh is not None:
            items += fh.company_news(symbol, days=self.cfg.sources.google_news_days)
        return self._ingest(items, category="ticker", origin="mixed", now=now)

    def collect_ticker_batch(self, now: datetime, *, batch: int) -> int:
        syms = watch_symbols()
        if not syms:
            return 0
        total = 0
        for _ in range(min(batch, len(syms))):
            sym = syms[self._cursor % len(syms)]
            self._cursor += 1
            total += self.collect_symbol(sym, now).new_items
        record_source_ok("tickers", now)
        return total

    def ticker_batch_size(self, loop_minutes: float) -> int:
        n = len(watch_symbols())
        return max(1, math.ceil(n * loop_minutes / self.cfg.sources.ticker_round_robin_minutes))

    def refresh_econ_schedule(self, now: datetime) -> int:
        pb = load_playbook()
        n = 0
        with news_session() as s:
            for e in get_econ_schedule_provider().this_week():
                if e.country != "USD" or e.impact not in ("High", "Medium"):
                    continue
                key = _event_key(e.scheduled_at, e.title)
                row = s.get(EconEventRow, key)
                entry = pb.match(e.title)
                if row is None:
                    s.add(
                        EconEventRow(
                            event_key=key,
                            title=e.title,
                            playbook_key=entry.key if entry else None,
                            scheduled_at=naive_utc(e.scheduled_at),
                            impact=e.impact,
                            forecast=e.forecast,
                            previous=e.previous,
                            alerted=False,
                        )
                    )
                    n += 1
                else:
                    row.forecast, row.previous, row.impact = e.forecast, e.previous, e.impact
        record_source_ok("econ_schedule", now)
        return n

    def refresh_econ_actuals(self, now: datetime) -> list[str]:
        pb = load_playbook()
        released: list[str] = []
        today = now.astimezone(ET).date()
        with news_session() as s:
            pending = list(
                s.scalars(
                    select(EconEventRow).where(
                        EconEventRow.actual.is_(None),
                        EconEventRow.scheduled_at <= naive_utc(now),
                        EconEventRow.scheduled_at >= naive_utc(now - timedelta(days=2)),
                    )
                )
            )
            days = sorted(
                {r.scheduled_at.replace(tzinfo=UTC).astimezone(ET).date() for r in pending}
                | {today}
            )
            rows_by_day = {d: get_econ_actuals_provider().actuals(d) for d in days if pending}
            for r in pending:
                et_at = r.scheduled_at.replace(tzinfo=UTC).astimezone(ET)
                for a in rows_by_day.get(et_at.date(), []):
                    if a.et_time != f"{et_at:%H:%M}" or a.actual is None:
                        continue
                    same_key = (
                        r.playbook_key
                        and (m := pb.match(a.title)) is not None
                        and m.key == r.playbook_key
                    )
                    same_title = norm_event_title(a.title) == norm_event_title(r.title)
                    if not (same_key or same_title):
                        continue
                    r.actual, r.consensus, r.actual_seen_at = a.actual, a.consensus, naive_utc(now)
                    entry = pb.match(r.title)
                    if entry is not None:
                        r.surprise_dir = surprise_dir(entry, a.actual, r.forecast or a.consensus)
                    released.append(r.event_key)
                    break
        record_source_ok("econ_actuals", now)
        return released

    def in_fast_econ_window(self, now: datetime) -> bool:
        before = timedelta(minutes=self.cfg.sources.econ_fast_window_before_min)
        after = timedelta(minutes=self.cfg.sources.econ_fast_window_after_min)
        with news_session() as s:
            hit = s.scalar(
                select(EconEventRow.event_key).where(
                    EconEventRow.actual.is_(None),
                    EconEventRow.scheduled_at.between(
                        naive_utc(now - after), naive_utc(now + before)
                    ),
                )
            )
        return hit is not None

    def refresh_earnings(self, now: datetime, *, days: int = 14) -> list[tuple[str, date]]:
        syms = set(watch_symbols())
        start = now.astimezone(ET).date() - timedelta(days=1)
        end = start + timedelta(days=days)
        nd = []
        d = start
        cal = get_earnings_calendar_provider()
        while d <= end:
            if d.weekday() < 5:
                nd += [e for e in cal.on(d) if e.symbol in syms]
            d += timedelta(days=1)
        fh_rows = []
        fh = get_finnhub_client()
        if fh is not None:
            fh_rows = [e for e in fh.earnings_calendar(start, end) if e.symbol in syms]
        yf_next: dict[str, date] = {}
        from src.analytics.fundamentals import get_fundamental_stats

        for sym in syms:
            try:
                nxt = get_fundamental_stats(sym).next_earnings
            except Exception:
                nxt = None
            if nxt and start <= nxt <= end:
                yf_next[sym] = nxt
        released = upsert_earnings(merge_earnings(nd, fh_rows, yf_next), now=now)
        record_source_ok("earnings", now)
        return released
