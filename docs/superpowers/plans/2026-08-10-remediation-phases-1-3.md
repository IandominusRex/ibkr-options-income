# Trading-System Remediation (Phases 1–3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the deterministic layer trade its intended universe at the account's real size for economically correct reasons, give it the ability to reduce risk unattended, and validate the execution path against a live paper broker.

**Architecture:** Three sequential phases. Phase 1 replaces the collateral-based concentration model with a risk-unit model plus a shared headroom helper used by both the generator and the gate, and promotes the existing variance-risk-premium floor from display to gate. Phase 2 adds loss-side exits, a kill switch that can see mark-to-market losses, and a four-rung autonomy ladder. Phase 3 answers the five open live-broker questions and removes dead subsystems.

**Tech Stack:** Python 3.12, Pydantic v2, SQLAlchemy 2.0 + SQLite, `ib_async`, pytest, ruff, mypy.

**Source spec:** `docs/superpowers/specs/2026-08-10-remediation-and-ios-app-design.md`

## Global Constraints

- Python ≥ 3.12. Type-hint everything. `ruff check .` and `mypy src` must pass at every commit.
- **The fence is absolute.** Nothing under `src/claude/` may be imported by `engine/`, `execution/`, or `strategies/`. `tests/test_eval_skills.py` asserts this — keep it green.
- **The Rules Engine is the only path to an order.** No task may add an LLM input to a gate, weight, or contract count.
- `src/analytics/fair_value.py` stays deterministic-tier: it may read technicals, IV, fundamentals, and Black-Scholes only. Promoting it to a gate does not change this.
- All tunables live in `config/risk_limits.yaml` or `config/settings.yaml`. No magic numbers in code.
- Option premiums are **per share**; multiply by 100 for contract value.
- Money and quantities are explicit. `IVStats.current_iv` is a **percent** (28.5 means 28.5%), not a fraction.
- Run `python -m pytest -q` before every commit. All 1,088 existing tests must stay green.
- After any code change, update the docs the CLAUDE.md table maps to. Each task names its doc updates explicitly.
- Never run a threaded scheduler in the same process as an `ib_async` loop.
- One clientId per process. No task may add a new IBKR connection.

---

## File Structure

**Created:**

| Path | Responsibility |
|---|---|
| `src/engine/capital.py` | Risk-unit arithmetic, resolved caps, and the single `max_contracts` helper shared by generator and gate. Pure functions; no I/O. |
| `scripts/capacity_report.py` | Answers "what can this system trade today, and what binds first" for every universe symbol. |
| `tests/test_capital.py` | Unit tests for `capital.py`. |
| `tests/test_account_sizing.py` | Property tests across account sizes — the regression class that would have caught D1 and D2. |
| `tests/test_loss_exits.py` | Loss-side exit behaviour. |
| `tests/test_autonomy.py` | Autonomy ladder and promotion gates. |
| `docs/live-validation-2026-08.md` | Recorded answers to the five live-broker questions. |

**Modified:**

| Path | Change |
|---|---|
| `src/common/schemas.py` | Add `TradeCandidate.current_iv`; add `AutonomyLevel` enum. |
| `src/engine/risk_engine.py` | Replace collateral concentration with risk units via `capital.py`; add the fair-value gate. |
| `src/strategies/cash_secured_put.py` | Size to headroom instead of to maximum affordable. |
| `src/strategies/covered_call.py` | Use campaign-adjusted cost basis; add the fair-value gate. |
| `src/strategies/_evaluation.py` | Add `REASON_BELOW_FAIR_VALUE`, `REASON_NO_HEADROOM`. |
| `src/analytics/fair_value.py` | Make `_min_credit` public as `min_credit_for`. |
| `src/analytics/iv.py` | Interpolate live IV to constant 30-day maturity before ranking. |
| `src/storage/campaigns.py` | Add `adjusted_cost_basis_for(symbol)` reader. |
| `src/execution/profit_take.py` | Add `check_loss_exits`; make auto-close independent of autonomy level. |
| `src/execution/circuit_breakers.py` | Add mark-based and drawdown breakers. |
| `src/storage/system_settings.py` | Autonomy level accessors; NLV high-water mark. |
| `src/strategies/rolling.py` | Defensive-roll economics; `date_cls.today()` → `today_et()`. |
| `src/monitor/triggers.py` | Add `check_manage_at_dte`. |
| `src/notify/formatters.py` | Labels for the new reason codes; autonomy in `/status`. |
| `src/notify/approval_service.py` | `/autonomy` command replacing `/mode`. |
| `config/risk_limits.yaml`, `config/settings.yaml` | New keys per phase. |
| `ARCHITECTURE.md`, `STATUS.md`, `README.md`, `SETUP.md` | Per the CLAUDE.md doc-update table. |

**Deleted (Phase 3):** `src/claude/skills/`, `src/claude/eval/metrics.py`, `src/common/profile.py`, `config/profiles/`, `scripts/propose_skill.py`, `scripts/skills.py`, `scripts/evaluate_verdicts.py`.

### Deliberate simplifications against the spec

Two places where implementation is simpler than §3–§9 describe. Both preserve the spec's intent; both are called out so a reviewer can reject them if they disagree.

1. **`min_credit_edge_pct` stays under `ideal_zone`** rather than moving to the `income` block. The spec's stated reason for moving it was "so display and gate can never diverge" — but the gate consumes `candidate.ideal.min_credit`, which is *derived* from that same key, so a single source already holds. Moving it is churn without benefit.
2. **No per-cycle `position_snapshots` writes.** The spec proposed this to feed the mark-based breaker. It is unnecessary: the intraday loop already holds live `positions` with `unrealized_pnl`, and the prior-day baseline is already available via `load_latest_position_snapshot(before=today)`. `PositionSnapshotRow` also carries `UniqueConstraint("snapshot_date")`, so per-cycle writes would require a schema change. Deferred to Phase 5, where the API genuinely needs it.

---

# Phase 1 — Capital and income

### Task 1: Risk-unit arithmetic and resolved caps

**Files:**
- Create: `src/engine/capital.py`
- Create: `tests/test_capital.py`

**Interfaces:**
- Consumes: `AccountSnapshot`, `PositionSnapshot` from `src.common.schemas`.
- Produces:
  - `risk_units(collateral: float, current_iv: float | None, dte: int) -> float | None`
  - `@dataclass(frozen=True) Caps` with fields `max_ticker_risk: float`, `max_sector_risk: float`, `max_ticker_collateral: float`, `max_csp_collateral: float`, `deployable_cash: float`, `max_large_positions: int`, `large_ticker_collateral: float`
  - `@dataclass Budgets` with fields `ticker_risk: dict[str, float]`, `sector_risk: dict[str, float]`, `ticker_collateral: dict[str, float]`, `csp_collateral: float`, `cash_used: float`, `large_slots_used: int`
  - `resolve_caps(account: AccountSnapshot, risk: dict) -> Caps`
  - `seed_budgets(positions: list[PositionSnapshot], sector_of: Callable[[str], str | None]) -> Budgets`
  - `max_contracts(*, unit_collateral: float, current_iv: float | None, dte: int, symbol: str, sector: str | None, caps: Caps, budgets: Budgets, hard_max: int) -> tuple[int, str]` — returns `(contracts, binding)`; `binding` is `""` when nothing bound below `hard_max`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_capital.py
"""Unit tests for src/engine/capital.py — risk units, caps, and headroom sizing."""

from __future__ import annotations

import pytest

from src.common.schemas import AccountSnapshot, OptionRight, PositionSnapshot
from src.engine.capital import (
    Budgets,
    Caps,
    max_contracts,
    resolve_caps,
    risk_units,
    seed_budgets,
)

RISK = {
    "portfolio": {
        "cash_reserve_pct": 20.0,
        "cash_reserve_absolute": 10000,
        "max_csp_allocation_pct_of_deployable": 100.0,
        "max_risk_units_per_ticker_pct": 5.0,
        "max_risk_units_per_sector_pct": 25.0,
        "max_collateral_per_ticker_pct": 10.0,
        "max_large_positions": 1,
        "max_pct_per_ticker_large": 25.0,
    }
}


def _account(net_liq=300_000.0, cash=100_000.0):
    return AccountSnapshot(
        account="DU1",
        net_liquidation=net_liq,
        total_cash=cash,
        buying_power=cash,
        maintenance_margin=0.0,
        excess_liquidity=cash,
    )


def test_risk_units_scales_collateral_by_vol_and_horizon():
    # META-like: $65,000 collateral, 35% IV, 30 DTE -> 65000 * 0.35 * sqrt(30/365)
    assert risk_units(65_000.0, 35.0, 30) == pytest.approx(6520.0, abs=5.0)


def test_risk_units_makes_a_cheap_high_vol_position_comparable():
    # MARA-like: $15,000 collateral at 110% IV is NOT 4x smaller than META in risk terms.
    meta = risk_units(65_000.0, 35.0, 30)
    mara = risk_units(15_000.0, 110.0, 30)
    assert meta is not None and mara is not None
    assert 0.5 < mara / meta < 1.0


def test_risk_units_returns_none_without_iv():
    assert risk_units(65_000.0, None, 30) is None
    assert risk_units(65_000.0, 0.0, 30) is None


def test_resolve_caps_subtracts_reserve_before_the_csp_budget():
    caps = resolve_caps(_account(), RISK)
    # reserve = max(20% of 100k, 10k) = 20k -> deployable 80k, budget 100% of that
    assert caps.deployable_cash == pytest.approx(80_000.0)
    assert caps.max_csp_collateral == pytest.approx(80_000.0)


def test_resolve_caps_reserve_uses_the_absolute_floor_when_larger():
    caps = resolve_caps(_account(cash=20_000.0), RISK)
    # reserve = max(20% of 20k = 4k, 10k) = 10k -> deployable 10k
    assert caps.deployable_cash == pytest.approx(10_000.0)


def test_seed_budgets_charges_short_puts_at_strike_collateral():
    positions = [
        PositionSnapshot(
            symbol="AAPL  260918P00200000",
            sec_type="OPT",
            position=-2,
            avg_cost=500.0,
            right=OptionRight.PUT,
            strike=200.0,
            underlying="AAPL",
            market_value=-900.0,
        )
    ]
    budgets = seed_budgets(positions, lambda s: "tech")
    assert budgets.csp_collateral == pytest.approx(40_000.0)
    assert budgets.ticker_collateral["AAPL"] == pytest.approx(40_000.0)


def test_max_contracts_trims_to_the_binding_constraint_instead_of_rejecting():
    caps = resolve_caps(_account(), RISK)
    budgets = seed_budgets([], lambda s: "tech")
    # AAPL 230 strike -> $23,000/contract. Risk cap = 5% of 300k = $15,000 risk units.
    # One contract = 23000 * 0.28 * sqrt(30/365) = ~1,847 risk units, so risk is not binding;
    # cash (80k deployable) allows 3.
    n, binding = max_contracts(
        unit_collateral=23_000.0,
        current_iv=28.0,
        dte=30,
        symbol="AAPL",
        sector="tech",
        caps=caps,
        budgets=budgets,
        hard_max=10,
    )
    assert n == 3
    assert binding == "cash"


def test_max_contracts_allows_one_lot_of_a_high_priced_name():
    """A $65k META put must not be rejected merely for being expensive (D1)."""
    caps = resolve_caps(_account(), RISK)
    budgets = seed_budgets([], lambda s: "tech")
    n, _ = max_contracts(
        unit_collateral=65_000.0,
        current_iv=35.0,
        dte=30,
        symbol="META",
        sector="tech",
        caps=caps,
        budgets=budgets,
        hard_max=10,
    )
    assert n == 1


def test_max_contracts_consumes_the_large_slot_and_refuses_a_second():
    caps = resolve_caps(_account(), RISK)
    budgets = seed_budgets([], lambda s: "tech")
    budgets.large_slots_used = 1  # slot already taken
    n, binding = max_contracts(
        unit_collateral=65_000.0,  # 21.7% of net liq -> needs the large slot
        current_iv=35.0,
        dte=30,
        symbol="META",
        sector="tech",
        caps=caps,
        budgets=budgets,
        hard_max=10,
    )
    assert n == 0
    assert binding == "large_slot"


def test_max_contracts_falls_back_to_collateral_when_iv_is_missing():
    caps = resolve_caps(_account(), RISK)
    budgets = seed_budgets([], lambda s: "tech")
    # No IV -> stricter raw-collateral cap of 10% of 300k = $30,000
    n, binding = max_contracts(
        unit_collateral=23_000.0,
        current_iv=None,
        dte=30,
        symbol="AAPL",
        sector="tech",
        caps=caps,
        budgets=budgets,
        hard_max=10,
    )
    assert n == 1
    assert binding == "ticker_collateral"


def test_max_contracts_returns_zero_when_nothing_fits():
    caps = resolve_caps(_account(cash=5_000.0), RISK)
    budgets = seed_budgets([], lambda s: "tech")
    n, binding = max_contracts(
        unit_collateral=23_000.0,
        current_iv=28.0,
        dte=30,
        symbol="AAPL",
        sector="tech",
        caps=caps,
        budgets=budgets,
        hard_max=10,
    )
    assert n == 0
    assert binding == "cash"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_capital.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.engine.capital'`

- [ ] **Step 3: Implement `src/engine/capital.py`**

```python
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

    reserve = max(cash * float(p.get("cash_reserve_pct", 20.0)) / 100.0,
                  float(p.get("cash_reserve_absolute", 0.0)))
    deployable = max(0.0, cash - reserve)

    return Caps(
        deployable_cash=deployable,
        max_csp_collateral=deployable
        * float(p.get("max_csp_allocation_pct_of_deployable", 100.0))
        / 100.0,
        max_ticker_risk=net_liq * float(p.get("max_risk_units_per_ticker_pct", 5.0)) / 100.0,
        max_sector_risk=net_liq * float(p.get("max_risk_units_per_sector_pct", 25.0)) / 100.0,
        max_ticker_collateral=net_liq
        * float(p.get("max_collateral_per_ticker_pct", 10.0))
        / 100.0,
        max_large_positions=int(p.get("max_large_positions", 1)),
        large_ticker_collateral=net_liq * float(p.get("max_pct_per_ticker_large", 25.0)) / 100.0,
    )


def seed_budgets(
    positions: list[PositionSnapshot], sector_of: Callable[[str], str | None]
) -> Budgets:
    """Seed running tallies from current positions.

    A short put contributes its assignment liability (strike x 100 x |contracts|), not the
    option's tiny market value — matching exactly how a *new* CSP candidate is charged, so
    existing and proposed positions share one consistent budget (N5). Everything else is
    measured at |market value|.

    Risk units cannot be seeded from a position snapshot (it carries no IV), so existing
    positions charge the raw-collateral tally only. This is conservative: it can refuse a new
    position, never wrongly admit one.
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
        sector = sector_of(key)
        if sector:
            budgets.sector_risk.setdefault(sector, 0.0)
    return budgets


def _fits(n: int, unit_collateral: float, current_iv: float | None, dte: int,
          symbol: str, sector: str | None, caps: Caps, budgets: Budgets) -> str:
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_capital.py -q`
Expected: PASS (11 tests)

