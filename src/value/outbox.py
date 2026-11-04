"""Which cards are due, and marking each posted once (Part 6 Task 4, rulings 11 and 14).

``due`` reads value.db and returns the cards, oldest first; ``mark_posted`` stamps them after
``src.value.notify.send_cards`` reports which keys it sent. A card is posted once: its row's
``posted_at`` (or the trim episode's ``trim_posted``) is set. Rows older than ``MAX_AGE`` are never
posted, so a database that predates the ``posted_at`` columns does not replay its whole history.
Minor re-evaluations and shadow entries' re-evaluations are not cards (the nightly digest, Task 6,
lists the minor ones).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.common import value_view
from src.common.config import ValueCfg
from src.value import cards
from src.value.book import get_state, set_state
from src.value.store import (
    ValueAttributionRow,
    ValueEffectiveRow,
    ValuePositionRow,
    ValueProposalRow,
    ValueReevaluationRow,
    ValueTickerFileRow,
)

MAX_AGE = timedelta(hours=48)
TICKER_QUEUE = (
    "ticker_cards"  # value_book_state: {symbol: queued_at} for the one-name cards (Task 8)
)


def queue_ticker_card(vs: Session, symbol: str, now: datetime) -> None:
    """A Telegram ``/value NAME`` refresh asks for its card; the next outbox tick posts it once."""
    queue = dict(get_state(vs, TICKER_QUEUE) or {})
    queue[symbol] = now.isoformat()
    set_state(vs, TICKER_QUEUE, queue, now)


def _trim_candidates(vs: Session) -> list[tuple[str, float]]:
    from src.value.book import sell_shares, totals

    held = totals(vs).names
    out: list[tuple[str, float]] = []
    for pos in vs.scalars(select(ValuePositionRow).where(ValuePositionRow.status == "open")):
        h = held.get(pos.symbol)
        shares = sell_shares(h.filled if h else 0.0, 0.5)
        if shares > 0:
            out.append((pos.symbol, float(shares)))
    return out


def due(vs: Session, now: datetime, cfg: ValueCfg) -> list[cards.Card]:
    out: list[tuple[datetime, cards.Card]] = []
    release = cfg.book.release.max_closes_per_request
    for p in vs.scalars(
        select(ValueProposalRow)
        .where(
            ValueProposalRow.posted_at.is_(None),
            ValueProposalRow.status.in_(("pending", "approved")),
            ValueProposalRow.expires_at > now,
            ValueProposalRow.created_at > now - MAX_AGE,
        )
        .order_by(ValueProposalRow.id)
    ):
        eff = vs.get(ValueEffectiveRow, (p.symbol, p.list_name))
        fair, mos, by = (
            (eff.fair_value, eff.margin_of_safety, eff.decided_by)
            if eff is not None
            else (None, None, p.cause)
        )
        if fair is None and eff is None:  # a held name's file, when the effective row is gone
            tf = vs.get(ValueTickerFileRow, p.symbol)
            if tf is not None:
                deep = p.list_name == "deep_value"
                fair = tf.fair_value_deep if deep else tf.fair_value_growth
                mos = tf.mos_deep if deep else tf.mos_growth
        out.append(
            (
                p.created_at,
                cards.proposal_card(
                    p,
                    release_closes=release,
                    fair_value=fair,
                    mos=mos,
                    verdict_by=by,
                    tranches=cfg.book.tranches,
                ),
            )
        )
    for r in vs.scalars(
        select(ValueReevaluationRow)
        .where(
            ValueReevaluationRow.posted_at.is_(None),
            ValueReevaluationRow.severity == "major",
            ValueReevaluationRow.position_id.is_not(
                None
            ),  # a held name's row, not a shadow entry's
            ValueReevaluationRow.created_at > now - MAX_AGE,
        )
        .order_by(ValueReevaluationRow.id)
    ):
        out.append((r.created_at, cards.reevaluation_card(r)))
    hw = get_state(vs, "high_water") or {}
    if hw.get("episode") and not hw.get("trim_posted"):
        offered = hw.get("trim_offered_at")
        out.append(
            (
                datetime.fromisoformat(offered) if offered else now,
                cards.trim_card(hw, _trim_candidates(vs)),
            )
        )
    for a in vs.scalars(
        select(ValueAttributionRow)
        .where(ValueAttributionRow.state == "frozen", ValueAttributionRow.posted_at.is_(None))
        .order_by(ValueAttributionRow.symbol)
    ):
        out.append((a.since or a.updated_at, cards.freeze_card(a.symbol, a.detail)))
    for symbol, queued in sorted((get_state(vs, TICKER_QUEUE) or {}).items()):
        at = datetime.fromisoformat(queued)
        view = value_view.read_ticker_file(symbol) if at > now - MAX_AGE else None
        if view is not None:
            out.append((at, cards.ticker_card(view)))
    out.sort(key=lambda t: t[0])
    return [c for _, c in out]


def mark_posted(vs: Session, keys: list[str], now: datetime) -> None:
    for key in keys:
        kind, _, ident = key.partition(":")
        if kind == "proposal":
            row = vs.get(ValueProposalRow, int(ident))
            if row is not None:
                row.posted_at = now
        elif kind == "reeval":
            r = vs.get(ValueReevaluationRow, int(ident))
            if r is not None:
                r.posted_at = now
        elif kind == "freeze":
            a = vs.get(ValueAttributionRow, ident)
            if a is not None:
                a.posted_at = now
        elif kind == "ticker":
            queue = dict(get_state(vs, TICKER_QUEUE) or {})
            if queue.pop(ident, None) is not None:
                set_state(vs, TICKER_QUEUE, queue, now)
        elif kind == "trim":
            hw = get_state(vs, "high_water") or {}
            if hw.get("episode") == ident:
                set_state(vs, "high_water", {**hw, "trim_posted": now.isoformat()}, now)
