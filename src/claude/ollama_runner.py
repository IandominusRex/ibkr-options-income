"""Local-LLM (Ollama) backend — mirrors `runner.py`'s interface.

Calls a local `ollama serve` instance's `/api/generate` endpoint with `format: "json"` so the
model's output is grammar-constrained to valid JSON, then runs the same `ClaudeReview` /
`RollReview` validation as the `claude -p` path (`src/claude/parser.py`). Any failure —
connection refused, timeout, invalid JSON, schema mismatch — returns the same fail-soft
empty/None values as `runner.py`, so callers (and the fence) don't care which backend served
the request. Selected via `config/settings.yaml → claude.backend` ("ollama" or
"cli_then_ollama"); see `runner.py` for the dispatcher.
"""

from __future__ import annotations

import logging

import httpx

from src.claude.parser import (
    parse_ollama_journal_output,
    parse_ollama_review_output,
    parse_ollama_roll_output,
    parse_ollama_skill_proposal,
)
from src.claude.prompts.eod import build_eod_prompt
from src.claude.prompts.roll import build_roll_prompt
from src.claude.prompts.strategist import build_prompt
from src.common.config import get_config
from src.common.schemas import (
    AccountSnapshot,
    ClaudeReview,
    EODSummary,
    MarketConditions,
    OptionQuote,
    PositionSnapshot,
    RollAlert,
    RollReview,
    SkillProposal,
    TradeCandidate,
)

log = logging.getLogger(__name__)


def _generate(prompt: str, cfg: object) -> str | None:
    """POST to Ollama's `/api/generate`. Returns the model's response text, or None on failure.

    `think: False` disables hybrid-reasoning models' (e.g. qwen3) <think> traces — they're slow
    and tend to fight the `format: "json"` grammar constraint. Ollama ignores the field for
    models that don't support it. `num_ctx` is raised from Ollama's 4096 default because the
    strategist prompt (universe context + history + active skills) routinely exceeds it.
    """
    url = f"{cfg.ollama_host.rstrip('/')}/api/generate"  # type: ignore[attr-defined]
    body = {
        "model": cfg.ollama_model,  # type: ignore[attr-defined]
        "prompt": prompt,
        "format": "json",
        "stream": False,
        "think": False,
        "options": {"temperature": 0.2, "num_ctx": 8192},
    }
    try:
        resp = httpx.post(url, json=body, timeout=cfg.ollama_timeout_seconds)  # type: ignore[attr-defined]
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        log.warning("ollama: request to %s failed: %s", url, exc)
        return None

    try:
        return resp.json()["response"]
    except (ValueError, KeyError) as exc:
        log.warning("ollama: malformed response envelope: %s", exc)
        return None


def review_candidates(
    candidates: list[TradeCandidate],
    account: AccountSnapshot,
    history: list | None = None,
    market_conditions: MarketConditions | None = None,
    spot_prices: dict[str, float] | None = None,
) -> list[ClaudeReview]:
    """Local-model equivalent of `runner.review_candidates`. Returns [] on any failure."""
    cfg = get_config().claude

    if not cfg.enabled:
        log.info("ollama: disabled by config — skipping review")
        return []

    if not candidates:
        log.info("ollama: no candidates to review")
        return []

    prompt = build_prompt(
        candidates,
        account,
        history=history,
        market_conditions=market_conditions,
        spot_prices=spot_prices,
    )

    raw = _generate(prompt, cfg)
    if raw is None:
        return []

    reviews = parse_ollama_review_output(raw)
    if not reviews:
        log.warning("ollama: output parsed to empty list")
    return reviews


def review_roll(alert: RollAlert, pos: PositionSnapshot, quote: OptionQuote) -> RollReview | None:
    """Local-model equivalent of `runner.review_roll`. Returns None on any failure."""
    cfg = get_config().claude

    if not cfg.enabled:
        log.info("ollama: disabled by config — skipping roll review")
        return None

    prompt = build_roll_prompt(alert, pos, quote)

    raw = _generate(prompt, cfg)
    if raw is None:
        return None

    review = parse_ollama_roll_output(raw)
    if review is None:
        log.warning("ollama roll: unparseable output")
    return review


def write_journal_narrative(summary: EODSummary) -> str | None:
    """Local-model equivalent of `runner.write_journal_narrative`. Returns None on failure."""
    cfg = get_config().claude

    if not cfg.enabled:
        log.info("ollama: disabled by config — skipping EOD journal")
        return None

    prompt = build_eod_prompt(summary)

    raw = _generate(prompt, cfg)
    if raw is None:
        return None

    narrative = parse_ollama_journal_output(raw)
    if narrative is None:
        log.warning("ollama eod: unparseable output")
    return narrative


def propose_skill(prompt: str) -> SkillProposal | None:
    """Local-model equivalent of the CLI skill-proposal path. Returns None on any failure.

    `prompt` is pre-built by `proposer.build_proposal_prompt` — identical regardless of
    backend. Unlike the CLI path there's no outer `{"result": ...}` envelope to unwrap.
    """
    cfg = get_config().claude

    if not cfg.enabled:
        log.info("ollama: disabled by config — skipping skill proposal")
        return None

    raw = _generate(prompt, cfg)
    if raw is None:
        return None

    proposal = parse_ollama_skill_proposal(raw)
    if proposal is None:
        log.warning("ollama skills: unparseable output")
    return proposal
