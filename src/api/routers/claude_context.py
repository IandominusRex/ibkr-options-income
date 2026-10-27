"""GET /claude/context — what each Claude call knows (market picture spec section 11).

Read-only. The regime and its suspension come from the trading database's ``system_settings``
through the shared ``read_setting``; the picture, the dropped list and the dossiers come from
``data/news.db`` through ``src/api/news_db.py``'s ``mode=ro`` session and the Session-parameterised
readers in ``src.news.store.queries`` (this module never imports the news process's read-write
engine). The limits shown are read from ``config/risk_limits.yaml`` — the same typed accessors the
sizer uses — so the page cannot disagree with what the gate applies. A missing or older
``news.db`` answers ``available: false`` or empty lists, a missing regime state ``regime: null``;
never a 500.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter
from pydantic import ValidationError
from sqlalchemy.orm import Session

from src.api.claude_calls import CALLS
from src.api.deps import OwnerUser, TradingDb
from src.api.models.claude_context import (
    CallContextOut,
    ClaudeContextResponse,
    DossierOut,
    DroppedOut,
    LeveragedLimitOut,
    RegimeLimitOut,
    SizingActionOut,
    SizingActionsResponse,
)
from src.api.models.common import as_utc, as_utc_opt
from src.api.news_db import news_read_session
from src.api.portfolio_source import read_portfolio
from src.api.settings_read import read_setting
from src.common.books import is_spreads_underlying
from src.common.config import (
    get_claude_cut_cfg,
    get_config,
    get_leveraged_sizing_cfg,
    get_regime_cfg,
)
from src.common.schemas import RegimeState
from src.common.universe import effective_universe
from src.news.schemas import TriageView
from src.news.store import queries
from src.storage.models import SizingActionRow
from src.storage.regime_state import STATE_KEY, SUSPENDED_KEY

log = logging.getLogger(__name__)

router = APIRouter(prefix="/claude", tags=["claude"])
ET = ZoneInfo("America/New_York")

# The trading process's per-day bookkeeping for Claude's cut (``src/notify/sender.py::_CUT_STATE_KEY``):
# {"day": ET date, "reviewed": [...], "breaker_alerted": bool}. Spelled out here because this module
# cannot import the sender (it would load the Telegram stack into the API); a test keeps the two equal.
_CUT_STATE_KEY = "claude_cut_state"

_DROPPED_WINDOW = timedelta(days=7)
_DROPPED_CAP = 100  # the list is the latest of them; ``dropped_total`` says how many there were
_DEFAULT_LEVERAGE = 3  # a leveraged ETF missing from the operator's map: the strictest factor
_PROMOTED_PREFIX = "promoted late:"
_WAS = "; was: "


def _now() -> datetime:
    return datetime.now(UTC)


def _regime_state(db: Session) -> RegimeState | None:
    """The trading process's persisted regime, or None (never written, or no longer valid)."""
    raw = read_setting(db, STATE_KEY)
    if not raw:
        return None
    try:
        return RegimeState.model_validate_json(raw)
    except ValidationError:
        log.warning("claude context: the stored regime state is unreadable", exc_info=True)
        return None


def _suspended_today(db: Session, today_et: str) -> bool:
    return read_setting(db, SUSPENDED_KEY) == today_et


def _breaker_tripped_today(db: Session, today_et: str) -> bool:
    """True when Claude's daily cut breaker tripped today (ET): the sender's day state says so.

    A state for another day, a missing setting and anything that is not the expected JSON object
    all read as not tripped, as the sender itself treats them (it starts a fresh day).
    """
    raw = read_setting(db, _CUT_STATE_KEY)
    if not raw:
        return False
    try:
        state = json.loads(raw)
    except ValueError:
        return False
    return (
        isinstance(state, dict)
        and state.get("day") == today_et
        and state.get("breaker_alerted") is True
    )


