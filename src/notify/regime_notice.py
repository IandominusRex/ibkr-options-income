"""Telegram text for the market regime: change notices and the ``/regime`` status.

A regime change is persisted as an unsent ``RegimeChange`` by ``src/regime/refresh.py`` (wherever
the refresh ran: the scan, or the order poll at send time) and announced here by the scan, which
already talks to Telegram (ruling 7). A change found at send time therefore reaches the operator
on the next scan, at most 15 minutes later. Notices go to the same chat and thread as order
notifications (the trades/orders thread).

Plain text, no Markdown: the texts carry arrows, percentages and free-form reasons.
"""

from __future__ import annotations

import logging
from datetime import date
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from telegram import Bot

from src.analytics.regime import ORDER
from src.common.config import RegimeCfg, get_config, get_regime_cfg
from src.common.schemas import MarketRegime, OrderState, RegimeChange, RegimeState, Strategy
from src.notify.sender import thread_id
from src.storage.db import session_scope
from src.storage.models import OrderRow
from src.storage.regime_state import mark_changes_sent, unsent_changes

log = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")


def _limits(regime: MarketRegime, cfg: RegimeCfg) -> str:
    """What the regime does to new CSPs, in words."""
    budget = cfg.csp.budget_multiplier[regime]
    per_trade = cfg.csp.per_trade_fraction[regime]
    daily = cfg.csp.max_new_per_day[regime]
    if daily is None:
        cap = "no daily limit on new CSPs"
    else:
        cap = f"at most {daily} new CSP{'' if daily == 1 else 's'} today"
    return f"CSP budget {budget:.0%}, per-trade {per_trade:.0%}, {cap}"


def format_regime_change(c: RegimeChange, cfg: RegimeCfg, *, working_opens: int) -> str:
    """One line for a regime change, e.g. ``QQQ regime -> stressed (QQQ -2.9% today): CSP budget
    40%, per-trade 30%, at most 3 new CSPs today.``

    When the regime tightened and opening orders are already working at the broker, a second
    sentence says they are unchanged (spec section 5: the operator is told).
    """
    why = f" ({'; '.join(c.why)})" if c.why else ""
    text = f"{c.index} regime -> {c.after.value}{why}: {_limits(c.after, cfg)}."
    tightened = ORDER.index(c.after) > ORDER.index(c.before)
    if tightened and working_opens > 0:
        if working_opens == 1:
            text += (
                "\n1 opening order already working at the broker is unchanged; "
                "cancel it in IBKR if you want it smaller."
            )
        else:
            text += (
                f"\n{working_opens} opening orders already working at the broker are unchanged; "
                "cancel them in IBKR if you want them smaller."
            )
    return text


def working_csp_opens() -> int:
    """Opening CSP orders submitted or part-filled at the broker (not queued, not closes)."""
    try:
        strategy = func.json_extract(OrderRow.snapshot, "$.strategy")
        with session_scope() as s:
            return int(
                s.execute(
                    select(func.count())
                    .select_from(OrderRow)
                    .where(
                        OrderRow.state.in_([OrderState.SUBMITTED.value, OrderState.PARTIAL.value]),
                        strategy == Strategy.CASH_SECURED_PUT.value,
                    )
                ).scalar_one()
            )
    except Exception:
        log.warning("regime notice: could not count working opening orders", exc_info=True)
        return 0


async def send_regime_changes() -> int:
    """Announce every unsent regime change on Telegram; returns how many went out.

    Best-effort: with no bot token, or when Telegram fails, the changes stay unsent and are
    retried on the next call. Only the changes actually sent are flagged, so one appended while
    this ran is not lost.
    """
    pending = unsent_changes()
    if not pending:
        return 0
    cfg = get_config()
    token = cfg.secrets.telegram_bot_token
    chat_id = str(cfg.secrets.telegram_chat_id)
    if not token or not chat_id:
        return 0
    regime_cfg = get_regime_cfg()
    working = working_csp_opens()
    thread = thread_id(cfg.secrets.telegram_thread_account)

    sent: list[RegimeChange] = []
    try:
        async with Bot(token=token) as bot:
            for change in pending:
                await bot.send_message(
                    chat_id=chat_id,
                    message_thread_id=thread,
                    text=format_regime_change(change, regime_cfg, working_opens=working),
                )
                sent.append(change)
    except Exception:
        log.warning("regime notice: sending failed — will retry on the next scan", exc_info=True)
    if sent:
        mark_changes_sent(sent)
    return len(sent)


def format_regime_status(
    state: RegimeState,
    cfg: RegimeCfg,
    *,
    suspended: bool,
    resumes_on: date | None = None,
) -> str:
    """The ``/regime`` reply: both indices, the limits each implies, and whether they apply."""
    as_of = state.as_of.astimezone(_ET).strftime("%H:%M")
    lines = [f"Market regime (as of {as_of} ET)", ""]
    for ir in (state.spy, state.qqq):
        head = f"{ir.index}: {ir.effective.value}"
        if "no_data" in ir.escalated_by:
            head += " (no market data yet: assumed normal until it can be read)"
        elif ir.effective != ir.base:
            raised = "; ".join(ir.escalated_by) or "intraday"
            head += f" (daily base {ir.base.value}, raised today: {raised})"
        lines.append(head)
        lines.append(f"  {_limits(ir.effective, cfg)}.")
        inp = ir.inputs
        facts: list[str] = []
        if inp.vol is not None:
            facts.append(f"VIX {inp.vol:.1f}")
        if inp.term_ratio is not None:
            facts.append(f"VIX/VIX3M {inp.term_ratio:.2f}")
        if inp.day_change_pct is not None:
            facts.append(f"{ir.index} {inp.day_change_pct:+.1f}% today")
        if facts:
            lines.append("  " + ", ".join(facts))
        if inp.stale:
            lines.append("  stale inputs: " + ", ".join(inp.stale))
    lines.append("")
    lines.append("Tech-linked names follow the stricter of the two; every other name follows SPY.")
    if not cfg.enabled:
        lines.append("Regime limits are switched off in risk_limits.yaml (regime.enabled: false).")
    elif suspended:
        until = (
            f" until the next trading day's base ({resumes_on.isoformat()})" if resumes_on else ""
        )
        lines.append(f"Regime limits are SUSPENDED today{until}. /regime on resumes them now.")
    else:
        lines.append("Regime limits are active. /regime off suspends them for today.")
    return "\n".join(lines)
