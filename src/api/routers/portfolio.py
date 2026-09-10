"""The portfolio read surfaces (P3-P4 M2) — what do I hold, what is it worth,
what is at risk, what happens next.

Every snapshot-derived route renders what `read_portfolio` (the M1 fallback chain)
found and adds nothing to it: no second data path, no re-derivation of account
values, no reaching past `PortfolioReading` to a table of its own. The routes are
owner-only and read through the read-only trading engine.

Shared conventions set by Task 2.1, followed by every route here:

- `as_of` is the reading's capture time (`reading.as_of`), never `datetime.now()`.
  On the empty rung, where the reading carries no capture time, request time is
  used and `degraded=True` — the envelope still needs a valid stamp, but nothing
  in it claims to be a measurement. Any timestamp read straight from SQLite goes
  through `as_utc_opt` (M0 Task 0.9); this router defines no `_as_utc` of its own.
- `Sourced` values use `Source.IBKR` — that is where the numbers came from, even
  though a database served them. `fresh_for` is twice the configured snapshot
  interval, so a portfolio that has missed one capture reads stale.
- Assignment risk comes from `src/common/assignment_risk.py` (M0 Task 0.3) with
  thresholds read from config. This router defines no threshold of its own.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Query
from sqlalchemy import select

from src.api.deps import OwnerUser, TradingDb
from src.api.models.common import Source, Sourced
from src.api.models.portfolio import (
    AccountBlock,
    CalendarDay,
    CalendarEntry,
    CalendarResponse,
    CampaignLeg,
    CampaignsResponse,
    CampaignSummary,
    ExposureBlock,
    OptionLeg,
    PortfolioSummaryResponse,
    PositionGroup,
    PositionsResponse,
    StockLeg,
)
from src.api.portfolio_source import read_portfolio
from src.common.assignment_risk import assignment_risk_thresholds, is_assignment_risk
from src.common.config import get_config
from src.common.schemas import OptionRight, PositionSnapshot
from src.storage.models import CampaignRow, CandidateRow

router = APIRouter()

_NONE_NOTE = "No portfolio snapshot has been captured yet."
_EOD_NOTE = "No intraday snapshot found — serving the last end-of-day positions and account."
_UNDERLYING_ATM_BAND = 0.01  # |spot - strike| / spot within 1% reads "atm", not a guess


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _fresh_for() -> timedelta:
    """Twice the configured snapshot interval — one missed capture reads stale."""
    return timedelta(minutes=2 * get_config().market_data.portfolio_snapshot_interval_minutes)


def _thresholds() -> tuple[float, int]:
    """The monitor's configured assignment-risk thresholds. No route hardcodes either."""
    return assignment_risk_thresholds(get_config())


def _dte(expiry: date) -> int:
    """Days to expiry in ET — the same rule as routers/options.py, never 0 for unknown."""
    from zoneinfo import ZoneInfo

    et = ZoneInfo("America/New_York")
    return (expiry - datetime.now(et).date()).days


def _consequence(  # noqa: PLR0911
    *,
    right: str,
    short: bool,
    moneyness: Literal["itm", "atm", "otm"] | None,
    stock_held: bool,
) -> Literal["assigned", "called_away", "expires_worthless", "unknown"]:
    """The Task 2.4 consequence table, implemented exactly as specified.

    `unknown` is a real value and must render — "we do not know what happens on
    Friday" is materially different from "nothing happens on Friday".
    """
    if moneyness is None:
        return "unknown"
    if not short:
        return "expires_worthless" if moneyness == "otm" else "unknown"
    if moneyness in ("otm", "atm"):
        return "expires_worthless"
    # short and itm
    if right.upper().startswith("P"):
        return "assigned"
    # A short call: called away only when the stock is held to deliver.
    return "called_away" if stock_held else "assigned"


