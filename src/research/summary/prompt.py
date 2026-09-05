"""The prompt contract for every summary backend.

Every clause is load-bearing (P0-P1-design §7):

1. The model receives the context as JSON and writes narrative only.
2. **Every number it uses must appear in the context.** It never calculates, estimates,
   or recalls a figure from training.
3. It must not recommend a trade, a position size, or an entry price. That is the
   engine's job and the model has no path to it.
4. ``UNKNOWN`` checks are stated as unknown, never guessed.
5. Output is strict JSON matching ``Summary``.

The prompt is shared across all four backends (``claude_cli``, ``anthropic``,
``openai``, ``ollama``) so the parser and the contract are genuinely common — only
transport differs.
"""

from __future__ import annotations

import json

from src.research.summary.context import ResearchContext

_CONTRACT = """\
You are writing a research summary for a single stock or ETF. You receive a fully-
computed context as JSON. Your job is narrative over those numbers, nothing else.

Hard rules — every one is load-bearing:
1. Every number you use MUST appear in the context. Never calculate, estimate, or recall
   a figure from training. If a number is not in the context, do not invent it.
2. Never recommend a trade, a position size, or an entry price. That is the engine's
   job and you have no path to it.
3. Checks with state "UNKNOWN" are stated as unknown, never guessed.
4. Output strict JSON only — no prose, no markdown — matching this shape:
   {"thesis": str, "bull_points": [str], "bear_points": [str],
    "watch_items": [str], "caveats": [str]}
5. Keep the thesis to one or two sentences. Each list is short (3-6 items).
6. Include the quantitative caveat from the context in your "caveats" verbatim.

Context as JSON:
"""


def build_prompt(context: ResearchContext) -> str:
    """Assemble the prompt: the fixed contract + the context serialised as JSON.

    The context is the only variable input; the contract text is constant. Backends
    hash the prompt (or its context portion) for cache keys, so this function is the
    single source of the prompt string across every backend.
    """
    payload = context.model_dump(mode="json")
    return _CONTRACT + json.dumps(payload, default=str, indent=2)


__all__ = ["build_prompt"]
