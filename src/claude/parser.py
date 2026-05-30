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

from src.common.schemas import ClaudeReview, RollReview  # EODSummary not needed here

log = logging.getLogger(__name__)

_FENCE_RE = re.compile(r"^```(?:json)?\s*\n(.*?)\n```\s*$", re.DOTALL)


def _strip_fences(text: str) -> str:
    m = _FENCE_RE.match(text.strip())
    return m.group(1) if m else text.strip()


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

    # Step 4: parse inner JSON
    try:
        payload = json.loads(inner_text)
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
        payload = json.loads(inner_text)
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
        payload = json.loads(inner_text)
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
