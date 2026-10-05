"""Read-only builders for the whole-account trade ledger (spec §4; revisions R3–R5, R9, R10).

executions -> orders -> option trades + stock lots -> ticker roll-ups -> USD portfolio summary.
Every figure on /ledger, in the CSV export and in the Google Sheet mirror comes from here, so they
agree by construction. Pure over loaded rows; never writes (tests/test_web_fence.py).
"""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import get_args

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.common.schemas import (
    LedgerClose,
    LedgerContract,
    LedgerOrphan,
    LedgerOutcome,
    LedgerTrade,
)
from src.storage.models import BrokerExecutionRow, TradeAnnotationRow

_EPS = 1e-9
_ROLL_WINDOW = timedelta(minutes=5)
# F10: the outcome vocabulary is defined once, on the `LedgerOutcome` Literal (src/common/schemas.py).
# Derived here rather than re-listed so the two can never drift apart.
_VALID_OUTCOMES: frozenset[str] = frozenset(get_args(LedgerOutcome))


def _sign(x: float) -> int:
    return (x > 0) - (x < 0)


def _tokens(codes: str) -> set[str]:
    return {c for c in codes.split(";") if c}


@dataclass(frozen=True)
class LedgerExec:
    """One non-superseded execution row, detached from the ORM."""

    row_id: int
    contract: LedgerContract
    trade_time: datetime  # aware UTC
    trade_date: date  # US/Eastern
    quantity: float
    price: float
    proceeds: float
    commission: float
    codes: str
    perm_id: int | None
    book: str
    ibkr_realized_pnl: float | None


@dataclass
class LedgerOrder:
    order_key: str
    contract: LedgerContract
    trade_time: datetime
    trade_date: date
    quantity: float
    price: float
    proceeds: float
    commission: float
    codes: str
    book: str
    ibkr_realized_pnl: float | None
    row_ids: list[int] = field(default_factory=list)

    def share(self, qty: float) -> tuple[float, float]:
        """(proceeds, commission) attributable to |qty| of this order."""
        frac = abs(qty) / abs(self.quantity) if self.quantity else 0.0
        return self.proceeds * frac, self.commission * frac

    @property
    def is_closing(self) -> bool:
        """True only for a pure close. IBKR gives a crossing order that both closes the old
        position and opens a new one the codes ``C;O`` together (group_orders also merges codes
        across a perm group, so a multi-fill crossing order ends up the same way) — that order
        must still flow through FIFO matching and leave its unmatched remainder as a new
        Opening, not get diverted to the orphan list for having a ``C`` token at all."""
        tokens = _tokens(self.codes)
        return "C" in tokens and "O" not in tokens


@dataclass
class Opening:
    order: LedgerOrder
    qty: float  # signed quantity this order opened
    remaining: float
    closes: list[tuple[LedgerOrder, float]] = field(default_factory=list)


@dataclass(frozen=True)
class LedgerAnnotation:
    order_key: str
    notes: str
    tags: list[str]
    outcome_override: str | None
    exclude_from_stats: bool


def group_orders(execs: list[LedgerExec]) -> list[LedgerOrder]:
    """Merge fills sharing a perm_id (per contract) and assign source-independent keys (R3).

    F18: the key signature deliberately excludes price. Task 4's twin pass tolerates up to a
    0.005 VWAP gap between a CSV order row and its exec-level twin; if price were part of the
    key, a superseding twin would hash to a different key than the CSV row it replaces, and any
    annotation keyed on the original would silently detach. The signature is
    (contract ident, ET trade date, sign of quantity, |quantity|, ordinal among otherwise-
    identical orders that day) — spec R3's "no re-keying is ever needed" depends on this.
    """
    buckets: dict[tuple[object, ...], list[LedgerExec]] = defaultdict(list)
    for e in execs:
        key: tuple[object, ...] = (
            ("perm", e.perm_id, e.contract.ident) if e.perm_id is not None else ("row", e.row_id)
        )
        buckets[key].append(e)
    orders: list[LedgerOrder] = []
    for group in buckets.values():
        group.sort(key=lambda e: e.trade_time)
        qty = sum(e.quantity for e in group)
        if abs(qty) < _EPS:
            continue
        realized = [e.ibkr_realized_pnl for e in group if e.ibkr_realized_pnl is not None]
        first = group[0]
        orders.append(
            LedgerOrder(
                order_key="",
                contract=first.contract,
                trade_time=first.trade_time,
                trade_date=first.trade_date,
                quantity=qty,
                price=sum(e.quantity * e.price for e in group) / qty,
                proceeds=sum(e.proceeds for e in group),
                commission=sum(e.commission for e in group),
                codes=";".join(dict.fromkeys(c for e in group for c in e.codes.split(";") if c)),
                book="system" if any(e.book == "system" for e in group) else "manual",
                ibkr_realized_pnl=sum(realized) if realized else None,
                row_ids=[e.row_id for e in group],
            )
        )
    orders.sort(key=lambda o: (o.trade_time, o.contract.ident))
    ordinal: Counter[tuple[str, ...]] = Counter()
    for o in orders:
        sig = (
            o.contract.ident,
            o.trade_date.isoformat(),
            str(_sign(o.quantity)),
            f"{abs(o.quantity):g}",
        )
        o.order_key = hashlib.sha1("|".join([*sig, str(ordinal[sig])]).encode()).hexdigest()[:16]
        ordinal[sig] += 1
    return orders


