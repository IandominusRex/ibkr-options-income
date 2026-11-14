"""Pure functions that turn the market regime into CSP limits (spec sections 4-5).

Deterministic, no I/O, no LLM: the generator (`strategies/cash_secured_put.py`) and the Rules
Engine (`engine/risk_engine.py`) call the *same* functions here, so what the sizer proposes and
what the gate accepts can never disagree. They read only the `SizingContext` they are handed and
`config/risk_limits.yaml` (`regime:` and `leveraged_sizing:`).

What each limit is:

* **Budgets** — the total CSP allocation scales by the **SPY** regime's multiplier; a name's
  per-ticker and per-sector risk caps scale by the **name's** regime (the stricter of SPY and QQQ
  for a tech-linked name). See `multipliers` and `capital.scale_caps`.
* **Per-trade ceiling** — `floor(hard_max x regime fraction)`; for a leveraged ETF also x its
  leverage fraction, tiered calm / stressed (ruling 35), never below one lot unless the regime's
  own ceiling is zero. See `per_trade_cap`.
* **Daily count** — new CSPs per ET day per *governing index* (QQQ for a tech-linked name, SPY
  for every other; ruling 16). See `daily_limit`.
* **Guaranteed floor** — a few lots per governing index per day may exceed the *scaled* budget
  (never the unscaled caps), so a full book is not a complete stop (decision 31). See
  `floor_left`.
* **Scale-in ladder** — a name under the ladder may add a lot only once the price has fallen into
  its zone (`scale_in_reason`); a loss exit on a name blocks new CSPs on it for the rest of the
  ET day (`loss_exit_reason`). The zone itself is worked out by `src/analytics/scale_in.py` and
  carried on the `SizingContext`.
* **Claude's cut** — an auto-opened opening CSP may be sent smaller than the deterministic size
  when Claude's review says so (`claude_cut`: a plain integer from a Claude CLI review, from 0 up
  to the size, never above it), applied in paper and only recorded in live (`cut_applies`, with a
  daily circuit breaker). Both functions take plain values and nothing else; the sender calls
  them and records every override.

* **Covered-call breakout** — after an upside breakout a held name's call strikes must clear a
  floor and stay under a delta cap (`cc_timing_reasons`, held again against the live delta at
  send time by `live_cc_delta_reason`): a call is pushed out, and when nothing on the chain
  clears both, none is sold on that name that scan. Its own switch (``cc_timing.breakout``); not
  a regime limit.
* **The leveraged sleeve** (risk-envelope Task 23, behind the ``leveraged_sleeve`` switch) - the one
  way a leveraged ETF gets a cash-secured put under ``leveraged_sizing.csp_mode: drawdown_only``.
  Above the governing index's 200-day average the Leveraged Entry Signal's pullback is the signal;
  below it only the bottoming signal + the sigma-drawdown path opens a lot, at half the tier
  (`sleeve_path`, `sleeve_tier`). Its DTE and delta windows replace the put's own
  (`sleeve_window_reason`), the pace is one lot per name per N sessions and at most M open
  (`sleeve_pace_reason`), and the size is the LES tier's room, leverage-weighted with every other
  leveraged put and LES share, rounded **down** to whole lots and never up to one (`sleeve_room_usd`,
  `sleeve_contracts`). Reasons: ``sleeve_window``, ``sleeve_pace``, ``sleeve_cap``.
* **The tech-linked cap and the stacking rule** (Task 25) and the index class's budget multipliers
  (Task 24), each behind its own switch: see `tech_cap_reason`, `stacking_action` and `multipliers`.
* **Variance-premium waiver** — a cash-secured put that opens on a *name-level* bottoming signal
  is exempt from the credit-below-fair-value floor and from nothing else (`vrp_waiver`): it
  carries its own guards (the delta cap and one lot per name per N sessions). Not a market-eased
  lot, not an ordinary ladder lot, not a call or a roll. The delta cap is held again at send
  time against the live quote (`live_bottoming_delta_reason`), read from the tag frozen on the
  card, since the fresh signals the decision-time guard needs do not exist then.

The regime limits (and the ladder's zone) switch off when the context is None, `/regime off`
suspended it today, or `regime.enabled` is false. The leveraged-ETF ceiling has its own switch and is **not** a regime
limit: it still applies when the regime is suspended or disabled (a ladder trigger on the name
still stresses its tier). Rolls, closes and exits are never limited here, and a covered call only
by the breakout rule: callers apply the other functions to cash-secured puts only.
"""

from __future__ import annotations

import math
from typing import Literal

from src.common.books import les_exposure, value_exposure
from src.common.config import (
    ClaudeCutCfg,
    get_cc_timing_cfg,
    get_config,
    get_leveraged_sizing_cfg,
    get_regime_cfg,
)
from src.common.schemas import (
    AccountSnapshot,
    CcBreakout,
    MarketRegime,
    OptionQuote,
    OptionRight,
    PositionSnapshot,
    SizingContext,
    SizingNote,
    Strategy,
    TradeCandidate,
)
from src.engine.capital import max_contracts, resolve_caps, scale_caps, seed_budgets
from src.storage.slow_breaker import csp_budget_fraction as slow_breaker_fraction

IndexName = Literal["SPY", "QQQ"]
Tier = Literal["calm", "stressed"]

