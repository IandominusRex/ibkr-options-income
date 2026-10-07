"""Read-only builders for the whole-account trade ledger (spec §4; revisions R3–R5, R9, R10).

executions -> orders -> option trades + stock lots -> ticker roll-ups -> USD portfolio summary.
Every figure on /ledger, in the CSV export and in the Google Sheet mirror comes from here, so they
agree by construction. Pure over loaded rows; never writes (tests/test_web_fence.py).
"""

from __future__ import annotations

import bisect
import hashlib
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Literal, get_args

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.common.config import get_config
from src.common.schemas import (
    LedgerBasisPoint,
    LedgerBook,
    LedgerBucket,
    LedgerCashItem,
    LedgerClose,
    LedgerContract,
    LedgerCurvePoint,
    LedgerMonth,
    LedgerOrphan,
    LedgerOutcome,
    LedgerStockDisposal,
    LedgerStockLot,
    LedgerSummary,
    LedgerTicker,
    LedgerTickerDetail,
    LedgerTrade,
    PortfolioSnapshot,
)
from src.ledger.state import ledger_account
from src.storage.models import (
    BrokerCashEventRow,
    BrokerCorporateActionRow,
    BrokerExecutionRow,
    FxRateRow,
    TradeAnnotationRow,
)

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


# --------------------------------------------------------------------------- #
# Stock lots (spec §4.3)
# --------------------------------------------------------------------------- #
def build_stock_lots(
    orders: list[LedgerOrder],
) -> tuple[list[LedgerStockLot], list[LedgerStockDisposal], list[LedgerOrphan]]:
    """FIFO share lots. Cost is commission-inclusive: ``-(proceeds + commission) / qty``."""
    lots: list[LedgerStockLot] = []
    disposals: list[LedgerStockDisposal] = []
    orphans: list[LedgerOrphan] = []
    by_contract: dict[str, list[LedgerOrder]] = defaultdict(list)
    for o in orders:
        if o.contract.sec_type == "STK":
            by_contract[o.contract.ident].append(o)
    for group in by_contract.values():
        queue: deque[LedgerStockLot] = deque()
        for o in sorted(group, key=lambda x: x.trade_time):
            basis = -(o.proceeds + o.commission) / o.quantity
            q = o.quantity
            while abs(q) > _EPS and queue and _sign(queue[0].remaining) != _sign(q):
                head = queue[0]
                m = min(abs(q), abs(head.remaining))
                disposals.append(
                    LedgerStockDisposal(
                        lot_key=head.lot_key,
                        underlying=head.underlying,
                        currency=head.currency,
                        disposal_date=o.trade_date,
                        quantity=m,
                        price=o.price,
                        realized=(basis - head.cost_per_share) * m * _sign(head.remaining),
                        codes=o.codes,
                    )
                )
                head.remaining += m * _sign(q)
                q -= m * _sign(q)
                if abs(head.remaining) < _EPS:
                    head.remaining = 0.0
                    queue.popleft()
            if abs(q) <= _EPS:
                continue
            if o.is_closing:
                orphans.append(_orphan(o, abs(q)))
                continue
            t = _tokens(o.codes)
            lot = LedgerStockLot(
                lot_key=o.order_key,
                underlying=o.contract.underlying,
                currency=o.contract.currency,
                acquired_date=o.trade_date,
                source="assigned" if "A" in t else "exercised" if "Ex" in t else "bought",
                quantity=q,
                remaining=q,
                cost_per_share=basis,
            )
            lots.append(lot)
            queue.append(lot)
    return lots, disposals, orphans


def attach_stock_gains(trades: list[LedgerTrade], disposals: list[LedgerStockDisposal]) -> None:
    """The sheet's "Capital" column: stock P&L realized when a short call got the shares called away."""
    for t in trades:
        if t.computed_outcome != "Called away" or t.close_date is None:
            continue
        gains = [
            d.realized
            for d in disposals
            if d.underlying == t.underlying
            and d.disposal_date == t.close_date
            and "A" in _tokens(d.codes)
            and abs(d.price - t.strike) < 1e-6
        ]
        t.stock_gain = sum(gains) if gains else None


