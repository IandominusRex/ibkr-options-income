"""Stage 2 of every alert (spec §7.2): once the reaction window has closed, fill 📈 and 🧠
and EDIT the same Telegram message. Edits made here do not count toward news.alerts.max_edits."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timedelta

from sqlalchemy import select

from src.common.config import Config
from src.news.explain import explain_card
from src.news.facts import build_macro_facts
from src.news.playbook import load_playbook, prior_for
from src.news.posting import update_post
from src.news.publish import Publisher
from src.news.reaction import Reaction, measure_reaction, waited_too_long
from src.news.schemas import CardPayload, GridRow, ItemView
from src.news.store import queries
from src.news.store.models import EconEventRow, NewsPostRow
from src.news.store.queries import naive_utc
from src.news.store.session import news_session

_ALERT_KINDS = (
    "macro_print",
    "earnings",
    "market_move",
    "vix_spike",
    "ticker_move",
    "breaking",
)  # briefs explain themselves (Task 28)


def pending_posts(now: datetime, *, horizon_h: int = 3) -> list[tuple[int, CardPayload]]:
    with news_session() as s:
        rows = s.scalars(
            select(NewsPostRow)
            .where(
                NewsPostRow.stage == "facts",
                NewsPostRow.kind.in_(_ALERT_KINDS),
                NewsPostRow.posted_at >= naive_utc(now - timedelta(hours=horizon_h)),
            )
            .order_by(NewsPostRow.posted_at)
        )
        return [(r.id, CardPayload.model_validate(r.payload)) for r in rows]


def fallback_what(p: CardPayload) -> str | None:
    if p.headline_line:
        return p.headline_line[:180]
    if p.facts and p.facts.facts:
        return "; ".join(f.display for f in p.facts.facts[:2])[:180]
    return None


def _headlines(p: CardPayload) -> list[ItemView]:
    out: list[ItemView] = []
    with news_session() as s:
        for cid in p.cluster_ids[:3]:
            cv = queries.cluster_view(s, cid, max_items=3)
            if cv:
                out += cv.items
    return out


async def complete_post(
    post_id: int,
    payload: CardPayload,
    *,
    now: datetime,
    cfg: Config,
    publisher: Publisher | None,
    measure: Callable[..., Reaction] = lambda rel, cfg: measure_reaction(rel, cfg=cfg),
) -> bool:
    prior = reaction = None
    update: dict[str, object] = {}
    if payload.kind == "macro_print":
        reaction = await asyncio.to_thread(measure, payload.when, cfg.news.reaction)
        if not reaction.complete and not waited_too_long(payload.when, now, cfg.news.reaction):
            return False
        with news_session() as s:
            evs = [
                queries.econ_view(r)
                for r in (s.get(EconEventRow, k) for k in payload.event_keys)
                if r is not None
            ]
        pb = load_playbook()
        entry = pb.match(evs[0].title) if evs else None
        prior = prior_for(entry, evs[0].surprise_dir) if entry and evs else None  # type: ignore[arg-type]
        update["grid"] = [
            GridRow(asset=g.asset, textbook=g.textbook, actual=reaction.display(g.asset))
            for g in payload.grid
        ]
        update["grid_note"] = None if reaction.complete else "📈 reaction pending (data delayed)"
        update["facts"] = build_macro_facts(evs, reaction=reaction, backdrop=None)
        payload = payload.model_copy(update=update)
        update = {}
    facts = payload.facts
    if facts is None:
        from src.news.schemas import FactSheet

        facts = FactSheet()
    outcome = await asyncio.to_thread(
        explain_card,
        payload.kind,
        headlines=_headlines(payload),
        facts=facts,
        prior=prior,
        reaction=reaction,
        now=now,
        fallback_what=fallback_what(payload),
    )
    payload = payload.model_copy(
        update={
            "explanation": outcome.explanation,
            "trimmed": outcome.trimmed,
            "llm_note": outcome.note,
        }
    )
    await update_post(
        post_id,
        payload,
        publisher=publisher,
        stage=outcome.stage,
        llm_backend=outcome.backend,
        count_edit=False,
    )
    return True
