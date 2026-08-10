# Design — Trading-System Remediation, Control API, and iOS App

**Date:** 2026-08-10
**Status:** Approved design, pending implementation plan
**Supersedes:** nothing. Complements `ARCHITECTURE.md` (how it's built) and `STATUS.md` (what's built).

---

## 1. Context

The system is a feature-complete, paper-only options-income desk: covered calls and cash-secured
puts on a ~60-symbol universe, with a deterministic Rules Engine as the sole path to an order and
a local LLM (`qwen3:8b` via Ollama) as advisory enrichment behind a hard architectural fence.
1,088 tests pass against a mocked IBKR. Nothing in the execution path has ever touched a live
broker.

A full-system review on 2026-08-10 found the engineering discipline sound and the architecture
correct — the fence, the two-stage risk gate, and the cumulative budget consumption are all right —
but identified three defects that would materially affect returns, plus a stated goal (stock
buying and selling) with no implementation at all.

### 1.1 The three defects

**D1 — CSP sizing and the concentration gate were never reconciled.** `screen_csp_candidates`
sizes to the *maximum affordable* lot (cash, 60% CSP budget, `max_contracts: 10`), knowing nothing
about `max_pct_per_ticker: 5.0`. `validate_candidates` then rejects rather than trims. A single
1-lot CSP therefore requires `NLV >= 2000 x strike`. At $300k NLV that excludes every strike above
$150.

**D2 — the income floor is a hidden IV floor of roughly 25-30%.** `min_roc_pct: 1.0` plus
`min_annualized_yield_pct: 12.0` produce a binding floor of `max(1.0%, 12% x DTE/365)`. Verified
with Black-Scholes at 30 DTE: SPY at 13.5% IV yields 0.33% ROC at 0.20 delta and 0.66% at 0.30
delta — rejected at every admissible delta. AAPL at 28% IV is rejected at 0.20 delta (0.71%) and
passes only at 0.30 (1.62%). Consequences: the defensive diversifiers deliberately added to
`universe.yaml` (GLD, TLT, XLP, XLU, XLV, XLI, SPY, V, MA, WMT, COST) can never produce a CSP, and
the gate acts as a hidden delta floor pushing every trade to the aggressive end of the configured
0.15-0.30 band.

Composed with D1, the emergent strategy is short puts on cheap, high-IV, speculative names only —
the opposite of the documented Tier 1 core-income intent, and an accident of two config numbers.

**D3 — there is no loss management, and the loss circuit breaker cannot see losses.** The only
exits are the 50% profit take, expiry, assignment, and roll *alerts* (execution default OFF, firing
at DTE <= 7). No stop-loss, no defensive delta exit, no 21-DTE management. `grep -i
"stop_loss|max_loss"` over `src/` and `config/` returns nothing. The one breaker meant to catch
this, `circuit_breakers.realized_cashflow_today`, sums `FillRow` credits and debits — so a day that
sells premium into a 15% drawdown registers as a profit and the kill switch stays open while the
15-minute loop opens more shorts into the same move.

### 1.2 Secondary defects

- **D4** — `rolling.py` demands net credit >= 1% ROC and >= 12% annualized from a roll, economics a
  challenged 0.60-delta short cannot produce; the roll list is empty exactly when the monitor
  fires. `rolling.py:39` also still uses `date_cls.today()`, the local-vs-ET bug the 2026-08-06
  audit fixed in 16 modules and missed here.
- **D5** — `campaigns.mark_campaign_assigned` computes `adjusted_cost_basis`, but only the
  `/campaigns` formatter reads it. `screen_cc_candidates` uses raw IBKR `avg_cost`, so with
  `min_strike_vs_basis: 1.00` the premium already collected is invisible to the gate deciding
  whether more may be collected.
- **D6** — IV rank ranks two different measurements against each other: `iv_history` stores IBKR's
  `OPTION_IMPLIED_VOLATILITY` daily bar (~30-day constant-maturity ATM index) while `current_iv` is
  overridden by `_live_atm_iv`, the mean IV of the four strikes nearest spot in the nearest scanned
  expiry (~21-25 DTE, intraday). In contango this biases IV rank down; in backwardation it biases
  up, loosening the gate exactly when the term structure inverts. IV rank is both the largest score
  weight (0.30) and a hard gate (`min_iv_rank: 30`).
