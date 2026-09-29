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

from src.claude import ollama_tools
from src.claude.news_context import news_block_for_candidates
from src.claude.parser import (
    parse_ollama_journal_output,
    parse_ollama_review_output,
    parse_ollama_roll_output,
)
from src.claude.prompts.eod import build_eod_prompt
from src.claude.prompts.roll import build_roll_prompt
from src.claude.prompts.strategist import build_prompt
from src.common.config import get_config
from src.common.schemas import (
    AccountSnapshot,
    ClaudeReview,
    EODSummary,
    FundamentalStats,
    IVStats,
    MarketConditions,
    OptionQuote,
    PositionSnapshot,
    RollAlert,
    RollReview,
    TechnicalStats,
    TradeCandidate,
)

AnalyticsMap = dict[str, tuple[IVStats, TechnicalStats, FundamentalStats]]

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Structured output (Task 10) — a JSON Schema for `{"reviews": [ClaudeReview-shaped, ...]}`.
# Ollama's `format` accepts a JSON Schema (not just the string "json") and grammar-constrains
# every generated token to match it, which is far more reliable than `format: "json"` alone at
# getting one object per requested candidate with the exact field names/types the parser
# expects — the old "always says wait" / dropped-candidate behaviour traced back to the model
# improvising shape under the unconstrained mode. `_generate` defaults to this for the review
# path; roll/EOD calls pass their own schema (or the bare `"json"` string) since their payload
# is a single object the shared parser already tolerates either way.
# ---------------------------------------------------------------------------
_REVIEW_ITEM = {
    "type": "object",
    "properties": {
        "candidate_id": {"type": "string"},
        "priority": {"type": "integer"},
        "recommendation": {"type": "string", "enum": ["sell", "wait", "skip"]},
        "why_attractive": {"type": "string"},
        "risks": {"type": "string"},
        "tradeoffs": {"type": "string"},
        "assignment_considerations": {"type": "string"},
        "rolling_considerations": {"type": "string"},
        "summary": {"type": "string"},
        "evidence": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number"},
    },
    "required": [
        "candidate_id",
        "priority",
        "recommendation",
        "why_attractive",
        "risks",
        "tradeoffs",
        "assignment_considerations",
        "summary",
        "evidence",
    ],
}
REVIEW_SCHEMA = {
    "type": "object",
    "properties": {"reviews": {"type": "array", "items": _REVIEW_ITEM}},
    "required": ["reviews"],
}

# ---------------------------------------------------------------------------
# Circuit breaker — suppresses per-cycle noise when Ollama is persistently broken
# ---------------------------------------------------------------------------
# After _CIRCUIT_THRESHOLD consecutive failures (connection error OR unparseable
# output), the circuit opens. Subsequent calls return empty immediately with only a
# DEBUG trace. The circuit resets on the first successful parse, logging a recovery
# WARNING so the operator knows the model is healthy again.
_CIRCUIT_THRESHOLD = 3
_consecutive_failures: int = 0
_circuit_open: bool = False


def _record_failure() -> None:
    global _consecutive_failures, _circuit_open
    _consecutive_failures += 1
    if not _circuit_open and _consecutive_failures >= _CIRCUIT_THRESHOLD:
        _circuit_open = True
        log.warning(
            "ollama: %d consecutive failures — circuit open, suppressing per-cycle warnings"
            " until the model recovers (check `ollama serve` and the model JSON output)",
            _consecutive_failures,
        )


def _record_success() -> None:
    global _consecutive_failures, _circuit_open
    if _consecutive_failures > 0:
        log.warning("ollama: recovered after %d consecutive failure(s)", _consecutive_failures)
    _consecutive_failures = 0
    _circuit_open = False


