"""Shell out to `claude -p` and return structured ClaudeReview objects.

If the CLI is unavailable, times out, or returns unparseable output, returns []
so the orchestrator can fall back to the deterministic Rules-Engine-approved list.
"""

from __future__ import annotations

import json
import logging
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.claude import cli, ollama_runner
from src.claude.cli import is_usage_limit, log_usage, should_fall_back
from src.claude.dossier_context import load_dossier_block
from src.claude.parser import parse_claude_output, parse_journal_output, parse_roll_output
from src.claude.picture_context import load_picture_block
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

# {symbol: (IVStats, TechnicalStats, FundamentalStats)} — raw analytics passed through to the
# prompt builder so each candidate is annotated with its underlying's signals (enrichment only).
AnalyticsMap = dict[str, tuple[IVStats, TechnicalStats, FundamentalStats]]

log = logging.getLogger(__name__)


def _build_cmd(cfg: object, *, model: str | None = None) -> list[str]:
    """Assemble the hardened `claude` headless command (N3).

    Beyond `--output-format`, this constrains the unattended subprocess so a prompt-injection
    or runaway can't drive tools or the filesystem: a single agentic turn, an explicit tool
    denylist, an optional pinned model, and an optional effort level. All are config-tunable
    (see ClaudeCfg); a falsy value omits the corresponding flag. The flags don't change the JSON envelope, so the
    parser path is unaffected.

    ``claude.slim_context`` (2026-10-15) additionally strips the interactive session's ambient
    context (``cli.build_cmd``); the caller then runs it from ``claude.workdir``
    (``_headless_cwd``). *model* overrides ``cfg.model`` for one call kind (``ClaudeCfg.model_for``).
    """
    chosen = model or cfg.model  # type: ignore[attr-defined]
    if getattr(cfg, "slim_context", False):
        return cli.build_cmd(
            cfg.cli_command,  # type: ignore[attr-defined]
            model=chosen,
            effort=getattr(cfg, "effort", ""),
            disallowed_tools=cfg.disallowed_tools,  # type: ignore[attr-defined]
            max_turns=cfg.max_turns,  # type: ignore[attr-defined]
            output_format=cfg.output_format,  # type: ignore[attr-defined]
            slim=True,
        )
    cmd = [cfg.cli_command, "--output-format", cfg.output_format]  # type: ignore[attr-defined]
    if cfg.max_turns:  # type: ignore[attr-defined]
        cmd += ["--max-turns", str(cfg.max_turns)]  # type: ignore[attr-defined]
    if chosen:
        cmd += ["--model", chosen]
    if getattr(cfg, "effort", ""):
        cmd += ["--effort", cfg.effort]  # type: ignore[attr-defined]
    if cfg.disallowed_tools:  # type: ignore[attr-defined]
        cmd += ["--disallowedTools", cfg.disallowed_tools]  # type: ignore[attr-defined]
    return cmd


def _headless_cwd(cfg: object) -> Path | None:
    """The directory a slim call runs from (``claude.workdir``, created on demand), else None.

    claude walks up from its cwd looking for CLAUDE.md, so this must be outside the repo
    (``ClaudeCfg`` validates that). A directory that cannot be created is logged and the call
    runs from the inherited cwd - heavier, never broken.
    """
    if not getattr(cfg, "slim_context", False):
        return None
    workdir = getattr(cfg, "workdir", "")
    if not workdir:
        return None
    path = Path(workdir).expanduser()
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        log.warning("claude: cannot create workdir %s - running from the inherited cwd", path)
        return None
    return path


