"""Strict parsing of the analyst's replies (spec §8.1: "validated name by name; a malformed or
missing reply means no notes, never a guess"). Shape only: whether a driver is inside its bound,
whether a fact is grounded, whether a verdict may apply, is ``src/value/``'s check.
"""

from __future__ import annotations

import json
import re
from typing import Any

from src.common.value_ai_types import (
    FACT_KINDS,
    KILL_KINDS,
    AnalystReply,
    AnalystRequest,
    Drivers,
    KillTrigger,
    ListCall,
    ProposedFact,
)

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)
_VERDICTS = ("READY", "WATCH", "WAIT", "NO")
_STATES = ("INTACT", "WEAKENED", "BROKEN")


def clean(text: object, limit: int = 1200) -> str:
    """One line, bounded: model text never carries newlines into a card or a prompt."""
    return " ".join(str(text).split())[:limit] if isinstance(text, str) else ""


def extract_json(text: str) -> dict[str, Any] | None:
    t = _FENCE.sub("", (text or "").strip())
    start, end = t.find("{"), t.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        obj = json.loads(t[start : end + 1])
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def _number(v: object) -> float | None:
    """A plain number: not a bool, not text, not NaN."""
    if isinstance(v, bool) or not isinstance(v, int | float) or v != v:
        return None
    return float(v)


def _drivers(raw: object) -> Drivers:
    d = raw if isinstance(raw, dict) else {}
    return Drivers(**{k: _number(d.get(k)) for k in Drivers.model_fields})


def _lists(raw: object, wanted: list[str]) -> list[ListCall]:
    out: list[ListCall] = []
    seen: set[str] = set()
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        name, verdict = item.get("list"), item.get("verdict")
        if name not in wanted or name in seen or verdict not in _VERDICTS:
            continue
        seen.add(name)
        out.append(
            ListCall(
                list_name=name,
                verdict=verdict,
                why=clean(item.get("why"), 300),
                drivers=_drivers(item.get("drivers")),
            )
        )
    return out


def _triggers(raw: object, limit: int) -> list[KillTrigger]:
    out: list[KillTrigger] = []
    seen: set[str] = set()
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict) or item.get("kind") not in KILL_KINDS:
            continue
        if item["kind"] in seen:
            continue
        seen.add(item["kind"])
        out.append(KillTrigger(kind=item["kind"], threshold=_number(item.get("threshold"))))
    return out[:limit]


def _facts(raw: object) -> list[ProposedFact]:
    out: list[ProposedFact] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict) or item.get("kind") not in FACT_KINDS:
            continue
        accn, quote = item.get("accn"), item.get("quote")
        if not isinstance(accn, str) or not isinstance(quote, str) or not quote.strip():
            continue
        item_name = item.get("item")
        out.append(
            ProposedFact(
                kind=item["kind"],
                value=_number(item.get("value")),
                unit=clean(item.get("unit"), 16),
                accn=accn.strip(),
                quote=quote.strip()[:300],
                item=item_name if isinstance(item_name, str) and item_name else None,
            )
        )
    return out


def parse_reply(text: str | None, req: AnalystRequest) -> AnalystReply | None:
    """The reply as plain data, or None when it is unusable for its kind: a standard read with no
    valid verdict, a review with no valid state, anything that is not a JSON object."""
    obj = extract_json(text or "")
    if obj is None:
        return None
    lists = _lists(obj.get("lists"), req.lists)
    state = obj.get("review_state")
    reply = AnalystReply(
        lists=lists if req.kind != "filing" else [],
        profile=clean(obj.get("profile"), 600),
        why_cheap=clean(obj.get("why_cheap")),
        thesis=clean(obj.get("thesis")),
        bear_case=clean(obj.get("bear_case")),
        kill_triggers=_triggers(obj.get("kill_triggers"), req.max_kill_triggers)
        if req.kind != "filing"
        else [],
        review_state=state if req.kind == "review" and state in _STATES else None,
        review_why=clean(obj.get("review_why"), 300) if req.kind == "review" else "",
        facts=_facts(obj.get("facts")) if req.kind == "filing" else [],
    )
    if req.kind == "standard" and not reply.lists:
        return None
    if req.kind == "review" and reply.review_state is None:
        return None
    return reply