def probe_ollama() -> tuple[bool, str]:
    """Check the Ollama backend is reachable and the configured model is pulled.

    Hits `/api/tags` (cheap, no model load) and confirms `ollama_model` is among the
    installed models. Returns `(ok, message)` and never raises — every failure mode
    (server down, malformed response, model not pulled) is reported as `(False, msg)`.
    Callers should gate on `cfg.backend` first; this is only meaningful when a backend
    actually uses Ollama. Used by the launcher and healthcheck so a missing local model
    surfaces up front instead of silently degrading to the deterministic-only path.
    """
    cfg = get_config().claude
    host = cfg.ollama_host.rstrip("/")
    try:
        resp = httpx.get(f"{host}/api/tags", timeout=5.0)
        resp.raise_for_status()
        models = [m.get("name", "") for m in resp.json().get("models", [])]
    except httpx.HTTPError as exc:
        return False, f"Ollama not reachable at {host} ({exc}) — start Ollama.app or `ollama serve`"
    except (ValueError, KeyError, TypeError) as exc:
        return False, f"Ollama returned a malformed /api/tags response: {exc}"

    want = cfg.ollama_model
    # Ollama lists models as "name:tag". Match an exact entry, or — when the configured
    # value omits a tag — any entry sharing the base name.
    if any(m == want or m.split(":")[0] == want for m in models):
        return True, f"reachable at {host}, model '{want}' available"
    available = ", ".join(m for m in models if m) or "(none installed)"
    return False, (
        f"reachable at {host} but model '{want}' is not pulled "
        f"(run `ollama pull {want}`); installed: {available}"
    )


