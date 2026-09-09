# Milestone 4 — The P&L engine

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or
> superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** One implementation of paired realised P&L in this repository, in a package the web layer
may read and the trading path may not import, producing leg rows and campaign threads that agree
with the outcome ledger by construction rather than by coincidence.

**Spec:** `Web plan/P3-P4-design.md` §6. **Index:** `Web plan/P3-P4-IMPLEMENTATION-PLAN.md`.
**Depends on:** Milestone 3.

**No routes and no UI in this milestone.** Everything here is a pure function with a test.

**The shape of this milestone in one sentence:** the accounting rule already exists inside
`src/claude/eval/reconcile.py` and this milestone **takes it over** rather than writing a second
one — if you find yourself implementing "credit minus debit minus commissions" from scratch, stop
and re-read spec §6.2.

---

## Task 4.1 — Extract the accounting rule into `src/reporting/legs.py` `[SONNET]`

**The highest-risk task in the phase.** It moves two functions that decide whether a closed trade
is recorded as assigned or expired, and what P&L the outcome ledger stores for it.

**Context.** `src/claude/eval/reconcile.py` contains, as module-private functions:

- `_fill_economics(fills) -> (credit_dollars, debit_dollars, commissions, entry_premium, entry_qty)`
- `_classify(candidate_id, fills, approval, order, expiry, today, assigned) -> (outcome, realized_pnl, filled, entry_premium, contracts)`
- `OPTION_MULTIPLIER = 100`

Both are pure. Both are exactly P4's accounting rule. They sit behind the fence only because the
reconciler happens to live there.

The move inverts the dependency: `src/reporting/` will import nothing from `src/claude/`, and
`reconcile.py` will import from `src/reporting/`. That is allowed — the fence stops `eval/`
reaching the **engine**, not `eval/` importing a neutral read-only module.

**Files:** Create `src/reporting/__init__.py`, `src/reporting/legs.py`. Modify
`src/claude/eval/reconcile.py`, `tests/test_web_fence.py`, root `CLAUDE.md`, `README.md`,
`ARCHITECTURE.md`, `docs/web/architecture.md`. Test `tests/test_reporting_legs.py`.

**Interfaces:**

```python
# src/reporting/legs.py
OPTION_MULTIPLIER = 100


def fill_economics(fills: list[FillRow]) -> FillEconomics:
    """Split fills into entry (SELL) and close (BUY) legs.

    Moved verbatim from src/claude/eval/reconcile.py::_fill_economics. The tuple return
    became a frozen dataclass; the arithmetic did not change.
    """


@dataclass(frozen=True)
class FillEconomics:
    credit: float          # dollars, SELL fills × OPTION_MULTIPLIER
    debit: float           # dollars, BUY fills × OPTION_MULTIPLIER
    commissions: float     # nulls summed as zero
    commissions_complete: bool   # False when any fill carried a null commission
    entry_premium: float   # per share
    entry_qty: int


def classify_outcome(
    candidate_id: str,
    fills: list[FillRow],
    approval: ApprovalRow | None,
    order: OrderRow | None,
    expiry: date,
    today: date,
    assigned: bool,
) -> ClassifiedOutcome:
    """The outcome decision. Moved verbatim from reconcile.py::_classify.

    Behaviour is unchanged: reconcile.py's own test suite must pass without edits.
    """


@dataclass(frozen=True)
class ClassifiedOutcome:
    outcome: VerdictOutcome
    realized_pnl: float | None
    filled: bool
    entry_premium: float | None
    contracts: int | None
```

```python
# src/claude/eval/reconcile.py — after the move
from src.reporting.legs import OPTION_MULTIPLIER, classify_outcome, fill_economics

# The private names are kept as thin aliases ONLY if something outside this module
# imported them. Grep first. If nothing did, delete them — a compatibility shim nobody
# needs is how two implementations come back.
```

**Design points that are not negotiable:**

1. **The arithmetic does not change.** This is a move, not a rewrite. The one addition is
   `commissions_complete`, which is new information the old tuple did not carry and which no
   existing caller reads.
2. **`reconcile.py`'s existing tests must pass unchanged.** `tests/test_eval.py`,
   `tests/test_assignment.py`, `tests/test_phase6.py` and `tests/test_notify.py` all exercise this
   path. **Not adapted, not relaxed, not re-expected.** If any of them needs an edit to go green,
   the extraction changed behaviour and the task is wrong — revert and find the difference.
3. **`src/reporting/` imports nothing from `src/claude/`.** It may import `src/storage/`,
   `src/common/`, and standard library. A test asserts this.
4. **`src/engine/`, `src/execution/` and `src/strategies/` may never import `src.reporting`.** A
   test asserts this too. `src/reporting/` reads enrichment-side tables; it stays on the read side
   of the tier line exactly as `src/api/` and `src/research/` do.
5. **`docstring` provenance.** `legs.py`'s module docstring says where these functions came from
   and that `reconcile.py` now imports them, so the next reader does not "restore" a copy into
   `eval/`.