_ORDER: tuple[MarketRegime, ...] = tuple(MarketRegime)  # normal -> crisis, by definition order


def _rank(r: MarketRegime) -> int:
    return _ORDER.index(r)


def _floor(x: float) -> int:
    """floor() that is not fooled by 1.7999999999999998-style float products."""
    return int(math.floor(x + 1e-9))


def active(ctx: SizingContext | None) -> bool:
    """True when the regime limits apply: a context, not suspended today, and enabled in config."""
    return ctx is not None and not ctx.suspended and get_regime_cfg().enabled


def governing_index(ctx: SizingContext, symbol: str) -> IndexName:
    """The index a name's daily count and floor lots are bucketed under (ruling 16).

    A tech-linked name counts against QQQ's bucket, every other name against SPY's, so BAC opens
    never use up TQQQ's stressed daily limit.
    """
    tech = {t.upper() for t in ctx.tech_linked}
    return "QQQ" if symbol.upper() in tech else "SPY"


def name_regime(ctx: SizingContext, symbol: str) -> tuple[MarketRegime, IndexName]:
    """The regime that governs *symbol* and the index it comes from.

    SPY's for an ordinary name; the stricter of SPY's and QQQ's for a tech-linked name (a tie
    reports QQQ).
    """
    spy = ctx.regimes.get("SPY", MarketRegime.NORMAL)
    if governing_index(ctx, symbol) == "SPY":
        return spy, "SPY"
    qqq = ctx.regimes.get("QQQ", MarketRegime.NORMAL)
    return (qqq, "QQQ") if _rank(qqq) >= _rank(spy) else (spy, "SPY")


def _effective_name_regime(ctx: SizingContext, symbol: str) -> MarketRegime:
    """The regime that sizes *symbol*: NORMAL when the regime limits are off."""
    return name_regime(ctx, symbol)[0] if active(ctx) else MarketRegime.NORMAL


def switch_on(ctx: SizingContext | None, name: str) -> bool:
    """Whether the data-gated switch *name* reads ``on`` in *ctx* (read once when the context was
    built; a missing key is off, and every switch is off in live)."""
    return ctx is not None and ctx.switches.get(name) == "on"


def index_class(symbol: str) -> bool:
    """True for a broad-index ETF (``portfolio.broad_index_etfs``): the ``index_1x`` tail class."""
    listed = get_config().risk.get("portfolio", {}).get("broad_index_etfs") or []
    return symbol.upper() in {str(s).upper() for s in listed}


def class_multipliers(ctx: SizingContext | None, symbol: str) -> tuple[float, float] | None:
    """``(ticker, book)`` multipliers from ``regime.csp.budget_multiplier_by_class.index_1x`` for an
    index-class name (the same regimes pick them as for any name), or None for any other name and
    when the regime limits are off. Both follow the class table: the index put's own budget and the
    total CSP allocation it draws on are eased together, or the book budget would still throttle it
    exactly when the evidence says leaning in pays (spec §3.8)."""
    if ctx is None or not active(ctx) or not index_class(symbol):
        return None
    table = get_regime_cfg().csp.budget_multiplier_by_class["index_1x"]
    spy = ctx.regimes.get("SPY", MarketRegime.NORMAL)
    return table[name_regime(ctx, symbol)[0]], table[spy]


def multipliers(ctx: SizingContext | None, symbol: str) -> tuple[float, float]:
    """``(ticker, book)`` budget multipliers for *symbol*; ``(1.0, 1.0)`` when inactive.

    ``book`` follows the SPY regime (the total CSP allocation); ``ticker`` follows the name's
    regime (per-ticker and per-sector risk). Pass both to `capital.scale_caps`. An index-class name
    takes the ``index_1x`` class table instead while the ``index_1x`` switch is on
    (`class_multipliers`); with it off the old table applies and the difference is recorded.
    """
    if ctx is None or not active(ctx):
        return 1.0, 1.0
    if switch_on(ctx, "index_1x"):
        by_class = class_multipliers(ctx, symbol)
        if by_class is not None:
            return by_class
    cfg = get_regime_cfg().csp.budget_multiplier
    spy = ctx.regimes.get("SPY", MarketRegime.NORMAL)
    return cfg[name_regime(ctx, symbol)[0]], cfg[spy]


def leverage_factor(ctx: SizingContext | None, symbol: str) -> int | None:
    """The daily leverage (2 or 3) when the leveraged-ETF ceiling applies to *symbol*."""
    if ctx is None or not get_leveraged_sizing_cfg().enabled:
        return None
    return ctx.leverage.get(symbol.upper())


def leverage_tier(ctx: SizingContext | None, symbol: str) -> Tier:
    """``"stressed"`` when the name's regime is not normal or any ladder trigger holds on it.

    With the regime suspended or disabled the regime part reads as normal, but a name trigger
    still stresses the tier. ``"calm"`` otherwise.
    """
    if ctx is None:
        return "calm"
    if _effective_name_regime(ctx, symbol) != MarketRegime.NORMAL:
        return "stressed"
    return "stressed" if ctx.name_triggers.get(symbol) else "calm"


def _regime_fraction(ctx: SizingContext, symbol: str) -> float:
    if not active(ctx):
        return 1.0
    return get_regime_cfg().csp.per_trade_fraction[name_regime(ctx, symbol)[0]]


