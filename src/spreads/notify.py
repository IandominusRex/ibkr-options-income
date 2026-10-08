"""Telegram output for the spreads system — its own thread, its own Bot, no src.notify import.

Best effort: a send failure is logged and swallowed, never raised into trading code.
"""

from __future__ import annotations

import logging
from datetime import date

from telegram import Bot

from src.common.config import Config
from src.common.schemas import GexLevels, SpreadEntryContext, SpreadPosition
from src.spreads.pricing import ET

log = logging.getLogger(__name__)


def _tag(mode: str) -> str:
    return f"[{mode.upper()}]"


def _money(v: float) -> str:
    return f"{'+' if v >= 0 else '-'}${abs(v):,.2f}"


def _lvl(v: float | None) -> str:
    return "n/a" if v is None else f"{v:,.2f}"


def fmt_map(levels: GexLevels, mode: str) -> str:
    em = "n/a" if levels.expected_move is None else f"±{levels.expected_move:.2f}"
    return (
        f"{_tag(mode)} GEX map {levels.as_of.astimezone(ET):%H:%M} ET (levels in traded-underlying points)\n"
        f"spot {levels.spot:,.2f} · regime {levels.regime} · expected move {em}\n"
        f"put wall {_lvl(levels.put_wall)} · flip {_lvl(levels.flip)} · call wall {_lvl(levels.call_wall)}"
    )


def fmt_entry(pos: SpreadPosition, mode: str, context: SpreadEntryContext | None = None) -> str:
    risk = (pos.width - pos.entry_credit) * 100 * pos.contracts
    line = (
        f"{_tag(mode)} OPENED {pos.side} spread {pos.short_strike:g}/{pos.long_strike:g} "
        f"×{pos.contracts} for {pos.entry_credit:.2f} credit · max loss ${risk:,.0f} · {pos.spread_id}"
    )
    if context is None:
        return line
    tags = ["NEGATIVE GAMMA" if context.regime == "negative" else f"gamma {context.regime}"]
    if context.trigger == "move" and context.move_em is not None:
        move = "drop" if pos.side == "put" else "rise"
        tags.append(f"after a {context.move_em:.2f}× expected-move {move}")
    if context.gap_day and context.gap_pct is not None:
        tags.append(f"gap {context.gap_pct * 100:+.2f}%")
    return line + "\n" + " · ".join(tags)


def fmt_exit(
    spread_id: str, reason: str, debit: float | None, realized_usd: float | None, mode: str
) -> str:
    paid = "n/a" if debit is None else f"{debit:.2f}"
    pnl = "pending settlement" if realized_usd is None else _money(realized_usd)
    return f"{_tag(mode)} CLOSED {spread_id} · {reason} · debit {paid} · {pnl}"


def fmt_eod(day: date, mode: str, trades: int, realized_usd: float, open_count: int) -> str:
    return (
        f"{_tag(mode)} spreads {day:%Y-%m-%d}: {trades} trade(s) · realized {_money(realized_usd)}"
        f" · {open_count} still open"
    )


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

    async def send(self, text: str) -> None:
        log.info("spreads notify: %s", text.splitlines()[0] if text else "")
        if not self.token or not self.chat_id:
            return
        try:
            async with Bot(token=self.token) as bot:
                await bot.send_message(
                    chat_id=self.chat_id, text=text, message_thread_id=self.thread_id
                )
        except Exception:
            log.exception("spreads notify failed")