Required behaviours, each with a test:
- `fill_economics` returns the same credit, debit, commissions, entry premium and quantity the old
  tuple did, for a table of fill sets written out by hand.
- `commissions_complete` is `False` when any fill has a null commission, `True` when all are
  present, and `True` for an empty fill list with a documented reason.
- `classify_outcome` returns the same outcome and realised P&L for every branch of the decision
  tree in `reconcile.py`'s module docstring: closed-early, expired-worthless, assigned,
  still-open-filled, user-rejected, risk-rejected, not-filled, still-open-unfilled.
- **`src/reporting/` imports nothing from `src.claude`.**
- **No module under `src/engine/`, `src/execution/` or `src/strategies/` imports `src.reporting`.**

- [ ] **Step 1: Before touching anything, record the baseline.**

```bash
python -m pytest tests/test_eval.py tests/test_assignment.py tests/test_phase6.py \
                 tests/test_notify.py -q
```

Write the passing count into the task's notes. This number must be identical after the move. A
different number means behaviour changed.

- [ ] **Step 2: Write the failing test**

```python
"""One accounting rule, in a package the trading path cannot import."""

from __future__ import annotations

from datetime import date

import pytest

from src.common.schemas import VerdictOutcome
from src.reporting.legs import OPTION_MULTIPLIER, classify_outcome, fill_economics
from src.storage.models import ApprovalRow, FillRow, OrderRow


def _sell(qty: float, price: float, commission: float | None = 1.0) -> FillRow:
    return FillRow(candidate_id="c1", order_id=1, action="SELL",
                   filled_qty=qty, avg_price=price, commission=commission)


def _buy(qty: float, price: float, commission: float | None = 1.0) -> FillRow:
    return FillRow(candidate_id="c1", order_id=1, action="BUY",
                   filled_qty=qty, avg_price=price, commission=commission)


def test_credit_and_debit_are_dollars_not_per_share() -> None:
    econ = fill_economics([_sell(2, 1.50), _buy(2, 0.40)])
    assert econ.credit == 2 * 1.50 * OPTION_MULTIPLIER
    assert econ.debit == 2 * 0.40 * OPTION_MULTIPLIER
    assert econ.entry_premium == 1.50
    assert econ.entry_qty == 2


def test_a_null_commission_is_summed_as_zero_and_flagged() -> None:
    """The figure stays usable; the UI must be able to say it is gross."""
    econ = fill_economics([_sell(1, 1.00, commission=None), _buy(1, 0.20, commission=0.65)])
    assert econ.commissions == 0.65
    assert econ.commissions_complete is False


def test_complete_commissions_are_flagged_complete() -> None:
    econ = fill_economics([_sell(1, 1.00, commission=0.65)])
    assert econ.commissions_complete is True


def test_a_bought_back_leg_is_closed_early() -> None:
    out = classify_outcome("c1", [_sell(1, 1.50), _buy(1, 0.40)], None, None,
                           date(2026, 10, 16), date(2026, 10, 1), assigned=False)
    assert out.outcome is VerdictOutcome.CLOSED_EARLY
    assert out.realized_pnl == pytest.approx(150.0 - 40.0 - 2.0)


def test_a_past_expiry_short_with_no_buy_expired_worthless() -> None:
    out = classify_outcome("c1", [_sell(1, 1.50)], None, None,
                           date(2026, 10, 16), date(2026, 10, 17), assigned=False)
    assert out.outcome is VerdictOutcome.EXPIRED_WORTHLESS


def test_an_assigned_flag_changes_the_outcome_not_the_arithmetic() -> None:
    kw = dict(fills=[_sell(1, 1.50)], approval=None, order=None,
              expiry=date(2026, 10, 16), today=date(2026, 10, 17))
    expired = classify_outcome("c1", assigned=False, **kw)
    assigned = classify_outcome("c1", assigned=True, **kw)
    assert assigned.outcome is VerdictOutcome.ASSIGNED
    assert assigned.realized_pnl == expired.realized_pnl


def test_an_open_leg_has_no_realized_pnl() -> None:
    out = classify_outcome("c1", [_sell(1, 1.50)], None, None,
                           date(2026, 12, 18), date(2026, 10, 1), assigned=False)
    assert out.outcome is VerdictOutcome.STILL_OPEN
    assert out.realized_pnl is None


def test_a_rejected_approval_is_user_rejected() -> None:
    out = classify_outcome("c1", [], ApprovalRow(status="rejected"), None,
                           date(2026, 12, 18), date(2026, 10, 1), assigned=False)
    assert out.outcome is VerdictOutcome.USER_REJECTED
    assert out.filled is False


def test_a_rejected_order_is_risk_rejected() -> None:
    out = classify_outcome("c1", [], None, OrderRow(state="rejected"),
                           date(2026, 12, 18), date(2026, 10, 1), assigned=False)
    assert out.outcome is VerdictOutcome.RISK_REJECTED


def test_an_unfilled_past_expiry_candidate_is_not_filled() -> None:
    out = classify_outcome("c1", [], None, None,
                           date(2026, 10, 16), date(2026, 10, 17), assigned=False)
    assert out.outcome is VerdictOutcome.NOT_FILLED
```

