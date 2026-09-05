"""The ``claude_cli`` summary backend.

Reuses ``src/claude/runner.py``'s subprocess and timeout handling rather than a second
CLI invoker. The prompt is built by ``src/research/summary/prompt.py`` and the output is
parsed by ``parse_summary`` (shared with every other backend — only transport differs).

Fail-soft contract: a missing CLI, a timeout, an unparseable response, or a missing
required field all return ``None`` so the page renders fully without a summary.
Enrichment, never a dependency — exactly how ``runner.py`` behaves today.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime

from pydantic import ValidationError

from src.claude.runner import _build_cmd, _run_cli
from src.common.config import get_config
from src.research.summary.context import ResearchContext
from src.research.summary.prompt import build_prompt
from src.research.summary.protocol import Summary

log = logging.getLogger(__name__)


def parse_summary(raw: str, *, model: str, data_as_of: datetime) -> Summary | None:
    """Parse model output into a ``Summary``. Returns ``None`` on any failure.

    Tolerates JSON wrapped in prose or a ```json fenced block — models sometimes wrap
    their output despite the contract. A missing required field (``thesis``) or a
    validation error returns ``None`` rather than a partial Summary, so a bad parse
    renders the page without a summary instead of printing garbage.
    """
    payload = _extract_json(raw)
    if payload is None:
        return None
    if not isinstance(payload, dict) or "thesis" not in payload:
        return None
    try:
        return Summary(
            thesis=str(payload["thesis"]),
            bull_points=list(payload.get("bull_points") or []),
            bear_points=list(payload.get("bear_points") or []),
            watch_items=list(payload.get("watch_items") or []),
            caveats=list(payload.get("caveats") or []),
            model=model,
            data_as_of=data_as_of,
        )
    except (ValidationError, TypeError, ValueError) as exc:
        log.warning("summary: failed to validate parsed summary: %s", exc)
        return None


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _extract_json(raw: str) -> object | None:
    """Best-effort extraction of the first JSON object from raw model output."""
    if not raw:
        return None
    text = raw.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    fence = _JSON_FENCE_RE.search(text)
    if fence:
        try:
            return json.loads(fence.group(1))
        except json.JSONDecodeError:
            pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    return None


class ClaudeCliSummaryProvider:
    """Shells out to ``claude -p`` reusing ``src/claude/runner.py``'s command shape."""

    @property
    def _model_name(self) -> str:
        return get_config().research.summary.model or "claude-cli"

    def generate(self, context: ResearchContext) -> Summary | None:
        cfg = get_config().research.summary
        claude_cfg = get_config().claude
        if not claude_cfg.enabled:
            log.info("summary: claude disabled by config — skipping")
            return None
        prompt = build_prompt(context)
        model = self._model_name
        data_as_of = context.data_as_of

        def _parse(stdout: str) -> Summary | None:
            raw = self._unwrap_envelope(stdout)
            if raw is None:
                return None
            return parse_summary(raw, model=model, data_as_of=data_as_of)

        # Reuses runner.py's subprocess retry loop and cost logging — the same
        # `--output-format json` hardening flags (cli_command, max_turns, model pin,
        # disallowedTools) as the strategist review, but the summary's own
        # research.summary.timeout_seconds budget and a single attempt (enrichment
        # triggered live from a page load should fail fast, not retry).
        return _run_cli(
            prompt,
            "summary claude_cli",
            _parse,
            cmd=_build_cmd(claude_cfg),
            timeout_seconds=cfg.timeout_seconds,
            max_retries=0,
        )

    @staticmethod
    def _unwrap_envelope(stdout: str) -> str | None:
        """``claude -p --output-format json`` wraps the answer in an envelope. The
        model's own JSON is inside ``.result``. Be tolerant if the envelope is absent.
        """
        if not stdout:
            return None
        try:
            env = json.loads(stdout)
        except json.JSONDecodeError:
            return stdout
        if isinstance(env, dict):
            result = env.get("result")
            if isinstance(result, str):
                return result
        return stdout


__all__ = ["ClaudeCliSummaryProvider", "parse_summary"]
