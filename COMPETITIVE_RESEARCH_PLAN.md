# Competitive Research & Improvement Plan — Puthouse and peers

**Created:** 2026-06-21
**Source:** Multi-agent web research into [puthouse.com](https://puthouse.com) (product, social, community) and the
broader options-income / wheel-strategy tool landscape (Option Alpha, tastytrade, QuantWheel, Option
Samurai, Market Chameleon, Tiblio, ThinkorSwim, OptionStrat, Barchart, wheel trackers).
**Baseline at planning time:** 581 tests green at the close of Improvement Plan v2 (2026-06-13); re-run
the quality gate before starting Phase 1.
**Purpose:** (Part A) document what was found; (Part B) register the features worth borrowing with
include/exclude decisions; (Part C) sequence the selected work phase by phase. Same tracker format as
`Archive/Improvement_Plans/IMPROVEMENT_PLAN_2.md` — tick the boxes and update the per-phase gate line as
work lands.

---

# Part A — Research findings

## A1. What Puthouse is

Puthouse ("PutHouse: AI options trader", "Earn income with your stocks automatically") is a **fully
automated, consumer-facing options-income SaaS** — a solo-founder product (Janson Lau, ex-Google
engineer; PutHouse, Inc., © 2026) launched ~January 2026. It connects to a user's **Alpaca** account via
OAuth and **auto-executes covered calls and cash-secured puts** as an income overlay on stocks the user
holds. It is not a screener, newsletter, or signal service — it places and manages the orders.

It is, in substance, **a commercial clone of this system's thesis**: the same two strategies (CC + CSP),
the same "deterministic guardrails first, explain every trade" philosophy, the same core signals
(IV, delta, RSI, DTE).

| | Puthouse | This system |
|---|---|---|
| Broker | Alpaca only | IBKR (full order control) |
| Execution | Full autopilot | Semi-autonomous + Telegram approval |
| "AI" role | Plain-English trade narration / selection | Claude reasoning **behind a fenced deterministic risk gate** |
| Audience | Beginners / busy professionals | Operator (single account) |
| Price | Free / $49 / $149 mo | — |

### Puthouse feature inventory (what they actually ship)

- **Two strategies only:** covered calls and cash-secured puts. No spreads, no naked, no multi-leg.
  Signature metaphor: "sell contracts, like insurance."
- **Six guardrail categories** (maps ~1:1 onto `risk_limits.yaml`): position sizing / per-symbol caps,
  entry filters (DTE bands, delta targets, IV ranges), liquidity filters (spread, OI, volume), market
  quality (price ≥ $20, volume minimums), rules-based exits (profit target, delta-risk exit, loss cap),
  safer timing (no entries in stressed markets or near earnings).
- **Named signals, shown on every trade card:** delta ("for probability"), **IV/RV ratio** as the
  premium-quality gate (their stated threshold: needs **≥ 1.05** — sell only when implied vol exceeds
  realized vol), **RSI** for entry timing (avoid selling calls right after a run-up), IV%, DTE, strike,
  premium.
- **Transparency UX (their strongest differentiator):** an AI explanation on every trade *and on every
  skip* — e.g. "Passed on a covered call because premium was not high enough. Stock $142.30, RSI 67.8,
  IV 58.2%, IV/RV 0.82 (needs 1.05+)." Timestamped emoji trade-feed cards ("📈 New order", "⏸️ Skipped",
  "📈 Closing a winner"). A **P&L calendar** (per-day $ gains/losses). Metric tiles (Options P&L, Return
  on Capital, Total Trades, Win Rate).
- **Active management to avoid assignment:** closes options before expiration, profit-taking (e.g. bought
  back a SOFI call at $0.31 for a 50% gain), roll suggestions/hedges, reinvestment/compounding.
- **Tiers gate customization:** Free = paper only; Pro ($49) = live with *predefined* modes; Max ($149) =
  self-configurable settings (take-profit, momentum filters, expiration windows) + 1-on-1 training.
- **Capital guidance:** start at $2k (1 contract, $20 min stock price); recommends $25k+.
- **Claimed edge:** "speed, discipline, and scale" + full transparency; "not a black box." Backtest
  2012–Mar 2026 on a mega-cap basket: overlay 1612% vs buy-and-hold 1509% — a **thin, mixed edge** that
  mostly came from one drawdown window (Feb–Apr 2025: −9.7% vs −17.5%).