- **D7** — every genuinely uncertain execution behaviour sits behind a default-off flag
  (`reprice_enabled`, `roll_execution_enabled`) and has never been exercised against a real broker.

### 1.3 The missing subsystem

`Strategy` is `COVERED_CALL | CASH_SECURED_PUT | ROLL`. `placeOrder` is called in exactly three
places (`executor.py`, `position_manager.py`, `roll_executor.py`), all options. `Stock()` appears
only for price lookups and contract qualification. `BuyCandidate` is scored, rendered to a Telegram
card, and discarded — no approve button, no order, no position tracking. There is no share exit
logic of any kind. The stock half of the stated goal does not exist.

There is also no HTTP surface anywhere in the repo, so an iOS app currently has nothing to talk to.

---

## 2. Goals

1. Make the deterministic layer trade the universe it was designed for, at the account's actual
   size, for economically correct reasons.
2. Give the system the ability to reduce risk on its own — the precondition for any unattended
   operation.
3. Reach genuine autonomy by graduated, evidence-gated stages rather than a switch.
4. Provide a native iOS client for monitoring and control, built only once the system beneath it is
   sound.

### 2.1 Non-goals

- Defined-risk spreads (put spreads, iron condors). Would solve capital efficiency on high-priced
  names but is a large new instrument surface. Explicitly out of scope; revisit after Phase 3.
- Margin-secured (naked) puts. Rejected in favour of true cash-securing — see §3.1.
- Replacing Telegram. It remains the alerting backbone; the app is a rich console. See §9.
- Postgres migration, ML regime detection, vol forecasting. Unchanged from `STATUS.md`.

The stock-trading leg (`BUY_STOCK`/`SELL_STOCK`) is **deferred, not excluded** — it is Phase 4, and
deliberately sequenced after the options path is validated live.

### 2.2 Account parameters this design assumes

Net liquidation ~$300,000, of which ~$100,000 is liquid USD; the remainder is existing positions.
All caps must be expressed so the system adapts as this changes, rather than being tuned to one
account size.

---

## 3. Part I — The capital model

### 3.1 Collateral treatment: true cash-secured

Every short put reserves full collateral (`strike x 100 x contracts`). IBKR would require ~20-25%
on a margin account; the system deliberately enforces the stricter model. The account can never be
assigned into a position it cannot pay for, and cannot be liquidated by a gap.

The consequence is accepted deliberately: at ~$100k liquid, the account can run **either** one
high-collateral position **or** roughly six standard ones. That is real arithmetic, and the design
makes it an explicit allocation choice (§3.4) rather than a side effect of share price.

### 3.2 The core insight

`max_pct_per_ticker: 5.0` is currently asked to answer three unrelated questions at once. Splitting
them resolves both D1 and the high-priced-name problem, because **share price is not a risk
measure** — a 10-for-1 split would make META tradeable overnight with identical risk.

### 3.3 Job 1 — feasibility, measured in cash

`max_csp_allocation_pct: 60` is measured against NLV ($180k) while only ~$100k of cash exists; the
budget can exceed the money. Likewise `min_buying_power_buffer_pct: 15` reserves $45k of a $100k
pile — a 45% reserve wearing a 15% label.

Both re-base onto available cash:

```yaml
portfolio:
  # Reserve held free at all times: the GREATER of a % of available cash and an absolute floor.
  # This is subtracted first; everything below operates on the remainder ("deployable cash").
  cash_reserve_pct: 20.0
  cash_reserve_absolute: 10000
  # Total CSP collateral as % of DEPLOYABLE CASH (not net liq, not gross cash).
  max_csp_allocation_pct_of_deployable: 100.0
```

Order of application is fixed and not configurable: `deployable = available_cash - reserve`, then
the CSP budget is a percentage of `deployable`. Setting the budget to 100.0 means "CSPs may use all
deployable cash"; lower it to hold room for share purchases in Phase 4. Expressing both against
gross cash would let the two knobs contradict each other.