def _base_cap(ctx: SizingContext, symbol: str, hard_max: int) -> int:
    return _floor(hard_max * _regime_fraction(ctx, symbol))


def per_trade_cap(
    ctx: SizingContext | None, symbol: str, hard_max: int, frozen: SizingNote | None = None
) -> int:
    """The most contracts one CSP on *symbol* may carry (ruling 35).

    ``hard_max`` when there is no context. Otherwise ``base = floor(hard_max x regime fraction)``
    (the fraction is 1.0 when the regime limits are off); zero when ``base`` is zero; for a
    leveraged ETF zero under ``csp_mode: drawdown_only`` outside the sleeve (`sleeve_lot`), else
    ``max(1, floor(hard_max x regime fraction x leverage fraction))`` with the leverage fraction of
    the name's tier (a ceiling only: a sleeve lot's size is the LES tier's room, `sleeve_contracts`,
    never a minimum of one); else ``base``. *frozen* is the card's own note, read for the sleeve's
    below-trend path at send time (`sleeve_path_and_tier`).
    """
    if ctx is None:
        return hard_max
    rf = _regime_fraction(ctx, symbol)
    base = _floor(hard_max * rf)
    if base == 0:
        return 0
    factor = leverage_factor(ctx, symbol)
    if factor is None:
        return base
    lev_cfg = get_leveraged_sizing_cfg()
    if lev_cfg.csp_mode == "drawdown_only" and not sleeve_lot(ctx, symbol, frozen):
        return 0  # 2026-11-14: no leveraged CSP outside the drawdown sleeve
    lf = lev_cfg.per_trade_fraction[leverage_tier(ctx, symbol)][factor]
    return max(1, _floor(hard_max * rf * lf))


# --------------------------------------------------------------------------- #
# The leveraged sleeve (risk-envelope Task 23; spec §3.5, rulings E7, L1-L4)
# --------------------------------------------------------------------------- #

SleevePath = Literal["trend", "below_trend"]
REASON_SLEEVE_WINDOW = "sleeve_window"
REASON_SLEEVE_PACE = "sleeve_pace"
REASON_SLEEVE_CAP = "sleeve_cap"


def les_index(symbol: str) -> str | None:
    """The unleveraged index whose Leveraged Entry Signal governs *symbol* (TQQQ -> QQQ, SOXL ->
    SOXX), or None when it has none."""
    return get_regime_cfg().leveraged_entry.governing.get(symbol.upper())


def sleeve_path_and_tier(
    ctx: SizingContext | None, symbol: str, frozen: SizingNote | None = None
) -> tuple[SleevePath | None, float]:
    """``(path, tier %)`` of a sleeve lot on *symbol*, or ``(None, 0.0)`` when none may open.

    Closed unless the ``leveraged_sleeve`` switch is on and *symbol* is a leveraged ETF with a
    governing index whose latest signal is on file (a missing or stale signal fails closed, L1).
    **Trend** (the index closed above its 200-day, L3): the signal's own tier (3.0 on a pullback,
    6.0 with the washout, 0.0 without a pullback). **Below trend**: ``tiers.below_trend`` (1.5) only
    when the bottoming signal, the sigma-drawdown and (per candidate, `sleeve_window_reason`) the IV
    rank all hold; at scan time that is ``ctx.sleeve_below_trend``, at send time (no bars) the path
    frozen on the card (*frozen*)."""
    if ctx is None or not switch_on(ctx, "leveraged_sleeve"):
        return None, 0.0
    if leverage_factor(ctx, symbol) is None:
        return None, 0.0
    index = les_index(symbol)
    signal = ctx.les.get(index) if index else None
    if signal is None:
        return None, 0.0
    if signal.trend_up:
        return ("trend", signal.tier_pct) if signal.tier_pct > 0 else (None, 0.0)
    if ctx.for_send:
        held = frozen is not None and frozen.sleeve == "below_trend"
    else:
        held = symbol.upper() in ctx.sleeve_below_trend
    tier = get_regime_cfg().leveraged_entry.tiers.below_trend
    return ("below_trend", tier) if held and tier > 0 else (None, 0.0)


def sleeve_path(
    ctx: SizingContext | None, symbol: str, frozen: SizingNote | None = None
) -> SleevePath | None:
    """Which path a sleeve lot on *symbol* opens on (`sleeve_path_and_tier`), or None."""
    return sleeve_path_and_tier(ctx, symbol, frozen)[0]


def sleeve_tier(ctx: SizingContext | None, symbol: str, frozen: SizingNote | None = None) -> float:
    """The LES tier, as a leverage-weighted % of net liquidation, a sleeve lot on *symbol* may fill
    (0.0 when the sleeve is closed to it)."""
    return sleeve_path_and_tier(ctx, symbol, frozen)[1]


def sleeve_lot(ctx: SizingContext | None, symbol: str, frozen: SizingNote | None = None) -> bool:
    """True when a CSP on leveraged *symbol* opens inside the drawdown sleeve (its tier is above
    zero): the only way it gets a lot under ``csp_mode: drawdown_only``."""
    return sleeve_tier(ctx, symbol, frozen) > 0.0


