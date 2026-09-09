# Milestone 2 — Portfolio read API

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or
> superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Four owner-only read routes that answer "what do I hold, what is it worth, what is at
risk, and what happens next" from the snapshot spine M1 built.

**Spec:** `Web plan/P3-P4-design.md` §5. **Index:** `Web plan/P3-P4-IMPLEMENTATION-PLAN.md`.
**Depends on:** Milestone 1, and on **M0 Task 0.3**, which built the single assignment-risk
predicate three of these routes consume. If `src/common/assignment_risk.py` does not exist, M0 was
not run and this milestone cannot start.

**Still no UI.** Every route here is consumed by Milestone 3.

**The shape of this milestone in one sentence:** these routes render the reading `read_portfolio`
returns and add nothing to it — if a route reaches past `PortfolioReading` to a table of its own,
the freshness contract M1 built is already broken.

---

## Task 2.1 — `GET /portfolio/summary` `[SONNET]`

**The first portfolio route. Every convention M2 and M3 follow is set here.**

**Files:** Create `src/api/routers/portfolio.py`, `src/api/models/portfolio.py`. Modify
`src/api/main.py`, `docs/web/api.md`. Test `tests/test_api_portfolio_summary.py`.

**Interfaces:**

```python
# src/api/models/portfolio.py
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
    buying_power_utilisation_pct: float | None   # None when buying power is unknown
    shorts_at_assignment_risk: int


class PortfolioSummaryResponse(Envelope):
    source: Literal["monitor", "refresh", "eod", "none"]
    degraded: bool
    account: AccountBlock | None      # None on the "none" rung
    exposure: ExposureBlock | None    # None on the "none" rung
    note: str | None                  # populated on every degraded rung, in plain words
```

Consumes: `read_portfolio` and `PortfolioReading` (Task 1.5), `is_assignment_risk` and
`assignment_risk_thresholds` (**M0 Task 0.3**), `Sourced.of` and `Envelope`
(`src/api/models/common.py`), `OwnerUser` and `TradingDb` (`src/api/deps.py`),
`src/storage/campaigns.py::load_campaigns`.

Produces, for Tasks 2.2-2.4 and Milestone 3: the router module, the `source`/`degraded`/`note`
triple that every portfolio response carries, and the convention that `as_of` is the reading's
capture time.

**Design points that are not negotiable:**

1. **`OwnerUser`, not `CurrentUser`.** `src/api/deps.py::require_owner` carries the docstring
   "Gate for anything exposing the book. Applied to P3/P4 routes when they land." These are those
   routes. Every route in M2, M5 and M6 uses it.
2. **`as_of` is `reading.as_of`**, not `datetime.now(UTC)`. Where the reading has no `as_of` (the
   empty rung), use request time and set `degraded=True` — the response still needs a valid
   envelope, but nothing in it claims to be a measurement. Any timestamp this router reads straight
   from SQLite goes through `as_utc_opt` (M0 Task 0.9); **this router defines no `_as_utc` of its
   own.**
3. **`Sourced` values use `Source.IBKR`**, because that is where the numbers came from, even
   though a database served them. The `as_of` and `stale` fields carry the age. `fresh_for` is
   twice the configured snapshot interval, so a portfolio that has missed one capture reads stale.
4. **The `none` rung returns `200`, not `404`.** There is no error; there is simply nothing
   captured yet, and the client needs a well-formed response saying so. `note` says it in words:
   "No portfolio snapshot has been captured yet."
5. **`buying_power_utilisation_pct` is `None` when buying power is zero or unknown**, never a
   division-by-zero guard that returns `0.0`. A zero would read as "nothing committed".
6. **`cash_secured_against_puts` counts only short puts**, at `strike × contracts × 100`. Long
   options and stock are not cash-secured obligations.

Required behaviours, each with a test:
- A fresh snapshot yields `source="monitor"`, `degraded=False`, and account values matching it.
- The `eod` rung yields `degraded=True` and a `note`.
- **The empty rung yields `200`, `source="none"`, `account=None`, and a `note` — never zeros.**
- `as_of` equals the snapshot's `captured_at`.
- A snapshot older than twice the interval marks every `Sourced` value `stale=True`.
- `cash_secured_against_puts` counts short puts only, proven with a mixed portfolio containing a
  short put, a short call, a long put and stock.