This becomes the only gate that may reject a position for affordability, and it is the honest one.

### 3.4 Job 2 — concentration, measured in risk units

Per-ticker and per-sector caps move off raw collateral onto capital at risk over the option's life:

```
risk_units = collateral x IV x sqrt(DTE / 365)
```

| Position            | Collateral | IV   | Risk units |
| ------------------- | ---------- | ---- | ---------- |
| META 650P, 30 DTE   | $65,000    | 35%  | $6,520     |
| MARA 15P x10, 30 DTE| $15,000    | 110% | $4,730     |

Comparable, as they should be; the current model calls META 4.3x the position.

```yaml
portfolio:
  max_risk_units_per_ticker_pct: 5.0   # of net liq — SEE CALIBRATION NOTE
  max_risk_units_per_sector_pct: 25.0  # of net liq — SEE CALIBRATION NOTE
```

**Calibration note — the numeric values are NOT carried over from the collateral-based caps.**
Risk units are denominated in dollars but are roughly an order of magnitude smaller than collateral
(they are collateral scaled by `IV x sqrt(DTE/365)`, typically 0.05-0.30). Comparing them to a
percentage of net liquidation therefore expresses a *risk budget*, not an exposure budget, and 5.0
here is far more permissive than 5.0 was before. Both percentages must be re-derived empirically
using `capacity_report.py` (§7.3) before Phase 1 exits, not inherited from `risk_limits.yaml`.
Carrying the old numbers over unexamined would silently widen concentration limits several-fold —
the mirror image of the bug being fixed.

When IV is unavailable the candidate falls back to raw collateral against a separate, stricter
`max_collateral_per_ticker_pct` (strictly more conservative), and the fallback is recorded on the
verdict so it is visible on the card and in `risk_verdicts`.

### 3.5 Job 3 — the large-position slot

```yaml
portfolio:
  max_large_positions: 1              # concurrent positions allowed to exceed the standard cap
  max_pct_per_ticker_large: 25.0      # hard ceiling, raw collateral, % of net liq
```

At most N concurrent positions may exceed the standard per-ticker cap, bounded by a hard ceiling.
This is how a book carries one outsized high-conviction name without becoming a book of them.
Without it the only options are "META impossible" or "everything can be huge" — one number cannot
express a third.

Slot occupancy is computed from current positions at gate time, and a candidate that would take the
last slot is charged against it greedily in score order, consistent with the existing cumulative
budget model.

### 3.6 Job 4 — sizing computes to the binding constraint

```
contracts = floor(min(all headrooms) / (strike x 100))
reject only when contracts < 1
```

A single `capital.headroom_for(candidate, account, positions)` helper returns every headroom
(cash, CSP budget, ticker risk units, sector risk units, large-slot, BP reserve). Both
`screen_csp_candidates` and `validate_candidates` call it. Generator and gate disagreeing is the
root cause of D1; sharing one helper makes the disagreement unrepresentable.

### 3.7 Job 5 — a blocked CSP surfaces the share route

When cash blocks a CSP, the assessed block reports the alternative rather than silence:

> META CSP needs $65,000, $55,000 free. Share entry level $612.

`buy_below` is already computed by `fair_value._buy_below`. This turns a rejection into the other
path to the same exposure and is the natural on-ramp to the Phase 4 stock leg.

---

## 4. Part I — The income floor

`min_roc_pct` and `min_annualized_yield_pct` are replaced as the primary gate by the
variance-risk-premium floor already implemented in `fair_value._min_credit`: Black-Scholes fair
value at realised vol (HV30), plus `min_credit_edge_pct`. A small absolute ROC floor remains solely
to reject noise trades.

The gate stops asking "is this yield big enough?" and starts asking "am I being paid more than this
risk is worth?" — the only question a premium seller should ask. The hidden delta floor disappears
as a side effect.

