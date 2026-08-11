"""Parse raw `claude -p --output-format json` output → list[ClaudeReview].

The CLI wraps the assistant reply in an outer envelope:
    {"type": "result", "subtype": "success", "result": "<assistant text>", ...}

The assistant text itself should be a JSON array of ClaudeReview objects, but may
be wrapped in markdown code fences. Every failure mode returns [] — never raises.
"""

from __future__ import annotations

import json
import logging
import re

from pydantic import ValidationError

from src.common.schemas import ClaudeReview, RollReview

log = logging.getLogger(__name__)

_FENCE_RE = re.compile(r"^```(?:json)?\s*\n(.*?)\n```\s*$", re.DOTALL)


def _strip_fences(text: str) -> str:
    m = _FENCE_RE.match(text.strip())
    return m.group(1) if m else text.strip()


def _first_json_span(text: str) -> str | None:
    """Return the first balanced JSON array/object substring, or None.

    Scans for the first '[' or '{' and returns through its matching close,
    respecting string literals and escapes. Lets us recover the payload when
    `claude -p` wraps the JSON in explanatory prose.
    """
    start = next((i for i, ch in enumerate(text) if ch in "[{"), None)
    if start is None:
        return None
    depth = 0
    in_str = False
    esc = False
    for j in range(start, len(text)):
        ch = text[j]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
            if depth == 0:
                return text[start : j + 1]
    return None


def _loads_lenient(text: str) -> object:
    """json.loads, but if the whole string isn't valid JSON, parse the first
    balanced array/object found within it. Raises JSONDecodeError if neither works."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        span = _first_json_span(text)
        if span is None:
            raise
        return json.loads(span)


def _unwrap_cli(raw: str, prefix: str) -> str | None:
    """Unwrap the claude -p JSON envelope; return the fence-stripped inner text or None."""
    if not raw or not raw.strip():
        log.warning("%s: empty output", prefix)
        return None
    try:
        envelope = json.loads(raw)
    except json.JSONDecodeError as exc:
        log.warning("%s: outer JSON parse failed: %s", prefix, exc)
        return None
    if not isinstance(envelope, dict):
        log.warning("%s: outer envelope is not a dict", prefix)
        return None
    inner = envelope.get("result")
    if inner is None:
        log.warning("%s: envelope missing 'result' key; keys=%s", prefix, list(envelope.keys()))
        return None
    return _strip_fences(inner if isinstance(inner, str) else json.dumps(inner))


def _parse_dict_payload(text: str, prefix: str) -> dict | None:
    """Parse fence-stripped text → dict; treat list-of-one as dict. Returns None on failure."""
    try:
        payload = _loads_lenient(text)
    except json.JSONDecodeError as exc:
        log.warning("%s: inner JSON parse failed: %s", prefix, exc)
        return None
    if isinstance(payload, list) and payload:
        payload = payload[0]
    if not isinstance(payload, dict):
        log.warning("%s: inner payload is not a dict", prefix)
        return None
    return payload


def _parse_reviews(text: str, prefix: str) -> list[ClaudeReview]:
    """Parse fence-stripped text → list[ClaudeReview]."""
    text = _strip_fences(text)
    try:
        payload = _loads_lenient(text)
    except json.JSONDecodeError as exc:
        log.warning("%s: inner JSON parse failed: %s", prefix, exc)
        return []
    if isinstance(payload, dict):
        payload = [payload]
    if not isinstance(payload, list):
        log.warning("%s: inner payload is not a list or dict", prefix)
        return []
    reviews: list[ClaudeReview] = []
    for item in payload:
        try:
            reviews.append(ClaudeReview.model_validate(item))
        except (ValidationError, TypeError) as exc:
            log.warning("%s: item failed validation (skipping): %s — item=%s", prefix, exc, item)
    if not reviews and payload:
        log.warning("%s: all %d item(s) failed validation", prefix, len(payload))
    return reviews


def _extract_narrative(payload: dict, prefix: str) -> str | None:
    narrative = payload.get("narrative")
    if not narrative or not isinstance(narrative, str):
        log.warning("%s: missing or non-string 'narrative' field", prefix)
        return None
    return narrative.strip()


def parse_claude_output(raw: str) -> list[ClaudeReview]:
    """Parse raw claude -p JSON output → list[ClaudeReview]. Returns [] on any failure."""
    inner = _unwrap_cli(raw, "claude")
    if inner is None:
        return []
    return _parse_reviews(inner, "claude")


def parse_roll_output(raw: str) -> RollReview | None:
    """Parse claude -p roll-review output → RollReview. Returns None on any failure."""
    inner = _unwrap_cli(raw, "claude roll")
    if inner is None:
        return None
    payload = _parse_dict_payload(inner, "claude roll")
    if payload is None:
        return None
    try:
        return RollReview.model_validate(payload)
    except (ValidationError, TypeError) as exc:
        log.warning("claude roll: validation failed: %s — payload=%s", exc, payload)
        return None


def parse_journal_output(raw: str) -> str | None:
    """Parse claude -p EOD journal output → narrative string. Returns None on any failure."""
    inner = _unwrap_cli(raw, "claude eod")
    if inner is None:
        return None
    payload = _parse_dict_payload(inner, "claude eod")
    return None if payload is None else _extract_narrative(payload, "claude eod")


def parse_ollama_review_output(raw: str) -> list[ClaudeReview]:
    """Parse Ollama's `response` text (already JSON, per `format: "json"`) → list[ClaudeReview].

    Unlike `parse_claude_output`, there is no outer CLI envelope to unwrap — `raw` is the
    model's response text directly. Returns [] on any failure.
    """
    if not raw or not raw.strip():
        log.warning("ollama: empty output")
        return []
    return _parse_reviews(raw, "ollama")


def parse_ollama_roll_output(raw: str) -> RollReview | None:
    """Parse Ollama's `response` text → RollReview. Returns None on any failure."""
    if not raw or not raw.strip():
        log.warning("ollama roll: empty output")
        return None
    payload = _parse_dict_payload(_strip_fences(raw), "ollama roll")
    if payload is None:
        return None
    try:
        return RollReview.model_validate(payload)
    except (ValidationError, TypeError) as exc:
        log.warning("ollama roll: validation failed: %s — payload=%s", exc, payload)
        return None


def parse_ollama_journal_output(raw: str) -> str | None:
    """Parse Ollama's `response` text → narrative string. Returns None on any failure."""
    if not raw or not raw.strip():
        log.warning("ollama eod: empty output")
        return None
    payload = _parse_dict_payload(_strip_fences(raw), "ollama eod")
    return None if payload is None else _extract_narrative(payload, "ollama eod")
