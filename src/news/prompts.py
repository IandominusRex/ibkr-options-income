"""Prompts for the news LLM passes. The model may use ONLY the numbered facts (F#) and
headlines (N#); every verdict must cite them. Output is one JSON object per schema."""

from __future__ import annotations

import json

from src.news.playbook import PlaybookPrior
from src.news.reaction import Reaction
from src.news.schemas import (
    ClusterView,
    DigestReads,
    EditorOutput,
    Explanation,
    FactSheet,
    ItemView,
)

EXPLANATION_SCHEMA = Explanation.model_json_schema()
EDITOR_SCHEMA = EditorOutput.model_json_schema()
DIGEST_SCHEMA = DigestReads.model_json_schema()

RULES = """You are a markets news analyst writing for an options premium seller (cash-secured puts, covered calls).
Rules:
- Use ONLY the facts (F#) and headlines (N#) below. Every number you write must appear in them.
- Cite the ids that support your verdict in "evidence". No ids, no verdict: use "unclear".
- Call a move an overreaction only when the facts or FLAG lines support it (e.g. large_move_no_hard_news,
  rumor_driven, oversold_at_support, earnings_outsized). Say "further downside" only when facts support it.
- If 📘 TEXTBOOK and 📈 ACTUAL disagree, the "read" field must explain the gap.
- Be terse and concrete. No trading advice, no hedging filler, no em dashes.
- F#/N# ids belong ONLY in "evidence", never in prose. Never comment on which facts or headlines
  were or were not supplied: write about the market, not the inputs.
- book_impact / setup_impact say what the move means for the positions or premium; never tell
  the reader to buy, sell, reduce, add, hedge or close anything.
- Reply with ONE JSON object matching the schema. Nothing outside the JSON."""


def number_headlines(items: list[ItemView], start: int = 1) -> tuple[str, dict[str, ItemView]]:
    index: dict[str, ItemView] = {}
    lines = []
    for i, it in enumerate(items, start):
        nid = f"N{i}"
        index[nid] = it
        # The date lets the model tell yesterday's "why is X falling" from today's catalyst.
        when = f"{it.published_at:%b %d}" if it.published_at else ""
        tag = ", ".join(x for x in (it.source, when) if x)
        src = f"[{tag}] " if tag else ""
        summ = f" — {it.summary[:200]}" if it.summary else ""
        lines.append(f"{nid} {src}{it.title}{summ}")
    return "\n".join(lines), index


def _prior_block(prior: PlaybookPrior | None, reaction: Reaction | None) -> str:
    if prior is None and reaction is None:
        return ""
    lines = ["=== 📘 TEXTBOOK vs 📈 ACTUAL ==="]
    for asset in ("stocks", "bonds", "dollar", "gold", "oil", "vol"):
        tb = prior.arrows.get(asset) if prior else None
        act = reaction.display(asset) if reaction else None
        if tb or act:
            lines.append(f"{asset}: textbook {tb or '-'} | actual {act or 'pending'}")
    if prior:
        lines.append(f"textbook rationale: {prior.rationale}")
    return "\n".join(lines)


def writer_prompt(
    kind: str,
    *,
    headlines: str,
    facts: FactSheet,
    prior: PlaybookPrior | None,
    reaction: Reaction | None,
) -> str:
    return "\n\n".join(
        x
        for x in (
            RULES,
            f"EVENT TYPE: {kind}",
            "=== FACTS ===\n" + facts.render(),
            _prior_block(prior, reaction),
            "=== HEADLINES ===\n" + (headlines or "(none)"),
            "=== JSON SCHEMA ===\n" + json.dumps(EXPLANATION_SCHEMA),
        )
        if x
    )


def editor_prompt(clusters: list[ClusterView], backdrop: FactSheet) -> str:
    lines = [
        f"C{c.id} [{c.category}/{c.topic_class}, {c.source_count} sources] {c.headline}"
        for c in clusters
    ]
    return "\n\n".join(
        [
            RULES.replace(
                'Cite the ids that support your verdict in "evidence". No ids, no verdict: use "unclear".',
                "",
            ),
            "TASK: label the market regime, group these stories into at most 6 threads ranked by market importance "
            "for a US options seller, and list cluster ids that are noise.",
            "=== BACKDROP ===\n" + backdrop.render(),
            "=== CLUSTERS ===\n" + "\n".join(lines),
            "=== JSON SCHEMA ===\n" + json.dumps(EDITOR_SCHEMA),
        ]
    )


def digest_prompt(threads: list[ClusterView], backdrop: FactSheet) -> str:
    items = [it for c in threads for it in c.items[:2]]
    heads, _ = number_headlines(items)
    ids = "\n".join(f"cluster_id {c.id}: {c.headline}" for c in threads)
    return "\n\n".join(
        [
            RULES,
            "TASK: for EACH cluster below write a one-line read (what it means for US stocks / rates) and a verdict.",
            "=== FACTS ===\n" + backdrop.render(),
            "=== CLUSTERS ===\n" + ids,
            "=== HEADLINES ===\n" + heads,
            "=== JSON SCHEMA ===\n" + json.dumps(DIGEST_SCHEMA),
        ]
    )
