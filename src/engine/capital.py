"""Capital arithmetic for the deterministic risk layer.

Three constraints, each in its proper unit — this module exists because one percentage
(`max_pct_per_ticker`) was previously asked to answer all three at once:

  * **Feasibility** — can the account pay for this? Measured in cash.
  * **Concentration** — is this too much of one name? Measured in *risk units*
    (``collateral x IV x sqrt(DTE/365)``), because share price is not a risk measure: a
    10-for-1 split would otherwise make a name tradeable overnight with identical risk.
  * **Deliberateness** — is this an outsized bet? Measured by an explicit, counted slot,
    against *cumulative* per-ticker collateral (the book plus the new lot, never the new lot
    alone). Cumulative is also what makes this the raw-collateral backstop for callers that
    cannot seed the risk-unit tallies from live IV.

Pure functions, no I/O, no config reads (callers pass the resolved ``risk`` dict).
``strategies/cash_secured_put.py`` sizes with ``max_contracts`` and
``engine/risk_engine.py`` gates with the same ``resolve_caps``/``seed_budgets``/``charge``
arithmetic and an inline copy of ``_fits``'s checks, so the generator and the gate can never
disagree about how big a position may be — that disagreement was the root cause of every CSP
above a ~$150 strike being unreachable. **Keep the two in step:** a change to ``_fits`` that
is not mirrored in ``risk_engine.validate_candidates`` (or vice versa) re-opens exactly that
gap.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Callable
from dataclasses import dataclass, field, replace

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
    # Tickers currently occupying a large-position slot — a SET, not a count: a slot belongs
    # to a ticker, not to a candidate, so a second candidate on an already-large name must
    # never consume a second slot. Adding an already-present symbol is a no-op, which is
    # exactly what makes this correct without a separate "did this just cross the threshold"
    # check — see ``charge`` and ``seed_budgets``.
    large_tickers: set[str] = field(default_factory=set)


def resolve_caps(account: AccountSnapshot, risk: dict, *, value_claim: float = 0.0) -> Caps:
    """Resolve config percentages into absolute dollar limits for this account.

    Order of application is fixed and deliberately not configurable: the cash reserve comes
    off first, and the CSP budget is a percentage of what remains. Expressing both against
    gross cash would let the two knobs contradict each other.

    *value_claim* (value book spec §9.3 item 1, revision 4; ``books.value_exposure().claim``)
    comes off excess liquidity before the reserve: the value book's whole contribution to it
    (its stock at (1 - maintenance) plus approved buys not yet filled), so the wheel is never
    handed the liquidity value stock bought with cash still appears to leave.
    """
    p = risk.get("portfolio", {})
    net_liq = max(0.0, account.net_liquidation)
    cash = max(0.0, account.excess_liquidity - max(0.0, value_claim))

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


def scale_caps(caps: Caps, *, ticker: float, book: float) -> Caps:
    """The caps with the market regime's CSP budgets scaled (spec section 5).

    ``book`` scales the total CSP allocation (``max_csp_collateral``); ``ticker`` scales the
    per-ticker and per-sector risk-unit budgets. **Only those three move.** The collateral caps
    (``max_ticker_collateral``, ``large_ticker_collateral``), the cash, and the large-position
    slot count are left alone, so the threshold at which a name needs a slot never shifts with
    the regime. Callers still seed their budgets with the *unscaled* caps and use the scaled
    ones only for the checks (the sizer and the gate both do).
    """
    return replace(
        caps,
        max_csp_collateral=caps.max_csp_collateral * book,
        max_ticker_risk=caps.max_ticker_risk * ticker,
        max_sector_risk=caps.max_sector_risk * ticker,
    )


def seed_budgets(
    positions: list[PositionSnapshot],
    sector_of: Callable[[str], str | None],
    iv_of: Callable[[str], float | None] | None = None,
    *,
    caps: Caps | None = None,
    extra_exposure: dict[str, float] | None = None,
) -> Budgets:
    """Seed running tallies from current positions.

    *extra_exposure* (value book spec §9.2, Part 5: ``books.value_exposure().by_name``) adds the
    value book's stock in a name to that name's collateral tally, so exposure is counted once
    across both books though the wheel's positions hold only its own shares.

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

    *caps*, when supplied, seeds ``large_tickers`` too: any symbol whose existing cumulative
    collateral already exceeds ``caps.max_ticker_collateral`` starts the cycle already
    occupying a large-position slot. Without this, a name that is *already* over the
    concentration cap purely from the current book — no new candidate has touched it yet —
    would let `max_large_positions` further names go large on top of it, silently exceeding
    the intended cap on concentrated bets. Both production callers (`risk_engine.
    validate_candidates`, `strategies.cash_secured_put`) already resolve `caps` before calling
    this, so pass it; keyword-only and optional only so existing direct callers/tests that
    don't care about slot seeding are unaffected.
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

    for key, exposure in (extra_exposure or {}).items():
        budgets.ticker_collateral[key] = budgets.ticker_collateral.get(key, 0.0) + exposure
    if caps is not None:
        for key, collateral in budgets.ticker_collateral.items():
            if collateral > caps.max_ticker_collateral:
                budgets.large_tickers.add(key)
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
    # Per-ticker collateral is CUMULATIVE: this lot on top of whatever the account already
    # holds in the same name. Comparing the marginal lot alone made both ticker-level brakes
    # blind to the book — a name already at the ceiling looked empty to every new candidate.
    cum_collateral = budgets.ticker_collateral.get(symbol, 0.0) + collateral

    if budgets.cash_used + collateral > caps.deployable_cash:
        return "cash"
    if budgets.csp_collateral + collateral > caps.max_csp_collateral:
        return "csp_budget"

    units = risk_units(collateral, current_iv, dte)
    if units is None:
        # No IV: fall back to the stricter raw-collateral cap.
        if cum_collateral > caps.max_ticker_collateral:
            return "ticker_collateral"
    else:
        if budgets.ticker_risk.get(symbol, 0.0) + units > caps.max_ticker_risk:
            return "ticker_risk"
        if sector and budgets.sector_risk.get(sector, 0.0) + units > caps.max_sector_risk:
            return "sector_risk"

    # Large-position slot: cumulative exposure in one name above the standard collateral cap
    # is refused unless a free slot is available, and must still sit under the hard
    # large-position ceiling. Measuring it cumulatively is also the raw-collateral backstop for
    # every caller that cannot seed the risk-unit tallies (no `iv_of` — the order-approval
    # re-gate, the single-ticker deep-dive, the CSP generator's sizer): whatever those paths
    # know about a candidate's IV, cumulative per-ticker collateral can never exceed
    # `max_pct_per_ticker_large`. A ticker that already occupies a slot (seeded from the
    # existing book, or claimed by an earlier candidate this cycle — see `charge`) needs no
    # NEW free slot to add another lot; only a ticker not yet counted as large does.
    if cum_collateral > caps.max_ticker_collateral:
        if (
            symbol not in budgets.large_tickers
            and len(budgets.large_tickers) >= caps.max_large_positions
        ):
            return "large_slot"
        if cum_collateral > caps.large_ticker_collateral:
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

    The large-position slot is marked used whenever this ticker's CUMULATIVE collateral
    (existing book + every lot charged against it so far, including this one) exceeds
    ``max_ticker_collateral`` — the same comparison ``_fits``/``validate_candidates`` use to
    *require* a free slot (fixed 2026-09-11; previously this compared only the candidate's own
    marginal collateral, so a chain of individually-small candidates on one ticker could cross
    the cap without ever registering as large — see STATUS.md's former "Remaining known
    issues"). Adding to a set rather than incrementing a counter means a second candidate on an
    already-large ticker is a no-op, not a second slot consumed.
    """
    cum_before = budgets.ticker_collateral.get(symbol, 0.0)
    collateral = unit_collateral * contracts
    budgets.cash_used += collateral
    budgets.csp_collateral += collateral
    budgets.ticker_collateral[symbol] = cum_before + collateral
    units = risk_units(collateral, current_iv, dte)
    if units is not None:
        budgets.ticker_risk[symbol] = budgets.ticker_risk.get(symbol, 0.0) + units
        if sector:
            budgets.sector_risk[sector] = budgets.sector_risk.get(sector, 0.0) + units
    if cum_before + collateral > caps.max_ticker_collateral:
        budgets.large_tickers.add(symbol)


# --- Capital release (value book spec revision 4, operator 2026-10-30) ---------------------------


@dataclass(frozen=True)
class ReleaseCandidate:
    """One wheel cash-secured put that might be closed to fund an approved value buy. Prices are
    per share; ``entry_credit`` is the roll chain's net credit (``chain_entry_credit_per_share``)."""

    key: str  # the contract, for logs and the close's idempotency
    underlying: str
    strike: float
    contracts: int
    entry_credit: float
    bid: float
    ask: float | None

    @property
    def mid(self) -> float | None:
        if self.ask is None or self.ask <= 0:
            return None
        return (self.bid + self.ask) / 2 if self.bid > 0 else self.ask

    @property
    def profit_pct(self) -> float | None:
        """Share of the entry credit kept by closing at mid now (the profit-take arithmetic)."""
        mid = self.mid
        if mid is None or self.entry_credit <= 0:
            return None
        return (1.0 - mid / self.entry_credit) * 100.0

    @property
    def released(self) -> float:
        """Collateral the close frees: strike x 100 x contracts."""
        return self.strike * 100.0 * self.contracts

    @property
    def given_up(self) -> float:
        """The premium still to earn that closing now forgoes: mid x 100 x contracts."""
        mid = self.mid
        return 0.0 if mid is None else mid * 100.0 * self.contracts


def release_reasons(
    c: ReleaseCandidate,
    release: dict,
    *,
    closes_today: int,
    released_today: float,
    net_liq: float,
) -> list[str]:
    """Why *c* may not be closed for capital, from its quote and the day's counts. Pure. Never
    at a loss: a close below ``min_profit_pct`` of the entry credit (0: breakeven) is refused."""
    reasons: list[str] = []
    mid = c.mid
    if mid is None:
        return ["release_no_quote"]
    ask = c.ask or 0.0
    if c.bid > 0 and (ask - c.bid) / mid * 100.0 > float(release.get("max_spread_pct", 25.0)):
        reasons.append("release_spread_too_wide")
    profit = c.profit_pct
    if profit is None or profit < float(release.get("min_profit_pct", 0.0)):
        reasons.append("release_at_loss")
    if closes_today >= int(release.get("max_closes_per_day", 4)):
        reasons.append("release_daily_cap")
    cap = net_liq * float(release.get("max_release_pct_per_day", 10.0)) / 100.0
    if released_today + c.released > cap:
        reasons.append("release_daily_notional")
    return reasons


def select_releases(
    eligible: list[ReleaseCandidate], needed: float, release: dict
) -> list[ReleaseCandidate]:
    """The fewest closes whose freed collateral covers *needed*, or ``[]`` when no allowed set
    does (never a partial release: nothing is closed for a buy that still could not be funded).

    Among sets of the smallest size: fewest closes under ``preferred_profit_pct``, then the least
    premium given up, then the most capital released per dollar given up. Candidates are the 20
    best by released per dollar given up, so the search stays small; at most
    ``max_closes_per_request`` closes. Deterministic: ties break on the contract key."""
    if needed <= 0:
        return []
    preferred = float(release.get("preferred_profit_pct", 25.0))
    limit = int(release.get("max_closes_per_request", 3))

    def ratio(c: ReleaseCandidate) -> float:
        return c.released / max(c.given_up, 0.01)

    pool = sorted(eligible, key=lambda c: (-ratio(c), c.key))[:20]
    for size in range(1, limit + 1):
        sets = [
            combo
            for combo in itertools.combinations(pool, size)
            if sum(c.released for c in combo) >= needed
        ]
        if sets:
            best = min(
                sets,
                key=lambda combo: (
                    sum(1 for c in combo if (c.profit_pct or 0.0) < preferred),
                    round(sum(c.given_up for c in combo), 2),
                    -sum(c.released for c in combo) / max(sum(c.given_up for c in combo), 0.01),
                    tuple(sorted(c.key for c in combo)),
                ),
            )
            return sorted(best, key=lambda c: c.key)
    return []
