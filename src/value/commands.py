"""Apply the value command kinds (Part 6, spec §9.7) inside value.db. Pure over a Session; the entrypoint claims
the app_commands rows and marks them. Paper only for the kinds that change order state."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import date, datetime

from pydantic import ValidationError
from sqlalchemy.orm import Session

from src.common.config import get_config
from src.common.value_commands import VALUE_ORDER_KINDS, proposal_fingerprint
from src.common.value_types import MarketFacts
from src.value import cards, outbox, service
from src.value.book import BookRefused, decide, trim_to_half
from src.value.claude_reads import queue_read
from src.value.schemas import Fingerprint
from src.value.store import ValueProposalRow, ValueTickerFileRow

log = logging.getLogger(__name__)


class ValueCommandFailed(Exception):
    def __init__(self, reason: str, detail: dict | None = None) -> None:
        super().__init__(reason)
        self.reason, self.detail = reason, detail or {}


Handler = Callable[[Session, dict, str, datetime], dict]
HANDLERS: dict[str, Handler] = {}

# The read-side kinds score a name, so they also read research.db and the market facts the
# entrypoint fetches (src/value opens no SEC client and imports no data layer).
ResearchFactory = Callable[[], AbstractContextManager[Session | None]]
MarketFn = Callable[[str], tuple[MarketFacts, date | None]]  # symbol -> (facts, next earnings)


@dataclass(frozen=True)
class ReadContext:
    research: ResearchFactory | None = None
    market: MarketFn | None = None


ReadHandler = Callable[[Session, dict, str, datetime, ReadContext], dict]
READ_HANDLERS: dict[str, ReadHandler] = {}


def _register(kind: str) -> Callable[[Handler], Handler]:
    def wrap(fn: Handler) -> Handler:
        HANDLERS[kind] = fn
        return fn

    return wrap


def _register_read(kind: str) -> Callable[[ReadHandler], ReadHandler]:
    def wrap(fn: ReadHandler) -> ReadHandler:
        READ_HANDLERS[kind] = fn
        return fn

    return wrap


def apply(
    vs: Session,
    kind: str,
    payload: dict,
    *,
    requested_by: str,
    now: datetime,
    live: bool,
    research: ResearchFactory | None = None,
    market: MarketFn | None = None,
) -> dict:
    """One command. Raises ValueCommandFailed with a machine reason; the caller marks the command.
    The read-side kinds (snapshot, refresh, analyse) change no order state and run in live too."""
    if live and kind in VALUE_ORDER_KINDS:
        raise ValueCommandFailed("not_paper")
    read = READ_HANDLERS.get(kind)
    if read is not None:
        return read(vs, payload, _by(requested_by), now, ReadContext(research, market))
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


def _score(
    vs: Session,
    symbol: str,
    ctx: ReadContext,
    now: datetime,
    *,
    fingerprint: dict | None = None,
) -> Fingerprint:
    if ctx.research is None:
        raise ValueCommandFailed("research_unavailable")
    facts, earnings = ctx.market(symbol) if ctx.market is not None else (None, None)
    with ctx.research() as rs:
        if rs is None:
            raise ValueCommandFailed("research_unavailable")
        try:
            return service.score_one(
                vs,
                rs,
                symbol,
                now=now,
                fingerprint=fingerprint,
                facts=facts,
                next_earnings=earnings,
            )
        except ValueError as exc:  # no price bars for the name
            raise ValueCommandFailed("no_data", {"error": str(exc)}) from exc


def _viewed(vs: Session, symbol: str, now: datetime) -> ValueTickerFileRow:
    vs.flush()
    row = vs.get(ValueTickerFileRow, symbol)
    assert row is not None
    row.last_viewed_at = now
    return row


def _refresh_one(vs: Session, symbol: str, by: str, now: datetime, ctx: ReadContext) -> dict:
    _score(vs, symbol, ctx, now)
    row = _viewed(vs, symbol, now)
    if by == "telegram":  # the asker is in the chat: post the fresh one-name card there
        outbox.queue_ticker_card(vs, symbol, now)
    return {"symbol": symbol, "universe": row.universe, "as_of": row.as_of.isoformat()}


@_register_read("value_refresh")
def _refresh(vs: Session, payload: dict, by: str, now: datetime, ctx: ReadContext) -> dict:
    return _refresh_one(vs, str(payload["symbol"]).upper(), by, now, ctx)


@_register_read("value_snapshot")
def _snapshot(vs: Session, payload: dict, by: str, now: datetime, ctx: ReadContext) -> dict:
    """Spec §6.9 / ruling 19: the API showed this name's file. Mark it viewed (the follow window's
    input); when the API carried the input set it computed from and that is not what is stored,
    persist a scorecard for exactly that set, recording ``detail: "moved"`` when the value
    process's own recomputation from it comes out different (the research worker moved since)."""
    symbol = str(payload["symbol"]).upper()
    raw = payload.get("fingerprint") or {}
    row = vs.get(ValueTickerFileRow, symbol)
    if row is None and not raw:
        return _refresh_one(vs, symbol, by, now, ctx)  # nothing stored, nothing carried
    result: dict = {"symbol": symbol}
    if raw:
        try:
            carried = Fingerprint.model_validate(raw)
        except ValidationError as exc:
            raise ValueCommandFailed("bad_fingerprint") from exc
        if row is None or row.fingerprint_key != carried.key():
            own = _score(vs, symbol, ctx, now, fingerprint=raw)
            if own.key() != carried.key():
                result["detail"] = "moved"
    _viewed(vs, symbol, now)
    return result


@_register_read("value_analyse")
def _analyse(vs: Session, payload: dict, by: str, now: datetime, ctx: ReadContext) -> dict:
    """Spec §8.5: Claude's read at the "request" priority (the operator's requests come first)."""
    if not get_config().value.claude.enabled:
        raise ValueCommandFailed("claude_off")
    symbol = str(payload["symbol"]).upper()
    queue_read(vs, symbol, kind="standard", reason="request", now=now)
    return {"symbol": symbol, "queued": True}


def outcome_line(kind: str, result: dict | None, reason: str | None) -> str:
    """The plain reply the value process posts to TELEGRAM_THREAD_VALUE after a tap (the words are cards.py's)."""
    return cards.outcome_line(kind, result, reason)


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
