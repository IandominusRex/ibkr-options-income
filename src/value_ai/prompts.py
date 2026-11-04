"""The versioned prompts of the value book's analyst (spec §8.1, §8.5) and the one output schema
they share with the interactive skill (``.claude/skills/value/reference/output-schema.json`` is
generated from :data:`OUTPUT_SCHEMA`, spec §8.6, and a test keeps the two equal).

Three call kinds, one shape: a ``standard`` read writes the verdict per list, the drivers, the
prose and the kill-trigger picks; a ``review`` (a held name's re-evaluation, spec §7.1 step 3)
adds the review state; a ``filing`` read proposes grounded facts from the sliced sections only.
Claude never returns a fair value, a price, a strike or a size: the schema has no field for one.
"""

from __future__ import annotations

import json
from typing import Any

from src.common.value_ai_types import FACT_KINDS, FACT_UNITS, KILL_KINDS, AnalystRequest
from src.value_ai.context import AnalystContext

PROMPT_VERSION = "value-v1"

_DRIVERS = {
    "type": "object",
    "properties": {
        "growth": {"type": ["number", "null"]},
        "terminal": {"type": ["number", "null"]},
        "discount": {"type": ["number", "null"]},
        "margin": {"type": ["number", "null"]},
        "rote": {"type": ["number", "null"]},
    },
}
OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "lists": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "list": {"type": "string", "enum": ["deep_value", "quality_growth"]},
                    "verdict": {"type": "string", "enum": ["READY", "WATCH", "WAIT", "NO"]},
                    "why": {"type": "string"},
                    "drivers": _DRIVERS,
                },
                "required": ["list", "verdict", "why", "drivers"],
            },
        },
        "profile": {"type": "string"},
        "why_cheap": {"type": "string"},
        "thesis": {"type": "string"},
        "bear_case": {"type": "string"},
        "kill_triggers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": list(KILL_KINDS)},
                    "threshold": {"type": ["number", "null"]},
                },
                "required": ["kind"],
            },
        },
        "review_state": {
            "type": ["string", "null"],
            "enum": ["INTACT", "WEAKENED", "BROKEN", None],
        },
        "review_why": {"type": "string"},
        "facts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": list(FACT_KINDS)},
                    "value": {"type": ["number", "null"]},
                    "unit": {"type": "string"},
                    "accn": {"type": "string"},
                    "quote": {"type": "string"},
                    "item": {"type": ["string", "null"]},
                },
                "required": ["kind", "accn", "quote"],
            },
        },
    },
    "required": ["lists"],
}

_RULES = """You are the analyst of a long-only value book. You judge healthy companies only:
Python has already checked health, earnings quality and dilution, and those checks are final.
Use only the numbers and text below. Do not invent figures. Every number you write in prose must
appear below. You never set a price, a fair value, a strike or a size: you choose assumptions
inside the bounds given, and Python does all the arithmetic and caps the result.
Return ONE JSON object and nothing else."""

_VERDICTS = """Verdicts, per list the name is on:
- READY: buy now (Python still applies the margin of safety and timing on top).
- WATCH: the right company; wait for the price to settle.
- WAIT: the right company at the wrong price.
- NO: not a company to own on this list."""

_DRIVER_HELP = """Drivers (fractions: 0.08 means 8%), one set per list, each inside its bound:
- growth: FCF per share growth for years 1-5 (years 6-10 fade to terminal);
- terminal: terminal growth; discount: the discount rate;
- margin: the normalised free-cash-flow margin on revenue;
- rote (banks and insurers, instead of growth and margin): sustainable return on tangible equity.
A driver outside its bound is clamped and the clamp is recorded against you."""


def _bounds(req: AnalystRequest) -> str:
    lines = []
    for b in req.bounds:
        parts = [f"terminal {b.terminal.lo:.3f}..{b.terminal.hi:.3f}"]
        parts.append(f"discount {b.discount.lo:.3f}..{b.discount.hi:.3f}")
        if b.growth is not None:
            parts.append(f"growth {b.growth.lo:.3f}..{b.growth.hi:.3f}")
        if b.margin is not None:
            parts.append(f"margin {b.margin.lo:.3f}..{b.margin.hi:.3f}")
        if b.rote is not None:
            parts.append(f"rote {b.rote.lo:.3f}..{b.rote.hi:.3f}")
        lines.append(f"- {b.list_name} ({b.method}): " + ", ".join(parts))
    return "\n".join(lines) or "(none: give a verdict only)"


