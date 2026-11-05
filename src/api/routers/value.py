"""GET /value/top, /value/book, /value/positions and /value/{symbol}: the value book, read-only,
through src/api/value_db.py (never src.value beyond the scorecard's shapes).

Nothing here writes value.db or decides anything. A web click on a proposal is a ``POST /commands``
of a value kind; this module only shows the fingerprint that click must carry back.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query

from src.api import value_db as vdb
from src.api.deps import OwnerUser
from src.api.models.value import (
    ValueBookResponse,
    ValueBreakersOut,
    ValueClaudeListOut,
    ValueClaudeOut,
    ValueDriverOut,
    ValueFactOut,
    ValueFileOut,
    ValueFundingOut,
    ValueGateOut,
    ValueKillTriggerOut,
    ValueListOut,
    ValueMethodOut,
    ValueNextExit,
    ValueNoteOut,
    ValuePlanOut,
    ValuePositionOut,
    ValuePositionsResponse,
    ValueProposalOut,
    ValueReevaluationOut,
    ValueTickerResponse,
    ValueTopItem,
    ValueTopResponse,
)
from src.common.config import get_config
from src.common.value_commands import trim_offer_stale
from src.value.schemas import Check, ListEvaluation, ValueScorecard

router = APIRouter(prefix="/value", tags=["value"])

_DEEP_FINANCIAL = ("bank", "insurer")
_NOTE_KINDS = ("profile", "why_cheap", "thesis", "bear_case")
_PRICED = ("READY", "WATCH", "WAIT")


def _now() -> datetime:
    """The routes' clock. Patched in tests."""
    return datetime.now(UTC)


def _next_exit_out(raw: dict[str, Any] | None) -> ValueNextExit | None:
    return None if raw is None else ValueNextExit(kind=raw["kind"], level=raw["level"])


def _position_out(p: dict[str, Any]) -> ValuePositionOut:
    return ValuePositionOut(
        id=p["id"],
        symbol=p["symbol"],
        list_name=p["list_name"],
        status=p["status"],
        shares=p["shares"],
        avg_cost=p["avg_cost"],
        mark=p["mark"],
        opened_at=p["opened_on"],
        closed_on=p["closed_on"],
        next_exit=_next_exit_out(p["next_exit"]),
        realised_usd=p["realised_usd"],
    )


# --- top ---------------------------------------------------------------------------------------------


@router.get("/top", response_model=ValueTopResponse)
def value_top(
    user: OwnerUser,  # noqa: ARG001
    list_name: Annotated[
        Literal["deep_value", "quality_growth"], Query(alias="list")
    ] = "deep_value",
) -> ValueTopResponse:
    now = _now()
    with vdb.value_read_session() as s:
        if s is None:
            return ValueTopResponse(as_of=now, available=False, list_name=list_name)
        rows = vdb.read_top(s, list_name, 10)
    if rows is None:
        return ValueTopResponse(as_of=now, available=False, list_name=list_name)
    items = [
        ValueTopItem(
            symbol=str(r["symbol"]),
            list_name=list_name,
            verdict=str(r["verdict"]),
            decided_by="claude" if r["decided_by"] == "claude" else "python",
            price=r["price"],
            fair_value=r["fair_value"],
            entry_ceiling=r["entry_ceiling"],
            stop=None,
            half_sell=r["fair_value"],
            mos=r["margin_of_safety"],
            reasons=r["reasons"],
            put_ceiling=r["put_ceiling"],
            age_days=vdb.age_days(vdb.day(r["as_of"]), now),
        )
        for r in rows
    ]
    return ValueTopResponse(as_of=now, available=True, list_name=list_name, items=items)


# --- book --------------------------------------------------------------------------------------------


def _breakers(state: dict[str, dict], now: datetime, trim_pct: float) -> ValueBreakersOut:
    trend = state.get("trend")
    hw = state.get("high_water") or {}
    high, value = hw.get("high"), hw.get("value")
    pct = (
        (float(high) - float(value)) / float(high) * 100.0
        if isinstance(high, int | float) and isinstance(value, int | float) and high > 0
        else None
    )
    return ValueBreakersOut(
        trend=None if not trend else bool(trend.get("brake", False)),
        drawdown=bool(hw["stop"]) if "stop" in hw else None,
        drawdown_pct=pct,
        # offered AND still tappable: the book's own staleness rule (a tap on a stale card is
        # refused), so Home never says "Trim offered" over a card that no longer works
        trim_offered=bool(hw.get("trim_offered_at"))
        and not trim_offer_stale(hw, trim_pct, now.replace(tzinfo=None)),
        trim_episode=hw.get("episode") or None,
        trimmed=bool(hw.get("trimmed")),
    )


