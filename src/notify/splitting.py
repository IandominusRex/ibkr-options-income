"""Telegram-sized chunks for the wheel's MarkdownV2 messages.

A message may carry at most 4096 characters. The formatters used to slice at 4000 and append
an ellipsis, which dropped whatever sat past the cut (2026-10-27: a `/scan GOOGL` reply lost its
Levels section) and could land inside a bold run or an escape pair, so Telegram rejected the whole
message. :func:`split_message` cuts at a paragraph, then a line, then a word boundary instead, and
closes any entity still open at a cut and reopens it at the start of the next chunk, so every
chunk parses on its own. The news package has its own HTML twin (``src/news/render.py``).
"""

from __future__ import annotations

# Telegram's cap is 4096; the margin covers the closers added at a cut and any difference in how
# Telegram counts emoji (it counts UTF-16 code units, which is what `_units` counts).
LIMIT = 4000
MAX_CHUNKS = 8
_RESERVE = 24  # room for the closers appended to a chunk and the marker added at its end

# MarkdownV2 entity markers, longest first so "```" is read before "`" and "__" before "_".
_MARKERS = ("```", "__", "||", "*", "_", "~", "`")


def _units(text: str) -> int:
    """Length in UTF-16 code units, the way Telegram counts (an emoji is two)."""
    return len(text.encode("utf-16-le")) // 2


def open_entities(text: str, stack: list[str] | None = None) -> list[str]:
    """The MarkdownV2 markers still open at the end of *text*, outermost first.

    *stack* is what was already open when *text* began. A backslash escapes the next character;
    inside a code span or block nothing but its own closer counts.
    """
    out = list(stack or [])
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch == "\\":
            i += 2
            continue
        if out and out[-1] in ("`", "```"):
            closer = out[-1]
            if text.startswith(closer, i):
                out.pop()
                i += len(closer)
            else:
                i += 1
            continue
        for marker in _MARKERS:
            if text.startswith(marker, i):
                if marker in out:
                    out.remove(marker)
                else:
                    out.append(marker)
                i += len(marker)
                break
        else:
            i += 1
    return out


def _fit(text: str, budget: int) -> int:
    """The largest index k with `_units(text[:k]) <= budget`."""
    if _units(text) <= budget:
        return len(text)
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if _units(text[:mid]) <= budget:
            lo = mid
        else:
            hi = mid - 1
    return lo


def _cut_point(text: str, budget: int) -> int:
    """Where to end the next chunk: after a blank line, else a line, else a word, else mid-text."""
    k = _fit(text, budget)
    head = text[:k]
    for sep, floor in (("\n\n", 0.4), ("\n", 0.25), (" ", 0.25)):
        at = head.rfind(sep)
        if at >= max(1, int(k * floor)):
            cut = at + len(sep)
            break
    else:
        cut = k
    # Never leave a lone backslash at the end of a chunk: it would escape the closer.
    while (
        cut > 1 and text[cut - 1] == "\\" and (len(text[:cut]) - len(text[:cut].rstrip("\\"))) % 2
    ):
        cut -= 1
    return max(cut, 1)


def split_message(text: str, limit: int = LIMIT, *, markdown: bool = True) -> list[str]:
    """Split *text* into chunks of at most *limit* UTF-16 units, each well-formed on its own.

    ``markdown=True`` treats the text as MarkdownV2 and keeps entities balanced across cuts;
    ``markdown=False`` is for plain text. Text already within the limit comes back as one chunk,
    untouched. More than ``MAX_CHUNKS`` chunks are cut off with a closing ellipsis (a message
    that long is a bug in the formatter, not something to send as twenty messages).
    """
    if _units(text) <= limit:
        return [text]
    chunks: list[str] = []
    carry: list[str] = []
    rest = text
    while rest:
        prefix = "".join(carry) if markdown else ""
        budget = limit - _units(prefix) - _RESERVE
        if _units(rest) <= budget:
            chunks.append(prefix + rest)
            break
        cut = _cut_point(rest, budget)
        head, rest = rest[:cut], rest[cut:]
        still_open = open_entities(head, carry) if markdown else []
        closers = "".join(reversed(still_open))
        chunks.append(prefix + head.rstrip("\n") + closers)
        carry = still_open
    if len(chunks) > MAX_CHUNKS:
        chunks = chunks[:MAX_CHUNKS]
        chunks[-1] += "\n…"
    return chunks