- [ ] **Step 5: Lint and type-check**

Run: `ruff check src/engine/capital.py tests/test_capital.py && ruff format src/engine/capital.py tests/test_capital.py && mypy src/engine/capital.py`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add src/engine/capital.py tests/test_capital.py
git commit -m "feat(engine): risk-unit capital model with shared headroom sizing

Adds risk_units (collateral x IV x sqrt(DTE/365)) so a \$65k META put and a
\$15k MARA put are compared in the unit that matters rather than by share
price, plus resolve_caps/seed_budgets/max_contracts/charge as the single
sizing helper both the CSP generator and the risk gate will call.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Carry IV on the candidate

**Files:**
- Modify: `src/common/schemas.py` (TradeCandidate)
- Modify: `src/strategies/cash_secured_put.py:177-205`
- Modify: `src/strategies/covered_call.py:190-218`
- Test: `tests/test_strategies.py`

**Interfaces:**
- Consumes: `capital.risk_units` from Task 1, which needs a percent IV.
- Produces: `TradeCandidate.current_iv: float | None` — IV percent at scan time, sourced from `IVStats.current_iv`. Every later task that computes risk units reads this field.

**Why:** `TradeCandidate` carries `iv_rank`, `vrp`, and `iv_rv_ratio` but not the IV level itself, so the gate cannot compute risk units without it.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_strategies.py — append
def test_candidates_carry_current_iv_for_risk_unit_sizing(monkeypatch):
    """The gate computes risk units from IV, so the generator must record it."""
    from src.common.schemas import IVStats
    from src.strategies.cash_secured_put import screen_csp_candidates

    iv_stats = IVStats(symbol="AAPL", current_iv=28.5, iv_rank=55.0, hv_30=22.0)
    result = screen_csp_candidates(
        "AAPL", _put_chain(), _account(), iv_stats, _tech(), _fund()
    )
    all_cands = result.passed + [c for c, _ in result.rejected]
    assert all_cands, "fixture should produce at least one contract"
    assert all(c.current_iv == 28.5 for c in all_cands)
```

Note: `_put_chain`, `_account`, `_tech`, `_fund` are existing helpers in `tests/test_strategies.py`. Read the top of that file and reuse them; do not create new ones.

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_strategies.py::test_candidates_carry_current_iv_for_risk_unit_sizing -q`
Expected: FAIL — `AttributeError` or `assert None == 28.5`

- [ ] **Step 3: Add the field and populate it**

In `src/common/schemas.py`, inside `TradeCandidate`, directly after the `iv_rank` field:

```python
    # IV level (percent, e.g. 28.5) at scan time — distinct from iv_rank, which is a
    # percentile. Required by engine/capital.risk_units to size concentration in risk
    # units rather than raw collateral.
    current_iv: float | None = None
```

In `src/strategies/cash_secured_put.py`, inside the `TradeCandidate(...)` construction, after `iv_rank=iv_stats.iv_rank,`:

```python
            current_iv=iv_stats.current_iv,
```

In `src/strategies/covered_call.py`, make the identical addition after `iv_rank=iv_stats.iv_rank,`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_strategies.py -q`
Expected: PASS

- [ ] **Step 5: Update docs**

In `ARCHITECTURE.md`, find the `src/common/schemas.py` data-flow section listing `TradeCandidate` fields and add `current_iv` with the description "IV percent at scan time; feeds risk-unit concentration sizing."

- [ ] **Step 6: Commit**

```bash
git add src/common/schemas.py src/strategies/cash_secured_put.py src/strategies/covered_call.py tests/test_strategies.py ARCHITECTURE.md
git commit -m "feat(schemas): carry current_iv on TradeCandidate

The risk gate needs an IV level to size concentration in risk units;
the candidate previously carried only iv_rank (a percentile).

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Size CSPs to headroom instead of to maximum affordable

**Files:**
- Modify: `src/strategies/cash_secured_put.py:96-145`
- Modify: `src/strategies/_evaluation.py` (add reason code)
- Test: `tests/test_strategies.py`

**Interfaces:**
- Consumes: `capital.resolve_caps`, `capital.seed_budgets`, `capital.max_contracts` (Task 1); `TradeCandidate.current_iv` (Task 2).
- Produces: `REASON_NO_HEADROOM = "no_headroom"` in `_evaluation.py`. `screen_csp_candidates` gains a keyword-only `positions: list[PositionSnapshot] | None = None` parameter.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_strategies.py — append
def test_csp_sizing_trims_to_headroom_rather_than_maxing_out():
    """D1: sizing must not propose a lot the gate will reject outright."""
    from src.common.schemas import IVStats
    from src.strategies.cash_secured_put import screen_csp_candidates

    account = _account(net_liq=300_000.0, cash=100_000.0)
    iv_stats = IVStats(symbol="AAPL", current_iv=28.0, iv_rank=55.0, hv_30=22.0)
    result = screen_csp_candidates(
        "AAPL", _put_chain(), account, iv_stats, _tech(), _fund(), positions=[]
    )
    for cand in result.passed:
        # deployable cash = 100k - max(20k, 10k) = 80k
        assert cand.collateral <= 80_000.0


def test_csp_high_priced_name_is_sized_to_one_lot_not_rejected():
    """A $650 strike must yield a 1-lot candidate, not a 0-lot rejection."""
    from src.common.schemas import IVStats
    from src.strategies.cash_secured_put import screen_csp_candidates

    account = _account(net_liq=300_000.0, cash=100_000.0)
    iv_stats = IVStats(symbol="META", current_iv=35.0, iv_rank=60.0, hv_30=28.0)
    result = screen_csp_candidates(
        "META", _put_chain(strike=650.0), account, iv_stats, _tech(), _fund(), positions=[]
    )
    sized = result.passed + [c for c, _ in result.rejected]
    assert sized, "expected a candidate to be produced"
    assert all(c.contracts == 1 for c in sized)
```

Add `META` to the `would_own` list used by the test fixture config, or monkeypatch `get_config().universe["would_own"]` to include it — follow whichever pattern `tests/test_strategies.py` already uses.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_strategies.py -k headroom -q`
Expected: FAIL — `TypeError: screen_csp_candidates() got an unexpected keyword argument 'positions'`

- [ ] **Step 3: Add the reason code**

In `src/strategies/_evaluation.py`, after `REASON_INSUFFICIENT_CASH`:

```python
REASON_NO_HEADROOM = "no_headroom"
```

- [ ] **Step 4: Rewrite the sizing block**

In `src/strategies/cash_secured_put.py`, add to the imports:

```python
from src.common.schemas import PositionSnapshot
from src.engine.capital import Budgets, max_contracts, resolve_caps, seed_budgets
from src.strategies._evaluation import REASON_NO_HEADROOM
```

Change the signature to add a keyword-only parameter:

```python
def screen_csp_candidates(
    symbol: str,
    quotes: list[OptionQuote],
    account: AccountSnapshot,
    iv_stats: IVStats,
    tech_stats: TechnicalStats,
    fund_stats: FundamentalStats,
    *,
    positions: list[PositionSnapshot] | None = None,
) -> ScreenResult:
```

Replace lines 96-100 (the `max_contracts`/`max_csp_pct` config reads) with:

```python
    hard_max: int = csp_cfg.get("max_contracts", 10)
    caps = resolve_caps(account, risk)
    sector_of = cfg.universe.get("sectors", {}).get
    budgets: Budgets = seed_budgets(positions or [], sector_of)
    sector = sector_of(symbol)
```

Replace the sizing block (lines 135-145, from `per_contract = quote.strike * 100` through `collateral = quote.strike * contracts * 100`) with:

```python
        per_contract = quote.strike * 100
        if per_contract <= 0:
            continue
        # Size to the binding constraint rather than to the maximum affordable lot. The gate
        # rejects rather than trims, so proposing the max meant any position whose *largest*
        # size breached a cap was refused entirely — even when one lot fitted comfortably (D1).
        contracts, binding = max_contracts(
            unit_collateral=per_contract,
            current_iv=iv_stats.current_iv,
            dte=dte,
            symbol=symbol,
            sector=sector,
            caps=caps,
            budgets=budgets,
            hard_max=hard_max,
        )
        if contracts < 1:
            reasons.append(
                REASON_INSUFFICIENT_CASH if binding == "cash" else REASON_NO_HEADROOM
            )
            contracts = 1  # display a 1-lot; the reason records that it does not fit

        collateral = quote.strike * contracts * 100
```

- [ ] **Step 5: Update the caller**

In `src/orchestrator/scan.py`, find the `screen_csp_candidates(` call (near line 1254) and pass positions:

```python
            csp_screen = screen_csp_candidates(
                symbol, quotes, account, iv_stats, tech_stats, fund_stats, positions=positions
            )
```

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS — all tests including the two new ones.

- [ ] **Step 7: Add the reason label**

In `src/notify/formatters.py`, find `_REJECT_REASON_LABELS` and add:

```python
    "no_headroom": "no room under the concentration or budget caps",
```

- [ ] **Step 8: Write the failing test for the share-route fallback**

```python
# tests/test_output_fidelity.py — append
def test_cash_blocked_csp_names_the_share_entry_level():
    """A rejection should offer the other route to the same exposure, not just say no."""
    from src.common.schemas import IdealZone, OptionRight
    from src.notify.formatters import format_assessed_contracts
    from src.common.schemas import AssessedContract, AssessmentStage

    zone = IdealZone(
        symbol="META", right=OptionRight.PUT, dte=30, spot=700.0, buy_below=612.0
    )
    cand = _csp_candidate(underlying="META", strike=650.0, contracts=1).model_copy(
        update={"ideal": zone}
    )
    assessed = [
        AssessedContract(
            candidate=cand, stage=AssessmentStage.GENERATOR, reasons=["insufficient_cash"]
        )
    ]
    text = format_assessed_contracts(assessed)
    assert "612" in text, "the share entry level must be surfaced when cash blocks the CSP"
```

Reuse `_csp_candidate` from `tests/test_engine.py` by importing it, or replicate its
construction locally — follow whichever pattern `tests/test_output_fidelity.py` already uses.

- [ ] **Step 9: Run to verify it fails**

Run: `python -m pytest tests/test_output_fidelity.py -k share_entry -q`
Expected: FAIL — the rendered block names the rejection but not the alternative.

- [ ] **Step 10: Surface the share route**

In `src/notify/formatters.py`, inside `format_assessed_contracts`, where each contract's
reasons are rendered, add after the reason line:

```python
        # A CSP blocked purely on affordability has another route to the same exposure:
        # buy the shares at the level the analytics already computed. Turning the rejection
        # into an alternative is also the on-ramp to the buy-to-own screen.
        cash_blocked = {"insufficient_cash", "no_headroom", "buying_power_buffer"}
        if set(item.reasons) & cash_blocked and item.candidate.ideal is not None:
            buy_below = item.candidate.ideal.buy_below
            if buy_below:
                parts.append(
                    f"    ↳ share entry level {_md(f'${buy_below:.2f}')}"
                )
```

Match `parts`/`item` to the loop variables that function actually uses; read it before editing.

- [ ] **Step 11: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS

- [ ] **Step 12: Commit**

```bash
git add src/strategies/cash_secured_put.py src/strategies/_evaluation.py src/orchestrator/scan.py src/notify/formatters.py tests/test_strategies.py tests/test_output_fidelity.py
git commit -m "fix(strategies): size CSPs to headroom instead of max affordable

Fixes D1. Sizing proposed min(max_contracts, cash, csp_budget) while the
gate rejected on max_pct_per_ticker without trimming, so a 1-lot CSP
required NLV >= 2000 x strike — excluding every strike above \$150 at
\$300k NLV. Both sides now call engine.capital.max_contracts.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Replace collateral concentration with risk units in the gate

**Files:**
- Modify: `src/engine/risk_engine.py:48-245`
- Test: `tests/test_engine.py`

**Interfaces:**
- Consumes: `capital.resolve_caps`, `capital.seed_budgets`, `capital.max_contracts`, `capital.charge`, `capital.risk_units` (Task 1); `TradeCandidate.current_iv` (Task 2).
- Produces: no new public names. Reason codes `concentration_limit`, `sector_limit`, `csp_allocation_limit`, `buying_power_buffer` keep their existing spellings so `formatters._REJECT_REASON_LABELS` continues to work.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_engine.py — append
def test_gate_accepts_a_high_priced_name_within_risk_units():
    """D1: a $65k META put at 35% IV is ~$6.5k of risk units, inside a 5%-of-300k cap."""
    from src.engine.risk_engine import validate_candidates

    cand = _csp_candidate(underlying="META", strike=650.0, contracts=1, current_iv=35.0, dte=30)
    account = _account(net_liq=300_000.0, cash=100_000.0)
    verdicts = validate_candidates([cand], account, [])
    assert verdicts[0].verdict.value == "pass", verdicts[0].reasons


def test_gate_rejects_a_cheap_high_vol_name_that_is_large_in_risk_units():
    """MARA at 110% IV must be charged for its volatility, not just its collateral."""
    from src.engine.risk_engine import validate_candidates

    cand = _csp_candidate(
        underlying="MARA", strike=15.0, contracts=40, current_iv=110.0, dte=30
    )  # $60k collateral, ~$19k risk units vs a $15k cap
    account = _account(net_liq=300_000.0, cash=100_000.0)
    verdicts = validate_candidates([cand], account, [])
    assert verdicts[0].verdict.value == "reject"
    assert "concentration_limit" in verdicts[0].reasons


def test_gate_falls_back_to_collateral_when_iv_is_missing():
    from src.engine.risk_engine import validate_candidates

    cand = _csp_candidate(underlying="META", strike=650.0, contracts=1, current_iv=None, dte=30)
    account = _account(net_liq=300_000.0, cash=100_000.0)
    verdicts = validate_candidates([cand], account, [])
    # $65k > the 10%-of-NLV ($30k) collateral fallback, but the large slot admits one.
    assert verdicts[0].verdict.value == "pass", verdicts[0].reasons


def test_covered_calls_still_consume_no_budget():
    """CCs are written against shares already owned — unchanged by the new model."""
    from src.common.schemas import Strategy
    from src.engine.risk_engine import validate_candidates

    cand = _cc_candidate(underlying="AAPL", strike=250.0, contracts=5)
    assert cand.strategy == Strategy.COVERED_CALL
    account = _account(net_liq=300_000.0, cash=0.0)  # no cash at all
    verdicts = validate_candidates([cand], account, [])
    assert "buying_power_buffer" not in verdicts[0].reasons
    assert "concentration_limit" not in verdicts[0].reasons
```

