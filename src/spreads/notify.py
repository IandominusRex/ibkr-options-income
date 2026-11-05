"""Telegram output for the spreads system — its own thread, its own Bot, no src.notify import.

2026-10-14 redesign (the thread was "clunky and cluttered": seven plain-text GEX-map posts a
day, a day plan with every flag run together on one line, a "nothing to sell" post per side,
and ``[PAPER]``/``[SPREADS]`` tags in front of everything):

* **One day card per session**, sent at the first map and then *edited in place*: the levels,
  Claude's plan as bullets, and a live status line (the last entry check). Map refreshes and
  "nothing to sell" checks update the card instead of posting.
* **Separate messages only for events**: an open, a close, a Claude pick, an alert, the EOD.
* Telegram HTML, every dynamic string escaped (Claude's text included).

Best effort: a send failure is logged and swallowed, never raised into trading code.
"""

from __future__ import annotations

import html
import logging
from dataclasses import dataclass, field
from datetime import date, datetime

from telegram import Bot
from telegram.error import BadRequest

from src.common.config import Config
from src.common.schemas import (
    GexLevels,
    SpreadBriefResult,
    SpreadEntryContext,
    SpreadMenuItem,
    SpreadPick,
    SpreadPosition,
    SpreadTradeRecord,
)
from src.spreads.pricing import ET

log = logging.getLogger(__name__)

_LIMIT = 4096
_REGIME = {"positive": "🟢 positive gamma", "negative": "🔴 negative gamma"}
_REASON = {
    "profit_take": "profit take",
    "stop_loss": "stop loss",
    "strike_touch": "short strike touched",
    "expire_worthless": "expired worthless",
    "max_hold": "held too long",
    "time_stop": "time stop",
    "force_close": "time stop",
}


def esc(s: object) -> str:
    return html.escape(str(s), quote=False)


def _money(v: float) -> str:
    return f"{'+' if v >= 0 else '-'}${abs(v):,.2f}"


def _lvl(v: float | None) -> str:
    return "n/a" if v is None else f"{v:,.2f}"


def _book(mode: str) -> str:
    """A book label only where it adds information: the simulated baseline book."""
    return " <i>(baseline, simulated)</i>" if mode == "baseline" else ""


def _reason(code: str) -> str:
    return _REASON.get(code, code.replace("_", " "))


# ---------------------------------------------------------------------------
# The day card
# ---------------------------------------------------------------------------


@dataclass
class DayCard:
    """Everything the day's one edited-in-place message shows."""

    day: date
    mode: str
    underlying: str = "SPY"
    levels: GexLevels | None = None
    plan: SpreadBriefResult | None = None
    status: str | None = None
    status_at: datetime | None = None
    checks: int = 0  # armed entry checks that found nothing to sell
    trades: list[str] = field(default_factory=list)  # one short line per open/close today
    message_id: int | None = None
    # The health lines (2026-11-05): is the map building, are trades being assessed. Edited in
    # place with `updated_at`, so the thread carries one message and no outage/recovery posts.
    updated_at: datetime | None = None
    map_at: datetime | None = None  # the last successful build
    map_builds: int = 0
    map_failed_since: datetime | None = None  # start of the current outage
    map_error: str | None = None
    map_retry_min: int = 5
    assessments: int = 0  # entry checks that fetched the chain and weighed candidates
    assessed_at: datetime | None = None
    watch_note: str | None = None  # what the entry loop is doing right now


def _hm(t: datetime) -> str:
    return f"{t.astimezone(ET):%H:%M} ET"


def _map_line(card: DayCard) -> str:
    if card.map_failed_since is not None:
        why = esc(card.map_error or "no chain or index price")
        return (
            f"🗺 <b>GEX map</b> ⚠️ failing since {_hm(card.map_failed_since)} · {why} · "
            f"retrying every {card.map_retry_min} min, no entries until it builds"
        )
    if card.map_at is not None:
        plural = "" if card.map_builds == 1 else "s"
        return (
            f"🗺 <b>GEX map</b> ✅ built {_hm(card.map_at)} · {card.map_builds} build{plural} today"
        )
    return "🗺 <b>GEX map</b> ⏳ not built yet"


def _assess_line(card: DayCard) -> str:
    last = f" · last {_hm(card.assessed_at)}" if card.assessed_at else ""
    note = f" · {esc(card.watch_note)}" if card.watch_note else ""
    return f"🔎 <b>Trades</b> {card.assessments} assessed{last}{note}"