def _run_cli_outcome[T](
    prompt: str,
    prefix: str,
    parse_fn: Callable[[str], T | None],
    *,
    cmd: list[str] | None = None,
    timeout_seconds: float | None = None,
    max_retries: int | None = None,
) -> tuple[T | None, str | None]:
    """Shared subprocess retry loop for every CLI-backed enrichment call: roll, EOD
    journal, news, and (M7) the summary layer's ``claude_cli`` backend.

    Retries up to ``max_retries`` on TimeoutExpired or empty/unparseable output;
    returns immediately on FileNotFoundError. Calls _log_cost on success.

    Returns ``(parsed, error)``; ``error`` is ``None`` on success, else one of ``cli_missing``,
    ``timeout``, ``cli_error`` (non-zero exit: a usage limit, auth expiry) or ``bad_envelope``
    (exit 0, unparseable). A timeout in ANY attempt makes the error ``timeout`` (the budget is
    spent). ``cli.should_fall_back`` turns the error into the Ollama-fallback decision.

    ``cmd``/``timeout_seconds``/``max_retries`` default to the ``claude.*`` config
    (roll and the EOD journal, unchanged from before this was parameterised). A caller
    with its own timeout/retry budget — the summary layer uses
    ``research.summary.timeout_seconds`` rather than ``claude.timeout_seconds`` — passes
    its own values so it need not duplicate this subprocess loop.
    """
    cfg = get_config().claude
    cmd = cmd if cmd is not None else _build_cmd(cfg)
    timeout = timeout_seconds if timeout_seconds is not None else cfg.timeout_seconds
    retries = max_retries if max_retries is not None else cfg.max_retries
    error = "cli_error"
    timed_out = False
    cwd = _headless_cwd(cfg)
    for attempt in range(retries + 1):
        try:
            result = subprocess.run(
                cmd, input=prompt, capture_output=True, text=True, timeout=timeout, cwd=cwd
            )
        except subprocess.TimeoutExpired:
            log.warning("%s: timed out (attempt %d)", prefix, attempt + 1)
            timed_out = True
            continue
        except FileNotFoundError:
            log.warning("claude: CLI not found — skipping %s", prefix)
            return None, "cli_missing"
        if result.returncode != 0 and not result.stdout:
            log.warning("%s: rc=%d, no stdout (attempt %d)", prefix, result.returncode, attempt + 1)
            error = "cli_error"
            continue
        if is_usage_limit(result.stdout):
            log.warning("%s: usage limit reached — not retrying", prefix)
            return None, ("timeout" if timed_out else "cli_error")
        parsed = parse_fn(result.stdout)
        if parsed is not None:
            _log_cost(result.stdout, prefix)
            return parsed, None
        log.warning("%s: unparseable output (attempt %d)", prefix, attempt + 1)
        error = "cli_error" if result.returncode != 0 else "bad_envelope"
    log.error("%s: all %d attempt(s) failed", prefix, retries + 1)
    return None, ("timeout" if timed_out else error)


def review_candidates(
    candidates: list[TradeCandidate],
    account: AccountSnapshot,
    market_conditions: MarketConditions | None = None,
    spot_prices: dict[str, float] | None = None,
    sector_context: str | None = None,
    single_ticker: bool = False,
    analytics: AnalyticsMap | None = None,
    picture_block: str | None = None,
    book_block: str | None = None,
    dossier_block: str | None = None,
) -> list[ClaudeReview]:
    """Review candidates via the configured `claude.backend`. Returns [] on any failure.

    "cli" (default): `claude -p` only. "ollama": local model only. "cli_then_ollama": try
    `claude -p`, fall back to the local model when it fails for any reason except a timeout
    (a usage limit, a missing CLI, an error envelope, unparseable output).

    sector_context / single_ticker: forwarded to the prompt builder so a `/scan TICKER` deep-dive
    gets the sector backdrop and the extra plain-English ``summary`` (see strategist.build_prompt).
    analytics: per-symbol raw signals annotated onto each candidate in the prompt (enrichment).
    picture_block / book_block / dossier_block: the shared market picture, the book around the
    reviewed names and the reviewed names' dossier notes, pre-rendered by the scan
    (``picture_context`` / ``book_context`` / ``dossier_context``); all prompt text only.

    Every review comes back stamped with the backend that produced it (``"cli"`` or ``"ollama"``):
    the stamp is the runner's, never the model's, and it is what keeps a local model's size
    suggestion from ever being applied (``engine.regime_limits.claude_cut``).
    """
    cfg = get_config().claude
    kwargs = dict(
        candidates=candidates,
        account=account,
        market_conditions=market_conditions,
        spot_prices=spot_prices,
        sector_context=sector_context,
        single_ticker=single_ticker,
        analytics=analytics,
        picture_block=picture_block,
        book_block=book_block,
        dossier_block=dossier_block,
    )

    if cfg.backend == "ollama":
        return ollama_runner.review_candidates(**kwargs)  # type: ignore[arg-type]

    reviews, error = _review_candidates_cli_outcome(**kwargs)  # type: ignore[arg-type]
    if not reviews and cfg.backend == "cli_then_ollama" and should_fall_back(error):
        log.warning("claude unavailable (%s) — using ollama", error)
        return ollama_runner.review_candidates(**kwargs)  # type: ignore[arg-type]
    return reviews


