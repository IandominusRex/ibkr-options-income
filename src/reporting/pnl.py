"""Read-only P&L builders over the trading DB (P3-P4 M4).

Pure functions returning the `src/common/schemas.py` P&L types. Nothing here writes,
nothing here takes a snapshot the caller did not hand in, and no figure is invented:
unknown means `None`, never `0.0`. Computed on read, never materialized (spec §6.6).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.common.schemas import (
    CampaignPnl,
    OptionRight,
    PnlBucket,
    PnlLeg,
    PnlSummary,
    PortfolioSnapshot,
    Strategy,
    VerdictOutcome,
)
from src.reporting.legs import classify_outcome, fill_economics
from src.storage.models import (
    ApprovalRow,
    CampaignRow,
    CandidateRow,
    FillRow,
    OrderRow,
)

log = logging.getLogger(__name__)

_SessionFactory = Callable[[], Session]


def _annualize(net_pnl: float, collateral: float, days_held: int) -> float | None:
    if days_held <= 0 or collateral <= 0:
        return None
    roc = net_pnl / collateral
    return roc * (365.0 / days_held) * 100.0


def build_legs(
    session: _SessionFactory,
    *,
    since: date | None = None,
    symbol: str | None = None,
    include_paper: bool = True,
    include_live: bool = True,
) -> list[PnlLeg]:
    """Every option leg the system has fills for, newest first.

    One leg per candidate_id that has at least one fill. A candidate with no fill was
    never a position and does not appear.

    `net_pnl` is `None` for every open leg — an open leg has a mark, not a result.
    `unrealized_pnl` is always `None` here; Task 4.4's `build_campaigns` fills it from
    the snapshot it is given, and only for open legs.
    """
    stmt = select(FillRow).order_by(FillRow.filled_at.desc(), FillRow.id.desc())
    if symbol is not None:
        stmt = stmt.where(
            FillRow.candidate_id.in_(
                select(CandidateRow.candidate_id).where(CandidateRow.underlying == symbol)
            )
        )
    with session() as sess:
        fills_by_candidate: dict[str, list[FillRow]] = {}
        for f in sess.execute(stmt).scalars():
            fills_by_candidate.setdefault(f.candidate_id, []).append(f)

        candidate_rows: dict[str, CandidateRow] = {
            c.candidate_id: c for c in sess.execute(select(CandidateRow)).scalars()
        }
        campaigns: list[CampaignRow] = list(sess.execute(select(CampaignRow)).scalars())
        orders_by_candidate: dict[str, list[OrderRow]] = {}
        for o in sess.execute(select(OrderRow)).scalars():
            orders_by_candidate.setdefault(o.candidate_id, []).append(o)
        approvals_by_candidate: dict[str, list[ApprovalRow]] = {}
        for a in sess.execute(select(ApprovalRow)).scalars():
            approvals_by_candidate.setdefault(a.candidate_id, []).append(a)

    # candidate_id -> campaign (a candidate belongs to at most one campaign's leg list)
    campaign_by_candidate: dict[str, CampaignRow] = {}
    for row in campaigns:
        for cid in row.leg_candidate_ids or []:
            campaign_by_candidate[cid] = row

    today = date.today()
    legs: list[PnlLeg] = []
    for cid, fills in fills_by_candidate.items():
        cand = candidate_rows.get(cid)
        campaign = campaign_by_candidate.get(cid)

        # Paper/live filter — a candidate's fills all share one book.
        leg_is_live = bool(fills[0].is_live)
        if not include_paper and not leg_is_live:
            continue
        if not include_live and leg_is_live:
            continue

        opened_at = min(f.filled_at for f in fills)
        if since is not None and opened_at.date() < since:
            continue

        approval = (
            ApprovalRow(status=approvals_by_candidate[cid][-1].status)
            if cid in approvals_by_candidate
            else None
        )
        order = (
            OrderRow(state=orders_by_candidate[cid][-1].state)
            if cid in orders_by_candidate
            else None
        )
        expiry = (
            cand.expiry
            if cand is not None
            else (campaign.opened_date if campaign is not None else today)
        )
        assigned = bool(campaign.assigned) if campaign is not None else False

        out = classify_outcome(cid, fills, approval, order, expiry, today, assigned)
        econ = fill_economics(fills)

        closed_at = (
            max(f.filled_at for f in fills if _is_buy(f))
            if any(_is_buy(f) for f in fills)
            else None
        )
        if out.outcome in (VerdictOutcome.EXPIRED_WORTHLESS, VerdictOutcome.ASSIGNED):
            closed_at = datetime.combine(expiry, datetime.min.time())

        days_held = (
            (closed_at.date() - opened_at.date()).days
            if closed_at is not None
            else (today - opened_at.date()).days
        )

        # Collateral: strike x contracts x 100 for a CSP or a CC's assigned-away
        # obligation. Unknown strike -> no collateral -> None, not 0.0.
        strike = cand.strike if cand is not None else None
        collateral = (
            strike * out.contracts * 100.0
            if strike is not None and strike > 0 and out.contracts
            else None
        )
        roc_pct = None
        annualized_pct = None
        if collateral:
            roc_pct = econ.credit / collateral * 100.0
            if out.realized_pnl is not None:
                annualized_pct = _annualize(out.realized_pnl, collateral, days_held)

        legs.append(
            PnlLeg(
                candidate_id=cid,
                campaign_id=campaign.campaign_id if campaign is not None else None,
                symbol=_option_symbol(cand, campaign, fills),
                underlying=(
                    cand.underlying
                    if cand is not None
                    else (campaign.symbol if campaign is not None else "")
                ),
                strategy=(
                    Strategy(cand.strategy) if cand is not None else Strategy.CASH_SECURED_PUT
                ),
                right=(OptionRight(cand.right) if cand is not None else OptionRight.PUT),
                strike=strike if strike is not None else 0.0,
                expiry=expiry,
                contracts=out.contracts or 0,
                opened_at=opened_at,
                closed_at=closed_at,
                credit=econ.credit,
                debit=econ.debit,
                commissions=econ.commissions,
                commissions_complete=econ.commissions_complete,
                net_pnl=out.realized_pnl,
                unrealized_pnl=None,
                days_held=max(days_held, 0),
                roc_pct=roc_pct,
                annualized_pct=annualized_pct,
                outcome=out.outcome,
                is_live=leg_is_live,
            )
        )

    legs.sort(key=lambda leg: leg.opened_at, reverse=True)
    return legs


def _is_buy(f: FillRow) -> bool:
    return (f.action or "SELL").upper() == "BUY"


def _option_symbol(
    cand: CandidateRow | None, campaign: CampaignRow | None, fills: list[FillRow]
) -> str:
    """Best-effort OCC-style symbol; a pruned candidate yields a stable placeholder."""
    if cand is not None:
        expiry_str = cand.expiry.strftime("%y%m%d")
        return f"{cand.underlying} {expiry_str}{cand.right}{int(cand.strike * 1000):08d}"
    sym = campaign.symbol if campaign is not None else "UNKNOWN"
    return f"{sym} PRUNED"


def _mark_for_leg(leg: PnlLeg, snapshot: PortfolioSnapshot | None) -> float | None:
    """The open leg's mark from the snapshot — None when it knows no such position.

    Matches on (underlying, right, strike, expiry) — the identifying quadruple of the
    contract, independent of how either side formats its symbol string.
    """
    if snapshot is None:
        return None
    for pos in snapshot.positions:
        if pos.sec_type != "OPT":
            continue
        if (
            pos.underlying == leg.underlying
            and pos.right is not None
            and pos.right.value == leg.right.value
            and pos.strike == leg.strike
            and pos.expiry == leg.expiry
        ):
            return pos.unrealized_pnl
    return None


def _stock_mark(symbol: str, snapshot: PortfolioSnapshot | None) -> float | None:
    if snapshot is None:
        return None
    for pos in snapshot.positions:
        if pos.sec_type == "STK" and pos.symbol == symbol:
            return pos.unrealized_pnl
    return None


def _marked_copy(leg: PnlLeg, snapshot: PortfolioSnapshot | None) -> PnlLeg:
    """A copy carrying the snapshot's mark — only ever applied to an open leg."""
    if leg.net_pnl is not None:
        return leg  # a closed leg has a result, not a mark
    return leg.model_copy(update={"unrealized_pnl": _mark_for_leg(leg, snapshot)})