def sleeve_window_reason(
    ctx: SizingContext | None,
    symbol: str,
    *,
    dte: int,
    delta: float | None,
    iv_rank: float | None,
    frozen: SizingNote | None = None,
) -> str | None:
    """``"sleeve_window"`` when a sleeve lot's DTE or |delta| is outside the sleeve's own window
    (conditions 4 and 5: DTE 7-14, delta 0.15-0.20), or, on the below-trend path, its IV rank is
    under ``iv_rank_min`` or unknown (condition 3, fail closed). None for a name with no sleeve lot
    and for a missing delta (the gate's own ``delta_missing``)."""
    path = sleeve_path(ctx, symbol, frozen)
    if path is None:
        return None
    cfg = get_leveraged_sizing_cfg().sleeve
    if not (cfg.dte[0] <= dte <= cfg.dte[1]):
        return REASON_SLEEVE_WINDOW
    if delta is not None and not (cfg.delta[0] - 1e-9 <= abs(delta) <= cfg.delta[1] + 1e-9):
        return REASON_SLEEVE_WINDOW
    if path == "below_trend" and (iv_rank is None or iv_rank < cfg.iv_rank_min):
        return REASON_SLEEVE_WINDOW
    return None


def leveraged_short_puts(
    ctx: SizingContext | None, positions: list[PositionSnapshot]
) -> list[PositionSnapshot]:
    """The open short puts on leveraged ETFs (every name in the leverage map): the sleeve's CSP lots."""
    if ctx is None:
        return []
    return [
        p
        for p in positions
        if p.sec_type == "OPT"
        and p.right == OptionRight.PUT
        and p.position < 0
        and ctx.leverage.get((p.underlying or p.symbol).upper(), 1) > 1
    ]


def sleeve_pace_reason(
    ctx: SizingContext | None,
    symbol: str,
    positions: list[PositionSnapshot],
    *,
    batch_lots: int = 0,
) -> str | None:
    """``"sleeve_pace"`` when *symbol* had a sleeve lot inside the pace window (``every_sessions``,
    3 sessions, ``ctx.sleeve_recent``), or when ``max_open_lots`` (2) sleeve puts are already open:
    the book's leveraged short puts (`leveraged_short_puts`, one lot per contract) plus *batch_lots*
    accepted earlier in the same batch."""
    if ctx is None:
        return None
    if symbol.upper() in {n.upper() for n in ctx.sleeve_recent}:
        return REASON_SLEEVE_PACE
    cfg = get_leveraged_sizing_cfg().sleeve
    open_lots = {
        (p.underlying or p.symbol, p.strike, p.expiry) for p in leveraged_short_puts(ctx, positions)
    }
    return REASON_SLEEVE_PACE if len(open_lots) + batch_lots >= cfg.max_open_lots else None


def sleeve_used_usd(ctx: SizingContext | None, positions: list[PositionSnapshot]) -> float:
    """What the sleeve's tier already holds, leverage-weighted: the strike x 100 x contracts of every
    open leveraged short put, plus the LES share book's market value (``books.les_exposure``, empty
    until Task 32a), each at its leverage."""
    if ctx is None:
        return 0.0
    used = sum(
        (p.strike or 0.0)
        * 100.0
        * abs(p.position)
        * ctx.leverage.get((p.underlying or p.symbol).upper(), 1)
        for p in leveraged_short_puts(ctx, positions)
    )
    used += sum(
        value * ctx.leverage.get(name.upper(), 1) for name, value in les_exposure().by_name.items()
    )
    return used


def sleeve_room_usd(
    ctx: SizingContext | None,
    symbol: str,
    account: AccountSnapshot,
    positions: list[PositionSnapshot],
    *,
    extra_usd: float = 0.0,
    frozen: SizingNote | None = None,
) -> float:
    """The leverage-weighted dollars a sleeve lot on *symbol* may still add: the tier's share of net
    liquidation less what the sleeve holds (`sleeve_used_usd`) and *extra_usd* (lots accepted
    earlier in the batch). Never negative."""
    tier = sleeve_tier(ctx, symbol, frozen)
    cap = tier / 100.0 * max(0.0, account.net_liquidation)
    return max(0.0, cap - sleeve_used_usd(ctx, positions) - extra_usd)


def sleeve_contracts(room_usd: float, strike: float, leverage: int) -> int:
    """Whole lots of ``strike x 100 x leverage`` that fit *room_usd*: rounded down, never up to one."""
    unit = strike * 100.0 * max(1, leverage)
    return 0 if unit <= 0 else max(0, _floor(room_usd / unit))


def ceiling_kind(
    ctx: SizingContext | None,
    symbol: str,
    hard_max: int,
    pre: int,
    frozen: SizingNote | None = None,
) -> Literal["regime_ceiling", "leveraged_ceiling"] | None:
    """Which factor brings *pre* contracts down to the per-trade ceiling, or None.

    ``"leveraged_ceiling"`` when the leveraged-ETF factor is what takes the ceiling below
    ``min(pre, regime base)``; ``"regime_ceiling"`` when the regime fraction does; None when the
    ceiling does not bind at all.
    """
    if ctx is None:
        return None
    cap = per_trade_cap(ctx, symbol, hard_max, frozen)
    if cap >= pre:
        return None
    if cap < min(pre, _base_cap(ctx, symbol, hard_max)):
        return "leveraged_ceiling"
    return "regime_ceiling"


def daily_limit(ctx: SizingContext | None, symbol: str) -> int | None:
    """New CSPs allowed today under *symbol*'s regime (None = no limit)."""
    if ctx is None or not active(ctx):
        return None
    return get_regime_cfg().csp.max_new_per_day[name_regime(ctx, symbol)[0]]