| Symbol         | IV    | Today (1% ROC)     | Under VRP floor                  |
| -------------- | ----- | ------------------ | -------------------------------- |
| SPY 0.20d 30d  | 13.5% | rejected (0.33%)   | passes when IV > HV30 + edge     |
| XLP/XLU/TLT    | 15-20%| rejected           | passes when vol is genuinely rich|
| AAPL 0.20d     | 28%   | rejected (0.71%)   | passes                           |
| MARA           | 110%  | passes on ROC      | rejected when IV ~= HV           |

```yaml
income:
  min_roc_pct: 0.15                 # noise floor only
  min_annualized_yield_pct: 0.0     # retired as primary gate
  require_vrp_edge: true            # promote _min_credit from display to gate
```

`min_credit_edge_pct` (currently 10.0, under `ideal_zone`) becomes a live gate parameter and moves
to the `income` block; `ideal_zone` reads it from there so display and gate can never diverge.

`fair_value.py` remains deterministic-tier and may continue to read only technicals, IV,
fundamentals, and Black-Scholes. Promoting it to a gate does not change its tier and does not
weaken the fence — it is already forbidden from importing sentiment, macro, or anything under
`src.claude`, and `tests/test_eval_skills.py` continues to assert this.

---

## 5. Part I — Loss management

All three of §5.1, §5.3, and a measured fill rate (§7.4) are hard prerequisites for any auto-open
autonomy rung.

### 5.1 A loss-side exit

```yaml
automation:
  max_loss_multiple: 2.0     # buy to close when cost-to-close >= N x entry credit
```

Implemented as `check_loss_exits`, a sibling to `check_profit_takes` in the same 15-minute cycle,
routing through `position_manager.close_short_position` — which already provides the
`OrderRow`/`FillRow` lifecycle, cancel-on-timeout, and contract-level idempotency. Entry credit
comes from `net_entry_credit_per_share`, already used by the profit-take path.

### 5.2 Risk-reducing actions get their own switch

Profit-takes currently auto-execute only in AUTOMATED mode, conflating two questions. MANUAL/AUTO
governs *opening* exposure; the codebase already treats closing differently (buy-to-close correctly
skips the income risk gate as risk-reducing).

```yaml
automation:
  auto_close_enabled: true   # independent of autonomy level
```

Closing risk never waits for a tap.

### 5.3 A kill switch that can see losses

`realized_cashflow_today` is replaced as the breaker input by mark-based P&L. `position_snapshots`
is already written daily for assignment detection; extend it to every intraday cycle (also required
by §8.2) and diff `unrealized_pnl` against the prior baseline, plus realized cashflow.

```yaml
automation:
  daily_loss_halt_pct: 3.0          # mark-based, % of net liq
  drawdown_halt_pct: 10.0           # NLV vs trailing high-water mark
```

The second breaker catches slow bleeds no single day trips. `realized_cashflow_today` is retained
for EOD reporting, where it is the correct measure, but is no longer wired to the breaker.

### 5.4 Defensive rolls judged as defence

```yaml
monitor:
  roll_defensive:
    max_debit: 0.50                 # per share; a defensive roll may cost money
    min_delta_reduction: 0.10       # the new leg must be meaningfully further OTM
    require_breakeven_improvement: true
```

Defensive rolls drop the ROC and annualized-yield tests entirely and are judged on delta reduction
and breakeven improvement. Income rolls (unchallenged positions rolled for credit) keep the
existing economics. The same change fixes `rolling.py:39` (`date_cls.today()` -> `today_et()`).

### 5.5 Manage at 21 DTE

```yaml
monitor:
  manage_at_dte: 21
```

Entry is 21-45 DTE and the roll trigger fires at DTE <= 7 — deep into gamma with no room to
manoeuvre. A mechanical decision point at 21 DTE: close, roll, or explicitly hold.

---

## 6. Part I — The autonomy ladder

The binary `/mode MANUAL|AUTOMATED` is replaced by four rungs.

| Level       | Opens positions              | Closes positions |
| ----------- | ---------------------------- | ---------------- |
| `observe`   | never — proposals only       | never            |
| `manual`    | human tap                    | automatic        |
| `whitelist` | auto, whitelisted names only | automatic        |
| `full`      | auto, anything passing gates | automatic        |