Add `_csp_candidate` and `_cc_candidate` helpers to `tests/test_engine.py` if they do not already exist, accepting `current_iv` and `dte` and building a valid `TradeCandidate` with `roc_pct`/`annualized_yield_pct` above the configured floors so only the concentration logic is under test.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_engine.py -k "risk_units or high_priced or collateral_when_iv" -q`
Expected: FAIL — the $65k META candidate is rejected with `concentration_limit`.

- [ ] **Step 3: Rewrite the concentration block**

In `src/engine/risk_engine.py`, replace the `_seed_exposures` function entirely with an import:

```python
from src.engine.capital import Budgets, charge, resolve_caps, risk_units, seed_budgets
```

Inside `validate_candidates`, replace the cap resolution (lines 105-120) with:

```python
    net_liq = account.net_liquidation
    margin_usage_pct = account.maintenance_margin / net_liq * 100 if net_liq > 0 else 0.0
    margin_exceeded = margin_usage_pct > portfolio.get("max_margin_usage_pct", 50.0)

    min_iv_rank = iv_cfg.get("min_iv_rank")
    blackout_days = events.get("earnings_blackout_days", 0)

    caps = resolve_caps(account, risk)
    sector_of_fn = get_config().universe.get("sectors", {}).get
    budgets: Budgets = seed_budgets(positions, sector_of_fn)
```

Replace the whole cumulative-limits block (lines 198-226, from `# --- Cumulative per-ticker concentration` through the `buying_power_buffer` append) with:

```python
        # --- Cumulative concentration, measured in RISK UNITS (new-exposure strategies only).
        # Raw collateral encodes share price, which is not a risk measure: a 10-for-1 split
        # would make a name tradeable overnight with identical risk. Risk units
        # (collateral x IV x sqrt(DTE/365)) put a $65k META put and a $15k MARA put on the
        # same scale. When IV is missing we fall back to a stricter raw-collateral cap.
        sector = _sector_of(cand.underlying)
        if adds_new_exposure:
            units = risk_units(cand.collateral, cand.current_iv, cand.dte)
            if units is None:
                if (
                    budgets.ticker_collateral.get(cand.underlying, 0.0) + cand.collateral
                    > caps.max_ticker_collateral
                    and cand.collateral > caps.large_ticker_collateral
                ):
                    reasons.append("concentration_limit")
            else:
                if (
                    budgets.ticker_risk.get(cand.underlying, 0.0) + units
                    > caps.max_ticker_risk
                ):
                    reasons.append("concentration_limit")
                if (
                    sector
                    and budgets.sector_risk.get(sector, 0.0) + units > caps.max_sector_risk
                ):
                    reasons.append("sector_limit")

            # Large-position slot: an outsized position must be deliberate and counted.
            if cand.collateral > caps.max_ticker_collateral:
                if budgets.large_slots_used >= caps.max_large_positions:
                    reasons.append("large_position_slot_full")
                elif cand.collateral > caps.large_ticker_collateral:
                    reasons.append("concentration_limit")

            if cand.strategy == Strategy.CASH_SECURED_PUT:
                if budgets.csp_collateral + cand.collateral > caps.max_csp_collateral:
                    reasons.append("csp_allocation_limit")
            if budgets.cash_used + cand.collateral > caps.deployable_cash:
                reasons.append("buying_power_buffer")

        if margin_exceeded:
            reasons.append("margin_limit")
```

Replace the budget-consumption block (lines 230-239) with:

```python
        if verdict == Verdict.PASS and adds_new_exposure:
            charge(
                contracts=cand.contracts,
                unit_collateral=cand.collateral / max(1, cand.contracts),
                current_iv=cand.current_iv,
                dte=cand.dte,
                symbol=cand.underlying,
                sector=sector,
                caps=caps,
                budgets=budgets,
            )
```

- [ ] **Step 4: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS. Existing engine tests that assert the *old* collateral behaviour will fail — update each to the risk-unit expectation, keeping the test's original intent. Do not delete a failing test without replacing its assertion.

- [ ] **Step 5: Add the new reason label**

In `src/notify/formatters.py`, `_REJECT_REASON_LABELS`:

```python
    "large_position_slot_full": "the single large-position slot is already taken",
```

- [ ] **Step 6: Lint and type-check**

Run: `ruff check . && ruff format . && mypy src`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add src/engine/risk_engine.py src/notify/formatters.py tests/test_engine.py
git commit -m "fix(engine): concentration in risk units, not raw collateral

Replaces max_pct_per_ticker's collateral test with
collateral x IV x sqrt(DTE/365), plus an explicit counted large-position
slot. Share price is not a risk measure; the old model called a \$65k
META put 4.3x the position of a \$15k MARA put.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: Promote the variance-risk-premium floor from display to gate

**Files:**
- Modify: `src/analytics/fair_value.py:244-290`
- Modify: `src/engine/risk_engine.py` (income gates)
- Modify: `src/strategies/_evaluation.py`
- Modify: `src/strategies/cash_secured_put.py`, `src/strategies/covered_call.py`
- Modify: `config/risk_limits.yaml`
- Test: `tests/test_fair_value.py`, `tests/test_engine.py`

**Interfaces:**
- Consumes: `TradeCandidate.ideal.min_credit`, already populated by `zone_for_contract` in both generators.
- Produces: `fair_value.min_credit_for(...)` (public rename of `_min_credit`, identical signature and return type: `tuple[float | None, list[str]]`); `REASON_BELOW_FAIR_VALUE = "premium_below_fair_value"`.

**Note:** `min_credit_edge_pct` stays under `ideal_zone` — see "Deliberate simplifications" above.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_engine.py — append
def test_gate_rejects_premium_below_fair_value():
    """D2: selling at or below BS-fair-value-at-realised-vol earns no edge."""
    from src.common.schemas import IdealZone, OptionRight
    from src.engine.risk_engine import validate_candidates

    zone = IdealZone(symbol="MARA", right=OptionRight.PUT, dte=30, spot=15.0, min_credit=0.90)
    cand = _csp_candidate(
        underlying="MARA", strike=15.0, contracts=1, current_iv=110.0, dte=30, premium=0.50
    ).model_copy(update={"ideal": zone})
    verdicts = validate_candidates([cand], _account(), [])
    assert "premium_below_fair_value" in verdicts[0].reasons


def test_gate_accepts_a_low_iv_name_paying_a_real_edge():
    """SPY at 13.5% IV was rejected by the flat 1% ROC floor regardless of edge."""
    from src.common.schemas import IdealZone, OptionRight
    from src.engine.risk_engine import validate_candidates

    zone = IdealZone(symbol="SPY", right=OptionRight.PUT, dte=30, spot=660.0, min_credit=1.80)
    cand = _csp_candidate(
        underlying="SPY", strike=640.0, contracts=1, current_iv=13.5, dte=30, premium=2.10
    ).model_copy(update={"ideal": zone, "roc_pct": 0.33, "annualized_yield_pct": 4.0})
    verdicts = validate_candidates([cand], _account(net_liq=2_000_000.0, cash=500_000.0), [])
    assert verdicts[0].verdict.value == "pass", verdicts[0].reasons


def test_missing_ideal_zone_never_blocks():
    """A candidate with no computable zone is data-unavailable, not a rejection."""
    from src.engine.risk_engine import validate_candidates

    cand = _csp_candidate(underlying="AAPL", strike=200.0, contracts=1, current_iv=28.0, dte=30)
    assert cand.ideal is None
    verdicts = validate_candidates([cand], _account(), [])
    assert "premium_below_fair_value" not in verdicts[0].reasons
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_engine.py -k fair_value -q`
Expected: FAIL — no such reason code is ever produced.

- [ ] **Step 3: Make `_min_credit` public**

In `src/analytics/fair_value.py`, rename `_min_credit` to `min_credit_for` (keep the full docstring). Update its two internal call sites — in `_compute` (line ~226) and in `zone_for_contract` (line ~121).

- [ ] **Step 4: Add the reason code**

In `src/strategies/_evaluation.py`, after `REASON_YIELD`:

```python
REASON_BELOW_FAIR_VALUE = "premium_below_fair_value"
```

- [ ] **Step 5: Add the gate**

In `src/engine/risk_engine.py`, inside the per-candidate loop, immediately after the existing ROC/yield checks:

```python
        # --- Variance-risk-premium floor. The income thesis is that implied vol exceeds
        # realised vol; selling at or below Black-Scholes fair value priced at HV30 earns
        # no edge for the risk taken. This replaces the flat ROC floor as the primary gate:
        # max(1% ROC, 12% annualized) was a hidden ~25-30% IV floor that excluded every
        # low-vol diversifier in the universe and pushed every trade to the top of the
        # delta band (D2). Missing zone = data unavailable, never a rejection.
        if income.get("require_vrp_edge", True) and cand.ideal is not None:
            floor = cand.ideal.min_credit
            if floor is not None and floor > 0 and cand.premium < floor:
                reasons.append("premium_below_fair_value")
```

- [ ] **Step 6: Add the same gate to both generators**

In `src/strategies/cash_secured_put.py`, after the existing ROC/yield reason appends and after `zone` is computed but before `scores` is built, insert:

```python
        contract_zone = zone_for_contract(zone, quote.strike, iv_stats)
        if income_cfg.get("require_vrp_edge", True):
            floor = contract_zone.min_credit
            if floor is not None and floor > 0 and mid < floor:
                reasons.append(REASON_BELOW_FAIR_VALUE)
```

Then change the `TradeCandidate(...)` construction to reuse it: replace
`ideal=zone_for_contract(zone, quote.strike, iv_stats),` with `ideal=contract_zone,`.

Make the equivalent change in `src/strategies/covered_call.py`, using
`zone_for_contract(zone, quote.strike, iv_stats, cost_basis=basis)` (where `basis` is the
existing cost-basis variable) and importing `REASON_BELOW_FAIR_VALUE`.

- [ ] **Step 7: Lower the ROC floors to noise level**

In `config/risk_limits.yaml`, replace the `income:` block:

```yaml
# --- Income quality gates ---
income:
  # PRIMARY GATE: require the credit to exceed Black-Scholes fair value priced at *realised*
  # vol (HV30) by `ideal_zone.min_credit_edge_pct`. This is the variance-risk-premium thesis
  # made explicit — selling at or below fair value earns no edge for the risk taken.
  require_vrp_edge: true
  # Noise floor only. These were previously the primary gate, and max(1.0%, 12% x DTE/365)
  # acted as a hidden ~25-30% IV floor: SPY at 13.5% IV yields 0.33% ROC at 0.20 delta and
  # 0.66% at 0.30, so every low-vol diversifier in universe.yaml was unreachable, and the
  # gate pushed every trade to the aggressive end of the configured delta band.
  min_roc_pct: 0.15
  min_annualized_yield_pct: 0.0
```

- [ ] **Step 8: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS. Tests asserting the old ROC-floor rejections need their expectations updated to the VRP floor.

- [ ] **Step 9: Add the reason label**

In `src/notify/formatters.py`, `_REJECT_REASON_LABELS`:

```python
    "premium_below_fair_value": "credit is below fair value for the risk (no variance premium)",
```

- [ ] **Step 10: Commit**

```bash
git add src/analytics/fair_value.py src/engine/risk_engine.py src/strategies/ src/notify/formatters.py config/risk_limits.yaml tests/
git commit -m "fix(engine): gate on variance-risk premium, not a flat ROC floor

Fixes D2. max(1% ROC, 12% annualized) was a hidden 25-30% IV floor that
excluded SPY/GLD/TLT/XLP/XLU/XLV/XLI and every low-vol megacap, and acted
as a hidden delta floor. The gate now asks whether the credit beats BS
fair value at realised vol — the question a premium seller should ask.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: Wheel cost basis reaches the covered-call gate

**Files:**
- Modify: `src/storage/campaigns.py`
- Modify: `src/strategies/covered_call.py:146-176`
- Test: `tests/test_phase6.py`

**Interfaces:**
- Consumes: `CampaignRow.adjusted_cost_basis` (already written by `mark_campaign_assigned`).
- Produces: `campaigns.adjusted_cost_basis_for(symbol: str) -> float | None` — the open assigned campaign's per-share adjusted basis, or None.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_phase6.py — append
def test_covered_call_uses_campaign_adjusted_cost_basis(tmp_path, monkeypatch):
    """D5: premium already collected must be visible to the gate deciding on more."""
    from src.common.schemas import IVStats, PositionSnapshot
    from src.storage.campaigns import mark_campaign_assigned, open_or_append
    from src.strategies.covered_call import screen_cc_candidates

    _use_temp_db(tmp_path, monkeypatch)  # existing helper in this file
    open_or_append("AAPL", "cand-1", "cash_secured_put", "SELL", 4.50, 1)
    mark_campaign_assigned("AAPL", assignment_price=150.0, right="P")

    pos = PositionSnapshot(
        symbol="AAPL", sec_type="STK", position=100, avg_cost=150.0, underlying="AAPL"
    )
    iv_stats = IVStats(symbol="AAPL", current_iv=28.0, iv_rank=55.0, hv_30=22.0)
    result = screen_cc_candidates(
        "AAPL", _call_chain(strike=147.0), pos, iv_stats, _tech(), _fund()
    )
    # Adjusted basis is 150.00 - 4.50 = 145.50, so a $147 strike is ABOVE basis and allowed.
    passed_strikes = [c.strike for c in result.passed]
    assert 147.0 in passed_strikes, [r for _, r in result.rejected]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_phase6.py -k adjusted_cost_basis -q`
Expected: FAIL — the $147 strike is rejected with `strike_below_basis` against the raw $150 basis.

- [ ] **Step 3: Add the reader**

In `src/storage/campaigns.py`, append:

```python
def adjusted_cost_basis_for(symbol: str) -> float | None:
    """Per-share adjusted cost basis from *symbol*'s open assigned campaign, or None.

    After a CSP assignment the true basis is the assignment price less the premium already
    collected across the campaign. Without this, the covered-call gate compared strikes to
    IBKR's raw ``avg_cost`` — so with ``min_strike_vs_basis: 1.00`` the premium you already
    earned was invisible to the gate deciding whether you may earn more (D5).
    """
    try:
        with session_scope() as s:
            row = (
                s.query(CampaignRow)
                .filter_by(symbol=symbol, closed=False, assigned=True)
                .order_by(CampaignRow.id.desc())
                .first()
            )
            if row is None or row.adjusted_cost_basis is None:
                return None
            basis = float(row.adjusted_cost_basis)
            return basis if basis > 0 else None
    except Exception:
        log.warning("adjusted_cost_basis_for failed for %s", symbol, exc_info=True)
        return None
```

Verify the `CampaignRow` field names (`closed`, `assigned`) against `src/storage/models.py:371-392` before writing, and match them exactly.

- [ ] **Step 4: Use it in the covered-call screen**

In `src/strategies/covered_call.py`, add the import:

```python
from src.storage.campaigns import adjusted_cost_basis_for
```

Immediately after the `contracts` computation (around line 99), add:

```python
    # Prefer the wheel-adjusted basis: after an assignment the real basis is the assignment
    # price less the premium already collected on this campaign. Falls back to IBKR avg_cost
    # for shares bought outright.
    basis = adjusted_cost_basis_for(symbol) or position.avg_cost
```

Then replace every use of `position.avg_cost` inside the per-quote loop with `basis` — the
`min_strike_vs_basis` comparison (line 146), `collateral` (line 153), `roc_pct` (line 158),
`breakeven` (line 204), and both `cost_basis=` arguments (lines 176 and 214).

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS

- [ ] **Step 6: Update docs**

In `STATUS.md`, find the "Campaign chaining (C6)" row and replace "`/campaigns` and `/campaigns open` Telegram commands display the wheel P&L thread" with a note that `adjusted_cost_basis` now feeds the covered-call gate via `adjusted_cost_basis_for`, so the wheel's collected premium affects which strikes are writable.

- [ ] **Step 7: Commit**

```bash
git add src/storage/campaigns.py src/strategies/covered_call.py tests/test_phase6.py STATUS.md
git commit -m "fix(strategies): wheel-adjusted cost basis reaches the CC gate