- `buying_power_utilisation_pct` is `None` when buying power is `0.0`.
- `shorts_at_assignment_risk` uses `is_assignment_risk`, proven by a position at 10 DTE and delta
  0.75 counting as one.
- **A non-owner role gets `403`.** Its own test.

- [ ] **Step 1: Write the failing test**

```python
"""The first portfolio route. Empty is reported as empty, never as zero."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


def test_a_fresh_snapshot_is_reported_fresh(client, seed_portfolio_snapshot) -> None:
    when = datetime.now(UTC) - timedelta(minutes=3)
    seed_portfolio_snapshot(captured_at=when, source="monitor", net_liq=250_000.0)

    body = client.get("/portfolio/summary", headers=OWNER).json()
    assert body["source"] == "monitor"
    assert body["degraded"] is False
    assert body["account"]["net_liquidation"]["value"] == 250_000.0
    assert body["account"]["net_liquidation"]["stale"] is False
    assert body["as_of"].startswith(when.isoformat()[:16])


def test_nothing_captured_yet_is_200_and_says_so(client) -> None:
    """Zeros here would be a claim about the account."""
    r = client.get("/portfolio/summary", headers=OWNER)
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "none"
    assert body["account"] is None
    assert body["exposure"] is None
    assert body["note"]


def test_the_eod_rung_is_flagged_degraded(client, seed_position_snapshot, seed_journal) -> None:
    seed_position_snapshot(symbols=["NVDA"])
    seed_journal(net_liq=100_000.0)

    body = client.get("/portfolio/summary", headers=OWNER).json()
    assert body["source"] == "eod"
    assert body["degraded"] is True
    assert body["note"]


def test_an_old_snapshot_marks_every_value_stale(client, seed_portfolio_snapshot) -> None:
    seed_portfolio_snapshot(captured_at=datetime.now(UTC) - timedelta(hours=4))
    account = client.get("/portfolio/summary", headers=OWNER).json()["account"]
    assert all(account[k]["stale"] is True for k in
               ("net_liquidation", "total_cash", "buying_power",
                "maintenance_margin", "excess_liquidity"))


def test_cash_secured_counts_short_puts_only(client, seed_portfolio_snapshot) -> None:
    seed_portfolio_snapshot(positions=[
        short_put(strike=100.0, contracts=2),    # 100 * 2 * 100 = 20_000
        short_call(strike=200.0, contracts=1),   # not cash-secured
        long_put(strike=90.0, contracts=1),      # not an obligation
        stock(symbol="NVDA", shares=100),        # not an option
    ])
    exposure = client.get("/portfolio/summary", headers=OWNER).json()["exposure"]
    assert exposure["cash_secured_against_puts"] == 20_000.0


def test_utilisation_is_none_not_zero_when_buying_power_is_zero(client,
                                                                seed_portfolio_snapshot) -> None:
    seed_portfolio_snapshot(buying_power=0.0)
    exposure = client.get("/portfolio/summary", headers=OWNER).json()["exposure"]
    assert exposure["buying_power_utilisation_pct"] is None


def test_assignment_risk_count_uses_the_shared_predicate(client, seed_portfolio_snapshot) -> None:
    seed_portfolio_snapshot(positions=[short_call(delta=-0.75, dte=10)])
    exposure = client.get("/portfolio/summary", headers=OWNER).json()["exposure"]
    assert exposure["shorts_at_assignment_risk"] == 1


def test_a_non_owner_is_refused(client) -> None:
    assert client.get("/portfolio/summary", headers=VIEWER).status_code == 403
```

Build `seed_portfolio_snapshot` and the `short_put`/`short_call`/`long_put`/`stock` position
builders as fixtures in `tests/conftest.py` — Tasks 2.3, 2.5, 4.3 and 4.4 all need them, and a
second copy in each test file is how the wheel-scenario suite in Task 4.7 ends up disagreeing with
this one.

- [ ] **Step 2: Run the tests and confirm they fail.**

- [ ] **Step 3: Implement** the models, the router, and its registration in `src/api/main.py`.

- [ ] **Step 4: Run the gate.** `python -m pytest -q` · `ruff check .` · `mypy src`

- [ ] **Step 5:** `docs/web/api.md` gains the route with its response shape and its degradation
  behaviour spelled out. Commit.

---

