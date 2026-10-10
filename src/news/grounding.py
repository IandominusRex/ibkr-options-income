"""Deterministic grounding (spec §6.6): numbers must come from facts/headlines; evidence ids
must exist; a verdict without valid evidence is downgraded to "unclear"; prose that cites ids,
talks about the prompt's inputs, or gives trading instructions is dropped. An explanation that
cites no valid evidence at all is withheld by the caller (explain.explain_card)."""

from __future__ import annotations

import re

from src.news.schemas import DigestReads, Explanation, FactSheet

_NUM = re.compile(r"(?<![A-Za-z0-9])(\$)?([-+]?\d[\d,]*(?:\.(\d+))?)\s?(%|bps|bp|σ|x|×|[KMB]\b)?")
_SENT = re.compile(r"(?<=[.!?;])\s+")
_TEXT_FIELDS = ("headline", "read", "bull", "bear", "book_impact", "setup_impact")
# Prose that addresses the inputs instead of the market: "(N2, N3)", "N6 is about CrowdStrike",
# "No AVGO price fact supplied". Ids belong in `evidence`; the reader never sees the prompt.
_ID_PAREN = re.compile(r"\s*\((?:\s*[NF]\d+\s*,?)+\)")
_ID = re.compile(r"\b[NF]\d+\b")
_META = re.compile(
    r"\b(?:facts?|headlines?|data)\b[^.!?;]*\b(?:supplied|provided|given|listed)\b"
    r"|\bin the (?:facts|headlines)\b",
    re.I,
)
# Trading instructions, which the rules forbid: a sentence that opens with an order verb, or
# a stock phrase anywhere in it. "Check open short puts" is a prompt to look, not an order.
# Opening verbs are the unambiguous ones: "Short interest…" and "Close above $50…" are prose.
_ADVICE = re.compile(
    r"^(?:sell|buy|reduce|trim|hedge|avoid|go long|go short|take profits?|"
    r"consider (?:buying|selling|adding|reducing|closing|trimming|hedging))(?![\w-])"
    r"|\b(?:sell (?:the )?rall(?:y|ies)|buy (?:the )?dips?|buy protection|reduce (?:long|short)"
    r" positions?|take profits?)\b",
    re.I,
)


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


def strip_meta_and_advice(text: str) -> tuple[str, bool]:
    """Drop sentences that cite ids in prose, talk about the prompt's inputs, or give trading
    instructions. A parenthetical id list is removed and the sentence kept."""
    text = _ID_PAREN.sub("", text)
    kept, trimmed = [], False
    for sent in _SENT.split(text.strip()) if text.strip() else []:
        if _ID.search(sent) or _META.search(sent) or _ADVICE.search(sent.strip()):
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
        new, t2 = strip_meta_and_advice(new)
        trimmed |= t or t2
        update[field] = new
    what, t = strip_ungrounded(e.what_happened, refs, rel_tol)
    what, t2 = strip_meta_and_advice(what)
    t = t or t2
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
        read, _ = strip_meta_and_advice(strip_ungrounded(it.read, refs, rel_tol)[0])
        head, _ = strip_meta_and_advice(strip_ungrounded(it.headline, refs, rel_tol)[0])
        ev = [x for x in it.evidence if x in valid_ids]
        items.append(
            it.model_copy(
                update={
                    "read": read,
                    # Never fall back to the LLM's own (ungrounded) headline: an empty one
                    # makes the digest show the source cluster headline instead.
                    "headline": head,
                    "evidence": ev,
                    "verdict": it.verdict if ev else "unclear",
                }
            )
        )
    return DigestReads(items=items)
