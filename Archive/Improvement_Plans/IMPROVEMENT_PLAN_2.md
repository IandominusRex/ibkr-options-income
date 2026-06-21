# Improvement Plan v2 — Signal-Layer Correctness & Hardening

**Created:** 2026-06-12
**Source:** Independent full-codebase review (Fable 5), conducted blind to the archived review docs,
then cross-checked against [`Archive/SYSTEM_REVIEW.md`](Archive/SYSTEM_REVIEW.md) and
[`Archive/IMPROVEMENT_PLAN.md`](Archive/IMPROVEMENT_PLAN.md).
**Baseline at review time:** 537/537 tests pass (~9 s), ruff clean, mypy clean.
**Purpose:** Single tracker for the new findings (N1–N23) and the phased work to close them.
Update the checkboxes and the per-phase gate lines as work lands.

---

## Context — relationship to the archived reviews

The 2026-06-12 archived review (F1–F8 + structural) focused on the **execution path and
operations**. All of its findings were verified as genuinely fixed in the current code
(position_manager close path, `live_premium_collapse`, scan lease, `live_greeks_required`,
periodic + external-close reconciliation, circuit breakers, nightly backup).

This review focused on what that one did not: the **trading-signal layer, approval integrity,
AI-subprocess hardening, and validation evidence**. Two of the archived plan's completion claims
are corrected here:

- **"Roll execution — DONE" is overstated.** `roll_executor.execute_roll` exists and is tested,
  but `strategies/rolling.generate_roll_candidates` has **no production caller** — nothing
  generates or queues a `Strategy.ROLL` order. Rolls remain alert-only (tracked as N20).
- **The backtest harness cannot validate the strategy.** It prices premiums with Black-Scholes
  at trailing HV (IV proxy), i.e. it sells options at fair value by construction — expected edge
  ≈ 0 by design. It validates plumbing, not the VRP/IV-rank hypothesis (tracked as N21). The
  paper-cycle gate remains the only strategy evidence.

---

## Findings register

Severity: **P0** = wrong trades / broken approval semantics · **P1** = wrong economics or material
risk before live · **P2** = robustness/efficiency · **P3** = hygiene/clarity.

### Critical — signal correctness & approval integrity

| ID | Severity | Finding | Where |
|---|---|---|---|
| **N1** | **P0** | **Regime scoring is inverted for short options.** `technical_score` rewards selling calls into BULLISH regimes and selling puts into BEARISH regimes — the alignment for *buying* options, backwards for premium selling (bullish favors CSPs; bearish/sideways favor CCs). Weight 0.20–0.25 of the blended score → systematically mis-ranks toward the riskiest regime/right combinations. | `src/strategies/_scoring.py::technical_score` |
| **N2** | **P0** | **Approved order ≠ executed order.** `candidate_id` hashes strategy\|underlying\|right\|strike\|expiry — no contracts, no date (the `models.py` docstring claiming "+date" is wrong). `_persist_candidates` delete+reinserts the payload on every re-scan; `_load_candidate` at execution reads the **latest** payload. A 15-min-loop re-scan can change `contracts` (BP or share-coverage changed) between approval and execution → the order executes a size the human never approved. Same mechanism: `record_verdicts` refreshes ledger `signals` on re-scan, so the row that eventually gets the realized outcome no longer carries the signal vector of the scan that produced the fill (training-label noise). | `src/orchestrator/scan.py::_persist_candidates` · `src/execution/approval.py::_load_candidate` · `src/claude/eval/ledger.py::record_verdicts` · `src/storage/models.py` docstring |

### AI layer