Fixes D5. mark_campaign_assigned computed adjusted_cost_basis but only the
/campaigns formatter read it, so with min_strike_vs_basis: 1.00 a put
assigned at \$150 after collecting \$4.50 refused every call below \$150 —
including the \$147 that is profitable on the campaign.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: IV rank measures one thing

**Files:**
- Modify: `src/analytics/iv.py:179-196`
- Test: `tests/test_analytics.py`

**Interfaces:**
- Consumes: `_term_structure_slope` (existing, unchanged).
- Produces: `_atm_iv_at_30d(quotes: list[OptionQuote]) -> float | None`, replacing `_live_atm_iv` as the `current_iv` source in `get_iv_stats`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_analytics.py — append
def test_atm_iv_is_interpolated_to_30_days():
    """D6: history is a 30-day constant-maturity index; the live value must match it."""
    from src.analytics.iv import _atm_iv_at_30d

    # 21 DTE at 20% and 49 DTE at 30% -> linear in DTE, 30 days sits at ~23.2%
    quotes = _atm_quotes(dte=21, iv=0.20) + _atm_quotes(dte=49, iv=0.30)
    result = _atm_iv_at_30d(quotes)
    assert result == pytest.approx(0.2321, abs=0.005)


def test_atm_iv_falls_back_to_nearest_expiry_with_one_expiry():
    from src.analytics.iv import _atm_iv_at_30d

    quotes = _atm_quotes(dte=21, iv=0.20)
    assert _atm_iv_at_30d(quotes) == pytest.approx(0.20, abs=0.001)


def test_atm_iv_returns_none_without_usable_quotes():
    from src.analytics.iv import _atm_iv_at_30d

    assert _atm_iv_at_30d([]) is None
```

Write `_atm_quotes(dte, iv)` as a local helper in the test file returning a paired
call/put `OptionQuote` list at strikes bracketing a fixed spot, so `infer_spot_from_quotes`
resolves. Follow the `OptionQuote` construction already used elsewhere in this test file.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_analytics.py -k atm_iv -q`
Expected: FAIL — `ImportError: cannot import name '_atm_iv_at_30d'`

- [ ] **Step 3: Implement the interpolation**

In `src/analytics/iv.py`, replace `_live_atm_iv` with:

```python
_TARGET_DTE = 30  # matches IBKR's OPTION_IMPLIED_VOLATILITY constant-maturity index


def _atm_iv_at_30d(quotes: list[OptionQuote]) -> float | None:
    """Live ATM IV interpolated to a constant 30-day maturity.

    ``iv_history`` stores IBKR's ``OPTION_IMPLIED_VOLATILITY`` daily bar, which is a ~30-day
    constant-maturity ATM index. Ranking the *nearest scanned expiry* (~21-25 DTE, since the
    chain is filtered to the 21-45 DTE window) against that series compares two different
    measurements: in contango it biases IV rank down, and in backwardation it biases it up —
    loosening the gate exactly when the term structure inverts (D6). IV rank is both the
    largest score weight (0.30) and a hard gate, so the two must be the same measurement.

    Linear in DTE between the two expiries bracketing 30 days. With a single expiry, or when
    30 days sits outside the scanned range, returns that expiry's ATM IV unextrapolated.
    """
    if not quotes:
        return None
    spot = infer_spot_from_quotes(quotes)
    if spot is None:
        return None

    from collections import defaultdict

    by_dte: dict[int, list[float]] = defaultdict(list)
    for q in quotes:
        if q.dte > 0 and q.iv is not None and q.iv > 0:
            by_dte[q.dte].append((abs(q.strike - spot), q.iv))  # type: ignore[arg-type]

    atm_by_dte: dict[int, float] = {}
    for dte, entries in by_dte.items():
        entries.sort(key=lambda e: e[0])  # nearest spot first
        nearest = entries[: min(4, len(entries))]
        atm_by_dte[dte] = sum(iv for _, iv in nearest) / len(nearest)

    if not atm_by_dte:
        return None
    dtes = sorted(atm_by_dte)
    if len(dtes) == 1:
        return atm_by_dte[dtes[0]]

    below = [d for d in dtes if d <= _TARGET_DTE]
    above = [d for d in dtes if d >= _TARGET_DTE]
    if not below:
        return atm_by_dte[above[0]]
    if not above:
        return atm_by_dte[below[-1]]
    lo, hi = below[-1], above[0]
    if lo == hi:
        return atm_by_dte[lo]
    weight = (_TARGET_DTE - lo) / (hi - lo)
    return atm_by_dte[lo] + weight * (atm_by_dte[hi] - atm_by_dte[lo])
```

In `get_iv_stats`, change line 39:

```python
    live_iv = _atm_iv_at_30d(quotes) if quotes else None
```

- [ ] **Step 4: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS

- [ ] **Step 5: Update docs**

In `STATUS.md`, in the analytics bullet, add a sentence: "The live IV used for IV rank is interpolated to a constant 30-day maturity (`_atm_iv_at_30d`) so it matches the constant-maturity `OPTION_IMPLIED_VOLATILITY` series it is ranked against."

- [ ] **Step 6: Commit**

```bash
git add src/analytics/iv.py tests/test_analytics.py STATUS.md
git commit -m "fix(analytics): rank IV at constant 30-day maturity

Fixes D6. iv_history stores IBKR's ~30d constant-maturity index while the
live override read the nearest scanned expiry (~21-25 DTE), so IV rank was
biased down in contango and up in backwardation — loosening the gate
exactly when the term structure inverts.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 8: The capacity report

**Files:**
- Create: `scripts/capacity_report.py`
- Test: `tests/test_account_sizing.py`

**Interfaces:**
- Consumes: `capital.resolve_caps`, `capital.max_contracts` (Task 1).
- Produces: `capacity_report.build_report(account, positions, universe_symbols, iv_by_symbol, price_by_symbol) -> list[CapacityRow]` where `CapacityRow` is a frozen dataclass with `symbol: str`, `spot: float`, `contracts: int`, `binding: str`, `collateral: float`, `nlv_needed_for_one: float`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_account_sizing.py
"""The regression class the suite lacked: what can this system actually trade?

1,088 tests asked "does the gate reject what it says it rejects" and never "given this
account and this universe, is the tradeable set non-empty and sane" — which is why D1 and
D2 both passed CI for months.
"""

from __future__ import annotations

import pytest

from src.common.schemas import AccountSnapshot
from scripts.capacity_report import build_report


def _account(net_liq: float, cash: float) -> AccountSnapshot:
    return AccountSnapshot(
        account="DU1",
        net_liquidation=net_liq,
        total_cash=cash,
        buying_power=cash,
        maintenance_margin=0.0,
        excess_liquidity=cash,
    )


PRICES = {"SPY": 660.0, "META": 700.0, "AAPL": 230.0, "XLF": 52.0, "SOFI": 18.0}
IVS = {"SPY": 13.5, "META": 35.0, "AAPL": 28.0, "XLF": 20.0, "SOFI": 60.0}


@pytest.mark.parametrize("net_liq,cash", [(50_000, 25_000), (300_000, 100_000), (1_000_000, 400_000)])
def test_tradeable_set_is_never_empty(net_liq, cash):
    rows = build_report(_account(net_liq, cash), [], list(PRICES), IVS, PRICES)
    tradeable = [r for r in rows if r.contracts >= 1]
    assert tradeable, f"no symbol tradeable at NLV={net_liq}"


def test_no_symbol_is_excluded_solely_for_share_price():
    """D1: META must be reachable at $300k; only cash may refuse it."""
    rows = build_report(_account(300_000, 100_000), [], list(PRICES), IVS, PRICES)
    by_symbol = {r.symbol: r for r in rows}
    meta = by_symbol["META"]
    if meta.contracts == 0:
        assert meta.binding in {"cash", "csp_budget"}, (
            f"META refused for {meta.binding!r}, which is not an affordability reason"
        )


def test_low_iv_names_are_reachable_at_a_large_account():
    """D2: the defensive diversifiers must be sizeable when capital allows."""
    rows = build_report(_account(1_000_000, 400_000), [], list(PRICES), IVS, PRICES)
    by_symbol = {r.symbol: r for r in rows}
    assert by_symbol["SPY"].contracts >= 1
    assert by_symbol["XLF"].contracts >= 1


def test_report_reports_the_nlv_needed_for_one_lot():
    rows = build_report(_account(50_000, 25_000), [], ["META"], IVS, PRICES)
    assert rows[0].nlv_needed_for_one > 50_000
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_account_sizing.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.capacity_report'`

- [ ] **Step 3: Implement the report**

```python
# scripts/capacity_report.py
"""What can this system actually trade today, and what binds first?

The test suite verifies that gates reject what they claim to reject; it never asked whether
the account can reach the universe at all. That blind spot is why a 1-lot CSP silently
required ``NLV >= 2000 x strike`` (D1) and why the income floor silently excluded every
low-vol name (D2) — both passed every test.

Run:
    python -m scripts.capacity_report              # live account via IBKR
    python -m scripts.capacity_report --net-liq 300000 --cash 100000   # hypothetical
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass

from src.common.config import get_config
from src.common.schemas import AccountSnapshot, PositionSnapshot
from src.engine.capital import max_contracts, resolve_caps, seed_budgets


@dataclass(frozen=True)
class CapacityRow:
    symbol: str
    spot: float
    contracts: int
    binding: str
    collateral: float
    nlv_needed_for_one: float


def build_report(
    account: AccountSnapshot,
    positions: list[PositionSnapshot],
    universe_symbols: list[str],
    iv_by_symbol: dict[str, float],
    price_by_symbol: dict[str, float],
) -> list[CapacityRow]:
    """One row per symbol: how many contracts fit, and which constraint stops the next one.

    Strike is approximated as 0.90 x spot, a stand-in for the ~0.25-delta put the screens
    target. This is a capacity estimate, not a quote.
    """
    cfg = get_config()
    risk = cfg.risk
    caps = resolve_caps(account, risk)
    sector_of = cfg.universe.get("sectors", {}).get
    hard_max = int(risk.get("cash_secured_put", {}).get("max_contracts", 10))
    dte = 30

    rows: list[CapacityRow] = []
    for symbol in universe_symbols:
        spot = price_by_symbol.get(symbol, 0.0)
        if spot <= 0:
            continue
        strike = round(spot * 0.90, 2)
        unit = strike * 100
        budgets = seed_budgets(positions, sector_of)
        n, binding = max_contracts(
            unit_collateral=unit,
            current_iv=iv_by_symbol.get(symbol),
            dte=dte,
            symbol=symbol,
            sector=sector_of(symbol),
            caps=caps,
            budgets=budgets,
            hard_max=hard_max,
        )
        ticker_pct = float(risk.get("portfolio", {}).get("max_collateral_per_ticker_pct", 10.0))
        rows.append(
            CapacityRow(
                symbol=symbol,
                spot=spot,
                contracts=n,
                binding=binding,
                collateral=unit * n,
                nlv_needed_for_one=unit / (ticker_pct / 100.0) if ticker_pct > 0 else 0.0,
            )
        )
    return rows


def format_report(rows: list[CapacityRow]) -> str:
    header = f"{'SYMBOL':<8}{'SPOT':>10}{'LOTS':>6}{'COLLATERAL':>13}  {'BINDING'}"
    lines = [header, "-" * len(header)]
    for r in sorted(rows, key=lambda x: (-x.contracts, x.symbol)):
        lines.append(
            f"{r.symbol:<8}{r.spot:>10.2f}{r.contracts:>6}{r.collateral:>13,.0f}  "
            f"{r.binding or 'none (hit hard_max)'}"
        )
    tradeable = sum(1 for r in rows if r.contracts >= 1)
    lines.append("")
    lines.append(f"{tradeable}/{len(rows)} symbols tradeable at this account size.")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Report tradeable capacity per symbol.")
    parser.add_argument("--net-liq", type=float, default=None)
    parser.add_argument("--cash", type=float, default=None)
    args = parser.parse_args()

    cfg = get_config()
    symbols = sorted(set(cfg.universe.get("would_own", [])))

    if args.net_liq is not None and args.cash is not None:
        account = AccountSnapshot(
            account="hypothetical",
            net_liquidation=args.net_liq,
            total_cash=args.cash,
            buying_power=args.cash,
            maintenance_margin=0.0,
            excess_liquidity=args.cash,
        )
        positions: list[PositionSnapshot] = []
    else:
        from src.ibkr.connection import connect
        from src.ibkr.portfolio import get_account_snapshot, get_positions

        with connect("healthcheck") as ib:
            account = get_account_snapshot(ib, cfg.secrets.ibkr_account)
            positions = get_positions(ib)

    from src.analytics.iv import get_iv_stats
    from src.analytics.technicals import get_technical_stats

    iv_by_symbol: dict[str, float] = {}
    price_by_symbol: dict[str, float] = {}
    for sym in symbols:
        stats = get_iv_stats(sym)
        if stats.current_iv:
            iv_by_symbol[sym] = stats.current_iv
        tech = get_technical_stats(sym)
        if tech.price:
            price_by_symbol[sym] = tech.price

    print(format_report(build_report(account, positions, symbols, iv_by_symbol, price_by_symbol)))


if __name__ == "__main__":
    main()
```

Verify `connect()`'s context-manager signature against `src/ibkr/connection.py` before writing the live branch; match the pattern `scripts/healthcheck.py` already uses.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_account_sizing.py -q`
Expected: PASS (6 tests, counting the parametrize expansion)

- [ ] **Step 5: Run it for real against the target account size**

Run: `python -m scripts.capacity_report --net-liq 300000 --cash 100000`
Expected: a table where a clear majority of `would_own` symbols show `contracts >= 1`. **If fewer than half are tradeable, stop and re-derive `max_risk_units_per_ticker_pct` before continuing** — the spec's calibration note applies here, and the shipped 5.0 is a starting point, not a validated value.

- [ ] **Step 6: Update docs**

- `README.md` layout table: add `scripts/capacity_report.py`.
- `SETUP.md` scripts table: add it with the `--net-liq/--cash` usage.
- `ARCHITECTURE.md`: add to the scripts section.

- [ ] **Step 7: Commit**

```bash
git add scripts/capacity_report.py tests/test_account_sizing.py README.md SETUP.md ARCHITECTURE.md
git commit -m "feat(scripts): capacity report + account-size regression tests

Answers 'what can this system actually trade today, and what binds first'
for every universe symbol. This is the test class the suite lacked — it
verified gate mechanics but never outcomes, which is why D1 and D2 both
passed CI.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 9: Phase 1 config and documentation sweep

**Files:**
- Modify: `config/risk_limits.yaml`
- Modify: `ARCHITECTURE.md`, `STATUS.md`, `SETUP.md`
- Test: `tests/test_config_keys.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config_keys.py — append
def test_portfolio_block_has_the_risk_unit_keys():
    from src.common.config import get_config

    p = get_config().risk["portfolio"]
    for key in (
        "cash_reserve_pct",
        "cash_reserve_absolute",
        "max_csp_allocation_pct_of_deployable",
        "max_risk_units_per_ticker_pct",
        "max_risk_units_per_sector_pct",
        "max_collateral_per_ticker_pct",
        "max_large_positions",
        "max_pct_per_ticker_large",
    ):
        assert key in p, f"missing risk_limits.yaml portfolio key: {key}"