- [ ] **Step 3: Add the fence tests** to `tests/test_web_fence.py`, beside the existing ones:

```python
def test_reporting_never_imports_the_enrichment_loop() -> None:
    """src/reporting/ is downstream of everything and upstream of nothing."""
    for path in Path("src/reporting").rglob("*.py"):
        text = path.read_text()
        assert "src.claude" not in text, f"{path} imports the enrichment layer"


def test_the_trading_path_never_imports_reporting() -> None:
    """A report reads the whole book, including enrichment tables. It stays on the read side."""
    for pkg in ("src/engine", "src/execution", "src/strategies"):
        for path in Path(pkg).rglob("*.py"):
            text = path.read_text()
            assert "src.reporting" not in text, f"{path} imports the reporting layer"
```

- [ ] **Step 4: Run the new tests and confirm they fail.**

- [ ] **Step 5: Do the move.** Create `src/reporting/legs.py` with the two functions and the
  constant, converted to dataclass returns. Grep for `_fill_economics` and `_classify` across the
  repo before deleting them — if nothing outside `reconcile.py` imports them, delete rather than
  alias. Rewire `reconcile.py`'s two call sites (`_reconcile_one` returns `_classify`'s tuple;
  unpack the dataclass at the boundary rather than changing the reconciler's own signature).

- [ ] **Step 6: Re-run the baseline from Step 1.** The count must be identical.

```bash
python -m pytest tests/test_eval.py tests/test_assignment.py tests/test_phase6.py \
                 tests/test_notify.py -q
```

**If any of those four files needed an edit to pass, revert and find out why.** They are the
safety property of this task, not an obstacle to it.

- [ ] **Step 7: Run the FULL suite**, then `ruff check .` and `mypy src`.

- [ ] **Step 8: Docs.**
  - Root `CLAUDE.md`, "Analytics tiers" section: add `src/reporting/` as a third, read-only tier —
    downstream of everything, upstream of nothing, never imported by `engine/`, `execution/` or
    `strategies/`. State that `tests/test_web_fence.py` enforces it.
  - `README.md` layout table and `ARCHITECTURE.md` folder guide gain `src/reporting/`.
  - `docs/web/architecture.md` gains the inversion: the fenced reconciler now imports the neutral
    reporting module, not the reverse.
  - `ARCHITECTURE.md`'s `src/claude/eval/` entry for `reconcile.py` notes where the accounting
    moved.

- [ ] **Step 9: Commit.**

```bash
git add src/reporting/ src/claude/eval/reconcile.py tests/test_reporting_legs.py \
        tests/test_web_fence.py CLAUDE.md README.md ARCHITECTURE.md docs/web/architecture.md
git commit -m "refactor(reporting): take the accounting rule out of the fenced reconciler"
```

---

## Task 4.2 — The P&L schemas `[GLM]`

**Files:** Modify `src/common/schemas.py`, `ARCHITECTURE.md`. Test `tests/test_pnl_schemas.py`.

**Interfaces:** exactly these, added beside the existing `VerdictOutcome` and `ScoreOutcomeReport`
definitions.

```python
class PnlLeg(BaseModel):
    """One option contract position, from the fill that opened it to whatever closed it.

    `net_pnl` is None while the leg is open — never 0.0. An open leg has an unrealised
    mark, not a realised result, and a zero in a realised column is a claim.
    """

    candidate_id: str
    campaign_id: str | None = None
    symbol: str
    underlying: str
    strategy: Strategy
    right: OptionRight
    strike: float
    expiry: date
    contracts: int
    opened_at: datetime
    closed_at: datetime | None = None
    credit: float
    debit: float
    commissions: float
    commissions_complete: bool
    net_pnl: float | None = None
    unrealized_pnl: float | None = None
    days_held: int
    roc_pct: float | None = None
    annualized_pct: float | None = None
    outcome: VerdictOutcome
    is_live: bool


class CampaignPnl(BaseModel):
    """A wheel cycle: every option leg on a symbol, plus the stock leg."""

    campaign_id: str
    symbol: str
    status: Literal["open", "closed"]
    opened_date: date
    closed_date: date | None = None
    legs: list[PnlLeg] = Field(default_factory=list)
    option_realized: float = 0.0
    option_unrealized: float | None = None
    stock_realized: float | None = None
    stock_unrealized: float | None = None
    assigned: bool = False
    adjusted_cost_basis: float | None = None
    total_net: float = 0.0


class PnlBucket(BaseModel):
    """Realised performance grouped by one key (a symbol, a strategy)."""

    label: str
    n_closed: int
    realized: float
    win_rate: float | None = None       # None when n_closed is 0, never 0.0
    mean_days_held: float | None = None
    mean_roc_pct: float | None = None


class PnlSummary(BaseModel):
    realized_total: float
    unrealized_total: float | None = None
    commissions_complete: bool
    n_open: int
    n_closed: int
    win_rate: float | None = None
    by_strategy: list[PnlBucket] = Field(default_factory=list)
    by_symbol: list[PnlBucket] = Field(default_factory=list)
    best: PnlLeg | None = None
    worst: PnlLeg | None = None


class EquityPoint(BaseModel):
    entry_date: date
    net_liquidation: float | None = None
    unrealized_pnl: float | None = None
    cumulative_realized: float
    premium_cashflow: float | None = None   # journal.realized_pnl — NOT paired realised P&L


class EquityCurve(BaseModel):
    """Points, and the days between the first and last point that have no point.

    `gaps` exists so the chart can render a gap rather than a straight line across a week
    nobody measured.
    """

    points: list[EquityPoint] = Field(default_factory=list)
    gaps: list[date] = Field(default_factory=list)
    starts_at: date | None = None
```