def _threads_total(
    option_realized: float,
    option_unrealized: float | None,
    stock_realized: float | None,
    stock_unrealized: float | None,
) -> float:
    total = option_realized
    if option_unrealized is not None:
        total += option_unrealized
    if stock_realized is not None:
        total += stock_realized
    if stock_unrealized is not None:
        total += stock_unrealized
    return total


def build_campaigns(
    session: _SessionFactory,
    legs: list[PnlLeg],
    *,
    snapshot: PortfolioSnapshot | None = None,
) -> list[CampaignPnl]:
    """Group legs into campaign threads and attach the stock leg.

    `snapshot` supplies the marks for open legs and open stock. When it is None, every
    unrealised field is None — never zero, and never a stale mark from somewhere else.
    The stock leg is read from the campaign row, never recomputed. A leg with no campaign
    is not dropped: it lands in a synthetic per-symbol thread.
    """
    with session() as sess:
        rows = list(sess.execute(select(CampaignRow)).scalars())
    by_id = {row.campaign_id: row for row in rows}

    # Legs grouped by their campaign; campaign-less legs get a synthetic per-symbol thread.
    grouped: dict[str, list[PnlLeg]] = {}
    synthetic: dict[str, list[PnlLeg]] = {}
    for leg in legs:
        if leg.campaign_id is not None and leg.campaign_id in by_id:
            grouped.setdefault(leg.campaign_id, []).append(leg)
        else:
            # A leg whose campaign is None, or names a campaign that no longer exists.
            synthetic.setdefault(leg.underlying, []).append(leg)

    campaigns: list[CampaignPnl] = []

    for campaign_id, c_legs in grouped.items():
        row = by_id[campaign_id]
        c_legs = sorted(c_legs, key=lambda leg: leg.opened_at)  # leg order, earliest first
        option_realized = sum(leg.net_pnl for leg in c_legs if leg.net_pnl is not None)
        open_marks = [_mark_for_leg(leg, snapshot) for leg in c_legs if leg.net_pnl is None]
        option_unrealized = (
            float(sum(m for m in open_marks if m is not None))
            if open_marks and all(m is not None for m in open_marks)
            else None
        )
        stock_unrealized = _stock_mark(row.symbol, snapshot)

        campaigns.append(
            CampaignPnl(
                campaign_id=campaign_id,
                symbol=row.symbol,
                status="open" if row.status == "open" else "closed",
                opened_date=row.opened_date,
                closed_date=row.closed_date,
                legs=[_marked_copy(leg, snapshot) for leg in c_legs],
                option_realized=option_realized,
                option_unrealized=option_unrealized,
                stock_realized=row.realized_stock_pnl,
                stock_unrealized=stock_unrealized,
                assigned=bool(row.assigned),
                adjusted_cost_basis=row.adjusted_cost_basis,
                total_net=_threads_total(
                    option_realized,
                    option_unrealized,
                    row.realized_stock_pnl,
                    stock_unrealized,
                ),
            )
        )

    # Synthetic threads: campaign-less legs grouped by symbol, in a stable derived order.
    for symbol in sorted(synthetic):
        s_legs = sorted(synthetic[symbol], key=lambda leg: leg.opened_at)
        option_realized = sum(leg.net_pnl for leg in s_legs if leg.net_pnl is not None)
        all_closed = all(leg.net_pnl is not None for leg in s_legs)
        open_marks = [_mark_for_leg(leg, snapshot) for leg in s_legs if leg.net_pnl is None]
        option_unrealized = (
            float(sum(m for m in open_marks if m is not None))
            if open_marks and all(m is not None for m in open_marks)
            else None
        )
        stock_unrealized = _stock_mark(symbol, snapshot)
        campaigns.append(
            CampaignPnl(
                campaign_id=f"synthetic:{symbol}",
                symbol=symbol,
                status="closed" if all_closed else "open",
                opened_date=min(leg.opened_at.date() for leg in s_legs),
                legs=[_marked_copy(leg, snapshot) for leg in s_legs],
                option_realized=option_realized,
                option_unrealized=option_unrealized,
                stock_realized=None,
                stock_unrealized=stock_unrealized,
                assigned=False,
                adjusted_cost_basis=None,
                total_net=_threads_total(
                    option_realized, option_unrealized, None, stock_unrealized
                ),
            )
        )

    return campaigns


