"""Backend chain for news explanations: claude -p → Ollama (on any claude failure but a timeout),
with a daily call cap (spec §6.5).

Reuses the trading pipeline's hardened CLI invocation (single turn, tool denylist) and the
Ollama /api/generate call with a JSON-schema grammar — never a third copy. Every attempt
counts toward news.llm.max_calls_per_day (ET date), so a flapping CLI cannot burn the cap
twice as fast unnoticed: it is visible in news_state and on GET /news/status.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Literal, NamedTuple
from zoneinfo import ZoneInfo

from src.claude.cli import should_fall_back
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


def _cli(prompt: str, prefix: str, cfg: NewsLlmCfg) -> tuple[str | None, str | None]:
    from src.claude import runner
    from src.claude.parser import _unwrap_cli

    ccfg = get_config().claude.model_copy(update={"model": cfg.model})
    return runner._run_cli_outcome(
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


Purpose = Literal["general", "picture", "dossier"]


def _dossier_share(cfg: NewsLlmCfg) -> int:
    """The calls kept for the dossier's prose builds: its own daily cap while it is enabled."""
    dossier = get_config().news.dossier
    return dossier.max_calls_per_day if dossier.enabled else 0


def _general_limit(cfg: NewsLlmCfg) -> int:
    """General calls (card writer, digests, briefs) stop here: the cap less the picture reserve
    and the dossier's own cap, but never below one a day, so a big reserve cannot silence the
    writer."""
    cap = cfg.max_calls_per_day
    return min(cap, max(1, cap - cfg.reserved_for_picture - _dossier_share(cfg)))


def _allowed(day: date, purpose: Purpose, cfg: NewsLlmCfg) -> bool:
    if llm_calls(day) >= cfg.max_calls_per_day:
        return False
    if purpose == "dossier":
        return _dossier_share(cfg) > llm_calls(day, "dossier")
    return purpose != "general" or llm_calls(day, "general") < _general_limit(cfg)


def cap_reached(now: datetime, purpose: Purpose = "general") -> bool:
    return not _allowed(now.astimezone(ET).date(), purpose, get_config().news.llm)


def call_llm(
    prompt: str, *, schema: dict, prefix: str, now: datetime, purpose: Purpose = "general"
) -> LlmResult | None:
    """``purpose`` picks the budget: ``general`` calls stop at ``max_calls_per_day`` less the
    picture reserve and the dossier's own cap, ``dossier`` calls at ``dossier.max_calls_per_day``
    (none while the dossier is disabled), ``picture`` (triage and picture builds) only at the
    total; every purpose stops at the total."""
    cfg = get_config().news.llm
    day = now.astimezone(ET).date()
    for backend in _ORDER[cfg.backend]:
        if not _allowed(day, purpose, cfg):
            log.info(
                "news llm: %s budget reached (cap %d, %d reserved for the picture, %d for "
                "dossiers) — deterministic output only",
                purpose,
                cfg.max_calls_per_day,
                cfg.reserved_for_picture,
                _dossier_share(cfg),
            )
            return None
        incr_llm_calls(day, purpose)
        error: str | None = None
        try:
            if backend == "cli":
                text, error = _cli(prompt, prefix, cfg)
            else:
                text = _ollama(prompt, schema, cfg)
        except Exception:
            log.exception("news llm: %s backend raised", backend)
            text, error = None, "cli_error"
        if text:
            return LlmResult(text, backend)
        if backend == "cli" and not should_fall_back(error):
            return None  # a timeout (or Claude disabled): the budget is spent, skip Ollama
    return None