def test_retired_collateral_keys_are_gone():
    from src.common.config import get_config

    p = get_config().risk["portfolio"]
    for key in ("max_pct_per_ticker", "max_pct_per_sector", "max_csp_allocation_pct",
                "min_buying_power_buffer_pct", "max_correlated_exposure_pct"):
        assert key not in p, f"retired key still present: {key}"
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_config_keys.py -k portfolio -q`
Expected: FAIL

- [ ] **Step 3: Replace the portfolio block**

In `config/risk_limits.yaml`, replace the entire `portfolio:` block:

```yaml
# --- Portfolio: three constraints, each in its proper unit ---
# `max_pct_per_ticker` used to answer three unrelated questions at once, which is why any
# CSP above a ~$150 strike was unreachable at $300k NLV. Split:
#   1. feasibility  -> cash
#   2. concentration -> RISK UNITS (collateral x IV x sqrt(DTE/365))
#   3. deliberateness -> an explicit, counted large-position slot
portfolio:
  # 1. Feasibility. The reserve comes off FIRST; the CSP budget is a % of what remains.
  #    Order is fixed in code (engine/capital.resolve_caps) so the two can't contradict.
  cash_reserve_pct: 20.0
  cash_reserve_absolute: 10000
  max_csp_allocation_pct_of_deployable: 100.0

  # 2. Concentration, in risk units. CALIBRATION WARNING: these values are NOT comparable to
  #    the old collateral-based percentages. Risk units are collateral scaled by
  #    IV x sqrt(DTE/365) (typically 0.05-0.30), so 5.0 here is far more permissive than 5.0
  #    was before. Re-derive with `python -m scripts.capacity_report` before trusting them.
  max_risk_units_per_ticker_pct: 5.0
  max_risk_units_per_sector_pct: 25.0
  # Fallback cap used when IV is unavailable (strictly more conservative than risk units).
  max_collateral_per_ticker_pct: 10.0

  # 3. Deliberateness. A position above max_collateral_per_ticker_pct needs a free slot and
  #    must still sit under the hard ceiling. Without this, a high-priced name is either
  #    impossible or unbounded — one number cannot express a third option.
  max_large_positions: 1
  max_pct_per_ticker_large: 25.0

  max_margin_usage_pct: 50.0
  max_new_positions_per_run: 10
```

- [ ] **Step 4: Run the full suite**

Run: `python -m pytest -q && ruff check . && mypy src`
Expected: all green.

- [ ] **Step 5: Update the docs**

- `ARCHITECTURE.md` config section: document every new key and the fixed order of application; add `src/engine/capital.py` to the `src/engine/` folder guide.
- `STATUS.md`: add a "Bugs fixed (2026-08-10 — capital & income model)" section covering D1, D2, D5, D6 with the measured numbers from §1 of the spec. Remove `max_correlated_exposure_pct` from the "Not built" table.
- `SETUP.md`: note the calibration step (run `capacity_report` after changing account size).

- [ ] **Step 6: Commit**

```bash
git add config/risk_limits.yaml ARCHITECTURE.md STATUS.md SETUP.md tests/test_config_keys.py
git commit -m "docs+config: risk-unit portfolio model, retire collateral caps

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

# Phase 2 — Loss management and autonomy

### Task 10: Loss-side exits

**Files:**
- Modify: `src/execution/profit_take.py`
- Modify: `config/settings.yaml`, `src/common/config.py` (AutomationCfg)
- Create: `tests/test_loss_exits.py`

**Interfaces:**
- Consumes: `position_manager.close_short_position(ib_exec, pos, bid, ask) -> CloseResult` (existing); `profit_take.net_entry_credit_per_share` (existing).
- Produces: `profit_take.check_loss_exits(ib_scan, ib_exec, bot, chat_id) -> None`; `AutomationCfg.max_loss_multiple: float`; `AutomationCfg.auto_close_enabled: bool`.

