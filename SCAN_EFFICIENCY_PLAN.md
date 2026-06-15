# Scan Efficiency Plan — the /scan pipeline & the 15-minute intraday loop

**Created:** 2026-06-15
**Source:** Focused review of the scan path (`src/orchestrator/scan.py`,
`src/ibkr/market_data.py`, `src/notify/approval_service.py::_intraday_scan_loop`,
`src/strategies/buy_candidates.py`, `src/notify/formatters.py`), conducted after the three
scan-focused commits below.
**Baseline at review time:** branch `feat/scan-progress-and-price-cache`; 581+ tests green per
[`Archive/IMPROVEMENT_PLAN_2.md`](Archive/IMPROVEMENT_PLAN_2.md).
**Purpose:** Single tracker for scan-efficiency findings (S1–S10) and the phased work to close
them. Update the checkboxes and per-phase gate lines as work lands.

---

## Context — what the recent commits already did

Three commits hardened and enriched the scan; this plan addresses what they did **not**:

- **`46a21bf` — "Fix /scan hang and slowness."** Added `symbol_timeout_seconds` (90 s) so a
  non-responding IBKR call skips the symbol instead of hanging the whole scan; added a
  spot-price fallback chain (`marketPrice` → `ticker.close` → tightly-bounded
  `reqHistoricalData`, previously a ~60 s/symbol stall on weekends); added a logging noise
  filter. **This stopped the bleeding (hangs), not the steady-state cost.**
- **`4980bda` — "Incremental OHLCV cache."** Added `src/storage/price_history.py` +
  `price_data.get_ohlcv` (`@daily_cached`): settled daily bars persist, only the live tail is
  fetched. Fundamentals and HV are already `@daily_cached`. **So the *day-static analytics* are
  now cheap — but the *option-chain fetch*, the dominant cost, is not cached or reused at all.**
- **`022c2aa` — "progress-bar dashboard + filtered, enriched buy-to-own output."** Added the
  two-message `_Tracker` (checklist + progress bar/ETA), a score floor + cap on the buy-list,
  and deterministic `format_buy_list` enrichment. **Output quality is now good; output
  *frequency* and *cost-to-produce* are not addressed.**

### The shape of the problem

The same `run_scan` body serves both the manual `/scan` command and `_intraday_scan_loop`, which
fires every `scheduler.intraday_loop_minutes = 15` during RTH — **~26 runs/session**. Every run
re-fetches the full in-band option chain for all `would_own` (46) ∪ stock-holdings symbols,
sequentially. `_STAGE_SPAN` itself assigns `market_data` the band **0.05 → 0.85 (80% of
wall-clock)**. The per-symbol cost is dominated by **fixed sleeps**:

| Cost | Per symbol | Config |
|---|---|---|
| Dedicated spot snapshot | `quote_sleep_seconds = 2.0 s` | `market_data.quote_sleep_seconds` |
| Batch quotes | `max(throttle, 2.0) = 2.0 s` **per 40-contract batch** | `chain_batch_size = 40`, `request_throttle_seconds = 0.25` |
| yfinance greeks fallback | a full Yahoo option-chain download (conditional) | — |

At ~2 s spot + ~6–10 s of batch sleeps + qualify round-trips, that is **~8–15 s/symbol ×
~50 symbols ≈ 7–12 minutes per scan, serialized** — most of the 15-minute interval. When a scan
overruns, the next cycle is silently skipped (`scan_running` guard / lease `lease_skipped`), so
the system may quietly run **far fewer than 26 scans** with no alert.

**Output is fine; the premise is the problem.** Re-fetching 46 chains every 15 minutes is
questionable when only **held positions** (for CC / profit-take / roll) and a **handful of
materially-moved `would_own` names** actually need fresh option quotes intraday.

---

## Findings register

Severity: **P1** = material cost / silent loss of intended behaviour before live · **P2** =
robustness/efficiency · **P3** = hygiene/clarity. "Verify" = depends on live-account behaviour;
confirm before/while fixing.

### Headline cost