# --------------------------------------------------------------------------- #
# FX (spec §3 fx_rates; R5)
# --------------------------------------------------------------------------- #
class FxTable:
    """USD conversion at the nearest rate within ``max_gap_days`` of the date; else None."""

    def __init__(self, rates: dict[str, list[tuple[date, float]]], max_gap_days: int) -> None:
        self._rates = {c: sorted(series) for c, series in rates.items()}
        self._dates = {c: [d for d, _ in series] for c, series in self._rates.items()}
        self._max_gap = max_gap_days

    def to_usd(self, amount: float, currency: str, on: date) -> float | None:
        if currency == "USD":
            return amount
        series = self._rates.get(currency)
        if not series:
            return None
        i = bisect.bisect_left(self._dates[currency], on)
        best: tuple[int, float] | None = None
        for j in (i - 1, i):
            if 0 <= j < len(series):
                d, rate = series[j]
                gap = abs((d - on).days)
                if gap <= self._max_gap and (best is None or gap < best[0]):
                    best = (gap, rate)
        return amount * best[1] if best else None


# --------------------------------------------------------------------------- #
# Ticker roll-ups (spec §4.4)
# --------------------------------------------------------------------------- #
def _collected(t: LedgerTrade) -> float:
    return t.net_pnl if t.net_pnl is not None else t.premium + t.open_commission


def _in_basis_scope(t: LedgerTrade, open_lots: list[LedgerStockLot]) -> bool:
    if t.side != "Sell":
        return False
    start = min(lot.acquired_date for lot in open_lots)
    assigned_on = {lot.acquired_date for lot in open_lots if lot.source == "assigned"}
    return t.order_date >= start or (
        t.computed_outcome == "Assigned" and t.close_date in assigned_on
    )


def _wheel_basis(
    trades: list[LedgerTrade], open_lots: list[LedgerStockLot], shares: float
) -> float | None:
    if shares <= _EPS or not open_lots:
        return None
    cost = sum(lot.remaining * lot.cost_per_share for lot in open_lots)
    collected = sum(_collected(t) for t in trades if _in_basis_scope(t, open_lots))
    return (cost - collected) / shares


def basis_walk(trades: list[LedgerTrade], lots: list[LedgerStockLot]) -> list[LedgerBasisPoint]:
    open_lots = [lot for lot in lots if lot.remaining > _EPS]
    shares = sum(lot.remaining for lot in open_lots)
    if shares <= _EPS:
        return []
    cost = sum(lot.remaining * lot.cost_per_share for lot in open_lots)
    start = min(lot.acquired_date for lot in open_lots)
    points = [
        LedgerBasisPoint(point_date=start, label="Shares acquired", basis_per_share=cost / shares)
    ]
    collected = 0.0
    scoped = sorted(
        (t for t in trades if _in_basis_scope(t, open_lots)),
        key=lambda t: (t.close_date or t.order_date, t.open_time),
    )
    for t in scoped:
        collected += _collected(t)
        points.append(
            LedgerBasisPoint(
                point_date=t.close_date or t.order_date,
                label=f"{t.side} {t.strike:g}{t.right} {t.outcome}",
                basis_per_share=(cost - collected) / shares,
            )
        )
    return points


def _unrealized(symbol: str, has_open: bool, snapshot: PortfolioSnapshot | None) -> float | None:
    if snapshot is None:
        return None
    marks = [
        p.unrealized_pnl
        for p in snapshot.positions
        if p.unrealized_pnl is not None
        and (
            (p.sec_type == "OPT" and p.underlying == symbol)
            or (p.sec_type == "STK" and p.symbol == symbol)
        )
    ]
    if marks:
        return sum(marks)
    return None if has_open else 0.0