**Note:** `check_loss_exits` lives in `profit_take.py` alongside `check_profit_takes`. The module is now about exits generally; renaming it would ripple through `approval_service` re-exports and tests for no functional gain.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_loss_exits.py
"""Loss-side exits (D3). The system could previously only add risk and take profits."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.common.schemas import OptionRight, PositionSnapshot


def _short_put(strike=100.0, qty=-1):
    from datetime import date, timedelta

    return PositionSnapshot(
        symbol="AAPL  260918P00100000",
        sec_type="OPT",
        position=qty,
        avg_cost=250.0,
        right=OptionRight.PUT,
        strike=strike,
        expiry=date.today() + timedelta(days=30),
        underlying="AAPL",
    )


@pytest.mark.asyncio
async def test_loss_exit_fires_at_the_configured_multiple():
    """Entry credit $2.50, cost-to-close $5.20 -> 2.08x, above the 2.0x threshold."""
    from src.execution.profit_take import check_loss_exits

    ib_scan, ib_exec, bot = MagicMock(), MagicMock(), MagicMock()
    with (
        patch("src.ibkr.portfolio.get_positions", return_value=[_short_put()]),
        patch("src.execution.profit_take.net_entry_credit_per_share", return_value=2.50),
        patch("src.execution.profit_take._quote_short", new=AsyncMock(return_value=(5.10, 5.30))),
        patch("src.execution.profit_take.close_short_position", new=AsyncMock()) as close,
    ):
        await check_loss_exits(ib_scan, ib_exec, bot, "chat")
    close.assert_awaited_once()


@pytest.mark.asyncio
async def test_loss_exit_does_not_fire_below_the_multiple():
    from src.execution.profit_take import check_loss_exits

    ib_scan, ib_exec, bot = MagicMock(), MagicMock(), MagicMock()
    with (
        patch("src.ibkr.portfolio.get_positions", return_value=[_short_put()]),
        patch("src.execution.profit_take.net_entry_credit_per_share", return_value=2.50),
        patch("src.execution.profit_take._quote_short", new=AsyncMock(return_value=(3.00, 3.20))),
        patch("src.execution.profit_take.close_short_position", new=AsyncMock()) as close,
    ):
        await check_loss_exits(ib_scan, ib_exec, bot, "chat")
    close.assert_not_awaited()


@pytest.mark.asyncio
async def test_loss_exit_is_skipped_when_auto_close_is_disabled():
    from src.execution.profit_take import check_loss_exits

    ib_scan, ib_exec, bot = MagicMock(), MagicMock(), MagicMock()
    cfg = MagicMock()
    cfg.automation.auto_close_enabled = False
    cfg.automation.max_loss_multiple = 2.0
    with (
        patch("src.execution.profit_take.get_config", return_value=cfg),
        patch("src.ibkr.portfolio.get_positions", return_value=[_short_put()]),
        patch("src.execution.profit_take.net_entry_credit_per_share", return_value=2.50),
        patch("src.execution.profit_take._quote_short", new=AsyncMock(return_value=(9.0, 9.2))),
        patch("src.execution.profit_take.close_short_position", new=AsyncMock()) as close,
    ):
        await check_loss_exits(ib_scan, ib_exec, bot, "chat")
    close.assert_not_awaited()
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_loss_exits.py -q`
Expected: FAIL — `ImportError: cannot import name 'check_loss_exits'`

- [ ] **Step 3: Extract the quote helper**

In `src/execution/profit_take.py`, extract the quote-fetch block currently inlined in
`check_profit_takes` (lines 204-239) into a module-level helper, and call it from
`check_profit_takes` in place of the inlined code:

```python
async def _quote_short(ib_scan: IB, pos: PositionSnapshot) -> tuple[float, float | None]:
    """Live (bid, ask) for a short option position. Returns (0.0, None) on failure.

    Polls in 0.1 s steps and returns as soon as a two-sided market arrives rather than
    burning the full quote timeout per position (N14).
    """
    cfg = get_config()
    assert pos.expiry is not None and pos.strike is not None and pos.right is not None
    try:
        contract = build_option(
            pos.underlying or pos.symbol, pos.expiry, pos.strike, pos.right.value
        )
        qualified_list = await ib_scan.qualifyContractsAsync(contract)
        if not qualified_list:
            return 0.0, None
        qualified = cast(IBContract, qualified_list[0])
        ticker = ib_scan.reqMktData(qualified, "101", False, False)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + float(cfg.execution.quote_timeout_seconds)

        def _two_sided(t: object = ticker) -> bool:
            b, a = getattr(t, "bid", None), getattr(t, "ask", None)
            try:
                return b is not None and a is not None and float(a) > 0
            except (TypeError, ValueError):
                return False

        while not _two_sided() and loop.time() < deadline:
            await asyncio.sleep(0.1)
        ib_scan.cancelMktData(qualified)

        raw_bid, raw_ask = ticker.bid, ticker.ask
        bid = float(raw_bid) if raw_bid is not None and float(raw_bid) > 0 else 0.0
        ask = float(raw_ask) if raw_ask is not None and float(raw_ask) > 0 else None
        return bid, ask
    except Exception:
        log.exception("quote fetch failed for %s", pos.symbol)
        return 0.0, None
```

Add `from src.execution.position_manager import close_short_position` to the module imports so
the test's patch target resolves.

- [ ] **Step 4: Implement `check_loss_exits`**

Append to `src/execution/profit_take.py`:

```python
async def check_loss_exits(
    ib_scan: IB,
    ib_exec: IB | None,
    bot: Bot,
    chat_id: str,
) -> None:
    """Buy to close any short whose cost-to-close has reached ``max_loss_multiple`` x credit.

    The system previously had no loss-side exit at all: the only ways out were the 50% profit
    take, expiry, assignment, and alert-only roll triggers. Short premium's entire risk lives
    in the left tail, so an unattended loop that can only add risk and harvest winners is the
    one configuration that can genuinely hurt the account (D3).

    Closing risk is always permitted, so this runs on ``automation.auto_close_enabled``
    independently of the autonomy level — that setting governs *opening* exposure.
    """
    cfg = get_config()
    if not getattr(cfg.automation, "auto_close_enabled", True):
        return
    multiple = float(getattr(cfg.automation, "max_loss_multiple", 0.0) or 0.0)
    if multiple <= 0 or ib_exec is None:
        return

    from src.ibkr.portfolio import get_positions

    try:
        positions = get_positions(ib_scan)
    except Exception:
        log.exception("loss-exit: failed to load positions")
        return

    for pos in positions:
        if not (
            pos.sec_type == "OPT"
            and pos.position < 0
            and pos.expiry is not None
            and pos.strike is not None
            and pos.right is not None
        ):
            continue

        with session_scope() as s:
            entry = net_entry_credit_per_share(
                s, pos.underlying or pos.symbol, pos.strike, pos.expiry, pos.right.value
            )
        if entry is None or entry <= 0:
            continue

        bid, ask = await _quote_short(ib_scan, pos)
        if ask is None:
            continue
        mid = (bid + ask) / 2 if bid > 0 else ask
        if mid < multiple * entry:
            continue

        log.warning(
            "Loss exit triggered: %s — entry=%.2f mid=%.2f (%.1fx)",
            pos.symbol,
            entry,
            mid,
            mid / entry,
        )
        result = await close_short_position(ib_exec, pos, bid, ask)
        if result.status == "skipped":
            continue
        from src.notify.formatters import _md, contract_label

        label = _md(
            contract_label(
                pos.underlying or pos.symbol, pos.strike, pos.right.value, pos.expiry
            )
        )
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=(
                    f"🛑 *Loss exit* — {label}\n"
                    f"Entry credit {_md(f'${entry:.2f}')}, cost to close "
                    f"{_md(f'${mid:.2f}')} \\({mid / entry:.1f}×\\)\\."
                ),
                parse_mode="MarkdownV2",
            )
        except Exception:
            log.exception("Failed to send loss-exit notice for %s", pos.symbol)
```

- [ ] **Step 5: Add the config keys**

In `src/common/config.py`, `AutomationCfg`:

```python
    # Buy to close when cost-to-close reaches this multiple of the entry credit. 0 disables.
    max_loss_multiple: float = 2.0
    # Risk-REDUCING actions run on this switch, independent of the autonomy level — that
    # governs opening exposure. Closing risk should never wait for a tap.
    auto_close_enabled: bool = True
```

In `config/settings.yaml`, under `automation:`:

```yaml
  # Buy to close when cost-to-close reaches this multiple of the entry credit. 0 disables.
  max_loss_multiple: 2.0
  # Risk-reducing closes (profit takes AND loss exits) run independently of autonomy level.
  auto_close_enabled: true
```

- [ ] **Step 6: Wire it into the intraday loop**

In `src/notify/approval_service.py`, add the import beside the existing profit-take import
(line 61):

```python
from src.execution.profit_take import check_loss_exits as _check_loss_exits
```

Directly after the `await _check_profit_takes(...)` call (line ~1123):

```python
                    await _check_loss_exits(ib_scan, ib_exec, bot, chat_id)
```

- [ ] **Step 7: Run the full suite**

Run: `python -m pytest -q && ruff check . && mypy src`
Expected: all green.

- [ ] **Step 8: Update docs**

- `ARCHITECTURE.md` `src/execution/` section: describe `check_loss_exits` and `_quote_short`.
- `STATUS.md`: add loss exits to "What is built"; remove any claim that exits are profit-take-only.
- `SETUP.md`: document `max_loss_multiple` and `auto_close_enabled`.

- [ ] **Step 9: Commit**

```bash
git add src/execution/profit_take.py src/common/config.py config/settings.yaml src/notify/approval_service.py tests/test_loss_exits.py ARCHITECTURE.md STATUS.md SETUP.md
git commit -m "feat(execution): loss-side exits at N x entry credit

Fixes the first half of D3. The system had no stop-loss of any kind — the
only exits were the 50% profit take, expiry, assignment, and alert-only
rolls. Runs on auto_close_enabled independently of autonomy level, since
that governs opening exposure and closing risk should never wait.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 11: A kill switch that can see losses

**Files:**
- Modify: `src/execution/circuit_breakers.py`
- Modify: `src/storage/system_settings.py`
- Modify: `config/settings.yaml`, `src/common/config.py`
- Test: `tests/test_circuit_breakers.py`

**Interfaces:**
- Consumes: `storage.positions.load_latest_position_snapshot(before: date | None) -> list[PositionSnapshot]` (existing).
- Produces:
  - `circuit_breakers.mark_based_loss(positions: list[PositionSnapshot], net_liquidation: float) -> float | None` — loss amount when breached, else None.
  - `circuit_breakers.drawdown_breached(net_liquidation: float) -> float | None`
  - `system_settings.get_high_water_mark() -> float`, `set_high_water_mark(value: float) -> None`
  - `AutomationCfg.drawdown_halt_pct: float`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_circuit_breakers.py — append
def test_mark_based_loss_sees_a_drawdown_that_cashflow_misses(tmp_path, monkeypatch):
    """D3: selling premium into a 15% drawdown reads as a PROFIT to the cashflow breaker."""
    from datetime import date, timedelta

    from src.common.schemas import PositionSnapshot
    from src.execution.circuit_breakers import mark_based_loss
    from src.storage.positions import save_position_snapshot

    _use_temp_db(tmp_path, monkeypatch)  # existing helper in this file
    yesterday = [
        PositionSnapshot(
            symbol="AAPL", sec_type="STK", position=100, avg_cost=200.0,
            underlying="AAPL", unrealized_pnl=0.0,
        )
    ]
    save_position_snapshot(date.today() - timedelta(days=1), yesterday)

    today = [
        PositionSnapshot(
            symbol="AAPL", sec_type="STK", position=100, avg_cost=200.0,
            underlying="AAPL", unrealized_pnl=-12_000.0,
        )
    ]
    loss = mark_based_loss(today, net_liquidation=300_000.0)
    assert loss is not None and loss == pytest.approx(12_000.0)


def test_mark_based_loss_returns_none_below_the_threshold(tmp_path, monkeypatch):
    from datetime import date, timedelta

    from src.common.schemas import PositionSnapshot
    from src.execution.circuit_breakers import mark_based_loss
    from src.storage.positions import save_position_snapshot

    _use_temp_db(tmp_path, monkeypatch)
    save_position_snapshot(
        date.today() - timedelta(days=1),
        [PositionSnapshot(symbol="AAPL", sec_type="STK", position=100, avg_cost=200.0,
                          underlying="AAPL", unrealized_pnl=0.0)],
    )
    today = [PositionSnapshot(symbol="AAPL", sec_type="STK", position=100, avg_cost=200.0,
                              underlying="AAPL", unrealized_pnl=-1_000.0)]
    assert mark_based_loss(today, net_liquidation=300_000.0) is None


def test_drawdown_breaker_tracks_the_high_water_mark(tmp_path, monkeypatch):
    from src.execution.circuit_breakers import drawdown_breached
    from src.storage.system_settings import get_high_water_mark

    _use_temp_db(tmp_path, monkeypatch)
    assert drawdown_breached(300_000.0) is None      # first call seeds the HWM
    assert get_high_water_mark() == pytest.approx(300_000.0)
    assert drawdown_breached(310_000.0) is None      # new high
    assert get_high_water_mark() == pytest.approx(310_000.0)
    breach = drawdown_breached(270_000.0)            # -12.9% from 310k, cap 10%
    assert breach is not None and breach == pytest.approx(40_000.0)
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_circuit_breakers.py -k "mark_based or drawdown" -q`
Expected: FAIL — `ImportError: cannot import name 'mark_based_loss'`

- [ ] **Step 3: Add the high-water-mark accessors**

In `src/storage/system_settings.py`, after `ACTIVE_PROFILE_KEY`:

```python
HIGH_WATER_MARK_KEY = "nlv_high_water_mark"
```

And append:

```python
def get_high_water_mark() -> float:
    """Highest net liquidation seen, used by the drawdown circuit breaker."""
    try:
        return float(get_setting(HIGH_WATER_MARK_KEY, "0") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def set_high_water_mark(value: float) -> None:
    set_setting(HIGH_WATER_MARK_KEY, f"{value:.2f}")
```

- [ ] **Step 4: Implement the breakers**

Append to `src/execution/circuit_breakers.py`:

```python
def mark_based_loss(
    positions: list[PositionSnapshot], net_liquidation: float
) -> float | None:
    """Today's mark-to-market loss if it breaches ``daily_loss_halt_pct``, else None.

    ``realized_cashflow_today`` sums FillRow credits and debits, so a day that sells premium
    into a 15% drawdown registers as a *profit* and the kill switch stays open while the
    15-minute loop opens more shorts into the same move (D3). This measures what actually
    happened to the book: today's summed ``unrealized_pnl`` against the prior snapshot's.

    Returns the loss as a positive number, or None when the breaker is disabled, no baseline
    exists, or no breach occurred.
    """
    pct = get_config().automation.daily_loss_halt_pct
    if not pct or net_liquidation <= 0:
        return None
    baseline_positions = load_latest_position_snapshot(before=datetime.now(_ET).date())
    if not baseline_positions:
        return None  # no baseline yet — cannot measure a delta
    baseline = sum(p.unrealized_pnl or 0.0 for p in baseline_positions)
    current = sum(p.unrealized_pnl or 0.0 for p in positions)
    delta = current - baseline
    if delta >= 0:
        return None
    loss = -delta
    return loss if loss >= (pct / 100.0) * net_liquidation else None


def drawdown_breached(net_liquidation: float) -> float | None:
    """Drawdown from the trailing net-liquidation high-water mark, if it breaches the cap.

    Catches the slow bleed no single day trips. Advances the high-water mark on a new high
    as a side effect, so the first call after a fresh install simply seeds it.
    """
    pct = getattr(get_config().automation, "drawdown_halt_pct", 0.0)
    if not pct or net_liquidation <= 0:
        return None
    hwm = get_high_water_mark()
    if net_liquidation > hwm:
        set_high_water_mark(net_liquidation)
        return None
    if hwm <= 0:
        set_high_water_mark(net_liquidation)
        return None
    drawdown = hwm - net_liquidation
    return drawdown if drawdown >= (pct / 100.0) * hwm else None
```

Add the required imports at the top of the module:

```python
from src.common.schemas import PositionSnapshot
from src.storage.positions import load_latest_position_snapshot
from src.storage.system_settings import get_high_water_mark, set_high_water_mark
```

- [ ] **Step 5: Add the config key**

In `src/common/config.py`, `AutomationCfg`, replace the `daily_loss_halt_pct` docstring
comment and add the second breaker:

```python
    # Auto-trip the kill switch when today's MARK-TO-MARKET loss exceeds this % of net liq.
    # Measured from the prior position snapshot's unrealized P&L, NOT from fill cashflow —
    # an income desk always has positive cashflow on a day it sells premium, so the old
    # cashflow-based measure read a drawdown as a profit.
    daily_loss_halt_pct: float = 3.0
    # Auto-trip when net liquidation falls this % below its trailing high-water mark. Catches
    # the slow bleed that no single day trips. 0 disables.
    drawdown_halt_pct: float = 10.0
```

In `config/settings.yaml`, under `automation:`, replace `daily_loss_halt_pct: 5.0` with:

```yaml
  # Mark-to-market, not fill cashflow. See config.py AutomationCfg.
  daily_loss_halt_pct: 3.0
  drawdown_halt_pct: 10.0
```

- [ ] **Step 6: Wire the breakers into the intraday loop**

In `src/notify/approval_service.py`, find where `daily_loss_breached` is currently called and
replace that call with both new breakers, engaging the kill switch on either:

```python
                    from src.execution.circuit_breakers import (
                        drawdown_breached,
                        mark_based_loss,
                    )
                    from src.storage.system_settings import set_halted

                    loss = mark_based_loss(positions, account.net_liquidation)
                    dd = drawdown_breached(account.net_liquidation)
                    if loss is not None:
                        set_halted(True, f"Daily mark-to-market loss ${loss:,.0f}")
                    elif dd is not None:
                        set_halted(True, f"Drawdown ${dd:,.0f} from high-water mark")
```

Match the surrounding variable names (`positions`, `account`) to whatever that scope actually
uses; read the enclosing function before editing.

- [ ] **Step 7: Run the full suite**

Run: `python -m pytest -q && ruff check . && mypy src`
Expected: all green.

- [ ] **Step 8: Update docs**

- `ARCHITECTURE.md`: describe both breakers in the `src/execution/` section.
- `STATUS.md`: correct the AUTOMATED-mode circuit-breaker bullet, which currently describes the cashflow measure.
- `SETUP.md`: document `daily_loss_halt_pct` (now mark-based) and `drawdown_halt_pct`.

- [ ] **Step 9: Commit**

```bash
git add src/execution/circuit_breakers.py src/storage/system_settings.py src/common/config.py config/settings.yaml src/notify/approval_service.py tests/test_circuit_breakers.py ARCHITECTURE.md STATUS.md SETUP.md
git commit -m "fix(execution): mark-based and drawdown kill switches

Fixes the second half of D3. The loss breaker summed FillRow cashflow, so a
day selling premium into a 15% drawdown registered as a profit and the
switch stayed open while the loop opened more shorts into the move.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 12: Defensive-roll economics and the rolling date bug

**Files:**
- Modify: `src/strategies/rolling.py`
- Modify: `config/settings.yaml`, `src/common/config.py` (MonitorCfg)
- Test: `tests/test_roll_pipeline.py`

**Interfaces:**
- Produces: `generate_roll_candidates(position, quotes, iv_stats, tech_stats, *, defensive: bool = False)`. When `defensive=True`, ROC and annualized-yield tests are skipped, a bounded net debit is permitted, and the new leg must reduce |delta| by at least `min_delta_reduction`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_roll_pipeline.py — append
def test_defensive_roll_allows_a_bounded_debit():
    """D4: a challenged 0.60-delta short cannot be rolled out for a credit."""
    from src.strategies.rolling import generate_roll_candidates

    pos = _short_call(delta=-0.62, strike=100.0, dte=10)
    quotes = _roll_chain(current_mid=8.00, new_mid=7.70, new_delta=-0.30, new_dte=35)
    cands = generate_roll_candidates(pos, quotes, _iv(), _tech(), defensive=True)
    assert cands, "a defensive roll costing $0.30 must be offered"
    assert cands[0].premium == pytest.approx(-0.30, abs=0.01)


def test_defensive_roll_rejects_a_debit_above_the_cap():
    from src.strategies.rolling import generate_roll_candidates

    pos = _short_call(delta=-0.62, strike=100.0, dte=10)
    quotes = _roll_chain(current_mid=8.00, new_mid=7.00, new_delta=-0.30, new_dte=35)
    assert not generate_roll_candidates(pos, quotes, _iv(), _tech(), defensive=True)


def test_defensive_roll_requires_delta_reduction():
    from src.strategies.rolling import generate_roll_candidates

    pos = _short_call(delta=-0.62, strike=100.0, dte=10)
    quotes = _roll_chain(current_mid=8.00, new_mid=8.20, new_delta=-0.60, new_dte=35)
    assert not generate_roll_candidates(pos, quotes, _iv(), _tech(), defensive=True)


def test_income_roll_still_requires_a_credit_and_roc():
    from src.strategies.rolling import generate_roll_candidates

    pos = _short_call(delta=-0.30, strike=100.0, dte=15)
    quotes = _roll_chain(current_mid=1.00, new_mid=0.90, new_delta=-0.28, new_dte=40)
    assert not generate_roll_candidates(pos, quotes, _iv(), _tech(), defensive=False)


def test_roll_dte_uses_et_not_local_date(monkeypatch):
    """D4: rolling.py:39 used date.today(), firing a day early in UTC+8."""
    import src.strategies.rolling as rolling

    called = {}
    monkeypatch.setattr(rolling, "today_et", lambda: called.setdefault("hit", True) or _ET_TODAY)
    generate_roll_candidates(_short_call(delta=-0.30, strike=100.0, dte=15), [], _iv(), _tech())
    assert called.get("hit"), "generate_roll_candidates must use today_et()"
```

Add these helpers at the top of `tests/test_roll_pipeline.py` (import `Regime` and
`OptionRight` from `src.common.schemas`):

```python
from datetime import timedelta

from src.common.market_hours import today_et
from src.common.schemas import (
    IVStats, OptionQuote, OptionRight, PositionSnapshot, Regime, TechnicalStats,
)

_ET_TODAY = today_et()


def _short_call(*, delta: float, strike: float, dte: int) -> PositionSnapshot:
    return PositionSnapshot(
        symbol="AAPL  CALL",
        sec_type="OPT",
        position=-1,
        avg_cost=100.0,
        right=OptionRight.CALL,
        strike=strike,
        expiry=_ET_TODAY + timedelta(days=dte),
        underlying="AAPL",
        delta=delta,
    )


def _quote(*, strike: float, dte: int, mid: float, delta: float) -> OptionQuote:
    return OptionQuote(
        underlying="AAPL",
        right=OptionRight.CALL,
        strike=strike,
        expiry=_ET_TODAY + timedelta(days=dte),
        bid=round(mid - 0.05, 2),
        ask=round(mid + 0.05, 2),
        delta=delta,
        iv=0.30,
        open_interest=500,
        volume=100,
    )


def _roll_chain(
    *, current_mid: float, new_mid: float, new_delta: float, new_dte: int
) -> list[OptionQuote]:
    """The position's own contract (so _infer_current_mid resolves) plus one roll target."""
    return [
        _quote(strike=100.0, dte=10, mid=current_mid, delta=-0.62),
        _quote(strike=105.0, dte=new_dte, mid=new_mid, delta=new_delta),
    ]


def _iv() -> IVStats:
    return IVStats(symbol="AAPL", current_iv=30.0, iv_rank=55.0, hv_30=25.0)


def _tech() -> TechnicalStats:
    return TechnicalStats(symbol="AAPL", price=100.0, regime=Regime.SIDEWAYS)
```

Check `OptionQuote`'s required fields in `src/common/schemas.py` before writing — if
`open_interest`/`volume` have different names, match the schema, and ensure the values chosen
clear `passes_liquidity_gates`.

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_roll_pipeline.py -k "defensive or et_not_local" -q`
Expected: FAIL — `TypeError: generate_roll_candidates() got an unexpected keyword argument 'defensive'`

- [ ] **Step 3: Fix the date bug and add the defensive path**

In `src/strategies/rolling.py`, replace the import `from datetime import date as date_cls` with:

```python
from src.common.market_hours import today_et
```

Change the signature and DTE computation:

```python
def generate_roll_candidates(
    position: PositionSnapshot,
    quotes: list[OptionQuote],
    iv_stats: IVStats,
    tech_stats: TechnicalStats,
    *,
    defensive: bool = False,
) -> list[TradeCandidate]:
    """Return ranked roll candidates for the given short option *position*.

    Two economics, deliberately separated (D4). An **income** roll rolls an unchallenged
    position forward for a credit and must clear the ROC/yield gates. A **defensive** roll
    rescues a challenged short and is judged on risk reduction instead: it may cost a bounded
    debit and must materially reduce |delta|. Requiring 1% ROC from a defensive roll meant the
    candidate list was empty exactly when the monitor fired, because a 0.60-delta short cannot
    be rolled to a 0.30-delta strike for a credit.
    """
```

Replace line 39:

```python
    pos_dte = (position.expiry - today_et()).days
```

Replace the economics block (lines 85-108) with:

