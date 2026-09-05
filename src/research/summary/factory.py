"""Select a SummaryProvider by ``research.summary.backend`` config.

Mirrors the pattern in ``src/claude/runner.py``: a config string picks the active
backend, every backend fails soft to a no-summary page, and the fence holds regardless
of which backend served the request.
"""

from __future__ import annotations

from functools import lru_cache

from src.common.config import get_config
from src.research.summary.protocol import SummaryProvider


@lru_cache(maxsize=1)
def get_summary_provider() -> SummaryProvider:
    """Return the configured summary backend, imported lazily.

    Importing a backend module is deferred to this call so a missing optional
    dependency (``anthropic``, ``openai``) does not break startup for users on a
    different backend. A backend that cannot initialise (missing key, library absent)
    returns ``None`` from ``generate`` rather than raising.
    """
    backend = get_config().research.summary.backend

    if backend == "claude_cli":
        from src.research.summary.claude_cli import ClaudeCliSummaryProvider

        return ClaudeCliSummaryProvider()
    if backend == "anthropic":
        from src.research.summary.anthropic import AnthropicSummaryProvider

        return AnthropicSummaryProvider()
    if backend == "openai":
        from src.research.summary.openai import OpenAISummaryProvider

        return OpenAISummaryProvider()
    if backend == "ollama":
        from src.research.summary.ollama import OllamaSummaryProvider

        return OllamaSummaryProvider()

    raise ValueError(f"unknown research.summary.backend: {backend!r}")


__all__ = ["get_summary_provider"]