def build_tickers(
    trades: list[LedgerTrade],
    lots: list[LedgerStockLot],
    disposals: list[LedgerStockDisposal],
    cash: list[LedgerCashItem],
    *,
    snapshot: PortfolioSnapshot | None,
) -> list[LedgerTicker]:
    income = [c for c in cash if c.underlying and c.event_type in ("dividend", "withholding")]
    symbols = sorted(
        {t.underlying for t in trades}
        | {lot.underlying for lot in lots}
        | {c.underlying for c in income if c.underlying}
    )
    out: list[LedgerTicker] = []
    for sym in symbols:
        ts = [t for t in trades if t.underlying == sym]
        closed = [t for t in ts if t.net_pnl is not None]
        stats = [t for t in closed if not t.exclude_from_stats]
        sym_lots = [lot for lot in lots if lot.underlying == sym]
        open_lots = [lot for lot in sym_lots if abs(lot.remaining) > _EPS]
        shares = sum(lot.remaining for lot in open_lots)
        currency = (
            ts[0].currency
            if ts
            else sym_lots[0].currency
            if sym_lots
            else next(c.currency for c in income if c.underlying == sym)
        )
        option_net = sum(t.net_pnl for t in closed if t.net_pnl is not None)
        stock_realized = sum(d.realized for d in disposals if d.underlying == sym)
        dividends = sum(c.amount for c in income if c.underlying == sym)
        capital_days = sum(t.capital * t.days_held for t in stats)
        stats_net = [t.net_pnl for t in stats if t.net_pnl is not None]
        open_trades = [t for t in ts if t.close_date is None]
        dates = [t.order_date for t in ts] + [lot.acquired_date for lot in sym_lots]
        out.append(
            LedgerTicker(
                symbol=sym,
                currency=currency,
                option_premium_gross=sum(t.premium for t in ts if t.side == "Sell"),
                option_net_pnl=option_net,
                stock_realized=stock_realized,
                dividends_net=dividends,
                total_realized=option_net + stock_realized + dividends,
                unrealized=_unrealized(sym, bool(open_trades) or shares > _EPS, snapshot),
                n_trades=len(ts),
                n_open=len(open_trades),
                n_closed=len(closed),
                win_rate=sum(1 for v in stats_net if v > 0) / len(stats_net) if stats_net else None,
                avg_premium=(sum(t.premium for t in stats) / len(stats)) if stats else None,
                best_trade=max(stats_net) if stats_net else None,
                worst_trade=min(stats_net) if stats_net else None,
                annualised_return_pct=(sum(stats_net) / capital_days * 365 * 100)
                if capital_days
                else None,
                shares_held=shares,
                broker_avg_cost=(
                    sum(lot.remaining * lot.cost_per_share for lot in open_lots) / shares
                )
                if shares > _EPS
                else None,
                wheel_adjusted_basis=_wheel_basis(ts, open_lots, shares),
                first_trade=min(dates) if dates else None,
                last_trade=max(dates) if dates else None,
            )
        )
    return out


# --------------------------------------------------------------------------- #
# Portfolio summary (spec §4.5; R5)
# --------------------------------------------------------------------------- #
def _bucket(label: str, items: list[tuple[float, bool]]) -> LedgerBucket:
    """``items`` = (realized_usd, counts_for_win_rate)."""
    stats = [v for v, counts in items if counts]
    return LedgerBucket(
        label=label,
        n_closed=len(items),
        realized_usd=sum(v for v, _ in items),
        win_rate=sum(1 for v in stats if v > 0) / len(stats) if stats else None,
    )