def _underlying_price(
    db: TradingDb, underlying: str, groups_stock_price: float | None
) -> float | None:
    """The underlying's price for moneyness, from the reading itself when it has one.

    Precedence: a stock leg in the same reading (the operator's own holding, same
    capture) — else the latest settled close in `price_history`, read through the
    same read-only engine the route already holds (the table `routers/research.py::
    _hv30_for` already reads). Never a second live-data path.
    """
    if groups_stock_price is not None:
        return groups_stock_price
    try:
        from src.storage.models import PriceHistoryRow

        row = (
            db.execute(
                select(PriceHistoryRow.close)
                .where(PriceHistoryRow.symbol == underlying)
                .order_by(PriceHistoryRow.obs_date.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        return float(row) if row is not None else None
    except Exception:
        return None


def _moneyness(
    spot: float | None, right: str, strike: float
) -> Literal["itm", "atm", "otm"] | None:
    """None when the underlying price is unknown — no guessing from the strike alone."""
    if spot is None or spot <= 0:
        return None
    if abs(spot - strike) / spot <= _UNDERLYING_ATM_BAND:
        return "atm"
    is_call = right.upper().startswith("C")
    if is_call:
        return "itm" if spot > strike else "otm"
    return "itm" if spot < strike else "otm"


# ---------------------------------------------------------------------------
# Task 2.1 — GET /portfolio/summary
# ---------------------------------------------------------------------------


@router.get("/summary", response_model=PortfolioSummaryResponse)
def portfolio_summary(user: OwnerUser, db: TradingDb) -> PortfolioSummaryResponse:  # noqa: ARG001
    """Account values as `Sourced` + the exposure the operator needs before deciding.

    The `none` rung is a 200, not a 404: there is no error, there is simply nothing
    captured yet, and the client needs a well-formed response saying so in words.
    """
    reading = read_portfolio(db)

    if reading.snapshot is None:
        return PortfolioSummaryResponse(
            as_of=datetime.now(UTC),
            source="none",
            degraded=True,
            account=None,
            exposure=None,
            note=_NONE_NOTE,
        )

    as_of = reading.as_of or datetime.now(UTC)
    fresh_for = _fresh_for()
    snapshot = reading.snapshot
    account = snapshot.account

    account_block: AccountBlock | None = None
    if account is not None:
        account_block = AccountBlock(
            as_of=as_of,
            net_liquidation=Sourced[float].of(
                account.net_liquidation, Source.IBKR, as_of, fresh_for=fresh_for
            ),
            total_cash=Sourced[float].of(
                account.total_cash, Source.IBKR, as_of, fresh_for=fresh_for
            ),
            buying_power=Sourced[float].of(
                account.buying_power, Source.IBKR, as_of, fresh_for=fresh_for
            ),
            maintenance_margin=Sourced[float].of(
                account.maintenance_margin, Source.IBKR, as_of, fresh_for=fresh_for
            ),
            excess_liquidity=Sourced[float].of(
                account.excess_liquidity, Source.IBKR, as_of, fresh_for=fresh_for
            ),
        )

    positions = snapshot.positions
    open_shorts = sum(1 for p in positions if p.sec_type == "OPT" and p.position < 0)
    delta_threshold, dte_threshold = _thresholds()
    shorts_at_risk = sum(
        1
        for p in positions
        if p.sec_type == "OPT"
        and is_assignment_risk(
            position=p.position,
            delta=p.delta,
            dte=_dte(p.expiry) if p.expiry else None,
            delta_threshold=delta_threshold,
            dte_threshold=dte_threshold,
        )
    )
    cash_secured = sum(
        float(p.strike or 0.0) * abs(p.position) * 100
        for p in positions
        if p.sec_type == "OPT" and p.position < 0 and (p.right or "P") == "P"
    )
    # Net delta: options contribute delta * position * 100, stock its share count —
    # the same Σ the EOD summary already computes (eod_report.py).
    net_delta = sum((p.delta or 0.0) * p.position * 100 for p in positions if p.sec_type == "OPT")
    net_delta += sum(p.position for p in positions if p.sec_type == "STK")

    utilisation: float | None = None
    if account is not None and account.buying_power > 0:
        utilisation = round(cash_secured / account.buying_power * 100, 2)

    exposure_block = ExposureBlock(
        as_of=as_of,
        open_positions=len(positions),
        open_shorts=open_shorts,
        open_campaigns=_open_campaign_count(db),
        net_delta_exposure=round(net_delta, 2),
        cash_secured_against_puts=round(cash_secured, 2),
        buying_power_utilisation_pct=utilisation,
        shorts_at_assignment_risk=shorts_at_risk,
    )

    note: str | None = None
    if reading.source == "eod":
        note = _EOD_NOTE

    return PortfolioSummaryResponse(
        as_of=as_of,
        source=reading.source,
        degraded=reading.degraded,
        account=account_block,
        exposure=exposure_block,
        note=note,
    )


def _open_campaign_count(db: TradingDb) -> int:
    """Open campaigns for the exposure block. A read that cannot fail the route."""
    try:
        return len(
            db.execute(select(CampaignRow.id).where(CampaignRow.status == "open")).scalars().all()
        )
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# Task 2.3 — GET /portfolio/campaigns
# ---------------------------------------------------------------------------


@router.get("/campaigns", response_model=CampaignsResponse)
def portfolio_campaigns(
    user: OwnerUser,  # noqa: ARG001
    db: TradingDb,
    status: Literal["open", "closed"] | None = None,
    symbol: str | None = None,
) -> CampaignsResponse:
    """The wheel threads — one thread per symbol, legs in order.

    `as_of` is request time here, NOT a snapshot time: campaigns are written on
    fill, not captured, so there is no capture time to read. Do not "fix" this to
    match the other portfolio routes. Financials are gross of commissions (M0
    Task 0.4's pinned semantics — see `src/storage/campaigns.py::_rollup`'s and
    `CampaignRow`'s docstrings); `src/reporting/` nets commissions on the same
    trades, so a campaign's `net_premium` and the net P&L of its legs differ by
    exactly the commission total. A leg whose `CandidateRow` was pruned still
    renders with `known: false` — the financials are rolled up from `FillRow` and
    survive pruning, so the leg count must not silently disagree with them.
    """
    now = datetime.now(UTC)
    try:
        # opened_date descending; open campaigns before closed at the same date.
        # status is "open"/"closed" and sorts alphabetically against us, so the
        # explicit key below — not the SQL order — is the ordering contract.
        # reverse=True means larger keys come first: a newer date wins, and at a
        # tie `status == "open"` (1) beats `"closed"` (0).
        stmt = select(CampaignRow).order_by(CampaignRow.opened_date.desc(), CampaignRow.id.desc())
        if status is not None:
            stmt = stmt.where(CampaignRow.status == status)
        if symbol is not None:
            stmt = stmt.where(CampaignRow.symbol == symbol.upper())
        rows = list(db.execute(stmt).scalars().all())
        rows.sort(key=lambda r: (r.opened_date, r.status == "open", -r.id), reverse=True)
    except Exception:
        return CampaignsResponse(as_of=now, campaigns=[])

    # One batched lookup for every leg's CandidateRow, then join by id.
    all_ids = [cid for r in rows for cid in (r.leg_candidate_ids or [])]
    candidates: dict[str, CandidateRow] = {}
    if all_ids:
        try:
            for found in db.execute(
                select(CandidateRow).where(CandidateRow.candidate_id.in_(all_ids))
            ).scalars():
                candidates[found.candidate_id] = found
        except Exception:
            candidates = {}

    out: list[CampaignSummary] = []
    for r in rows:
        legs: list[CampaignLeg] = []
        for cid in r.leg_candidate_ids or []:
            crow: CandidateRow | None = candidates.get(cid)
            legs.append(
                CampaignLeg(
                    as_of=now,
                    candidate_id=cid,
                    strategy=crow.strategy if crow is not None else "unknown",
                    right=(crow.right if crow is not None else None),  # type: ignore[arg-type]
                    strike=float(crow.strike) if crow is not None else None,
                    expiry=crow.expiry if crow is not None else None,
                    known=crow is not None,
                )
            )
        out.append(
            CampaignSummary(
                as_of=now,
                campaign_id=r.campaign_id,
                symbol=r.symbol,
                status=r.status,  # type: ignore[arg-type]
                opened_date=r.opened_date,
                closed_date=r.closed_date,
                legs=legs,
                total_premium_collected=float(r.total_premium_collected or 0.0),
                total_debit_paid=float(r.total_debit_paid or 0.0),
                net_premium=float(r.net_premium or 0.0),
                assigned=bool(r.assigned),
                adjusted_cost_basis=(
                    float(r.adjusted_cost_basis) if r.adjusted_cost_basis is not None else None
                ),
                realized_stock_pnl=(
                    float(r.realized_stock_pnl) if r.realized_stock_pnl is not None else None
                ),
            )
        )

    return CampaignsResponse(as_of=now, campaigns=out)


# ---------------------------------------------------------------------------
# Task 2.4 — GET /portfolio/calendar
# ---------------------------------------------------------------------------


@router.get("/calendar", response_model=CalendarResponse)
def portfolio_calendar(
    user: OwnerUser,  # noqa: ARG001
    db: TradingDb,
    horizon_days: int = Query(default=45, ge=1, le=365),
) -> CalendarResponse:
    """Option expiries grouped by date over a horizon, with what expiry would mean.

    The `consequence` mapping, exactly as specified: an ITM short put is
    `assigned`; an ITM short call is `called_away` only when the stock is held to
    deliver — a naked short call assignment is a short stock position, not a
    call-away; any short OTM/ATM is `expires_worthless`; a long option is
    `expires_worthless` only when OTM; unknown moneyness is `unknown`, never a
    default to `expires_worthless`.
    """
    reading = read_portfolio(db)

    if reading.snapshot is None:
        return CalendarResponse(
            as_of=datetime.now(UTC),
            source="none",
            degraded=True,
            horizon_days=horizon_days,
            days=[],
        )

    as_of = reading.as_of or datetime.now(UTC)
    snapshot = reading.snapshot
    today = datetime.now(UTC).date()
    cutoff = today + timedelta(days=horizon_days)
    delta_threshold, dte_threshold = _thresholds()

    grouped = _group_positions(snapshot.positions)

    by_expiry: dict[date, list[CalendarEntry]] = {}
    for g in grouped:
        spot = _underlying_price(
            db, g.underlying, g.stock.market_price if g.stock is not None else None
        )
        stock_held = g.stock is not None and g.stock.position > 0
        for p in g.options:
            if p.expiry is None or p.strike is None or p.right is None:
                continue  # cannot be placed on a calendar without a date
            if p.expiry > cutoff:
                continue
            dte = _dte(p.expiry)
            if dte < 0:
                continue  # already expired; not "what happens next"
            right = p.right.value if isinstance(p.right, OptionRight) else str(p.right)
            moneyness = _moneyness(spot, right, float(p.strike))
            by_expiry.setdefault(p.expiry, []).append(
                CalendarEntry(
                    as_of=as_of,
                    symbol=p.symbol,
                    underlying=g.underlying,
                    right=right,  # type: ignore[arg-type]
                    strike=float(p.strike),
                    contracts=int(abs(p.position)),
                    short=p.position < 0,
                    moneyness=moneyness,
                    consequence=_consequence(
                        right=right,
                        short=p.position < 0,
                        moneyness=moneyness,
                        stock_held=stock_held,
                    ),
                    assignment_risk=is_assignment_risk(
                        position=p.position,
                        delta=p.delta,
                        dte=dte,
                        delta_threshold=delta_threshold,
                        dte_threshold=dte_threshold,
                    ),
                )
            )

    days = [
        CalendarDay(as_of=as_of, expiry=exp, dte=_dte(exp), entries=entries)
        for exp, entries in sorted(by_expiry.items())
    ]
    return CalendarResponse(
        as_of=as_of,
        source=reading.source,
        degraded=reading.degraded,
        horizon_days=horizon_days,
        days=days,
    )


# ---------------------------------------------------------------------------
# Task 2.2 — GET /portfolio/positions
# ---------------------------------------------------------------------------


@dataclass
class _Group:
    """One underlying's positions: its stock leg (at most one) beside its options."""

    underlying: str
    stock: PositionSnapshot | None = None
    options: list[PositionSnapshot] = field(default_factory=list)


def _group_positions(positions: list[PositionSnapshot]) -> list[_Group]:
    """Group by underlying: `underlying` for options, `symbol` for stock.

    An option whose `underlying` is None groups under its own symbol rather than
    being dropped — a dropped position is a lie about the account.
    """
    groups: dict[str, _Group] = {}
    order: list[str] = []
    for p in positions:
        key = (p.underlying or p.symbol) if p.sec_type == "OPT" else p.symbol
        if key not in groups:
            groups[key] = _Group(underlying=key)
            order.append(key)
        if p.sec_type == "STK":
            groups[key].stock = p
        else:
            groups[key].options.append(p)
    return [groups[k] for k in order]


@router.get("/positions", response_model=PositionsResponse)
def portfolio_positions(user: OwnerUser, db: TradingDb) -> PositionsResponse:  # noqa: ARG001
    """Every position, grouped by underlying — the unit the operator thinks in.

    Both cost bases are reported, never one substituted for the other: `avg_cost`
    is what IBKR says, `adjusted_cost_basis` is what the collected premium makes
    it. The empty rung returns `groups: []` with `source="none"` — an empty list
    plus `source="monitor"` would be a claim that the account holds nothing.
    """
    reading = read_portfolio(db)

    if reading.snapshot is None:
        return PositionsResponse(
            as_of=datetime.now(UTC),
            source="none",
            degraded=True,
            groups=[],
        )

    as_of = reading.as_of or datetime.now(UTC)
    snapshot = reading.snapshot
    grouped = _group_positions(snapshot.positions)
    delta_threshold, dte_threshold = _thresholds()

    out: list[PositionGroup] = []
    for g in grouped:
        stock_leg = _stock_leg(db, g.underlying, g.stock, as_of)
        option_legs = _option_legs(
            g.options,
            stock_pos=g.stock,
            db=db,
            underlying=g.underlying,
            as_of=as_of,
            delta_threshold=delta_threshold,
            dte_threshold=dte_threshold,
        )
        out.append(
            PositionGroup(
                as_of=as_of, underlying=g.underlying, stock=stock_leg, options=option_legs
            )
        )

    return PositionsResponse(
        as_of=as_of, source=reading.source, degraded=reading.degraded, groups=out
    )


def _stock_leg(
    db: TradingDb, underlying: str, stock_pos: PositionSnapshot | None, as_of: datetime
) -> StockLeg | None:
    from src.storage.campaigns import adjusted_cost_basis_for

    if stock_pos is None:
        return None
    try:
        adjusted = adjusted_cost_basis_for(underlying)
    except Exception:
        adjusted = None
    if adjusted is None:
        # adjusted_cost_basis_for reads through its own session_scope; fall back to the
        # reading the route already holds when that path is unavailable.
        adjusted = _campaign_basis_from_reading(db, underlying)
    return StockLeg(
        as_of=as_of,
        shares=stock_pos.position,
        avg_cost=stock_pos.avg_cost,
        adjusted_cost_basis=adjusted,
        market_price=stock_pos.market_price,
        market_value=stock_pos.market_value,
        unrealized_pnl=stock_pos.unrealized_pnl,
        unrealized_pnl_adjusted=(
            (stock_pos.market_price - adjusted) * stock_pos.position
            if adjusted is not None and stock_pos.market_price is not None
            else None
        ),
    )


def _campaign_basis_from_reading(db: TradingDb, underlying: str) -> float | None:
    """Adjusted basis read through the route's own read-only session."""
    try:
        val = db.execute(
            select(CampaignRow.adjusted_cost_basis).where(
                CampaignRow.symbol == underlying,
                CampaignRow.status == "open",
                CampaignRow.assigned.is_(True),
            )
        ).scalar_one_or_none()
        return float(val) if val is not None and float(val) > 0 else None
    except Exception:
        return None


def _option_legs(
    options: list[PositionSnapshot],
    *,
    stock_pos: PositionSnapshot | None,
    db: TradingDb,
    underlying: str,
    as_of: datetime,
    delta_threshold: float,
    dte_threshold: int,
) -> list[OptionLeg]:
    spot = _underlying_price(
        db, underlying, stock_pos.market_price if stock_pos is not None else None
    )
    legs: list[OptionLeg] = []
    for p in options:
        dte = _dte(p.expiry) if p.expiry else None
        moneyness = _moneyness(spot, p.right.value if p.right else "C", float(p.strike or 0.0))
        legs.append(
            OptionLeg(
                as_of=as_of,
                symbol=p.symbol,
                right=(p.right.value if p.right else "C") or "C",
                strike=float(p.strike or 0.0),
                expiry=p.expiry,
                dte=dte,
                contracts=int(abs(p.position)),
                short=p.position < 0,
                delta=p.delta,
                delta_source=Source.IBKR.value if p.delta is not None else None,
                market_price=p.market_price,
                market_value=p.market_value,
                unrealized_pnl=p.unrealized_pnl,
                moneyness=moneyness,
                assignment_risk=is_assignment_risk(
                    position=p.position,
                    delta=p.delta,
                    dte=dte,
                    delta_threshold=delta_threshold,
                    dte_threshold=dte_threshold,
                ),
            )
        )
    return legs
