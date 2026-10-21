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

The regime limits switch off when the context is None, `/regime off` suspended it today, or
`regime.enabled` is false. The leveraged-ETF ceiling has its own switch and is **not** a regime
limit: it still applies when the regime is suspended or disabled (a ladder trigger on the name
still stresses its tier). Rolls, covered calls, closes and exits are never limited here: callers
apply these functions to cash-secured puts only.
"""

from __future__ import annotations

import math
from typing import Literal

from src.common.config import get_leveraged_sizing_cfg, get_regime_cfg
from src.common.schemas import MarketRegime, SizingContext, SizingNote

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


def multipliers(ctx: SizingContext | None, symbol: str) -> tuple[float, float]:
    """``(ticker, book)`` budget multipliers for *symbol*; ``(1.0, 1.0)`` when inactive.

    ``book`` follows the SPY regime (the total CSP allocation); ``ticker`` follows the name's
    regime (per-ticker and per-sector risk). Pass both to `capital.scale_caps`.
    """
    if ctx is None or not active(ctx):
        return 1.0, 1.0
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


def per_trade_cap(ctx: SizingContext | None, symbol: str, hard_max: int) -> int:
    """The most contracts one CSP on *symbol* may carry (ruling 35).

    ``hard_max`` when there is no context. Otherwise ``base = floor(hard_max x regime fraction)``
    (the fraction is 1.0 when the regime limits are off); zero when ``base`` is zero; for a
    leveraged ETF ``max(1, floor(hard_max x regime fraction x leverage fraction))`` with the
    leverage fraction of the name's tier; else ``base``.
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
    lf = get_leveraged_sizing_cfg().per_trade_fraction[leverage_tier(ctx, symbol)][factor]
    return max(1, _floor(hard_max * rf * lf))


def ceiling_kind(
    ctx: SizingContext | None, symbol: str, hard_max: int, pre: int
) -> Literal["regime_ceiling", "leveraged_ceiling"] | None:
    """Which factor brings *pre* contracts down to the per-trade ceiling, or None.

    ``"leveraged_ceiling"`` when the leveraged-ETF factor is what takes the ceiling below
    ``min(pre, regime base)``; ``"regime_ceiling"`` when the regime fraction does; None when the
    ceiling does not bind at all.
    """
    if ctx is None:
        return None
    cap = per_trade_cap(ctx, symbol, hard_max)
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
