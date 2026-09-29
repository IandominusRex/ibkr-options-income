"""Bounded tool-calling research turn for the local Ollama strategist (Task 11).

Before the final structured review call, the model gets one `/api/chat` turn with a single
`search_news` tool available and an explicit budget (`claude.max_tool_rounds`, default 2): it
*may* call `search_news` for anything the static `=== NEWS ===` block
(:mod:`src.claude.news_context`) left open — e.g. "AAPL guidance" or "Fed meeting this week" —
or it may not call it at all. Each call is executed against the configured
`NewsSearchProvider` (:func:`src.data.factory.get_news_search_provider`), capped at 5 results,
and appended as a `role: "tool"` message numbered to continue the NEWS block's `N#` ids so the
DECISION RUBRIC's "cite F#/N#" instruction stays valid for anything the research turn surfaces.

`research_turn` does **not** make the final structured call itself — when the model actually
calls `search_news`, it returns the accumulated chat messages (the user turn + the assistant's
tool-call turn + the tool-result turns) for the caller (`ollama_runner.review_candidates`) to
send as one more `/api/chat` request with `format=REVIEW_SCHEMA` and *no* `tools`. Any failure
here — a connection error, a timeout, a model that doesn't support tool calling, or a malformed
response — is logged and `research_turn` returns `None`; the caller falls back to the Task 10
single-shot `_generate` (`/api/generate`) path. **Fix round 1:** the model choosing *not* to call
`search_news` also returns `None`, not the messages — its unconstrained reply otherwise had to be
fed into a second, `format`-constrained call for no benefit (and at real cost: on a full
multi-candidate prompt that reply can itself run to ~1.7-2k tokens, and appending it as a
trailing assistant turn to the final call risked Ollama treating it as a prefill). The research
turn is enrichment, never a dependency: a broken, slow, or declined tool-calling round must never
be the reason a review doesn't happen, or costs more than the single-shot path would have.

**Fence (CLAUDE.md).** Enrichment tier only — must never be importable from `src/engine/`,
`src/execution/`, or `src/strategies/` — see
`tests/test_eval_skills.py::test_news_and_tool_research_never_reach_the_deterministic_layer`.
"""

from __future__ import annotations

import json
import logging
import re

import httpx

from src.data.factory import get_news_search_provider

log = logging.getLogger(__name__)

# Matches the F#/N# fact/news ids already present in the built prompt, so a research turn's
# new search results continue numbering from the NEWS block's highest id rather than colliding
# with it (the DECISION RUBRIC asks the model to cite these ids in `evidence`).
_N_ID_RE = re.compile(r"\bN(\d+)\b")

_SEARCH_NEWS_TOOL = {
    "type": "function",
    "function": {
        "name": "search_news",
        "description": (
            "Search recent news for a query — a ticker plus a topic (e.g. 'AAPL guidance') or "
            "a macro topic (e.g. 'Fed meeting this week'). Use only for something the NEWS "
            "block above does not already cover."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search text."},
                "days": {
                    "type": "integer",
                    "description": "How many days back to search (default 7).",
                },
            },
            "required": ["query"],
        },
    },
}

_INSTRUCTION_TEMPLATE = (
    "Before judging, you MAY call search_news up to {n} times for anything the NEWS block "
    "leaves open (e.g. '<SYMBOL> guidance', 'Fed meeting this week'). Do not call it otherwise."
)


def _next_news_id(prompt: str) -> int:
    """The next unused `N#` id, continuing from the highest id already in *prompt*."""
    ids = [int(m) for m in _N_ID_RE.findall(prompt)]
    return (max(ids) + 1) if ids else 1


def _tool_calls_from_message(message: dict) -> list[dict]:
    calls = message.get("tool_calls")
    return calls if isinstance(calls, list) else []


def _call_args(call: dict) -> dict:
    func = call.get("function") if isinstance(call, dict) else None
    if not isinstance(func, dict):
        return {}
    args = func.get("arguments")
    if isinstance(args, dict):
        return args
    if isinstance(args, str):
        try:
            parsed = json.loads(args)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _call_name(call: dict) -> str | None:
    func = call.get("function") if isinstance(call, dict) else None
    return func.get("name") if isinstance(func, dict) else None


def research_turn(prompt: str, cfg: object) -> list[dict] | None:
    """Run the bounded tool-calling research turn. Returns the accumulated chat messages for
    the caller's final structured call, or `None` on any failure (see module docstring).
    """
    max_calls = cfg.max_tool_rounds  # type: ignore[attr-defined]
    messages: list[dict] = [
        {"role": "user", "content": f"{prompt}\n\n{_INSTRUCTION_TEMPLATE.format(n=max_calls)}"}
    ]
    url = f"{cfg.ollama_host.rstrip('/')}/api/chat"  # type: ignore[attr-defined]
    body = {
        "model": cfg.ollama_model,  # type: ignore[attr-defined]
        "messages": messages,
        "tools": [_SEARCH_NEWS_TOOL],
        "stream": False,
        "think": False,
        "keep_alive": cfg.ollama_keep_alive,  # type: ignore[attr-defined]
        "options": {
            "temperature": cfg.ollama_temperature,  # type: ignore[attr-defined]
            "num_ctx": cfg.ollama_num_ctx,  # type: ignore[attr-defined]
        },
    }
    try:
        resp = httpx.post(url, json=body, timeout=cfg.tool_research_timeout_seconds)  # type: ignore[attr-defined]
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPError as exc:
        log.warning("ollama research turn: request to %s failed: %s", url, exc)
        return None
    except (ValueError, TypeError) as exc:
        log.warning("ollama research turn: malformed /api/chat response: %s", exc)
        return None

    message = data.get("message") if isinstance(data, dict) else None
    if not isinstance(message, dict):
        log.warning("ollama research turn: /api/chat response had no 'message' object")
        return None
    messages.append(message)

    tool_calls = _tool_calls_from_message(message)[:max_calls]
    if not tool_calls:
        # Fix round 1: the model chose not to research (or the backend doesn't surface tool
        # support) — a valid outcome, but NOT one worth a second /api/chat call over. The
        # assistant's reply here was generated with no `format` constraint, so on a full
        # multi-candidate prompt it can run to ~1.7-2k unconstrained tokens (close to or past
        # `tool_research_timeout_seconds`), and feeding it back as a trailing assistant turn to
        # the final `format`-constrained call risked Ollama treating it as a prefill. Returning
        # `None` sends the caller straight to the well-tested single-shot `_generate` path
        # (schema-constrained from message 1) instead of paying for a second, likely-wasted
        # call — the NEWS block is still in that prompt either way.
        log.debug("ollama research turn: model made no tool_calls — skipping to single-shot")
        return None

    next_id = _next_news_id(prompt)
    for call in tool_calls:
        if _call_name(call) != "search_news":
            continue
        args = _call_args(call)
        query = args.get("query")
        if not query:
            continue
        days = args.get("days") or 7
        try:
            results = get_news_search_provider().search(str(query), days=int(days), limit=5)
        except Exception as exc:  # noqa: BLE001 — one tool call's failure must not abort research
            log.warning("ollama research turn: search_news(%r) failed: %s", query, exc)
            results = []
        lines = [f"N{next_id + i} {item.title[:140]}" for i, item in enumerate(results)]
        next_id += len(results)
        messages.append({"role": "tool", "content": "\n".join(lines) if lines else "(no results)"})

    return messages
