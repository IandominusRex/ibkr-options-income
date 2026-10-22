"""Writer and digest-read passes with one validation retry and the deterministic fallback
(spec §6.5–6.6). The editor pass is gone: the triage (``src/news/triage.py``) orders the digest."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ValidationError

from src.claude.parser import _parse_dict_payload
from src.common.config import get_config
from src.common.picture_text import render_picture
from src.news.grounding import extract_numbers, ground, ground_digest
from src.news.llm import Purpose, call_llm, cap_reached
from src.news.playbook import PlaybookPrior
from src.news.prompts import (
    DIGEST_SCHEMA,
    EXPLANATION_SCHEMA,
    digest_prompt,
    number_headlines,
    writer_prompt,
)
from src.news.reaction import Reaction
from src.news.schemas import (
    ClusterView,
    DigestRead,
    DigestReads,
    Explanation,
    FactSheet,
    ItemView,
)
from src.news.store import queries
from src.news.store.session import news_session

log = logging.getLogger(__name__)


@dataclass
class ExplainOutcome:
    explanation: Explanation | None
    backend: str | None
    trimmed: bool
    stage: Literal["explained", "fallback"]
    note: str | None


def validated_call[M: BaseModel](
    model: type[M],
    prompt: str,
    *,
    schema: dict,
    prefix: str,
    now: datetime,
    purpose: Purpose = "general",
) -> tuple[M | None, str | None]:
    """One model call parsed into *model*, with one retry that shows the validation error. Both
    attempts count against *purpose*'s budget (triage and picture builds use ``picture``)."""
    res = call_llm(prompt, schema=schema, prefix=prefix, now=now, purpose=purpose)
    for attempt in (0, 1):
        if res is None:
            return None, None
        payload = _parse_dict_payload(res.text, prefix)
        try:
            return model.model_validate(payload or {}), res.backend
        except ValidationError as exc:
            if attempt == 1:
                log.info("%s: invalid output after retry: %s", prefix, exc)
                return None, res.backend
            res = call_llm(
                f"{prompt}\n\nYour previous reply failed validation. Validation error:\n{exc}\nReply again with valid JSON only.",
                schema=schema,
                prefix=prefix,
                now=now,
                purpose=purpose,
            )
    return None, None


def validated_items_call[I: BaseModel](
    item_model: type[I],
    prompt: str,
    *,
    key: str,
    schema: dict,
    prefix: str,
    now: datetime,
    purpose: Purpose = "general",
) -> tuple[list[I], list[tuple[object, str]]] | None:
    """One model call whose answer is ``{key: [item, ...]}``, validated item by item.

    Each element is parsed into *item_model* on its own: those that fail their limits or their
    schema come back in the second list as ``(raw element, error)`` and never cost the others.
    The call is counted once. Only a reply that is not usable at all (no JSON object, *key*
    missing, or *key* not a list) is retried once with the problem shown, like `validated_call`;
    a second failure, no answer or a spent budget returns None. A reply with no *key* is **not**
    an empty list (``{}``, ``{"error": "..."}`` and a wrong key are not answers): only an explicit
    ``[]`` says "nothing to return".
    """
    res = call_llm(prompt, schema=schema, prefix=prefix, now=now, purpose=purpose)
    for attempt in (0, 1):
        if res is None:
            return None
        payload = _parse_dict_payload(res.text, prefix)
        raw = payload.get(key) if payload is not None else None
        if isinstance(raw, list):
            accepted: list[I] = []
            rejected: list[tuple[object, str]] = []
            for element in raw:
                try:
                    accepted.append(item_model.model_validate(element))
                except ValidationError as exc:
                    rejected.append((element, str(exc)))
            return accepted, rejected
        if payload is None:
            problem = "the reply was not a JSON object"
        elif key not in payload:
            problem = f'"{key}" is missing'
        else:
            problem = f'"{key}" must be a list'
        if attempt == 1:
            log.info("%s: unusable output after retry: %s", prefix, problem)
            return None
        res = call_llm(
            f"{prompt}\n\nYour previous reply was not usable: {problem}. "
            "Reply again with valid JSON only.",
            schema=schema,
            prefix=prefix,
            now=now,
            purpose=purpose,
        )
    return None


def latest_picture_text(now: datetime) -> str | None:
    """The stored market picture as prompt text, or None before the first one is built (then the
    prompt simply has no picture block). Stale pictures say so: ``render_picture`` prefixes them."""
    try:
        with news_session() as s:
            picture = queries.latest_picture(s)
    except Exception:
        log.warning("news: could not read the market picture", exc_info=True)
        return None
    if picture is None:
        return None
    return render_picture(
        picture, now=now, staleness_hours=get_config().news.picture.staleness_hours
    )


def _note(now: datetime) -> str:
    return "🧠 off (daily cap)" if cap_reached(now) else "🧠 unavailable"


def explain_card(
    kind: str,
    *,
    headlines: list[ItemView],
    facts: FactSheet,
    prior: PlaybookPrior | None,
    reaction: Reaction | None,
    now: datetime,
    fallback_what: str | None = None,
    picture_text: str | None = None,
) -> ExplainOutcome:
    block, index = number_headlines(headlines)
    prompt = writer_prompt(
        kind,
        headlines=block,
        facts=facts,
        prior=prior,
        reaction=reaction,
        picture_text=picture_text,
    )
    expl, backend = validated_call(
        Explanation, prompt, schema=EXPLANATION_SCHEMA, prefix=f"news:{kind}", now=now
    )
    if expl is None:
        return ExplainOutcome(None, backend, False, "fallback", _note(now))
    news_numbers = [
        v for it in headlines for v, _d, _m in extract_numbers(f"{it.title} {it.summary or ''}")
    ]
    grounded_e, trimmed = ground(
        expl,
        facts=facts,
        news_numbers=news_numbers,
        news_ids=set(index),
        rel_tol=get_config().news.grounding.rel_tol,
        fallback_what=fallback_what,
    )
    if not grounded_e.evidence:
        # Nothing cited: the read is unanchored (2026-10-09: a claims beat explained as a "soft
        # jobs data risk-off rally" with evidence []). Ship the facts card, not the prose.
        log.info("news:%s: explanation cites no valid evidence — withheld", kind)
        return ExplainOutcome(None, backend, False, "fallback", "🧠 withheld (uncited)")
    return ExplainOutcome(grounded_e, backend, trimmed, "explained", None)


def digest_reads(
    threads: list[ClusterView],
    backdrop: FactSheet,
    *,
    now: datetime,
    picture_text: str | None = None,
) -> dict[int, DigestRead]:
    if not threads:
        return {}
    out, _ = validated_call(
        DigestReads,
        digest_prompt(threads, backdrop, picture_text),
        schema=DIGEST_SCHEMA,
        prefix="news:digest",
        now=now,
    )
    if out is None:
        return {}
    items = [it for c in threads for it in c.items[:2]]
    _, index = number_headlines(items)
    refs = backdrop.numbers() + [v for it in items for v, _d, _m in extract_numbers(it.title)]
    grounded_r = ground_digest(
        out,
        refs=refs,
        valid_ids=set(index) | backdrop.ids(),
        rel_tol=get_config().news.grounding.rel_tol,
    )
    known = {c.id for c in threads}
    return {r.cluster_id: r for r in grounded_r.items if r.cluster_id in known and r.read}