def floor_left(ctx: SizingContext | None, symbol: str, accepted_so_far: dict[str, int]) -> int:
    """Guaranteed-floor lots still available to *symbol*'s governing index today (decision 31).

    ``floor_new_per_day[name regime]`` less the floor lots already sent today
    (``ctx.floor_lots_counted``) and those accepted earlier in this batch
    (*accepted_so_far*, keyed by governing index). Zero when the regime limits are off.
    """
    if ctx is None or not active(ctx):
        return 0
    allowed = get_regime_cfg().csp.floor_new_per_day[name_regime(ctx, symbol)[0]]
    index = governing_index(ctx, symbol)
    return max(0, allowed - ctx.floor_lots_counted.get(index, 0) - accepted_so_far.get(index, 0))


def loss_exit_reason(ctx: SizingContext | None, symbol: str) -> str | None:
    """``"loss_exit_cooldown"`` while *symbol* had a loss exit earlier in the same ET day.

    Applies whenever a context is present (the regime being suspended does not lift it), and
    only while ``regime.ladder.loss_exit_same_day_block`` is on. Checked before the zone: the
    re-entries of the week of 2026-10-13 came 18-55 minutes after the stop-outs. CSPs only; the
    callers never apply it to closes, rolls or covered calls.
    """
    if ctx is None or not get_regime_cfg().ladder.loss_exit_same_day_block:
        return None
    return (
        "loss_exit_cooldown" if symbol.upper() in {s.upper() for s in ctx.loss_exit_today} else None
    )


def scale_in_reason(ctx: SizingContext | None, symbol: str, spot: float | None) -> str | None:
    """``"scale_in_zone_not_reached"`` when *symbol* has a zone and *spot* is above its top.

    None when the context is missing or inactive (``/regime off``, ``regime.enabled: false``),
    when the name has no zone (it is not under the ladder, or this is its first lot), or when
    the spot is unknown. A spot at or below the top of the zone is allowed: the zone is where
    the next lot may be sold, and a price already past it is no reason to refuse.
    """
    if ctx is None or not active(ctx) or spot is None:
        return None
    zone = ctx.scale_in.get(symbol)
    if zone is None:
        return None
    if symbol in ctx.name_bottoming:
        return None  # a bottom is forming: the lot may open here, under `bottoming_reason`'s guards
    return "scale_in_zone_not_reached" if spot > zone.zone_high else None


def signal_lot(ctx: SizingContext | None, symbol: str, spot: float | None) -> bool:
    """True when a lot on *symbol* at *spot* opens on a name-level bottoming signal.

    The name has a zone, a bottom is forming (``ctx.name_bottoming``) and the price is above the
    zone top, i.e. the ladder alone would have made it wait. A lot inside or under the zone is an
    ordinary ladder lot, not a signal lot. Off when the regime limits are off.
    """
    if ctx is None or not active(ctx) or spot is None or symbol not in ctx.name_bottoming:
        return False
    zone = ctx.scale_in.get(symbol)
    return zone is not None and spot > zone.zone_high


def vrp_waiver(
    ctx: SizingContext | None,
    strategy: Strategy,
    symbol: str,
    spot: float | None,
    frozen: SizingNote | None = None,
) -> bool:
    """True when the credit-below-fair-value floor (``premium_below_fair_value``) does not apply.

    Only a cash-secured put that opens on a **name-level** bottoming signal is exempt: the lots
    that carry the delta cap and the one-lot-per-N-sessions guard (`bottoming_guard`), since the
    operator's 2026-10-22 ruling. Nothing else is: not an ordinary ladder lot (inside or under
    the zone), not a lot sized under a market-eased regime (tag ``"market"``), not a covered
    call or a roll, and not when the regime limits are off (``/regime off``,
    ``regime.enabled: false``, or no context), because no signal lot exists then.

    At decision time (*ctx* built for a scan) the fresh signal decides, exactly as `signal_lot`
    does for the guards; a tag already on the card is never trusted there. At send time
    (``ctx.for_send``) the context carries no signals, so the re-gate reads the tag frozen on
    the card (*frozen*, the candidate's own `SizingNote`): ``bottoming == "name"``, **unless the
    name already had a signal lot within the window** (``ctx.signal_lot_recent``, which the
    send-time context does carry): that lot is refused by `bottoming_send_reason`, and a lot
    refused for the guard is never waived. Pure; the generator and the gate call this one
    function, so they cannot disagree.
    """
    if strategy != Strategy.CASH_SECURED_PUT or ctx is None or not active(ctx):
        return False
    if leverage_factor(ctx, symbol) is not None:
        return False  # 2026-11-14: a leveraged ETF is never waived; it meets the floor like any lot
    if ctx.for_send:
        return (
            frozen is not None
            and frozen.bottoming == "name"
            and symbol not in ctx.signal_lot_recent
        )
    return signal_lot(ctx, symbol, spot)