| ID | Severity | Finding | Where |
|---|---|---|---|
| **S1** | **P1** | **The 15-min loop re-fetches the full universe chain every cycle with no materiality or change detection.** Day-static analytics are cached (`4980bda`), but the expensive part — the IBKR option-chain fetch (80% of wall-clock) — is repeated for all 46 `would_own` names every 15 min, even when spot moved < 0.5%, the name never clears the score floor / risk gate, or no position exists and none will. Most fetched chains are discarded ~26×/day. | `src/orchestrator/scan.py::_run_scan_body` (per-symbol loop) · `src/notify/approval_service.py::_intraday_scan_loop` |
| **S2** | **P1 (verify)** | **The yfinance greeks fallback is a second full chain download per symbol.** `_enrich_greeks_yf` fires whenever IBKR returns no `modelGreeks` — on a paper/delayed-data account, essentially every quote, every symbol, every scan. It downloads `ticker.options` + `option_chain(exp)` per expiry from Yahoo, duplicating the chain already pulled from IBKR (46 names × 26 scans). Likely the single biggest avoidable cost after the fixed sleeps, **if** greeks are usually absent on the target account. | `src/ibkr/market_data.py::_enrich_greeks_yf` |

### Per-symbol cost

| ID | Severity | Finding | Where |
|---|---|---|---|
| **S3** | P2 | **Dedicated 2 s spot snapshot, separate from the chain.** `_get_spot_async` issues its own `reqMktData(snapshot=True)` + fixed `quote_sleep_seconds = 2.0 s` per symbol (~100 s/scan across 50 names) — when the chain batch already opens lines and `get_ohlcv` already has a recent close. | `src/ibkr/market_data.py::_get_spot_async` |
| **S4** | P2 | **Reddit sentiment is the only analytics input not day-cached.** `SentimentScorer.score` is called per-symbol per-scan (~46 × 26 = ~1,200 praw calls/day) for a signal that does not move in 15 min and is rate-limited — while fundamentals/HV/OHLCV are `@daily_cached`. | `src/analytics/sentiment.py::SentimentScorer.score` · called in `scan.py` |
| **S7** | P2 | **Fixed sleeps instead of event-driven waits.** `ib.sleep(2)` / `asyncio.sleep(2)` per batch and the 2 s spot sleep are floors, not ceilings. ib_async is event-driven — awaiting `ticker.updateEvent` until bid/ask/greeks populate (with 2 s as a *cap*) would let well-behaved symbols return in ~0.2–0.5 s. | `src/ibkr/market_data.py::_batch_quotes_async` / `_get_spot_async` |
| **S8** | P3 | **IV-scaled strike band (N6) blows up contract count on exactly the high-IV ETFs.** `band = max(0.15, 1.5·IV·√(DTE/365))`; at IV≈0.8 / DTE≈45 → ±42% band → many strikes → more 40-contract batches → more 2 s sleeps. The slowest fetches are the leveraged ETFs scanned most defensively. Cap the band and/or qualify by a delta window rather than a symmetric % band. | `src/ibkr/market_data.py::_strike_band_pct` / `_filter_strikes` |

### LLM & output frequency

| ID | Severity | Finding | Where |
|---|---|---|---|
| **S5** | P2 | **Claude review re-runs on unchanged candidate sets.** The `claude -p` subprocess fires every 15 min even when the top list is identical to the prior cycle. N9 fixed *DB* memory bloat, not the per-scan *LLM invocation*. A content hash of the top-candidate signal vectors → skip the review and reuse the prior `ClaudeReview` when unchanged. | `src/orchestrator/scan.py` (step 8) · `src/claude/runner.py` |
| **S6** | P2 | **No temporal output suppression → notification fatigue.** `022c2aa` filtered *within* a scan (score floor, caps) but there is no "we already surfaced NVDA CC at the same strike/score 15 min ago — suppress." 26 near-identical buy-list / CSP blasts per day erode signal value. | `src/notify/sender.py::send_candidates` / `send_buy_list` |

### Observability / hygiene

| ID | Severity | Finding | Where |
|---|---|---|---|
| **S9** | P2 | **Scan overrun is silent.** When a scan exceeds 15 min, the next cycle is dropped (`scan_running` / lease `lease_skipped`) with only a `logger.info` — no Telegram alert, no metric. The operator cannot tell intended (~26) from actual scan count. | `src/notify/approval_service.py::_intraday_scan_loop` · `src/orchestrator/scan.py` (lease path) |
| **S10** | P3 | **Chains are fetched but never persisted.** `persist_chain_quotes` exists but has no caller in `scan.py`, so even a within-session reuse/diff (prerequisite for S1/S6) has no store to read. Minor, but it's the missing substrate for change-detection. | `src/ibkr/market_data.py::persist_chain_quotes` · `src/orchestrator/scan.py` |

---

## Phased implementation plan

Run the quality gate after every change set; update the per-phase gate line when done. Phases are
ordered safe-and-cheap first, then the big structural lever, then investigate-first items.

