"""Primary-source choice and inline links for a cluster. Imports only schemas, so the web API
can use it without loading the news process's read-write engine (fence §10.6)."""

from __future__ import annotations

from src.news.schemas import ClusterView, ItemView, SourceLink


def pick_primary(items: list[ItemView], rank: list[str]) -> ItemView | None:
    if not items:
        return None
    order = {d: i for i, d in enumerate(rank)}
    return min(items, key=lambda it: order.get(it.source_domain or "", len(order)))


def links_for(cluster: ClusterView, rank: list[str]) -> list[SourceLink]:
    return links_for_items(cluster.items, rank)


def links_for_items(items: list[ItemView], rank: list[str]) -> list[SourceLink]:
    order = {d: i for i, d in enumerate(rank)}
    seen: set[str] = set()
    out: list[SourceLink] = []
    for it in sorted(items, key=lambda it: order.get(it.source_domain or "", len(order))):
        name = it.source or it.source_domain
        if it.url and name and name not in seen:
            seen.add(name)
            out.append(SourceLink(name=name, url=it.url))
    return out[:4]
