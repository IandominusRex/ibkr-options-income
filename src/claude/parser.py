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

from src.common.schemas import ClaudeReview, RollReview, SkillProposal

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


def parse_claude_output(raw: str) -> list[ClaudeReview]:
    """Parse raw claude -p JSON output → list[ClaudeReview]. Returns [] on any failure."""
    if not raw or not raw.strip():
        log.warning("claude: empty output")
        return []

    # Step 1: parse outer envelope
    try:
        envelope = json.loads(raw)
    except json.JSONDecodeError as exc:
        log.warning("claude: outer JSON parse failed: %s", exc)
        return []

    if not isinstance(envelope, dict):
        log.warning("claude: outer envelope is not a dict")
        return []

    # Step 2: extract assistant text from envelope
    inner_text = envelope.get("result")
    if inner_text is None:
        log.warning("claude: envelope missing 'result' key; keys=%s", list(envelope.keys()))
        return []

    if not isinstance(inner_text, str):
        # Already parsed (shouldn't happen but handle gracefully)
        inner_text = json.dumps(inner_text)

    # Step 3: strip markdown fences if present
    inner_text = _strip_fences(inner_text)

    # Step 4: parse inner JSON (tolerating surrounding prose)
    try:
        payload = _loads_lenient(inner_text)
    except json.JSONDecodeError as exc:
        log.warning("claude: inner JSON parse failed: %s", exc)
        return []

    # Step 5: normalise to list
    if isinstance(payload, dict):
        payload = [payload]

    if not isinstance(payload, list):
        log.warning("claude: inner payload is not a list or dict")
        return []

    # Step 6: validate each item against ClaudeReview schema; collect valid, skip invalid
    reviews: list[ClaudeReview] = []
    for item in payload:
        try:
            reviews.append(ClaudeReview.model_validate(item))
        except (ValidationError, TypeError) as exc:
            log.warning("claude: item failed validation (skipping): %s — item=%s", exc, item)

    if not reviews and payload:
        log.warning("claude: all %d item(s) failed validation", len(payload))
    return reviews


def parse_roll_output(raw: str) -> RollReview | None:
    """Parse claude -p roll-review output → RollReview. Returns None on any failure."""
    if not raw or not raw.strip():
        log.warning("claude roll: empty output")
        return None

    try:
        envelope = json.loads(raw)
    except json.JSONDecodeError as exc:
        log.warning("claude roll: outer JSON parse failed: %s", exc)
        return None

    if not isinstance(envelope, dict):
        log.warning("claude roll: outer envelope is not a dict")
        return None

    inner_text = envelope.get("result")
    if inner_text is None:
        log.warning("claude roll: envelope missing 'result' key")
        return None

    if not isinstance(inner_text, str):
        inner_text = json.dumps(inner_text)

    inner_text = _strip_fences(inner_text)

    try:
        payload = _loads_lenient(inner_text)
    except json.JSONDecodeError as exc:
        log.warning("claude roll: inner JSON parse failed: %s", exc)
        return None

    if isinstance(payload, list) and payload:
        payload = payload[0]

    if not isinstance(payload, dict):
        log.warning("claude roll: inner payload is not a dict")
        return None

    try:
        return RollReview.model_validate(payload)
    except (ValidationError, TypeError) as exc:
        log.warning("claude roll: validation failed: %s — payload=%s", exc, payload)
        return None


def _parse_review_payload(text: str) -> list[ClaudeReview]:
    """Shared inner-payload parsing for review items, given already-unwrapped text."""
    text = _strip_fences(text)
    try:
        payload = _loads_lenient(text)
    except json.JSONDecodeError as exc:
        log.warning("ollama: inner JSON parse failed: %s", exc)
        return []

    if isinstance(payload, dict):
        payload = [payload]
    if not isinstance(payload, list):
        log.warning("ollama: inner payload is not a list or dict")
        return []

    reviews: list[ClaudeReview] = []
    for item in payload:
        try:
            reviews.append(ClaudeReview.model_validate(item))
        except (ValidationError, TypeError) as exc:
            log.warning("ollama: item failed validation (skipping): %s — item=%s", exc, item)

    if not reviews and payload:
        log.warning("ollama: all %d item(s) failed validation", len(payload))
    return reviews


