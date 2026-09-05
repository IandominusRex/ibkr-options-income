"""Ollama backend for the research summary.

Reuses ``src/claude/ollama_runner.py``'s host and timeout config rather than a second
copy — same ``ollama serve`` daemon on ``localhost:11434`` that the trading pipeline's
local reviewer uses. The prompt and parser are shared with every other backend.

Fail-soft: a connection error, timeout, or malformed response returns ``None``.
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


class OllamaSummaryProvider:
    """Calls a local Ollama instance's ``/api/generate``. ``None`` on any failure."""

    @property
    def _model_name(self) -> str:
        return get_config().claude.ollama_model

    def generate(self, context: ResearchContext) -> Summary | None:
        claude_cfg = get_config().claude
        summary_cfg = get_config().research.summary
        url = f"{claude_cfg.ollama_host.rstrip('/')}/api/generate"
        body = {
            "model": self._model_name,
            "prompt": build_prompt(context),
            "format": "json",
            "stream": False,
            "think": False,
            "keep_alive": claude_cfg.ollama_keep_alive,
            "options": {
                "temperature": claude_cfg.ollama_temperature,
                "num_ctx": claude_cfg.ollama_num_ctx,
            },
        }
        try:
            resp = httpx.post(url, json=body, timeout=summary_cfg.timeout_seconds)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            log.warning("summary/ollama: request to %s failed: %s", url, exc)
            return None

        try:
            raw = resp.json()["response"]
        except (ValueError, KeyError) as exc:
            log.warning("summary/ollama: malformed response envelope: %s", exc)
            return None

        return parse_summary(raw, model=self._model_name, data_as_of=context.data_as_of)


__all__ = ["OllamaSummaryProvider"]
