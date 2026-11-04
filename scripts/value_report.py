"""The value book's shadow record, printed for a human (spec §6.8, §7, §11, §12).

    python -m scripts.value_report [--track baseline] [--universe all|trading|evidence]
        [--ruleset VERSION] [--postmortems]
    python -m scripts.value_report --symbol NVDA --json   # one ticker file, both halves


Reads data/value.db (select only; on a new install it first creates the empty tables) and
prints: the survivorship caveat, the
go-live line of spec §12, fixed-horizon returns against SPY with errors clustered by entry date,
the three exit policies side by side, the re-evaluations of §7.1 (the re-evaluated plan against the
original), the ranked monthly record, Claude's track beside the baseline's with the breaker's two
rates (Part 4, §12) and, with ``--postmortems``, one postmortem per closed position. No IBKR
connection, no network.
"""

from __future__ import annotations

import argparse
import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.common.config import get_config
from src.value.claude_verdicts import breaker_state
from src.value.report import (
    HORIZONS,
    EntryView,
    EventView,
    LegView,
    RankedView,
    ReevaluationView,
    claude_section,
    render,
)
from src.value.store import (
    ValueClaudeNoteRow,
    ValueClaudeVerdictRow,
    ValueEffectiveRow,
    ValueKillTriggerRow,
    ValueRankedRow,
    ValueReevaluationRow,
    ValueRunRow,
    ValueShadowEventRow,
    ValueShadowLegRow,
    ValueShadowRow,
    ValueTickerFileRow,
    init_value_db,
    value_session,
)


def _entry_view(r: ValueShadowRow) -> EntryView:
    return EntryView(
        id=r.id,
        track=r.track,
        kind=r.kind,
        list_name=r.list_name,
        symbol=r.symbol,
        universe=r.universe,
        status=r.status,
        signal_date=r.signal_date,
        entry_date=r.entry_date,
        entry_price=r.entry_price,
        fair_value=r.fair_value,
        margin_of_safety=r.margin_of_safety,
        ruleset_version=r.ruleset_version,
        returns={h: getattr(r, f"ret_{h}") for h in HORIZONS},
        spy={h: getattr(r, f"spy_{h}") for h in HORIZONS},
        scorecard_json=r.scorecard_json if r.kind == "ready" else "",
    )


def _claude_lines(s: Session, ruleset: str | None) -> list[str]:
    """Spec §12: Claude's track beside the baseline's, and the breaker's two rates."""
    vcfg = get_config().value
    q = select(ValueShadowRow).where(ValueShadowRow.kind == "ready")
    if ruleset:
        q = q.where(ValueShadowRow.ruleset_version == ruleset)
    rows = [_entry_view(r) for r in s.scalars(q)]
    runs = s.scalars(
        select(ValueRunRow)
        .where(ValueRunRow.kind == "nightly")
        .order_by(ValueRunRow.as_of.desc())
        .limit(vcfg.claude.breaker.sessions)
    )
    nights = [json.loads(r.summary_json or "{}").get("claude", {}) for r in runs]
    state = breaker_state(s)
    return claude_section(
        [e for e in rows if e.track == "baseline"],
        [e for e in rows if e.track == "claude"],
        nights,
        breaker=f"TRIPPED ({state.get('reason', '')})" if state.get("tripped") else "ok",
        ready_multiple=vcfg.claude.breaker.ready_multiple,
        clamp_rate_pct=vcfg.claude.breaker.clamp_rate_pct,
    )


