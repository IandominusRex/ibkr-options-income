"""OpenAI Chat Completions backend for the research summary.

Uses ``httpx`` directly (no ``openai`` SDK dependency). The prompt and parser are
shared with every other backend — only transport differs.

Fail-soft: a missing API key logs once and returns ``None``; a timeout or malformed
response returns ``None``.
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

_API_URL = "https://api.openai.com/v1/chat/completions"
_missing_key_logged = False


class OpenAISummaryProvider:
    """Calls OpenAI's Chat Completions API. ``None`` on any failure."""

    @property
    def _model_name(self) -> str:
        return get_config().research.summary.model or "gpt-4o-mini"

    def generate(self, context: ResearchContext) -> Summary | None:
        global _missing_key_logged
        cfg = get_config()
        key = cfg.secrets.openai_api_key
        if not key:
            if not _missing_key_logged:
                log.warning("summary/openai: OPENAI_API_KEY not set — skipping")
                _missing_key_logged = True
            return None

        prompt = build_prompt(context)
        body = {
            "model": self._model_name,
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {key}",
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
            log.warning("summary/openai: request failed: %s", exc)
            return None

        raw = self._extract_text(resp.json())
        if raw is None:
            log.warning("summary/openai: malformed response envelope")
            return None
        return parse_summary(raw, model=self._model_name, data_as_of=context.data_as_of)

    @staticmethod
    def _extract_text(envelope: object) -> str | None:
        """OpenAI wraps the text in ``choices[0].message.content``."""
        if not isinstance(envelope, dict):
            return None
        choices = envelope.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                msg = first.get("message")
                if isinstance(msg, dict):
                    return msg.get("content")
        return None


__all__ = ["OpenAISummaryProvider"]
