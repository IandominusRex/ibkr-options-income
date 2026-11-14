"""Response models for ``GET /envelope`` (risk-envelope plan Task 14).

Named ``RiskEnvelope*`` because ``src.api.models.common.Envelope`` is the API's response base
(code fact C6). Every scenario figure is a percent of net liquidation, a loss counted positive;
U_ew is a ratio of it. Unknown is ``null``, never ``0``.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from src.api.models.common import Envelope


class RiskEnvelopeSnapshot(BaseModel):
    """One measurement: every scenario gross (no long option, H1) and net (long options counted)."""

    captured_at: datetime
    source: Literal["stored", "live"]  # "stored": the display on stored IV, labelled as such
    measured: bool
    enforce: str
    s10: float
    s10_net: float
    s10_vol10: float  # S10 with every option at +10 vol points
    s10_vol10_net: float
    s20: float
    s20_net: float
    g10: float
    g10_net: float
    p20: float
    p20_net: float
    t20: float
    t20_net: float
    s_smh: float
    s_smh_net: float
    uew: float
    nlv: float | None = None
    unmeasured: list[str] = Field(
        default_factory=list
    )  # symbols the gross measures could not value
    reasons: list[str] = Field(default_factory=list)  # why the measurement was unmeasured


class RiskEnvelopeLimits(BaseModel):
    """The limits the snapshot was compared with (null with no snapshot) and the glide's targets."""

    s10: float | None = None
    uew: float | None = None
    t20: float | None = None  # only while switch t20_limit is on
    s10_target: float
    uew_target: float


class RiskEnvelopeGlide(BaseModel):
    start: date
    end: date
    week: int  # 1-based, capped at weeks
    weeks: int
    s10_start: float
    uew_start: float
    s10_today: float
    uew_today: float


class RiskEnvelopeSwitch(BaseModel):
    name: str
    value: str  # what the trading process reads (the default in live, spxw_ready excepted)
    default: str
    source: str  # "default", "cli", "report:<id>" or "trigger:<id>"
    set_at: str | None = None


class RiskEnvelopeLes(BaseModel):
    """The latest Leveraged Entry Signal for one governing index (record only)."""

    index: str
    asof: date | None = None
    trend_up: bool
    pullback: bool
    washout: bool
    trend_break: bool
    tier_pct: float
    reasons: list[str] = Field(default_factory=list)
    breadth_osc: float | None = None  # the newest Nasdaq-100 breadth oscillator reading
    breadth_asof: date | None = None


class RiskEnvelopeResponse(Envelope):
    snapshot: RiskEnvelopeSnapshot | None = None  # the live one when same-day, else stored
    live: RiskEnvelopeSnapshot | None = None
    stored: RiskEnvelopeSnapshot | None = None
    limits: RiskEnvelopeLimits
    enforce: str
    glide: RiskEnvelopeGlide | None = None
    switches: list[RiskEnvelopeSwitch]
    cash_after_itm_assignment: float | None = None  # E11: cash after every ITM put is assigned
    les: list[RiskEnvelopeLes] = Field(default_factory=list)