Required behaviours, each with a test:
- Every model round-trips through `model_dump(mode="json")` and `model_validate`.
- `PnlLeg(net_pnl=None)` is valid and `net_pnl` stays `None`; there is no validator defaulting it.
- `PnlBucket(n_closed=0)` leaves `win_rate` as `None`.
- `EquityCurve()` with no points is valid and has `starts_at is None`.

- [ ] **Step 1: Write the failing test. Step 2: Confirm failure. Step 3: Add the schemas.
  Step 4: Gate. Step 5:** `ARCHITECTURE.md`'s `src/common/` section and data-flow schemas gain all
  six. **Step 6: Commit.**

---

## Task 4.3 — `build_legs` `[SONNET]`

**The accounting. A silent error here is a wrong P&L on a page an operator trusts.**

**Files:** Create `src/reporting/pnl.py`. Test `tests/test_build_legs.py`.

**Interfaces:**

```python
# src/reporting/pnl.py
def build_legs(
    session: Session,
    *,
    since: date | None = None,
    symbol: str | None = None,
    include_paper: bool = True,
    include_live: bool = True,
) -> list[PnlLeg]:
    """Every option leg the system has fills for, newest first.

    One leg per candidate_id that has at least one fill. A candidate with no fill was
    never a position and does not appear.
    """
```

Consumes: `fill_economics`, `classify_outcome`, `ClassifiedOutcome` (Task 4.1); `PnlLeg`
(Task 4.2); `FillRow`, `CandidateRow`, `ApprovalRow`, `OrderRow`, `CampaignRow`
(`src/storage/models.py`); `src.claude.eval.assignment.assigned_candidate_ids` **must not be
imported** — see design point 4.

**Design points that are not negotiable:**

1. **`net_pnl` is `None` for every open leg.** Not `0.0`, not the credit so far. This is the single
   most valuable assertion in P4 and it has its own test.
2. **Contract detail comes from `CandidateRow`.** A leg whose candidate was pruned still appears —
   fills survive pruning and a total that silently drops a row is worse than a row with unknown
   strike. Where the candidate is missing, carry the fields the fill knows and leave the rest at
   their nullable defaults.
3. **Paper and live never mix.** `FillRow.is_live` carries onto the leg, and the two filters
   default to including both so the caller must choose. **A leg list containing both is legal; a
   *total* over both is not** — that constraint lives in Task 4.5 and is asserted there.
4. **Assignment is read from `CampaignRow.assigned`, not recomputed.** `classify_outcome` takes an
   `assigned` flag as a caller decision because it needs position knowledge. The campaign already
   holds it, set by `mark_campaign_assigned`. Do not import the detector from
   `src/claude/eval/assignment.py`: that would put `src/reporting/` in violation of Task 4.1's
   fence test, and the campaign is the more durable source anyway.
5. **`roc_pct` is credit over collateral**, where collateral is `strike × contracts × 100` for a
   cash-secured put and `strike × contracts × 100` for a covered call's assigned-away obligation.
   Where collateral cannot be determined, `roc_pct` is `None`, not `0.0`.
6. **`annualized_pct` is `None` when `days_held` is zero**, never a division that produces
   infinity or a fabricated number from a same-day open and close.
7. **`build_legs` always leaves `unrealized_pnl` as `None`.** It takes no snapshot and has no mark
   to work from. Task 4.4 fills that field from the snapshot it is given, and only for open legs.
   A closed leg's `unrealized_pnl` stays `None` forever — it has a result, not a mark.

Required behaviours, each with a test:
- A single sold-and-expired leg produces one row with the right credit, outcome and `net_pnl`.
- **An open leg has `net_pnl: None`.** Its own test.
- A bought-back leg has `net_pnl` equal to credit minus debit minus commissions.
- A leg with a null commission has `commissions_complete: False`.
- A leg whose `CandidateRow` was pruned still appears, with nulls where the detail is unknown.
- An assigned leg reads `assigned` from the campaign, proven by flipping the campaign flag and
  seeing the outcome change.