| ID | Severity | Finding | Where |
|---|---|---|---|
| **N3** | **P1** | **`claude -p` subprocess is unsandboxed.** Invoked with only `--output-format json` — no `--max-turns`, no tool restriction, no model pin. A headless agent with the user's default tool permissions runs ~26+×/day on the trading machine. The fence isolates Claude's *output* from execution; the *subprocess* itself is not constrained. | `src/claude/runner.py` (all three call sites) |
| **N9** | P2 | **Unbounded memory injection.** `_load_memory` has no LIMIT: 30 days × every scan's surfaced candidates. AUTOMATED mode writes ~hundreds of `ClaudeMemoryRow`s/day → thousands of history lines per prompt within weeks (cost, latency, context dilution, echo chamber of Claude's own prior prose). | `src/orchestrator/scan.py::_load_memory` / `_persist_memory` |
| **N12** | P2 | **In AUTOMATED mode Claude is decoration.** `_auto_queue_candidates` queues the full gate-passing slate regardless of reviews — a "skip / confidence 0.9" verdict changes nothing. Consistent with the fence, but undocumented: AUTO trades the deterministic slate, full stop. Needs an explicit decision + documentation (do **not** let Claude gate — that crosses the fence; options: higher score floor in AUTO, or keep AUTO off until the ledger proves the baseline). | `src/notify/sender.py::_auto_queue_candidates` · STATUS.md |
| **N17** | P3 | **Hardcoded universe context will rot.** `_UNIVERSE_CONTEXT` carries Jun-2026 prices/IV ranks; in months Claude reasons from wrong anchors with high confidence. | `src/claude/prompts/strategist.py` |

### Data integrity & risk-engine accuracy

| ID | Severity | Finding | Where |
|---|---|---|---|
| **N4** | **P1** | **IV history is bootstrap-only.** `iv_history` is written only by `scripts/backfill_iv.py` ("run once"). Nothing appends a daily observation, so the IV-rank window ages silently — and IV rank is simultaneously the largest score weight (0.30) and a hard gate (`min_iv_rank: 30`). | `scripts/backfill_iv.py` · `src/orchestrator/eod_report.py` (missing appender) |
| **N5** | **P1** | **Exposure seeding inconsistent.** `_seed_exposures` counts existing short puts at \|option MV\| (~1% of notional) for per-ticker/sector exposure but at strike×100 for the CSP-collateral tally. A ticker with 5 working short puts looks nearly unexposed to the 5%-per-ticker cap. | `src/engine/risk_engine.py::_seed_exposures` |
| **N6** | **P1** | **±15% strike band excludes the high-IV tier.** At IV ≈ 100% / 30 DTE, a 0.25-delta strike sits ~20–30% OTM — outside the band. SOXL/LABU/TSLL/MARA/RGTI etc. (the headline Tier-3 CC names in UNIVERSE_RESEARCH) rarely/never produce candidates. Band must scale with IV (≈1.5σ√T) or be per-symbol. | `src/ibkr/market_data.py::_filter_strikes` |
| **N10** | P2 | **Candidate premium can be a stale `last` print.** `OptionQuote.mid` falls back to `last`; scan-time ROC/yield/score can be priced off a prior-session trade when the snapshot has no two-sided market. The send-time floor limits damage but the approval the human sees may be fiction. (The order builder already refuses `last`; the strategy layer should too.) | `src/common/schemas.py::OptionQuote.mid` · strategy generators |

### Operational robustness

| ID | Severity | Finding | Where |
|---|---|---|---|
| **N7** | P2 | **Scan-lease TTL race.** A full ~60-symbol scan plausibly exceeds the 600 s TTL (sequential: 2 s spot sleep + qualify + ≥2 s per 40-contract batch + yfinance ×3 + Reddit per symbol) → lease expires mid-scan and a second scan starts (the exact line-cap poisoning the lease prevents). Also `release_scan_lease` unconditionally zeroes the key — it can release a lease another process has since claimed. | `src/storage/system_settings.py::acquire/release_scan_lease` |
| **N8** | P2 | **A REJECTED order can have a real fill.** If the executor's monitor loop throws (e.g. `cancelOrder` on a dropped socket), the except path marks the order REJECTED; if the SELL actually filled at the broker, nothing recovers it — `reconcile_orphan_fills` sweeps SUBMITTED rows only, `reconcile_external_closes` handles BUYs only. Result: live short with no FillRow → invisible to profit-take, no entry IV, mislabelled ledger. | `src/execution/executor.py` except path · `src/execution/reconciliation.py::reconcile_orphan_fills` |
| **N11** | P2 | **Chase logic reprices against the pre-placement quote.** `reprice_limit` consumes `quote.bid/ask` captured before `placeOrder`; 45–90 s later it chases a stale bid. Default OFF — must be fixed before enabling. | `src/execution/executor.py` reprice loop |
| **N14** | P3 | **Profit-take check burns a fixed 10 s sleep per short position** (sequentially, every 15-min cycle) instead of polling for the tick like `_fetch_quote` does. | `src/notify/approval_service.py::_check_profit_takes` |
| **N13** | P3 | **EOD `realized_pnl` is daily premium cashflow, not P&L** — correct internally-documented proxy, but it flows into `JournalRow.realized_pnl`, the Telegram summary, and Claude's EOD narrative under the wrong name; assignment stock-leg P&L is invisible. | `src/orchestrator/eod_report.py` · `src/notify/formatters.py` |