def fmt_day_card(card: DayCard) -> str:
    head = f"🟦 <b>{esc(card.underlying)} 0DTE · {card.day:%a %d %b}</b> · {esc(card.mode.upper())}"
    if card.updated_at is not None:
        head += f" · <i>updated {_hm(card.updated_at)}</i>"
    parts = [head, _map_line(card), _assess_line(card)]
    lv = card.levels
    if lv is not None:
        em = "n/a" if lv.expected_move is None else f"±{lv.expected_move:.2f}"
        parts += [
            "",
            f"<b>Levels</b> {lv.as_of.astimezone(ET):%H:%M} ET · spot {lv.spot:,.2f} · EM {em}",
            f"put wall {_lvl(lv.put_wall)} · flip {_lvl(lv.flip)} · call wall {_lvl(lv.call_wall)}",
            _REGIME.get(lv.regime, esc(lv.regime)),
        ]
    if card.plan is not None:
        p = card.plan.plan
        parts.append("")
        if p is None:
            err = card.plan.call.error or "no plan"
            parts.append(f"<b>Plan</b> unavailable ({esc(err)}) — picks run without one")
        else:
            parts.append(f"<b>Plan</b> · bias {esc(p.bias)}")
            if p.summary:
                parts.append(f"<i>{esc(p.summary)}</i>")
            if p.risk_flags:
                parts.append("<b>Watch</b>")
                parts += [f"• {esc(f)}" for f in p.risk_flags]
            if p.skip_conditions:
                parts.append("<b>Skip if</b>")
                parts += [f"• {esc(c)}" for c in p.skip_conditions]
            if p.preferred_distance:
                parts.append(f"<b>Distance</b> {esc(p.preferred_distance)}")
    if card.trades:
        parts += ["", "<b>Trades</b>", *card.trades]
    if card.status:
        when = f"{card.status_at.astimezone(ET):%H:%M} ET · " if card.status_at else ""
        extra = f" <i>({card.checks} armed checks)</i>" if card.checks > 1 else ""
        parts += ["", f"<b>Status</b> {when}{esc(card.status)}{extra}"]
    text = "\n".join(parts)
    return text if len(text) <= _LIMIT else text[: _LIMIT - 1] + "…"


def status_nothing_to_sell(side: str, why: str) -> str:
    """``why_nothing`` text → the card's status line: the side and the deciding clause."""
    tail = why.split(" — ", 1)[1] if " — " in why else why
    return f"{side} side armed, no trade — {tail}"


# ---------------------------------------------------------------------------
# Event messages
# ---------------------------------------------------------------------------


def fmt_entry(pos: SpreadPosition, mode: str, context: SpreadEntryContext | None = None) -> str:
    risk = (pos.width - pos.entry_credit) * 100 * pos.contracts
    lines = [
        f"🟢 <b>Opened {esc(pos.side)} spread {pos.short_strike:g}/{pos.long_strike:g}</b> "
        f"×{pos.contracts} @ {pos.entry_credit:.2f}{_book(mode)}",
        f"max loss ${risk:,.0f}",
    ]
    if context is not None:
        tags: list[str] = []
        if context.trigger == "move" and context.move_em is not None:
            move = "drop" if pos.side == "put" else "rise"
            tags.append(f"after a {context.move_em:.2f}× expected-move {move}")
        tags.append(
            "⚠️ NEGATIVE GAMMA" if context.regime == "negative" else f"gamma {context.regime}"
        )
        if context.gap_day and context.gap_pct is not None:
            tags.append(f"gap {context.gap_pct * 100:+.2f}%")
        lines[1] += " · " + " · ".join(esc(t) for t in tags)
    lines.append(f"<code>{esc(pos.spread_id)}</code>")
    return "\n".join(lines)


def entry_card_line(pos: SpreadPosition) -> str:
    return (
        f"🟢 {esc(pos.side)} {pos.short_strike:g}/{pos.long_strike:g} ×{pos.contracts} "
        f"@ {pos.entry_credit:.2f}"
    )


def fmt_exit(
    spread_id: str, reason: str, debit: float | None, realized_usd: float | None, mode: str
) -> str:
    paid = "n/a" if debit is None else f"{debit:.2f}"
    if realized_usd is None:
        icon, pnl = "⚪", "pending settlement"
    else:
        icon, pnl = ("✅" if realized_usd >= 0 else "🔴"), f"<b>{_money(realized_usd)}</b>"
    return (
        f"{icon} <b>Closed</b> <code>{esc(spread_id)}</code>{_book(mode)}\n"
        f"{esc(_reason(reason))} · debit {paid} · {pnl}"
    )


def exit_card_line(spread_id: str, reason: str, realized_usd: float | None) -> str:
    pnl = "pending" if realized_usd is None else _money(realized_usd)
    return f"⏹ {esc(spread_id)} · {esc(_reason(reason))} · {pnl}"