- `roc_pct` is `None` when collateral cannot be determined.
- `annualized_pct` is `None` for a same-day open and close.
- `include_paper=False` excludes paper fills; `include_live=False` excludes live ones.
- `symbol="NVDA"` filters; `since` filters on the opening fill date.
- A candidate with no fills produces no leg.

- [ ] **Step 1: Write the failing test**

```python
"""Every number here is one an operator will act on. None of them may be invented."""

from __future__ import annotations

import pytest


def test_an_open_leg_has_no_realized_pnl(db, seed_leg) -> None:
    """The single most valuable assertion in P4. An open leg has a mark, not a result."""
    seed_leg(candidate_id="c1", sold=(1, 1.50), expiry_in_days=30)
    leg = build_legs(db)[0]
    assert leg.net_pnl is None
    assert leg.outcome.value == "still_open"


def test_a_bought_back_leg_nets_credit_minus_debit_minus_commissions(db, seed_leg) -> None:
    seed_leg(candidate_id="c1", sold=(2, 1.50, 1.30), bought=(2, 0.40, 1.30),
             expiry_in_days=30)
    leg = build_legs(db)[0]
    assert leg.credit == 300.0
    assert leg.debit == 80.0
    assert leg.commissions == pytest.approx(2.60)
    assert leg.net_pnl == pytest.approx(300.0 - 80.0 - 2.60)


def test_a_leg_whose_candidate_was_pruned_still_appears(db, seed_leg) -> None:
    """Fills survive pruning. A total that silently loses a row is the worse failure."""
    seed_leg(candidate_id="c1", sold=(1, 1.50), expiry_in_days=-1, prune_candidate=True)
    legs = build_legs(db)
    assert len(legs) == 1
    assert legs[0].candidate_id == "c1"


def test_assignment_is_read_from_the_campaign_not_recomputed(db, seed_leg, set_campaign) -> None:
    seed_leg(candidate_id="c1", sold=(1, 1.50), expiry_in_days=-1, campaign_id="camp1")
    assert build_legs(db)[0].outcome.value == "expired_worthless"

    set_campaign("camp1", assigned=True)
    assert build_legs(db)[0].outcome.value == "assigned"


def test_roc_is_none_when_collateral_is_unknown(db, seed_leg) -> None:
    seed_leg(candidate_id="c1", sold=(1, 1.50), expiry_in_days=-1, strike=None)
    assert build_legs(db)[0].roc_pct is None


def test_annualized_is_none_for_a_same_day_leg(db, seed_leg) -> None:
    seed_leg(candidate_id="c1", sold=(1, 1.50), bought=(1, 0.20), days_held=0)
    assert build_legs(db)[0].annualized_pct is None


def test_paper_and_live_can_be_filtered_apart(db, seed_leg) -> None:
    seed_leg(candidate_id="paper", sold=(1, 1.0), is_live=False)
    seed_leg(candidate_id="live", sold=(1, 1.0), is_live=True)
    assert {leg.candidate_id for leg in build_legs(db, include_live=False)} == {"paper"}
    assert {leg.candidate_id for leg in build_legs(db, include_paper=False)} == {"live"}


def test_a_candidate_with_no_fills_is_not_a_leg(db, seed_candidate_only) -> None:
    seed_candidate_only("c1")
    assert build_legs(db) == []
```

Put `seed_leg`, `set_campaign` and `seed_candidate_only` in `tests/conftest.py` beside the
fixtures M2 Task 2.1 added. Task 4.4 and Task 4.7 both need them.

- [ ] **Step 2: Confirm failure. Step 3: Implement. Step 4: Run the gate. Step 5: Commit.**

---

## Task 4.4 — `build_campaigns` `[SONNET]`

**Requires a judgment call about degradation: what a campaign total says when there is no mark.**

**Files:** Modify `src/reporting/pnl.py`. Test `tests/test_build_campaigns.py`.

**Interfaces:**

```python
def build_campaigns(
    session: Session,
    legs: list[PnlLeg],
    *,
    snapshot: PortfolioSnapshot | None = None,
) -> list[CampaignPnl]:
    """Group legs into campaign threads and attach the stock leg.

    `snapshot` supplies the marks for open legs and open stock. When it is None, every
    unrealised field is None — never zero, and never a stale mark from somewhere else.
    """
```

Consumes: `PnlLeg` (4.2), `build_legs` (4.3), `CampaignRow` and
`src/storage/campaigns.py::load_campaigns`, `PortfolioSnapshot` (M1 Task 1.1).

**Design points that are not negotiable:**

1. **The stock leg is read, never recomputed.** `campaigns.realized_stock_pnl` and
   `campaigns.adjusted_cost_basis` already exist and are maintained on assignment. P4 reads them.
2. **`snapshot=None` means every unrealised field is `None`.** Not zero. A campaign whose
   unrealised is unknown must not present a `total_net` that silently means "realised only" —
   `total_net` in that case is the realised total and the response says `option_unrealized: None`
   so the caller can see what is missing.