def bottoming_guard(ctx: SizingContext | None, symbol: str, delta: float | None) -> str | None:
    """The guards on a signal lot (spec section 6b): the delta cap and one lot per N sessions.

    ``"bottoming_delta_too_high"`` when ``abs(delta)`` is above ``bottoming.signal_delta_max``
    (config validation keeps that above the strategy's ``delta_min``, so a real far strike
    passes); ``"bottoming_lot_recent"`` when the name had a signal lot within
    ``signal_lot_every_sessions`` sessions. Callers apply it only to a `signal_lot`.
    """
    if ctx is None:
        return None
    if delta is not None and abs(delta) > get_regime_cfg().bottoming.signal_delta_max + 1e-9:
        return "bottoming_delta_too_high"
    if symbol in ctx.signal_lot_recent:
        return "bottoming_lot_recent"
    return None


def bottoming_reason(ctx: SizingContext | None, cand: TradeCandidate) -> str | None:
    """`bottoming_guard` for a candidate that opens on a name-level signal, else None."""
    spot = cand.ideal.spot if cand.ideal is not None else None
    if not signal_lot(ctx, cand.underlying, spot):
        return None
    return bottoming_guard(ctx, cand.underlying, cand.delta)


def bottoming_send_reason(ctx: SizingContext | None, cand: TradeCandidate) -> str | None:
    """The one signal-lot guard that holds at send time: one lot per name per N sessions.

    ``"bottoming_lot_recent"`` for a cash-secured put whose frozen note carries the name-level tag
    (``bottoming == "name"``: the card was opened on a name signal, which the send-time context has
    no fresh signals to re-derive) when the name already had a signal lot within
    ``signal_lot_every_sessions`` sessions (``ctx.signal_lot_recent``, read from the lots recorded
    when sent). Two cards queued on one name before either was sent, approved one poll apart, would
    otherwise both go out with the fair-value floor waived. Reads the tag on the card and not
    the regime switch: refusing is only ever more conservative (as the live delta cap is). Rolls,
    covered calls, market-eased lots and ordinary ladder lots carry no such tag and are untouched.
    """
    if ctx is None or not ctx.for_send:
        return None
    if cand.strategy != Strategy.CASH_SECURED_PUT or cand.sizing is None:
        return None
    if cand.sizing.bottoming != "name":
        return None
    return "bottoming_lot_recent" if cand.underlying in ctx.signal_lot_recent else None


def bottoming_tag(
    ctx: SizingContext | None, symbol: str, spot: float | None
) -> Literal["market", "name"] | None:
    """How a lot relates to the bottoming signal, for the card and the order snapshot.

    ``"name"`` for a signal lot (it opened above the zone on the name's signal); ``"market"``
    when the name's governing index was eased one notch by the market signal; else None.
    """
    if ctx is None:
        return None
    if signal_lot(ctx, symbol, spot):
        return "name"
    return "market" if ctx.market_bottoming.get(governing_index(ctx, symbol)) else None


def live_ladder_spot(
    candidate: TradeCandidate, quote: OptionQuote, ctx: SizingContext | None
) -> float | None:
    """The underlying price the send-time ladder re-check uses (ruling 48).

    The fresh quote's ``underlying_price``; when the quote carries none (paper fallback greeks),
    the price ``approval._send_context`` fetched for this name (``ctx.spot_at_send``); else None.
    """
    if quote.underlying_price is not None and quote.underlying_price > 0:
        return float(quote.underlying_price)
    if ctx is not None:
        return ctx.spot_at_send.get(candidate.underlying)
    return None


def live_ladder_reason(
    candidate: TradeCandidate, quote: OptionQuote, ctx: SizingContext | None
) -> str | None:
    """The send-time ladder check: the card's frozen zone against the live underlying price.

    ``"scale_in_zone_not_reached"`` when the candidate's snapshot carries a zone and the live
    price is above its top, i.e. the underlying bounced after the card was made. The zone is the
    one frozen in the order snapshot; no bars are fetched at send time. CSPs only.
    """
    if candidate.strategy != Strategy.CASH_SECURED_PUT or candidate.sizing is None:
        return None
    zone = candidate.sizing.scale_in
    if zone is None or ctx is None or not active(ctx):
        return None
    if zone.bottoming_signal or candidate.sizing.bottoming == "name":
        return None  # opened above the zone on a name-level signal, validated at decision time
    spot = live_ladder_spot(candidate, quote, ctx)
    if spot is None:
        return None
    return "scale_in_zone_not_reached" if spot > zone.zone_high else None


def live_ladder_note(
    candidate: TradeCandidate, quote: OptionQuote, ctx: SizingContext | None
) -> str | None:
    """The order ``detail`` when the ladder could not be re-checked at send time, else None."""
    if candidate.strategy != Strategy.CASH_SECURED_PUT or candidate.sizing is None:
        return None
    if candidate.sizing.scale_in is None or ctx is None or not active(ctx):
        return None
    if candidate.sizing.scale_in.bottoming_signal or candidate.sizing.bottoming == "name":
        return None
    if live_ladder_spot(candidate, quote, ctx) is None:
        return "ladder not re-checked: no underlying price"
    return None


def sizing_note(
    ctx: SizingContext | None, symbol: str, pre: int, hard_max: int
) -> SizingNote | None:
    """The `SizingNote` for a CSP on *symbol* sized at most *pre* by capital (None: no context).

    ``floor_lot`` is left False: whoever accepts a lot under the guaranteed floor sets it.
    """
    if ctx is None:
        return None
    _, index = name_regime(ctx, symbol)
    factor = leverage_factor(ctx, symbol)
    return SizingNote(
        pre_regime_contracts=pre,
        regime=_effective_name_regime(ctx, symbol),
        regime_index=index,
        per_trade_cap=per_trade_cap(ctx, symbol, hard_max),
        budget_multiplier=multipliers(ctx, symbol)[0],
        leverage=factor,
        leverage_tier=leverage_tier(ctx, symbol) if factor is not None else None,
        ceiling_kind=ceiling_kind(ctx, symbol, hard_max, pre),
    )


