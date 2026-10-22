"""Prompts for the news LLM passes. The model may use ONLY the numbered facts (F#) and
headlines (N#); every verdict must cite them. Output is one JSON object per schema."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

from src.common.schemas import DossierFact
from src.news.playbook import PlaybookPrior
from src.news.reaction import Reaction
from src.news.schemas import (
    ClusterView,
    DigestReads,
    DossierDraft,
    Explanation,
    FactSheet,
    ItemView,
    PictureDraft,
    TriageOutput,
)

if TYPE_CHECKING:  # triage.py imports this module; the type is only needed for annotations
    from src.news.triage import TriageCandidate

EXPLANATION_SCHEMA = Explanation.model_json_schema()
TRIAGE_SCHEMA = TriageOutput.model_json_schema()
PICTURE_SCHEMA = PictureDraft.model_json_schema()
DIGEST_SCHEMA = DigestReads.model_json_schema()
DOSSIER_SCHEMA = DossierDraft.model_json_schema()

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


def picture_block(picture_text: str | None) -> str | None:
    """The market picture as context for a prompt, or None when there is none yet. It frames the
    story; it is not a source: the card's numbers must still come from its own facts."""
    if not picture_text:
        return None
    return (
        f"{picture_text}\n"
        "(Context for framing only: do not quote its numbers, do not cite it. "
        "Numbers you write must come from the facts and headlines.)"
    )


def writer_prompt(
    kind: str,
    *,
    headlines: str,
    facts: FactSheet,
    prior: PlaybookPrior | None,
    reaction: Reaction | None,
    picture_text: str | None = None,
) -> str:
    return "\n\n".join(
        x
        for x in (
            RULES,
            picture_block(picture_text),
            f"EVENT TYPE: {kind}",
            "=== FACTS ===\n" + facts.render(),
            _prior_block(prior, reaction),
            "=== HEADLINES ===\n" + (headlines or "(none)"),
            "=== JSON SCHEMA ===\n" + json.dumps(EXPLANATION_SCHEMA),
        )
        if x
    )


def triage_prompt(cands: list[TriageCandidate], picture_text: str | None) -> str:
    """One batched triage call: the ranked clusters, each to be put in a pile. The model is
    told nothing about floors: Python applies them to whatever it answers."""
    lines = []
    for c in cands:
        cl = c.cluster
        tags = [f"{cl.category}/{cl.topic_class}", f"{cl.source_count} sources"]
        if cl.tickers:
            tags.append(",".join(cl.tickers[:4]))
        lines.append(f"C{cl.id} [{', '.join(tags)}] {cl.headline}")
    return "\n\n".join(
        x
        for x in (
            RULES.replace(
                'Cite the ids that support your verdict in "evidence". No ids, no verdict: use "unclear".',
                "",
            ),
            "TASK: sort each cluster into a pile. 1 = shapes the market picture (market-wide, "
            "persisting); 2 = worth telling an options seller but does not change the picture; "
            "3 = noise. Give a one-line reason each. Cite nothing else.",
            picture_text,
            "=== CLUSTERS ===\n" + "\n".join(lines),
            "=== JSON SCHEMA ===\n" + json.dumps(TRIAGE_SCHEMA),
        )
        if x
    )


def digest_prompt(
    threads: list[ClusterView], backdrop: FactSheet, picture_text: str | None = None
) -> str:
    items = [it for c in threads for it in c.items[:2]]
    heads, _ = number_headlines(items)
    ids = "\n".join(f"cluster_id {c.id}: {c.headline}" for c in threads)
    return "\n\n".join(
        x
        for x in (
            RULES,
            picture_block(picture_text),
            "TASK: for EACH cluster below write a one-line read (what it means for US stocks / rates) and a verdict.",
            "=== FACTS ===\n" + backdrop.render(),
            "=== CLUSTERS ===\n" + ids,
            "=== HEADLINES ===\n" + heads,
            "=== JSON SCHEMA ===\n" + json.dumps(DIGEST_SCHEMA),
        )
        if x
    )


PICTURE_RULES = """You are a markets news analyst writing for an options premium seller (cash-secured puts, covered calls).
Rules:
- Use ONLY the facts (F#) and story clusters (C#) below. Every number you write must appear in the facts.
- Cite the ids that support each story in "evidence" (C# and F#). A story that cites no valid id is dropped.
- Be terse and concrete. No trading advice, no hedging filler, no em dashes. Never tell the reader to buy, sell, reduce, add, hedge or close anything.
- F#/C# ids belong ONLY in "evidence", never in prose. Never comment on which facts or clusters were supplied: write about the market, not the inputs.
- Seasonality is a weak signal: never use it as a reason.
- Reply with ONE JSON object matching the schema. Nothing outside the JSON."""


