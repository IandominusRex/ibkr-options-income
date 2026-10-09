"""Deterministic grounding (spec §6.6): numbers must come from facts/headlines; evidence ids
must exist; a verdict without valid evidence is downgraded to "unclear"."""

from __future__ import annotations

import re

from src.news.schemas import DigestReads, Explanation, FactSheet

_NUM = re.compile(r"(?<![A-Za-z0-9])(\$)?([-+]?\d[\d,]*(?:\.(\d+))?)\s?(%|bps|bp|σ|x|×|[KMB]\b)?")
_SENT = re.compile(r"(?<=[.!?;])\s+")
_TEXT_FIELDS = ("headline", "read", "bull", "bear", "book_impact", "setup_impact")


def extract_numbers(text: str) -> list[tuple[float, int, bool]]:
    out = []
    for m in _NUM.finditer(text):
        dollar, raw, dec, unit = m.group(1), m.group(2), m.group(3), m.group(4)
        try:
            v = float(raw.replace(",", ""))
        except ValueError:
            continue
        decimals = len(dec) if dec else 0
        must = bool(dollar or unit or dec) or abs(v) > 10
        out.append((v, decimals, must))
    return out


def grounded(value: float, decimals: int, refs: list[float], rel_tol: float) -> bool:
    step = 10**-decimals if decimals else 0.5
    for r in refs:
        tol = max(rel_tol * abs(r), step)
        if abs(value - r) <= tol or abs(abs(value) - abs(r)) <= tol:
            return True
    return False


def strip_ungrounded(text: str, refs: list[float], rel_tol: float) -> tuple[str, bool]:
    kept, trimmed = [], False
    for sent in _SENT.split(text.strip()) if text.strip() else []:
        bad = any(
            must and not grounded(v, d, refs, rel_tol) for v, d, must in extract_numbers(sent)
        )
        if bad:
            trimmed = True
        else:
            kept.append(sent)
    return " ".join(kept), trimmed


def ground(
    e: Explanation,
    *,
    facts: FactSheet,
    news_numbers: list[float],
    news_ids: set[str],
    rel_tol: float,
    fallback_what: str | None,
) -> tuple[Explanation, bool]:
    refs = facts.numbers() + news_numbers
    update: dict[str, object] = {}
    trimmed = False
    for field in _TEXT_FIELDS:
        new, t = strip_ungrounded(getattr(e, field), refs, rel_tol)
        trimmed |= t
        update[field] = new
    what, t = strip_ungrounded(e.what_happened, refs, rel_tol)
    if t or not what:
        trimmed |= t
        what = (fallback_what or what)[:180]
    update["what_happened"] = what
    valid = facts.ids() | news_ids
    evidence = [x for x in e.evidence if x in valid]
    update["evidence"] = evidence
    if not evidence and e.verdict != "unclear":
        update["verdict"], update["confidence"] = "unclear", "low"
    return e.model_copy(update=update), trimmed


def ground_digest(
    r: DigestReads, *, refs: list[float], valid_ids: set[str], rel_tol: float
) -> DigestReads:
    items = []
    for it in r.items:
        read, _ = strip_ungrounded(it.read, refs, rel_tol)
        head, _ = strip_ungrounded(it.headline, refs, rel_tol)
        ev = [x for x in it.evidence if x in valid_ids]
        items.append(
            it.model_copy(
                update={
                    "read": read,
                    "headline": head or it.headline[:80],
                    "evidence": ev,
                    "verdict": it.verdict if ev else "unclear",
                }
            )
        )
    return DigestReads(items=items)