def claude_cut(deterministic: int, suggested: int | None, backend: str | None) -> int:
    """The contract count to send after Claude's size suggestion: the deterministic size, or a
    smaller number Claude chose. The one place an LLM value reaches a size, and it can only lower.

    Returns *suggested* only when the review came from the Claude CLI (``backend == "cli"``: a
    local model's number is never applied), *suggested* is a plain integer (not a bool, a float or
    text) and ``0 <= suggested <= deterministic``. Everything else (a missing value, a negative, a
    number above the card, an unknown or absent backend) returns *deterministic*. ``0`` means "not
    now". Pure: takes plain values, imports nothing from the reasoning layer.
    """
    if backend != "cli":
        return deterministic
    if not isinstance(suggested, int) or isinstance(suggested, bool):
        return deterministic
    if not 0 <= suggested <= deterministic:
        return deterministic
    return suggested


def cut_applies(
    *, is_live: bool, zeroed_today: int, reviewed_today: int, cfg: ClaudeCutCfg
) -> tuple[bool, str | None]:
    """Whether a valid cut changes the size that is sent: ``(True, None)``, or ``(False, why)``.

    ``why`` is ``live_record_only`` (live and ``apply_live`` is off), ``paper_record_only`` (paper
    and ``apply_in_paper`` is off) or ``breaker``: Claude has already cut at least
    ``breaker_min`` auto CSPs to zero today (*zeroed_today*) and those are more than
    ``breaker_pct`` percent of the day's reviewed auto CSPs (*reviewed_today*). A zeroed candidate
    was necessarily reviewed, so a lost or low counter cannot hide a breach.
    """
    if is_live and not cfg.apply_live:
        return False, "live_record_only"
    if not is_live and not cfg.apply_in_paper:
        return False, "paper_record_only"
    if zeroed_today >= cfg.breaker_min:
        reviewed = max(reviewed_today, zeroed_today)
        if zeroed_today / reviewed * 100 > cfg.breaker_pct:
            return False, "breaker"
    return True, None


def with_claude_cut(
    note: SizingNote | None, deterministic: int, suggested: int, reason: str
) -> SizingNote:
    """*note* with Claude's number and reason on it (a candidate built with no sizing context gets
    a plain note: normal regime, capital allowed *deterministic* lots). Display and audit only."""
    base = note or SizingNote(
        pre_regime_contracts=deterministic,
        regime=MarketRegime.NORMAL,
        regime_index="SPY",
        per_trade_cap=deterministic,
        budget_multiplier=1.0,
    )
    return base.model_copy(update={"claude_suggested": suggested, "claude_reason": reason})


def hard_max_contracts() -> int:
    """``cash_secured_put.max_contracts`` from ``risk_limits.yaml`` (10 when absent)."""
    csp = get_config().risk.get("cash_secured_put") or {}
    return int(csp.get("max_contracts", 10))


def scaled_budget_fit(
    cand: TradeCandidate,
    ctx: SizingContext | None,
    account: AccountSnapshot,
    positions: list[PositionSnapshot],
) -> int | None:
    """The most contracts of *cand* that fit the regime-SCALED budgets right now (send time).

    ``None`` when there is nothing to re-fit (no context, not a CSP, the regime limits off, or
    the budgets are not scaled for this name). Budgets are seeded from *positions* with the
    unscaled caps, exactly as the sizer and the gate do. A candidate that was a guaranteed-floor
    lot is re-checked against the **unscaled** caps while the floor still has a lot left today,
    else against the scaled ones (so it fits nothing and is refused as ``regime_budget``).
    """
    if ctx is None or cand.strategy != Strategy.CASH_SECURED_PUT or not active(ctx):
        return None
    floor_lot = bool(cand.sizing and cand.sizing.floor_lot)
    ticker, book = multipliers(ctx, cand.underlying)
    if ticker == 1.0 and book == 1.0 and not floor_lot:
        return None
    cfg = get_config()
    vx = value_exposure()  # the value book, counted as the gate counts it (Part 5)
    caps = resolve_caps(
        account, cfg.risk, value_claim=vx.claim, csp_fraction=slow_breaker_fraction()
    )
    use = (
        caps
        if floor_lot and floor_left(ctx, cand.underlying, {}) > 0
        else scale_caps(caps, ticker=ticker, book=book)
    )
    sector_of = (cfg.universe.get("sectors") or {}).get

    def leverage_of(name: str) -> int:
        return leverage_factor(ctx, name) or 1

    budgets = seed_budgets(
        positions, sector_of, caps=caps, extra_exposure=vx.by_name, leverage_of=leverage_of
    )
    fit, _ = max_contracts(
        unit_collateral=cand.strike * 100.0,
        current_iv=cand.current_iv,
        dte=cand.dte,
        symbol=cand.underlying,
        sector=sector_of(cand.underlying),
        caps=use,
        budgets=budgets,
        hard_max=cand.contracts,
        leverage=leverage_of(cand.underlying),
    )
    return fit