3. **A leg with no campaign is not dropped.** Legs whose `campaign_id` is `None` are grouped into a
   synthetic per-symbol thread with `campaign_id` set to a stable derived value and
   `status: "closed"` if every leg is closed. Dropping them would make the ledger's totals
   disagree with the leg list above it.
4. **Marks come from the same snapshot the portfolio page renders.** Do not fetch a second one and
   do not fall back to a different capture — the two surfaces must agree by construction.

Required behaviours, each with a test:
- A three-leg campaign groups all three, in leg order.
- `option_realized` sums only closed legs.
- **With `snapshot=None`, `option_unrealized` and `stock_unrealized` are `None`**, and `total_net`
  equals the realised total. Its own test.
- With a snapshot, an open leg's mark contributes to `option_unrealized`.
- An assigned campaign reports `stock_realized` and `adjusted_cost_basis` exactly as stored.
- A leg with `campaign_id: None` appears in a synthetic thread, and the sum of every thread's legs
  equals the input leg count.
- An open campaign with no closed legs reports `option_realized: 0.0` — a real zero, because zero
  legs have closed and that is a measured fact, unlike an unknown.
- **With a snapshot, an open leg's `unrealized_pnl` is populated and a closed leg's stays `None`.**
  Its own test: a closed leg has a result, not a mark, and a mark on it would be meaningless.

- [ ] **Step 1: Write the failing test**

```python
def test_no_snapshot_means_unrealised_is_unknown_not_zero(db, seed_leg) -> None:
    """A total that quietly means 'realised only' is how a P&L page misleads."""
    seed_leg(candidate_id="c1", sold=(1, 1.50), expiry_in_days=30, campaign_id="camp1")
    campaign = build_campaigns(db, build_legs(db), snapshot=None)[0]
    assert campaign.option_unrealized is None
    assert campaign.stock_unrealized is None
    assert campaign.total_net == campaign.option_realized


def test_every_leg_lands_in_exactly_one_thread(db, seed_leg) -> None:
    seed_leg(candidate_id="c1", campaign_id="camp1", sold=(1, 1.0))
    seed_leg(candidate_id="c2", campaign_id=None, sold=(1, 1.0))
    legs = build_legs(db)
    campaigns = build_campaigns(db, legs, snapshot=None)
    assert sum(len(c.legs) for c in campaigns) == len(legs)


def test_an_open_campaign_reports_a_real_zero_realised(db, seed_leg) -> None:
    """Zero closed legs is a measurement. It is not the same as unknown."""
    seed_leg(candidate_id="c1", sold=(1, 1.50), expiry_in_days=30, campaign_id="camp1")
    assert build_campaigns(db, build_legs(db), snapshot=None)[0].option_realized == 0.0
```

- [ ] **Step 2: Confirm failure. Step 3: Implement. Step 4: Gate. Step 5: Commit.**

---

## Task 4.5 — `build_summary` `[GLM]`

**Files:** Modify `src/reporting/pnl.py`. Test `tests/test_build_summary.py`.

**Interfaces:**

```python
def build_summary(
    legs: list[PnlLeg],
    campaigns: list[CampaignPnl],
) -> PnlSummary:
    """Aggregate. Pure — no session, no database, no config.

    Raises ValueError when `legs` mixes paper and live. A total across both is not a
    number that means anything, and returning one silently is the failure this guards.
    """
```

**Design points:**

1. **Mixing paper and live raises.** The caller filters; the aggregator refuses. This is the one
   place in `src/reporting/` that raises, and it raises rather than returning a misleading total.
2. `win_rate` is `None` when no legs have closed, not `0.0`.
3. `commissions_complete` on the summary is the **AND** of every leg's flag — one incomplete leg
   makes the whole total gross.
4. `best` and `worst` are chosen among closed legs only. An open leg has no result to compare.
5. `by_strategy` and `by_symbol` are ordered by realised descending, ties broken by label.

Required behaviours, each with a test:
- Realised total sums closed legs only.
- **Mixing `is_live=True` and `is_live=False` raises `ValueError`.** Its own test.
- `win_rate` is `None` with zero closed legs.
- One leg with `commissions_complete: False` makes the summary's flag `False`.
- `best` and `worst` are closed legs, never open ones.
- An empty leg list returns a valid summary with `realized_total: 0.0`, `n_open: 0`, `n_closed: 0`,
  `win_rate: None`.

- [ ] **Step 1: Write the failing test**

```python
def test_mixing_paper_and_live_raises_rather_than_totalling(paper_leg, live_leg) -> None:
    """A total across both is not a number. Refuse rather than return one."""
    with pytest.raises(ValueError):
        build_summary([paper_leg, live_leg], [])


def test_win_rate_is_unknown_not_zero_with_nothing_closed(open_leg) -> None:
    assert build_summary([open_leg], []).win_rate is None
```

- [ ] **Step 2: Confirm failure. Step 3: Implement. Step 4: Gate. Step 5: Commit.**

---

## Task 4.6 — `equity_curve` `[SONNET]`

