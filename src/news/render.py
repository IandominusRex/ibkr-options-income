"""Telegram HTML for news cards (spec §7.1). Every dynamic string goes through esc()."""

from __future__ import annotations

import html
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


def split_message(text: str, limit: int = LIMIT) -> list[str]:
    parts: list[str] = []
    cur = ""
    for block in text.split("\n\n"):
        while len(block) > limit:
            if cur:
                parts.append(cur)
                cur = ""
            parts.append(block[:limit])
            block = block[limit:]
        candidate = f"{cur}\n\n{block}" if cur else block
        if len(candidate) > limit:
            parts.append(cur)
            cur = block
        else:
            cur = candidate
    if cur:
        parts.append(cur)
    return parts