def _generate(prompt: str, cfg: object, schema: dict | str | None = REVIEW_SCHEMA) -> str | None:
    """POST to Ollama's `/api/generate`. Returns the model's response text, or None on failure.

    `format` grammar-constrains the model's output to `schema`. Defaults to `REVIEW_SCHEMA` — a
    JSON Schema for `{"reviews": [...]}` — since the review path is the dominant caller and
    schema-constrained output (Ollama >=0.5) is materially more reliable than the bare
    `format: "json"` mode at producing one object per requested candidate with the exact field
    names/types the parser expects. Roll and EOD callers pass their own schema, or `"json"` (the
    prior unconstrained-shape mode) since their payload is a single object the shared parser
    already tolerates.

    `think: False` disables hybrid-reasoning models' (e.g. qwen3) <think> traces — they're slow
    and tend to fight the JSON/schema grammar constraint. Ollama ignores the field for
    models that don't support it. `num_ctx` is raised from Ollama's 4096 default because the
    strategist prompt (universe context + history + active skills) plus the generated JSON
    routinely exceeds it; an undersized window silently truncates the prompt and/or the output.
    All three knobs (`num_ctx`, `keep_alive`, `temperature`) are config-tunable — see ClaudeCfg.
    """
    url = f"{cfg.ollama_host.rstrip('/')}/api/generate"  # type: ignore[attr-defined]
    body = {
        "model": cfg.ollama_model,  # type: ignore[attr-defined]
        "prompt": prompt,
        "format": schema,
        "stream": False,
        "think": False,
        "keep_alive": cfg.ollama_keep_alive,  # type: ignore[attr-defined]
        "options": {
            "temperature": cfg.ollama_temperature,  # type: ignore[attr-defined]
            "num_ctx": cfg.ollama_num_ctx,  # type: ignore[attr-defined]
        },
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


def _generate_chat(
    messages: list[dict], cfg: object, schema: dict | str = REVIEW_SCHEMA
) -> str | None:
    """POST accumulated chat *messages* to `/api/chat` for the final structured review call —
    used only after a successful `ollama_tools.research_turn` (Task 11). Unlike `_generate`
    (`/api/generate`, a single prompt string), this carries the research turn's message history
    and, critically, **no** `tools` — the model must answer, not keep researching. Returns the
    assistant message's `content` string, or None on failure (the caller falls back to the
    single-shot `_generate` path).
    """
    url = f"{cfg.ollama_host.rstrip('/')}/api/chat"  # type: ignore[attr-defined]
    body = {
        "model": cfg.ollama_model,  # type: ignore[attr-defined]
        "messages": messages,
        "format": schema,
        "stream": False,
        "think": False,
        "keep_alive": cfg.ollama_keep_alive,  # type: ignore[attr-defined]
        "options": {
            "temperature": cfg.ollama_temperature,  # type: ignore[attr-defined]
            "num_ctx": cfg.ollama_num_ctx,  # type: ignore[attr-defined]
        },
    }
    try:
        resp = httpx.post(url, json=body, timeout=cfg.ollama_timeout_seconds)  # type: ignore[attr-defined]
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        log.warning("ollama: request to %s failed: %s", url, exc)
        return None

    try:
        return resp.json()["message"]["content"]
    except (ValueError, KeyError, TypeError) as exc:
        log.warning("ollama: malformed /api/chat response envelope: %s", exc)
        return None


def review_candidates(
    candidates: list[TradeCandidate],
    account: AccountSnapshot,
    history: list | None = None,
    market_conditions: MarketConditions | None = None,
    spot_prices: dict[str, float] | None = None,
    sector_context: str | None = None,
    single_ticker: bool = False,
    analytics: AnalyticsMap | None = None,
) -> list[ClaudeReview]:
    """Local-model equivalent of `runner.review_candidates`. Returns [] on any failure."""
    cfg = get_config().claude

    if not cfg.enabled:
        log.info("ollama: disabled by config — skipping review")
        return []

    if _circuit_open:
        log.debug("ollama: circuit open — skipping review")
        return []

    if not candidates:
        log.info("ollama: no candidates to review")
        return []

    # Task 11 — news-grounded review. `tool_research_enabled` is the single switch for both the
    # static NEWS block and the bounded tool-calling research turn below (SETUP.md documents
    # `claude.tool_research_enabled: false` as how to fully disable the feature and revert to
    # Task 10's single-shot behaviour). Compared with `is True` rather than a bare truthy check
    # so a test double that leaves this attribute unset (a plain MagicMock auto-creates a
    # truthy child attribute) defaults OFF like the real `ClaudeCfg` default would only if a
    # test explicitly opts in — the production config always holds an exact `bool`.
    research_enabled = cfg.tool_research_enabled is True

    news_block = ""
    if research_enabled:
        news_block, _news_index = news_block_for_candidates(
            candidates,
            per_symbol=cfg.news_per_symbol,
            days=cfg.news_days,
            max_items=cfg.news_max_items,
        )

    prompt = build_prompt(
        candidates,
        account,
        history=history,
        market_conditions=market_conditions,
        spot_prices=spot_prices,
        sector_context=sector_context,
        single_ticker=single_ticker,
        analytics=analytics,
        news_block=news_block or None,
    )

    raw: str | None = None
    if research_enabled:
        try:
            messages = ollama_tools.research_turn(prompt, cfg)
        except Exception as exc:  # noqa: BLE001 — the research turn must never break a review
            log.warning("ollama: research turn raised %s — falling back to single-shot", exc)
            messages = None
        if messages is not None:
            raw = _generate_chat(messages, cfg)
            if raw is None:
                log.warning("ollama: research-turn final call failed — falling back to single-shot")

    if raw is None:
        raw = _generate(prompt, cfg)
    if raw is None:
        _record_failure()
        return []

    reviews = parse_ollama_review_output(raw, [c.candidate_id for c in candidates])
    if not reviews:
        log.warning("ollama: output parsed to empty list")
        _record_failure()
    else:
        _record_success()
    return reviews


def review_roll(alert: RollAlert, pos: PositionSnapshot, quote: OptionQuote) -> RollReview | None:
    """Local-model equivalent of `runner.review_roll`. Returns None on any failure."""
    cfg = get_config().claude

    if not cfg.enabled:
        log.info("ollama: disabled by config — skipping roll review")
        return None

    if _circuit_open:
        log.debug("ollama: circuit open — skipping roll review")
        return None

    prompt = build_roll_prompt(alert, pos, quote)

    raw = _generate(prompt, cfg, schema="json")
    if raw is None:
        _record_failure()
        return None

    review = parse_ollama_roll_output(raw)
    if review is None:
        log.warning("ollama roll: unparseable output")
        _record_failure()
    else:
        _record_success()
    return review


def write_journal_narrative(summary: EODSummary) -> str | None:
    """Local-model equivalent of `runner.write_journal_narrative`. Returns None on failure."""
    cfg = get_config().claude

    if not cfg.enabled:
        log.info("ollama: disabled by config — skipping EOD journal")
        return None

    if _circuit_open:
        log.debug("ollama: circuit open — skipping EOD journal")
        return None

    prompt = build_eod_prompt(summary)

    raw = _generate(prompt, cfg, schema="json")
    if raw is None:
        _record_failure()
        return None

    narrative = parse_ollama_journal_output(raw)
    if narrative is None:
        log.warning("ollama eod: unparseable output")
        _record_failure()
    else:
        _record_success()
    return narrative
