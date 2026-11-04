"""The VALUE NOTE: what the value book thinks of a name, as prompt text (Part 6, ruling 9).

Pure: plain values in, text out, no I/O and no import from the rest of ``src`` (so the read-only
``src.common.value_view`` may build these shapes and ``src.claude.value_context`` may render
them). It is context for the wheel's trade review, roll review and ``/scan NAME`` and nothing
else: the block ends with a rule line saying so, the Rules Engine enforces the value put
ceiling itself, and the only reach the prompt has over size is the existing clamped, reduce-only
``max_contracts`` cut. Unknown numbers print ``n/a``, never zero.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

HEADER = "=== VALUE NOTE ==="
RULE_LINE = "Context only. It never moves the Rules Engine; the value put ceiling is enforced by the system."
MAX_CHARS = 2000
_LIST_WORDS = {"deep_value": "deep value", "quality_growth": "quality growth"}
_VERDICT_RANK = {"READY": 0, "WATCH": 1, "WAIT": 2}


@dataclass(frozen=True, slots=True)
class ListNote:
    """One list's standing for one name: the verdict in force and who decided it."""

    list_name: str
    verdict: str
    decided_by: str  # "claude" | "python"
    python_fair_value: float | None = None
    effective_fair_value: float | None = None  # Claude's clamped value when Claude decided
    margin: float | None = None  # margin of safety, a fraction
    put_ceiling: float | None = None  # the effective entry ceiling


@dataclass(frozen=True, slots=True)
class ValueNoteView:
    """Everything the note says about one name."""

    symbol: str
    lists: tuple[ListNote, ...] = ()
    held_shares: float = 0.0
    next_exit: tuple[str, float | None] | None = None  # ("sell half at" | "stop at", price)
    reevaluation: tuple[str, str] | None = None  # (severity, session date) of an open one


def _money(v: float | None) -> str:
    return "n/a" if v is None else f"${v:,.2f}"


def _pct(v: float | None) -> str:
    return "n/a" if v is None else f"{v * 100:.0f}%"


def _word(list_name: str) -> str:
    return _LIST_WORDS.get(list_name, list_name.replace("_", " "))


def _who(by: str) -> str:
    return "Claude" if by == "claude" else "Python"


def _sort_key(n: ListNote) -> tuple[int, str]:
    return (_VERDICT_RANK.get(n.verdict, 3), n.list_name)


def _fair_value_line(n: ListNote, label: str) -> str:
    if n.decided_by == "claude" and n.effective_fair_value is not None:
        fair = (
            f"fair value {_money(n.python_fair_value)} (Python) / "
            f"{_money(n.effective_fair_value)} (effective, Claude's clamped)"
        )
    else:
        fair = f"fair value {_money(n.python_fair_value)} (Python)"
    return f"  {label}{fair} · margin {_pct(n.margin)} · value put ceiling {_money(n.put_ceiling)}"


def render_name(note: ValueNoteView) -> str:
    """One name's lines (at most six); ``""`` for a name the book does not know."""
    lists = sorted(note.lists, key=_sort_key)
    if not lists and note.held_shares <= 0:
        return ""
    lines: list[str] = []
    if lists:
        head = " · ".join(
            f"{_word(n.list_name)}: {n.verdict} ({_who(n.decided_by)})" for n in lists
        )
        lines.append(f"{note.symbol}  {head}")
        for n in lists:
            lines.append(_fair_value_line(n, f"{_word(n.list_name)}: " if len(lists) > 1 else ""))
    else:
        lines.append(note.symbol)
    if note.held_shares > 0:
        parts = [f"value book holds {note.held_shares:g} sh"]
        if note.next_exit is not None:
            parts.append(f"next exit: {note.next_exit[0]} {_money(note.next_exit[1])}")
        if note.reevaluation is not None:
            parts.append(f"re-evaluation open ({note.reevaluation[0]}, {note.reevaluation[1]})")
        lines.append("  " + " · ".join(parts))
    return "\n".join(lines[:6])


def render_value_notes(
    symbols: Iterable[str], notes: Mapping[str, ValueNoteView], *, max_chars: int = MAX_CHARS
) -> str:
    """The ``=== VALUE NOTE ===`` block for the names of *symbols* the book knows (each once, in
    the order given), at most *max_chars* characters, cut on a name boundary with a count of the
    names left out. ``""`` when it knows none of them. The rule line is always the last."""
    names = list(dict.fromkeys(s.upper() for s in symbols))
    blocks = [b for s in names if s in notes and (b := render_name(notes[s]))]
    if not blocks:
        return ""
    more = "\n(%d more names with value notes are not shown)"
    room = max_chars - len(HEADER) - len(RULE_LINE) - 2 - len(more % 99)
    kept: list[str] = []
    used = 0
    for b in blocks:
        if used + len(b) + 1 > room:
            break
        kept.append(b)
        used += len(b) + 1
    if not kept:
        return ""
    text = "\n".join([HEADER, *kept])
    if len(kept) < len(blocks):
        text += more % (len(blocks) - len(kept))
    return f"{text}\n{RULE_LINE}"