def _menu(req: AnalystRequest) -> str:
    lines = []
    for kind, bound in req.kill_menu.items():
        if bound is None:
            lines.append(f"- {kind} (no threshold: fires on a grounded filing fact)")
        else:
            lines.append(f"- {kind}: threshold in {bound.lo:g}..{bound.hi:g}")
    return "\n".join(lines)


def _context(ctx: AnalystContext) -> str:
    parts = [ctx.dossier or "(no dossier for this name)"]
    parts.append("Recent stories (pile 1-2):")
    parts += [f"- {h}" for h in ctx.headlines] or ["- (none)"]
    parts.append("Earnings dates:")
    parts += [f"- {e}" for e in ctx.earnings] or ["- (none known)"]
    if ctx.unavailable:
        parts.append("Unavailable: " + ", ".join(ctx.unavailable))
    return "\n".join(parts)


def _shape(req: AnalystRequest) -> dict[str, Any]:
    lists = [
        {
            "list": name,
            "verdict": "READY|WATCH|WAIT|NO",
            "why": "one line",
            "drivers": {"growth": 0.0, "terminal": 0.0, "discount": 0.0, "margin": 0.0},
        }
        for name in req.lists
    ]
    shape: dict[str, Any] = {
        "lists": lists,
        "profile": "what the business is and what moves it, two sentences",
        "why_cheap": "one paragraph citing the numbers above",
        "thesis": "what has to be true for the price to reach fair value",
        "bear_case": "the strongest case against, in a short seller's voice",
        "kill_triggers": [{"kind": "one of the menu", "threshold": 0.0}],
    }
    if req.kind == "review":
        shape["review_state"] = "INTACT|WEAKENED|BROKEN"
        shape["review_why"] = "one line"
    return shape


def build_prompt(req: AnalystRequest, ctx: AnalystContext) -> str:
    """The prompt for one read. A filing read asks for facts only."""
    if req.kind == "filing":
        sections = "\n\n".join(
            f"--- {s.form} {s.accn} · {s.section} ---\n{s.text}" for s in req.sections
        )
        return "\n\n".join(
            [
                _RULES,
                "Task: extract facts from the filing sections below. Each fact needs the "
                "accession number and a VERBATIM quote (copied exactly, 300 characters at most) "
                "that contains its number. Python checks every quote against the filing and "
                "drops any that does not match. Kinds: " + ", ".join(FACT_KINDS) + ". "
                "Use guidance_cut or customer_loss (value null) only when the text says so "
                "plainly. Give lists as [].",
                f"=== {req.symbol}: SCORECARD ===\n{req.card_text}",
                f"=== FILING SECTIONS ===\n{sections or '(none)'}",
                'Reply shape: {"lists": [], "facts": [{"kind": "...", "value": 0.0, "unit": '
                f'"{"|".join(FACT_UNITS)}", "accn": "...", "quote": "...", "item": null}}]}}',
            ]
        )
    blocks = [
        _RULES,
        _VERDICTS,
        _DRIVER_HELP,
        f"=== {req.symbol}: SCORECARD (Python's numbers) ===\n{req.card_text}",
        f"=== DRIVER BOUNDS ===\n{_bounds(req)}",
        f"=== KILL-TRIGGER MENU (pick up to {req.max_kill_triggers}) ===\n{_menu(req)}",
        f"=== WHAT THE NEWS SAYS ===\n{_context(ctx)}",
    ]
    if req.kind == "review":
        blocks.append(
            "=== RE-EVALUATION (Python decided to re-evaluate; you judge the thesis) ===\n"
            f"{req.trigger_text}\nState INTACT, WEAKENED or BROKEN. A headline alone changes "
            "nothing about what the company is worth."
        )
    blocks.append("Reply shape:\n" + json.dumps(_shape(req), indent=1))
    return "\n\n".join(blocks)
