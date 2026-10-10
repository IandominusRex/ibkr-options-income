"""Stage 2 of every alert (spec §7.2): once the reaction window has closed, fill 📈 and 🧠
and EDIT the same Telegram message. Edits made here do not count toward news.alerts.max_edits."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timedelta

from sqlalchemy import select

from src.common.config import Config
from src.news.alerts import items_about
from src.news.explain import explain_card
from src.news.facts import build_macro_facts
from src.news.playbook import load_playbook, prior_for
from src.news.posting import update_post
from src.news.publish import Publisher
from src.news.reaction import Reaction, measure_reaction, waited_too_long
from src.news.schemas import CardPayload, EconEventView, GridRow, ItemView
from src.news.store import queries
from src.news.store.models import EconEventRow, NewsPostRow
from src.news.store.queries import naive_utc
from src.news.store.session import news_session
from src.news.tagging import is_noise

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


_TICKER_KINDS = ("ticker_move", "earnings", "brief")
_MAX_HEADLINES = 8


def _headlines(p: CardPayload, noise_terms: list[str]) -> list[ItemView]:
    """The N# headlines the writer may cite. Law-firm solicitations never go in. A ticker card
    sends only items that name its symbol, newest first: on 2026-10-09 an ASTS card sent an
    Arm story and two lawsuit ads ahead of the one headline that explained the drop."""
    ticker = p.kind in _TICKER_KINDS and p.subject
    out: list[ItemView] = []
    with news_session() as s:
        for cid in p.cluster_ids[: 5 if ticker else 3]:
            cv = queries.cluster_view(s, cid, max_items=6 if ticker else 3)
            if cv:
                out += [it for it in cv.items if not is_noise(it.title, noise_terms)]
    if ticker:
        about = items_about(out, str(p.subject))
        if about:
            out = about
    seen: set[str] = set()
    uniq = []
    for it in out:
        if it.title not in seen:
            seen.add(it.title)
            uniq.append(it)
    return uniq[:_MAX_HEADLINES]


def _econ_views(keys: list[str]) -> list[EconEventView]:
    with news_session() as s:
        return [
            queries.econ_view(r) for r in (s.get(EconEventRow, k) for k in keys) if r is not None
        ]


def _concurrent_fields(post_id: int) -> dict[str, object]:
    """Fields another loop may have changed while the LLM call ran: a second trigger on the same
    story appends 🔄 updates and cluster ids (alerts.apply_update). Re-read them so stage 2's
    write-back never drops an update that landed mid-call (Review Focus 4)."""
    with news_session() as s:
        row = s.get(NewsPostRow, post_id)
        if row is None:
            return {}
        cur = CardPayload.model_validate(row.payload)
    return {"updates": cur.updates, "cluster_ids": cur.cluster_ids}


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
        evs = await asyncio.to_thread(_econ_views, payload.event_keys)
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
    headlines = await asyncio.to_thread(_headlines, payload, cfg.news.tagging.noise_terms)
    outcome = await asyncio.to_thread(
        explain_card,
        payload.kind,
        headlines=headlines,
        facts=facts,
        prior=prior,
        reaction=reaction,
        now=now,
        fallback_what=fallback_what(payload),
    )
    concurrent = await asyncio.to_thread(_concurrent_fields, post_id)
    payload = payload.model_copy(
        update={
            "explanation": outcome.explanation,
            "trimmed": outcome.trimmed,
            "llm_note": outcome.note,
            **concurrent,
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