## Task 2.2 — `GET /portfolio/positions` `[SONNET]`

**Adjusted-basis semantics. Getting this wrong makes a profitable assigned position look like a
loss.**

**Files:** Modify `src/api/routers/portfolio.py`, `src/api/models/portfolio.py`,
`docs/web/api.md`. Test `tests/test_api_portfolio_positions.py`.

**Interfaces:**

```python
class OptionLeg(Envelope):
    symbol: str                       # the OCC option symbol
    right: Literal["C", "P"]
    strike: float
    expiry: date
    dte: int | None
    contracts: int                    # absolute; `short` carries the direction
    short: bool
    delta: float | None
    delta_source: Source | None
    market_price: float | None
    market_value: float | None
    unrealized_pnl: float | None
    moneyness: Literal["itm", "atm", "otm"] | None
    assignment_risk: bool


class StockLeg(Envelope):
    shares: float
    avg_cost: float
    adjusted_cost_basis: float | None   # from campaigns, when the shares came from assignment
    market_price: float | None
    market_value: float | None
    unrealized_pnl: float | None
    unrealized_pnl_adjusted: float | None   # against adjusted basis; None when no adjusted basis


class PositionGroup(Envelope):
    underlying: str
    stock: StockLeg | None
    options: list[OptionLeg]


class PositionsResponse(Envelope):
    source: Literal["monitor", "refresh", "eod", "none"]
    degraded: bool
    groups: list[PositionGroup]
```

Consumes: everything Task 2.1 produced, plus
`src/storage/campaigns.py::adjusted_cost_basis_for(symbol) -> float | None`.

**Design points that are not negotiable:**

1. **Grouped by underlying.** `PositionSnapshot.underlying` for options, `symbol` for stock. An
   option whose `underlying` is `None` groups under its own symbol rather than being dropped.
2. **Both cost bases are reported, never one substituted for the other.** `avg_cost` is what IBKR
   says. `adjusted_cost_basis` is what the collected premium makes it. `unrealized_pnl` is against
   the former and `unrealized_pnl_adjusted` against the latter. **Do not overwrite `avg_cost` with
   the adjusted figure** — the operator needs to see both, and a single "cost" field that silently
   means different things per row is exactly the kind of number this design exists to prevent.
3. **`adjusted_cost_basis` is `None` for shares that did not come from an assignment**, and
   `unrealized_pnl_adjusted` is `None` with it. Not equal to `unrealized_pnl`, and not zero.
4. **`moneyness` is `None` when the underlying price is unknown.** No guessing from the strike
   alone.
5. **`dte` is `None` when expiry is unknown, never `0`** — `0` reads as "expires today". This rule
   already exists at `src/api/routers/options.py:832` with a comment saying so; follow it.
6. **The empty rung returns `groups: []` with `source="none"`.** An empty list plus `source="none"`
   is honest; an empty list plus `source="monitor"` would be a claim that the account holds
   nothing.

Required behaviours, each with a test:
- A stock position and two option legs on the same underlying come back as one group.
- An option with a `None` underlying still appears, grouped under its own symbol.
- Assigned shares report both `avg_cost` and `adjusted_cost_basis`, and two distinct unrealised
  figures.
- **Non-assigned shares report `adjusted_cost_basis: None` and `unrealized_pnl_adjusted: None`.**
- `moneyness` is `None` when `market_price` is absent.
- `dte` is `None`, never `0`, for an unknown expiry.
- `assignment_risk` matches M0 Task 0.3's predicate, and the router hardcodes no threshold.
- The empty rung returns `groups: []` and `source="none"`.
- A non-owner gets `403`.

- [ ] **Step 1: Write the failing test.** Cover each bullet above with its own named test. The
  adjusted-basis pair needs two: one proving both figures are present and different for assigned
  shares, one proving both adjusted fields are `None` for ordinary shares.