def load(args: argparse.Namespace) -> str:
    vcfg = get_config().value
    init_value_db()
    with value_session() as s:
        q = select(ValueShadowRow).where(ValueShadowRow.track == args.track)
        if args.universe != "all":
            q = q.where(ValueShadowRow.universe == args.universe)
        if args.ruleset:
            q = q.where(ValueShadowRow.ruleset_version == args.ruleset)
        entries = [_entry_view(r) for r in s.scalars(q.order_by(ValueShadowRow.id))]
        ids = {e.id for e in entries}
        legs = [
            LegView(
                shadow_id=g.shadow_id,
                policy=g.policy,
                plan=g.plan,
                closed=g.closed,
                exit_date=g.exit_date,
                ret=g.ret_exit,
                spy_ret=g.spy_ret_exit,
                max_drawdown=g.max_drawdown,
                sessions=g.sessions,
                sells=g.sells,
            )
            for g in s.scalars(select(ValueShadowLegRow))
            if g.shadow_id in ids
        ]
        events = [
            EventView(
                shadow_id=v.shadow_id,
                policy=v.policy,
                plan=v.plan,
                day=v.day,
                kind=v.kind,
                price=v.price,
                fraction=v.fraction,
                detail=v.detail,
            )
            for v in s.scalars(select(ValueShadowEventRow).order_by(ValueShadowEventRow.id))
            if args.postmortems and v.shadow_id in ids
        ]
        ranked = [
            RankedView(
                formed_on=r.formed_on,
                list_name=r.list_name,
                bucket=r.bucket,
                n=r.n,
                closed_on=r.closed_on,
                ret=r.ret,
                spy_ret=r.spy_ret,
                missing=r.missing,
            )
            for r in s.scalars(select(ValueRankedRow).order_by(ValueRankedRow.formed_on))
            if not args.ruleset or r.ruleset_version == args.ruleset
        ]
        reevaluations = [
            ReevaluationView(
                shadow_id=r.shadow_id,
                list_name=r.list_name,
                severity=r.severity,
                kinds=[t["kind"] for t in json.loads(r.triggers_json)],
            )
            for r in s.scalars(select(ValueReevaluationRow))
            if r.shadow_id in ids
        ]
        rebases = s.scalar(
            select(func.count())
            .select_from(ValueShadowEventRow)
            .where(ValueShadowEventRow.kind == "rebase", ValueShadowEventRow.shadow_id.in_(ids))
        )
        claude_lines = _claude_lines(s, args.ruleset)
        now: dict[tuple[str, str], float | None] = {}
        for f in s.scalars(select(ValueTickerFileRow)):
            now[(f.symbol, "deep_value")] = f.fair_value_deep
            now[(f.symbol, "quality_growth")] = f.fair_value_growth
    return render(
        entries,
        legs,
        events,
        ranked,
        fair_values_now=now,
        live_policy=vcfg.rules.exits.live_policy,
        track=args.track,
        postmortems=args.postmortems,
        reevaluations=reevaluations,
        rebases=int(rebases or 0),
        claude_lines=claude_lines,
    )


def symbol_json(symbol: str) -> str:
    """One name's ticker file as JSON (spec §8.6: what the interactive skill reads instead of
    re-computing anything): Part 1 (the scorecard), the effective verdict per list, and Claude's
    latest verdicts, notes and active kill triggers, each labelled with its source."""
    init_value_db()
    sym = symbol.upper()
    with value_session() as s:
        f = s.get(ValueTickerFileRow, sym)
        if f is None:
            return json.dumps({"symbol": sym, "error": "no ticker file"})
        effective = {
            e.list_name: {
                "verdict": e.verdict,
                "decided_by": e.decided_by,
                "fair_value": e.fair_value,
                "entry_ceiling": e.entry_ceiling,
                "margin_of_safety": e.margin_of_safety,
            }
            for e in s.scalars(select(ValueEffectiveRow).where(ValueEffectiveRow.symbol == sym))
        }
        verdicts = [
            {
                "list": v.list_name,
                "verdict": v.verdict,
                "why": v.why,
                "fair_value": v.fair_value,
                "uncapped": v.uncapped,
                "clamp_bound": v.clamp_bound,
                "drivers": json.loads(v.drivers_json),
                "backend": v.backend,
                "written": v.created_at.isoformat(),
            }
            for v in s.scalars(
                select(ValueClaudeVerdictRow).where(
                    ValueClaudeVerdictRow.symbol == sym, ValueClaudeVerdictRow.superseded.is_(False)
                )
            )
        ]
        note = s.scalars(
            select(ValueClaudeNoteRow)
            .where(ValueClaudeNoteRow.symbol == sym)
            .order_by(ValueClaudeNoteRow.id.desc())
            .limit(1)
        ).first()
        triggers = [
            {"kind": t.kind, "threshold": t.threshold, "state": t.last_state}
            for t in s.scalars(
                select(ValueKillTriggerRow).where(
                    ValueKillTriggerRow.symbol == sym, ValueKillTriggerRow.active.is_(True)
                )
            )
        ]
        return json.dumps(
            {
                "symbol": sym,
                "as_of": f.as_of.isoformat(),
                "source": {"scorecard": "python", "claude": "claude"},
                "scorecard": json.loads(f.scorecard_json),
                "effective": effective,
                "claude": {
                    "verdicts": verdicts,
                    "notes": None
                    if note is None
                    else {
                        "profile": note.profile,
                        "why_cheap": note.why_cheap,
                        "thesis": note.thesis,
                        "bear_case": note.bear_case,
                        "review_state": note.review_state,
                        "written": note.created_at.isoformat(),
                    },
                    "kill_triggers": triggers,
                },
            },
            indent=1,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="The value book's shadow record (spec §6.8)")
    parser.add_argument("--track", default="baseline", choices=("baseline", "claude"))
    parser.add_argument("--universe", default="all", choices=("all", "trading", "evidence"))
    parser.add_argument("--ruleset", default=None, help="only this ruleset version")
    parser.add_argument("--postmortems", action="store_true")
    parser.add_argument("--symbol", default=None, help="one ticker file (with --json)")
    parser.add_argument("--json", action="store_true", help="with --symbol: print JSON")
    args = parser.parse_args(argv)
    print(symbol_json(args.symbol) if args.symbol else load(args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
