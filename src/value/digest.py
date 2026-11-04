"""The value book's nightly digest and review cards (Part 6 Task 6; ruling 13; spec §7, §7.1 step 4).

One message a night, after the night's run: the Minor re-evaluations of held names since the last
digest, the review cards, the book's line and the proposals waiting for a tap. Review cards never
sell and never create a proposal (spec §7 "Review cards, not exits"): a Claude-chosen kill trigger
that fired, a position held ``no_progress_months`` or more whose best close never passed entry +
10% of the way to fair value, and a Python fair value down ``fv_drop_pct`` or more since entry while
the price is not. Each review card is shown once (the ``digest`` state key remembers what it
showed). Nothing is sent when every part is empty. Reads value.db only.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.common.config import ValueCfg
from src.value.book import get_state, set_state, totals
from src.value.cards import _LIST_WORDS, plan_levels
from src.value.store import (
    ValueKillTriggerRow,
    ValuePositionRow,
    ValueProposalRow,
    ValueReevaluationRow,
    ValueTickerFileRow,
    ValueTickerHistoryRow,
)

STATE_KEY = "digest"
_SHOWN_KEPT = 300
_KILL_WINDOW_DAYS = 7  # a trigger that fired longer ago than this is not news
_PROGRESS_FRACTION = 0.10  # of the distance from entry to fair value
_MONTH_DAYS = 30.44


@dataclass(frozen=True)
class Digest:
    text: str | None  # None: every part was empty
    keys: list[str] = field(default_factory=list)  # the review cards shown, remembered once sent


def last_sent(vs: Session) -> datetime | None:
    at = (get_state(vs, STATE_KEY) or {}).get("at")
    return datetime.fromisoformat(at) if at else None


def mark_sent(vs: Session, d: Digest, now: datetime) -> None:
    state = get_state(vs, STATE_KEY) or {}
    shown = [*state.get("shown", []), *d.keys]
    set_state(vs, STATE_KEY, {"at": now.isoformat(), "shown": shown[-_SHOWN_KEPT:]}, now)


def _money(v: float | None) -> str:
    return "n/a" if v is None else f"${v:,.2f}"


def _plan(pos: ValuePositionRow) -> dict:
    try:
        plan = json.loads(pos.plan_json or "{}")
    except ValueError:
        return {}
    return plan if isinstance(plan, dict) else {}


def _num(plan: dict, key: str) -> float | None:
    v = plan.get(key)
    return float(v) if isinstance(v, int | float) else None


def _minor_lines(vs: Session, since: datetime) -> list[str]:
    out: list[str] = []
    for r in vs.scalars(
        select(ValueReevaluationRow)
        .where(
            ValueReevaluationRow.severity == "minor",
            ValueReevaluationRow.position_id.is_not(None),
            ValueReevaluationRow.created_at > since,
        )
        .order_by(ValueReevaluationRow.id)
    ):
        try:
            fired = json.loads(r.triggers_json or "[]")
        except ValueError:
            fired = []
        what = (
            "; ".join(
                f"{t.get('kind', 'trigger')}: {t['detail']}"
                if t.get("detail")
                else str(t.get("kind"))
                for t in fired
                if isinstance(t, dict)
            )
            or "n/a"
        )
        out.append(
            f"{r.symbol} ({_LIST_WORDS.get(r.list_name, r.list_name)}): {what}. "
            f"Plan {plan_levels(r.plan_before_json)} -> {plan_levels(r.plan_after_json)}."
        )
    return out


def _review_lines(
    vs: Session, now: datetime, cfg: ValueCfg, shown: set[str]
) -> tuple[list[str], list[str]]:
    lines: list[str] = []
    keys: list[str] = []
    positions = list(vs.scalars(select(ValuePositionRow).where(ValuePositionRow.status == "open")))
    held = {p.symbol for p in positions}
    horizon = now.date() - timedelta(days=_KILL_WINDOW_DAYS)
    for t in vs.scalars(
        select(ValueKillTriggerRow)
        .where(ValueKillTriggerRow.fired_on.is_not(None), ValueKillTriggerRow.fired_on >= horizon)
        .order_by(ValueKillTriggerRow.id)
    ):
        key = f"kill:{t.id}"
        if t.symbol not in held or key in shown:
            continue
        threshold = "" if t.threshold is None else f" {t.threshold:g}"
        actual = "" if t.last_actual is None else f", now {t.last_actual:g}"
        lines.append(
            f"{t.symbol}: kill trigger fired ({t.kind.replace('_', ' ')}{threshold}{actual})."
        )
        keys.append(key)
    months = cfg.telegram.no_progress_months
    for pos in positions:
        plan = _plan(pos)
        entry, fair, best = (
            _num(plan, "entry_price"),
            _num(plan, "fair_value"),
            _num(plan, "highest_close"),
        )
        key = f"noprog:{pos.id}"
        if (
            key not in shown
            and entry is not None
            and fair is not None
            and fair > entry
            and best is not None
            and (now.date() - pos.opened_on).days >= months * _MONTH_DAYS
        ):
            bar = entry + _PROGRESS_FRACTION * (fair - entry)
            if best <= bar:
                lines.append(
                    f"{pos.symbol}: no progress after {months} months: the best close since entry is "
                    f"{_money(best)}, and progress means above {_money(bar)} (entry plus 10% of the "
                    f"way to fair value {_money(fair)})."
                )
                keys.append(key)
        fv_key = f"fv:{pos.id}"
        if fv_key in shown or entry is None:
            continue
        line = _fair_value_drop(vs, pos, entry, cfg)
        if line is not None:
            lines.append(line)
            keys.append(fv_key)
    return lines, keys


def _fair_value_drop(vs: Session, pos: ValuePositionRow, entry: float, cfg: ValueCfg) -> str | None:
    deep = pos.list_name == "deep_value"
    file = vs.get(ValueTickerFileRow, pos.symbol)
    now_fv = None if file is None else (file.fair_value_deep if deep else file.fair_value_growth)
    price = None if file is None else file.price
    hist = vs.scalars(
        select(ValueTickerHistoryRow)
        .where(
            ValueTickerHistoryRow.symbol == pos.symbol, ValueTickerHistoryRow.as_of >= pos.opened_on
        )
        .order_by(ValueTickerHistoryRow.as_of, ValueTickerHistoryRow.id)
    ).first()
    if hist is None or now_fv is None or price is None:
        return None
    try:
        entry_fv = json.loads(hist.summary_json)["lists"][pos.list_name]["fair_value"]
    except (ValueError, KeyError, TypeError):
        return None
    if not isinstance(entry_fv, int | float) or entry_fv <= 0:
        return None
    drop = (entry_fv - now_fv) / entry_fv * 100.0
    price_down = (entry - price) / entry * 100.0 if entry > 0 else 0.0
    if drop < cfg.telegram.fv_drop_pct or price_down >= cfg.telegram.fv_drop_pct:
        return None
    return (
        f"{pos.symbol}: fair value is down {drop:.0f}% since entry ({_money(float(entry_fv))} to "
        f"{_money(now_fv)}) while the price is not (entry {_money(entry)}, now {_money(price)})."
    )


def _book_line(vs: Session) -> str | None:
    t = totals(vs)
    open_names = {
        p.symbol
        for p in vs.scalars(select(ValuePositionRow).where(ValuePositionRow.status == "open"))
    }
    n = len(open_names)
    cost = sum(x.cost for s, x in t.names.items() if s in open_names)
    hw = get_state(vs, "high_water") or {}
    trend = bool((get_state(vs, "trend") or {}).get("brake"))
    stop = bool(hw.get("stop"))
    if n == 0 and not trend and not stop:
        return None
    high, value = float(hw.get("high", 0.0)), float(hw.get("value", cost))
    down = (high - value) / high * 100.0 if high > 0 else 0.0
    parts = [
        f"The book holds {n} open position{'s' if n != 1 else ''}, cost ${cost:,.0f}, "
        f"marked at ${value:,.0f}",
        f"down {down:.0f}% from its high" if down >= 0.5 else "at its high",
    ]
    parts.append(
        "the market trend brake is on (no new buys)" if trend else "the market trend brake is off"
    )
    parts.append(
        "the drawdown breaker has stopped new entries"
        if stop
        else "the drawdown breaker has not tripped"
    )
    return "; ".join(parts) + "."


def _waiting_lines(vs: Session) -> list[str]:
    return [
        f"#{p.id} {'Buy' if p.kind == 'buy' else 'Sell'} {p.shares:g} {p.symbol}"
        for p in vs.scalars(
            select(ValueProposalRow)
            .where(ValueProposalRow.needs_tap.is_(True), ValueProposalRow.status == "pending")
            .order_by(ValueProposalRow.id)
        )
    ]


def compose(vs: Session, *, since: datetime, now: datetime, cfg: ValueCfg) -> Digest:
    shown = set((get_state(vs, STATE_KEY) or {}).get("shown", []))
    sections: list[str] = []
    minor = _minor_lines(vs, since)
    if minor:
        sections.append(
            "Re-evaluations since the last digest:\n" + "\n".join(f"  {m}" for m in minor)
        )
    review, keys = _review_lines(vs, now, cfg, shown)
    if review:
        sections.append(
            "Review cards (a review card never sells on its own):\n"
            + "\n".join(f"  {r}" for r in review)
        )
    book = _book_line(vs)
    if book:
        sections.append(book)
    waiting = _waiting_lines(vs)
    if waiting:
        sections.append(
            "Waiting for your tap (the buttons are on their own cards): " + ", ".join(waiting) + "."
        )
    if not sections:
        return Digest(None)
    head = f"Value book, night of {now.date()}:"
    return Digest("\n".join([head, *sections]), keys)


def build(vs: Session, *, since: datetime, now: datetime, cfg: ValueCfg) -> str | None:
    return compose(vs, since=since, now=now, cfg=cfg).text