def _review_candidates_cli(*args: Any, **kwargs: Any) -> list[ClaudeReview]:
    """The reviews alone; the dispatcher uses ``_review_candidates_cli_outcome``."""
    return _review_candidates_cli_outcome(*args, **kwargs)[0]


def _stamp(reviews: list[ClaudeReview], backend: str) -> list[ClaudeReview]:
    """Reviews marked with the backend that produced them (the parser leaves it blank)."""
    return [r.model_copy(update={"backend": backend}) for r in reviews]


def _review_candidates_cli_outcome(
    candidates: list[TradeCandidate],
    account: AccountSnapshot,
    market_conditions: MarketConditions | None = None,
    spot_prices: dict[str, float] | None = None,
    sector_context: str | None = None,
    single_ticker: bool = False,
    analytics: AnalyticsMap | None = None,
    picture_block: str | None = None,
    book_block: str | None = None,
    dossier_block: str | None = None,
) -> tuple[list[ClaudeReview], str | None]:
    """Shell out to `claude -p`, parse output → (list[ClaudeReview], error). [] on any failure.

    picture_block / book_block / dossier_block: the pre-rendered market picture, book and name
    notes (enrichment, prompt text only). The reviews returned are stamped ``backend="cli"``.
    market_conditions: optional macro snapshot (VIX) injected as enrichment context.
    spot_prices: optional scan-time {symbol: spot} so Claude reasons from current levels rather
    than the stale static universe anchors (N17).
    analytics: per-symbol raw signals annotated onto each candidate in the prompt (enrichment).
    """
    cfg = get_config().claude

    if not cfg.enabled:
        log.info("claude: disabled by config — skipping review")
        return [], "disabled"

    if not candidates:
        log.info("claude: no candidates to review")
        return [], None

    prompt = build_prompt(
        candidates,
        account,
        market_conditions=market_conditions,
        spot_prices=spot_prices,
        sector_context=sector_context,
        single_ticker=single_ticker,
        analytics=analytics,
        picture_block=picture_block,
        book_block=book_block,
        dossier_block=dossier_block,
    )

    # Pass prompt via stdin rather than -p to avoid ARG_MAX (~128 KB) limits
    # when the candidate list + history grows large.
    cmd = _build_cmd(cfg, model=cfg.model_for("review"))
    cwd = _headless_cwd(cfg)
    candidate_ids = [c.candidate_id for c in candidates]
    error = "cli_error"
    timed_out = False

    for attempt in range(cfg.max_retries + 1):
        try:
            result = subprocess.run(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=cfg.timeout_seconds,
                cwd=cwd,
            )
        except subprocess.TimeoutExpired:
            log.warning(
                "claude: timed out after %.0fs (attempt %d)", cfg.timeout_seconds, attempt + 1
            )
            timed_out = True
            continue
        except FileNotFoundError:
            log.warning("claude: CLI not found — is 'claude' on PATH?")
            return [], "cli_missing"

        if is_usage_limit(result.stdout):
            log.warning("claude: usage limit reached — not retrying")
            return [], ("timeout" if timed_out else "cli_error")

        if result.returncode != 0:
            log.warning(
                "claude: non-zero returncode %d (attempt %d) stderr=%s",
                result.returncode,
                attempt + 1,
                result.stderr[:200] if result.stderr else "",
            )
            error = "cli_error"
            if not result.stdout:
                continue  # transient — retry
            # stdout present despite non-zero rc: try to parse it
            reviews = parse_claude_output(result.stdout, candidate_ids)
            if reviews:
                return _stamp(reviews, "cli"), None
            continue

        reviews = parse_claude_output(result.stdout, candidate_ids)
        if reviews:
            _log_cost(result.stdout, "claude review")
            return _stamp(reviews, "cli"), None

        log.warning("claude: output parsed to empty list (attempt %d)", attempt + 1)
        error = "bad_envelope"

    log.error("claude: all %d attempt(s) failed — returning []", cfg.max_retries + 1)
    return [], ("timeout" if timed_out else error)


