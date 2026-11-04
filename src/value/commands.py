"""Apply the value command kinds (Part 6, spec §9.7) inside value.db. Pure over a Session; the entrypoint claims
the app_commands rows and marks them. Paper only for the kinds that change order state."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from src.common.value_commands import VALUE_ORDER_KINDS, proposal_fingerprint
from src.value.book import BookRefused, decide, trim_to_half
from src.value.store import ValueProposalRow

log = logging.getLogger(__name__)


class ValueCommandFailed(Exception):
    def __init__(self, reason: str, detail: dict | None = None) -> None:
        super().__init__(reason)
        self.reason, self.detail = reason, detail or {}


Handler = Callable[[Session, dict, str, datetime], dict]
HANDLERS: dict[str, Handler] = {}


def _register(kind: str) -> Callable[[Handler], Handler]:
    def wrap(fn: Handler) -> Handler:
        HANDLERS[kind] = fn
        return fn

    return wrap


def apply(
    vs: Session, kind: str, payload: dict, *, requested_by: str, now: datetime, live: bool
) -> dict:
    """One command. Raises ValueCommandFailed with a machine reason; the caller marks the command."""
    if live and kind in VALUE_ORDER_KINDS:
        raise ValueCommandFailed("not_paper")
    fn = HANDLERS.get(kind)
    if fn is None:
        raise ValueCommandFailed("unknown_kind")
    return fn(vs, payload, _by(requested_by), now)


def _by(requested_by: str) -> str:
    return requested_by if requested_by in ("web", "telegram", "cli") else "web"


def _decision(vs: Session, payload: dict, by: str, now: datetime, *, approve: bool) -> dict:
    pid = int(payload["proposal_id"])
    row = vs.get(ValueProposalRow, pid)
    if row is None:
        raise ValueCommandFailed("no_such_proposal")
    if (
        proposal_fingerprint(row.id, row.kind, row.symbol, row.shares, row.created_at)
        != payload["fingerprint"]
    ):
        raise ValueCommandFailed("stale_proposal")
    status = decide(vs, pid, approve=approve, now=now, by=by)
    if status not in ("approved", "rejected"):
        raise ValueCommandFailed(status, {"proposal_id": pid})  # already_<status> | expired
    return {"proposal_id": pid, "decision": status, "symbol": row.symbol, "kind": row.kind}


@_register("value_approve")
def _approve(vs: Session, payload: dict, by: str, now: datetime) -> dict:
    return _decision(vs, payload, by, now, approve=True)


@_register("value_reject")
def _reject(vs: Session, payload: dict, by: str, now: datetime) -> dict:
    return _decision(vs, payload, by, now, approve=False)


@_register("value_trim")
def _trim(vs: Session, payload: dict, by: str, now: datetime) -> dict:
    try:
        created = trim_to_half(vs, episode=str(payload["episode"]), by=by, now=now)
    except BookRefused as exc:
        raise ValueCommandFailed(exc.reason) from exc
    return {"episode": payload["episode"], "proposals": created}


def outcome_line(kind: str, result: dict | None, reason: str | None) -> str:
    """The plain reply the value process posts to TELEGRAM_THREAD_VALUE after a tap."""
    return f"{kind}: {reason or 'done'}"  # Task 4 moves the wording to cards.outcome_line


# --- the drain (the entrypoint's loop body, testable without importing scripts/run_value.py) ---

# (command id, kind, payload, requested_by, confirm_token), read from app_commands by the caller
CommandTuple = tuple[int, str, dict, str, str | None]
ApplyFn = Callable[
    [str, dict, str], dict
]  # (kind, payload, requested_by) -> result; commits value.db
MarkFn = Callable[[int, dict | None, str | None, dict | None], None]  # (id, result, reason, detail)


@dataclass(frozen=True, slots=True)
class DrainOutcome:
    cid: int
    kind: str
    requested_by: str
    result: dict | None
    reason: str | None


def drain(rows: Iterable[CommandTuple], apply_fn: ApplyFn, mark_fn: MarkFn) -> list[DrainOutcome]:
    """Apply each claimed command, then mark it: value.db commits inside ``apply_fn`` before
    ``mark_fn`` runs, so a crash between the two leaves the command pending and the next drain
    re-applies it, which an idempotent handler answers ``already_<status>``. A command still
    awaiting its live confirmation is skipped (it waits for a human, as in the trading drain);
    one bad command never stops the rest."""
    out: list[DrainOutcome] = []
    for cid, kind, payload, by, confirm_token in rows:
        if confirm_token is not None:
            continue
        result: dict | None = None
        reason: str | None = None
        detail: dict | None = None
        try:
            result = apply_fn(kind, payload, by)
        except ValueCommandFailed as exc:
            reason, detail = exc.reason, exc.detail
        except Exception as exc:  # noqa: BLE001 - one bad command never stops the drain
            log.exception("value: command %d (%s) raised", cid, kind)
            reason, detail = "handler_error", {"error": str(exc)}
        mark_fn(cid, result if reason is None else None, reason, detail)
        out.append(DrainOutcome(cid, kind, by, result, reason))
    return out
