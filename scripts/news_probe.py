"""Live probe of every news source — run before go-live and whenever a source looks dead.

Usage:
    python -m scripts.news_probe

Prints, per source, whether it answered and how many items it returned, and re-derives the
Nasdaq economic-calendar date offset (spec §5.1) by matching this week's past ForexFactory
events against Nasdaq's rows for date=D and date=D+1. Read-only; writes nothing.
"""

from __future__ import annotations

from datetime import date, timedelta

from src.common.config import get_config
from src.news.text import normalize_title


def _norm(title: str) -> str:
    t = normalize_title(title)
    for suffix in (" m m", " y y", " q q", " mom", " yoy"):
        t = t.replace(suffix, "")
    return t.strip()


def infer_offset(
    ff_titles_by_day: dict[date, set[str]],
    nasdaq_titles_by_request_day: dict[date, set[str]],
    *,
    synonyms: dict[str, str],
) -> int | None:
    """The offset k such that Nasdaq's rows for date=D+k best contain ForexFactory's day-D titles."""
    scores: dict[int, int] = {}
    for day, titles in ff_titles_by_day.items():
        wanted = {synonyms.get(t, t) for t in titles}
        for k in (0, 1):
            got = nasdaq_titles_by_request_day.get(day + timedelta(days=k), set())
            scores[k] = scores.get(k, 0) + len(wanted & got)
    if not scores or max(scores.values()) == 0:
        return None
    return max(scores, key=lambda k: scores[k])


def main() -> None:
    from src.news.playbook import load_playbook

    from src.data import factory
    from src.data.nasdaq_backend import _get, parse_nasdaq_econ

    cfg = get_config()
    pb = load_playbook()
    today = date.today()

    ff = factory.get_econ_schedule_provider().this_week()
    print(f"forexfactory: {len(ff)} events this week")
    ff_by_day: dict[date, set[str]] = {}
    for e in ff:
        d = e.scheduled_at.date()
        if e.country == "USD" and d < today:
            ff_by_day.setdefault(d, set()).add(_norm(e.title))
    nd: dict[date, set[str]] = {}
    for d in sorted(ff_by_day):
        for k in (0, 1):
            body = _get("economicevents", d + timedelta(days=k))
            nd[d + timedelta(days=k)] = {_norm(r.title) for r in parse_nasdaq_econ(body or {}, d)}
    synonyms = {_norm(a): _norm(e.aliases[0]) for e in pb.entries for a in e.aliases}
    off = infer_offset(ff_by_day, nd, synonyms=synonyms)
    print(
        f"nasdaq econ date offset: inferred {off} (configured {cfg.news.sources.nasdaq_econ_date_offset_days})"
    )

    for feed in cfg.news.sources.rss_feeds:
        res = factory.get_feed_provider().fetch(feed.url)
        print(f"rss {feed.name}: {len(res.items)} items")
    fh = factory.get_finnhub_client()
    print(
        "finnhub:", "dormant (no key)" if fh is None else f"{len(fh.general_news())} general items"
    )


if __name__ == "__main__":
    main()
