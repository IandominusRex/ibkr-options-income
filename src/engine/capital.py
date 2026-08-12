"""Capital arithmetic for the deterministic risk layer.

Three constraints, each in its proper unit — this module exists because one percentage
(`max_pct_per_ticker`) was previously asked to answer all three at once:

  * **Feasibility** — can the account pay for this? Measured in cash.
  * **Concentration** — is this too much of one name? Measured in *risk units*
    (``collateral x IV x sqrt(DTE/365)``), because share price is not a risk measure: a
    10-for-1 split would otherwise make a name tradeable overnight with identical risk.
  * **Deliberateness** — is this an outsized bet? Measured by an explicit, counted slot.

Pure functions, no I/O, no config reads (callers pass the resolved ``risk`` dict). Both
``strategies/cash_secured_put.py`` and ``engine/risk_engine.py`` call ``max_contracts`` so
the generator and the gate can never disagree about how big a position may be — that
disagreement was the root cause of every CSP above a ~$150 strike being unreachable.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field

from src.common.market_hours import today_et
from src.common.schemas import AccountSnapshot, OptionRight, PositionSnapshot


def risk_units(collateral: float, current_iv: float | None, dte: int) -> float | None:
    """Capital at risk over the option's life: ``collateral x IV x sqrt(DTE/365)``.

    *current_iv* is a **percent** (28.5 means 28.5%), matching ``IVStats.current_iv``.
    Returns None when IV is unavailable or non-positive — callers must then fall back to a
    stricter raw-collateral cap rather than treating the position as risk-free.
    """
    if collateral <= 0 or dte <= 0:
        return None
    if current_iv is None or current_iv <= 0:
        return None
    return collateral * (current_iv / 100.0) * math.sqrt(dte / 365.0)


@dataclass(frozen=True)
class Caps:
    """Absolute limits resolved from config against one account snapshot."""

    deployable_cash: float
    max_csp_collateral: float
    max_ticker_risk: float
    max_sector_risk: float
    max_ticker_collateral: float
    max_large_positions: int
    large_ticker_collateral: float


@dataclass
class Budgets:
    """Running tallies, consumed greedily in score order by the gate."""

    ticker_risk: dict[str, float] = field(default_factory=dict)
    sector_risk: dict[str, float] = field(default_factory=dict)
    ticker_collateral: dict[str, float] = field(default_factory=dict)
    csp_collateral: float = 0.0
    cash_used: float = 0.0
    large_slots_used: int = 0


def resolve_caps(account: AccountSnapshot, risk: dict) -> Caps:
    """Resolve config percentages into absolute dollar limits for this account.

    Order of application is fixed and deliberately not configurable: the cash reserve comes
    off first, and the CSP budget is a percentage of what remains. Expressing both against
    gross cash would let the two knobs contradict each other.
    """
    p = risk.get("portfolio", {})
    net_liq = max(0.0, account.net_liquidation)
    cash = max(0.0, account.excess_liquidity)

    reserve = max(
        cash * float(p.get("cash_reserve_pct", 20.0)) / 100.0,
        float(p.get("cash_reserve_absolute", 0.0)),
    )
    deployable = max(0.0, cash - reserve)

    return Caps(
        deployable_cash=deployable,
        max_csp_collateral=deployable
        * float(p.get("max_csp_allocation_pct_of_deployable", 100.0))
        / 100.0,
        max_ticker_risk=net_liq * float(p.get("max_risk_units_per_ticker_pct", 5.0)) / 100.0,
        max_sector_risk=net_liq * float(p.get("max_risk_units_per_sector_pct", 25.0)) / 100.0,
        max_ticker_collateral=net_liq * float(p.get("max_collateral_per_ticker_pct", 10.0)) / 100.0,
        max_large_positions=int(p.get("max_large_positions", 1)),
        large_ticker_collateral=net_liq * float(p.get("max_pct_per_ticker_large", 25.0)) / 100.0,
    )


def seed_budgets(
    positions: list[PositionSnapshot],
    sector_of: Callable[[str], str | None],
    iv_of: Callable[[str], float | None] | None = None,
) -> Budgets:
    """Seed running tallies from current positions.

    A short put contributes its assignment liability (strike x 100 x |contracts|), not the
    option's tiny market value — matching exactly how a *new* CSP candidate is charged, so
    existing and proposed positions share one consistent budget (N5). Everything else is
    measured at |market value|.

    Risk units ARE seeded — for **option** positions, and only when the caller supplies
    *iv_of*, a per-symbol IV lookup (percent, e.g. 28.5). Without it the risk-unit tallies
    would stay empty while `_fits`/`validate_candidates` measured new candidates against
    them, so existing exposure would count for nothing on the (common) path where the
    candidate's own IV is known. Callers that already hold IV for the whole portfolio (the
    full scan sweep, the capacity report) pass it; callers that would have to buy it with a
    new network round-trip on a latency-sensitive path (the order-approval re-validation
    gate, a single-ticker deep-dive) do not, and lean on the raw-collateral tally below.

    Stock positions get no risk-unit seeding — they have no natural DTE — and neither does an
    option whose IV can't be resolved or whose expiry has passed. Those, and every caller that
    omits *iv_of*, are covered by ``ticker_collateral``, which is always seeded.
    """
    budgets = Budgets()
    for p in positions:
        key = p.underlying or p.symbol
        is_short_put = (
            p.sec_type == "OPT" and p.right == OptionRight.PUT and p.position < 0 and p.strike
        )
        if is_short_put:
            exposure = (p.strike or 0.0) * 100.0 * abs(p.position)
            budgets.csp_collateral += exposure
        else:
            exposure = abs(p.market_value or 0.0)
        budgets.ticker_collateral[key] = budgets.ticker_collateral.get(key, 0.0) + exposure

        if iv_of is None or p.sec_type != "OPT" or p.expiry is None:
            continue
        dte = (p.expiry - today_et()).days
        if dte <= 0:
            continue
        units = risk_units(exposure, iv_of(key), dte)
        if units is None:
            continue
        budgets.ticker_risk[key] = budgets.ticker_risk.get(key, 0.0) + units
        sector = sector_of(key)
        if sector:
            budgets.sector_risk[sector] = budgets.sector_risk.get(sector, 0.0) + units
    return budgets


def _fits(
    n: int,
    unit_collateral: float,
    current_iv: float | None,
    dte: int,
    symbol: str,
    sector: str | None,
    caps: Caps,
    budgets: Budgets,
) -> str:
    """Return the name of the first constraint ``n`` contracts would breach, or ""."""
    collateral = unit_collateral * n

    if budgets.cash_used + collateral > caps.deployable_cash:
        return "cash"
    if budgets.csp_collateral + collateral > caps.max_csp_collateral:
        return "csp_budget"

    units = risk_units(collateral, current_iv, dte)
    if units is None:
        # No IV: fall back to the stricter raw-collateral cap.
        if budgets.ticker_collateral.get(symbol, 0.0) + collateral > caps.max_ticker_collateral:
            return "ticker_collateral"
    else:
        if budgets.ticker_risk.get(symbol, 0.0) + units > caps.max_ticker_risk:
            return "ticker_risk"
        if sector and budgets.sector_risk.get(sector, 0.0) + units > caps.max_sector_risk:
            return "sector_risk"

    # Large-position slot: a position exceeding the standard collateral cap needs a free slot
    # and must still sit under the hard large-position ceiling.
    if collateral > caps.max_ticker_collateral:
        if budgets.large_slots_used >= caps.max_large_positions:
            return "large_slot"
        if collateral > caps.large_ticker_collateral:
            return "large_ceiling"
    return ""


def max_contracts(
    *,
    unit_collateral: float,
    current_iv: float | None,
    dte: int,
    symbol: str,
    sector: str | None,
    caps: Caps,
    budgets: Budgets,
    hard_max: int,
) -> tuple[int, str]:
    """Largest contract count that fits every constraint, and what bound it.

    Returns ``(contracts, binding)``. ``binding`` is the name of the constraint that stopped
    it growing, or ``""`` when ``hard_max`` was reached with room to spare. ``contracts == 0``
    means not even one lot fits, and ``binding`` names why — which is the message an operator
    can actually act on.

    This replaces "size to the maximum affordable, then let the gate reject": the gate
    rejected rather than trimmed, so any position whose *maximum* size breached a cap was
    refused entirely even when one lot would have fitted comfortably.
    """
    if unit_collateral <= 0 or hard_max < 1:
        return 0, "invalid"
    best = 0
    binding = ""
    for n in range(1, hard_max + 1):
        breach = _fits(n, unit_collateral, current_iv, dte, symbol, sector, caps, budgets)
        if breach:
            binding = breach
            break
        best = n
    if best == 0:
        return 0, binding or "cash"
    return best, binding


def charge(
    *,
    contracts: int,
    unit_collateral: float,
    current_iv: float | None,
    dte: int,
    symbol: str,
    sector: str | None,
    caps: Caps,
    budgets: Budgets,
) -> None:
    """Consume budget for an accepted candidate so later ones see reduced headroom.

    Mutates *budgets* in place. Mirrors the greedy consumption the risk engine has always
    done, extended to the risk-unit tallies and the large-position slot.
    """
    collateral = unit_collateral * contracts
    budgets.cash_used += collateral
    budgets.csp_collateral += collateral
    budgets.ticker_collateral[symbol] = budgets.ticker_collateral.get(symbol, 0.0) + collateral
    units = risk_units(collateral, current_iv, dte)
    if units is not None:
        budgets.ticker_risk[symbol] = budgets.ticker_risk.get(symbol, 0.0) + units
        if sector:
            budgets.sector_risk[sector] = budgets.sector_risk.get(sector, 0.0) + units
    if collateral > caps.max_ticker_collateral:
        budgets.large_slots_used += 1
