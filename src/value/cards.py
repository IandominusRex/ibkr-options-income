"""The value book's Telegram cards (spec §7, §7.1, §9.7; Part 6 Task 4). Pure: no I/O, no Telegram import.

Every card is plain text of at most ``MAX_CHARS`` characters. A button carries a label and the
``vbook:`` callback data from ``src.common.value_commands``; no Claude prose ever appears on a
button. Unknown numbers read ``n/a``, never zero.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from src.common.value_commands import callback_data, proposal_fingerprint
from src.value.store import ValueProposalRow, ValueReevaluationRow

MAX_CHARS = 3500
_LIST_WORDS = {"deep_value": "deep value", "quality_growth": "quality growth"}


@dataclass(frozen=True)
class Card:
    key: str  # what the outbox marks posted: "proposal:12", "reeval:7", "trim:<episode>", "freeze:GOOGL"
    text: str  # plain text, at most MAX_CHARS characters
    buttons: tuple[tuple[str, str], ...] = ()  # (label, callback_data)


# Every reason src/value/risk.py can return, then the command reasons (src/value/commands.py,
# src/value/book.py), then the sell reasons a proposal carries.
VALUE_REASON_LABELS: dict[str, str] = {
    "not_paper": "the book trades in paper only",
    "halted": "trading is halted",
    "reserved_for_spreads_book": "this underlying belongs to the spreads book",
    "no_shares": "the size rounds to no shares",
    "verdict_not_ready": "the verdict is not READY",
    "health_gate_failed": "a health gate failed",
    "data_unreliable": "the data is not reliable enough yet",
    "mos_below_required": "the margin of safety is below what the regime asks",
    "timing_not_ready": "the entry timing is not ready",
    "earnings_within_window": "earnings are inside the entry window",
    "book_attribution_mismatch": "the broker's shares and the books' shares do not match",
    "adds_paused": "adds are paused by an open re-evaluation",
    "trend_brake": "the market trend brake is on",
    "sleeve_breaker": "the drawdown breaker has stopped new entries",
    "sleeve_exhausted": "the book is at its ceiling",
    "name_cap": "the name is at its cap",
    "list_share_cap": "the list is at its share of the book",
    "max_positions": "the book holds as many names as it may",
    "combined_name_cap": "the wheel and the book together hold too much of the name",
    "gross_notional_cap": "the account's gross exposure cap is reached",
    "illiquid": "the position would be too large against daily volume",
    "price_stale_at_send": "the quote was too old to send on",
    # command reasons
    "no_such_proposal": "that proposal no longer exists",
    "stale_proposal": "the card is out of date (the proposal changed)",
    "expired": "the proposal expired before the tap",
    "handler_error": "the value process hit an error",
    "unknown_kind": "the value process does not know that command",
    "no_trim_offered": "no trim is on offer",
    "already_trimmed": "the trim was already made",
}

_SELL_WORDS = {
    "arm": "the trailing stop armed",
    "half": "the price reached fair value: sell half, tighten the stop on the rest",
    "stop": "the stop was hit",
    "trail": "the trailing stop was hit",
    "peak": "the peak signal fired",
    "thesis": "a thesis exit fired",
    "remark": "fair value was re-marked",
    "remark_below": "fair value fell below the price",
    "catastrophe": "the catastrophe stop was hit",
    "time": "the holding period ended",
    "proposal": "an exit proposal",
    "shock": "a shock stop fired",
    "drawdown_trim": "the book is down 25% from its high: trimming every holding to half",
    "claude_broken": "Claude's review of the held name returned BROKEN",
    "claude_no": "Claude's verdict on the name turned NO",
}


def reason_words(code: str) -> str:
    if code in VALUE_REASON_LABELS:
        return VALUE_REASON_LABELS[code]
    if code.startswith("already_"):
        return f"it was already {code[len('already_') :]}"
    return code.replace("_", " ")


def _sell_reason(code: str) -> str:
    if code.startswith("tranche "):
        return f"scaling in, {code}"
    return _SELL_WORDS.get(code, reason_words(code))


def _money(v: float | None) -> str:
    return "n/a" if v is None else f"${v:,.2f}"


def _pct(v: float | None) -> str:
    return "n/a" if v is None else f"{v * 100:.0f}%"


def _cap(text: str) -> str:
    return text if len(text) <= MAX_CHARS else text[: MAX_CHARS - 1].rstrip() + "…"


def proposal_card(
    p: ValueProposalRow,
    *,
    release_closes: int,
    fair_value: float | None,
    mos: float | None,
    verdict_by: str,
    tranches: int | None = None,
) -> Card:
    list_word = _LIST_WORDS.get(p.list_name, p.list_name.replace("_", " "))
    if p.kind == "buy":
        tr = ""
        if p.tranche is not None:
            tr = f", tranche {p.tranche} of {tranches}" if tranches else f", tranche {p.tranche}"
        head = f"Buy {p.shares:g} {p.symbol} ({list_word}{tr})"
    else:
        head = f"Sell {p.shares:g} {p.symbol} ({list_word})"
    lines = [head]
    if p.cause == "claude" and p.kind == "sell":
        lines.append("Only Claude's number makes this sale; it waits for you.")
    elif p.cause == "claude":
        lines.append("Claude's verdict makes this name READY; Python's gates still apply.")
    else:
        lines.append("Python's rules proposed this.")
    lines.append(f"Sized at the close of {_money(p.price)}.")
    decider = "Claude" if verdict_by == "claude" else "Python"
    lines.append(
        f"Fair value {_money(fair_value)}, margin of safety {_pct(mos)} (verdict decided by {decider})."
    )
    lines.append(f"Why: {_sell_reason(p.reason)}.")
    if p.kind == "buy":
        lines.append(
            f"If cash is short, approving may close up to {release_closes} of the wheel's "
            "cash-secured puts at breakeven or better to fund it."
        )
    lines.append("The order is checked again at send time on a fresh quote.")
    buttons: tuple[tuple[str, str], ...] = ()
    if p.needs_tap and p.status == "pending":
        fp = proposal_fingerprint(p.id, p.kind, p.symbol, p.shares, p.created_at)
        buttons = (
            ("Approve", callback_data("approve", p.id, fp)),
            ("Reject", callback_data("reject", p.id, fp)),
        )
    elif not p.needs_tap:
        lines.append("Approved by the system; no tap needed.")
    return Card(key=f"proposal:{p.id}", text=_cap("\n".join(lines)), buttons=buttons)


def plan_levels(blob: str) -> str:
    """A re-evaluation's plan in one line: ``{policy: {stop, ...}}`` or a single leg's state."""
    try:
        plan = json.loads(blob or "{}")
    except ValueError:
        return "n/a"
    if not isinstance(plan, dict):
        return "n/a"
    if "stop" not in plan and "trail_floor" not in plan:
        legs = [v for v in plan.values() if isinstance(v, dict)]
        plan = (plan.get("value") if isinstance(plan.get("value"), dict) else None) or (
            legs[0] if legs else {}
        )
    parts = []
    stop, floor = plan.get("stop"), plan.get("trail_floor")
    if isinstance(stop, int | float):
        parts.append(f"stop {_money(float(stop))}")
    if isinstance(floor, int | float):
        parts.append(f"trail floor {_money(float(floor))}")
    return ", ".join(parts) if parts else "n/a"


def reevaluation_card(r: ValueReevaluationRow) -> Card:
    try:
        fired = json.loads(r.triggers_json or "[]")
    except ValueError:
        fired = []
    what = (
        "; ".join(
            f"{t.get('kind', 'trigger')}: {t['detail']}" if t.get("detail") else str(t.get("kind"))
            for t in fired
            if isinstance(t, dict)
        )
        or "n/a"
    )
    lines = [
        f"Major re-evaluation: {r.symbol} ({_LIST_WORDS.get(r.list_name, r.list_name)}), {r.session}",
        f"What fired: {what}.",
        f"Plan before: {plan_levels(r.plan_before_json)}.",
        f"Plan now: {plan_levels(r.plan_after_json)}.",
        "Adds on this name are paused while it is open; Claude's review is queued when it is on. "
        "Nothing here sells on its own.",
    ]
    return Card(key=f"reeval:{r.id}", text=_cap("\n".join(lines)))


def trim_card(state: dict, positions: list[tuple[str, float]]) -> Card:
    high, value = float(state.get("high", 0.0)), float(state.get("value", 0.0))
    down = (high - value) / high * 100.0 if high > 0 else 0.0
    episode = str(state.get("episode", ""))
    lines = [
        f"The value book is down {down:.0f}% from its high (${high:,.0f} to ${value:,.0f}). "
        "Trim every holding to half?"
    ]
    lines += [f"  {sym}: sell {sh:g}" for sym, sh in positions] or [
        "  (no holding has a share to sell)"
    ]
    lines.append("Each sale is still checked at send time; nothing sells until the next check.")
    return Card(
        key=f"trim:{episode}",
        text=_cap("\n".join(lines)),
        buttons=(("Trim to half", callback_data("trim", 0, episode)),),
    )


def freeze_card(symbol: str, detail: str) -> Card:
    text = (
        f"Share attribution FROZEN on {symbol}: both books stop opening it until you clear it.\n"
        f"{detail or 'The broker, the wheel and the value book do not agree.'}"
    )
    return Card(key=f"freeze:{symbol}", text=_cap(text))


def outcome_line(kind: str, result: dict | None, reason: str | None) -> str:
    """The plain reply the value process posts after a tap."""
    if reason is not None:
        return f"Not done ({kind.removeprefix('value_')}): {reason_words(reason)}."
    r = result or {}
    if kind == "value_approve":
        return (
            f"Approved: {r.get('kind', 'trade')} {r.get('symbol', '')} (proposal {r.get('proposal_id')}). "
            "It is checked again on a fresh quote at the next check."
        ).replace("  ", " ")
    if kind == "value_reject":
        return f"Rejected: {r.get('kind', 'trade')} {r.get('symbol', '')} (proposal {r.get('proposal_id')})."
    if kind == "value_trim":
        n = len(r.get("proposals") or [])
        if n == 0:
            return "Trim: no holding had a share to sell."
        return f"Trim approved: {n} half-size sale{'s' if n != 1 else ''}, each checked again at send time."
    return f"Done: {kind.removeprefix('value_')}."