@router.get("/book", response_model=ValueBookResponse)
def value_book(user: OwnerUser) -> ValueBookResponse:  # noqa: ARG001
    now = _now()
    cfg = get_config().value
    enabled, release_max = cfg.book.enabled, cfg.book.release.max_closes_per_request
    with vdb.value_read_session() as s:
        if s is None:
            return ValueBookResponse(
                as_of=now, available=False, enabled=enabled, release_max_closes=release_max
            )
        positions = vdb.read_positions(s, "open") or []
        proposals = vdb.read_proposals(s) or []
        funding = vdb.read_funding(s) or []
        state = vdb.book_state(s)
        used = vdb.used_usd(vdb.read_orders(s))
    snapshot = state.get("snapshot") or {}
    net_liq = snapshot.get("net_liq")
    brake = bool((state.get("trend") or {}).get("brake", False))
    ceiling = (
        max(0.0, float(net_liq))
        * cfg.book.ceiling_pct_of_net_liq
        / 100.0
        * (cfg.book.trend_brake_ceiling_pct / 100.0 if brake else 1.0)
        if isinstance(net_liq, int | float)
        else None
    )
    return ValueBookResponse(
        as_of=now,
        available=True,
        enabled=enabled,
        release_max_closes=release_max,
        ceiling_usd=ceiling,
        used_usd=used,
        positions=[_position_out(p) for p in positions],
        proposals=[
            ValueProposalOut(
                id=int(p["id"]),
                kind=p["kind"],
                symbol=str(p["symbol"]),
                list_name=str(p["list_name"]),
                shares=float(p["shares"]),
                price=p["price"],
                cost_usd=p["cost_usd"],
                reason=str(p["reason"]),
                cause="claude" if p["cause"] == "claude" else "python",
                needs_tap=p["needs_tap"],
                status=str(p["status"]),
                created_at=p["created_at"],
                expires_at=p["expires_at"],
                fingerprint=p["fingerprint"],
            )
            for p in proposals
        ],
        funding=[
            ValueFundingOut(
                id=int(f["id"]),
                proposal_id=int(f["proposal_id"]),
                symbol=str(f["symbol"]),
                needed_usd=float(f["needed_usd"]),
                created_at=f["created_at"],
                expires_at=f["expires_at"],
            )
            for f in funding
        ],
        breakers=_breakers(state, now, cfg.book.drawdown_trim_pct),
    )


@router.get("/positions", response_model=ValuePositionsResponse)
def value_positions(
    user: OwnerUser,  # noqa: ARG001
    status: Literal["open", "closed"] = "open",
) -> ValuePositionsResponse:
    now = _now()
    with vdb.value_read_session() as s:
        if s is None:
            return ValuePositionsResponse(as_of=now, available=False, status=status)
        rows = vdb.read_positions(s, status)
    if rows is None:
        return ValuePositionsResponse(as_of=now, available=False, status=status)
    return ValuePositionsResponse(
        as_of=now, available=True, status=status, positions=[_position_out(p) for p in rows]
    )


# --- the ticker file -----------------------------------------------------------------------------------


def _gate(
    check: Check, group: Literal["data_quality", "health", "entry", "timing"]
) -> ValueGateOut:
    return ValueGateOut(
        id=check.id,
        group=group,
        state=check.state,
        value=check.actual,
        threshold=check.threshold,
        detail=check.detail,
    )


def _methods(card: ValueScorecard, ev: ListEvaluation) -> list[ValueMethodOut]:
    if ev.list_name == "quality_growth":
        use: tuple[str, ...] = ("D", "C")
    elif card.company_class in _DEEP_FINANCIAL:
        use = ("PTBV",)
    else:
        use = ("A", "B", "C")
    out: list[ValueMethodOut] = []
    for m in ev.methods:
        used = m.method in use and m.state == "ok" and m.value is not None
        out.append(
            ValueMethodOut(
                method=m.method,
                value=m.value,
                state=m.state,
                detail=m.detail,
                used=used,
                median=used
                and ev.fair_value is not None
                and m.value is not None
                and abs(m.value - ev.fair_value) < 1e-9,
            )
        )
    return out