def review_roll(
    alert: RollAlert,
    pos: PositionSnapshot,
    quote: OptionQuote,
    *,
    proposal: str | None = None,
    picture_block: str | None = None,
    dossier_block: str | None = None,
) -> RollReview | None:
    """Roll/hold/close recommendation via the configured `claude.backend`.

    Returns None on any failure — the caller proceeds without Claude's input.
    Intended to be called from a ThreadPoolExecutor so it doesn't block asyncio.
    *picture_block* is the pre-rendered market picture; when not given the stored picture is
    read (news.db, read-only; one small read, never raises) and shown either backend.
    *dossier_block* is the rolled name's dossier note; when not given, the full note of the
    underlying is read the same way (an explicit empty string means none).
    """
    cfg = get_config().claude
    now = datetime.now(UTC)
    if picture_block is None:
        picture_block = load_picture_block(now)
    if dossier_block is None:
        dossier_block = load_dossier_block(
            [alert.underlying or pos.underlying or pos.symbol], now, compact=False
        )

    if cfg.backend == "ollama":
        return ollama_runner.review_roll(
            alert,
            pos,
            quote,
            proposal=proposal,
            picture_block=picture_block,
            dossier_block=dossier_block,
        )

    review, error = _review_roll_cli(
        alert,
        pos,
        quote,
        proposal=proposal,
        picture_block=picture_block,
        dossier_block=dossier_block,
    )
    if review is None and cfg.backend == "cli_then_ollama" and should_fall_back(error):
        log.warning("claude unavailable (%s) — using ollama for the roll review", error)
        return ollama_runner.review_roll(
            alert,
            pos,
            quote,
            proposal=proposal,
            picture_block=picture_block,
            dossier_block=dossier_block,
        )
    return review


def _review_roll_cli(
    alert: RollAlert,
    pos: PositionSnapshot,
    quote: OptionQuote,
    *,
    proposal: str | None = None,
    picture_block: str | None = None,
    dossier_block: str | None = None,
) -> tuple[RollReview | None, str | None]:
    """Shell out to `claude -p` for a focused roll/hold/close recommendation.

    Returns ``(None, error)`` on any failure — the caller proceeds without Claude's input.
    """
    cfg = get_config().claude
    if not cfg.enabled:
        log.info("claude: disabled by config — skipping roll review")
        return None, "disabled"
    return _run_cli_outcome(
        build_roll_prompt(
            alert,
            pos,
            quote,
            proposal=proposal,
            picture_block=picture_block,
            dossier_block=dossier_block,
        ),
        "claude roll",
        parse_roll_output,
        cmd=_build_cmd(cfg, model=cfg.model_for("roll")),
    )


def write_journal_narrative(summary: EODSummary) -> str | None:
    """EOD journal narrative via the configured `claude.backend`.

    Returns the narrative string, or None on any failure — the caller writes
    JournalRow without a narrative and sends Telegram without the journal paragraph.
    """
    cfg = get_config().claude
    picture_block = load_picture_block(datetime.now(UTC))

    if cfg.backend == "ollama":
        return ollama_runner.write_journal_narrative(summary, picture_block=picture_block)

    narrative, error = _write_journal_narrative_cli(summary, picture_block=picture_block)
    if narrative is None and cfg.backend == "cli_then_ollama" and should_fall_back(error):
        log.warning("claude unavailable (%s) — using ollama for the EOD journal", error)
        return ollama_runner.write_journal_narrative(summary, picture_block=picture_block)
    return narrative


def _write_journal_narrative_cli(
    summary: EODSummary, *, picture_block: str | None = None
) -> tuple[str | None, str | None]:
    """Shell out to `claude -p` for an EOD journal narrative. ``(None, error)`` on any failure."""
    cfg = get_config().claude
    if not cfg.enabled:
        log.info("claude: disabled by config — skipping EOD journal")
        return None, "disabled"
    return _run_cli_outcome(
        build_eod_prompt(summary, picture_block=picture_block),
        "claude eod",
        parse_journal_output,
        cmd=_build_cmd(cfg, model=cfg.model_for("eod")),
    )


def _log_cost(raw: str, kind: str = "claude") -> None:
    """Best-effort cost + per-call-kind usage logging from the envelope; never raises."""
    try:
        envelope = json.loads(raw)
        cost = envelope.get("total_cost_usd")
        if cost is not None:
            log.info("claude: call cost $%.6f USD", cost)
    except Exception:
        pass
    log_usage(log, kind, raw)