### Validation & strategy evidence

| ID | Severity | Finding | Where |
|---|---|---|---|
| **N22** | P1* | **Scoring model is unvalidated and weakly discriminative.** Technical spans 45–60, fundamental is a 4-step function, assignment-safety spans 65–85 inside the delta band — the blend is effectively IV-rank + liquidity. No analysis links `blended_score` to realized outcomes, though the verdict ledger stores exactly the data needed. (*P1 for live cutover, not for paper.) | `src/engine/scoring.py` · `config/scoring_weights.yaml` · ledger |
| **N21** | P2 | **Backtest cannot validate the edge** (HV-as-IV ⇒ fair-value premiums ⇒ expected edge ≈ 0 by construction; no profit-take/roll/IV-rank gating simulated). | `src/backtest/engine.py` |
| **N20** | P2 | **Roll pipeline not wired.** `generate_roll_candidates` has no production caller; `execute_roll` is unreachable except via hand-crafted DB rows. Rolls are alert-only despite "Phase 4 complete". | `src/strategies/rolling.py` · monitor → approval wiring |

### Hygiene / clarity

| ID | Severity | Finding | Where |
|---|---|---|---|
| **N15** | P3 | Unmapped `sectors:` symbols silently escape the 25% sector cap (no warning); `market_data.max_concurrent_lines` appears to be read by nothing (the unenforced-key test covers risk_limits.yaml only). | `src/engine/risk_engine.py::_sector_of` · `config/settings.yaml` |
| **N16** | P3 | `prob_profit = 1 − \|delta\|` is P(expire OTM), not P(profit) — mislabelled into prompts/Telegram. `_adx_proxy` (ATR/price) is a volatility measure labelled "trend strength". | `src/strategies/*.py` · `src/analytics/technicals.py` |
| **N18** | P3 | `min_strike_vs_basis: 1.00` disables CC generation entirely on any drawdown holding (no income, no roll-down management on exactly the names needing it). Deliberate anti-loss-lock rule — needs an explicit decision, not silent behavior. | `config/risk_limits.yaml` · `src/strategies/covered_call.py` |
| **N19** | P3 | `min_option_volume: 10` at a 9:45 scan rejects liquid chains whose day volume hasn't printed yet (OI is the stable morning gate). | `config/risk_limits.yaml` · `src/analytics/liquidity.py` |
| **N23** | P3 | `approval_service.py` (1,292 lines) still hosts the intraday loop + profit-take orchestration (trading control flow in the notify layer). | `src/notify/approval_service.py` |

---

## Phased implementation plan

Run the quality gate after every change set; update the per-phase gate line when done.

### Phase 1 — Signal & approval integrity  ✅ DONE (2026-06-13)
*The two findings that change what gets traded. Do these before any further AUTOMATED-mode runs.*

- [x] **N1** Fixed `technical_score` regime alignment for short premium: BULLISH favours
      PUT-selling (CSP, +10), BEARISH/SIDEWAYS favours CALL-selling (CC, +10); adverse regimes −5.
      A (regime × right) matrix test pins each cell
      (`tests/test_strategies.py::test_technical_score_regime_matrix`).
- [x] **N2a** Froze the approved snapshot: `ApprovalRow`/`OrderRow` gained a `snapshot` JSON
      column (lightweight migration in `db.py`). `_send_with_session` + `_auto_queue_candidates`
      freeze the payload; `_process_button` copies the approval snapshot onto the order;
      `execution/approval.py::_load_candidate` executes the OrderRow snapshot (legacy rows fall
      back to `CandidateRow`). The batched re-validation gate still runs against fresh
      quotes/positions, so drift is *rejected* by the Rules Engine rather than executed blindly.