## A2. Community reality check

Puthouse has **near-zero organic traction** — relevant when weighing how much to copy. YouTube 17 subs,
Discord 11 members, Threads ~1 follower; a "Show HN" scored 2 points with 0 comments; **zero Reddit
mentions** (r/thetagang, r/options, r/CoveredCalls); no third-party reviews, no press. The inspiration is
in their **feature framing and transparency UX**, not in proven product-market fit. (Note: the well-known
open-source `ThetaGang` IBKR bot by brndnmtthws is a different project people sometimes conflate.)

## A3. Competitor landscape — ideas worth stealing

- **Option Alpha** (closest architectural reference for a semi-autonomous bot): Scanners (enter) vs
  Monitors (manage) split; **SmartPricing** = walk the limit across timed intervals toward NBBO with a
  hard profit floor (vs a static mid); minute-by-minute automated exits (profit target / stop / DTE /
  earnings).
- **tastytrade:** **P50 / ePoP** (Monte-Carlo probability of reaching 50% of max profit) instead of
  delta-as-POP; a single proprietary **liquidity score**; beta-weighted portfolio delta; free backtester
  with explicit exit conditions.
- **QuantWheel / Tiblio:** purpose-built wheel tools — **Roll Assistant / Roll Finder** ("optimal roll to
  avoid assignment" with concrete strikes), **assignment-risk alerts**, **campaign chaining** (CSP →
  assignment → CC → roll → close as one P&L thread with auto cost-basis), composite "Setup Score",
  scan modes ("Find Deals" / "Covered Calls" / "Roll" / "Vol Crush").
- **Option Samurai:** 100+ filters; sort scans by **edge / probability / expected return**; **IV-vs-HV
  ratio**; **scan templates/presets** (start from a working scan, not a blank form).
- **Market Chameleon:** per-strategy **backtest across prior earnings cycles**; term-structure & fixed-
  strike IV matrices for strike/expiry selection.
- **Barchart:** scheduled income-screener **digests emailed with CSV** (maps to Telegram delivery).
- **OptionStrat / ThinkorSwim:** payoff-diagram heatmaps and probability overlays.

## A4. Where this system is already ahead

- **Claude as a true reasoning layer behind a double-firing deterministic risk gate** is more sophisticated
  than any competitor's "AI" (which is suggestion-only chat or pure deterministic recipes).
- **IBKR-native with full order control** — most automation peers are read-only or stuck on
  Tradier/TradeStation/Schwab/Alpaca.
- **Telegram human-in-the-loop approval** occupies a sweet spot between full autopilot (Puthouse / Option
  Alpha) and manual screeners (Samurai / Barchart) that none of them cleanly hold.
- Several "borrow" targets are **already built here**: earnings blackout (`earnings_blackout_days: 14`),
  roll combo execution and limit repricing (both coded, gated OFF pending live-paper verification), a
  per-scan rejection tally, IV history, and a v2 backtest harness that prices from stored IV.

---

# Part B — Findings register (borrowable features)

Decisions captured from the planning Q&A. **IN** = scheduled below; **OUT** = excluded with rationale in
Part D. The "current state" column is what already exists, so each task is scoped as *new* vs *extend* vs
*activate*.