**The honesty constraint lives here.**

**Files:** Modify `src/reporting/pnl.py`. Test `tests/test_equity_curve.py`.

**Interfaces:**

```python
def equity_curve(
    session: Session,
    legs: list[PnlLeg],
    *,
    since: date | None = None,
) -> EquityCurve:
    """One point per JournalRow, plus the trading days between them that have none.

    Reads net_liquidation from journal.payload["eod_summary"]["account"], validated
    through AccountSnapshot rather than indexed field by field, so a schema drift
    surfaces as a missing value rather than a KeyError at render time.
    """
```

**Design points that are not negotiable:**

1. **`gaps` lists the trading days with no journal row**, between the first and last point. Use
   `src.common.market_hours.is_trading_day` — a weekend is not a gap, a missed Tuesday is.
2. **No interpolation.** The function returns points and gaps; it never synthesises a value for a
   day it has no row for.
3. **`starts_at` is the first journal date**, and it is not zero-anchored. The curve is the
   system's history, not the account's, and the chart says so.
4. **`premium_cashflow` carries `journal.realized_pnl` under its true name.** The column is named
   `realized_pnl` for back-compat and its own comment says it is premium cashflow, not paired
   realised P&L. **The schema field is `premium_cashflow` and nothing downstream may label it
   "realised".**
5. **`cumulative_realized` sums `PnlLeg.net_pnl` for legs closed on or before each point's date.**
   It is P4's own figure, and it will visibly differ from `premium_cashflow`. That is correct.
6. A `journal` row whose payload has no readable account yields `net_liquidation: None` for that
   point, and the point still exists — the day was measured even if one field is unreadable.

Required behaviours, each with a test:
- One point per journal row, ordered by date ascending.
- A missing trading day between two rows appears in `gaps`; a weekend does not.
- `starts_at` is the first journal date.
- `cumulative_realized` is monotonic in the sense that each point includes every leg closed on or
  before it, proven with two legs closing on different dates.
- `premium_cashflow` carries the journal's `realized_pnl` value.
- An unreadable account payload yields `net_liquidation: None` and the point still appears.
- No journal rows returns an empty curve with `starts_at: None`, not an exception.
- `since` trims the leading points and recomputes `starts_at`.

- [ ] **Step 1: Write the failing test**

```python
def test_a_missed_trading_day_is_a_gap_and_a_weekend_is_not(db, seed_journal_day) -> None:
    """A straight line across a week nobody measured is a fabricated claim."""
    seed_journal_day(date(2026, 9, 1))    # Tuesday
    seed_journal_day(date(2026, 9, 4))    # Friday — Wed and Thu missing
    seed_journal_day(date(2026, 9, 7))    # Monday — the weekend between is not a gap

    curve = equity_curve(db, [])
    assert date(2026, 9, 2) in curve.gaps
    assert date(2026, 9, 3) in curve.gaps
    assert date(2026, 9, 5) not in curve.gaps   # Saturday
    assert date(2026, 9, 6) not in curve.gaps   # Sunday


def test_premium_cashflow_is_never_called_realised(db, seed_journal_day) -> None:
    """journal.realized_pnl is premium cashflow. The schema field name says so."""
    seed_journal_day(date(2026, 9, 1), realized_pnl=412.0)
    point = equity_curve(db, []).points[0]
    assert point.premium_cashflow == 412.0
    assert not hasattr(point, "realized_pnl")


def test_an_unreadable_account_payload_still_produces_a_point(db, seed_journal_day) -> None:
    seed_journal_day(date(2026, 9, 1), payload={"eod_summary": {"account": "corrupt"}})
    curve = equity_curve(db, [])
    assert len(curve.points) == 1
    assert curve.points[0].net_liquidation is None
```

- [ ] **Step 2: Confirm failure. Step 3: Implement. Step 4: Gate. Step 5: Commit.**

---

## Task 4.7 — The wheel-scenario suite `[SONNET]`

**The highest-value tests in P4.** Every test in this file writes its expected numbers out by hand.
**A test that computes its expectation the same way the code does proves nothing.**

**Files:** Test `tests/test_wheel_scenarios.py`. No production code.

Build five scenarios end to end, each seeding fills and campaigns and asserting on `build_legs`,
`build_campaigns` and `build_summary` output:

**Scenario 1 — a CSP that expires worthless.** Sell one NVDA 170 put for 2.40, commission 1.30,
30 DTE, expires. Expected: one leg, `credit == 240.00`, `debit == 0.0`,
`net_pnl == 238.70`, `outcome == expired_worthless`, `roc_pct == 240.0 / 17000.0 * 100`.

**Scenario 2 — the full wheel.** Sell a CSP, get assigned, write two covered calls, the second
gets called away. Expected: three option legs plus a stock leg; the campaign's `option_realized`
is the sum of the three legs written out by hand; `stock_realized` comes from the campaign row;
`total_net` is their sum; `assigned` is true and `adjusted_cost_basis` is the stored value.

