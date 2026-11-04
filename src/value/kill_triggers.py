"""Claude's kill-triggers, evaluated by Python (spec §8.4, §7.1 trigger 6). Pure: no I/O.

Claude picks up to five predicates from a fixed menu; Python bounds each threshold when the read
is accepted and evaluates every active one on each night's scorecard. A predicate is ``fired``
past its threshold, ``near`` within ``kill_near_pct`` of it (trigger 6, Minor: it opens a
re-evaluation, it never moves a level), ``far`` otherwise, ``unknown`` when the number is missing
(unknown is never zero). The fact-based kinds (``guidance_cut``, ``customer_loss``) fire when a
grounded filing fact of that kind lands after the trigger was chosen; they have no ``near``, and
neither has ``fcf_ttm_negative``, whose threshold is zero.

Units: percent for revenue growth, dilution and gross margin; a multiple for net debt / EBITDA;
dollars (millions, as filed) for TTM FCF.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from src.value.schemas import ValueScorecard

KillState = Literal["fired", "near", "far", "unknown"]
ABOVE = ("net_debt_to_ebitda_above", "dilution_above")
BELOW = ("revenue_growth_below", "gross_margin_below")
FACT_BASED = ("guidance_cut", "customer_loss")
_BELOW_BAND_FLOOR = 10.0  # a "below" threshold near zero still gets a band of p% of 10 points


@dataclass(frozen=True, slots=True)
class KillCheck:
    kind: str
    threshold: float | None
    actual: float | None
    state: KillState

    def line(self) -> str:
        actual = "n/a" if self.actual is None else f"{self.actual:.2f}"
        threshold = "" if self.threshold is None else f" vs {self.threshold:g}"
        return f"{self.kind} {self.state} ({actual}{threshold})"


def _check_actual(card: ValueScorecard, check_id: str) -> float | None:
    return next((c.actual for c in card.health_checks if c.id == check_id), None)


def actual_for(kind: str, card: ValueScorecard) -> float | None:
    m = card.metrics
    if kind == "revenue_growth_below":
        v = m.get("revenue_growth_1y")
        return None if v is None else v * 100.0
    if kind == "gross_margin_below":
        v = m.get("gross_margin_latest")
        return None if v is None else v * 100.0
    if kind == "fcf_ttm_negative":
        return m.get("fcf_ttm")
    if kind == "net_debt_to_ebitda_above":
        return _check_actual(card, "health.net_debt_to_ebitda")
    if kind == "dilution_above":
        return _check_actual(card, "health.dilution")
    return None


def check(
    kind: str,
    threshold: float | None,
    card: ValueScorecard,
    *,
    near_pct: float,
    facts_since: set[str],
) -> KillCheck:
    """One predicate on tonight's scorecard. *facts_since*: the kinds of grounded facts that
    landed for the name since the trigger was chosen."""
    if kind in FACT_BASED:
        return KillCheck(kind, None, None, "fired" if kind in facts_since else "far")
    actual = actual_for(kind, card)
    if actual is None:
        return KillCheck(kind, threshold, None, "unknown")
    p = near_pct / 100.0
    if kind == "fcf_ttm_negative":
        return KillCheck(kind, 0.0, actual, "fired" if actual < 0 else "far")
    if threshold is None:
        return KillCheck(kind, None, actual, "unknown")
    if kind in ABOVE:
        if actual > threshold:
            state: KillState = "fired"
        elif actual >= threshold * (1.0 - p):
            state = "near"
        else:
            state = "far"
        return KillCheck(kind, threshold, actual, state)
    if actual < threshold:
        state = "fired"
    elif actual <= threshold + p * max(abs(threshold), _BELOW_BAND_FLOOR):
        state = "near"
    else:
        state = "far"
    return KillCheck(kind, threshold, actual, state)