def _bucket(legs: list[PnlLeg], key: Callable[[PnlLeg], str]) -> list[PnlBucket]:
    """Realised buckets ordered by realised descending, ties broken by label."""
    groups: dict[str, list[PnlLeg]] = {}
    for leg in legs:
        if leg.net_pnl is None:
            continue  # an open leg has no result to bucket
        groups.setdefault(key(leg), []).append(leg)
    buckets = []
    for label, closed in groups.items():
        n = len(closed)
        pnls = [leg.net_pnl for leg in closed]
        assert all(v is not None for v in pnls)  # only closed legs were grouped
        wins = sum(1 for v in pnls if v is not None and v > 0)
        rocs = [leg.roc_pct for leg in closed if leg.roc_pct is not None]
        buckets.append(
            PnlBucket(
                label=label,
                n_closed=n,
                realized=sum(v for v in pnls if v is not None),
                win_rate=(wins / n) if n else None,
                mean_days_held=sum(leg.days_held for leg in closed) / n,
                mean_roc_pct=(sum(rocs) / len(rocs)) if rocs else None,
            )
        )
    buckets.sort(key=lambda b: (-b.realized, b.label))
    return buckets


def build_summary(
    legs: list[PnlLeg],
    campaigns: list[CampaignPnl],
) -> PnlSummary:
    """Aggregate. Pure — no session, no database, no config.

    Raises ValueError when `legs` mixes paper and live. A total across both is not a
    number that means anything, and returning one silently is the failure this guards.
    """
    is_live_values = {leg.is_live for leg in legs}
    if len(is_live_values) > 1:
        raise ValueError(
            "build_summary refuses to total a leg list mixing paper and live fills; "
            "filter with build_legs(include_paper=…, include_live=…)"
        )

    closed = [leg for leg in legs if leg.net_pnl is not None]
    open_legs = [leg for leg in legs if leg.net_pnl is None]
    realized_total = sum(leg.net_pnl for leg in closed if leg.net_pnl is not None)

    marked = [leg.unrealized_pnl for leg in open_legs if leg.unrealized_pnl is not None]
    unmarked_open = [leg for leg in open_legs if leg.unrealized_pnl is None]
    unrealized_total: float | None = float(sum(marked)) if marked and not unmarked_open else None

    n_closed = len(closed)
    win_rate = (
        sum(1 for leg in closed if leg.net_pnl is not None and leg.net_pnl > 0) / n_closed
        if n_closed
        else None
    )

    best = max(closed, key=lambda leg: leg.net_pnl or 0.0) if closed else None
    worst = min(closed, key=lambda leg: leg.net_pnl or 0.0) if closed else None

    return PnlSummary(
        realized_total=realized_total,
        unrealized_total=unrealized_total,
        commissions_complete=all(leg.commissions_complete for leg in legs),
        n_open=len(open_legs),
        n_closed=n_closed,
        win_rate=win_rate,
        by_strategy=_bucket(legs, lambda leg: leg.strategy.value),
        by_symbol=_bucket(legs, lambda leg: leg.underlying),
        best=best,
        worst=worst,
    )
