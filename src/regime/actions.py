"""The counterfactual record of sizing actions (spec section 10): `sizing_actions` rows.

Every time the market regime, the leveraged-ETF ceiling or (a later task) Claude's cut makes a
CSP smaller than the deterministic size it would otherwise have been, or stops it, one row says
what the size would have been, what was sent, and why. A human reads the outcome later
(`scripts/sizing_report.py`); nothing here is ever read back by the engine, the sizer or
execution.

The same contract is trimmed on every 15-minute scan, so the write is an **upsert** keyed on
(``key`` or the candidate id, ``kind``, the ET day): the first row of the day is kept and later
calls only refresh ``sent_contracts``, ``reason`` and ``order_id`` (ruling 20). A CSP that was
never sent is keyed per *name*, ``csp:<SYM>:<kind>:<ET day>``, so one blocked name is one row
however many strikes and cycles it was rejected on (ruling 44).

Every function here swallows its own errors: a counterfactual write must never fail a scan or an
order.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from src.common.market_hours import today_et
from src.common.schemas import MarketRegime, Strategy, TradeCandidate
from src.storage.db import session_scope
from src.storage.models import SizingActionRow

log = logging.getLogger(__name__)

# Gate reasons that mean "the market regime said no" (engine/regime_limits.py), as opposed to
# the book (concentration, cash, ...): a name rejected only for these is a regime block.
REGIME_REASONS: tuple[str, ...] = (
    "regime_budget",
    "regime_ceiling",
    "leveraged_ceiling",
    "regime_daily_limit",
)

# The scale-in ladder's gate reasons and the counterfactual kind each is recorded under. The
# sizer rejects these before a candidate reaches the gate, so they come in as generator rejects.
LADDER_KINDS: dict[str, str] = {
    "loss_exit_cooldown": "loss_exit_cooldown",
    "scale_in_zone_not_reached": "scale_in_zone",
}


def _regime_of(cand: TradeCandidate) -> str:
    return cand.sizing.regime.value if cand.sizing is not None else MarketRegime.NORMAL.value


def record_action(
    *,
    cand: TradeCandidate,
    kind: str,
    deterministic: int,
    sent: int,
    reason: str,
    picture_version: str | None = None,
    order_id: int | None = None,
    key: str | None = None,
    session: Session | None = None,
) -> None:
    """Upsert one `sizing_actions` row for (*key* or the candidate id, *kind*, today's ET day).

    The first row of the day is kept (``deterministic_contracts`` and ``entry_iv`` are taken
    from it); later calls update ``sent_contracts``, ``reason`` and, when given, ``order_id``.
    With *session* the write joins the caller's transaction (inside a savepoint, so a failure
    here cannot poison the caller's work); without it the write has its own. Never raises.
    """
    try:
        day = today_et()
        record_key = key or cand.candidate_id

        def write(s: Session) -> None:
            row = (
                s.query(SizingActionRow)
                .filter_by(record_key=record_key, kind=kind, action_day=day)
                .first()
            )
            if row is None:
                s.add(
                    SizingActionRow(
                        created_at=datetime.now(UTC),
                        candidate_id=cand.candidate_id,
                        underlying=cand.underlying,
                        strategy=cand.strategy.value,
                        right=cand.right.value,
                        strike=cand.strike,
                        expiry=cand.expiry,
                        premium=cand.premium,
                        kind=kind,
                        regime=_regime_of(cand),
                        picture_version=picture_version,
                        deterministic_contracts=deterministic,
                        sent_contracts=sent,
                        reason=reason,
                        action_day=day,
                        order_id=order_id,
                        entry_iv=cand.current_iv,
                        record_key=record_key,
                    )
                )
            else:
                row.sent_contracts = sent
                row.reason = reason
                if order_id is not None:
                    row.order_id = order_id

        if session is not None:
            with session.begin_nested():
                write(session)
        else:
            with session_scope() as s:
                write(s)
    except Exception:
        log.warning("sizing action not recorded (%s %s)", kind, cand.candidate_id, exc_info=True)


def link_order(candidate_id: str, order_id: int, *, session: Session | None = None) -> None:
    """Attach *order_id* to the not-yet-linked action rows of *candidate_id*. Never raises."""
    try:

        def write(s: Session) -> None:
            for row in (
                s.query(SizingActionRow)
                .filter(
                    SizingActionRow.candidate_id == candidate_id,
                    SizingActionRow.order_id.is_(None),
                    SizingActionRow.record_key == candidate_id,
                )
                .all()
            ):
                row.order_id = order_id

        if session is not None:
            with session.begin_nested():
                write(session)
        else:
            with session_scope() as s:
                write(s)
    except Exception:
        log.warning("sizing actions not linked to order %s", order_id, exc_info=True)


def _describe(cand: TradeCandidate) -> str:
    note = cand.sizing
    if note is None:
        return ""
    if note.ceiling_kind == "leveraged_ceiling" and note.leverage is not None:
        return f"leveraged ETF {note.leverage}x, {note.leverage_tier or 'calm'} tier"
    return f"{note.regime_index} {note.regime.value}"


def _verdict_parts(verdict: Any) -> tuple[bool, list[str]]:
    """``(passed, reasons)`` from a RiskVerdict (or anything shaped like one)."""
    passed = getattr(getattr(verdict, "verdict", None), "value", None) == "pass"
    return passed, list(getattr(verdict, "reasons", []) or [])


def record_scan_actions(
    *,
    top: list[TradeCandidate],
    scored: list[TradeCandidate],
    verdicts: dict[str, Any],
    picture_version: str | None = None,
    generator_rejects: list[tuple[TradeCandidate, list[str]]] | None = None,
) -> None:
    """Record what the regime did in one scan: trims and floor lots on the surfaced CSPs, and
    the names it stopped outright.

    * a surfaced candidate cut below its capital-fitted size is recorded under its ceiling kind
      (``regime_ceiling`` / ``leveraged_ceiling``), or ``regime_budget`` when only the scaled
      budget cut it; a floor lot is recorded as ``regime_floor_lot``;
    * a name none of whose strikes passed, whose best-ranked candidate was rejected only for
      regime reasons, is recorded once as a never-sent row (``sent_contracts`` 0);
    * a name the scale-in ladder stopped (*generator_rejects*: contracts the sizer refused,
      best-ranked first, whose only reasons are ``loss_exit_cooldown`` /
      ``scale_in_zone_not_reached``) is recorded once per name, kind and ET day, as
      ``loss_exit_cooldown`` or ``scale_in_zone``.

    *scored* is expected best-ranked first (the scan passes it sorted by blended score). Never
    raises.
    """
    try:
        day = today_et().isoformat()
        for cand in top:
            if cand.strategy != Strategy.CASH_SECURED_PUT or cand.sizing is None:
                continue
            note = cand.sizing
            if note.floor_lot:
                record_action(
                    cand=cand,
                    kind="regime_floor_lot",
                    deterministic=cand.contracts,
                    sent=cand.contracts,
                    reason=f"guaranteed floor lot under {_describe(cand)}",
                    picture_version=picture_version,
                )
            if note.pre_regime_contracts > cand.contracts:
                record_action(
                    cand=cand,
                    kind=note.ceiling_kind or "regime_budget",
                    deterministic=note.pre_regime_contracts,
                    sent=cand.contracts,
                    reason=(
                        f"{_describe(cand)}: {note.pre_regime_contracts} -> {cand.contracts} "
                        f"(per-trade ceiling {note.per_trade_cap})"
                    ),
                    picture_version=picture_version,
                )

        by_name: dict[str, list[TradeCandidate]] = {}
        for cand in scored:
            if cand.strategy == Strategy.CASH_SECURED_PUT:
                by_name.setdefault(cand.underlying, []).append(cand)
        for underlying, cands in by_name.items():
            parts = {c.candidate_id: _verdict_parts(verdicts.get(c.candidate_id)) for c in cands}
            if any(passed for passed, _ in parts.values()):
                continue
            for cand in cands:  # best-ranked first
                reasons = parts[cand.candidate_id][1]
                if reasons and all(r in REGIME_REASONS for r in reasons):
                    kind = reasons[0]
                    pre = cand.sizing.pre_regime_contracts if cand.sizing else cand.contracts
                    record_action(
                        cand=cand,
                        kind=kind,
                        deterministic=pre,
                        sent=0,
                        reason=f"rejected by the market regime ({', '.join(reasons)})",
                        picture_version=picture_version,
                        key=f"csp:{underlying}:{kind}:{day}",
                    )
                    break

        ladder_done: set[str] = set()
        for cand, reasons in generator_rejects or []:
            if cand.strategy != Strategy.CASH_SECURED_PUT or cand.underlying in ladder_done:
                continue
            if not reasons or not all(r in LADDER_KINDS for r in reasons):
                continue  # something else also stopped it: not the ladder's doing alone
            ladder_done.add(cand.underlying)
            kind = LADDER_KINDS[
                "loss_exit_cooldown" if "loss_exit_cooldown" in reasons else reasons[0]
            ]
            record_action(
                cand=cand,
                kind=kind,
                deterministic=cand.contracts,
                sent=0,
                reason=f"stopped by the scale-in ladder ({', '.join(reasons)})",
                picture_version=picture_version,
                key=f"csp:{cand.underlying}:{kind}:{day}",
            )
    except Exception:
        log.warning("scan sizing actions not recorded", exc_info=True)
