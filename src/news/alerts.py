"""Turn an admitted AlertCandidate into a CardPayload, and decide new / update / reply (spec §7.2)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal

from sqlalchemy import select

from src.common.config import Config
from src.common.schemas import MarketConditions, PositionSnapshot
from src.news.facts import Analytics, build_macro_facts, build_market_facts, build_ticker_facts
from src.news.links import links_for, pick_primary  # noqa: F401  (re-exported)
from src.news.playbook import ASSETS, Playbook, prior_for
from src.news.render import SGT
from src.news.schemas import CardPayload, ClusterView, EarningsView, EconEventView, GridRow
from src.news.store import queries
from src.news.store.models import EconEventRow, NewsPostRow
from src.news.store.queries import naive_utc
from src.news.store.session import news_session
from src.news.tape import Quote
from src.news.triggers import AlertCandidate

_SURPRISE_WORD = {
    "hot": "hotter than expected",
    "cold": "cooler than expected",
    "inline": "in line",
}
_SURPRISE_EMOJI = {"hot": "🔴", "cold": "🟢", "inline": "⚪"}


@dataclass
class AlertContext:
    cfg: Config
    an: Analytics
    pb: Playbook
    now: datetime
    today: date
    positions: list[PositionSnapshot]
    held: set[str]
    universe: set[str]
    backdrop: MarketConditions | None
    tape: dict[str, Quote]


@dataclass
class AlertAction:
    action: Literal["new", "update", "reply"]
    payload: CardPayload
    post_id: int | None = None


def _events(keys: list[str]) -> list[EconEventView]:
    with news_session() as s:
        rows = [s.get(EconEventRow, k) for k in keys]
        return [queries.econ_view(r) for r in rows if r is not None]


def _macro_card(c: AlertCandidate, ctx: AlertContext) -> CardPayload:
    evs = _events(c.event_keys)
    primary = evs[0]
    entry = ctx.pb.match(primary.title)
    direction = primary.surprise_dir
    prior = prior_for(entry, direction) if entry else None  # type: ignore[arg-type]
    exp = primary.forecast or primary.consensus
    line = " · ".join(
        f"{e.title} {e.actual or 'n/a'} vs {e.forecast or e.consensus or 'n/a'} est"
        for e in evs[:4]
    )
    word = _SURPRISE_WORD.get(direction or "", "released")
    title = f"{(entry.key.replace('_', ' ').upper() if entry else primary.title)} {word}"
    return CardPayload(
        kind="macro_print",
        subject=c.subject,
        title=title,
        emoji=_SURPRISE_EMOJI.get(direction or "", "📊"),
        when=primary.scheduled_at,
        headline_line=line,
        grid=[GridRow(asset=a, textbook=prior.arrows[a] if prior else None) for a in ASSETS],
        grid_note=f"📈 reaction in ~{ctx.cfg.news.reaction.window_min} min",
        facts=build_macro_facts(evs, reaction=None, backdrop=ctx.backdrop),
        critical=True,
        event_keys=c.event_keys,
        llm_note=None if prior else (f"Expected {exp}" if exp else None),
    )


def _ticker_clusters(symbol: str, now: datetime) -> list[ClusterView]:
    with news_session() as s:
        return queries.clusters_since(s, now - timedelta(hours=24), symbol=symbol, limit=5)


def _earnings_view(symbol: str, today: date) -> EarningsView | None:
    with news_session() as s:
        rows = queries.earnings_between(s, today - timedelta(days=1), today, {symbol})
        return rows[-1] if rows else None


def _ticker_card(
    c: AlertCandidate, ctx: AlertContext, *, kind: Literal["ticker_move", "earnings", "brief"]
) -> CardPayload:
    from src.news.collectors import universe_lists

    sym = c.symbols[0]
    clusters = _ticker_clusters(sym, ctx.now)
    tags = {t for cl in clusters for t in cl.tags}
    earn = _earnings_view(sym, ctx.today) if kind != "ticker_move" else None
    sheet = build_ticker_facts(
        sym,
        an=ctx.an,
        positions=ctx.positions,
        lists=universe_lists(sym),
        earnings=earn,
        cluster_tags=tags,
        today=ctx.today,
        cfg=ctx.cfg.news,
    )
    parts = [
        f.display
        for f in (
            sheet.get("Move today"),
            sheet.get("Move in σ"),
            sheet.get("Move vs SPY"),
            sheet.get("RSI14"),
            sheet.get("Price vs SMA200"),
        )
        if f is not None
    ]
    if earn is not None:
        parts = [
            f.display
            for f in (
                sheet.get("EPS vs est"),
                sheet.get("Revenue vs est"),
                sheet.get("Move ÷ implied"),
            )
            if f
        ] + parts
    top = clusters[0] if clusters else None
    primary = pick_primary(top.items, ctx.cfg.news.source_rank) if top else None
    move = sheet.get("Move today")
    chg = (move.value if move else None) or 0.0
    if kind == "earnings":
        title = f"{sym} earnings"
    elif kind == "brief":
        title = f"{sym} brief"
    else:
        title = f"{sym} {chg:+.1f}%" + ("" if top else " · no identifiable catalyst")
    return CardPayload(
        kind=kind,
        subject=sym,
        title=title,
        emoji="📉" if chg < 0 else "📈",
        when=ctx.now,
        headline_line=top.headline if top else None,
        facts_line=" · ".join(parts) or None,
        facts=sheet,
        links=links_for(top, ctx.cfg.news.source_rank) if top else [],
        image_url=primary.image_url if primary else None,
        preview_url=primary.url if primary else None,
        critical=c.critical,
        cluster_ids=[cl.id for cl in clusters],
    )


def _market_card(c: AlertCandidate, ctx: AlertContext) -> CardPayload:
    sym = c.symbols[0]
    chg = float(c.detail.get("change_pct") or 0.0)
    if c.kind == "vix_spike":
        title = (
            f"VIX {float(c.detail.get('last') or 0):.1f}"
            if "level" in c.detail
            else f"VIX +{chg:.0f}%"
        )
        emoji = "⚠️"
    else:
        title = f"{sym} {chg:+.1f}% (crossed {float(c.detail.get('level') or 0):+.0f}%)"
        emoji = "🔴" if chg < 0 else "🟢"
    facts = build_market_facts(
        {k: v for k, v in ctx.tape.items() if v.change_pct is not None}, ctx.backdrop
    )
    line = " · ".join(f.display for f in facts.facts[:6])
    return CardPayload(
        kind=c.kind,
        subject=c.subject,
        title=title,
        emoji=emoji,
        when=ctx.now,
        facts_line=line,
        facts=facts,
        critical=c.critical,
    )


def _breaking_card(c: AlertCandidate, ctx: AlertContext) -> CardPayload:
    with news_session() as s:
        cl = queries.cluster_view(s, c.cluster_ids[0])
    assert cl is not None
    primary = pick_primary(cl.items, ctx.cfg.news.source_rank)
    facts = build_market_facts(
        {k: v for k, v in ctx.tape.items() if v.change_pct is not None}, ctx.backdrop
    )
    return CardPayload(
        kind="breaking",
        subject=c.subject,
        title=cl.headline[:120],
        emoji="🌍",
        when=ctx.now,
        headline_line=f"{cl.source_count} sources · {cl.topic_class}",
        facts_line=" · ".join(f.display for f in facts.facts[:4]),
        facts=facts,
        links=links_for(cl, ctx.cfg.news.source_rank),
        image_url=primary.image_url if primary else None,
        preview_url=primary.url if primary else None,
        critical=True,
        cluster_ids=[cl.id],
    )


def build_card(c: AlertCandidate, ctx: AlertContext) -> CardPayload:
    if c.kind == "macro_print":
        return _macro_card(c, ctx)
    if c.kind in ("ticker_move", "earnings"):
        return _ticker_card(c, ctx, kind=c.kind)
    if c.kind == "breaking":
        return _breaking_card(c, ctx)
    return _market_card(c, ctx)


def apply_update(existing: CardPayload, new: CardPayload, now: datetime) -> CardPayload:
    line = f"🔄 Update {now.astimezone(SGT):%H:%M} SGT · {new.title}"
    if new.facts_line:
        line += f" · {new.facts_line}"
    return existing.model_copy(
        update={
            "updates": [*existing.updates, line],
            "cluster_ids": sorted(set(existing.cluster_ids) | set(new.cluster_ids)),
        }
    )


def plan_alert(
    c: AlertCandidate, payload: CardPayload, *, now: datetime, max_edits: int
) -> AlertAction:
    start = naive_utc(now - timedelta(hours=18))
    with news_session() as s:
        posts = list(
            s.scalars(
                select(NewsPostRow)
                .where(NewsPostRow.posted_at >= start)
                .order_by(NewsPostRow.posted_at)
            )
        )
    for post in posts:
        shares = (
            bool(set(post.cluster_ids or []) & set(c.cluster_ids))
            or bool(set(post.payload.get("event_keys") or []) & set(c.event_keys))
            or (post.kind == c.kind and post.subject == c.subject)
        )
        if not shares:
            continue
        existing = CardPayload.model_validate(post.payload)
        if post.edits >= max_edits:
            return AlertAction("reply", payload, post.id)
        return AlertAction("update", apply_update(existing, payload, now), post.id)
    return AlertAction("new", payload)