def build_summary(
    trades: list[LedgerTrade],
    tickers: list[LedgerTicker],
    lots: list[LedgerStockLot],
    disposals: list[LedgerStockDisposal],
    cash: list[LedgerCashItem],
    fx: FxTable,
    *,
    today: date,
    snapshot: PortfolioSnapshot | None,
    orphans: list[LedgerOrphan],
    unreviewed_corporate_actions: int,
    marks_as_of: datetime | None,
) -> LedgerSummary:
    missing = False

    def usd(amount: float, currency: str, on: date) -> float:
        nonlocal missing
        value = fx.to_usd(amount, currency, on)
        if value is None:
            missing = True
            return 0.0
        return value

    realized: list[tuple[date, float]] = []
    strategy_items: dict[str, list[tuple[float, bool]]] = defaultdict(list)
    book_items: dict[str, list[tuple[float, bool]]] = defaultdict(list)
    for t in trades:
        if t.net_pnl is None or t.close_date is None:
            continue
        v = usd(t.net_pnl, t.currency, t.close_date)
        realized.append((t.close_date, v))
        label = "Long" if t.side == "Buy" else "CSP" if t.right == "P" else "CC"
        strategy_items[label].append((v, not t.exclude_from_stats))
        book_items[t.book].append((v, not t.exclude_from_stats))
    for disp in disposals:
        v = usd(disp.realized, disp.currency, disp.disposal_date)
        realized.append((disp.disposal_date, v))
        strategy_items["Stock"].append((v, False))
    for c in cash:
        if c.event_type in ("dividend", "withholding"):
            realized.append((c.event_date, usd(c.amount, c.currency, c.event_date)))
    for o in orphans:
        if o.ibkr_realized_pnl is not None:
            realized.append((o.trade_date, usd(o.ibkr_realized_pnl, o.currency, o.trade_date)))
    other = sum(
        usd(c.amount, c.currency, c.event_date) for c in cash if c.event_type in ("interest", "fee")
    )
    total = sum(v for _, v in realized) + other

    flows = [c for c in cash if c.event_type in ("deposit", "withdrawal")]
    contributed = sum(usd(c.amount, c.currency, c.event_date) for c in flows) if flows else None
    utilised = sum(
        usd(t.strike * t.multiplier * t.lots, t.currency, today)
        for t in trades
        if t.side == "Sell" and t.right == "P" and t.close_date is None
    ) + sum(
        usd(lot.remaining * lot.cost_per_share, lot.currency, lot.acquired_date)
        for lot in lots
        if lot.remaining > _EPS
    )
    unrealized = (
        None
        if snapshot is None or any(tk.unrealized is None for tk in tickers)
        else sum(
            usd(tk.unrealized, tk.currency, today) for tk in tickers if tk.unrealized is not None
        )
    )

    months: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for t in trades:
        if t.side == "Sell":
            months[t.order_date.strftime("%Y-%m")][0] += usd(t.premium, t.currency, t.order_date)
    for d, v in realized:
        months[d.strftime("%Y-%m")][1] += v
    curve: list[LedgerCurvePoint] = []
    running = 0.0
    by_day: dict[date, float] = defaultdict(float)
    for d, v in realized:
        by_day[d] += v
    for d in sorted(by_day):
        running += by_day[d]
        curve.append(LedgerCurvePoint(point_date=d, cumulative_usd=running))

    stats = [t.net_pnl for t in trades if t.net_pnl is not None and not t.exclude_from_stats]
    open_trades = sorted((t for t in trades if t.close_date is None), key=lambda t: t.expiry)
    this_month = today.strftime("%Y-%m")
    return LedgerSummary(
        total_realized_usd=total,
        interest_and_fees_usd=other,
        contributed_usd=contributed,
        capital_utilised_usd=utilised,
        available_usd=contributed + total - utilised if contributed is not None else None,
        unrealized_usd=unrealized,
        win_rate=sum(1 for v in stats if v > 0) / len(stats) if stats else None,
        n_trades=len(trades),
        n_open=len(open_trades),
        premium_this_month_usd=months[this_month][0] if this_month in months else 0.0,
        months=[
            LedgerMonth(month=m, premium_usd=v[0], realized_usd=v[1])
            for m, v in sorted(months.items())
        ],
        curve=curve,
        by_strategy=[_bucket(k, v) for k, v in sorted(strategy_items.items())],
        by_book=[_bucket(k, v) for k, v in sorted(book_items.items())],
        upcoming=open_trades[:20],
        fx_incomplete=missing,
        orphan_closes=len(orphans),
        unreviewed_corporate_actions=unreviewed_corporate_actions,
        marks_as_of=marks_as_of,
    )


# --------------------------------------------------------------------------- #
# Loading + the one entry point
# --------------------------------------------------------------------------- #
def load_cash(session: Session) -> list[LedgerCashItem]:
    return [
        LedgerCashItem(
            event_date=r.event_date,
            event_type=r.event_type,
            currency=r.currency,
            amount=r.amount,
            description=r.description,
            underlying=r.underlying,
        )
        for r in session.scalars(select(BrokerCashEventRow).order_by(BrokerCashEventRow.event_date))
    ]


def load_fx(session: Session, max_gap_days: int) -> FxTable:
    rates: dict[str, list[tuple[date, float]]] = defaultdict(list)
    for r in session.scalars(select(FxRateRow)):
        rates[r.currency].append((r.rate_date, r.usd_rate))
    return FxTable(dict(rates), max_gap_days)


