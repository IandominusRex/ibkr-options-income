# tests/test_news_links.py
from __future__ import annotations

from datetime import UTC, datetime

from src.news import links as L
from src.news.schemas import ClusterView, ItemView

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)


def test_pick_primary_by_rank() -> None:
    items = [
        ItemView(title="a", source_domain="yahoo.com", url="u1"),
        ItemView(title="b", source_domain="reuters.com", url="u2"),
    ]
    picked = L.pick_primary(items, ["reuters.com", "cnbc.com"])
    assert picked is not None and picked.url == "u2"
    assert L.pick_primary([], ["reuters.com"]) is None


def test_links_for_ranks_dedupes_by_outlet_and_caps_at_four() -> None:
    items = [
        ItemView(title="a", source="Yahoo", source_domain="yahoo.com", url="https://yahoo.com/1"),
        ItemView(
            title="b", source="Reuters", source_domain="reuters.com", url="https://reuters.com/2"
        ),
        ItemView(
            title="b2", source="Reuters", source_domain="reuters.com", url="https://reuters.com/3"
        ),
        ItemView(title="c", source="CNBC", source_domain="cnbc.com", url="https://cnbc.com/4"),
        ItemView(title="d", source="Blog", source_domain="blog.io", url="https://blog.io/5"),
        ItemView(title="e", source="Other", source_domain="other.io", url="https://other.io/6"),
        ItemView(title="no url", source="NoUrl", source_domain="nourl.io", url=None),
    ]
    cl = ClusterView(
        id=1,
        headline="h",
        category="macro",
        first_seen=NOW,
        last_seen=NOW,
        source_count=6,
        items=items,
    )
    out = L.links_for(cl, ["reuters.com", "cnbc.com"])
    assert [(x.name, x.url) for x in out[:2]] == [
        ("Reuters", "https://reuters.com/2"),
        ("CNBC", "https://cnbc.com/4"),
    ]
    assert (
        len(out) == 4 and len({x.name for x in out}) == 4 and "NoUrl" not in {x.name for x in out}
    )
