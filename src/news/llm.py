"""Backend chain for news explanations: claude -p → Ollama, with a daily call cap (spec §6.5).

Reuses the trading pipeline's hardened CLI invocation (single turn, tool denylist) and the
Ollama /api/generate call with a JSON-schema grammar — never a third copy. Every attempt
counts toward news.llm.max_calls_per_day (ET date), so a flapping CLI cannot burn the cap
twice as fast unnoticed: it is visible in news_state and on GET /news/status.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Literal, NamedTuple
from zoneinfo import ZoneInfo

from src.common.config import NewsLlmCfg, get_config
from src.news.store.state import incr_llm_calls, llm_calls

log = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")
_ORDER: dict[str, tuple[Literal["cli", "ollama"], ...]] = {
    "cli": ("cli",),
    "ollama": ("ollama",),
    "cli_then_ollama": ("cli", "ollama"),
}


class LlmResult(NamedTuple):
    text: str
    backend: Literal["cli", "ollama"]


def _cli(prompt: str, prefix: str, cfg: NewsLlmCfg) -> str | None:
    from src.claude import runner
    from src.claude.parser import _unwrap_cli

    ccfg = get_config().claude.model_copy(update={"model": cfg.model})
    return runner._run_cli(
        prompt,
        prefix,
        lambda out: _unwrap_cli(out, prefix),
        cmd=runner._build_cmd(ccfg),
        timeout_seconds=cfg.timeout_seconds,
        max_retries=0,
    )


def _ollama(prompt: str, schema: dict, cfg: NewsLlmCfg) -> str | None:
    from src.claude.ollama_runner import _generate

    ccfg = get_config().claude
    if cfg.ollama_model:
        ccfg = ccfg.model_copy(update={"ollama_model": cfg.ollama_model})
    return _generate(prompt, ccfg, schema, timeout=cfg.timeout_seconds)


def cap_reached(now: datetime) -> bool:
    cfg = get_config().news.llm
    return llm_calls(now.astimezone(ET).date()) >= cfg.max_calls_per_day


def call_llm(prompt: str, *, schema: dict, prefix: str, now: datetime) -> LlmResult | None:
    cfg = get_config().news.llm
    day = now.astimezone(ET).date()
    for backend in _ORDER[cfg.backend]:
        if llm_calls(day) >= cfg.max_calls_per_day:
            log.info(
                "news llm: daily cap %d reached — deterministic cards only", cfg.max_calls_per_day
            )
            return None
        incr_llm_calls(day)
        try:
            text = _cli(prompt, prefix, cfg) if backend == "cli" else _ollama(prompt, schema, cfg)
        except Exception:
            log.exception("news llm: %s backend raised", backend)
            text = None
        if text:
            return LlmResult(text, backend)
    return None
