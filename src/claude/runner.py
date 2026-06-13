"""Shell out to `claude -p` and return structured ClaudeReview objects.

If the CLI is unavailable, times out, or returns unparseable output, returns []
so the orchestrator can fall back to the deterministic Rules-Engine-approved list.
"""

from __future__ import annotations

import logging
import subprocess

from src.claude.parser import parse_claude_output, parse_journal_output, parse_roll_output
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
    TradeCandidate,
)

log = logging.getLogger(__name__)


def _build_cmd(cfg: object) -> list[str]:
    """Assemble the hardened `claude` headless command (N3).

    Beyond `--output-format`, this constrains the unattended subprocess so a prompt-injection
    or runaway can't drive tools or the filesystem: a single agentic turn, an explicit tool
    denylist, and an optional pinned model. All three are config-tunable (see ClaudeCfg); a
    falsy value omits the corresponding flag. The flags don't change the JSON envelope, so the
    parser path is unaffected.
    """
    cmd = [cfg.cli_command, "--output-format", cfg.output_format]  # type: ignore[attr-defined]
    if cfg.max_turns:  # type: ignore[attr-defined]
        cmd += ["--max-turns", str(cfg.max_turns)]  # type: ignore[attr-defined]
    if cfg.model:  # type: ignore[attr-defined]
        cmd += ["--model", cfg.model]  # type: ignore[attr-defined]
    if cfg.disallowed_tools:  # type: ignore[attr-defined]
        cmd += ["--disallowedTools", cfg.disallowed_tools]  # type: ignore[attr-defined]
    return cmd


def review_candidates(
    candidates: list[TradeCandidate],
    account: AccountSnapshot,
    history: list | None = None,
    market_conditions: MarketConditions | None = None,
    spot_prices: dict[str, float] | None = None,
) -> list[ClaudeReview]:
    """Shell out to `claude -p`, parse output → list[ClaudeReview]. Returns [] on any failure.

    history: optional list of ClaudeMemoryRow objects from prior scans; injected into the prompt
    so Claude can learn from past recommendations and their outcomes.
    market_conditions: optional macro snapshot (VIX) injected as enrichment context.
    spot_prices: optional scan-time {symbol: spot} so Claude reasons from current levels rather
    than the stale static universe anchors (N17).
    """
    cfg = get_config().claude

    if not cfg.enabled:
        log.info("claude: disabled by config — skipping review")
        return []

    if not candidates:
        log.info("claude: no candidates to review")
        return []

    prompt = build_prompt(
        candidates,
        account,
        history=history,
        market_conditions=market_conditions,
        spot_prices=spot_prices,
    )

    # Pass prompt via stdin rather than -p to avoid ARG_MAX (~128 KB) limits
    # when the candidate list + history grows large.
    cmd = _build_cmd(cfg)

    for attempt in range(cfg.max_retries + 1):
        try:
            result = subprocess.run(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=cfg.timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            log.warning(
                "claude: timed out after %.0fs (attempt %d)", cfg.timeout_seconds, attempt + 1
            )
            continue
        except FileNotFoundError:
            log.warning("claude: CLI not found — is 'claude' on PATH?")
            return []

        if result.returncode != 0:
            log.warning(
                "claude: non-zero returncode %d (attempt %d) stderr=%s",
                result.returncode,
                attempt + 1,
                result.stderr[:200] if result.stderr else "",
            )
            if not result.stdout:
                continue  # transient — retry
            # stdout present despite non-zero rc: try to parse it
            reviews = parse_claude_output(result.stdout)
            if reviews:
                return reviews
            continue

        reviews = parse_claude_output(result.stdout)
        if reviews:
            _log_cost(result.stdout)
            return reviews

        log.warning("claude: output parsed to empty list (attempt %d)", attempt + 1)

    log.error("claude: all %d attempt(s) failed — returning []", cfg.max_retries + 1)
    return []


def review_roll(alert: RollAlert, pos: PositionSnapshot, quote: OptionQuote) -> RollReview | None:
    """Shell out to `claude -p` for a focused roll/hold/close recommendation.

    Returns None on any failure — the caller proceeds without Claude's input.
    Intended to be called from a ThreadPoolExecutor so it doesn't block asyncio.
    """
    cfg = get_config().claude

    if not cfg.enabled:
        log.info("claude: disabled by config — skipping roll review")
        return None

    prompt = build_roll_prompt(alert, pos, quote)
    cmd = _build_cmd(cfg)

    for attempt in range(cfg.max_retries + 1):
        try:
            result = subprocess.run(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=cfg.timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            log.warning("claude roll: timed out (attempt %d)", attempt + 1)
            continue
        except FileNotFoundError:
            log.warning("claude: CLI not found — skipping roll review")
            return None

        if result.returncode != 0 and not result.stdout:
            log.warning(
                "claude roll: rc=%d, no stdout (attempt %d)", result.returncode, attempt + 1
            )
            continue

        review = parse_roll_output(result.stdout)
        if review is not None:
            _log_cost(result.stdout)
            return review

        log.warning("claude roll: unparseable output (attempt %d)", attempt + 1)

    log.error("claude roll: all %d attempt(s) failed", cfg.max_retries + 1)
    return None


def write_journal_narrative(summary: EODSummary) -> str | None:
    """Shell out to `claude -p` for an EOD journal narrative.

    Returns the narrative string, or None on any failure — the caller writes
    JournalRow without a narrative and sends Telegram without the journal paragraph.
    """
    cfg = get_config().claude

    if not cfg.enabled:
        log.info("claude: disabled by config — skipping EOD journal")
        return None

    prompt = build_eod_prompt(summary)
    cmd = _build_cmd(cfg)

    for attempt in range(cfg.max_retries + 1):
        try:
            result = subprocess.run(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=cfg.timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            log.warning("claude eod: timed out (attempt %d)", attempt + 1)
            continue
        except FileNotFoundError:
            log.warning("claude: CLI not found — skipping EOD journal")
            return None

        if result.returncode != 0 and not result.stdout:
            log.warning("claude eod: rc=%d, no stdout (attempt %d)", result.returncode, attempt + 1)
            continue

        narrative = parse_journal_output(result.stdout)
        if narrative is not None:
            _log_cost(result.stdout)
            return narrative

        log.warning("claude eod: unparseable output (attempt %d)", attempt + 1)

    log.error("claude eod: all %d attempt(s) failed", cfg.max_retries + 1)
    return None


def _log_cost(raw: str) -> None:
    """Best-effort cost logging from the envelope; never raises."""
    import json

    try:
        envelope = json.loads(raw)
        cost = envelope.get("total_cost_usd")
        if cost is not None:
            log.info("claude: call cost $%.6f USD", cost)
    except Exception:
        pass