def parse_ollama_review_output(raw: str) -> list[ClaudeReview]:
    """Parse Ollama's `response` text (already JSON, per `format: "json"`) → list[ClaudeReview].

    Unlike `parse_claude_output`, there is no outer CLI envelope to unwrap — `raw` is the
    model's response text directly. Returns [] on any failure.
    """
    if not raw or not raw.strip():
        log.warning("ollama: empty output")
        return []
    return _parse_review_payload(raw)


def parse_ollama_roll_output(raw: str) -> RollReview | None:
    """Parse Ollama's `response` text → RollReview. Returns None on any failure."""
    if not raw or not raw.strip():
        log.warning("ollama roll: empty output")
        return None

    text = _strip_fences(raw)
    try:
        payload = _loads_lenient(text)
    except json.JSONDecodeError as exc:
        log.warning("ollama roll: inner JSON parse failed: %s", exc)
        return None

    if isinstance(payload, list) and payload:
        payload = payload[0]
    if not isinstance(payload, dict):
        log.warning("ollama roll: inner payload is not a dict")
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

    text = _strip_fences(raw)
    try:
        payload = _loads_lenient(text)
    except json.JSONDecodeError as exc:
        log.warning("ollama eod: inner JSON parse failed: %s", exc)
        return None

    if isinstance(payload, list) and payload:
        payload = payload[0]
    if not isinstance(payload, dict):
        log.warning("ollama eod: inner payload is not a dict")
        return None

    narrative = payload.get("narrative")
    if not narrative or not isinstance(narrative, str):
        log.warning("ollama eod: missing or non-string 'narrative' field")
        return None

    return narrative.strip()


def parse_ollama_skill_proposal(raw: str) -> SkillProposal | None:
    """Parse Ollama's `response` text → SkillProposal. Returns None on any failure.

    Unlike the CLI proposer (`_parse_proposal` in `proposer.py`), there is no outer
    `{"result": "..."}` envelope to unwrap — `raw` is the model's response text directly.
    """
    if not raw or not raw.strip():
        log.warning("ollama skills: empty output")
        return None

    text = _strip_fences(raw)
    try:
        payload = _loads_lenient(text)
    except json.JSONDecodeError as exc:
        log.warning("ollama skills: inner JSON parse failed: %s", exc)
        return None

    if isinstance(payload, list) and payload:
        payload = payload[0]
    if not isinstance(payload, dict):
        log.warning("ollama skills: inner payload is not a dict")
        return None

    try:
        return SkillProposal.model_validate(payload)
    except (ValidationError, TypeError) as exc:
        log.warning("ollama skills: validation failed: %s — payload=%s", exc, payload)
        return None


def parse_journal_output(raw: str) -> str | None:
    """Parse claude -p EOD journal output → narrative string. Returns None on any failure."""
    if not raw or not raw.strip():
        log.warning("claude eod: empty output")
        return None

    try:
        envelope = json.loads(raw)
    except json.JSONDecodeError as exc:
        log.warning("claude eod: outer JSON parse failed: %s", exc)
        return None

    if not isinstance(envelope, dict):
        log.warning("claude eod: outer envelope is not a dict")
        return None

    inner_text = envelope.get("result")
    if inner_text is None:
        log.warning("claude eod: envelope missing 'result' key")
        return None

    if not isinstance(inner_text, str):
        inner_text = json.dumps(inner_text)

    inner_text = _strip_fences(inner_text)

    try:
        payload = _loads_lenient(inner_text)
    except json.JSONDecodeError as exc:
        log.warning("claude eod: inner JSON parse failed: %s", exc)
        return None

    if isinstance(payload, list) and payload:
        payload = payload[0]

    if not isinstance(payload, dict):
        log.warning("claude eod: inner payload is not a dict")
        return None

    narrative = payload.get("narrative")
    if not narrative or not isinstance(narrative, str):
        log.warning("claude eod: missing or non-string 'narrative' field")
        return None

    return narrative.strip()
