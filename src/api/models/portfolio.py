"""Response shapes for the portfolio read surfaces (P3-P4 M2).

Every route is owner-only and renders what `read_portfolio` (the M1 fallback chain)
found — never a second data path. The `source`/`degraded`/`note` triple rides on
every snapshot-derived response so a client can always tell which rung it is
looking at and read the degradation in words.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from src.api.models.common import Envelope, Sourced

# ---------------------------------------------------------------------------
# Task 2.1 — GET /portfolio/summary
# ---------------------------------------------------------------------------


class AccountBlock(Envelope):
    net_liquidation: Sourced[float]
    total_cash: Sourced[float]
    buying_power: Sourced[float]
    maintenance_margin: Sourced[float]
    excess_liquidity: Sourced[float]


class ExposureBlock(Envelope):
    open_positions: int
    open_shorts: int
    open_campaigns: int
    net_delta_exposure: float
    cash_secured_against_puts: float
    buying_power_utilisation_pct: float | None  # None when buying power is unknown
    shorts_at_assignment_risk: int


class PortfolioSummaryResponse(Envelope):
    source: Literal["monitor", "refresh", "eod", "none"]
    degraded: bool
    account: AccountBlock | None  # None on the "none" rung
    exposure: ExposureBlock | None  # None on the "none" rung
    note: str | None  # populated on every degraded rung, in plain words


# ---------------------------------------------------------------------------
# Task 2.2 — GET /portfolio/positions
# ---------------------------------------------------------------------------


class OptionLeg(Envelope):
    symbol: str  # the OCC option symbol
    right: Literal["C", "P"] | None = None  # None when the snapshot carried none — never fabricated
    strike: float | None = None  # None when the snapshot carried none — never 0.0
    expiry: date | None
    dte: int | None
    contracts: int  # absolute; `short` carries the direction
    short: bool
    delta: float | None
    delta_source: str | None
    market_price: float | None
    market_value: float | None
    unrealized_pnl: float | None
    moneyness: Literal["itm", "atm", "otm"] | None
    assignment_risk: bool


class StockLeg(Envelope):
    shares: float
    avg_cost: float
    adjusted_cost_basis: float | None  # from campaigns, when the shares came from assignment
    market_price: float | None
    market_value: float | None
    unrealized_pnl: float | None
    unrealized_pnl_adjusted: float | None  # against adjusted basis; None when no adjusted basis


class PositionGroup(Envelope):
    underlying: str
    stock: StockLeg | None
    options: list[OptionLeg]


class PositionsResponse(Envelope):
    source: Literal["monitor", "refresh", "eod", "none"]
    degraded: bool
    groups: list[PositionGroup]


# ---------------------------------------------------------------------------
# Task 2.3 — GET /portfolio/campaigns
# ---------------------------------------------------------------------------


class CampaignLeg(Envelope):
    candidate_id: str
    strategy: str
    right: Literal["C", "P"] | None
    strike: float | None
    expiry: date | None
    known: bool  # False when the CandidateRow was pruned; the leg still renders


class CampaignSummary(Envelope):
    campaign_id: str
    symbol: str
    status: Literal["open", "closed"]
    opened_date: date
    closed_date: date | None
    legs: list[CampaignLeg]
    total_premium_collected: float
    total_debit_paid: float
    net_premium: float
    assigned: bool
    adjusted_cost_basis: float | None
    realized_stock_pnl: float | None


class CampaignsResponse(Envelope):
    campaigns: list[CampaignSummary]


# ---------------------------------------------------------------------------
# Task 2.4 — GET /portfolio/calendar
# ---------------------------------------------------------------------------


class CalendarEntry(Envelope):
    symbol: str
    underlying: str
    right: Literal["C", "P"]
    strike: float
    contracts: int
    short: bool
    moneyness: Literal["itm", "atm", "otm"] | None
    consequence: Literal["assigned", "called_away", "expires_worthless", "unknown"]
    assignment_risk: bool


class CalendarDay(Envelope):
    expiry: date
    dte: int
    entries: list[CalendarEntry]


class CalendarResponse(Envelope):
    source: Literal["monitor", "refresh", "eod", "none"]
    degraded: bool
    horizon_days: int
    days: list[CalendarDay]
