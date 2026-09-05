"""Anthropic Messages API backend for the research summary.

Uses ``httpx`` directly (no ``anthropic`` SDK dependency) so the web extra stays light.
The prompt is built by ``prompt.py`` and parsed by ``claude_cli.parse_summary`` — the
contract and the parser are genuinely shared across backends.

Fail-soft: a missing API key logs once and returns ``None``; a timeout or malformed
response returns ``None``. The page renders fully without a summary in every case.
"""

from __future__ import annotations

import logging

import httpx

from src.common.config import get_config
from src.research.summary.claude_cli import parse_summary
from src.research.summary.context import ResearchContext
from src.research.summary.prompt import build_prompt
from src.research.summary.protocol import Summary

log = logging.getLogger(__name__)

_API_URL = "https://api.anthropic.com/v1/messages"
_API_VERSION = "2023-06-01"
_missing_key_logged = False


class AnthropicSummaryProvider:
    """Calls Anthropic's Messages API. ``None`` on any failure."""

    @property
    def _model_name(self) -> str:
        return get_config().research.summary.model or "claude-3-5-sonnet-latest"

    def generate(self, context: ResearchContext) -> Summary | None:
        global _missing_key_logged
        cfg = get_config()
        key = cfg.secrets.anthropic_api_key
        if not key:
            if not _missing_key_logged:
                log.warning("summary/anthropic: ANTHROPIC_API_KEY not set — skipping")
                _missing_key_logged = True
            return None

        prompt = build_prompt(context)
        body = {
            "model": self._model_name,
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": prompt}],
        }
        headers = {
            "x-api-key": key,
            "anthropic-version": _API_VERSION,
            "content-type": "application/json",
        }
        try:
            resp = httpx.post(
                _API_URL,
                json=body,
                headers=headers,
                timeout=cfg.research.summary.timeout_seconds,
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            log.warning("summary/anthropic: request failed: %s", exc)
            return None

        raw = self._extract_text(resp.json())
        if raw is None:
            log.warning("summary/anthropic: malformed response envelope")
            return None
        return parse_summary(raw, model=self._model_name, data_as_of=context.data_as_of)

    @staticmethod
    def _extract_text(envelope: object) -> str | None:
        """Anthropic wraps the text in ``content[0].text``. Be defensive about shape."""
        if not isinstance(envelope, dict):
            return None
        content = envelope.get("content")
        if isinstance(content, list) and content:
            first = content[0]
            if isinstance(first, dict):
                return first.get("text")
        return None


__all__ = ["AnthropicSummaryProvider"]