def _limits(state: RegimeState | None) -> tuple[bool, list[RegimeLimitOut]]:
    """``(regime enabled, the CSP limits of each index's current regime)``.

    The limits are those the regime *would* apply; whether they are in force today is
    ``enabled`` and not ``suspended_today``. An invalid ``regime:`` block (the trading service
    refuses it at first use) shows no limits rather than failing the page.
    """
    try:
        cfg = get_regime_cfg()
    except ValueError:
        log.warning("claude context: regime config is invalid", exc_info=True)
        return True, []
    if state is None:
        return cfg.enabled, []
    csp = cfg.csp
    out: list[RegimeLimitOut] = []
    for ix in (state.spy, state.qqq):
        r = ix.effective
        out.append(
            RegimeLimitOut(
                index=ix.index,
                regime=r,
                budget_pct=round(csp.budget_multiplier[r] * 100, 1),
                per_trade_pct=round(csp.per_trade_fraction[r] * 100, 1),
                max_new_per_day=csp.max_new_per_day[r],
                floor_new_per_day=csp.floor_new_per_day[r],
            )
        )
    return cfg.enabled, out


def _leveraged() -> tuple[bool, list[LeveragedLimitOut]]:
    """``(enabled, the per-trade ceiling of each leveraged ETF in the universe)``."""
    try:
        cfg = get_leveraged_sizing_cfg()
    except ValueError:
        log.warning("claude context: leveraged_sizing config is invalid", exc_info=True)
        return True, []
    if not cfg.enabled:
        return False, []
    names = {str(s).upper() for s in get_config().universe.get("leveraged_etfs") or []}
    out = []
    for symbol in sorted(names):
        factor = cfg.leverage.get(symbol, _DEFAULT_LEVERAGE)
        out.append(
            LeveragedLimitOut(
                symbol=symbol,
                leverage=factor,
                calm_fraction=cfg.per_trade_fraction["calm"][factor],
                stressed_fraction=cfg.per_trade_fraction["stressed"][factor],
            )
        )
    return True, out


def _cut_mode() -> tuple[Literal["applied", "record_only"], Literal["paper", "live"]]:
    """Whether Claude's size cut changes the size sent, for the account this API runs against.
    (The daily breaker can still stop a cut on the day; that is not a mode.)"""
    live = get_config().is_live
    try:
        cfg = get_claude_cut_cfg()
    except ValueError:
        log.warning("claude context: claude_cut config is invalid", exc_info=True)
        return "record_only", "live" if live else "paper"
    applied = cfg.apply_live if live else cfg.apply_in_paper
    return ("applied" if applied else "record_only"), ("live" if live else "paper")


def _held(db: Session) -> set[str]:
    """Held underlyings from the trading DB reading the API already uses (never
    ``src.news.collectors``: that module loads the news process's read-write engine)."""
    snap = read_portfolio(db).snapshot
    positions = snap.positions if snap else []
    return {(p.underlying or p.symbol).upper() for p in positions if p.position != 0}


def _covered(held: set[str]) -> list[str]:
    """The names that get a dossier: ``would_own`` + ``actively_wheeling`` (the effective
    universe, web overrides included) + every held underlying, spreads names out. This mirrors
    ``src.news.dossier.dossier_symbols`` (which cannot be imported here)."""
    u = effective_universe()
    names = {str(s).upper() for k in ("would_own", "actively_wheeling") for s in u.get(k) or []}
    return sorted(n for n in names | held if n and not is_spreads_underlying(n))


def _dismissal_reason(reason: str) -> str:
    """The reason a story was dismissed. A promoted row's stored reason is
    ``promoted late: <move>% (<basis>); was: <the dismissal reason>`` (cut at 160 characters), so
    the promotion text is dropped; when the cut took the original reason, it reads as empty."""
    if not reason.startswith(_PROMOTED_PREFIX):
        return reason
    return reason.split(_WAS, 1)[1] if _WAS in reason else ""