### Phase 1 — Cheap, safe efficiency wins  ✅
*Pure cost reduction, no change to what gets surfaced. Each is independently shippable.*

- [x] **S4** Wrapped `fetch_sentiment` (the inner fetch behind `SentimentScorer.score`) in
      `@daily_cached` keyed on `(symbol, today)` — same pattern as fundamentals. Test
      `test_daily_cache_skips_second_fetch_same_day` asserts a fresh scorer (next cycle) reuses the
      cached value and does not hit praw.
- [x] **S3** Added `_resolve_spot_async`: prefers `get_ohlcv`'s latest cached close for
      band-centering and only falls back to the dedicated `reqMktData(snapshot=True)` when no cached
      close exists. The `46a21bf` fallback chain is intact. `TestResolveSpotAsync` pins that no
      `reqMktData` snapshot is issued on the cached path.
- [x] **S7** Converted the per-batch and spot snapshot waits from fixed floors to an event-driven
      `_await_ready` poll: returns the instant bid/ask populate, bounded by the existing 2s /
      `quote_sleep_seconds` as a *ceiling*. Greeks are not blocked on (absent on paper data → would
      forfeit the speedup; BS fallback fills them). Cancel-between-batches discipline preserved.
      `TestAwaitReady` covers early-return + ceiling-bound.

**Gate after Phase 1:** ✅ tests pass (627) · ✅ ruff · ✅ mypy · ✅ docs updated (ARCHITECTURE.md
src/analytics + src/ibkr + cache notes; STATUS.md caching + new S3/S7 row)

### Phase 2 — Materiality-gated intraday scan (the big lever)  ✅
*Stop re-fetching chains that cannot change a decision. Largest single win; needs a per-symbol
last-spot store and tests. Does **not** touch the morning cron, which keeps a full sweep.*

- [x] **S10** Wired `persist_chain_quotes` into the scan (every fetched symbol's chain is persisted,
      off-thread) and added the `scan_state` table + `storage/scan_state.py`
      (`get_scan_state`/`upsert_scan_state`) holding per-symbol `last_spot`/`last_scanned_at`/
      `cleared_floor`. This is the substrate for S1/S6.
- [x] **S1** `run_scan(intraday=True)` (passed only by `_intraday_scan_loop`) gates the per-symbol
      chain fetch via `_compute_material_symbols`: (a) held stock positions, (b) `would_own` names
      whose live `fast_info` spot moved ≥ `intraday_rescan_move_pct` since their last *fetch*, (c)
      names that cleared the score floor last cycle. Immaterial names skip the chain fetch (analytics
      still run so the buy list stays complete). `last_spot` updates only on a fetch, so slow drift
      accrues to a re-fetch. The 09:45 cron and manual `/scan` leave `intraday=False` → full sweep.
- [x] Added config keys `market_data.intraday_rescan_move_pct` (0.005) and `force_full_scan_minutes`
      (90), plus `tests/test_scan_materiality.py`: moved→fetched, unmoved non-held→skipped,
      held→always fetched, cleared-floor→fetched, force-full timer, missing-baseline→fetched, full
      sweep ignores the gate, plus a scan_state round-trip.

**Gate after Phase 2:** ✅ tests pass (639) · ✅ ruff · ✅ mypy · ✅ docs updated (ARCHITECTURE.md
pipeline + config + storage sections, SETUP.md daemons note, STATUS.md known-behaviour)

### Phase 3 — Eliminate the yfinance greeks double-fetch  ✅
*Investigate-first: depends on what the live/paper account actually returns for `modelGreeks`.*

- [x] **S2 (instrumentation)** `_enrich_greeks_yf` now logs how many quotes forced a Yahoo fetch,
      how many expiry-chains it downloaded, and the elapsed time per symbol — so one real paper scan
      reveals how often it fires and how slow Yahoo is. It still short-circuits on `not missing`.
- [x] **S2 (avoid the double-fetch)** Greeks are now resolved IBKR-first in three tiers before Yahoo:
      (1) `_pick_greeks` takes the delta/IV from the first available per-contract IBKR computation
      (`modelGreeks` → `lastGreeks` → `askGreeks` → `bidGreeks`), so a lagging model tick still yields
      genuine IBKR greeks; (2) `_enrich_greeks_from_ibkr_iv` BS-fills delta locally from any IBKR IV
      (generic tick `106`, now requested via `genericTickList="101,106"`) — no second chain pulled;
      (3) `_enrich_greeks_yf` runs only for quotes IBKR could value neither greeks nor IV for. BS-derived
      deltas stay `greeks_source="black_scholes"` so the F6 live gate still rejects them as untrusted.
      Which tiers actually fire on the target account is flagged for **live verification** in STATUS.md.

