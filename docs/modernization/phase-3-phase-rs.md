# Phase 3 — Phase Classification + Relative Strength

**Source of inspiration:** `RyanJHamby/stock-screener` (Minervini 8-criteria, 4-phase
classification, RS slope vs SPY, linear scoring philosophy).
**Pain addressed:** `Regime` is 5 coarse states (BULLISH/BEARISH/SIDEWAYS/HIGH_VOL/LOW_VOL).
A CSP on a name in Stage-4 downtrend is a bad trade regardless of IV richness — you'll get
assigned into a falling knife. There is no relative-strength ranking of watchlist names
against SPY. The current `buy_candidates.py` only rejects `BEARISH`; everything else scores
70-80, so a slow bleed in a Phase-3 distribution still qualifies.

**Risk:** Low — all default-off. The deterministic gate (`reject_downtrend`) ships disabled by
design; only the *scoring* changes initially, and even that at weight 0.0. No live-trade
impact until a human raises the flag after paper validation.

**Depends on:** **Phase 2** — relative strength needs SPY OHLCV via the price provider. Phase
1 is *not* required (can run before or without it).

---

## Files touched

### Modified files
- `src/analytics/technicals.py`:
  - New `classify_phase(price, sma_50, sma_200, slopes, rsi) -> Phase` returning the new
    `Phase` enum. Classification rule (Minervini/Weinstein 4-stage):
    - `UPTREND`: 50 > 150 > 200 SMA, 200 SMA rising ≥ 1 month, price > 50 SMA.
    - `DISTRIBUTION`: SMAs flattening, price below 50 SMA, RSI < 50, but 200 SMA still rising.
    - `DOWNTREND`: 50 < 200 SMA, both falling, price below both.
    - `BASE`: everything else (consolidation, not yet confirmed).
    - Compute SMA slopes as annualized % (linear regression over last 21 bars).
  - New `relative_strength(stock_close, spy_close, period=63) -> float` returning the
    annualized slope of `stock_return / spy_return`. Requires SPY OHLCV via the Phase 2 price
    provider.
- `src/common/schemas.py`:
  - New `Phase` StrEnum: `BASE` / `UPTREND` / `DISTRIBUTION` / `DOWNTREND`.
  - Extend `TechnicalStats` with `phase: Phase | None` and `relative_strength: float | None`.
  - Keep `regime` for backwards compat — derive it from phase:
    - UPTREND → BULLISH
    - DOWNTREND → BEARISH
    - BASE → SIDEWAYS
    - HIGH-ATR → HIGH_VOL
    - low-ATR → LOW_VOL
  - (The derivation runs inside `_classify_regime` so existing call sites see no change.)
- `src/strategies/cash_secured_put.py`:
  - Add optional reject: when `tech_stat.phase == Phase.DOWNTREND` and
    `risk.csp.reject_downtrend: true` (**default false** in Phase 3, flipped to true only
    after paper validation).
  - Add `REASON_PHASE_DOWNTREND` to `src/strategies/_evaluation.py`.
- `src/strategies/covered_call.py`:
  - Phase is display-only for CC (you already own the shares); no gate change. Surface phase
    on the card for context.
- `src/strategies/_scoring.py`:
  - New `relative_strength_score(rs: float | None) -> float` — linear from −0.3 → 0 to
    +0.3 → 100, clipped to [0, 100].
- `src/engine/decision_engine.py`:
  - Blend `relative_strength_score` into `technical_score` under the new
    `relative_strength` weight (default 0.0).
- `config/scoring_weights.yaml`:
  - New `relative_strength: 0.0` key inside both `covered_call` and `cash_secured_put`
    blocks (same "ships at 0.0" pattern as `zone_fit`).
  - Full comment block per the new weight.
- `config/risk_limits.yaml`:
  - `cash_secured_put.reject_downtrend: false`
- `src/notify/formatters.py`:
  - Surface phase + RS on the `/scan TICKER` card and approval card.
  - Use existing `_md_escape`; must pass
    `test_card_has_no_unescaped_markdownv2_parens`.

### Tests (new or extended)
- `tests/test_technicals_phase.py` — **new**:
  - Classify each phase with synthetic price series (UPTREND, DOWNTREND, DISTRIBUTION, BASE).
  - RS calculation correctness vs SPY (mocked SPY OHLCV).
  - RS slope boundaries (−0.3 → 0, +0.3 → 100).
  - `regime` derivation from `phase` stays backwards-compatible.
- `tests/test_csp_screen.py` — extend:
  - When `reject_downtrend: true`, a DOWNTREND-phase name is rejected with
    `REASON_PHASE_DOWNTREND` even if IV rank is high and delta fits.
  - When `reject_downtrend: false` (default), the DOWNTREND name passes as before.
- `tests/test_buy_candidates.py` — phase + RS feed into the buy score (final scoring shape is
  Phase 4's concern; here we just verify the fields are populated and non-`None` when data
  is available).
- `tests/test_eval_skills.py` — verify phase/RS additions don't breach the deterministic-tier
  constraint on `fair_value.py` (no enrichment-tier imports added).

---

## Doc updates (mandatory per CLAUDE.md trigger table)

- `ARCHITECTURE.md`:
  - `src/analytics/technicals.py` row — phase classifier, relative strength.
  - `src/strategies/` — phase-aware CSP reject (default off).
- `STATUS.md`:
  - New "What is built" entry for phase + RS.
- `README.md`:
  - CSP section note: "4-phase trend classification + relative strength vs SPY now factored
    into the technical score (weight defaults to 0.0 — raise in `scoring_weights.yaml`)."
- `config/scoring_weights.yaml`:
  - Comment block for the new `relative_strength` weight.
  - Note the default-off `reject_downtrend` flag in `risk_limits.yaml`.
- `UNIVERSE_RESEARCH.md`:
  - No ticker changes in Phase 3. (A "phase at time of writing" column is a possible
    future addition; out of scope here.)

---

## Verification checklist

```bash
python -m pytest -q
ruff check .
mypy src
python -m pytest tests/test_eval_skills.py::test_fair_value_stays_in_the_deterministic_tier
python -m pytest tests/test_eval_skills.py::test_macro_never_reaches_the_engine
```

All must pass. The phase classifier and RS calculation live in the deterministic tier; the
optional `reject_downtrend` gate is deterministic Python with no LLM; the new
`relative_strength` score weight ships at 0.0 (no ranking change until a human raises it).

---

## Why this phase is third

- Phase 3 depends on Phase 2 (price provider for SPY OHLCV). Cannot run before Phase 2.
- Phase 3 is a prerequisite for Phase 4 (the buy-recommendation overhaul uses phase + RS as
  two of its six scoring factors).
- The `reject_downtrend` gate ships *disabled* — paper-trading first, per the locked decision.
  A human raises the flag after validating on paper.

---

## Risk mitigation

- **All default-off.** `reject_downtrend: false`, `relative_strength: 0.0`. The phase and RS
  fields are computed and displayed, but neither gates nor ranks until a human raises the
  flag.
- **Backwards compat.** `regime` is derived from `phase`; existing call sites see no change.
- **Deterministic-tier preserved.** Phase and RS are computed in `technicals.py` from price
  data only — no sentiment, no sector context, no macro.