```yaml
autonomy:
  level: observe
  whitelist: []
```

Auto-close is on from `manual` upward, per §5.2.

### 6.1 Promotion gates

Objective and checkable, surfaced in `/status` and on the app's Account screen with current
progress:

- **observe -> manual**: 20+ scans with no unhandled errors; `iv_history` current for every universe
  symbol.
- **manual -> whitelist**: >= 20 real fills; measured fill rate at mid >= 60%; zero live re-gate
  surprises; loss exits observed firing at least once.
- **whitelist -> full**: >= 3 months at `whitelist`; positive expectancy over closed trades;
  mark-based halt exercised at least once, in anger or in a deliberate drill.

Promotion is a human action; the system reports readiness and refuses promotion when criteria are
unmet.

### 6.2 Hard prerequisite

No auto-open rung unlocks until §5.1, §5.3, and a measured fill rate all exist. Opening exposure
unattended without a working loss exit or a kill switch that can see losses is the one
configuration of this system that can genuinely cause harm.

---

## 7. Part I — Correctness fixes

### 7.1 Wheel cost basis reaches the CC gate (D5)

A `cost_basis_for(symbol, position)` resolver prefers an open assigned campaign's
`adjusted_cost_basis` over IBKR `avg_cost`, falling back cleanly when no campaign exists. Three call
sites in `covered_call.py`: the `min_strike_vs_basis` gate, `roc_pct`, and the `cost_basis` passed
to the ideal zone.

Second-order effect, intended: `min_strike_vs_basis: 1.00` measured against a $145.50 adjusted basis
rather than a $150.00 assignment price is a different and more correct policy, and loosens in the
operator's favour without touching the knob.

### 7.2 IV rank measures one thing (D6)

The live chain IV is interpolated to constant 30-day maturity before ranking, using the term
structure already computed in `_term_structure_slope`. When the chain carries fewer than two
expiries, fall back to the stored daily observation rather than the nearest-expiry value. This
preserves intraday responsiveness while making numerator and denominator the same measurement.

### 7.3 `scripts/capacity_report.py`

Given current NLV, positions, and universe: for every symbol, what does the system actually permit?
Contracts affordable, which gate binds first, and what the account would need for one lot.

This is the regression test the suite lacks — 1,088 tests ask "does the gate reject what it says it
rejects" and never "what can this system trade today," which is why D1 and D2 both passed CI. It
becomes a permanent artifact and the data source for the app's Account screen (§10).

### 7.4 Live paper validation session (D7)

Measurement, not code, and a hard gate on Phase 3. Five questions:

1. Fill rate of a mid-price DAY limit over 5 minutes, by liquidity tier, n >= 20 orders.
2. Whether `reprice_enabled: true` amend works (`placeOrder` with the same orderId).
3. Whether the BAG combo sign convention is correct on a real roll (negative limit = net credit) —
   mock-tested only today.
4. **Whether `greeks_source == "ibkr"` ever populates on this data subscription.** If it does not,
   `require_ibkr_greeks_when_live: true` will silently block 100% of live income trades. Must be
   learned on paper.
5. Whether Tier 3 names (SOXL, MARA, RGTI) produce candidates end-to-end — flagged unverified since
   N6.

Results are recorded in `STATUS.md` and gate the corresponding default-off flags.

---

## 8. Part I — Deletions

Under the mandatory doc-update rule every module carries a standing tax in `ARCHITECTURE.md`,
`STATUS.md`, and the fence tests. These are not paying it.