```python
def test_assigned_shares_report_both_cost_bases(client, seed_portfolio_snapshot,
                                                seed_assigned_campaign) -> None:
    """Premium collected is what makes an assigned position profitable. Show both numbers."""
    seed_assigned_campaign(symbol="NVDA", assignment_price=180.0, adjusted_basis=173.50)
    seed_portfolio_snapshot(positions=[stock(symbol="NVDA", shares=100, avg_cost=180.0,
                                             market_price=176.0)])

    group = client.get("/portfolio/positions", headers=OWNER).json()["groups"][0]
    assert group["stock"]["avg_cost"] == 180.0
    assert group["stock"]["adjusted_cost_basis"] == 173.50
    assert group["stock"]["unrealized_pnl"] < 0            # against the raw fill price
    assert group["stock"]["unrealized_pnl_adjusted"] > 0   # against the premium-adjusted basis


def test_ordinary_shares_report_no_adjusted_basis(client, seed_portfolio_snapshot) -> None:
    """None, not a copy of the raw figure, and not zero."""
    seed_portfolio_snapshot(positions=[stock(symbol="AAPL", shares=100, avg_cost=200.0)])
    stock_leg = client.get("/portfolio/positions", headers=OWNER).json()["groups"][0]["stock"]
    assert stock_leg["adjusted_cost_basis"] is None
    assert stock_leg["unrealized_pnl_adjusted"] is None
```

- [ ] **Step 2: Run the tests and confirm they fail.**

- [ ] **Step 3: Implement.**

- [ ] **Step 4: Run the gate.**

- [ ] **Step 5:** `docs/web/api.md`. Commit.

---

## Task 2.3 — `GET /portfolio/campaigns` `[GLM]`

**Files:** Modify `src/api/routers/portfolio.py`, `src/api/models/portfolio.py`,
`docs/web/api.md`. Test `tests/test_api_portfolio_campaigns.py`.

**Interfaces:**

```python
class CampaignLeg(Envelope):
    candidate_id: str
    strategy: str
    right: Literal["C", "P"] | None
    strike: float | None
    expiry: date | None
    known: bool          # False when the CandidateRow was pruned; the leg still renders


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
```

Consumes: `src/storage/campaigns.py::load_campaigns(...)`, whose return shape you must read before
writing the mapping — it returns dicts, not ORM rows. `CandidateRow` for leg detail, joined on
`leg_candidate_ids`.

**Design points:**

1. **A leg whose `CandidateRow` no longer exists still renders**, with `known: false` and null
   contract fields. `risk_verdicts` and candidates are pruned; a campaign is not. Dropping the leg
   would make the leg count disagree with the financials, which are rolled up from `FillRow` and
   survive.
2. `as_of` is request time here, not a snapshot time — campaigns are written on fill, not captured.
   Say so in the docstring so a later reader does not "fix" it to match the other routes.
3. Ordered by `opened_date` descending, open campaigns before closed ones at the same date.
4. Query parameters: `status` (`open` | `closed` | omitted for both) and `symbol`.
5. **`docs/web/api.md`'s write-up must document `total_premium_collected`/`total_debit_paid`/
   `net_premium` as gross of commissions** — pinned by M0 Task 0.4. `src/storage/campaigns.py::_rollup`'s
   docstring and `CampaignRow`'s docstring are the source of truth for the exact semantics; carry
   that language into this route's doc section rather than re-deriving it.

Required behaviours, each with a test:
- An open campaign with three legs returns all three, in leg order.
- A pruned candidate renders as a leg with `known: false` and null strike/expiry, and the leg count
  still matches `leg_candidate_ids`.
- `status=open` excludes closed campaigns; `status=closed` excludes open ones; omitting it returns
  both.
- `symbol=NVDA` filters.
- An assigned campaign reports `adjusted_cost_basis` and `realized_stock_pnl` as stored, without
  recomputation.
- Empty database returns `campaigns: []` and a valid `as_of`.
- A non-owner gets `403`.

- [ ] **Step 1: Write the failing test**

```python
def test_a_pruned_candidate_still_renders_as_a_leg(client, seed_campaign) -> None:
    """Financials survive pruning; the leg list must not silently shrink beneath them."""
    seed_campaign(symbol="NVDA", leg_candidate_ids=["c1", "c2"], seed_candidates=["c1"])

    campaign = client.get("/portfolio/campaigns", headers=OWNER).json()["campaigns"][0]
    assert len(campaign["legs"]) == 2
    assert campaign["legs"][0]["known"] is True
    assert campaign["legs"][1]["known"] is False
    assert campaign["legs"][1]["strike"] is None
```

Write the remaining six as their own named tests following this shape.

- [ ] **Step 2: Run, confirm failure. Step 3: Implement. Step 4: Gate. Step 5: `docs/web/api.md`,
  commit.**

