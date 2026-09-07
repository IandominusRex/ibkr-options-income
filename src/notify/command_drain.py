"""The command-drain loop's handlers and the ``drain_once`` entry point.

Runs inside ``approval_service`` (the process that holds the exec connection). Every
``interval`` seconds, the loop reads all ``pending`` commands and applies each one
through its registered handler. In M1 ``HANDLERS`` is empty — the only observable
behaviour is the unknown-kind path and the expiry sweep. This is deliberate: the
machinery is proven before anything can use it.

Design points that are not negotiable (see M1-write-foundation.md Task 1.5):

1. ``drain_once`` never raises. A handler that throws marks its own command ``failed``
   with the exception text and the loop continues to the next one.
2. An unknown kind is ``failed``, not skipped — a command sitting ``pending`` forever
   is the failure mode the operator cannot see.
3. A command with an outstanding ``confirm_token`` is **skipped**, not failed — it is
   waiting for a human, which is not an error. Skipping does not count toward the
   return value.
4. The loop starts even when ``ib is None``. Commands that do not need the broker
   (reject, halt, resume, set_autonomy, universe edits) must still apply when TWS is
   down. Handlers that do need it fail their own command with ``broker_unavailable``.
5. ``expire_stale_commands`` runs once per drain, using ``approval.ttl_minutes``.
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from ib_async import IB
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.common.config import get_config
from src.common.schemas import ApprovalStatus
from src.storage.app_commands import (
    expire_stale_commands,
    mark_applied,
    mark_failed,
    pending_commands,
)
from src.storage.db import session_scope
from src.storage.models import ApprovalRow, RiskVerdictRow
from src.storage.orders import active_order_for
from src.storage.system_settings import set_setting

log = logging.getLogger(__name__)

CommandHandler = Callable[..., Any]


class CommandFailed(Exception):
    """Raised by a handler to fail its own command with a machine-readable reason.

    The drain catches this and marks the command ``failed`` with the reason as
    ``result.reason`` (plus any ``detail``), so a receipt can render the cause
    instead of a raw exception string. Any other exception is a handler bug and
    is recorded as ``handler_error`` with the exception text.
    """

    def __init__(self, reason: str, detail: dict | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


# system_settings key: ISO UTC timestamp of the last completed drain cycle. Written
# AFTER the work, never before, so a hung handler cannot make the loop look healthy.
# M2's /options/controls reads this to tell an operator their click is queued and
# nothing is picking it up (spec §4.1, M1 Task 1.5 design point 6).
COMMAND_DRAIN_HEARTBEAT_KEY = "command_drain_heartbeat"

# Populated by M3 onwards; empty in M1.
HANDLERS: dict[str, CommandHandler] = {}


def register(kind: str) -> Callable[[CommandHandler], CommandHandler]:
    """Decorator. Each later milestone registers its own kinds here."""

    def decorator(fn: CommandHandler) -> CommandHandler:
        HANDLERS[kind] = fn
        return fn

    return decorator


async def drain_once(ib: IB | None, bot: Any, chat_id: str) -> int:
    """Apply every pending command. Returns how many were processed. Never raises.

    A command awaiting confirmation (``confirm_token`` is set) is skipped and does not
    count toward the return value. An unknown kind is failed with ``unknown_kind``.
    A throwing handler marks its own command ``failed`` and the loop continues.
    """
    with session_scope() as s:
        # 1. Expire stale commands past their TTL.
        ttl = get_config().approval.ttl_minutes
        expired = expire_stale_commands(s, ttl)
        if expired:
            log.info("command drain: expired %d stale command(s)", expired)

        # 2. Read pending commands (after expiry, so expired ones are not processed).
        commands = pending_commands(s)
        s.commit()  # release the read lock before processing

    processed = 0
    for cmd in commands:
        # Skip commands awaiting a human confirmation.
        if cmd.confirm_token is not None:
            log.debug("command drain: skipping %d (awaiting confirmation)", cmd.id)
            continue

        try:
            handler = HANDLERS.get(cmd.kind)
            if handler is None:
                _fail(cmd.id, "unknown_kind")
                continue

            result = handler(ib=ib, bot=bot, chat_id=chat_id, command=cmd, payload=cmd.payload)
            # A handler may be a coroutine function (M4 Task 4.2's "promote" re-runs a scan
            # path and must await it) or a plain sync function (every earlier handler) — both
            # are supported so existing handlers need no change.
            if inspect.isawaitable(result):
                result = await result
            # Handlers return the result dict stored on the command. The M1
            # machinery wrapped everything as {"ok": True, "result": ...}; a
            # handler's own dict is stored verbatim so a receipt can read
            # fields like "decision" straight off `result` (M3 Task 3.1).
            _applied(cmd.id, result)
            processed += 1
        except CommandFailed as exc:
            log.info("command drain: %s command %d failed: %s", cmd.kind, cmd.id, exc.reason)
            _fail(cmd.id, exc.reason, exc.detail)
        except Exception as exc:
            log.exception("command drain: handler for %s raised", cmd.kind)
            _fail(cmd.id, "handler_error", {"error": str(exc)})

    # Heartbeat written AFTER the work, never before — a hung handler cannot make the
    # loop look healthy. Written even when nothing was processed, so a stalled queue
    # is distinguishable from a dead loop (M2 /options/controls reads this).
    set_setting(
        COMMAND_DRAIN_HEARTBEAT_KEY,
        datetime.now(UTC).isoformat(),
    )
    return processed


def _applied(command_id: int, result: dict) -> None:
    with session_scope() as s:
        mark_applied(s, command_id, result)


def _fail(command_id: int, reason: str, detail: dict | None = None) -> None:
    with session_scope() as s:
        mark_failed(s, command_id, reason, detail)


# ---------------------------------------------------------------------------
# M3 Task 3.1 — approve / reject.
#
# The handler calls ``_process_button`` and does not reimplement one line of it.
# If a future refactor makes the web path diverge from the Telegram path, every
# safety property tested against Telegram silently stops covering the web —
# ``test_the_handler_calls_process_button_rather_than_reimplementing_it`` exists
# to make that refactoring loudly fail instead.
#
# The import is deferred to call time because ``approval_service`` imports this
# module at its own import time (for ``drain_once``); a module-level import
# would be circular.
# ---------------------------------------------------------------------------


def _process_button(approval_id: int, action: str) -> tuple[bool, str, str]:
    """Indirection to ``src.notify.approval_service._process_button``.

    Deferred so ``approval_service`` (which imports this module at import time
    for ``drain_once``) is not a circular import. Tests monkeypatch THIS name to
    assert the handler delegates rather than reimplementing.
    """
    from src.notify.approval_service import _process_button as real

    return real(approval_id, action)


def _apply_approval_decision(*, command: Any, action: str, **_: Any) -> dict:
    """Apply an approve or reject intent by calling ``_process_button`` unchanged.

    Returns the result dict stored on the command. Raises ``CommandFailed`` to
    fail the command. ``ib`` is deliberately unused: a reject with TWS down
    must still apply, and an approve only creates a ``QUEUED`` ``OrderRow``
    that ``process_queued_orders`` picks up when the exec connection returns
    (existing behaviour). The handler sends no Telegram message — notification
    stays with the existing order poll loop, which already reports fills; two
    notification paths for one order is how duplicates start.
    """
    from src.api.models.commands import ApprovePayload, RejectPayload

    payload_cls = ApprovePayload if action == "approve" else RejectPayload
    payload = payload_cls(**command.payload)

    found, decision_text, _short = _process_button(payload.approval_id, action)
    if not found:
        raise CommandFailed("approval_not_found")
    # An already-decided approval is NOT a failure: ``_process_button`` returned
    # "Already <status>" and mutated nothing, but the intent's goal — this
    # approval is decided — is satisfied. Marking it failed would make a normal
    # Telegram-vs-console race look like a malfunction.
    return {"decision": decision_text, "approval_id": payload.approval_id}


@register("approve")
def _approve(*, command: Any, **_: Any) -> dict:
    """Apply an approve intent by calling ``_process_button`` unchanged."""
    return _apply_approval_decision(command=command, action="approve")


@register("reject")
def _reject(*, command: Any, **_: Any) -> dict:
    """Apply a reject intent by calling ``_process_button`` unchanged."""
    return _apply_approval_decision(command=command, action="reject")


# ---------------------------------------------------------------------------
# M4 Task 4.2 — promote.
#
# The API-boundary guard (`src.api.routers.commands.assert_promotable`, M4 Task 4.1) already
# refused a non-promotable stage before this command row could exist. That guard read a
# *stored* `RiskVerdictRow` — a snapshot of what a past scan saw. This handler is the belt of
# the belt-and-braces: it re-prices and re-gates the requested contract right now, through the
# exact same generators/scoring/Rules-Engine path a `/scan TICKER` would use, and only raises
# an approval if the fresh run still clears the gate. Nothing from the stored row reaches the
# approval except the (candidate_id, symbol, strategy, strike, expiry) used to select which
# contract to look for — every number on the resulting approval comes from the fresh run.
# ---------------------------------------------------------------------------


def _original_stage(candidate_id: str) -> str | None:
    """The most recent stored ``risk_verdicts`` stage for *candidate_id*, or ``None``.

    Mirrors ``src.api.routers.commands.assert_promotable``'s query exactly (same
    ordering: ``created_at`` descending, ``id`` descending, limit 1) so the two
    lookups agree on what "the assessed row" means — but this is a plain read, not
    an HTTP-raising guard, since this module is not the API layer and cannot import
    that function without pulling in FastAPI's `HTTPException`.

    Returns ``None`` when no row exists at all — which should not normally happen
    since the API guard already required one to exist before this command row
    could be created, but the drain handler does not share that guarantee
    structurally (see ``test_no_promote_path_exists_for_a_gate_rejected_contract``,
    which enqueues a promote command directly, bypassing the API guard entirely).
    """
    with session_scope() as s:
        row = s.execute(
            select(RiskVerdictRow)
            .where(RiskVerdictRow.candidate_id == candidate_id)
            .order_by(RiskVerdictRow.created_at.desc(), RiskVerdictRow.id.desc())
            .limit(1)
        ).scalar_one_or_none()
        return row.stage if row is not None else None


@register("promote")
async def _promote(*, command: Any, ib: Any, bot: Any, chat_id: str, **_: Any) -> dict:
    """Re-price and re-gate a promoted candidate; raise a PENDING approval if it still clears.

    Never places, sizes, or bypasses the Rules Engine — it drives the identical
    `_price_and_gate_ticker` path the Telegram `/scan TICKER` command uses (chain fetch,
    analytics, CC/CSP screens, scoring, `validate_candidates`), then searches the gate-passed
    output for the exact (strategy, strike, expiry) the operator asked to promote. Raises
    ``CommandFailed`` with the most specific reason available when it cannot (see
    ``docs/web/commands.md``'s promote failure-reason table). ``ib is None`` fails immediately
    with ``broker_unavailable`` — a promote needs a fresh chain and cannot be honestly served
    without one. A `TickerPricingAborted` (the analytics or portfolio fetch failed outright,
    before a chain was even screened) folds into ``chain_unavailable`` too — same "no fresh,
    honest price for this ticker" umbrella a chain-fetch failure already reports under — with
    the failed stage carried in the detail rather than inventing a fifth reason code.
    """
    from src.api.models.commands import PromotePayload
    from src.orchestrator.scan import TickerPricingAborted, _price_and_gate_ticker

    if ib is None:
        raise CommandFailed("broker_unavailable")

    payload = PromotePayload(**command.payload)

    try:
        priced = await _price_and_gate_ticker(ib, payload.symbol)
    except TickerPricingAborted as exc:
        raise CommandFailed(
            "chain_unavailable", {"stage": exc.stage, "detail": exc.detail}
        ) from exc

    # Check chain failure before searching `scored` at all — an empty chain from a real
    # failure must not be reported as "contract not priced".
    if priced.chain_error is not None:
        raise CommandFailed("chain_unavailable", {"detail": priced.chain_error})

    match = next(
        (
            c
            for c in priced.scored
            if c.strategy.value == payload.strategy
            and c.strike == payload.strike
            and c.expiry == payload.expiry
            and c.underlying == payload.symbol
        ),
        None,
    )
    if match is None:
        raise CommandFailed("contract_not_priced", {"priced_count": len(priced.quotes)})

    verdict = priced.verdict_map.get(match.candidate_id)
    if verdict is None or verdict.verdict.value != "pass":
        reasons = list(verdict.reasons) if verdict is not None else []
        raise CommandFailed("gate_rejected", {"reasons": reasons})

    # The score-floor check is a re-derivation safeguard, not a re-enforcement of the same
    # bar for every stage: a `score_floor` candidate is, by definition, one whose score
    # already sits below this minimum — that's the entire reason it's in that stage, and
    # promoting it is letting the operator go below a bar they configured themselves
    # (P2-design.md §5.2), not something to reject again. Every other original stage
    # (`dedupe`, `top_n`, unknown/missing) keeps the check: the fresh run might reveal a
    # score has newly dropped for a reason unrelated to why it was staged.
    if _original_stage(payload.candidate_id) != "score_floor" and (
        match.blended_score < priced.min_score
    ):
        raise CommandFailed(
            "score_below_minimum",
            {"score": match.blended_score, "minimum": priced.min_score},
        )

    from src.execution.promote_pipeline import queue_promoted_for_approval

    ttl_minutes = get_config().approval.ttl_minutes
    approval_id = queue_promoted_for_approval(match, chat_id=chat_id, ttl_minutes=ttl_minutes)
    if approval_id is None:
        # `queue_promoted_for_approval` returns None only when an order is already active for
        # this candidate — a replayed drain, not a failure: the intent's goal (this contract
        # has a proposal in flight) is already satisfied. Mirrors `_apply_approval_decision`'s
        # "already decided" outcome above.
        return {"approval_id": None, "note": "order_already_active"}
    return {"approval_id": approval_id}


# ---------------------------------------------------------------------------
# M5 Task 5.1 — roll_request.
#
# The console asks the system to PROPOSE a roll; the operator then approves that proposal
# through M3's path. There is no button that rolls a position. `queue_roll_for_approval` already
# does the entire job (run the generator with the defensive policy, pick the best by ROC, upsert
# the CandidateRow, raise a PENDING ApprovalRow with the frozen snapshot); this handler resolves
# the position, fetches the inputs through the same shared helper the monitor uses
# (`roll_pipeline.fetch_roll_inputs`), and disambiguates the pipeline's `None` into the five
# operator-meaningful reasons in `docs/web/commands.md`'s roll_request table.
#
# The roll's economic bounds are `rolling.py`'s alone. The handler adds none and relaxes none —
# it calls the same generator, with the same defensive flag, and reports what comes back. The
# degradation tests in `tests/test_write_path_invariants.py` pin that no economic token leaks
# into this file and that the defensive policy is shared with the monitor.
# ---------------------------------------------------------------------------


def _existing_roll_in_flight(s: Session, candidate_id: str) -> dict | None:
    """Return ``{"approval_id": int | None}`` if a roll is already in flight for *candidate_id*,
    else None.

    "In flight" covers both an active order (the monitor's proposal was approved and is working)
    and an existing PENDING approval (the monitor's proposal is awaiting the operator's decision).
    ``has_active_order`` only sees OrderRows, so the pending-approval check is what closes the
    monitor-vs-web race the milestone's headline acceptance criterion demands — a web request
    that arrives while the monitor's approval is still PENDING must not raise a second one. Both
    cases map to ``roll_already_working``; the approval id (the working order's, or the pending
    proposal's) is returned so the receipt can link to it.
    """
    order = active_order_for(s, candidate_id)
    if order is not None:
        return {"approval_id": order.approval_id}
    pending = s.execute(
        select(ApprovalRow)
        .where(
            ApprovalRow.candidate_id == candidate_id,
            ApprovalRow.status == ApprovalStatus.PENDING.value,
        )
        .order_by(ApprovalRow.created_at.desc(), ApprovalRow.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    if pending is not None:
        return {"approval_id": pending.id}
    return None


@register("roll_request")
async def _roll_request(*, command: Any, ib: Any, bot: Any, chat_id: str, **_: Any) -> dict:
    """Ask the system to propose a roll for one open short.

    Fetches the chain for the underlying (through the same shared helper the intraday monitor
    uses), then calls ``queue_roll_for_approval`` unchanged. Returns
    ``{"approval_id": int, "candidate_id": str}`` on success. Raises ``CommandFailed`` with one
    of the five reasons in ``docs/web/commands.md``'s roll_request table otherwise.
    """
    if ib is None:
        raise CommandFailed("broker_unavailable")

    from src.api.models.commands import RollRequestPayload

    payload = RollRequestPayload(**command.payload)

    from src.ibkr.portfolio import get_positions

    position = next((p for p in get_positions(ib) if p.symbol == payload.position_symbol), None)
    if position is None:
        raise CommandFailed("position_not_found")
    if position.sec_type != "OPT" or position.position >= 0:
        raise CommandFailed("not_an_open_short")

    from src.execution.roll_pipeline import fetch_roll_inputs, queue_roll_for_approval

    try:
        quotes, iv_stats, tech_stats = await fetch_roll_inputs(ib, position)
    except Exception as exc:
        raise CommandFailed("chain_unavailable", {"detail": str(exc)}) from exc
    if not quotes:
        raise CommandFailed("chain_unavailable", {"detail": "the chain returned no quotes"})

    # Disambiguate the pipeline's None BEFORE calling it (Task 5.1 design point): derive the same
    # candidates the pipeline will choose from — same function, same inputs, same deterministic
    # ids — and check what is already in flight for any of them, not just the current best.
    # Two fetches taken minutes apart see different chain snapshots, so the top-ranked candidate
    # at fetch time is not guaranteed to be the same contract the monitor's earlier PENDING
    # approval named — but that earlier contract is still in this list as long as it still
    # qualifies, just possibly no longer first. Checking every candidate (bounded — a handful of
    # strikes/expiries from one chain) is what actually closes the monitor-vs-web race; checking
    # only the best would miss it whenever ranking shifts between the two fetches. The roll's
    # economics stay in rolling.py; this call only asks "would anything qualify, and what would
    # each one's id be".
    from src.strategies.rolling import generate_roll_candidates

    candidates = generate_roll_candidates(position, quotes, iv_stats, tech_stats, defensive=True)
    if not candidates:
        raise CommandFailed("no_qualifying_roll")

    with session_scope() as s:
        for cand in candidates:
            in_flight = _existing_roll_in_flight(s, cand.candidate_id)
            if in_flight is not None:
                raise CommandFailed("roll_already_working", in_flight)

    ttl_minutes = get_config().approval.ttl_minutes
    queued = queue_roll_for_approval(
        position, quotes, iv_stats, tech_stats, chat_id=chat_id, ttl_minutes=ttl_minutes
    )
    if queued is None:
        # The pre-checks passed an instant ago, so the pipeline's own guard is what said no —
        # the narrow race window where an order or approval appeared between the check and the
        # call. Re-derive for the receipt link; if genuinely nothing is in flight (an internal
        # pipeline error — it never raises) surface it as a handler error rather than inventing
        # a sixth reason.
        with session_scope() as s:
            for cand in candidates:
                in_flight = _existing_roll_in_flight(s, cand.candidate_id)
                if in_flight is not None:
                    raise CommandFailed("roll_already_working", in_flight)
        raise RuntimeError(
            "queue_roll_for_approval returned None with no order or pending approval in flight"
        )
    approval_id, cand = queued
    return {"approval_id": approval_id, "candidate_id": cand.candidate_id}


# ---------------------------------------------------------------------------
# M6 Task 6.1 — halt / resume / set_autonomy.
#
# The three control-plane handlers. None of them touches an order path: they flip the
# same `system_settings` keys the Telegram /halt, /resume and /autonomy commands flip
# (`set_halted`, `set_autonomy_level`), so there is exactly one halt flag and one
# autonomy rung, read through `system_settings.HALT_KEY` / `get_autonomy_level` by every
# consumer. Two halt flags would be a catastrophe — one of them would silently stop
# being read. The reference behaviour is `handle_halt_command` / `handle_resume_command`
# / `handle_autonomy_command` in approval_service.py.
#
# The asymmetry that shapes them (M6): halting when you did not mean to costs some
# missed premium; failing to halt when you meant to can cost a great deal more. So
# halt/resume are idempotent and always `applied` (the operator's intent is satisfied),
# and never fail for lack of a broker — TWS being down is a common shape of "something
# is wrong", which is exactly when halting matters most. set_autonomy enforces the same
# promotion evidence gate Telegram does (`promotion_blockers`), so the web is not the
# rung ladder's back door.
#
# Each handler sends a Telegram notification — the one place a handler notifies,
# because these are control-plane changes with no order-poll loop to report them later.
# A halt raised from the browser must be visible to the operator wherever they are.
# ---------------------------------------------------------------------------


def _notify(bot: Any, chat_id: str, text: str) -> None:
    """Best-effort Telegram send. A control must apply even when Telegram is down too.

    The bot's send_message is async in production; the call is scheduled without
    blocking the drain either way (fire-and-forget through the event loop).
    """
    try:
        import asyncio

        coro = bot.send_message(chat_id=chat_id, text=text)
        loop = asyncio.get_running_loop()
        loop.create_task(coro)
    except Exception:
        log.warning("control notification failed", exc_info=True)


@register("halt")
def _halt(*, command: Any, bot: Any, chat_id: str, **_: Any) -> dict:
    """Set the kill switch. Never needs the broker, never fails for lack of one.

    Idempotent: halting an already-halted system is `applied` — the operator's intent
    is satisfied, not an error. The reason (defaulted to a readable sentence when empty,
    so `/status` and the console always say something useful) is recorded in
    `HALT_REASON_KEY` through `set_halted`, exactly like Telegram's /halt.
    """
    from src.api.models.commands import HaltPayload
    from src.storage.system_settings import set_halted

    payload = HaltPayload(**command.payload)
    reason = (payload.reason or "").strip() or "halted from the web console"
    set_halted(True, reason)
    log.warning("Kill switch ENGAGED via web command %s — %s", command.id, reason)
    _notify(bot, chat_id, f"Execution HALTED from the web console: {reason}")
    return {"halted": True, "reason": reason}


@register("resume")
def _resume(*, command: Any, bot: Any, chat_id: str, **_: Any) -> dict:
    """Release the kill switch. Also idempotent and broker-free.

    Records who released it in the command's `result` (`requested_by`), because
    releasing the kill switch re-arms execution and the ledger should say who did.
    """
    from src.storage.system_settings import set_halted

    set_halted(False)
    log.warning("Kill switch RELEASED via web command %s (by %s)", command.id, command.requested_by)
    _notify(
        bot,
        chat_id,
        "Execution RESUMED from the web console. QUEUED orders resume on the next poll cycle.",
    )
    return {"halted": False, "released_by": command.requested_by}


@register("set_autonomy")
def _set_autonomy(*, command: Any, bot: Any, chat_id: str, **_: Any) -> dict:
    """Move the autonomy rung. The four `AutonomyLevel` values are enforced at parse
    time (M1's `SetAutonomyPayload.level: AutonomyLevel`); this handler never coerces
    an unknown value. Promotion is refused the same way Telegram refuses it —
    `promotion_blockers` must be empty — so the web is not a back door around the
    evidence gate. Demotion (including a same-rung no-op) always applies.
    """
    from src.api.models.commands import SetAutonomyPayload
    from src.storage.system_settings import (
        get_autonomy_level,
        promotion_blockers,
        set_autonomy_level,
    )

    payload = SetAutonomyPayload(**command.payload)
    blockers = promotion_blockers(payload.level)
    if blockers:
        raise CommandFailed("promotion_refused", {"blockers": blockers})
    set_autonomy_level(payload.level)
    log.warning(
        "Autonomy level set to %s via web command %s (by %s)",
        payload.level.value,
        command.id,
        command.requested_by,
    )
    _notify(bot, chat_id, f"Autonomy set to {payload.level.value.upper()} from the web console.")
    return {"level": payload.level.value, "previous": get_autonomy_level().value}


# ---------------------------------------------------------------------------
# M7 Task 7.4 — universe_add / universe_remove.
#
# All real validation (non-overridable list -> 422, actively_wheeling remove -> 409,
# unknown symbol -> 404) already happened at the API boundary before this command could
# ever be created — see src/api/routers/universe.py. A command that reaches this handler
# is always valid and always applies: neither handler raises CommandFailed. Neither sends
# a Telegram notification either (unlike halt/resume/set_autonomy) — a universe edit is
# reversible, non-urgent config, not a safety-critical control.
# ---------------------------------------------------------------------------


@register("universe_add")
def _universe_add(*, command: Any, **_: Any) -> dict:
    """Upsert an 'add' override. Idempotent — repeating it is applied, not an error, the
    same idempotency shape as halt/resume/set_autonomy. Invalidates the cache so the edit
    is live in this process immediately, not up to 60s later."""
    from src.api.models.commands import UniversePayload
    from src.common.universe import invalidate_universe_cache
    from src.storage.universe_overrides import set_override

    payload = UniversePayload(**command.payload)
    with session_scope() as s:
        set_override(
            s,
            symbol=payload.symbol,
            list_name=payload.list_name,
            action="add",
            created_by=command.requested_by,
        )
    invalidate_universe_cache()
    return {"symbol": payload.symbol.upper(), "list_name": payload.list_name, "action": "add"}


@register("universe_remove")
def _universe_remove(*, command: Any, **_: Any) -> dict:
    """Upsert a 'remove' override — NOT clear_override. A remove always means "record an
    override that suppresses this symbol," whether the symbol started in the YAML base or
    was itself an override-add; deleting the row (clear_override) would silently do nothing
    for a YAML-base symbol, which is the wrong behaviour for an explicit remove request."""
    from src.api.models.commands import UniversePayload
    from src.common.universe import invalidate_universe_cache
    from src.storage.universe_overrides import set_override

    payload = UniversePayload(**command.payload)
    with session_scope() as s:
        set_override(
            s,
            symbol=payload.symbol,
            list_name=payload.list_name,
            action="remove",
            created_by=command.requested_by,
        )
    invalidate_universe_cache()
    return {"symbol": payload.symbol.upper(), "list_name": payload.list_name, "action": "remove"}