def fifo(orders: list[LedgerOrder]) -> tuple[list[Opening], list[tuple[LedgerOrder, float]]]:
    """FIFO-match one contract's orders. Returns (openings with their closes, orphan slices).

    A closing-coded order (code token ``C``) with nothing left to close is an orphan — its
    opening predates the imported history — and never becomes a new opposite position.
    """
    openings: list[Opening] = []
    orphans: list[tuple[LedgerOrder, float]] = []
    queue: deque[Opening] = deque()
    for o in sorted(orders, key=lambda x: x.trade_time):
        q = o.quantity
        while abs(q) > _EPS and queue and _sign(queue[0].remaining) != _sign(q):
            head = queue[0]
            m = min(abs(q), abs(head.remaining))
            head.closes.append((o, m))
            head.remaining += m * _sign(q)
            q -= m * _sign(q)
            if abs(head.remaining) < _EPS:
                queue.popleft()
        if abs(q) <= _EPS:
            continue
        if o.is_closing:
            orphans.append((o, abs(q)))
            continue
        op = Opening(order=o, qty=q, remaining=q)
        openings.append(op)
        queue.append(op)
    return openings, orphans


def _close_kind(codes: str, *, right: str, short: bool) -> LedgerOutcome:
    t = _tokens(codes)
    if "Ep" in t:
        return "Expired"
    if "A" in t:
        if not short:
            return "Exercised"
        return "Assigned" if right == "P" else "Called away"
    if "Ex" in t:
        return "Exercised"
    return "Bought back" if short else "Sold"


def _trade_from_opening(op: Opening, *, today: date) -> LedgerTrade:
    o, c = op.order, op.order.contract
    assert c.right is not None and c.strike is not None and c.expiry is not None
    short = op.qty < 0
    lots = abs(op.qty)
    premium, open_comm = o.share(op.qty)
    closes: list[LedgerClose] = []
    realized: list[float] = []
    row_ids = list(o.row_ids)
    for close_order, m in op.closes:
        cash, comm = close_order.share(m)
        closes.append(
            LedgerClose(
                order_key=close_order.order_key,
                close_date=close_order.trade_date,
                close_time=close_order.trade_time,
                quantity=m,
                cash=cash,
                commission=comm,
                codes=close_order.codes,
            )
        )
        row_ids.extend(close_order.row_ids)
        if close_order.ibkr_realized_pnl is not None:
            realized.append(close_order.ibkr_realized_pnl * m / abs(close_order.quantity))
    fully_closed = abs(lots - sum(x.quantity for x in closes)) < _EPS
    kinds = [_close_kind(x.codes, right=c.right, short=short) for x in closes]
    outcome: LedgerOutcome
    if fully_closed:
        biggest = max(range(len(closes)), key=lambda i: (closes[i].quantity, -i))
        outcome = kinds[biggest]
    else:
        outcome = "Pending" if c.expiry < today else "Open"
    close_date = max(x.close_date for x in closes) if fully_closed else None
    dte = max(1, (c.expiry - o.trade_date).days)
    days_held = max(1, ((close_date or today) - o.trade_date).days)
    capital = c.strike * c.multiplier * lots if short else abs(premium)
    net = premium + open_comm + sum(x.cash + x.commission for x in closes) if fully_closed else None
    return LedgerTrade(
        order_key=o.order_key,
        underlying=c.underlying,
        currency=c.currency,
        side="Sell" if short else "Buy",
        right=c.right,
        strike=c.strike,
        expiry=c.expiry,
        multiplier=c.multiplier,
        lots=lots,
        order_date=o.trade_date,
        open_time=o.trade_time,
        close_date=close_date,
        dte=dte,
        days_held=days_held,
        premium=premium,
        open_commission=open_comm,
        closes=closes,
        outcome=outcome,
        computed_outcome=outcome,
        mixed_close=len(set(kinds)) > 1,
        capital=capital,
        pct_profit=premium / capital * 365 / dte * 100 if short and capital else None,
        net_pnl=net,
        return_pct=net / capital * 100 if net is not None and capital else None,
        annualised_net_pct=net / capital * 365 / days_held * 100
        if net is not None and capital
        else None,
        book="system" if o.book == "system" else "manual",
        ibkr_realized_pnl=sum(realized) if realized else None,
        exec_row_ids=row_ids,
    )