def picture_prompt(
    facts: FactSheet,
    stories: list[tuple[int, str, date]],
    clusters: list[ClusterView],
    events: list[str],
    *,
    piles: dict[int, int] | None = None,
    max_stories: int = 5,
) -> str:
    """The market-picture call: name the stories moving the market against the numbered facts.

    Previous stories are listed by id, title and start date only, **never with their earlier
    prose** (the model must not harden its own words into fact). *piles* marks each cluster's
    triage pile so the model knows which ones may start a new story (pile 1 only).
    """
    story_lines = [f"S{sid} {title} (since {started:%b %d})" for sid, title, started in stories]
    cluster_lines = []
    for cl in clusters:
        tags = [f"{cl.category}/{cl.topic_class}", f"{cl.source_count} sources"]
        if cl.tickers:
            tags.append(",".join(cl.tickers[:4]))
        pile = f"pile {piles[cl.id]}; " if piles and cl.id in piles else ""
        cluster_lines.append(f"C{cl.id} [{pile}{', '.join(tags)}] {cl.headline}")
    return "\n\n".join(
        x
        for x in (
            PICTURE_RULES,
            f"TASK: name the stories moving the market for an options premium seller (at most "
            f"{max_stories}). Continue a listed story by its id (story_id) or start a new one "
            "(story_id null). Start a new story only from a pile 1 cluster. Each description is one "
            "or two sentences that tie the story to the numbered facts; every number must appear "
            "in the facts. Cite clusters (C#) and facts (F#) in evidence. Seasonality is a weak "
            "signal: never use it as a reason. Leave out a listed story you cannot support.",
            "=== FACTS ===\n" + facts.render(),
            "=== PREVIOUS STORIES (titles only) ===\n" + ("\n".join(story_lines) or "(none)"),
            "=== CLUSTERS ===\n" + ("\n".join(cluster_lines) or "(none)"),
            ("=== UPCOMING EVENTS ===\n" + "\n".join(events)) if events else None,
            "=== JSON SCHEMA ===\n" + json.dumps(PICTURE_SCHEMA),
        )
        if x
    )


DOSSIER_RULES = """You are a markets news analyst writing short notes on individual stocks and ETFs for an options premium seller (cash-secured puts, covered calls).
Rules:
- Use ONLY the facts (<SYM>:F#) and the story clusters (C#) listed under each name. Every number you write must appear in that name's facts; write no other number or date in the profile or the story.
- Cite the clusters that support a story in "story_evidence", and the one that states an event's date in that event's "evidence". A story that cites no listed cluster is dropped.
- Be terse and concrete. No trading advice, no hedging filler, no em dashes. Never tell the reader to buy, sell, reduce, add, hedge or close anything.
- Cluster and fact ids belong ONLY in the evidence fields, never in prose. Never comment on which facts or clusters were supplied: write about the company, not the inputs.
- Reply with ONE JSON object matching the schema. Nothing outside the JSON."""

_DOSSIER_ITEMS = 2  # items shown under a cluster
_DOSSIER_SUMMARY_CHARS = 200
_EPOCH = datetime.min.replace(tzinfo=UTC)


@dataclass
class DossierPromptEntry:
    """One name's slice of a dossier prompt: its numbers, its recent clusters and whether the
    profile is wanted this time. Nothing the model wrote before is ever in here."""

    symbol: str
    kind: str
    facts: list[DossierFact]
    clusters: list[ClusterView]
    want_profile: bool


def dossier_cluster_lines(cl: ClusterView, symbol: str) -> list[str]:
    """The text the model is shown for one cluster: its headline and up to two items, preferring
    the items that name *symbol*, each with its summary cut at 200 characters.

    This is also the text an event's date is checked against (``dossier.verify_event_date``): the
    date has to be written in what the model actually saw."""
    about = sorted(
        (it for it in cl.items if symbol in it.tickers),
        key=lambda it: it.published_at or _EPOCH,
        reverse=True,
    )
    lines = [f"C{cl.id} {cl.headline}"]
    for it in (about or cl.items)[:_DOSSIER_ITEMS]:
        summary = f" — {it.summary[:_DOSSIER_SUMMARY_CHARS]}" if it.summary else ""
        lines.append(f"  - {it.title}{summary}")
    return lines


def dossier_prompt(entries: list[DossierPromptEntry], picture_text: str | None) -> str:
    """One batched call: notes on several names, each against its own numbered facts and clusters.

    The previous profile, story and events are **never** included (the model must not harden its
    own earlier words into fact); only the current numbers and the current news are."""
    blocks = []
    for e in entries:
        blocks.append(
            "\n".join(
                [
                    f"=== {e.symbol} ({e.kind.replace('_', ' ')}) ===",
                    f"PROFILE requested: {'yes' if e.want_profile else 'no'}",
                    "FACTS",
                    *(f"{f.id} {f.label}: {f.display}" for f in e.facts),
                    "CLUSTERS",
                    *(
                        [line for cl in e.clusters for line in dossier_cluster_lines(cl, e.symbol)]
                        or ["(none)"]
                    ),
                ]
            )
        )
    return "\n\n".join(
        x
        for x in (
            DOSSIER_RULES,
            picture_block(picture_text),
            'TASK: for EACH name below write its notes. PROFILE (only where "PROFILE requested: '
            'yes"): what the company or fund is and what moves its price, at most three sentences '
            "and 400 characters, with no numbers. STORY: what is happening to the name now, from "
            "its listed clusters only, at most 280 characters; cite those clusters in "
            "story_evidence (C# ids); leave it empty when none of them is about the name. EVENTS: "
            "dated upcoming catalysts other than earnings that a listed cluster states with a "
            "calendar date, at most three; give the date as YYYY-MM-DD and cite that cluster in "
            "evidence; never infer or estimate a date. Use each name's symbol exactly as headed.",
            *blocks,
            "=== JSON SCHEMA ===\n" + json.dumps(DOSSIER_SCHEMA),
        )
        if x
    )