| ID | Feature | Decision | Current state → scope |
|---|---|---|---|
| **C1** | **IV/RV richness gate** — sell only when implied vol richly exceeds realized vol (Puthouse's ≥1.05 gate) | **IN** | IV history exists; **no realized-vol helper** → new realized-vol calc + new gate + score input |
| **C2** | **Annualized ROC normalization** — rank candidates on annualized return-on-capital across DTE | **IN** | ROC computed per candidate today but not annualized for cross-DTE ranking → extend scoring |
| **C3** | **Roll Assistant — wire & activate** — monitor → roll candidate → approval → execute | **IN** | `roll_pipeline.py` + `execute_roll` exist, gated OFF (`monitor.roll_execution_enabled`); BAG sign unverified → wire generator + live-paper verify + enable |
| **C4** | **Assignment-risk alerts** — Telegram alert on deep-ITM / high prob-ITM shorts near expiry | **IN** | none → new monitor check + formatter |
| **C5** | **SmartPricing fill-walking — verify & enable** — walk limit toward NBBO with profit floor | **IN** | `execution.reprice_*` coded, `reprice_enabled: false` → live-paper verify + enable (+ extend to close/roll legs) |
| **C6** | **Campaign chaining + auto cost-basis** — link CSP→assignment→CC→roll→close into one P&L thread | **IN** | candidate_id links exist per-leg; no campaign rollup / ACB → new storage model + rollup |
| **C7** | **Skipped-trade reasons in Telegram** — per-symbol "why nothing fired / why rejected" | **IN** | `rejection_tally` exists (top-3 gate breakdown) → extend to per-symbol surfacing + formatter |
| **C8** | **P&L calendar + richer trade-feed cards** — per-day P&L view + emoji narration cards | **IN** | EOD summary + order notifications exist → new calendar formatter + card styling |
| **C9** | **Named trading modes / scan presets** — conservative/balanced/aggressive YAML profiles | **IN** | single `risk_limits.yaml`/`scoring_weights.yaml` → add selectable profile overlay |
| **C10** | **Earnings-cycle backtest + vol-crush mode** — backtest a candidate across prior earnings cycles | **IN** | earnings *blackout* already exists; backtest v2 exists → extend backtest with earnings-cycle + vol-crush |
| **C11** | **Backtest-on-demand for a candidate** — command/Claude action to backtest params before approval | **IN** | backtest v2 + CLI exist → wire a per-candidate entrypoint |
| C-x1 | P50 / Monte-Carlo POP | **OUT** | see Part D |
| C-x2 | RSI-after-runup avoidance | **OUT** | see Part D |
| C-x3 | Payoff / P&L heatmap image in approvals | **OUT** | see Part D |
| C-x4 | Composite liquidity/tradeability score | **OUT** | see Part D |
| C-x5 | Dealer positioning (GEX / max-pain / put-call walls) | **OUT** | see Part D |

**Fence reminder (CLAUDE.md):** every signal/scoring change below (C1, C2, C10, C11) feeds **verdict and
ranking only**. Gates, weights, and contract counts remain human-edited config. Nothing here may become
importable from `engine/`, `execution/`, or the sizing path. C1's gate is a *deterministic Python gate in
the risk engine / strategy generator* (human-configured threshold), **not** an LLM output — that keeps it
on the correct side of the fence.

---

# Part C — Phased implementation plan

Run the quality gate (`pytest -q` · `ruff check .` · `mypy src`) after every change set, add/adjust tests
for changed behaviour, and apply the CLAUDE.md doc-update rule. Update the per-phase gate line when done.

### Phase 1 — Signal layer (changes what gets ranked/traded) ✅ 2026-06-21
*Do before any further AUTOMATED-mode runs, mirroring the v2 plan's "signal integrity first" ordering.*

- [x] **C1 — IV/RV richness gate.**
  - `src/analytics/realized_vol.py` — `compute_realized_vol(symbol, window=20)` (log-return annualized HV).
  - `IVStats.iv_rv_ratio` and `TradeCandidate.iv_rv_ratio` added to `schemas.py`.
  - `iv.py` computes `iv_rv_ratio = current_iv_pct / realized_vol` using `realized_vol_window` from config.
  - `risk_engine.py` gates on `iv_rv_below_minimum` when `iv_rv_ratio < min_iv_rv_ratio` (both readable from
    `risk_limits.yaml → iv`; defaults 1.05 / 20d). Missing ratio is soft-fail (no scan block).
  - `formatters.py` displays `IV/RV X.XX` on the approval card.
  - Tests: realized-vol math (manual log-return verification), gate pass/fail at threshold, None handling,
    IV/RV ratio on IVStats, ratio-below-minimum rejection tally.
- [x] **C2 — Annualized ROC normalization.**
  - `ScoreCard.annualized_roc_score` (0-100, cap 100%) added to `schemas.py`; computed by
    `strategies/_scoring.py::annualized_roc_score(annualized_yield_pct)`.
  - Both `covered_call.py` and `cash_secured_put.py` populate it on every `ScoreCard`.
  - `scoring.py` includes `annualized_roc_score * w.get("annualized_roc", 0.0)` in the blended score.
  - `scoring_weights.yaml → covered_call/cash_secured_put → annualized_roc: 0.0` (off by default, tunable).
  - Tests: cap at 100% (blow-up prevention), score at midpoint, ranking order with non-zero weight.

**Gate after Phase 1:** ✅ tests (all pass) · ✅ ruff · ✅ mypy · ✅ docs (ARCHITECTURE config/schemas, STATUS)

### Phase 2 — Active position management (activate built code + one new alert) ⬜
*Highest-leverage gaps; two of three are "verify on paper, then enable".*

- [ ] **C3 — Roll Assistant: wire & activate.**
  - Wire `strategies/rolling.generate_roll_candidates` into the monitor → approval flow via the existing
    `execution/roll_pipeline.py` so an ITM short produces a concrete roll candidate (new strike/expiry,
    net credit, new POP, "roll vs take assignment" framing) as a PENDING approval.
  - **Blocker:** verify the BAG combo limit-price sign convention on **live paper** before enabling
    (logged in STATUS.md). Then flip `monitor.roll_execution_enabled: true`.
  - Tests: generator → pipeline → PENDING approval path; exposure-neutral validation already covers ROLL.
- [x] **C4 — Assignment-risk alerts.** ✅ 2026-06-21
  - `monitor/triggers.py::check_assignment_risk` — fires when `|delta| ≥ assignment_alert_delta` (default
    0.70) AND `DTE ≤ assignment_alert_dte` (default 21); trigger string `"assignment_risk"`.
  - `MonitorCfg` + `config/settings.yaml` → `monitor.assignment_alert_delta / assignment_alert_dte`.
  - `intraday.py::_on_pending_tickers` passes both keys into the limits dict; `fire_alerts` dispatches to
    `format_assignment_alert` when all fresh alerts are `assignment_risk` type.
  - `notify/formatters.py::format_assignment_alert` — MarkdownV2 card with |Δ|/DTE header and
    "roll / close / let-assign" action menu; Claude review section same as roll alert.
  - Tests (7): fires at/above threshold, skips when delta below / DTE above / long position / missing
    delta, fires exactly at threshold, `check_all` includes it, formatter card content, Claude section.
- [x] **C5 — SmartPricing fill-walking: extend to close/roll legs.** ✅ 2026-06-21 (code only)
  - `position_manager.close_short_position` — BUY reprice loop steps toward ask.
  - `roll_executor.execute_roll` — re-fetches per-leg bid/ask, recomputes live net credit, steps
    BAG net-limit toward market; ceiling = `min_live_premium_ratio × approved credit`.
  - Tests (3): `test_close_reprice_steps_toward_ask`, `test_roll_reprice_steps_toward_market`,
    `test_roll_reprice_floor_not_breached`.
  - **Still required before enabling:** verify `placeOrder` amend on live paper (entry SELL first,
    then close/roll), then set `execution.reprice_enabled: true`.

**Gate after Phase 2:** ✅ tests · ✅ ruff · ✅ mypy · ✅ docs (ARCHITECTURE + STATUS)

### Phase 3 — Transparency & UX (Puthouse's strongest area) ✅ 2026-06-21
*Low-risk, high-trust; mostly formatter work.*

- [x] **C7 — Skipped-trade reasons in Telegram.**
  - Extend the per-scan `rejection_tally` into a per-symbol breakdown so the operator sees *why* each
    surfaced name didn't produce a trade (e.g. "AAPL: iv_rank_below_minimum", "MARA: iv_rv 0.82 < 1.05").
  - New/extended formatter; attach to the scan summary message (keep it compact; respect append-dedup).
  - Tests: per-symbol reason rollup; formatter snapshot.
- [x] **C8 — P&L calendar + richer trade-feed cards.**
  - Calendar: a per-day realized-cashflow view (build on the EOD summary data) as a Telegram message
    (text/table; image only if needed later — see C-x3 exclusion).
  - Cards: emoji-prefixed narration for order/skip/close events ("📈 New order", "⏸️ Skipped",
    "📈 Closing a winner") consistent with existing order notifications.
  - Tests: calendar aggregation; card formatting.
- [x] **C9 — Named trading modes / scan presets.**
  - Add selectable profiles (e.g. `config/profiles/{conservative,balanced,aggressive}.yaml`) that overlay
    delta/DTE/IV bands and score floors onto the base `risk_limits.yaml` / `scoring_weights.yaml`. One
    setting (or Telegram command) selects the active profile; base files remain the source of truth.
  - Tests: overlay merge precedence; unenforced-key guard still passes; invalid profile fails loud.

**Gate after Phase 3:** ✅ tests · ✅ ruff · ✅ mypy · ✅ docs (README + ARCHITECTURE + SETUP Telegram/commands & config tables)

### Phase 4 — Position-tracking depth ✅ 2026-06-22
*More involved (storage model); not on the live-cutover critical path.*

- [x] **C6 — Campaign chaining + auto cost-basis.** ✅ 2026-06-22
  - New ORM model (e.g. `CampaignRow`) linking the leg sequence CSP → assignment → CC → roll → close under
    one campaign id, with adjusted cost basis maintained across assignment/rolls/splits.
  - Roll up "total premium collected since open" and net P&L per campaign; surface in EOD + a Telegram
    command. Reuse existing `candidate_id` links and assignment detection (`eval/assignment.py`).
  - Tests: chaining across each leg type; ACB after assignment + roll; split edge case noted.

**Gate after Phase 4:** ✅ tests · ✅ ruff · ✅ mypy · ✅ docs (ARCHITECTURE src/storage models + data-flow, STATUS)

### Phase 5 — Backtest & validation extensions ✅ 2026-06-22
*Builds on the v2 backtest harness; import-isolated from the engine/execution path.*

- [x] **C10 — Earnings-cycle backtest + vol-crush mode.** ✅ 2026-06-22
  - Extend `src/backtest/` to evaluate a strategy's behaviour across prior **earnings cycles** for a
    symbol (entry/skip per the existing blackout, premium/assignment outcomes), plus an optional
    post-earnings **vol-crush** sell mode. Reuse the yfinance earnings dates already wired in
    `analytics/fundamentals.py`.
  - Tests: earnings-cycle segmentation; vol-crush window selection; remains pure/offline.
- [x] **C11 — Backtest-on-demand for a candidate.** ✅ 2026-06-22
  - A command (and a Claude-invocable action) that runs the v2 backtest for a specific candidate's
    parameters (symbol, delta/DTE, profit-take, IV-rank gate) and returns a compact result for the
    operator/strategist at decision time. CLI entrypoint in `scripts/`.
  - Tests: candidate → params → backtest invocation; output schema.

**Gate after Phase 5:** ✅ tests · ✅ ruff · ✅ mypy · ✅ docs (ARCHITECTURE src/backtest, SETUP scripts table, STATUS)

---

# Part D — Explicitly excluded / deferred

| Feature | Why excluded |
|---|---|
| **P50 / Monte-Carlo POP** | Per-candidate Monte-Carlo compute cost for marginal gain over the existing delta-based `prob_otm`; revisit if delta-as-POP proves miscalibrated against the verdict ledger. |
| **RSI-after-runup avoidance** | Adds a tunable that can suppress genuinely high-IV opportunities; the IV/RV gate (C1) already filters poorly-priced premium, which covers most of the same intent. |
| **Payoff / P&L heatmap image in approvals** | Needs image-generation infra in the notify path; cosmetic and not decision-changing. C8 delivers the P&L calendar as text first; reconsider images later. |
| **Composite liquidity/tradeability score** | Mostly a refactor of liquidity gates that already exist separately — modest new value, deferred as hygiene. |
| **Dealer positioning (GEX / max-pain / put-call walls)** | Heavy options-OI/flow data dependency likely beyond IBKR-only data; advisory-only; high effort. Out of scope. |

---

## Quality gate (run after every change set)

```bash
python -m pytest -q     # all pass
ruff check .            # no lint
mypy src                # no type errors
```

Plus the mandatory doc-update rule in CLAUDE.md.

## Do-not-go-live until

- **C1** (IV/RV gate) and **C2** (annualized ROC) are complete and tested — they change *what gets ranked
  and traded*.
- **C3** roll execution and **C5** repricing are **verified on live paper** before either is enabled with
  real money (BAG combo limit-sign for rolls; broker fill behaviour for the chase loop).
- The existing ≥10–20-paper-cycle validation gate in SETUP.md §12 remains in force; C11/C10 backtests are
  supporting evidence, not a substitute for paper fills.