def _list_out(
    card: ValueScorecard, name: Literal["deep_value", "quality_growth"], eff: dict[str, Any] | None
) -> ValueListOut | None:
    ev = card.lists.get(name)
    if ev is None:
        return None
    baseline = card.verdict_for(name)
    return ValueListOut(
        list_name=name,
        baseline_verdict=baseline,
        verdict=str(eff["verdict"]) if eff else baseline,
        decided_by="claude" if eff and eff["decided_by"] == "claude" else "python",
        fair_value=ev.fair_value,
        effective_fair_value=eff["fair_value"] if eff else ev.fair_value,
        mos=eff["margin_of_safety"] if eff else ev.margin_of_safety,
        required_mos_pct=ev.required_mos_pct,
        entry_ceiling=eff["entry_ceiling"] if eff else ev.entry_ceiling,
        entry=ev.entry,
        timing=ev.timing,
        reasons=list(ev.reasons),
        mos_review=bool(eff["mos_review"]) if eff else ev.mos_review,
        methods=_methods(card, ev),
        gates=[
            *(_gate(c, "entry") for c in ev.entry_checks),
            *(_gate(c, "timing") for c in ev.timing_checks),
        ],
    )


def file_out(
    card: ValueScorecard,
    effective: dict[str, dict],
    *,
    computed_at: datetime | None,
    universe: str | None,
) -> ValueFileOut:
    """One ticker file for the web: the scorecard with the effective verdicts laid over each
    list's baseline. A card with no effective rows (a lookup computed now) reads as Python's."""
    lists = [
        out
        for name in ("deep_value", "quality_growth")
        if (out := _list_out(card, name, effective.get(name))) is not None  # type: ignore[arg-type]
    ]
    ceilings = [
        li.entry_ceiling for li in lists if li.verdict in _PRICED and li.entry_ceiling is not None
    ]
    return ValueFileOut(
        symbol=card.symbol,
        as_of=card.as_of,
        computed_at=computed_at,
        universe=universe,
        company_class=card.company_class,
        data_quality=card.data_quality,
        health=card.health,
        not_applicable_reason=card.not_applicable_reason,
        price=card.price,
        ruleset_version=card.ruleset_version,
        ruleset_hash=card.ruleset_hash,
        gates=[
            *(_gate(c, "data_quality") for c in card.data_quality_checks),
            *(_gate(c, "health") for c in card.health_checks),
        ],
        lists=lists,
        metrics=dict(card.metrics),
        reverse_dcf_implied_growth=card.reverse_dcf_implied_growth,
        put_ceiling=max(ceilings) if ceilings else None,
        adjustments=list(card.adjustments),
    )


def _drivers(drivers_json: Any, clamps: list[str]) -> list[ValueDriverOut]:
    kept = vdb.jsonish(drivers_json, {})
    out: list[ValueDriverOut] = []
    for name, used in kept.items() if isinstance(kept, dict) else []:
        if not isinstance(used, int | float):
            continue
        chosen = float(used)
        clamped = False
        for line in clamps:
            head, _, tail = line.partition(" -> ")
            parts = head.split()
            if len(parts) == 2 and parts[0] == name and tail:
                try:
                    chosen, clamped = float(parts[1]), True
                except ValueError:
                    pass
        bound: Literal["lo", "hi"] | None = None
        if clamped and chosen != used:
            bound = "hi" if chosen > used else "lo"
        out.append(
            ValueDriverOut(name=name, chosen=chosen, used=float(used), clamped=clamped, bound=bound)
        )
    return out


def _distance(kind: str, threshold: Any, actual: Any) -> float | None:
    if not isinstance(threshold, int | float) or not isinstance(actual, int | float):
        return None
    if threshold == 0:
        return None
    if kind in vdb.ABOVE_KILLS:
        return (threshold - actual) / abs(threshold) * 100.0
    if kind in vdb.BELOW_KILLS:
        return (actual - threshold) / abs(threshold) * 100.0
    return None


def claude_out(raw: dict[str, Any] | None) -> ValueClaudeOut | None:
    if raw is None:
        return None
    lists: list[ValueClaudeListOut] = []
    for v in raw["verdicts"]:
        clamps = [str(x) for x in vdb.jsonish(v["clamps_json"], []) if isinstance(x, str)]
        lists.append(
            ValueClaudeListOut(
                list_name=str(v["list_name"]),
                verdict=str(v["verdict"]),
                why=str(v["why"] or ""),
                fair_value=v["fair_value"],
                python_fair_value=v["python_fair_value"],
                cap_applied=bool(v["clamp_bound"]),
                unreliable=v["unreliable"],
                drivers=_drivers(v["drivers_json"], clamps),
                clamps=clamps,
                backend=str(v["backend"]),
            )
        )
    notes: list[ValueNoteOut] = []
    n = raw["notes"]
    if n is not None:
        notes = [ValueNoteOut(kind=k, text=str(n[k])) for k in _NOTE_KINDS if n[k]]
        if n["review_state"] or n["review_why"]:
            text = " ".join(x for x in (n["review_state"], n["review_why"]) if x)
            notes.append(ValueNoteOut(kind="review", text=text))
    return ValueClaudeOut(
        read_at=raw["read_at"],
        lists=lists,
        notes=notes,
        kill_triggers=[
            ValueKillTriggerOut(
                name=str(t["kind"]),
                threshold=t["threshold"],
                actual=t["last_actual"],
                state=t["last_state"],
                distance_pct=_distance(str(t["kind"]), t["threshold"], t["last_actual"]),
            )
            for t in raw["kill_triggers"]
        ],
        facts=[
            ValueFactOut(
                text=str(f["kind"])
                + ("" if f["value"] is None else f" {f['value']:g} {f['unit']}"),
                quote=str(f["quote"]),
                filing=str(f["accn"]),
            )
            for f in raw["facts"]
        ],
    )