```python
        if current_mid is None:
            continue
        roll_credit = new_mid - current_mid

        if defensive:
            max_debit = float(roll_cfg.get("max_debit", 0.50))
            min_reduction = float(roll_cfg.get("min_delta_reduction", 0.10))
            require_be = bool(roll_cfg.get("require_breakeven_improvement", True))
            if roll_credit < -max_debit:
                continue
            if pos_delta_abs is not None and (pos_delta_abs - delta_abs) < min_reduction:
                continue
            if require_be and position.strike is not None:
                improves = (
                    quote.strike < position.strike
                    if position.right == OptionRight.PUT
                    else quote.strike > position.strike
                )
                if not improves and roll_credit <= 0:
                    continue
            roc_pct = 0.0
            annualized_yield_pct = 0.0
        else:
            if roll_credit <= 0:
                continue
            roc_basis = quote.strike
            roc_pct = (roll_credit / roc_basis) * 100 if roc_basis > 0 else 0.0
            annualized_yield_pct = roc_pct * (365 / new_dte) if new_dte > 0 else 0.0
            if roc_pct < income_cfg["min_roc_pct"]:
                continue
            if annualized_yield_pct < income_cfg["min_annualized_yield_pct"]:
                continue

        collateral = quote.strike * contracts * 100
```

Add near the other config reads:

```python
    roll_cfg = get_config().monitor.roll_defensive if defensive else {}
```

- [ ] **Step 4: Add the config**

In `src/common/config.py`, `MonitorCfg`:

```python
    # Manage mechanically at this DTE — entries are 21-45 DTE and the roll trigger fires at
    # dte_threshold (7), which is deep into gamma with no room to manoeuvre.
    manage_at_dte: int = 21
    # Defensive-roll economics. A roll that rescues a challenged short is judged on risk
    # reduction, not yield: it may cost a bounded debit and must reduce |delta| materially.
    roll_defensive: dict[str, float | bool] = Field(
        default_factory=lambda: {
            "max_debit": 0.50,
            "min_delta_reduction": 0.10,
            "require_breakeven_improvement": True,
        }
    )
```

In `config/settings.yaml`, under `monitor:`:

```yaml
  # Mechanical management point. Entries are 21-45 DTE; dte_threshold (7) is deep into gamma.
  manage_at_dte: 21
  # Defensive rolls are judged on risk reduction, not yield — requiring 1% ROC from a roll
  # meant the candidate list was empty exactly when the monitor fired.
  roll_defensive:
    max_debit: 0.50
    min_delta_reduction: 0.10
    require_breakeven_improvement: true
```

- [ ] **Step 5: Pass `defensive=True` from the roll pipeline**

In `src/execution/roll_pipeline.py`, find the `generate_roll_candidates(` call and pass
`defensive=True` — every roll originating from a monitor trigger is by definition defensive.

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest -q && ruff check . && mypy src`
Expected: all green.

- [ ] **Step 7: Update docs**

- `ARCHITECTURE.md`: document the two roll economics in the `src/strategies/` section.
- `STATUS.md`: add to the 2026-08-10 bug-fix section — D4 and the residual `date_cls.today()` the 2026-08-06 audit missed.

- [ ] **Step 8: Commit**

```bash
git add src/strategies/rolling.py src/common/config.py config/settings.yaml src/execution/roll_pipeline.py tests/test_roll_pipeline.py ARCHITECTURE.md STATUS.md
git commit -m "fix(strategies): defensive rolls judged on risk, not yield

Fixes D4. A roll needed net credit >= 1% ROC and >= 12% annualized —
economics a challenged 0.60-delta short cannot produce — so the roll list
was empty precisely when the monitor fired. Also fixes rolling.py:39's
date_cls.today(), which fires should_roll a day early in UTC+8.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 13: Manage at 21 DTE

**Files:**
- Modify: `src/monitor/triggers.py`
- Test: `tests/test_monitor.py`

**Interfaces:**
- Consumes: `MonitorCfg.manage_at_dte` (Task 12).
- Produces: `triggers.check_manage_at_dte(pos: PositionSnapshot, manage_dte: int) -> RollAlert | None`, wired into `check_all`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_monitor.py — append
def test_manage_at_dte_fires_inside_the_window():
    from datetime import timedelta

    from src.common.market_hours import today_et
    from src.monitor.triggers import check_manage_at_dte

    pos = _short_position(expiry=today_et() + timedelta(days=20))
    alert = check_manage_at_dte(pos, 21)
    assert alert is not None
    assert alert.trigger == "manage_dte"


def test_manage_at_dte_silent_outside_the_window():
    from datetime import timedelta

    from src.common.market_hours import today_et
    from src.monitor.triggers import check_manage_at_dte

    pos = _short_position(expiry=today_et() + timedelta(days=30))
    assert check_manage_at_dte(pos, 21) is None


def test_manage_at_dte_ignores_long_positions():
    from datetime import timedelta

    from src.common.market_hours import today_et
    from src.monitor.triggers import check_manage_at_dte

    pos = _short_position(expiry=today_et() + timedelta(days=10), qty=1)
    assert check_manage_at_dte(pos, 21) is None
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_monitor.py -k manage_at_dte -q`
Expected: FAIL — `ImportError: cannot import name 'check_manage_at_dte'`

- [ ] **Step 3: Implement the trigger**

In `src/monitor/triggers.py`, after `check_dte_threshold`:

```python
def check_manage_at_dte(
    pos: PositionSnapshot,
    manage_dte: int,
) -> RollAlert | None:
    """Fire at the mechanical management point, well before the gamma window.

    Entries sit at 21-45 DTE and ``check_dte_threshold`` fires at 7 days — by then the
    position has little extrinsic left and few good options. This is the decision point where
    closing, rolling, or explicitly holding are all still available.
    """
    if pos.position >= 0 or pos.expiry is None:
        return None
    dte = (pos.expiry - today_et()).days
    if dte > manage_dte:
        return None
    return RollAlert(
        position_symbol=pos.symbol,
        underlying=pos.underlying or pos.symbol,
        trigger="manage_dte",
        detail=(
            f"{dte} days left — the {manage_dte}-day management point. Close, roll, or "
            f"decide to hold while extrinsic value still makes all three viable"
        ),
        dte=dte,
    )
```

In `check_all`, after the `check_dte_threshold` block:

```python
    alert = check_manage_at_dte(pos, limits.get("manage_at_dte", 21))
    if alert:
        alerts.append(alert)
```

- [ ] **Step 4: Add the trigger label**

In `src/notify/formatters.py`, `_TRIGGER_LABELS`:

```python
    "manage_dte": "management point",
```

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS

- [ ] **Step 6: Update docs**

`ARCHITECTURE.md` and `STATUS.md`: the monitor now has six triggers, not five. Update both counts and the trigger lists.

- [ ] **Step 7: Commit**

```bash
git add src/monitor/triggers.py src/notify/formatters.py tests/test_monitor.py ARCHITECTURE.md STATUS.md
git commit -m "feat(monitor): mechanical management trigger at 21 DTE

Entries are 21-45 DTE and the roll trigger fired at 7 days, deep into
gamma with no room to manoeuvre.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 14: The autonomy ladder

**Files:**
- Modify: `src/common/schemas.py` (AutonomyLevel)
- Modify: `src/storage/system_settings.py`
- Modify: `src/notify/sender.py:268`, `src/notify/approval_service.py`
- Modify: `src/notify/formatters.py`
- Create: `tests/test_autonomy.py`

**Interfaces:**
- Produces:
  - `schemas.AutonomyLevel` — `StrEnum` with `OBSERVE = "observe"`, `MANUAL = "manual"`, `WHITELIST = "whitelist"`, `FULL = "full"`.
  - `system_settings.get_autonomy_level() -> AutonomyLevel`, `set_autonomy_level(level: AutonomyLevel) -> None`, `AUTONOMY_LEVEL_KEY`.
  - `system_settings.may_auto_open(symbol: str) -> bool`.
- Replaces: `is_automated_mode()` / `set_automated_mode()` — deleted, all call sites migrated.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_autonomy.py
"""The autonomy ladder: autonomy is arrived at with evidence, not switched on."""

from __future__ import annotations

import pytest

from src.common.schemas import AutonomyLevel


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    from tests.conftest import use_temp_db  # existing helper

    use_temp_db(tmp_path, monkeypatch)


def test_default_level_is_observe():
    from src.storage.system_settings import get_autonomy_level

    assert get_autonomy_level() == AutonomyLevel.OBSERVE


def test_observe_never_auto_opens():
    from src.storage.system_settings import may_auto_open, set_autonomy_level

    set_autonomy_level(AutonomyLevel.OBSERVE)
    assert may_auto_open("SPY") is False


def test_manual_never_auto_opens():
    from src.storage.system_settings import may_auto_open, set_autonomy_level

    set_autonomy_level(AutonomyLevel.MANUAL)
    assert may_auto_open("SPY") is False


def test_whitelist_opens_only_listed_symbols(monkeypatch):
    from src.storage.system_settings import may_auto_open, set_autonomy_level

    set_autonomy_level(AutonomyLevel.WHITELIST)
    monkeypatch.setattr(
        "src.storage.system_settings._autonomy_whitelist", lambda: {"SPY", "QQQ"}
    )
    assert may_auto_open("SPY") is True
    assert may_auto_open("MARA") is False


def test_full_opens_anything():
    from src.storage.system_settings import may_auto_open, set_autonomy_level

    set_autonomy_level(AutonomyLevel.FULL)
    assert may_auto_open("MARA") is True


def test_halted_blocks_every_level():
    from src.storage.system_settings import may_auto_open, set_autonomy_level, set_halted

    set_autonomy_level(AutonomyLevel.FULL)
    set_halted(True, "test")
    assert may_auto_open("SPY") is False


def test_promotion_is_refused_without_evidence():
    """A ladder you can skip rungs on is the old binary with more words."""
    from src.storage.system_settings import promotion_blockers, set_autonomy_level

    set_autonomy_level(AutonomyLevel.MANUAL)
    blockers = promotion_blockers(AutonomyLevel.WHITELIST)
    assert any("fills" in b for b in blockers)
    assert any("close" in b for b in blockers)


def test_demotion_is_always_allowed():
    from src.storage.system_settings import promotion_blockers, set_autonomy_level

    set_autonomy_level(AutonomyLevel.WHITELIST)
    assert promotion_blockers(AutonomyLevel.MANUAL) == []
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_autonomy.py -q`
Expected: FAIL — `ImportError: cannot import name 'AutonomyLevel'`

- [ ] **Step 3: Add the enum**

In `src/common/schemas.py`, beside the other `StrEnum` definitions:

```python
class AutonomyLevel(StrEnum):
    """How much the system may do without a human tap.

    Auto-CLOSE is on from MANUAL upward and is governed separately by
    ``automation.auto_close_enabled`` — this ladder governs *opening* exposure only.
    """

    OBSERVE = "observe"      # proposals only; never opens, never closes
    MANUAL = "manual"        # human tap to open; closes automatically
    WHITELIST = "whitelist"  # opens whitelisted symbols automatically
    FULL = "full"            # opens anything that passes the gates
```

- [ ] **Step 4: Add the accessors**

In `src/storage/system_settings.py`, replace `AUTOMATED_MODE_KEY` and both
`is_automated_mode`/`set_automated_mode` functions with:

```python
AUTONOMY_LEVEL_KEY = "autonomy_level"
AUTONOMY_WHITELIST_KEY = "autonomy_whitelist"


def get_autonomy_level() -> AutonomyLevel:
    """Current autonomy rung. Defaults to OBSERVE — the safe rung for a fresh install."""
    raw = get_setting(AUTONOMY_LEVEL_KEY, AutonomyLevel.OBSERVE.value).lower()
    try:
        return AutonomyLevel(raw)
    except ValueError:
        log.warning("Unknown autonomy level %r — falling back to observe", raw)
        return AutonomyLevel.OBSERVE


def set_autonomy_level(level: AutonomyLevel) -> None:
    set_setting(AUTONOMY_LEVEL_KEY, level.value)


def _autonomy_whitelist() -> set[str]:
    raw = get_setting(AUTONOMY_WHITELIST_KEY, "")
    return {s.strip().upper() for s in raw.split(",") if s.strip()}


def set_autonomy_whitelist(symbols: set[str]) -> None:
    set_setting(AUTONOMY_WHITELIST_KEY, ",".join(sorted(symbols)))


def may_auto_open(symbol: str) -> bool:
    """True when the system may open new exposure in *symbol* without a human tap.

    The kill switch overrides every rung — closing risk stays permitted while halted, but
    opening it never is.
    """
    if is_halted():
        return False
    level = get_autonomy_level()
    if level in (AutonomyLevel.OBSERVE, AutonomyLevel.MANUAL):
        return False
    if level == AutonomyLevel.FULL:
        return True
    return symbol.upper() in _autonomy_whitelist()
```

Add `from src.common.schemas import AutonomyLevel` to the imports.

- [ ] **Step 5: Migrate every call site**

Run `grep -rn "is_automated_mode\|set_automated_mode" src tests scripts` and update each:

- `src/notify/sender.py:268` — replace `if is_automated_mode():` with a per-candidate partition: candidates where `may_auto_open(c.underlying)` go to `_auto_queue_candidates`, the rest to `_send_with_session`. At `OBSERVE`, send neither buttons nor orders — send the card with a "proposal only" footer.
- `src/execution/profit_take.py:258` — replace `if is_automated_mode() and ib_exec is not None:` with `if cfg.automation.auto_close_enabled and ib_exec is not None:`. Closing no longer depends on the ladder.
- `src/notify/approval_service.py:825, 918, 1217, 1547` — display and routing; use `get_autonomy_level()`.

- [ ] **Step 6: Replace `/mode` with `/autonomy`**

In `src/notify/approval_service.py`, rename `handle_mode_command` to `handle_autonomy_command`
and register it as `CommandHandler("autonomy", handle_autonomy_command)`. Accept an optional
argument (`/autonomy whitelist`); with no argument, report the current rung and the promotion
criteria for the next one. Remove the `mode:` `CallbackQueryHandler` and
`handle_mode_toggle`.

Promotion must be **refused when the criteria are unmet** — autonomy is arrived at with
evidence, and a ladder you can skip rungs on is just the old binary with more words. Add to
`src/storage/system_settings.py`:

```python
def promotion_blockers(target: AutonomyLevel) -> list[str]:
    """Unmet criteria for promoting to *target*. Empty list means promotion is allowed.

    Demotion is always permitted — reducing autonomy needs no evidence.
    """
    from sqlalchemy import func, select

    from src.storage.models import FillRow, OrderRow

    order = [AutonomyLevel.OBSERVE, AutonomyLevel.MANUAL,
             AutonomyLevel.WHITELIST, AutonomyLevel.FULL]
    if order.index(target) <= order.index(get_autonomy_level()):
        return []

    blockers: list[str] = []
    try:
        with session_scope() as s:
            fills = s.execute(select(func.count()).select_from(FillRow)).scalar_one()
            attempts = s.execute(select(func.count()).select_from(OrderRow)).scalar_one()
            closes = s.execute(
                select(func.count())
                .select_from(OrderRow)
                .where(OrderRow.candidate_id.like("close:%"))
            ).scalar_one()
    except Exception:
        return ["could not read fill history"]

    if target in (AutonomyLevel.WHITELIST, AutonomyLevel.FULL):
        if fills < 20:
            blockers.append(f"needs >=20 fills, has {fills}")
        rate = (fills / attempts) if attempts else 0.0
        if rate < 0.60:
            blockers.append(f"fill rate {rate:.0%} is below the 60% gate")
        if closes < 1:
            blockers.append("no risk-reducing close has fired yet")
    return blockers
