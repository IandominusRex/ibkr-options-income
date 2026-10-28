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

import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from src.api.deps import OwnerUser, TradingDb
from src.api.models.common import Source, Sourced
from src.api.models.portfolio import (
    AccountBlock,
    AccountValueResponse,
    CalendarDay,
    CalendarEntry,
    CalendarResponse,
    CampaignLeg,
    CampaignsResponse,
    CampaignSummary,
    ExposureBlock,
    OptionLeg,
    PortfolioSummaryResponse,
    PositionDetailResponse,
    PositionGroup,
    PositionsResponse,
    StockLeg,
)
from src.api.portfolio_source import read_portfolio
from src.api.spread_inputs import spread_day_inputs, spread_position_out, spread_rows
from src.common.assignment_risk import assignment_risk_thresholds, is_assignment_risk
from src.common.config import get_config
from src.common.schemas import AccountValueRange, OptionRight, PositionSnapshot
from src.reporting.account_value import account_value_series
from src.reporting.day import build_position_story, build_spread_story
from src.reporting.pnl import build_legs
from src.storage.campaigns import prior_legs_premium, whole_position_basis
from src.storage.models import CampaignRow, CandidateRow

router = APIRouter()

_NONE_NOTE = "No portfolio snapshot has been captured yet."
_EOD_NOTE = "No intraday snapshot found - serving the last end-of-day positions and account."
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
    return (expiry - _today_et()).days


def _today_et() -> date:
    """The exchange-calendar today (ET), the one clock this router measures days in.

    `_dte` has always used ET; the calendar's horizon cutoff must use the same
    clock — a UTC cutoff disagrees with the ET dte by one day for any expiry whose
    date the two clocks straddle, silently dropping or keeping a day inconsistently.
    """
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("America/New_York")).date()


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


def _last_close(db: TradingDb, underlying: str) -> tuple[float, date] | None:
    """The latest settled close in `price_history` and its date, or None when there is none.

    The table `routers/research.py::_hv30_for` already reads, through the route's own
    read-only engine. Never a second live-data path.
    """
    try:
        from src.storage.models import PriceHistoryRow

        row = db.execute(
            select(PriceHistoryRow.close, PriceHistoryRow.obs_date)
            .where(PriceHistoryRow.symbol == underlying)
            .order_by(PriceHistoryRow.obs_date.desc())
            .limit(1)
        ).first()
        return (float(row[0]), row[1]) if row is not None else None
    except Exception:
        return None


def _underlying_price(
    db: TradingDb, underlying: str, groups_stock_price: float | None
) -> float | None:
    """The underlying's price for moneyness, from the reading itself when it has one.

    Precedence: a stock leg in the same reading (the operator's own holding, same
    capture) - else the latest settled close (`_last_close`).
    """
    if groups_stock_price is not None:
        return groups_stock_price
    close = _last_close(db, underlying)
    return close[0] if close is not None else None