| Remove                                                    | Rationale                                                                                                   | Keep                                        |
| --------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- | ------------------------------------------- |
| `src/claude/skills/`, `scripts/propose_skill.py`, `scripts/skills.py` | Drafts playbooks to improve a verdict deliberately inert in auto mode; needs years of closed trades to signal | —                                           |
| `src/claude/eval/metrics.py`, `scripts/evaluate_verdicts.py` | Brier/EV calibration of a model that cannot change a decision; admittedly survivorship-conditioned            | `eval/ledger.py`, `eval/reconcile.py`       |
| `config/profiles/`, `/profile` command, `src/common/profile.py` | Four parameter overlays on a system that has not validated one set live                                       | —                                           |
| `option_quotes` table                                     | Two write-only audit tables, two pruning jobs, zero readers; the raw chain dump is the less useful of the two | `risk_verdicts` — stage + reasons + zone per assessed contract is the forensics that answers "why did nothing trade" |
| Backtest v1 (BS at trailing HV)                            | Expected edge ~= 0 by construction, per its own docs                                                          | v2 (`--use-stored-iv`), which measures VRP  |
| `max_correlated_exposure_pct`                              | Configured, documented, unenforced — worse than no limit                                                     | —                                           |
| `annualized_roc` weight                                    | Superseded by the VRP floor (§4)                                                                             | `zone_fit`, set to a real value or removed  |

Removing `src/common/profile.py` requires replacing `get_effective_risk()` / `get_effective_weights()`
call sites (used throughout the engine and strategies) with direct config reads. This is mechanical
but touches many files and must be a single, self-contained commit.

### 8.1 One structural refactor, as a prerequisite

`src/orchestrator/scan.py` is 1,943 lines mixing pipeline, progress tracking, and Telegram
rendering. The API must trigger a scan and read its result without importing the Telegram layer.
Split into pipeline / orchestration / presentation **before** Phase 3, or the API grows a Telegram
dependency it can never shed.

`src/notify/formatters.py` (1,990 lines) has the same problem at lower stakes — the API will not
reuse MarkdownV2 renderers. Split opportunistically, not as a gate.

---

## 9. Part II — The control API

### 9.1 Process and network model

A new package `src/api/`, run as a fourth process under `scripts.start`: FastAPI + uvicorn, bound to
the Tailscale interface only.
**No `ib_async` connection** — hence no clientId, no contention with the existing four processes,
and structurally no path to `placeOrder`. Tailscale (free tier) provides the private mesh;
`tailscale serve` issues a real TLS certificate for the `*.ts.net` hostname, so iOS App Transport
Security is satisfied without an exception. A bearer token in Keychain sits on top, so that another
device on the tailnet is not automatically authorised to trade.

Cloudflare Tunnel was considered and rejected: it requires wiring Access service tokens into a
native client, and it places a third party in the path of a system that can place trades. Tailscale
has no public endpoint at all.

### 9.2 Reads come from SQLite

The API never talks to IBKR. `approval_service` already fetches positions every 15 minutes and
persists `position_snapshots` daily; extend that to persist every cycle (also required by §5.3).
The API serves from the DB with an explicit `as_of` on every payload. Staleness is bounded at 15
minutes and always visible. On-demand freshness is a `refresh` intent picked up by the existing
30-second poll.

SQLite is already in WAL mode, so a read-only connection from a second process is safe.

### 9.3 Writes go through an intent queue

One new table:

```
app_commands(id, kind, payload_json, status, result_json, created_at, applied_at)
  status: pending | applied | failed
  kind:   approve | reject | universe_add | universe_remove
        | set_autonomy | halt | resume | trigger_scan | refresh
```

Drained by the poll loop already running in `approval_service`. The load-bearing property:
`approve` performs **exactly the same `ApprovalRow` mutation `_process_button` performs today** —
same code path, same N2a snapshot freeze, same execution-time re-gate. Every safety property
already tested holds unchanged, and the phone inherits them rather than re-implementing them.

The API can create intent. It cannot create orders.

### 9.4 Universe editing without touching YAML

`universe.yaml` is human-curated, comment-rich, and cached by `get_config()`. An API that rewrites
it would destroy the tier documentation and race the loader.

Instead, a `universe_overrides(symbol, list_name, action, created_at)` table is composed onto the
YAML at config load. `list_name` is `would_own` or `watchlist`; `action` is `add` or `remove`. The
file remains the documented base; the app writes reversible, auditable deltas. A new `/universe`
Telegram command uses the same mechanism, so it is built once.

### 9.5 Universe suggestions