```

`handle_autonomy_command` calls `promotion_blockers(target)` and, when it returns a non-empty
list, refuses the change and reports each blocker.

- [ ] **Step 7: Show the ladder in `/status`**

In `src/notify/formatters.py`, `format_status`, replace the MANUAL/AUTOMATED line with the
current rung plus progress toward the next, using the §6.1 criteria: fills recorded, measured
fill rate, whether a loss exit has fired.

- [ ] **Step 8: Run the full suite**

Run: `python -m pytest -q && ruff check . && mypy src`
Expected: all green. Existing tests referencing `is_automated_mode` must be migrated, not
deleted.

- [ ] **Step 9: Update docs**

- `README.md` and `SETUP.md` Telegram command tables: `/mode` → `/autonomy`.
- `ARCHITECTURE.md` commands table and `src/storage/` section.
- `STATUS.md`: replace the "MANUAL / AUTOMATED mode toggle" bullet with the four-rung ladder and its promotion gates.

- [ ] **Step 10: Commit**

```bash
git add src/common/schemas.py src/storage/system_settings.py src/notify/ src/execution/profit_take.py tests/ README.md SETUP.md ARCHITECTURE.md STATUS.md
git commit -m "feat(autonomy): four-rung ladder replacing the MANUAL/AUTO binary

observe -> manual -> whitelist -> full, with auto-close independent from
manual upward. Autonomy becomes somewhere you arrive with evidence rather
than a switch you flip.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

# Phase 3 — Validation and cleanup

### Task 15: The live paper validation session

**Files:**
- Create: `docs/live-validation-2026-08.md`
- Modify: `config/settings.yaml` (resolve default-off flags)
- Modify: `STATUS.md`

**This task is measurement, not code.** It has no test cycle; its deliverable is recorded
evidence. Do not skip it — it gates every remaining default-off flag, and question 4 can
silently block 100% of live trades.

**Prerequisite:** TWS or IB Gateway running on the paper port (4002) with the API enabled, during
regular trading hours.

- [ ] **Step 1: Create the record file**

```markdown
# Live paper validation — August 2026

Answers the five questions in the design spec §7.4. Every default-off execution flag depends
on these; until they are answered, nothing in the execution path has been exercised against a
real broker.

| # | Question | Answer | Evidence |
|---|---|---|---|
| 1 | Fill rate of a mid-price DAY limit over 5 min, by liquidity tier (n >= 20) | | |
| 2 | Does `reprice_enabled: true` amend work (same orderId)? | | |
| 3 | Is the BAG combo sign convention correct (negative limit = net credit)? | | |
| 4 | Does `greeks_source == "ibkr"` ever populate on this subscription? | | |
| 5 | Do Tier 3 names (SOXL, MARA, RGTI) produce candidates end-to-end? | | |

## Method

Paper TWS/Gateway on port 4002, API enabled, regular trading hours. Autonomy at `manual`.
Each question below records the raw observation, not a summary — a later reader must be able
to disagree with the conclusion.

### Q1 — fill rate
For every approved order, record from `OrderRow`: symbol, liquidity tier (Tier 1/2/3 per
`universe.yaml`), limit price, bid/ask at placement, and terminal state within
`fill_timeout_minutes`. Minimum 20 orders. Report fill rate per tier.

### Q2 — reprice amend
Order id, original limit, amended limit, whether TWS showed one order or two.

### Q3 — BAG sign
Screenshot or transcription of the working combo order in TWS, showing the net limit price
and its sign, before any fill.

### Q4 — greeks source
Count of quotes with `greeks_source == "ibkr"` versus `"black_scholes"` across one full scan,
from `logs/system.log`.

### Q5 — Tier 3 coverage
For SOXL, MARA, RGTI: number of quotes priced, and the gate that stopped each if none passed.

## Conclusions and config changes

One line per flag changed, with the question number that justifies it.
```

- [ ] **Step 2: Answer question 4 first — it is the cheapest and the most dangerous**

Run: `python -m scripts.healthcheck` then a single-symbol scan: `/scan AAPL` from Telegram.
Inspect `logs/system.log` for `greeks_source`. Record the proportion of quotes with
`greeks_source == "ibkr"` versus `"black_scholes"`.

**If it is 0%:** `live_execution.require_ibkr_greeks_when_live: true` would block every live
income trade. Record this prominently, and either obtain the market-data subscription or plan
to set that flag `false` with a written justification before going live.

- [ ] **Step 3: Answer question 5**

Run a full `/scan` and inspect the assessed block for SOXL, MARA, RGTI. Record whether each
produced any priced contract, and if not, which gate stopped it.

- [ ] **Step 4: Answer question 1**

With autonomy at `manual`, approve at least 20 candidates across liquidity tiers over several
sessions. For each, record from `OrderRow`: symbol, limit price, whether it filled within
`fill_timeout_minutes`, and the spread at placement. Compute the fill rate per tier.

**This number decides Phase 2's `manual -> whitelist` promotion gate (>= 60%).**

- [ ] **Step 5: Answer question 2**

Set `execution.reprice_enabled: true`. Place an order deliberately above the market so it
will not fill. Confirm from the logs and TWS that `placeOrder` with the same `orderId` amends
the resting order rather than creating a second one. Revert the flag if it does not.

- [ ] **Step 6: Answer question 3**

With `monitor.roll_execution_enabled: true` and a single open short, trigger a roll and
inspect the BAG order in TWS **before it fills**: confirm a net credit is expressed as a
negative limit price. If the sign is inverted, fix `order_builder.build_combo_roll_order` and
its tests before re-enabling.

- [ ] **Step 7: Resolve the flags and record**

Update `config/settings.yaml` to reflect what was proven, and update `STATUS.md`'s
"needs live verification" list — removing each item that is now answered and recording the
answer. Link `docs/live-validation-2026-08.md` from `STATUS.md`.

- [ ] **Step 8: Commit**

```bash
git add docs/live-validation-2026-08.md config/settings.yaml STATUS.md
git commit -m "docs: record live paper validation results

Answers the five open broker-path questions. Nothing in the execution path
had previously been exercised against a real broker.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 16: Deletions

**Files:**
- Delete: `src/claude/skills/`, `src/claude/eval/metrics.py`, `src/common/profile.py`, `config/profiles/`, `scripts/propose_skill.py`, `scripts/skills.py`, `scripts/evaluate_verdicts.py`
- Modify: every `get_effective_risk()` / `get_effective_weights()` call site
- Modify: `src/storage/models.py` (drop `OptionQuoteRow`), `src/storage/maintenance.py`
- Modify: `config/scoring_weights.yaml`
- Test: `tests/test_eval_skills.py` and others

**Do this as three separate commits** — the profile removal touches many files and must be
independently revertible.

- [ ] **Step 1: Remove the skills loop and verdict EV**

```bash
git rm -r src/claude/skills
git rm src/claude/eval/metrics.py scripts/propose_skill.py scripts/skills.py scripts/evaluate_verdicts.py
```

Remove `render_active_skills()` calls from `src/claude/prompts/strategist.py` and the roll
prompt builder, plus `ClaudeCfg.skills_enabled` from `src/common/config.py` and
`claude.skills_enabled` from `config/settings.yaml`. Delete the corresponding tests in
`tests/test_eval_skills.py`, **keeping** `test_skills_never_reach_the_engine` and
`test_fair_value_stays_in_the_deterministic_tier` — rewrite the former to assert that nothing
under `src/claude/` is importable from `engine/`, `execution/`, or `strategies/`, which is the
invariant that actually matters now.

Run: `python -m pytest -q && ruff check . && mypy src`

```bash
git add -A && git commit -m "chore: remove the skill-proposal loop and verdict EV scoring

Both measured the calibration of a model whose verdict is deliberately
inert in auto mode, and needed years of closed trades to signal. The
outcome ledger and reconciler are kept — they are cheap and useful.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

- [ ] **Step 2: Remove named profiles**

```bash
git rm -r config/profiles src/common/profile.py
```

Replace every `get_effective_risk()` with `get_config().risk` and every
`get_effective_weights()` with `get_config().weights`. Find them with:

```bash
grep -rn "get_effective_risk\|get_effective_weights\|active_profile" src scripts tests
```

Remove `handle_profile_command` and its `CommandHandler("profile", ...)` registration from
`src/notify/approval_service.py`, and `ACTIVE_PROFILE_KEY`/`get_active_profile`/
`set_active_profile` from `src/storage/system_settings.py`.

Run: `python -m pytest -q && ruff check . && mypy src`

```bash
git add -A && git commit -m "chore: remove named trading profiles

Four parameter overlays on a system that has not validated one set live.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

- [ ] **Step 3: Remove the dead table and weights**

Drop `OptionQuoteRow` from `src/storage/models.py`, `persist_chain_quotes` from wherever it is
defined, its call site in `src/orchestrator/scan.py` (~line 1170), and
`purge_old_option_quotes` from `src/storage/maintenance.py` plus its EOD call.

In `config/scoring_weights.yaml`, remove the `annualized_roc` key from both blocks and remove
`annualized_roc_score` from `src/strategies/_scoring.py` and `ScoreCard`.

Run: `python -m pytest -q && ruff check . && mypy src`

- [ ] **Step 4: Update all docs**

`README.md` layout table, `ARCHITECTURE.md` folder guide and commands table, `STATUS.md`
(remove every deleted feature from "What is built"; add a "Removed 2026-08-10" section
explaining why), `SETUP.md` scripts and commands tables.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore: drop option_quotes table and the annualized_roc weight

option_quotes was write-only with a pruning job and no readers;
annualized_roc is superseded by the VRP floor.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 17: Split `scan.py`

**Files:**
- Create: `src/orchestrator/scan_pipeline.py`, `src/orchestrator/scan_progress.py`
- Modify: `src/orchestrator/scan.py`
- Test: existing `tests/test_scan_*.py` must pass unchanged

**Interfaces:**
- `scan_progress.py` owns `_Tracker` and every Telegram edit — the only module in this trio that imports from `src.notify`.
- `scan_pipeline.py` owns the per-symbol fetch/analytics/screen loop and returns data.
- `scan.py` keeps `run_scan` and `ScanResult` as the public entry point, orchestrating the other two.

**Why now:** Phase 5's API must trigger a scan and read its result without importing the
Telegram layer. Doing this after the API exists means the API grows a Telegram dependency it
can never shed.

- [ ] **Step 1: Confirm the safety net**

Run: `python -m pytest tests/test_scan_memory.py tests/test_scan_materiality.py tests/test_scan_timeout.py tests/test_scan_tracker.py tests/test_scan_review_reuse.py tests/test_ticker_scan_format.py -q`
Expected: PASS. These are the behaviour contract; they must not be modified during this task.

- [ ] **Step 2: Extract the progress tracker**

Move `_Tracker` and its helpers into `src/orchestrator/scan_progress.py`. Import it back into
`scan.py`. Change nothing else.

Run: `python -m pytest -q` — expected PASS.

```bash
git add -A && git commit -m "refactor(orchestrator): extract scan progress tracking

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

- [ ] **Step 3: Extract the per-symbol pipeline**

Move the per-symbol loop body (chain fetch, spot resolution, analytics, sentiment, CC/CSP
screening) into `scan_pipeline.py` as a function taking explicit inputs and returning
candidates plus provenance — no Telegram calls, no `_Tracker`. `scan.py` calls it per symbol
and reports progress itself.

Run: `python -m pytest -q` — expected PASS.

```bash
git add -A && git commit -m "refactor(orchestrator): extract the per-symbol scan pipeline

Separates data production from presentation so the Phase 5 API can trigger
a scan without importing the Telegram layer.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

- [ ] **Step 4: Verify the separation holds**

Add to `tests/test_eval_skills.py`:

```python
def test_scan_pipeline_does_not_import_the_notify_layer():
    """The Phase 5 API triggers scans; it must not drag Telegram in."""
    import ast
    import pathlib

    source = pathlib.Path("src/orchestrator/scan_pipeline.py").read_text()
    tree = ast.parse(source)
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
        elif isinstance(node, ast.Import):
            imported.extend(a.name for a in node.names)
    offenders = [m for m in imported if m.startswith("src.notify") or m == "telegram"]
    assert not offenders, f"scan_pipeline must not import the notify layer: {offenders}"
```

Run: `python -m pytest tests/test_eval_skills.py -q` — expected PASS.

- [ ] **Step 5: Update docs and commit**

`ARCHITECTURE.md` `src/orchestrator/` section and `README.md` layout table: add both new
modules and describe the three-way split.

```bash
git add -A
git commit -m "docs: record the orchestrator split

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 18: Phase 1–3 closeout

**Files:**
- Modify: `STATUS.md`, `ARCHITECTURE.md`, `README.md`, `CLAUDE.md`

- [ ] **Step 1: Run the whole gate**

Run: `python -m pytest -q && ruff check . && ruff format --check . && mypy src`
Expected: all green. Record the test count.

- [ ] **Step 2: Re-run the capacity report and record the outcome**

Run: `python -m scripts.capacity_report --net-liq 300000 --cash 100000`

Paste the output into `STATUS.md` under a "Tradeable capacity at $300k (2026-08)" heading.
This is the evidence that D1 and D2 are actually fixed, as distinct from the tests passing.

- [ ] **Step 3: Reconcile `STATUS.md` with reality**

Walk the whole file. Every bullet describing behaviour changed in Phases 1–3 must be corrected:
the collateral model, the income gates, the exits, the circuit breakers, the mode toggle, the
monitor's trigger count, the deleted subsystems, and the resolved live-verification items.

- [ ] **Step 4: Update `CLAUDE.md`**

The "Analytics tiers" section describes `fair_value.py` as display-plus-optional-ranking. It is
now a **gate**. Update that paragraph, keeping the tier constraint (it may still read only
technicals, IV, fundamentals, and Black-Scholes) and the reason the constraint matters.

Also remove the `config/profiles/` reference and the skills-loop paragraph from the fence
section, keeping the fence itself.

- [ ] **Step 5: Commit**

```bash
git add STATUS.md ARCHITECTURE.md README.md CLAUDE.md
git commit -m "docs: reconcile documentation with Phases 1-3

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Verification checklist

Before declaring Phases 1–3 complete:

- [ ] `python -m pytest -q` — all green, count >= 1,088 minus tests deleted with their subsystems
- [ ] `ruff check . && ruff format --check .` — clean
- [ ] `mypy src` — clean
- [ ] `python -m scripts.capacity_report --net-liq 300000 --cash 100000` — a clear majority of `would_own` tradeable, and no symbol refused for a non-affordability reason
- [ ] `tests/test_eval_skills.py` — fence tests green, including the new `scan_pipeline` import test
- [ ] `docs/live-validation-2026-08.md` — all five questions answered
- [ ] A loss exit has fired at least once on paper, with the Telegram notice observed
- [ ] A circuit breaker has been tripped deliberately and `/resume` clears it
- [ ] Autonomy is at `manual`, and `/status` reports honest progress toward `whitelist`
