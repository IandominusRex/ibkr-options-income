"""Accepting Claude's reads, and what they decide (spec §6.7, §8.2, §8.3, §8.5).

``accept`` turns one ``AnalystResult`` into rows: per list, the verdict and the drivers after
Python bounded them, with the fair value Python computed and capped (``claude_valuation``);
the prose; the kill triggers with their thresholds bounded; and, for a review, the review state on
the re-evaluation. Between filings a re-read may lower Claude's value, never raise it: drivers that
would value the name higher on the same accession are refused and the earlier ones kept.

``opinions`` reads the latest usable verdict per name and list and recomputes its fair value from
the stored drivers on **tonight's** scorecard, so Claude's value moves only when the filed inputs
or Python's own value (the cap) move. An Ollama verdict is never an opinion. ``persist_effective``
writes ``value_effective`` every night. The breaker (spec §8.2) is read from the nightly runs'
summaries and, once tripped, stays tripped until the operator resets it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.common.config import ValueCfg, ValueRulesCfg
from src.common.value_ai_types import AnalystResult, Drivers, KillTrigger
from src.value import kill_triggers
from src.value.claude_valuation import ClaudeValue, claude_fair_value
from src.value.effective import ClaudeOpinion, Effective, effective
from src.value.schemas import LISTS, ValueScorecard
from src.value.store import (
    ValueClaudeFactRow,
    ValueClaudeNoteRow,
    ValueClaudeReadRow,
    ValueClaudeStateRow,
    ValueClaudeVerdictRow,
    ValueEffectiveRow,
    ValueKillTriggerRow,
    ValueReevaluationRow,
    ValueRunRow,
)

BREAKER_KEY = "breaker"


@dataclass(slots=True)
class Accepted:
    verdicts: int = 0
    refused: list[str] | None = None  # lists whose verdict was not stored, and why
    kept_earlier: int = 0  # raised between filings: the earlier drivers stand
    triggers: int = 0
    review_state: str | None = None


def _latest_verdict(vs: Session, symbol: str, list_name: str) -> ValueClaudeVerdictRow | None:
    return vs.scalars(
        select(ValueClaudeVerdictRow)
        .where(
            ValueClaudeVerdictRow.symbol == symbol,
            ValueClaudeVerdictRow.list_name == list_name,
            ValueClaudeVerdictRow.superseded.is_(False),
            ValueClaudeVerdictRow.backend == "cli",
        )
        .order_by(ValueClaudeVerdictRow.id.desc())
        .limit(1)
    ).first()


def bounded_trigger(t: KillTrigger, rules: ValueRulesCfg) -> KillTrigger | None:
    """A trigger with its threshold moved into the menu's range; None when a numeric predicate
    came without a threshold. The fact-based kinds carry none."""
    bound = rules.claude.kill_bounds.get(t.kind)
    if bound is None:
        return KillTrigger(kind=t.kind, threshold=None)
    if t.threshold is None:
        return None
    lo, hi = bound
    return KillTrigger(kind=t.kind, threshold=min(max(t.threshold, lo), hi))


def accept(
    vs: Session,
    read: ValueClaudeReadRow,
    result: AnalystResult,
    card: ValueScorecard,
    cfg: ValueCfg,
    *,
    now: datetime,
) -> Accepted:
    """Store one read's outcome. The read row records the call either way; a reply that is None
    (a failure, a malformed reply) stores nothing else: no notes, never a guess."""
    call = result.call
    read.read_at, read.model, read.backend = now, call.model, call.backend
    read.latency_ms, read.cost_usd, read.error = call.latency_ms, call.cost_usd, call.error
    read.prompt_version, read.prompt, read.raw = call.prompt_version, call.prompt, call.raw
    read.status = "done" if result.reply is not None else "failed"
    out = Accepted(refused=[])
    reply = result.reply
    if reply is None:
        return out
    rules = cfg.rules
    accn = card.fingerprint.latest_accn
    for call_list in reply.lists:
        if call_list.list_name not in card.lists:
            out.refused = [*(out.refused or []), f"{call_list.list_name}: not on this list"]
            continue
        value = claude_fair_value(card, call_list.list_name, call_list.drivers, rules)
        drivers = value.drivers
        prev = (
            _latest_verdict(vs, read.symbol, call_list.list_name) if call.backend == "cli" else None
        )
        clamps = list(value.clamps)
        if prev is not None and prev.accn == accn and value.fair_value is not None:
            before = claude_fair_value(
                card, call_list.list_name, Drivers.model_validate_json(prev.drivers_json), rules
            )
            if before.fair_value is not None and value.fair_value > before.fair_value:
                value, drivers = before, before.drivers  # between filings: lower, never raise
                clamps.append("raised between filings: the earlier drivers stand")
                out.kept_earlier += 1
        if prev is not None:
            prev.superseded = True
        vs.add(
            ValueClaudeVerdictRow(
                read_id=read.id,
                symbol=read.symbol,
                list_name=call_list.list_name,
                verdict=call_list.verdict,
                why=call_list.why,
                drivers_json=drivers.model_dump_json(),
                clamps_json=json.dumps(clamps),
                fair_value=value.fair_value,
                uncapped=value.uncapped,
                python_fair_value=value.python_fair_value,
                clamp_bound=value.clamp_bound,
                unreliable=value.unreliable,
                accn=accn,
                fingerprint_key=card.fingerprint.key(),
                backend=call.backend,
                created_at=now,
            )
        )
        out.verdicts += 1
    vs.add(
        ValueClaudeNoteRow(
            read_id=read.id,
            symbol=read.symbol,
            profile=reply.profile,
            why_cheap=reply.why_cheap,
            thesis=reply.thesis,
            bear_case=reply.bear_case,
            review_state=reply.review_state,
            review_why=reply.review_why,
            backend=call.backend,
            created_at=now,
        )
    )
    if reply.kill_triggers and call.backend == "cli":
        for old in vs.scalars(
            select(ValueKillTriggerRow).where(
                ValueKillTriggerRow.symbol == read.symbol, ValueKillTriggerRow.active.is_(True)
            )
        ):
            old.active = False  # a new set replaces the old one
        for t in reply.kill_triggers[: rules.claude.max_kill_triggers]:
            kept = bounded_trigger(t, rules)
            if kept is None:
                continue
            vs.add(
                ValueKillTriggerRow(
                    read_id=read.id,
                    symbol=read.symbol,
                    kind=kept.kind,
                    threshold=kept.threshold,
                    chosen_at=now,
                )
            )
            out.triggers += 1
    if reply.review_state is not None and read.reevaluation_id is not None:
        reeval = vs.get(ValueReevaluationRow, read.reevaluation_id)
        if reeval is not None and call.backend == "cli":
            reeval.review_state = reply.review_state
            out.review_state = reply.review_state
    vs.flush()
    return out


def opinions(
    vs: Session, cards: list[ValueScorecard], rules: ValueRulesCfg
) -> dict[tuple[str, str], tuple[ClaudeOpinion, ClaudeValue]]:
    """Every name's latest usable CLI verdict per list, its fair value recomputed from the
    stored drivers on tonight's scorecard. Ignores the breaker and the live switch: callers
    decide whether an opinion applies (``applies``)."""
    by_symbol = {c.symbol: c for c in cards}
    out: dict[tuple[str, str], tuple[ClaudeOpinion, ClaudeValue]] = {}
    rows = vs.scalars(
        select(ValueClaudeVerdictRow).where(
            ValueClaudeVerdictRow.superseded.is_(False),
            ValueClaudeVerdictRow.backend == "cli",
            ValueClaudeVerdictRow.symbol.in_(list(by_symbol)),
        )
    )
    for row in rows:
        card = by_symbol[row.symbol]
        value = claude_fair_value(
            card, row.list_name, Drivers.model_validate_json(row.drivers_json), rules
        )
        out[(row.symbol, row.list_name)] = (
            ClaudeOpinion(row.verdict, value.fair_value, row.id),
            value,
        )
    return out


def breaker_state(vs: Session) -> dict[str, Any]:
    row = vs.get(ValueClaudeStateRow, BREAKER_KEY)
    return {"tripped": False} if row is None else json.loads(row.value)


def set_breaker(vs: Session, state: dict[str, Any], now: datetime) -> None:
    row = vs.get(ValueClaudeStateRow, BREAKER_KEY)
    blob = json.dumps(state, sort_keys=True)
    if row is None:
        vs.add(ValueClaudeStateRow(key=BREAKER_KEY, value=blob, updated_at=now))
    else:
        row.value, row.updated_at = blob, now


def applies(vs: Session, cfg: ValueCfg, *, is_live: bool) -> bool:
    """Whether Claude's verdict decides what Stage 3 acts on: paper, or live with
    ``apply_live`` on, and the breaker not tripped (spec §8.2)."""
    if is_live and not cfg.claude.apply_live:
        return False
    return not breaker_state(vs).get("tripped", False)


def night_counts(
    cards: list[ValueScorecard],
    tags: dict[str, str],
    ops: dict[tuple[str, str], tuple[ClaudeOpinion, ClaudeValue]],
    review_above_pct: float,
) -> dict[str, int]:
    """Tonight's breaker inputs over the trading universe: Claude-decided READYs (opinions
    applied), the baseline's READYs, Claude's usable fair values and how many the cap set."""
    out = {"ready": 0, "baseline_ready": 0, "values": 0, "clamped": 0}
    for card in cards:
        if tags.get(card.symbol) != "trading":
            continue
        for name in LISTS:
            if card.verdict_for(name) == "READY":
                out["baseline_ready"] += 1
            found = ops.get((card.symbol, name))
            if found is None:
                continue
            opinion, value = found
            if value.fair_value is not None:
                out["values"] += 1
                out["clamped"] += int(value.clamp_bound)
            eff = effective(card, name, opinion, review_above_pct=review_above_pct)
            if eff.decided_by == "claude" and eff.verdict == "READY":
                out["ready"] += 1
    return out


def check_breaker(vs: Session, cfg: ValueCfg, tonight: dict[str, int], now: datetime) -> bool:
    """Trip the breaker when the last ``sessions`` nights (tonight included) breach either
    rate. Returns whether it is tripped after tonight. Never resets itself."""
    state = breaker_state(vs)
    if state.get("tripped"):
        return True
    b = cfg.claude.breaker
    totals = dict(tonight)
    runs = vs.scalars(
        select(ValueRunRow)
        .where(ValueRunRow.kind == "nightly")
        .order_by(ValueRunRow.as_of.desc())
        .limit(b.sessions - 1)
    )
    for run in runs:
        night = json.loads(run.summary_json or "{}").get("claude", {})
        for key in totals:
            totals[key] += int(night.get(key, 0))
    reason = None
    if (
        totals["ready"] >= b.min_ready
        and totals["ready"] > b.ready_multiple * totals["baseline_ready"]
    ):
        reason = (
            f"Claude READY {totals['ready']} > {b.ready_multiple:g} x the baseline's "
            f"{totals['baseline_ready']} over {b.sessions} sessions"
        )
    elif (
        totals["values"] >= b.min_values
        and totals["clamped"] * 100.0 / totals["values"] > b.clamp_rate_pct
    ):
        reason = (
            f"the 1.5x clamp set {totals['clamped']} of {totals['values']} fair values "
            f"(> {b.clamp_rate_pct:g}%) over {b.sessions} sessions"
        )
    if reason is None:
        return False
    set_breaker(vs, {"tripped": True, "since": now.isoformat(), "reason": reason}, now)
    return True


def reset_breaker(vs: Session, now: datetime) -> None:
    set_breaker(vs, {"tripped": False, "reset_at": now.isoformat()}, now)


def persist_effective(
    vs: Session,
    cards: list[ValueScorecard],
    ops: dict[tuple[str, str], tuple[ClaudeOpinion, ClaudeValue]],
    *,
    applied: bool,
    as_of: date,
    now: datetime,
    review_above_pct: float,
) -> dict[tuple[str, str], Effective]:
    """Write ``value_effective`` for every scored name and list; returns it. With *applied*
    False every list keeps Python's baseline (breaker tripped, or live with apply_live off)."""
    out: dict[tuple[str, str], Effective] = {}
    for card in cards:
        for name in LISTS:
            found = ops.get((card.symbol, name)) if applied else None
            eff = effective(
                card, name, found[0] if found else None, review_above_pct=review_above_pct
            )
            out[(card.symbol, name)] = eff
            row = vs.get(ValueEffectiveRow, (card.symbol, name))
            values = dict(
                as_of=as_of,
                verdict=eff.verdict,
                decided_by=eff.decided_by,
                python_verdict=eff.python_verdict,
                claude_verdict=eff.claude_verdict,
                verdict_id=eff.verdict_id,
                fair_value=eff.fair_value,
                entry_ceiling=eff.entry_ceiling,
                margin_of_safety=eff.margin_of_safety,
                mos_review=eff.mos_review,
                updated_at=now,
            )
            if row is None:
                vs.add(ValueEffectiveRow(symbol=card.symbol, list_name=name, **values))
            else:
                for key, value in values.items():
                    setattr(row, key, value)
    return out