`scripts/suggest_universe.py`, run weekly from the EOD job, scores a candidate pool (liquid ETFs and
large caps) on option liquidity (OI, volume, spread), IV-history availability, realised VRP over the
trailing year, fundamental quality flag, and **sector fit against current book concentration** — so
it proposes what the book is missing rather than more of what it already holds. Writes
`universe_suggestions(symbol, score, rationale, sector, computed_at)`; the API serves it with the
rationale attached.

### 9.6 Endpoints

```
GET  /health                    daemon liveness, IBKR connection state, last scan time
GET  /account                   NLV, cash, buying power, autonomy level + promotion progress
GET  /capacity                  §7.3 capacity report, per symbol
GET  /positions                 open positions with P&L, DTE, delta, assignment-risk flags
GET  /positions/{symbol}/campaign   wheel thread for one symbol
GET  /proposals                 current candidates + verdicts + ideal zones
GET  /proposals/assessed        assessed-but-not-approved, with per-contract reasons
GET  /universe                  effective universe (YAML + overrides), grouped by list
GET  /universe/suggestions      system suggestions with rationale
GET  /commands/{id}             status of a submitted intent
POST /commands                  submit an intent (see §9.3)
```

### 9.7 Error handling

If `approval_service` is down, commands queue rather than fail. The client therefore **must**
distinguish `pending` from `applied` — a queued approval rendering as an executed one is the single
most dangerous failure mode in this design. `GET /commands/{id}` exists for exactly this.

SQLite lock contention is retried with bounded backoff; a persistent failure returns 503 with the
last-known `as_of`, and the client falls back to its cache.

### 9.8 Testing

FastAPI `TestClient` against a temporary SQLite database, plus contract tests pinning every response
to its Pydantic schema. The OpenAPI document is exported to `docs/openapi.json` and the Swift models
are generated from it, so client and server cannot drift.

---

## 10. Part III — The iOS app

SwiftUI, iOS 17+, `@Observable`, async/await `URLSession`, `Codable` models generated from the
OpenAPI spec. **No third-party dependencies.** Bearer token in Keychain.

Telegram remains the alerting backbone. The app is a rich console, never the critical path for a
time-sensitive approval. This avoids the $99/yr Apple Developer Program requirement for APNs
push — though $99/yr is still recommended, since free provisioning re-signs every 7 days.

### 10.1 Screens

**Positions** — open positions with P&L, DTE, delta, and assignment-risk flags; tap through to the
campaign thread so a wheel reads as one story (CSP -> assignment -> CC -> roll) rather than
disconnected legs. This is the first proper surface for `campaigns.py`.

**Proposals** — candidates with score, ideal-price zone, and model verdict; approve/reject inline.
Also renders the **assessed-but-not-approved** list with per-contract reasons — the most useful
output the system produces and the one Telegram renders worst.

**Account** — NLV, cash, buying power; current autonomy rung with promotion criteria and progress;
halt switch; and the §7.3 capacity report, which directly answers the question that surfaced D1 and
D2.

**Universe** — `would_own` and `watchlist` with add/remove, plus system suggestions with rationale
and sector-fit reasoning.

### 10.2 Three rules that keep it from feeling clunky

1. **Offline-first.** Cache the last good response; show `as_of` everywhere. Never a spinner over a
   blank screen — a phone on a train shows yesterday's book, clearly labelled.
2. **Provenance on every number.** The backend already tracks `price_source` and `greeks_source`. A
   delta derived from yfinance Black-Scholes must not look identical to one from IBKR.
3. **Never claim more than the backend did.** Approve renders `queued -> applied -> filled` from
   real state. There is no "execute now" button, because no such path exists; the app must not imply
   capability the system lacks.

### 10.3 Build order within the phase

All four screens read-only against the API first, then the three write paths (approve/reject,
universe edit, autonomy/halt). Ship only when both halves are complete.

### 10.4 Testing

Swift Testing for model decoding and view-model state transitions against recorded API fixtures.
XCUITest for the two flows where a mistake is expensive: approving a proposal, and editing the
universe. No live-network tests in CI.

---