def _link_rolls(trades: list[LedgerTrade]) -> None:
    """A buy-to-close followed within the session by a same-underlying, same-right new short."""
    opens: dict[tuple[str, str, date], list[LedgerTrade]] = defaultdict(list)
    for t in trades:
        if t.side == "Sell":
            opens[(t.underlying, t.right, t.order_date)].append(t)
    taken: set[str] = set()
    for t in sorted(trades, key=lambda x: x.open_time):
        if t.computed_outcome != "Bought back" or not t.closes:
            continue
        last = max(t.closes, key=lambda x: x.close_time)
        candidates = [
            n
            for n in opens.get((t.underlying, t.right, last.close_date), [])
            if n.order_key != t.order_key
            and n.order_key not in taken
            and n.open_time >= last.close_time - _ROLL_WINDOW
        ]
        if not candidates:
            continue
        nxt = min(candidates, key=lambda n: abs((n.open_time - last.close_time).total_seconds()))
        taken.add(nxt.order_key)
        t.outcome = t.computed_outcome = "Rolled"
        t.rolled_to = nxt.order_key
        nxt.rolled_from = t.order_key


def _orphan(order: LedgerOrder, qty: float) -> LedgerOrphan:
    c = order.contract
    realized = (
        order.ibkr_realized_pnl * qty / abs(order.quantity)
        if order.ibkr_realized_pnl is not None
        else None
    )
    return LedgerOrphan(
        order_key=order.order_key,
        underlying=c.underlying,
        sec_type=c.sec_type,
        contract_ident=c.ident,
        currency=c.currency,
        trade_date=order.trade_date,
        quantity=qty,
        price=order.price,
        ibkr_realized_pnl=realized,
    )


def build_option_trades(
    orders: list[LedgerOrder], *, today: date
) -> tuple[list[LedgerTrade], list[LedgerOrphan]]:
    by_contract: dict[str, list[LedgerOrder]] = defaultdict(list)
    for o in orders:
        if o.contract.sec_type == "OPT":
            by_contract[o.contract.ident].append(o)
    trades: list[LedgerTrade] = []
    orphans: list[LedgerOrphan] = []
    for group in by_contract.values():
        openings, orphan_slices = fifo(group)
        trades.extend(_trade_from_opening(op, today=today) for op in openings)
        orphans.extend(_orphan(o, q) for o, q in orphan_slices)
    _link_rolls(trades)
    trades.sort(key=lambda t: (t.open_time, t.order_key))
    return trades, orphans


def apply_annotations(trades: list[LedgerTrade], annotations: dict[str, LedgerAnnotation]) -> None:
    for t in trades:
        a = annotations.get(t.order_key)
        if a is None:
            continue
        t.notes, t.tags, t.exclude_from_stats = a.notes, list(a.tags), a.exclude_from_stats
        if a.outcome_override and a.outcome_override in _VALID_OUTCOMES:
            t.outcome = a.outcome_override  # type: ignore[assignment]
            t.outcome_overridden = True


def load_execs(session: Session) -> list[LedgerExec]:
    rows = session.scalars(
        select(BrokerExecutionRow).where(BrokerExecutionRow.superseded_by.is_(None))
    )
    return [
        LedgerExec(
            row_id=r.id,
            contract=LedgerContract(
                underlying=r.underlying,
                sec_type="OPT" if r.sec_type == "OPT" else "STK",
                currency=r.currency,
                right="P" if r.right == "P" else "C" if r.right == "C" else None,
                strike=r.strike,
                expiry=r.expiry,
                multiplier=r.multiplier,
            ),
            trade_time=r.trade_time.replace(tzinfo=UTC),
            trade_date=r.trade_date,
            quantity=r.quantity,
            price=r.price,
            proceeds=r.proceeds,
            commission=r.commission,
            codes=r.codes,
            perm_id=r.perm_id,
            book=r.book,
            ibkr_realized_pnl=r.ibkr_realized_pnl,
        )
        for r in rows
    ]


def load_annotations(session: Session) -> dict[str, LedgerAnnotation]:
    return {
        r.order_key: LedgerAnnotation(
            order_key=r.order_key,
            notes=r.notes or "",
            tags=list(r.tags or []),
            outcome_override=r.outcome_override,
            exclude_from_stats=bool(r.exclude_from_stats),
        )
        for r in session.scalars(select(TradeAnnotationRow))
    }