- [x] **N2b** `record_verdicts` no longer refreshes `signals`/verdict fields once an `OrderRow`
      exists for the candidate (`_candidate_is_committed`), so the ledger row that receives the
      outcome keeps the committed scan's signal vector.
- [x] **N2c** Documented `make_candidate_id`: the id is deliberately **date-free** (idempotency
      for the 15-min loop); payload drift is handled by the N2a snapshot freeze. Confirmed no stale
      "+date" docstring remained in `models.py`.

**Gate after Phase 1:** ✅ tests pass (545) · ✅ ruff · ✅ mypy · ✅ docs updated (STATUS.md, ARCHITECTURE.md)

### Phase 2 — AI-layer hardening  ✅ DONE (2026-06-13)

- [x] **N3** `runner._build_cmd` hardens all three call sites: `--max-turns` (default 1),
      `--disallowedTools` (full denylist), optional `--model` pin — all config-driven
      (`claude.max_turns`/`disallowed_tools`/`model`). The JSON envelope is unchanged (flags don't
      affect output); tests assert the cmd carries the flags.
- [x] **N9** `_load_memory` caps at 3 rows/symbol (outcomes-first); `_persist_memory` upserts one
      `claude_memory` row per (symbol, strategy, day) instead of one per candidate per cycle.
- [x] **N12** Documented AUTO-mode semantics (STATUS.md + README): AUTO trades the deterministic
      gate-passing slate; Claude never filters/gates (the fence). Raise `weights.min_candidate_score`
      to tighten the bar — not via Claude's verdict.
- [x] **N17** Static universe block carries a STALE banner; scan injects a scan-time spot-price
      block (from the technicals) marked authoritative, threaded scan → `review_candidates` →
      `build_prompt`.

**Gate after Phase 2:** ✅ tests pass (552) · ✅ ruff · ✅ mypy · ✅ docs updated (STATUS.md, README.md, ARCHITECTURE.md, SETUP.md)

### Phase 3 — Data integrity & risk-engine accuracy  ✅ DONE (2026-06-13)

