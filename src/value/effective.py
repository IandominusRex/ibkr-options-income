"""The effective verdict (spec §6.7): Python's baseline, then Claude's call. Pure: no I/O.

- Python's ``NO``, ``UNKNOWN`` and ``NOT_APPLICABLE`` are final: Claude cannot lift a name over
  a health, data or list-entry gate, nor value a name Python cannot.
- On a healthy name with a usable Claude opinion (a CLI verdict that is not superseded, whose
  fair value Python computed and clamped, while the breaker is not tripped and Claude applies in
  this mode), Claude's fair value replaces Python's in the entry ceiling and the margin of
  safety, and the verdict is the **stricter** of Claude's word and what price and timing allow
  against Claude's fair value: Claude decides which state a name is in, Python's gates bound it.
  So a Claude READY with timing failing is WATCH, a Claude READY above Claude's own ceiling is
  WAIT, and a Claude WAIT stays WAIT until Claude reads the name again.
- Anything else keeps Python's baseline, labelled ``python``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from src.value.schemas import ValueScorecard

_RANK = {"NO": 0, "WAIT": 1, "WATCH": 2, "READY": 3}


@dataclass(frozen=True, slots=True)
class ClaudeOpinion:
    """What a stored Claude verdict says about one list, as the night reads it."""

    verdict: str  # READY | WATCH | WAIT | NO
    fair_value: float | None  # Claude's clamped fair value; None when unusable
    verdict_id: int | None = None


@dataclass(frozen=True, slots=True)
class Effective:
    list_name: str
    verdict: str
    decided_by: Literal["claude", "python"]
    python_verdict: str
    fair_value: float | None
    entry_ceiling: float | None
    margin_of_safety: float | None
    mos_review: bool
    claude_verdict: str | None = None
    verdict_id: int | None = None


def _python(card: ValueScorecard, list_name: str) -> Effective:
    ev = card.lists.get(list_name)
    return Effective(
        list_name=list_name,
        verdict=card.verdict_for(list_name),
        decided_by="python",
        python_verdict=card.verdict_for(list_name),
        fair_value=ev.fair_value if ev else None,
        entry_ceiling=ev.entry_ceiling if ev else None,
        margin_of_safety=ev.margin_of_safety if ev else None,
        mos_review=ev.mos_review if ev else False,
    )


def effective(
    card: ValueScorecard,
    list_name: str,
    opinion: ClaudeOpinion | None,
    *,
    review_above_pct: float,
) -> Effective:
    """One list's effective verdict. *opinion* is None when Claude has not read the name, its
    reply was not usable, the breaker is tripped, or Claude does not apply in this mode."""
    base = _python(card, list_name)
    ev = card.lists.get(list_name)
    if (
        opinion is None
        or opinion.fair_value is None
        or opinion.fair_value <= 0
        or ev is None
        or card.price is None
        or card.health != "pass"
        or base.verdict not in ("READY", "WATCH", "WAIT")
    ):
        return base
    fv = opinion.fair_value
    ceiling = fv * (1.0 - ev.required_mos_pct / 100.0)
    mos = (fv - card.price) / fv
    if card.price > ceiling:
        allowed = "WAIT"
    elif ev.timing != "pass":
        allowed = "WATCH"
    else:
        allowed = "READY"
    verdict = min(opinion.verdict, allowed, key=lambda v: _RANK[v])
    return Effective(
        list_name=list_name,
        verdict=verdict,
        decided_by="claude",
        python_verdict=base.python_verdict,
        fair_value=fv,
        entry_ceiling=ceiling,
        margin_of_safety=mos,
        mos_review=mos * 100.0 > review_above_pct,
        claude_verdict=opinion.verdict,
        verdict_id=opinion.verdict_id,
    )