## 11. Sequencing

Each phase ends in a state that is coherent and shippable on its own.

| Phase | Content | Exit criteria |
| ----- | ------- | ------------- |
| **1 — Capital & income** (§3, §4) | Shared headroom helper, risk-unit concentration, large-position slot, cash-based feasibility, VRP income floor, `capacity_report.py` | `capacity_report` shows a broad, sane tradeable set at $300k; full suite green; `ARCHITECTURE.md`/`STATUS.md` updated |
| **2 — Loss management & autonomy** (§5, §6) | Loss exits, independent auto-close switch, mark-based + drawdown breakers, defensive rolls, 21-DTE management, autonomy ladder | Loss exit demonstrably fires on paper; breaker trips in a drill; ladder at `observe` |
| **3 — Validation & cleanup** (§7.4, §8) | Live paper session, deletions, `scan.py` split | Five §7.4 questions answered and recorded; default-off flags resolved; ladder promoted to `manual` |
| **4 — Stock leg** (§2.1) | `BUY_STOCK`/`SELL_STOCK`, `BuyCandidate` execution path, share exit rules | Wheel runs end to end including share entry and exit |
| **5 — Control API** (§9) | FastAPI process, intent queue, universe overrides, suggestions, Tailscale | OpenAPI exported; contract tests green; Telegram and API produce identical effects |
| **6 — iOS app** (§10) | Four screens, read then write | Both halves complete; XCUITest green on the two critical flows |

Phases 1-3 are strictly ordered. Phase 4 may run in parallel with Phase 5 if desired — they touch
disjoint code. Phase 6 depends only on Phase 5.

Autonomy promotion beyond `manual` requires Phase 2 complete and the §6.1 criteria met; it is not a
phase deliverable but an ongoing, evidence-gated decision.

---

## 12. Testing strategy

The existing suite's blind spot is that it verifies *mechanism* without verifying *outcome*. Every
phase adds outcome-level tests:

- **Phase 1** — property tests over an account-size range: for NLV in {50k, 300k, 1M} and the full
  universe, assert the tradeable set is non-empty and that no symbol is excluded solely on share
  price. This is the test class that would have caught D1 and D2.
- **Phase 2** — simulated position lifecycles: a short that moves against the book must produce a
  loss exit; a mark-based drawdown must trip the breaker while cashflow is positive (the exact
  scenario the current breaker misses).
- **Phase 3** — recorded live-session fixtures replayed in CI, so real IBKR quote shapes are
  exercised without a connection.
- **Phase 5** — contract tests asserting that an API `approve` and a Telegram approve produce
  byte-identical `ApprovalRow` state.
- **Phase 6** — decoding and state-transition tests against recorded fixtures; UI tests on approve
  and universe-edit.

The fence tests (`tests/test_eval_skills.py`) remain green throughout and are extended to cover the
new API package: nothing under `src/api/` may be imported by `engine/`, `execution/`, or
`strategies/`.

---

## 13. Decisions recorded

| Decision | Choice | Rationale |
| -------- | ------ | --------- |
| Income floor | Promote `_min_credit` VRP floor to gate (A1) | Economically correct, self-adapting across vol regimes, code already exists |
| Concentration unit | Risk units, not raw collateral (B3) | Share price is not a risk measure; collateral% cannot be patched into correctness |
| Collateral model | True cash-secured | Cannot be assigned into an unaffordable position or liquidated by a gap |
| High-priced names | Large-position slot, bounded and counted | Makes META deliberate rather than impossible or accidental |
| API shape | Separate process, intent queue (C1) | The phone physically cannot place an order; the tested chokepoint stays sole authority |
| Network | Tailscale | Free, no public endpoint, no auth flow in the client, TLS via `tailscale serve` |
| Telegram | Retained as alert backbone | Reliable push without Apple Developer Program; app never on the critical path |
| Autonomy | Four-rung ladder, whitelist interim, `full` destination | Autonomy arrived at with evidence rather than switched on |
| Spreads | Out of scope | Would solve capital efficiency but is a large new instrument surface; revisit after Phase 3 |
