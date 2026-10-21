"""Telegram HTML for news cards (spec §7.1). Every dynamic string goes through esc()."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from src.news.schemas import CardPayload, DigestSection, SourceLink

SGT = ZoneInfo("Asia/Singapore")
ET = ZoneInfo("America/New_York")
LIMIT = 4096

VERDICT_LABEL = {
    "further_downside_likely": "Further downside likely",
    "further_upside_likely": "Further upside likely",
    "overreaction_likely": "Overreaction likely",
    "priced_in": "Priced in",
    "unclear": "Unclear",
}
_REGIME = {
    "risk_on": "🟢 Risk-on",
    "risk_off": "🔴 Risk-off",
    "rotation": "🔄 Rotation",
    "mixed": "⚪ Mixed",
}


def late_post_line(move_pct: float) -> str:
    """The exact copy of a late promotion (safeguard 2): it states the move, never a cause."""
    return f"Dismissed earlier; the market moved {move_pct:+.1f}% after it. Cause not confirmed."


@dataclass
class RenderedMessage:
    text: str
    preview_url: str | None
    show_above: bool


def esc(s: str | None) -> str:
    return html.escape(s or "", quote=False)


def link(lk: SourceLink) -> str:
    return f'<a href="{html.escape(lk.url, quote=True)}">{esc(lk.name)}</a>'


def fmt_when(dt: datetime) -> str:
    if dt.tzinfo is None:  # the store keeps naive-UTC; astimezone() would read it as host-local
        dt = dt.replace(tzinfo=UTC)
    return f"{dt.astimezone(SGT):%H:%M} SGT ({dt.astimezone(ET):%H:%M} ET)"


def _grid(p: CardPayload) -> list[str]:
    if not p.grid:
        return []
    rows = [f"{'':<9} {'📘 Textbook':<12} 📈 Actual (15m)"]
    for g in p.grid:
        rows.append(
            f"{esc(g.asset.title()):<9} {esc(g.textbook or '·'):<12} {esc(g.actual or '·')}"
        )
    out = ["<pre>" + "\n".join(rows) + "</pre>"]
    if p.grid_note:
        out.append(f"<i>{esc(p.grid_note)}</i>")
    return out


def _section(sec: DigestSection) -> list[str]:
    out = [f"<b>{esc(sec.title)}</b>"]
    for it in sec.items:
        line = f"• {esc(it.text)}"
        if it.links:
            line += " — " + " · ".join(link(lk) for lk in it.links[:3])
        out.append(line)
        if it.read:
            out.append(f"  🧠 {esc(it.read)}")
        if it.verdict:
            out.append(f"  🎯 {VERDICT_LABEL[it.verdict]}")
    return out


def render_card(p: CardPayload) -> RenderedMessage:
    blocks: list[list[str]] = []
    head = [f"{esc(p.emoji)} <b>{esc(p.title)}</b> · {fmt_when(p.when)}"]
    if p.regime:
        head.append(_REGIME.get(p.regime, esc(p.regime)))
    if p.headline_line:
        line = esc(p.headline_line)
        if p.links:
            line += " — " + " · ".join(link(lk) for lk in p.links[:3])
        head.append(line)
    if p.facts_line:
        head.append(esc(p.facts_line))
    blocks.append(head)
    if p.grid:
        blocks.append(_grid(p))
    e = p.explanation
    if e is not None:
        ex = [
            f"🧠 {esc(e.read)}",
            f"⚖️ Bull: {esc(e.bull)} · Bear: {esc(e.bear)}",
            f"🎯 {VERDICT_LABEL[e.verdict]} · {e.confidence}",
        ]
        if e.book_impact:
            ex.append(f"💼 {esc(e.book_impact)}")
        if e.setup_impact:
            ex.append(f"🛒 {esc(e.setup_impact)}")
        if p.trimmed:
            ex.append("<i>⚠︎ trimmed</i>")
        blocks.append(ex)
    if p.llm_note:
        blocks.append([f"<i>{esc(p.llm_note)}</i>"])
    for sec in p.sections:
        blocks.append(_section(sec))
    if p.updates:
        blocks.append([esc(u) for u in p.updates])
    if p.links and not p.headline_line:
        blocks.append(["🔗 " + " · ".join(link(lk) for lk in p.links[:4])])
    text = "\n\n".join("\n".join(b) for b in blocks if b)
    if p.image_url:
        return RenderedMessage(text=text, preview_url=p.image_url, show_above=True)
    return RenderedMessage(text=text, preview_url=p.preview_url, show_above=False)


_TAG = re.compile(r"<(/?)([a-zA-Z][a-zA-Z0-9-]*)[^>]*>")


def _open_after(text: str, stack: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """The (name, opening tag) stack still open after *text*, starting from *stack*."""
    out = list(stack)
    for m in _TAG.finditer(text):
        name = m.group(2).lower()
        if m.group(1):
            for i in range(len(out) - 1, -1, -1):
                if out[i][0] == name:
                    del out[i:]
                    break
        else:
            out.append((name, m.group(0)))
    return out


def _closers(stack: list[tuple[str, str]]) -> str:
    return "".join(f"</{name}>" for name, _ in reversed(stack))


def _safe_cut(s: str, n: int) -> int:
    """Largest cut <= n that lands neither inside a tag nor inside an HTML entity."""
    cut = min(n, len(s))
    lt = s.rfind("<", 0, cut)
    if lt > s.rfind(">", 0, cut):
        cut = lt
    amp = s.rfind("&", 0, cut)
    if amp != -1 and ";" not in s[amp:cut]:
        cut = amp
    return cut if cut > 0 else min(n, len(s))


def _units(text: str, limit: int) -> list[tuple[str, str]]:
    """(separator, piece) pairs, each piece small enough to fit a chunk on its own.

    Paragraphs first, then lines, then words; a single word longer than the limit is sliced at
    a point that is outside any tag or entity. Separators are kept so the pieces rejoin exactly.
    """
    out: list[tuple[str, str]] = []
    budget = max(limit // 2, 1)  # room left for the tags a chunk must close and reopen
    for bi, block in enumerate(text.split("\n\n")):
        sep = "" if bi == 0 else "\n\n"
        if len(block) <= budget:
            out.append((sep, block))
            continue
        for li, line in enumerate(block.split("\n")):
            lsep = sep if li == 0 else "\n"
            if len(line) <= budget:
                out.append((lsep, line))
                continue
            rest, first = line, True
            while rest:
                cut = len(rest) if len(rest) <= budget else _safe_cut(rest, budget)
                if cut < len(rest):
                    space = rest.rfind(" ", 0, cut)
                    if space > 0 and _safe_cut(rest, space) == space:
                        cut = space
                out.append((lsep if first else "", rest[:cut]))
                rest, first = rest[cut:], False
    return out


def split_message(text: str, limit: int = LIMIT) -> list[str]:
    """Split HTML *text* into Telegram-sized chunks, every chunk well-formed on its own.

    Cuts prefer paragraph, then line, then word boundaries and never land inside a tag or an
    entity. A tag still open at a cut is closed at the end of its chunk and reopened at the
    start of the next (2026-10-13: a hard slice inside an ``<a href>`` made Telegram reject a
    whole close digest after its header).
    """
    parts: list[str] = []
    stack: list[tuple[str, str]] = []  # tags open at the start of the current chunk
    prefix = ""
    cur = ""
    for sep, piece in _units(text, limit):
        candidate = f"{cur}{sep}{piece}" if cur else piece
        if cur and len(prefix + candidate + _closers(_open_after(candidate, stack))) > limit:
            end = _open_after(cur, stack)
            parts.append(prefix + cur + _closers(end))
            stack = end
            prefix = "".join(tag for _, tag in stack)
            cur = piece
        else:
            cur = candidate
    if cur:
        parts.append(prefix + cur + _closers(_open_after(cur, stack)))
    return parts