def update_kill_triggers(
    vs: Session, cards: list[ValueScorecard], cfg: ValueCfg, as_of: date
) -> dict[str, list[str]]:
    """Evaluate every active kill trigger on tonight's scorecard (spec §8.4) and record the
    result on its row. Returns, per name, the lines of the triggers that are near or fired:
    trigger 6's input for tonight's re-evaluations (spec §7.1)."""
    by_symbol = {c.symbol: c for c in cards}
    out: dict[str, list[str]] = {}
    rows = vs.scalars(
        select(ValueKillTriggerRow).where(
            ValueKillTriggerRow.active.is_(True),
            ValueKillTriggerRow.symbol.in_(list(by_symbol)),
        )
    ).all()
    for t in rows:
        facts = set(
            vs.scalars(
                select(ValueClaudeFactRow.kind).where(
                    ValueClaudeFactRow.symbol == t.symbol,
                    ValueClaudeFactRow.grounded.is_(True),
                    ValueClaudeFactRow.created_at >= t.chosen_at,
                )
            )
        )
        c = kill_triggers.check(
            t.kind,
            t.threshold,
            by_symbol[t.symbol],
            near_pct=cfg.rules.claude.kill_near_pct,
            facts_since=facts,
        )
        t.last_state, t.last_actual, t.last_checked = c.state, c.actual, as_of
        if c.state == "fired" and t.fired_on is None:
            t.fired_on = as_of
        if c.state in ("near", "fired"):
            out.setdefault(t.symbol, []).append(c.line())
    return out