def fmt_eod(day: date, mode: str, trades: int, realized_usd: float, open_count: int) -> str:
    still = f" · {open_count} still open" if open_count else ""
    word = "trade" if trades == 1 else "trades"
    return (
        f"📊 <b>Spreads · {day:%a %d %b}</b> · {esc(mode.upper())}\n"
        f"{trades} {word} · realised <b>{_money(realized_usd)}</b>{still}"
    )


def fmt_books(
    mode: str, main_today: float, base_today: float, main_total: float, base_total: float
) -> str:
    return (
        f"Claude {_money(main_today)} vs baseline {_money(base_today)} today · "
        f"since start {_money(main_total)} vs {_money(base_total)}"
    )


def _menu_item(i: SpreadMenuItem, chosen: SpreadMenuItem | None) -> str:
    c = i.candidate
    text = f"{esc(i.letter)} {c.short_strike:g}/{c.long_strike:g} {c.credit_mid:.2f}"
    return f"<b>{text}</b>" if chosen is not None and i.letter == chosen.letter else text


def fmt_pick(
    menu: list[SpreadMenuItem],
    pick: SpreadPick,
    fallback: str | None,
    chosen: SpreadMenuItem | None,
    baseline: SpreadTradeRecord | None,
    mode: str,
) -> str:
    if fallback is not None:
        head = (
            f"⚙️ <b>Picker failed</b> ({esc(fallback)}) → baseline item {esc(chosen.letter)} "
            f"{chosen.candidate.short_strike:g}/{chosen.candidate.long_strike:g}"
            if chosen is not None
            else f"⚙️ <b>Picker failed</b> ({esc(fallback)}) → no baseline item, no trade"
        )
        lines = [head]
    elif chosen is None:
        lines = (
            ["🧠 <b>Claude skipped</b>", f"<i>{esc(pick.reason)}</i>"]
            if pick.reason
            else ["🧠 <b>Claude skipped</b>"]
        )
    else:
        c = chosen.candidate
        lines = [
            f"🧠 <b>Claude chose {esc(chosen.letter)}</b> ({esc(chosen.position)}) · "
            f"{esc(c.side)} {c.short_strike:g}/{c.long_strike:g} ×{chosen.contracts}"
        ]
        if pick.reason:
            lines.append(f"<i>{esc(pick.reason)}</i>")
    lines.append("Menu: " + " · ".join(_menu_item(i, chosen) for i in menu))
    lines.append(
        "Baseline: no trade this episode"
        if baseline is None
        else f"Baseline: sold {baseline.short_strike:g}/{baseline.long_strike:g} "
        f"×{baseline.contracts} @ {baseline.entry_credit:.2f} (simulated)"
    )
    return "\n".join(lines)


def _untag(text: str) -> str:
    for tag in ("[SPREADS] ", "[PAPER] ", "[SHADOW] ", "[LIVE] "):
        if text.startswith(tag):
            return text[len(tag) :]
    return text


def fmt_alert(text: str) -> str:
    """A plain-text operator alert → escaped HTML with one icon instead of a bracket tag."""
    text = _untag(text)
    icon = "🚨" if "URGENT" in text else "⚠️"
    return f"{icon} {esc(text)}"


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------


class SpreadsNotifier:
    def __init__(self, token: str, chat_id: str, thread: str) -> None:
        self.token = token
        self.chat_id = chat_id
        self.thread = thread

    @classmethod
    def from_config(cls, cfg: Config) -> SpreadsNotifier:
        s = cfg.secrets
        return cls(s.telegram_bot_token, s.telegram_chat_id, s.telegram_thread_spreads)

    @property
    def thread_id(self) -> int | None:
        raw = (self.thread or "").strip()
        return int(raw) if raw.isdigit() else None

    async def send(self, text: str) -> int | None:
        """Post *text* (Telegram HTML); the message id, or None when nothing was sent."""
        log.info("spreads notify: %s", text.splitlines()[0] if text else "")
        if not self.token or not self.chat_id:
            return None
        try:
            async with Bot(token=self.token) as bot:
                msg = await bot.send_message(
                    chat_id=self.chat_id,
                    text=text,
                    parse_mode="HTML",
                    message_thread_id=self.thread_id,
                    disable_web_page_preview=True,
                )
                return int(msg.message_id)
        except Exception:
            log.exception("spreads notify failed")
            return None

    async def edit(self, message_id: int, text: str) -> bool:
        """Edit a sent message in place. True when it now shows *text*."""
        if not self.token or not self.chat_id:
            return True
        try:
            async with Bot(token=self.token) as bot:
                await bot.edit_message_text(
                    chat_id=self.chat_id,
                    message_id=message_id,
                    text=text,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
            return True
        except BadRequest as exc:
            if "not modified" in str(exc).lower():
                return True
            log.warning("spreads notify: edit of %s refused: %s", message_id, exc)
            return False
        except Exception:
            log.exception("spreads notify edit failed")
            return False