def _moneyness(
    spot: float | None, right: str | None, strike: float | None
) -> Literal["itm", "atm", "otm"] | None:
    """None when the underlying price is unknown — no guessing from the strike alone.

    Also None when right or strike is unknown: moneyness needs all three, and a
    fabricated value would read as a real measurement.
    """
    if spot is None or spot <= 0 or right is None or strike is None:
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
    # `p.right == "P"` (not `(p.right or "P") == "P"`) — a short option with an
    # unknown right (malformed snapshot data) must not be silently assumed to be
    # a put and folded into this exposure figure; excluded is the honest answer,
    # matching this file's "never guess from missing data" discipline elsewhere
    # (_moneyness, the OptionLeg/right/strike fields).
    cash_secured = sum(
        float(p.strike or 0.0) * abs(p.position) * 100
        for p in positions
        if p.sec_type == "OPT" and p.position < 0 and p.right == "P"
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
    limit: int = Query(default=50, ge=1, le=200),
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

    `limit` (default 50, max 200) caps the read because campaigns are never
    pruned — the table grows forever, and a response that materialises every row
    ever written is an unbounded JSON payload, not a "latest threads" list.
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
        rows = list(db.execute(stmt.limit(limit)).scalars().all())
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
    today = _today_et()  # the same clock _dte measures in — one route, one calendar
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
            moneyness = _moneyness(spot, right, p.strike if p.strike is not None else None)
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
        price, basis, price_date = _group_price(db, g.underlying, stock_leg)
        out.append(
            PositionGroup(
                as_of=as_of,
                underlying=g.underlying,
                stock=stock_leg,
                options=option_legs,
                underlying_price=price,
                underlying_price_basis=basis,
                underlying_price_date=price_date,
            )
        )

    return PositionsResponse(
        as_of=as_of, source=reading.source, degraded=reading.degraded, groups=out
    )


def _group_price(
    db: TradingDb, underlying: str, stock_leg: StockLeg | None
) -> tuple[float | None, Literal["position", "close"] | None, date | None]:
    """The card's price for a name, and where it came from: the share position's own market
    price when held as shares, else the last settled close with its date, else nothing."""
    if stock_leg is not None and stock_leg.market_price is not None:
        return stock_leg.market_price, "position", None
    close = _last_close(db, underlying)
    return (close[0], "close", close[1]) if close is not None else (None, None, None)


def _stock_leg(
    db: TradingDb, underlying: str, stock_pos: PositionSnapshot | None, as_of: datetime
) -> StockLeg | None:
    if stock_pos is None:
        return None
    # The read-only engine the route already holds is the primary path — the design's
    # invariant (§4.2). `storage.campaigns.adjusted_cost_basis_for` opens the storage
    # engine's own read-write session_scope, which an API process must not do; the
    # universe composer is the one documented exception, and this route is not it.
    adjusted = _campaign_basis_from_reading(db, underlying, stock_pos)
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


def _campaign_basis_from_reading(
    db: TradingDb, underlying: str, stock_pos: PositionSnapshot
) -> float | None:
    """Adjusted basis read through the route's own read-only session.

    Mirrors `storage.campaigns.adjusted_cost_basis_for` exactly — every open assigned
    campaign for the symbol, blended over the whole position by the same pure
    `whole_position_basis` — so the page and the covered-call gate cannot disagree.
    """
    try:
        payloads = db.execute(
            select(CampaignRow.payload).where(
                CampaignRow.symbol == underlying,
                CampaignRow.status == "open",
                CampaignRow.assigned.is_(True),
            )
        ).scalars()
        priors = [p for p in (prior_legs_premium(x) for x in payloads) if p is not None]
        return whole_position_basis(priors, stock_pos.position, stock_pos.avg_cost)
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
        # right/strike stay None when the snapshot carried none — the shorts route's
        # null-stays-null discipline. Moneyness needs all three of spot/right/strike;
        # a fabricated pair would guess "otm" against a strike that is not real.
        right = p.right.value if p.right is not None else None
        strike = float(p.strike) if p.strike is not None else None
        # `strike is not None`, not a truthy check — a genuine (if unrealistic)
        # $0.00 strike must not be treated the same as "strike unknown", matching
        # portfolio_calendar's equivalent guard.
        moneyness = _moneyness(spot, right, strike) if (right is not None and strike is not None) else None
        legs.append(
            OptionLeg(
                as_of=as_of,
                symbol=p.symbol,
                right=right,  # type: ignore[arg-type]  # OptionRight values are "C"/"P"
                strike=strike,
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


# ---------------------------------------------------------------------------
# Web Home follow-ups (2026-10-15) - GET /portfolio/positions/{underlying}/{slug}
# ---------------------------------------------------------------------------

_OPTION_SLUG = re.compile(r"^(\d{4}-\d{2}-\d{2})_([CP])(\d+(?:\.\d+)?)$")


@router.get("/positions/{underlying}/{slug}", response_model=PositionDetailResponse)
def portfolio_position(
    underlying: str,
    slug: str,
    user: OwnerUser,
    db: TradingDb,
) -> PositionDetailResponse:
    """One position's page: where it stands now, and the trade that opened it.

    The slug is what a Positions row links with: ``2026-11-21_P180`` (an option contract),
    ``shares``, or ``spread-<id>``. The live figures come from the same snapshot reading
    ``GET /portfolio/positions`` renders (so the two never disagree); the initial trade comes from
    the system's own fills through the builders Home's "Done today" uses. A contract that is no
    longer held but was traded by the system still answers, with ``closed`` saying how it ended.
    404 when neither the snapshot nor the fills know it. Read-only; never reaches IBKR.
    """
    upper = underlying.upper()
    reading = read_portfolio(db)
    as_of = reading.as_of or datetime.now(UTC)
    snapshot = reading.snapshot
    source: Literal["monitor", "refresh", "eod", "none"] = (
        reading.source if snapshot is not None else "none"
    )
    degraded = reading.degraded if snapshot is not None else True
    group = None
    if snapshot is not None:
        group = next(
            (g for g in _group_positions(snapshot.positions) if g.underlying == upper), None
        )
    stock = _stock_leg(db, upper, group.stock, as_of) if group is not None else None
    book = "live" if get_config().is_live else "paper"

    def respond(**extra: Any) -> PositionDetailResponse:
        return PositionDetailResponse(
            as_of=as_of, underlying=upper, slug=slug, source=source, degraded=degraded, **extra
        )

    not_found = HTTPException(status_code=404, detail=f"No such position: {upper} {slug}")

    if slug == "shares":
        if stock is None:
            raise HTTPException(status_code=404, detail=f"No shares of {upper} are held")
        wheel = portfolio_campaigns(user, db, status="open", symbol=upper, limit=5).campaigns
        campaign = next((c for c in wheel if c.assigned), wheel[0] if wheel else None)
        return respond(kind="shares", held=True, stock=stock, campaign=campaign)

    if slug.startswith("spread-"):
        sid = slug[len("spread-") :]
        inputs = spread_day_inputs(book)
        if inputs is None:
            raise HTTPException(status_code=503, detail="The spreads book could not be read.")
        found = next((i for i in inputs if i.spread_id == sid), None)
        row = next((r for r in (spread_rows(book) or []) if str(r["spread_id"]) == sid), None)
        if found is None or row is None:
            raise not_found
        out = spread_position_out(row, as_of)
        spread_opened, spread_closed = build_spread_story(found)
        return respond(
            kind="spread",
            held=out.status != "closed",
            spread=out,
            opened=spread_opened,
            closed=spread_closed,
        )

    m = _OPTION_SLUG.match(slug)
    if m is None:
        raise not_found
    try:
        expiry = date.fromisoformat(m.group(1))
    except ValueError:
        raise not_found from None
    right, strike = m.group(2), float(m.group(3))
    live = None
    if group is not None:
        delta_threshold, dte_threshold = _thresholds()
        legs_now = _option_legs(
            group.options,
            stock_pos=group.stock,
            db=db,
            underlying=upper,
            as_of=as_of,
            delta_threshold=delta_threshold,
            dte_threshold=dte_threshold,
        )
        live = next(
            (o for o in legs_now if o.right == right and o.strike == strike and o.expiry == expiry),
            None,
        )
    legs = build_legs(
        _session_factory(db),
        symbol=upper,
        include_paper=book == "paper",
        include_live=book == "live",
    )
    opened, closed = build_position_story(
        _session_factory(db), legs, underlying=upper, right=right, strike=strike, expiry=expiry
    )
    if live is None and opened is None:
        raise not_found
    return respond(
        kind="option", held=live is not None, option=live, stock=stock, opened=opened, closed=closed
    )


# ---------------------------------------------------------------------------
# Web overhaul Part 1, Task 7 — GET /portfolio/value
# ---------------------------------------------------------------------------


def _session_factory(db: TradingDb):
    """`src/reporting` takes a session factory; yield the request's read-only session."""

    @contextmanager
    def _factory() -> Iterator[TradingDb]:
        yield db

    return _factory


@router.get("/value", response_model=AccountValueResponse)
def portfolio_value(
    user: OwnerUser,  # noqa: ARG001
    db: TradingDb,
    # Annotated, not `= Query(...)`: ruff B008 cannot see through the `AccountValueRange`
    # alias (see ledger.py `sort`); the alias keeps the builtin `range` unshadowed.
    range_: Annotated[AccountValueRange, Query(alias="range")] = "1m",
) -> AccountValueResponse:
    """Account value over `range` for the Home hero. Computes nothing itself: a thin render
    of `account_value_series`. No history is a 200 with no points, never zeros."""
    now = datetime.now(UTC)
    return AccountValueResponse(
        as_of=now,
        series=account_value_series(_session_factory(db), range_, now=now),
    )