def _dropped(s: Session, now: datetime) -> tuple[list[DroppedOut], int, int]:
    """``(the latest dropped stories, how many there were, how many nobody reviewed)``, last 7 days.

    Dropped = judged noise (pile 3) plus any story the market-reaction check promoted later
    (those left pile 3, so they are found by their ``promoted_at``). Not reviewed = outside the
    ranked batch: nobody judged them.
    """
    rows = queries.triage_since(s, now - _DROPPED_WINDOW)
    floor = datetime.min.replace(tzinfo=UTC)

    def key(t: TriageView) -> datetime:
        return t.judged_at or floor

    dropped = sorted(
        (t for t in rows if t.pile == 3 or t.promoted_at is not None), key=key, reverse=True
    )
    out = [
        DroppedOut(
            cluster_id=t.cluster_id,
            headline=t.headline,
            reason=_dismissal_reason(t.reason),
            judged_at=t.judged_at,
            promoted=t.promoted_at is not None,
            promoted_move_pct=t.promoted_move_pct,
        )
        for t in dropped[:_DROPPED_CAP]
    ]
    return out, len(dropped), sum(1 for t in rows if t.pile is None)


def _dossiers(s: Session, covered: list[str], held: set[str]) -> tuple[list[DossierOut], list[str]]:
    """The covered names' newest dossiers (held names first, then alphabetical), and the covered
    names that have none yet."""
    found = queries.latest_dossiers(s, covered)
    out = [
        DossierOut(
            symbol=d.symbol,
            kind=d.kind,
            health=d.health,
            health_why=d.health_why,
            held=d.symbol.upper() in held,
            story=d.story,
            story_evidence=d.story_evidence,
            reported=d.reported,
            events=d.events,
            profile=d.profile,
            facts=d.facts,
            facts_at=as_utc(d.facts_at),
            prose_at=as_utc_opt(d.prose_at),
            stale=d.stale,
        )
        for d in found.values()
    ]
    out.sort(key=lambda d: (not d.held, d.symbol))
    return out, [c for c in covered if c not in found]


@router.get("/context", response_model=ClaudeContextResponse)
def context(_: OwnerUser, db: TradingDb) -> ClaudeContextResponse:
    now = _now()
    state = _regime_state(db)
    regime_enabled, limits = _limits(state)
    leveraged_enabled, leveraged = _leveraged()
    cut_mode, account = _cut_mode()
    held = _held(db)
    today = now.astimezone(ET).date().isoformat()
    base = ClaudeContextResponse(
        as_of=now,
        available=False,
        regime=state,
        regime_enabled=regime_enabled,
        suspended_today=_suspended_today(db, today),
        limits=limits,
        leveraged_enabled=leveraged_enabled,
        leveraged=leveraged,
        claude_cut_mode=cut_mode,
        claude_cut_breaker_tripped_today=_breaker_tripped_today(db, today),
        account_mode=account,
        calls=[
            CallContextOut(kind=c.kind, label=c.label, blocks=[b.label for b in c.blocks])
            for c in CALLS
        ],
    )
    with news_read_session() as s:
        if s is None:
            return base
        dropped, dropped_total, not_reviewed = _dropped(s, now)
        dossiers, without_notes = _dossiers(s, _covered(held), held)
        return base.model_copy(
            update={
                "available": True,
                "picture": queries.latest_picture(s),
                "dropped": dropped,
                "dropped_total": dropped_total,
                "not_reviewed_7d": not_reviewed,
                "dossiers": dossiers,
                "without_notes": without_notes,
            }
        )


@router.get("/sizing", response_model=SizingActionsResponse)
def sizing(_: OwnerUser, db: TradingDb, day: date | None = None) -> SizingActionsResponse:
    """The day's sizing record: puts the regime, the ladder or Claude's cut trimmed or held back."""
    now = _now()
    shown = day or now.astimezone(ET).date()
    rows = (
        db.query(SizingActionRow)
        .filter(SizingActionRow.action_day == shown)
        .order_by(SizingActionRow.created_at.desc(), SizingActionRow.id.desc())
        .limit(200)
        .all()
    )
    return SizingActionsResponse(
        as_of=now,
        day=shown,
        actions=[
            SizingActionOut(
                id=r.id,
                created_at=as_utc(r.created_at),
                underlying=r.underlying,
                right=r.right,
                strike=r.strike,
                expiry=r.expiry,
                premium=r.premium,
                kind=r.kind,
                regime=r.regime,
                deterministic_contracts=r.deterministic_contracts,
                sent_contracts=r.sent_contracts,
                reason=r.reason,
                order_id=r.order_id,
            )
            for r in rows
        ],
    )
