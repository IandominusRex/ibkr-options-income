"""Response models for the read-only spreads routes (web overhaul Part 1, Task 8)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from src.api.models.common import Envelope


class SpreadPositionOut(Envelope):
    spread_id: str
    mode: str
    side: Literal["put", "call"]
    expiry: date
    short_strike: float
    long_strike: float
    width: float
    contracts_opened: int
    contracts: int  # still open
    entry_credit: float  # per share
    entry_commission: float
    opened_at: datetime
    status: str  # open | expiring | closed
    exit_debit: float | None = None  # per share, qty-weighted; None while open
    exit_commission: float | None = None
    exit_reason: str | None = None
    closed_at: datetime | None = None
    realized_pnl_usd: float | None = None  # None while open, never 0.0


class SpreadPositionsResponse(Envelope):
    available: bool  # False when data/spreads.db does not exist or cannot be read
    underlying: str
    mode: str
    positions: list[SpreadPositionOut] = Field(default_factory=list)


class SpreadMenuItemOut(BaseModel):
    """One lettered spread on a pick menu, flattened from the stored SpreadMenuItem. Credits are
    per share; every figure was computed by src/spreads/menu.py when the menu was built."""

    letter: str
    position: Literal["inside", "baseline", "outer"]
    side: Literal["put", "call"]
    short_strike: float
    long_strike: float
    width: float
    contracts: int  # set by the spreads gate, never by Claude
    credit_mid: float
    credit_after_costs: float
    max_loss_per_contract_usd: float
    short_delta: float | None
    spot: float
    dist_spot_pts: float  # short strike's distance from spot (positive = out of the money)
    dist_em_multiple: float | None  # the same in expected moves
    be_nominal_exits: float | None  # break-even win rate (0-1) under the configured exits


class SpreadPickOut(BaseModel):
    """One menu Claude was shown, its choice, and what the service did with it."""

    pick_id: int
    created_at: datetime
    book_mode: str
    choice: str  # a menu letter, or "skip"
    reason: str  # Claude's reason; "" when it gave none
    fallback_reason: str | None  # set when Claude's answer could not be used
    executed_letter: str | None  # the item the service tried to send; None when nothing
    send_rejected: bool  # True when it did not trade (refused at send time, or not filled)
    send_reasons: list[str]
    filled: bool
    model: str
    regime: str
    side: str | None
    plan_bias: str | None
    event_flag: bool
    menu_readable: bool  # False when the stored menu no longer parses; `menu` is then empty
    menu: list[SpreadMenuItemOut] = Field(default_factory=list)
    spread_id: str | None = None  # the position this pick opened, when one did


class SpreadPicksResponse(Envelope):
    available: bool  # False when data/spreads.db does not exist or cannot be read
    underlying: str
    mode: str  # the spreads service's configured book mode (shadow | paper)
    ai_enabled: bool  # config spreads.ai.enabled: whether menus are offered at all
    day: date  # the New York day shown
    previous_day: date | None = None  # nearest earlier day with a pick or an opened spread
    next_day: date | None = None
    picks: list[SpreadPickOut] = Field(default_factory=list)  # newest first
    positions: list[SpreadPositionOut] = Field(default_factory=list)  # every mode, oldest first


class SpreadOrderOut(BaseModel):
    """One filled order of the credit-spreads book (``spread_orders``: only filled orders are
    recorded), joined to its spread. The spread's fields are None when its position row is
    missing."""

    spread_id: str
    kind: Literal["open", "close"]
    ib_order_id: int | None
    perm_id: int | None
    filled_qty: int
    price: float | None  # per share; None when no price was recorded
    commission: float
    reason: str | None  # why a close was sent (profit take, stop, expiry...)
    created_at: datetime
    mode: str | None
    side: Literal["put", "call"] | None
    expiry: date | None
    short_strike: float | None
    long_strike: float | None


class SpreadOrdersResponse(Envelope):
    available: bool  # False when data/spreads.db does not exist or cannot be read
    underlying: str
    orders: list[SpreadOrderOut] = Field(default_factory=list)
