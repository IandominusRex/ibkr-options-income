"""The value book's gate (spec §9.4, amended by revision 4). Pure: no I/O, no model call.

Run at decision time (on the close) and again at send time (on a fresh quote). Every reason is a
refusal; ``FUNDABLE`` names the one a released capital can cure (the gross cap: the account's
stock and CSP collateral leave no room for a cash buy). What an LLM produced reaches it only as
the effective verdict and fair value (``value_effective``), which Python computed from bounded
drivers and clamped, and in live only once ``value.claude.apply_live`` is on (the effective
verdict is then Python's baseline); the gate reads no other Claude table.

**The risk envelope (risk-envelope Task 20, ruling Q2).** A buy is stock, so its S10 and U_ew are
linear: the context carries the room (``envelope``) and the buy's rates per dollar
(``s10_per_dollar``: the fraction of NLV a dollar of the name loses at SPY -10%, beta x 0.10 / NLV,
leverage-capped as the shock engine moves it; ``uew_per_dollar``: leverage / NLV), built by
``stage3`` from the pure shock engine. ``envelope_shock_budget`` (S10_gross after the buy above
L(t)), ``envelope_gross_budget`` (U_ew above its limit) and ``envelope_unmeasured`` refuse only
while the room's ``enforce`` is ``on``; in ``record`` they are returned by ``envelope_reasons`` for
the record and refuse nothing. They are never ``FUNDABLE``: released capital frees cash, not
envelope room, so an envelope-blocked buy opens no funding request.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace

from src.common.config import ValueBookCfg
from src.common.envelope_types import EnvelopeRoom

FUNDABLE = frozenset({"gross_notional_cap"})
ENVELOPE_SHOCK = "envelope_shock_budget"
ENVELOPE_GROSS = "envelope_gross_budget"
ENVELOPE_UNMEASURED = "envelope_unmeasured"
_EPS = 1e-9


@dataclass(frozen=True, slots=True)
class ValueEnvelope:
    """The risk envelope as the value book reads it in one RTH cycle: the room (S10_gross, U_ew
    and their limits) and each buy symbol's linear rates (see the module docstring). A symbol with
    no rate is unmeasured."""

    room: EnvelopeRoom
    s10_per_dollar: Mapping[str, float] = field(default_factory=dict)
    uew_per_dollar: Mapping[str, float] = field(default_factory=dict)

    def after_buy(self, symbol: str, cost: float) -> ValueEnvelope:
        """The envelope with *cost* dollars of *symbol* bought (later buys this cycle see it)."""
        s10 = self.s10_per_dollar.get(symbol)
        uew = self.uew_per_dollar.get(symbol)
        if s10 is None or uew is None or cost <= 0:
            return self
        return replace(
            self,
            room=replace(
                self.room,
                s10_gross=self.room.s10_gross + cost * s10 * 100.0,
                uew=self.room.uew + cost * uew,
            ),
        )


@dataclass(frozen=True, slots=True)
class BuyContext:
    symbol: str
    list_name: str
    shares: int
    price: float
    verdict: str  # the effective verdict
    mos: float | None  # the effective margin of safety, a fraction
    required_mos_pct: float
    mos_review: bool
    health: str
    data_quality: str
    timing: str
    earnings_in_window: bool | None
    net_liq: float
    ceiling: float  # the book's ceiling in dollars (halved by the trend brake)
    book_cost: float  # the book's cost: filled lots and working buys
    list_cost: float
    name_cost: float
    holds_name: bool
    positions_open: int
    wheel_name_exposure: float  # the wheel's CSP collateral and stock in the name
    gross_used: float  # stock of both books + CSP collateral + other approved buys
    adv_dollar_20: float | None
    attribution: str = "ok"  # ok | pending | frozen
    adds_paused: bool = False
    trend_brake: bool = False
    drawdown_stop: bool = False
    is_live: bool = False
    halted: bool = False
    spreads_underlying: bool = False
    quote_age_seconds: float | None = None  # None at decision time
    # The risk envelope at send time (Task 20); None at decision time and while it is off.
    envelope: EnvelopeRoom | None = None
    s10_per_dollar: float | None = None
    uew_per_dollar: float | None = None

    @property
    def cost(self) -> float:
        return self.shares * self.price


def envelope_reasons(ctx: BuyContext) -> list[str]:
    """What the risk envelope says of the buy, whatever the mode (empty with no envelope or while
    it is ``off``). S10 and U_ew after the buy are compared with their limits as ``admits`` does
    for a put: refused only when the measure ends above its limit **and** the buy raises it."""
    room = ctx.envelope
    if room is None or room.enforce == "off":
        return []
    if not room.measured or ctx.s10_per_dollar is None or ctx.uew_per_dollar is None:
        return [ENVELOPE_UNMEASURED]
    out: list[str] = []
    s10_add = ctx.cost * ctx.s10_per_dollar * 100.0
    if room.s10_gross + s10_add > room.s10_limit + _EPS and s10_add > _EPS:
        out.append(ENVELOPE_SHOCK)
    uew_add = ctx.cost * ctx.uew_per_dollar
    if room.uew + uew_add > room.uew_limit + _EPS and uew_add > _EPS:
        out.append(ENVELOPE_GROSS)
    return out


def validate(
    ctx: BuyContext,
    book: ValueBookCfg,
    *,
    max_gross_notional_pct: float,
    max_combined_name_pct: float,
) -> list[str]:
    reasons: list[str] = []
    if ctx.is_live:
        reasons.append("not_paper")  # Stage 3 is paper only until a separate live plan
    if ctx.halted:
        reasons.append("halted")
    if ctx.spreads_underlying:
        reasons.append("reserved_for_spreads_book")
    if ctx.shares < 1 or ctx.price <= 0:
        reasons.append("no_shares")
    if ctx.verdict != "READY":
        reasons.append("verdict_not_ready")
    if ctx.health != "pass":
        reasons.append("health_gate_failed")
    if ctx.data_quality != "pass" or ctx.mos_review:
        reasons.append("data_unreliable")
    if ctx.mos is None or ctx.mos * 100.0 < ctx.required_mos_pct:
        reasons.append("mos_below_required")
    if ctx.timing != "pass":
        reasons.append("timing_not_ready")
    if ctx.earnings_in_window is not False:
        reasons.append("earnings_within_window")
    if ctx.attribution != "ok":
        reasons.append("book_attribution_mismatch")
    if ctx.adds_paused:
        reasons.append("adds_paused")
    if ctx.trend_brake:
        reasons.append("trend_brake")
    if ctx.drawdown_stop:
        reasons.append("sleeve_breaker")
    cost = ctx.cost
    if ctx.book_cost + cost > ctx.ceiling:
        reasons.append("sleeve_exhausted")
    if ctx.name_cost + cost > ctx.ceiling * book.name_cap_pct / 100.0:
        reasons.append("name_cap")
    if ctx.list_cost + cost > ctx.ceiling * book.max_list_share_pct / 100.0:
        reasons.append("list_share_cap")
    if not ctx.holds_name and ctx.positions_open >= book.max_positions:
        reasons.append("max_positions")
    if ctx.wheel_name_exposure + ctx.name_cost + cost > ctx.net_liq * max_combined_name_pct / 100:
        reasons.append("combined_name_cap")
    if ctx.gross_used + cost > ctx.net_liq * max_gross_notional_pct / 100.0:
        reasons.append("gross_notional_cap")
    if ctx.adv_dollar_20 is None or (ctx.name_cost + cost) > ctx.adv_dollar_20 * (
        book.illiquid_adv_pct / 100.0
    ):
        reasons.append("illiquid")
    if ctx.quote_age_seconds is not None and ctx.quote_age_seconds > book.quote_max_age_seconds:
        reasons.append("price_stale_at_send")
    if ctx.envelope is not None and ctx.envelope.enforce == "on":
        reasons.extend(envelope_reasons(ctx))  # never FUNDABLE (ruling Q2)
    return reasons


def fundable_only(reasons: list[str]) -> bool:
    """True when released capital would let the buy pass: the gross cap is its only refusal."""
    return bool(reasons) and set(reasons) <= FUNDABLE