---

## Task 2.4 — `GET /portfolio/calendar` `[GLM]`

**Files:** Modify `src/api/routers/portfolio.py`, `src/api/models/portfolio.py`,
`docs/web/api.md`. Test `tests/test_api_portfolio_calendar.py`.

**Interfaces:**

```python
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
```

Query parameter `horizon_days`, default 45, maximum 365.

**The `consequence` mapping — implement exactly this table:**

| Position | Moneyness | `consequence` |
|---|---|---|
| Short put | `itm` | `assigned` |
| Short call, stock held | `itm` | `called_away` |
| Short call, no stock held | `itm` | `assigned` (a naked short call assignment is a short stock position, not a call-away) |
| Any short | `otm` or `atm` | `expires_worthless` |
| Any | moneyness unknown | `unknown` |
| Long option | any | `expires_worthless` when `otm`, else `unknown` |

**`unknown` is a real value and must render.** Do not default it to `expires_worthless`; "we do not
know what happens on Friday" is materially different from "nothing happens on Friday".

Required behaviours, each with a test:
- An ITM short put maps to `assigned`.
- An ITM short call **with** the stock held maps to `called_away`.
- An ITM short call **without** the stock held maps to `assigned`. Its own test.
- An OTM short maps to `expires_worthless`.
- Unknown moneyness maps to `unknown`, not to `expires_worthless`.
- Entries are grouped by expiry and days are ordered nearest first.
- `horizon_days=7` excludes an expiry 30 days out.
- `horizon_days=9999` is rejected with `422`.
- The empty rung returns `days: []` with `source="none"`.
- A non-owner gets `403`.

- [ ] **Step 1: Write the failing tests, one per bullet. Step 2: Confirm they fail. Step 3:
  Implement. Step 4: Gate. Step 5: `docs/web/api.md`, commit.**

---

## Task 2.5 — API documentation and schema regeneration `[GLM]`

**Files:** Modify `docs/web/api.md`, `docs/web/openapi.json`, `web/lib/api-types.ts`,
`ARCHITECTURE.md`, `README.md`.

- [ ] **Step 1:** Confirm all four routes are documented in `docs/web/api.md` with request
  parameters, response shapes, and degradation behaviour. Tasks 2.2-2.5 each own their section;
  this step verifies rather than assumes.

- [ ] **Step 2:** Regenerate the schema artifacts from the live app, in-process, no server needed:

```bash
python -c "import json; from src.api.main import create_app; \
print(json.dumps(create_app().openapi(), indent=2))" > docs/web/openapi.json
cd web && npm run gen:api
```

- [ ] **Step 3:** Confirm the four new routes and every new model appear in both files. A previous
  milestone found `api-types.ts` stale by three whole endpoints; check rather than trust.

- [ ] **Step 4:** `ARCHITECTURE.md`'s `src/api/` section gains `routers/portfolio.py` and
  `models/portfolio.py`; `README.md`'s layout table gains them too.

- [ ] **Step 5:** Run all six gate commands and commit.

---

## Milestone 2 acceptance

- [ ] Four `/portfolio/*` routes serve from `read_portfolio` and add no second data path.
- [ ] Every assignment-risk figure on those routes comes from M0 Task 0.3's
  `src/common/assignment_risk.py`. **No route in this milestone defines a threshold of its own** —
  verified by grepping the new router for a numeric delta or DTE literal and finding none.
- [ ] Every one of them is `owner_only`, proven with a non-owner role.
- [ ] Every one of them returns `200` with an explicit `source="none"` when nothing is captured.
  **None of them returns zeros in that case.**
- [ ] `as_of` is a capture time on the three snapshot-derived routes and request time on
  `/campaigns`, with the difference documented.
- [ ] Assigned shares report both cost bases; ordinary shares report `adjusted_cost_basis: None`.
- [ ] `consequence: "unknown"` is reachable and rendered.
- [ ] `docs/web/openapi.json` and `web/lib/api-types.ts` regenerate to an empty diff, and M0 Task
  0.5's `tests/test_openapi_current.py` is green.
- [ ] Full gate green, all six commands. **This milestone touches no trading code** — every
  trading-side change it once carried moved to M0 — so a failure outside `src/api/` here means
  something unrelated broke.
