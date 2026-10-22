"""The one neutral rendering of a ticker dossier, shared by every reader.

The trade review, the roll review and ``/scan`` all show the model the same block, so a name can
never read differently in two places. Neutral module: it imports only ``src.common.schemas`` (and
the standard library), so any tier may use it and it can reach neither the engine nor a database.

Two sizes. **Compact** (about 80 words) is for the many names of a full-scan prompt: kind and
health, the story, the dated events and three key facts. **Full** (about 220 words) adds the
profile (labelled as Claude's general knowledge), every fact that fits and the 7-day news
sentiment; it is for the one name a deep-dive or a roll is about. The word budget is enforced here,
not left to the builder: facts give way first, then extra events, then extra reported figures,
then the story is shortened, and only then is the last reported figure dropped.

Figures quoted from the news (``TickerDossier.reported``, OI-E10) print on **their own line**,
labelled "Reported in news (not computed by the system)", under the story and never inside it: the
story carries only the system's numbers, the reader must be able to tell the two apart.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from src.common.schemas import DossierEvent, DossierFact, DossierReported, TickerDossier

_ET = ZoneInfo("America/New_York")
_HEADER = "=== NAME NOTES ==="
COMPACT_WORDS = 80
FULL_WORDS = 220
_KIND = {"stock": "stock", "etf": "ETF", "leveraged_etf": "leveraged ETF"}
# The compact block shows the first three of these that the dossier has, in this order.
_COMPACT_FACTS = (
    "Price vs SMA200",
    "RSI14",
    "IV rank",
    "Nearest resistance",
    "Nearest support",
)
# What the full block keeps first when it has to choose (most useful first); unknown labels last.
_FACT_PRIORITY = (
    *_COMPACT_FACTS,
    "Earnings date",
    "1-month return",
    "3-month return",
    "Move today",
    "Phase",
    "IV30 vs HV30",
    "Avg post-earnings move",
    "Move vs SPY",
    "Move in σ",
    "SPY today",
    "IV-implied 1-day move",
    "Move ÷ ATR14",
    "Regime index",
    "Universe",
)
_MIN_STORY_WORDS = 8
REPORTED_LABEL = "Reported in news (not computed by the system): "
_REPORTED_COMPACT = 2  # reported figures a compact note starts with (the budget may drop some)


def _aware(dt: datetime) -> datetime:
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt


def _words(*lines: str) -> int:
    return sum(len(line.split()) for line in lines)


def _fact_line(f: DossierFact) -> str:
    return f"{f.id} {f.label}: {f.display}"


def _event_line(e: DossierEvent) -> str:
    return f"{e.id} {e.title} on {e.on:%Y-%m-%d} ({e.evidence})"


def _reported_line(items: list[DossierReported]) -> str:
    """The quoted figures on their own line, each with the cluster that states it ("" for none)."""
    if not items:
        return ""
    return REPORTED_LABEL + "; ".join(f"{r.text} ({r.cluster_id})" for r in items)


def _story_line(story: str, evidence: list[str]) -> str:
    cited = f" ({', '.join(evidence)})" if evidence else ""
    return f"Story: {story}{cited}"


def _shorten(story: str, evidence: list[str], allowance: int) -> str:
    """The story line cut so that the whole line fits *allowance* words (never below a few)."""
    cited = f" ({', '.join(evidence)})" if evidence else ""
    keep = max(_MIN_STORY_WORDS, allowance - len(cited.split()) - 1)  # -1: the "Story:" label
    cut = story.split()
    if len(cut) <= keep:
        return _story_line(story, evidence)
    return f"Story: {' '.join(cut[:keep])}…{cited}"


def _rank(label: str) -> int:
    return _FACT_PRIORITY.index(label) if label in _FACT_PRIORITY else len(_FACT_PRIORITY)


def _stale_line(d: TickerDossier, *, now: datetime, staleness_hours: float) -> str | None:
    if d.prose_at is None:
        return None
    built = _aware(d.prose_at)
    if d.stale or _aware(now) - built > timedelta(hours=staleness_hours):
        return f"PROSE IS STALE (built {built.astimezone(_ET):%b %d %H:%M} ET)"
    return None


def _pick_facts(facts: list[DossierFact], *, compact: bool, room: int) -> list[DossierFact]:
    """The facts to show within *room* words: three by preference when compact, as many as fit by
    priority (kept in their original order) when full."""
    if compact:
        by_label = {f.label: f for f in facts}
        candidates = [by_label[label] for label in _COMPACT_FACTS if label in by_label][:3]
        shown: list[DossierFact] = []
        for f in candidates:  # in preference order: the least preferred is the first to go
            if _words(*(_fact_line(x) for x in shown), _fact_line(f)) <= room:
                shown.append(f)
        return shown
    keep: set[str] = set()
    used = 0
    for f in sorted(facts, key=lambda f: (_rank(f.label), f.id)):
        cost = _words(_fact_line(f))
        if used + cost <= room:
            keep.add(f.id)
            used += cost
    return [f for f in facts if f.id in keep]


def render_dossier(
    d: TickerDossier | None,
    *,
    symbol: str,
    now: datetime,
    staleness_hours: float,
    compact: bool,
) -> str:
    """One name's block. ``None`` (no dossier built yet) renders as ``--- SYM --- (no notes yet)``.

    Prose older than *staleness_hours*, or marked stale because its last rebuild failed, is
    prefixed ``PROSE IS STALE (built ...)`` so the reader weighs it accordingly; the numbers are
    never older than the hourly refresh and carry no such label.
    """
    if d is None:
        return f"--- {symbol} --- (no notes yet)"
    budget = COMPACT_WORDS if compact else FULL_WORDS
    head = f"--- {symbol} ({_KIND[d.kind]} · health {d.health}) ---"
    top: list[str] = [head]
    stale = _stale_line(d, now=now, staleness_hours=staleness_hours)
    if stale is not None:
        top.append(stale)
    if d.health_why:
        top.append(
            "Health: " + ("; ".join(d.health_why[:1]) if compact else "; ".join(d.health_why))
        )
    if d.prose_at is None:
        top.append("Notes not written yet (numbers only)")
    story = _story_line(d.story, d.story_evidence) if d.story else ""
    events = [_event_line(e) for e in d.events]
    tail: list[str] = []
    if not compact:
        if d.profile:
            tail.append(f"Profile (Claude's summary, general knowledge): {d.profile}")
        if d.sentiment_7d is not None:
            n = d.sentiment_items_7d
            tail.append(
                f"7-day news sentiment {d.sentiment_7d:+.2f} over {n} item{'' if n == 1 else 's'}"
            )

    reported = d.reported[:_REPORTED_COMPACT] if compact else list(d.reported)
    base = _words(*top, story, _reported_line(reported), *events, *tail)
    if base > budget:
        # extra events go first, then extra reported figures, then the story is shortened, and
        # only then is the last reported figure dropped
        while base > budget and len(events) > 1:
            events.pop()
            base = _words(*top, story, _reported_line(reported), *events, *tail)
        while base > budget and len(reported) > 1:
            reported = reported[:-1]
            base = _words(*top, story, _reported_line(reported), *events, *tail)
        if base > budget and story:
            allowance = len(story.split()) - (base - budget)
            story = _shorten(d.story, d.story_evidence, allowance)
            base = _words(*top, story, _reported_line(reported), *events, *tail)
        if base > budget and reported:
            reported = []
            base = _words(*top, story, *events, *tail)
    shown = _pick_facts(d.facts, compact=compact, room=max(0, budget - base))

    lines = [*top]
    if story:
        lines.append(story)
    if reported:
        lines.append(_reported_line(reported))
    lines.extend(events)
    lines.extend(tail)
    lines.extend(_fact_line(f) for f in shown)
    return "\n".join(lines)


def render_dossiers(
    ds: list[tuple[str, TickerDossier | None]],
    *,
    now: datetime,
    staleness_hours: float,
    compact: bool,
) -> str:
    """The ``=== NAME NOTES ===`` block for several names, in the order given ("" for none)."""
    if not ds:
        return ""
    blocks = [
        render_dossier(d, symbol=symbol, now=now, staleness_hours=staleness_hours, compact=compact)
        for symbol, d in ds
    ]
    return _HEADER + "\n" + "\n\n".join(blocks)