def _reevaluations(rows: list[dict[str, Any]]) -> list[ValueReevaluationOut]:
    out: list[ValueReevaluationOut] = []
    for r in rows:
        triggers = vdb.jsonish(r["triggers_json"], [])
        before = vdb.jsonish(r["plan_before_json"], {})
        after = vdb.jsonish(r["plan_after_json"], {})
        out.append(
            ValueReevaluationOut(
                id=int(r["id"]),
                list_name=str(r["list_name"]),
                session=vdb.day(r["session"]),
                last_session=vdb.day(r["last_session"]),
                severity="major" if r["severity"] == "major" else "minor",
                triggers=[t for t in triggers if isinstance(t, dict)],
                plan_before=before if isinstance(before, dict) else {},
                plan_after=after if isinstance(after, dict) else {},
                review_state=r["review_state"],
            )
        )
    return out


def _plan(session: Any, symbol: str) -> ValuePlanOut | None:
    held = [p for p in (vdb.read_positions(session, "open") or []) if p["symbol"] == symbol]
    if not held:
        return None
    p = held[0]
    plan = vdb.jsonish(p["plan_json"], {})
    plan = plan if isinstance(plan, dict) else {}
    return ValuePlanOut(
        position_id=p["id"],
        list_name=p["list_name"],
        opened_at=p["opened_on"],
        shares=p["shares"],
        avg_cost=p["avg_cost"],
        next_exit=_next_exit_out(p["next_exit"]),
        stop=plan.get("stop") if isinstance(plan.get("stop"), int | float) else None,
        half_sold=bool(plan.get("half_sold")),
        fair_value=plan.get("fair_value"),
        effective_fair_value=plan.get("effective_fair_value"),
    )


def side_blocks(
    session: Any, symbol: str
) -> tuple[ValueClaudeOut | None, list[ValueReevaluationOut], ValuePlanOut | None]:
    """What sits beside a ticker file whether it is stored or computed now: Claude's block (labelled
    as Claude's), a held name's re-evaluations and its plan."""
    return (
        claude_out(vdb.read_claude(session, symbol)),
        _reevaluations(vdb.read_reevaluations(session, symbol)),
        _plan(session, symbol),
    )


def stored_response(session: Any, row: dict[str, Any], now: datetime) -> ValueTickerResponse:
    """The stored ticker file as the web shows it (``computed: "stored"``)."""
    symbol = str(row["symbol"]).upper()
    card = ValueScorecard.model_validate_json(row["scorecard_json"])
    claude, reevaluations, plan = side_blocks(session, symbol)
    return ValueTickerResponse(
        as_of=now,
        available=True,
        symbol=symbol,
        computed="stored",
        age_days=vdb.age_days(card.as_of, now),
        file=file_out(
            card,
            vdb.read_effective(session, symbol),
            computed_at=vdb.dt(row["computed_at"]),
            universe=row["universe"],
        ),
        claude=claude,
        reevaluations=reevaluations,
        plan=plan,
    )


@router.get("/{symbol}", response_model=ValueTickerResponse)
def value_ticker(symbol: str, user: OwnerUser) -> ValueTickerResponse:
    """The ticker file for a name: the stored one when it is current, else computed now from
    research.db (src/api/value_lookup.py). 404 when neither value.db nor research.db knows it."""
    from src.api.value_lookup import lookup

    try:
        found = lookup(symbol, user)
    except ValueError as exc:  # a scorecard this build cannot read (an older ruleset)
        raise HTTPException(
            status_code=404, detail=f"No readable ticker file for {symbol.upper()}"
        ) from exc
    if found is None:
        raise HTTPException(status_code=404, detail=f"No ticker file for {symbol.upper()}")
    return found
