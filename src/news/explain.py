"""Editor and writer passes with one validation retry and the deterministic fallback (spec §6.5–6.6)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ValidationError

from src.claude.parser import _parse_dict_payload
from src.common.config import get_config
from src.news.grounding import extract_numbers, ground, ground_digest
from src.news.llm import call_llm, cap_reached
from src.news.playbook import PlaybookPrior
from src.news.prompts import (
    DIGEST_SCHEMA,
    EDITOR_SCHEMA,
    EXPLANATION_SCHEMA,
    digest_prompt,
    editor_prompt,
    number_headlines,
    writer_prompt,
)
from src.news.reaction import Reaction
from src.news.schemas import (
    ClusterView,
    DigestRead,
    DigestReads,
    EditorOutput,
    Explanation,
    FactSheet,
    ItemView,
)

log = logging.getLogger(__name__)


@dataclass
class ExplainOutcome:
    explanation: Explanation | None
    backend: str | None
    trimmed: bool
    stage: Literal["explained", "fallback"]
    note: str | None


def _validated[M: BaseModel](
    model: type[M], prompt: str, *, schema: dict, prefix: str, now: datetime
) -> tuple[M | None, str | None]:
    res = call_llm(prompt, schema=schema, prefix=prefix, now=now)
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
            )
    return None, None


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
) -> ExplainOutcome:
    block, index = number_headlines(headlines)
    prompt = writer_prompt(kind, headlines=block, facts=facts, prior=prior, reaction=reaction)
    expl, backend = _validated(
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
    return ExplainOutcome(grounded_e, backend, trimmed, "explained", None)


def edit_digest(
    clusters: list[ClusterView], backdrop: FactSheet, *, now: datetime
) -> EditorOutput | None:
    if not clusters:
        return None
    out, _ = _validated(
        EditorOutput,
        editor_prompt(clusters, backdrop),
        schema=EDITOR_SCHEMA,
        prefix="news:editor",
        now=now,
    )
    if out is None:
        return None
    known = {c.id for c in clusters}
    threads = [
        t.model_copy(update={"cluster_ids": [i for i in t.cluster_ids if i in known]})
        for t in out.threads
    ]
    return out.model_copy(update={"threads": [t for t in threads if t.cluster_ids]})


def digest_reads(
    threads: list[ClusterView], backdrop: FactSheet, *, now: datetime
) -> dict[int, DigestRead]:
    if not threads:
        return {}
    out, _ = _validated(
        DigestReads,
        digest_prompt(threads, backdrop),
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