def build_book(
    session: Session,
    *,
    today: date,
    snapshot: PortfolioSnapshot | None,
    marks_as_of: datetime | None = None,
) -> LedgerBook:
    orders = group_orders(load_execs(session))
    trades, option_orphans = build_option_trades(orders, today=today)
    apply_annotations(trades, load_annotations(session))
    lots, disposals, stock_orphans = build_stock_lots(orders)
    attach_stock_gains(trades, disposals)
    cash = load_cash(session)
    # F5: the live PortfolioSnapshot is captured from the paper account while the ledger
    # tracks the real account (ledger_account). A snapshot from any other account must never
    # be borrowed for this account's marks — treat it as absent rather than silently mixing
    # books. Spec: "No position snapshot -> unrealized/available shown as n/a, never 0".
    effective_snapshot = (
        snapshot
        if snapshot is not None
        and snapshot.account is not None
        and snapshot.account.account == ledger_account(session)
        else None
    )
    tickers = build_tickers(trades, lots, disposals, cash, snapshot=effective_snapshot)
    orphans = option_orphans + stock_orphans
    unreviewed = (
        session.scalar(
            select(func.count())
            .select_from(BrokerCorporateActionRow)
            .where(BrokerCorporateActionRow.reviewed.is_(False))
        )
        or 0
    )
    summary = build_summary(
        trades,
        tickers,
        lots,
        disposals,
        cash,
        load_fx(session, get_config().ledger.fx_max_gap_days),
        today=today,
        snapshot=effective_snapshot,
        orphans=orphans,
        unreviewed_corporate_actions=int(unreviewed),
        marks_as_of=marks_as_of,
    )
    return LedgerBook(
        trades=trades,
        orphans=orphans,
        tickers=tickers,
        summary=summary,
        lots=lots,
        disposals=disposals,
        cash=cash,
    )


def ticker_detail(book: LedgerBook, symbol: str) -> LedgerTickerDetail | None:
    sym = symbol.upper()
    ticker = next((t for t in book.tickers if t.symbol.upper() == sym), None)
    if ticker is None:
        return None
    trades = [t for t in book.trades if t.underlying.upper() == sym]
    lots = [lot for lot in book.lots if lot.underlying.upper() == sym]
    return LedgerTickerDetail(
        ticker=ticker,
        trades=trades,
        lots=lots,
        disposals=[d for d in book.disposals if d.underlying.upper() == sym],
        dividends=[c for c in book.cash if (c.underlying or "").upper() == sym],
        basis_walk=basis_walk(trades, lots),
    )


# --------------------------------------------------------------------------- #
# Sheet-format rows (CSV export + Google Sheet mirror) and filters (spec §6.1, §7)
# --------------------------------------------------------------------------- #
SHEET_HEADER: list[str] = [
    "Sell/Buy",
    "Put/Call",
    "Order Date",
    "Expiration Date",
    "Ticker",
    "Lots",
    "Strike Price",
    "Premium",
    "Outcome",
    "Capital",
    "DTE",
    "% Profit",
    "Notes",
    "Close Date",
    "Net P&L",
    "Book",
    "Tags",
    "Commission",
]
TICKER_HEADER: list[str] = [
    "Ticker",
    "Currency",
    "Total realized",
    "Option net",
    "Stock realized",
    "Dividends",
    "Unrealized",
    "Trades",
    "Open",
    "Win rate",
    "Shares",
    "Broker avg cost",
    "Wheel-adjusted basis",
    "Annualised return %",
]
# F10: the sort vocabulary is defined once, as `TradeSort`, and derived into `TRADE_SORTS` so the
# two can never drift apart. Task 9's API imports `TradeSort` rather than re-listing the strings.
TradeSort = Literal[
    "order_date",
    "-order_date",
    "expiry",
    "-expiry",
    "pct_profit",
    "-pct_profit",
    "net_pnl",
    "-net_pnl",
    "underlying",
    "-underlying",
]
TRADE_SORTS: tuple[str, ...] = get_args(TradeSort)


def _num(v: float) -> float | int:
    return int(v) if float(v).is_integer() else round(v, 4)


def _blank(v: float | None, digits: int = 2) -> object:
    return "" if v is None else round(v, digits)


def sheet_row(t: LedgerTrade) -> list[object]:
    commission = t.open_commission + sum(c.commission for c in t.closes)
    return [
        t.side,
        "Put" if t.right == "P" else "Call",
        t.order_date.isoformat(),
        t.expiry.isoformat(),
        t.underlying,
        _num(t.lots),
        _num(t.strike),
        round(t.premium, 2),
        t.outcome,
        _blank(t.stock_gain),
        t.dte,
        "" if t.pct_profit is None else f"{t.pct_profit:.2f}%",
        t.notes,
        t.close_date.isoformat() if t.close_date else "",
        _blank(t.net_pnl),
        t.book,
        ", ".join(t.tags),
        round(commission, 2),
    ]