- [x] **N4** New `src/storage/iv_history.py` (latest_iv / append_observation / stale_symbols).
      The EOD run appends one IV observation per universe symbol daily (`_append_daily_iv`,
      idempotent on `(symbol, date)` via the backfill's `OPTION_IMPLIED_VOLATILITY` bar). `/health`
      gained an "IV history" line that warns when any symbol's latest row is > 5 days old/missing.
- [x] **N5** `_seed_exposures` charges existing short puts at strike×100×|contracts| toward
      per-ticker/per-sector exposure (matching new-CSP charging), not |option MV|.
- [x] **N6** `_strike_band_pct` IV-scales the band
      (`max(strike_band_pct, strike_band_iv_mult · IV · √(DTE/365))`) from the latest stored IV,
      with per-symbol `universe.yaml → strike_bands` overrides for the extreme-IV leveraged ETFs.
      *Tier-3 candidate production still needs confirmation on a live paper scan (math unit-tested).*
- [x] **N10** `OptionQuote.strict_mid` (no `last` fallback) added; CC/CSP generators price premium
      off it so a candidate is never built from a stale prior-session print.

**Gate after Phase 3:** ✅ tests pass (565) · ✅ ruff · ✅ mypy · ✅ docs updated (STATUS.md, ARCHITECTURE.md, SETUP.md)

### Phase 4 — Operational robustness  ✅ DONE (2026-06-13)

- [x] **N7** Scan lease is now `"<expiry>|<owner-token>"`: `acquire_scan_lease` returns a stable
      token, the per-symbol loop calls `renew_scan_lease(token)` (heartbeat extends the TTL), and
      `renew`/`release` are compare-and-swap on the owner so an overran+re-claimed scan can't
      clobber the new holder.
- [x] **N8** `reconcile_orphan_fills` sweeps REJECTED/CANCELLED orders carrying an `ib_order_id`
      (executor except path) in addition to SUBMITTED; pre-placement cancels (no `ib_order_id`) are
      left untouched.
- [x] **N11** The reprice loop re-fetches the live bid/ask (`_refetch_bid_ask`) before each step
      (still default OFF pending live-paper verification).
- [x] **N14** `_check_profit_takes` polls for bid/ask in 0.1 s steps with a deadline instead of a
      fixed `quote_timeout_seconds` sleep per position.
- [x] **N13** The EOD figure is labelled "premium cashflow" at the Telegram + Claude-narrative
      boundaries (with an "excludes assignment P&L" note); the `JournalRow`/`EODSummary` fields are
      retained with clarifying comments.

**Gate after Phase 4:** ✅ tests pass (569) · ✅ ruff · ✅ mypy · ✅ docs updated (STATUS.md, ARCHITECTURE.md)

### Phase 5 — Validation & strategy evidence  ✅ DONE (2026-06-13)
*Blocks live cutover: certifies that what's executed is worth executing.*

- [x] **N22** `src/claude/eval/score_metrics.py` + `scripts/evaluate_scores.py`: blended-score
      bands + per-component splits + per-signal Pearson correlation vs realized P&L/win rate over
      closed ledger rows. Read-only; `scoring_weights.yaml` is still re-derived by hand (the fence).
      *The tool exists; an actual weight change awaits enough closed paper fills.*
- [x] **N21** Backtest v2: `simulate(..., iv_series=…)` prices entries from stored `iv_history` IV
      (measures VRP via `mean_vrp_pct`); `profit_take_pct` simulates the 50% take; `min_iv_rank`
      gates by IV rank. v1 (HV proxy) unchanged when no `iv_series` is passed. Import-isolated.
- [x] **N20** Rolls wired end-to-end via `execution/roll_pipeline.py::queue_roll_for_approval`
      (monitor `fire_alerts` → chain → candidate → PENDING approval → Approve → QUEUED ROLL →
      `execute_roll`), gated by `monitor.roll_execution_enabled` (default OFF until the BAG sign is
      verified on live paper). `validate_candidates` treats ROLL as exposure-neutral.

**Gate after Phase 5:** ✅ tests pass (577) · ✅ ruff · ✅ mypy · ✅ docs updated (STATUS.md, ARCHITECTURE.md, SETUP.md)

### Phase 6 — Hygiene (any time)  ✅ DONE (2026-06-13)

- [x] **N15** Scan warns for universe symbols missing from `sectors:`; `MarketDataCfg` enforces
      `chain_batch_size ≤ max_concurrent_lines`; the unenforced-key test now covers `settings.yaml`.
- [x] **N16** `prob_profit` → `prob_otm` everywhere (prompt label clarified); `_adx_proxy` /
      `trend_strength` → `_atr_ratio` / `atr_ratio` (documented as volatility, not trend).
- [x] **N18** Drawdown-CC policy decided + documented: keep `min_strike_vs_basis: 1.00` (underwater
      holdings generate no CCs); lower the knob to permit below-basis writes.
- [x] **N19** Day-volume gate is time-aware (`volume_gate_active`); skipped before
      `liquidity.morning_volume_cutoff_et` (default 10:30 ET), OI + spread still apply.
- [x] **N23** Profit-take orchestration extracted to `execution/profit_take.py`; the daemon
      re-exports it and drives the loop, Telegram sends via the passed bot.

**Gate after Phase 6:** ✅ tests pass (581) · ✅ ruff · ✅ mypy · ✅ docs updated (STATUS.md, ARCHITECTURE.md)

---

## Quality gate (run after every change set)

```bash
python -m pytest -q     # all pass
ruff check .            # no lint
mypy src                # no type errors
```

Plus the mandatory doc-update rule in CLAUDE.md (README / ARCHITECTURE / STATUS / SETUP rows that match).

## Do-not-go-live until

- Phase 1 (N1 + N2) and Phase 3 (N4, N5) are complete — these change *what gets traded* and
  *what the limits actually bound*.
- Phase 2 N3 (subprocess sandboxing) is complete — one-line hardening, no reason to defer.
- Phase 5 N22 has produced at least a first score-vs-outcome report from paper fills, and the
  existing ≥10–20-paper-cycle gate in SETUP.md §12 is satisfied.
- AUTOMATED mode specifically: Phase 1 must be done first (N2 is most dangerous under the
  15-minute re-scan loop), and N12's semantics must be documented.