def trim_for_send(
    cand: TradeCandidate, ctx: SizingContext | None, hard_max: int, budget_fit: int | None
) -> int:
    """The contract count to send a queued order at: the card's size, trimmed down, never up.

    For a CSP ``min(cand.contracts, per_trade_cap, budget_fit)`` (*budget_fit* is
    `scaled_budget_fit`, None when there is nothing to re-fit); anything else, and a missing
    context, keep the card's size. A result of zero means the regime now allows nothing: the
    caller leaves the order as it is and the gate refuses it with the regime's reason.
    """
    if ctx is None or cand.strategy != Strategy.CASH_SECURED_PUT:
        return cand.contracts
    n = min(cand.contracts, per_trade_cap(ctx, cand.underlying, hard_max, cand.sizing))
    if budget_fit is not None:
        n = min(n, budget_fit)
    return n


def _breakout_in_force(ctx: SizingContext | None, cand: TradeCandidate) -> CcBreakout | None:
    """The covered-call breakout that governs *cand*, or None (the rule is off, or none applies).

    Covered calls only (a roll or a put has none), with ``cc_timing.breakout.enabled`` on. The
    breakout comes from the context (the scan's fresh one) or, failing that, from the copy frozen
    on the candidate, which is how the send-time re-gate sees it without fetching bars.
    """
    if cand.strategy != Strategy.COVERED_CALL or cand.roll_from is not None:
        return None
    if not get_cc_timing_cfg().breakout.enabled:
        return None
    return (ctx.cc_breakout.get(cand.underlying.upper()) if ctx is not None else None) or (
        cand.cc_breakout
    )


def cc_timing_reasons(ctx: SizingContext | None, cand: TradeCandidate) -> list[str]:
    """Why a covered call on a name in an upside breakout is too close (spec section 17).

    ``"cc_breakout_strike_floor"`` when the strike is under the breakout's floor and
    ``"cc_breakout_delta"`` when its delta is over the cap: while a breakout lasts, a call is
    pushed out to a strike that clears both, and when nothing on the chain does, none is sold on
    the name that scan. Covered calls only: a roll or a put never gets a reason here. The
    breakout comes from the context (the scan's fresh one) or, failing that, from the copy
    frozen on the candidate, which is how the send-time re-gate sees it without fetching bars.

    **Not gated by** `active`: this is not a regime limit, so ``/regime off`` and
    ``regime.enabled: false`` leave it on; ``cc_timing.breakout.enabled: false`` switches it off.
    A missing delta is the generator's and the gate's own ``delta_missing``, not this rule's.
    """
    found = _breakout_in_force(ctx, cand)
    if found is None:
        return []
    reasons: list[str] = []
    if cand.strike < found.floor_strike - 1e-9:
        reasons.append("cc_breakout_strike_floor")
    if cand.delta is not None and abs(cand.delta) > found.delta_max + 1e-9:
        reasons.append("cc_breakout_delta")
    return reasons


def live_cc_delta_reason(
    candidate: TradeCandidate, quote: OptionQuote, ctx: SizingContext | None
) -> str | None:
    """The send-time breakout check against the FRESH quote: the live delta against the cap.

    ``"cc_breakout_delta"`` when a covered call carries a breakout (frozen on the card, or in
    *ctx*) and the live quote's delta is over its ``delta_max``: the call drifted toward the
    money between approval and send. The card's own delta is already held by `cc_timing_reasons`;
    this holds the number the order is about to be sent at, so the gate runs twice on the cap.
    A missing live delta triggers nothing (the live re-gate's delta handling stands: missing
    greeks degrade to the decision-time gate). Covered calls only; never a roll or a put.
    """
    found = _breakout_in_force(ctx, candidate)
    if found is None or quote.delta is None:
        return None
    return "cc_breakout_delta" if abs(quote.delta) > found.delta_max + 1e-9 else None


def live_bottoming_delta_reason(candidate: TradeCandidate, quote: OptionQuote) -> str | None:
    """The send-time delta cap of a name-level signal lot, against the FRESH quote.

    ``"bottoming_delta_too_high"`` when the card's frozen tag says it opened as a name-level
    signal lot (``sizing.bottoming == "name"``, the tag `vrp_waiver` reads at send time) and the
    live quote's ``abs(delta)`` is above ``bottoming.signal_delta_max``: the put drifted toward
    the money between approval and send. The card's own delta was held at decision time by
    `bottoming_guard`; this holds the number the order is about to go out at. The one-lot-per-N-
    sessions guard needs the fresh signals and stays decision-time only.

    Reads the tag on the card and nothing from a context, so it applies with no send-time
    context and under ``/regime off``: refusing a lot that drifted is only ever more
    conservative. A missing live delta triggers nothing (missing greeks degrade to the
    decision-time gate, as the other live delta checks do). Cash-secured puts only: never a
    covered call, a roll (the strategy or a roll origin), a market-eased lot (tag ``"market"``)
    or an ordinary ladder lot (no tag).
    """
    if candidate.strategy != Strategy.CASH_SECURED_PUT or candidate.roll_from is not None:
        return None
    if candidate.sizing is None or candidate.sizing.bottoming != "name" or quote.delta is None:
        return None
    if abs(quote.delta) > get_regime_cfg().bottoming.signal_delta_max + 1e-9:
        return "bottoming_delta_too_high"
    return None
