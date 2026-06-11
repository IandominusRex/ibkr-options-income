"""Skill proposer — draft a reasoning skill from labeled history via `claude -p`.

Feeds Claude the verdict ledger (what it recommended, what the signals were, what actually
happened) plus the current evaluation and the already-active skills, and asks for ONE new or
refined playbook. The draft lands in `config/skills/proposed/` for human review — it is never
auto-promoted, and it cannot touch gates/weights/sizing.

Shares the runner's fail-soft contract: any CLI/parse failure returns None.
"""

from __future__ import annotations

import json
import logging
import subprocess

from src.claude.eval.ledger import load_records
from src.claude.eval.metrics import evaluate
from src.claude.parser import _loads_lenient, _strip_fences
from src.claude.skills.registry import load_active_skills, save_proposal
from src.common.config import get_config
from src.common.schemas import SkillProposal, VerdictEvaluation, VerdictRecord

log = logging.getLogger(__name__)

_MAX_EXAMPLES = 60  # cap the labeled rows injected so the prompt stays well under ARG limits


def _format_record(r: VerdictRecord) -> str:
    s = r.signals or {}
    pnl = "open" if r.realized_pnl is None else f"{r.realized_pnl:+.0f}"

    def _num(key: str, fmt: str) -> str:
        v = s.get(key)
        return format(v, fmt) if isinstance(v, int | float) else "n/a"

    return (
        f"[{r.scan_date}] {r.underlying} {r.strategy.value} {r.right.value}{r.strike:g} "
        f"{r.dte}DTE | claude={r.claude_recommendation}"
        f"(conf={r.claude_confidence if r.claude_confidence is not None else 'na'}) "
        f"baseline={r.baseline_recommendation} | "
        f"score={_num('blended_score', '.0f')} ivr={_num('iv_rank', '.0f')} "
        f"delta={_num('delta', '.2f')} vrp={_num('vrp', '+.0f')} "
        f"| outcome={r.outcome.value} pnl={pnl}"
    )


def build_proposal_prompt(
    records: list[VerdictRecord],
    evaluation: VerdictEvaluation,
) -> str:
    """Assemble the skill-proposal prompt from labeled history + current evaluation."""
    active = load_active_skills()
    closed = [r for r in records if r.realized_pnl is not None]
    examples = closed[:_MAX_EXAMPLES]

    lines: list[str] = [
        "You are refining the reasoning layer of a covered-call / cash-secured-put income "
        "system. The deterministic Rules Engine already gates, sizes, and risk-approves every "
        "trade — you CANNOT change that. Your job is to propose ONE reasoning skill: a short "
        "playbook that improves how the strategist forms its verdict (sell/wait/skip) and "
        "ranking, learned from the labeled outcomes below.",
        "",
        "HARD CONSTRAINTS:",
        "- A skill influences verdict + ranking ONLY. Never propose changing deltas, DTE, IV "
        "thresholds, position sizing, concentration limits, or any numeric gate — those are "
        "human-edited config and out of scope.",
        "- Base the skill on patterns visible in the data, not generic options advice.",
        "- If the data is too thin to support a confident skill, say so in the rationale and "
        "propose a conservative, easily-falsifiable one.",
        "",
        "=== CURRENT EVALUATION ===",
        f"Closed trades scored: {evaluation.n_closed}",
        f"Brier score (lower=better calibrated): {evaluation.brier_score}",
        f"Edge per trade (follow_claude − baseline): {evaluation.edge_per_trade}",
        f"Agreement with baseline: {evaluation.agreement_rate}",
        f"follow_claude: {evaluation.follow_claude.model_dump()}",
        f"baseline: {evaluation.baseline.model_dump()}",
        "",
        "=== ALREADY-ACTIVE SKILLS (refine or complement; don't duplicate) ===",
    ]
    if active:
        for s in active:
            lines.append(f"- {s.name}: {s.description}")
    else:
        lines.append("(none yet)")

    lines += [
        "",
        f"=== LABELED HISTORY ({len(examples)} of {len(closed)} closed verdicts) ===",
        *[_format_record(r) for r in examples],
        "",
        "=== YOUR TASK ===",
        "Return ONLY a JSON object (no prose, no fences) matching:",
        "{",
        '  "name": "<kebab-case slug>",',
        '  "description": "<one line shown in the prompt skill index>",',
        '  "body": "<the markdown playbook to inject — concrete, falsifiable rules>",',
        '  "rationale": "<why this skill, citing the patterns above>",',
        '  "supporting_stats": {"<metric>": <value>, ...}',
        "}",
    ]
    return "\n".join(lines)


def _parse_proposal(raw: str) -> SkillProposal | None:
    if not raw or not raw.strip():
        return None
    try:
        envelope = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("skills: proposer outer JSON parse failed")
        return None
    inner = envelope.get("result") if isinstance(envelope, dict) else None
    if not isinstance(inner, str):
        log.warning("skills: proposer envelope missing 'result'")
        return None
    try:
        payload = _loads_lenient(_strip_fences(inner))
    except json.JSONDecodeError:
        log.warning("skills: proposer inner JSON parse failed")
        return None
    if isinstance(payload, list) and payload:
        payload = payload[0]
    if not isinstance(payload, dict):
        return None
    try:
        return SkillProposal.model_validate(payload)
    except Exception as exc:  # noqa: BLE001
        log.warning("skills: proposal failed validation: %s", exc)
        return None


def propose_skill(*, save: bool = True) -> SkillProposal | None:
    """Draft a skill from the full ledger. Returns the proposal (and saves it) or None.

    Fail-soft: disabled config, no labeled data, CLI missing, or unparseable output → None.
    """
    cfg = get_config().claude
    if not cfg.enabled:
        log.info("skills: claude disabled — skipping proposal")
        return None

    records = load_records(closed_only=True)
    if not records:
        log.info("skills: no closed verdicts yet — nothing to learn from")
        return None

    evaluation = evaluate(records)
    prompt = build_proposal_prompt(records, evaluation)
    cmd = [cfg.cli_command, "--output-format", cfg.output_format]

    try:
        result = subprocess.run(
            cmd, input=prompt, capture_output=True, text=True, timeout=cfg.timeout_seconds
        )
    except subprocess.TimeoutExpired:
        log.warning("skills: proposer timed out")
        return None
    except FileNotFoundError:
        log.warning("skills: claude CLI not found — cannot propose")
        return None

    if result.returncode != 0 and not result.stdout:
        log.warning("skills: proposer rc=%d, no stdout", result.returncode)
        return None

    proposal = _parse_proposal(result.stdout)
    if proposal is None:
        return None
    if save:
        save_proposal(proposal)
    return proposal