**Gate after Phase 3:** ✅ tests pass (649) · ✅ ruff · ✅ mypy · ✅ docs updated (ARCHITECTURE.md
src/ibkr greeks-fallback note, STATUS.md fallback row + "items needing live verification")

### Phase 4 — LLM cost & output frequency  ✅
*Cut redundant Claude invocations and redundant Telegram blasts.*

- [x] **S5** `_candidates_review_hash` hashes the top candidates' `candidate_id` + `_signal_vector`
      payload; when it matches the prior cycle (stored in the `last_review_hash` system setting),
      the intraday loop skips `review_candidates` and reuses the persisted `ClaudeReviewRow`s via
      `_load_prior_reviews`. Enrichment-only — the risk gate already ran, so it never affects gating
      (the fence). Manual `/scan` and the morning cron always review fresh (`intraday=False`).
- [x] **S6** `send_candidates`/`send_buy_list` take `suppress_unchanged` (set only by the intraday
      loop). A CC/CSP candidate that still has a live, same-score-band PENDING approval is collapsed
      into one compact `format_unchanged_cards_digest` line (its original buttons stay actionable);
      an unchanged buy-to-own screen (`(symbol, score-band)` set vs. `last_buy_list_hash`) becomes a
      one-line `format_buy_list_digest` "unchanged since HH:MM". Manual `/scan` always sends in full.

**Gate after Phase 4:** ✅ tests pass (662) · ✅ ruff · ✅ mypy · ✅ docs updated (ARCHITECTURE.md
scan.py + sender.py + formatters.py, STATUS.md S5/S6 row)

### Phase 5 — Observability & band hygiene  ✅

- [x] **S9** The intraday loop now counts every lost cycle: `_note_intraday_skip` increments a
      per-session `intraday_scans_skipped` counter on the `scan_running` overrun path and the
      `lease_skipped` path, sends a throttled (≤ once / 30 min, `_OVERRUN_WARN_INTERVAL`) Telegram
      warning, and successful cycles bump `intraday_scans_run`. Both are surfaced in `/status` via
      `format_status(scans_run, scans_skipped)` so intended (~26) vs actual is visible.
- [x] **S8** `_strike_band_pct` clamps the IV-scaled band to `[strike_band_pct,
      strike_band_max_pct]` (new config key, default 0.40), so high-IV ETFs can't explode the
      qualified-strike/batch count. The N6 floor holds; an explicit per-symbol override is exempt
      from the cap. A `MarketDataCfg` validator rejects a cap below the floor.

**Gate after Phase 5:** ✅ tests pass (669) · ✅ ruff · ✅ mypy · ✅ docs updated (ARCHITECTURE.md
`/status` commands table + config + formatters + approval_service notes, SETUP.md daemons note,
STATUS.md S8/S9 row)

---

## Quality gate (run after every change set)

```bash
python -m pytest -q     # all pass
ruff check .            # no lint
mypy src                # no type errors
```

Plus the mandatory doc-update rule in CLAUDE.md (README / ARCHITECTURE / STATUS / SETUP rows that
match — new config keys → ARCHITECTURE config section + SETUP; behaviour changes → STATUS).

## Guardrails — do not regress these while optimizing

- **The fence holds.** S5 (review-skip) and any caching must remain enrichment-only; nothing here
  may feed a gate, weight, or contract count (`tests/test_eval_skills.py::test_skills_never_reach_the_engine`).
- **The line cap holds.** The ~100 market-data-line budget and the scan lease (N7) exist to
  serialize concurrent scans; S1's selective fetch must still cancel between batches and renew the
  lease per iteration.
- **The morning cron stays a full sweep.** Materiality gating (S1/S6) applies to the intraday loop
  only; the 09:45 scan and manual `/scan` always cover the full universe and always send in full.
- **Re-validation at execution is untouched.** None of these changes alter the send-time risk
  re-gate against a fresh quote (the core invariant).

## Suggested first cuts (highest ROI / lowest risk)

1. **S4** — one-line `@daily_cached`, trivially safe, immediate ~1,200 calls/day saved.
2. **S2 investigation** — measure before building; may be the biggest single win.
3. **S1** — the structural lever; biggest wall-clock reduction, but needs the S10 store + tests.