**Scenario 3 — a roll chain.** One leg opened, bought back at a debit, a new leg opened the same
day at a credit, held to expiry. Expected: **two legs, not one**; the first's `net_pnl` is
negative; the second's is positive; the campaign's `option_realized` is their sum; the leg count
on the campaign is 2.

**Scenario 4 — a leg with no commission data.** Expected: `commissions == 0.0`,
`commissions_complete == False`, and the summary's `commissions_complete == False`.

**Scenario 5 — paper and live side by side.** Expected: `build_legs` returns both;
`build_summary` over both **raises**; filtered to each, the two summaries have different totals and
neither equals their sum.

Plus two cross-checks against existing machinery:

```python
def test_the_ledger_and_the_reporting_layer_agree_on_every_closed_trade(db, seed_wheel) -> None:
    """Task 4.1's whole point: one accounting rule, so these cannot disagree."""
    seed_wheel()
    run_the_reconciler()

    for leg in build_legs(db):
        if leg.net_pnl is None:
            continue
        ledger_row = verdict_ledger_row_for(db, leg.candidate_id)
        if ledger_row is None or ledger_row.realized_pnl is None:
            continue
        assert leg.net_pnl == pytest.approx(ledger_row.realized_pnl)
        assert leg.outcome.value == ledger_row.outcome


def test_the_campaign_rollup_and_the_leg_sum_agree(db, seed_wheel) -> None:
    """Both are rolled up from FillRow, so they must reconcile — but not naively.

    campaigns.net_premium is GROSS of commissions (pinned by M0 Task 0.4); PnlLeg.net_pnl is
    NET of them. Compare like with like: sum the legs' credit - debit, before commissions.
    A test that compared net_pnl to net_premium would fail by exactly the commission total
    and tell you nothing about whether the two rollups agree.
    """
    seed_wheel()
    legs = build_legs(db)
    gross = sum(leg.credit - leg.debit for leg in legs)
    stored = load_campaigns(symbol="NVDA")[0]
    assert gross == pytest.approx(stored["net_premium"])


def test_the_gross_and_net_views_differ_by_exactly_the_commissions(db, seed_wheel) -> None:
    """Makes the relationship explicit rather than leaving it as a known discrepancy."""
    seed_wheel()
    legs = [leg for leg in build_legs(db) if leg.net_pnl is not None]
    gross = sum(leg.credit - leg.debit for leg in legs)
    net = sum(leg.net_pnl for leg in legs)
    assert gross - net == pytest.approx(sum(leg.commissions for leg in legs))
```

The first cross-check is the strongest evidence in the milestone that Task 4.1 achieved what it
set out to. If it fails, there are two accounting rules again.

The second exists because the campaign rollup and the leg ledger will visibly disagree on any
symbol with commissions, and an operator comparing `/portfolio/campaigns` against `/pnl/ledger`
will notice. Asserting the exact relationship turns "these two numbers differ" from a mystery into
a documented, tested fact — and gives whoever later decides to net commissions into `_rollup` a
test that tells them what they changed.

- [ ] **Step 1:** Write all five scenarios and both cross-checks with expected values computed by
  hand and written as literals in the test.

- [ ] **Step 2:** Run them. Fix `src/reporting/pnl.py` where they fail — **not the test's
  expectations**, unless you can show by hand that the literal was arithmetically wrong.

- [ ] **Step 3:** Run the FULL suite, `ruff check .`, `mypy src`.

- [ ] **Step 4:** `STATUS.md` records the P&L engine as built and states plainly that its numbers
  have not yet been reconciled against a broker statement.

- [ ] **Step 5: Commit.**

---

## Milestone 4 acceptance

- [ ] There is exactly **one** implementation of `fill_economics` and `classify_outcome` in the
  repository. Verified by grepping for the arithmetic, not just by reading the diff.
- [ ] `src/claude/eval/reconcile.py` imports from `src/reporting/legs.py`, and its four existing
  test files pass **unchanged** at the same count recorded in Task 4.1 Step 1.
- [ ] `src/reporting/` imports nothing from `src.claude`; `src/engine/`, `src/execution/` and
  `src/strategies/` import nothing from `src.reporting`. Both asserted in
  `tests/test_web_fence.py`.
- [ ] `PnlLeg.net_pnl` is `None` for every open leg, with its own test.
- [ ] A null commission produces `commissions_complete: False` and propagates to the summary.
- [ ] `build_summary` **raises** on a mixed paper and live leg list.
- [ ] The equity curve reports gaps for missed trading days and never interpolates, and its
  journal-derived field is named `premium_cashflow`.
- [ ] The five wheel scenarios pass with hand-written expected values.
- [ ] The reporting layer and `verdict_ledger` agree on realised P&L and outcome for every closed
  trade the reconciler has labelled.
- [ ] Root `CLAUDE.md`'s analytics-tier section names `src/reporting/` as the third, read-only
  tier.
- [ ] Full gate green, with the full Python suite run because Task 4.1 modifies the reconciler.