def ticker_row(t: LedgerTicker) -> list[object]:
    return [
        t.symbol,
        t.currency,
        round(t.total_realized, 2),
        round(t.option_net_pnl, 2),
        round(t.stock_realized, 2),
        round(t.dividends_net, 2),
        _blank(t.unrealized),
        t.n_trades,
        t.n_open,
        "" if t.win_rate is None else f"{t.win_rate * 100:.0f}%",
        _num(t.shares_held),
        _blank(t.broker_avg_cost, 4),
        _blank(t.wheel_adjusted_basis, 4),
        "" if t.annualised_return_pct is None else f"{t.annualised_return_pct:.2f}%",
    ]


BUY_HOLD_HEADER: list[str] = [
    "Ticker",
    "Currency",
    "Shares",
    "Avg cost",
    "Cost basis",
    "Lots",
    "First acquired",
    "Source",
    "Dividends",
    "Stock realized",
    "Wheel-adjusted basis",
]


def buy_hold_rows(book: LedgerBook) -> list[list[object]]:
    """One row per ticker with open stock lots: the long-term holdings view for the sheet.

    Native currency throughout (SGD / GBP lines are never converted), commission-inclusive cost,
    and no market value — the sheet carries no live marks. ``Source`` splits the open shares by
    how they were acquired (bought / assigned / exercised) so wheel-assigned shares can be told
    apart from deliberate buys.
    """
    tickers = {t.symbol: t for t in book.tickers}
    by_symbol: dict[str, list[LedgerStockLot]] = defaultdict(list)
    for lot in book.lots:
        if lot.remaining > 1e-9:
            by_symbol[lot.underlying].append(lot)
    rows: list[list[object]] = []
    for symbol in sorted(by_symbol):
        lots = by_symbol[symbol]
        shares = sum(lot.remaining for lot in lots)
        cost = sum(lot.remaining * lot.cost_per_share for lot in lots)
        by_source: dict[str, float] = defaultdict(float)
        for lot in lots:
            by_source[lot.source] += lot.remaining
        tk = tickers.get(symbol)
        rows.append(
            [
                symbol,
                lots[0].currency,
                _num(shares),
                round(cost / shares, 4),
                round(cost, 2),
                len(lots),
                min(lot.acquired_date for lot in lots).isoformat(),
                ", ".join(f"{src} {_num(q)}" for src, q in sorted(by_source.items())),
                _blank(tk.dividends_net) if tk else "",
                _blank(tk.stock_realized) if tk else "",
                _blank(tk.wheel_adjusted_basis, 4) if tk else "",
            ]
        )
    header: list[object] = list(BUY_HOLD_HEADER)
    return [header, *rows]


def summary_rows(s: LedgerSummary) -> list[list[object]]:
    def money(v: float | None) -> object:
        return "n/a" if v is None else round(v, 2)

    return [
        ["Metric", "Value (USD)"],
        ["Total Profit", money(s.total_realized_usd)],
        ["Contributed capital", money(s.contributed_usd)],
        ["Capital utilised", money(s.capital_utilised_usd)],
        ["Available capital", money(s.available_usd)],
        ["Unrealized", money(s.unrealized_usd)],
        ["Win rate", "n/a" if s.win_rate is None else f"{s.win_rate * 100:.0f}%"],
        ["Premium this month", money(s.premium_this_month_usd)],
        ["Trades", s.n_trades],
        ["Open trades", s.n_open],
        ["FX incomplete", "yes" if s.fx_incomplete else "no"],
        ["Orphan closes", s.orphan_closes],
    ]


def filter_trades(
    trades: list[LedgerTrade],
    *,
    symbol: str | None = None,
    right: Literal["C", "P"] | None = None,
    outcome: LedgerOutcome | None = None,
    book: Literal["system", "manual"] | None = None,
    tag: str | None = None,
    since: date | None = None,
    until: date | None = None,
    sort: TradeSort = "-order_date",
) -> list[LedgerTrade]:
    out = [
        t
        for t in trades
        if (symbol is None or t.underlying.upper() == symbol.upper())
        and (right is None or t.right == right)
        and (outcome is None or t.outcome == outcome)
        and (book is None or t.book == book)
        and (tag is None or tag in t.tags)
        and (since is None or t.order_date >= since)
        and (until is None or t.order_date <= until)
    ]
    field_name = sort.lstrip("-")
    if sort not in TRADE_SORTS:
        raise ValueError(f"unknown sort {sort!r}")
    present = [t for t in out if getattr(t, field_name) is not None]
    absent = [t for t in out if getattr(t, field_name) is None]
    present.sort(key=lambda t: (getattr(t, field_name), t.open_time), reverse=sort.startswith("-"))
    return present + absent
