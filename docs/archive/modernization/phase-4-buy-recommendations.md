# Phase 4 — Stock Recommendation Overhaul

**Source of inspiration:** Modern multi-factor stock screeners (Piotroski F-Score, low-volatility
factor, analyst revisions), plus the Minervini/Weinstein stage analysis from Phase 3.
**Pain addressed:** The current `buy_candidates.py` is a 3-factor model (IV rank 40% + binary
quality 30% + 5-state regime 30%). Modern screeners use 5-8 factors. The system already
fetches `recommendation_key` and `target_mean_price` from yfinance but never scores on them.
The quality screen is binary (PE>0 ∧ D/E<150 ∧ FCF>0) — it doesn't distinguish AAPL from a
borderline name.

**Risk:** Low — buy-to-own is explicitly display-only (the system doesn't place these trades,
per STATUS.md). Changing its ranking is the lowest-risk change in the entire plan.

**Depends on:** **Phase 3** — phase and relative strength are two of the six scoring factors.
Phase 2 is implicitly required (Phase 3 depends on it).

---

## Files touched

### Modified files
- `src/analytics/fundamentals.py` — extend `FundamentalStats` with:
  - `piotroski_score: int | None` — **partial** (5-6 of the 9 components: profitability
    ROA / ROA-change / CFO positive; leverage D/E change / current ratio change; efficiency
    asset-turnover change / gross-margin change). Ship `None` when data is insufficient —
    matches the existing fail-soft pattern. Piotroski is a published academic methodology,
    not code from any external repo.
  - `analyst_target_upside_pct: float | None` = `(target_mean_price - current_price) /
    current_price * 100`. Computed in `get_fundamental_stats` (price already fetched).
  - `revenue_growth_yoy: float | None`, `eps_growth_yoy: float | None` — from
    `ticker.financials` / `ticker.earnings_history` via the Phase 2 fundamentals provider.
  - `beta: float | None` — from `info.get("beta")`.
- `src/common/schemas.py`:
  - Extend `FundamentalStats` with the new fields.
  - Extend `BuyCandidate` with the new sub-scores for card display:
    `piotroski_score`, `analyst_upside_pct`, `relative_strength`, `phase`.
- `src/strategies/buy_candidates.py` — **rewrite scoring** to a 6-factor linear model (no
  bucket cliffs, per the Minervini-screener's design philosophy):
  1. **Premium quality (30%)** — IV rank + IV/RV ratio + ATM open interest. Captures "is this
     a good CC platform."
  2. **Underlying quality (25%)** — Piotroski-lite (scaled 0-9 → 0-100) + dividend safety
     bonus. Captures "is this safe to own."
  3. **Entry timing (20%)** — phase score (UPTREND=100, BASE=60, DISTRIBUTION=30,
     DOWNTREND=0) + relative strength (linear: −0.3 → 0, +0.3 → 100). Captures "is now a
     good time to buy." Uses Phase 3 outputs.
  4. **Value/analyst (15%)** — `analyst_target_upside_pct` (linear: 0% upside = 0, 25%
     upside = 100, capped) + `recommendation_key` mapping (buy=100, outperform=80, hold=50,
     underperform=20, sell=0). Captures "do analysts agree this is cheap."
  5. **Growth (5%)** — revenue growth + EPS growth, linear. Small weight, breaks ties.
  6. **Low-volatility tilt (5%)** — beta (linear: beta 2.0 = 0, beta 0.5 = 100). CC income
     prefers calmer names; assignment pain is lower. *Deliberately small* because high-IV
     names are also high-premium, and we don't want to fight the premium-quality factor.
- `config/scoring_weights.yaml`:
  - Move `buy_to_own:` weights into the same shape as CC/CSP blocks (must sum to 1.0, engine
    normalizes).
  - Full comment block per factor, documenting the linear scoring ranges.
- `src/notify/formatters.py` — update `format_buy_list`:
  - Phase tag (UPTREND / BASE / DISTRIBUTION / DOWNTREND).
  - RS arrow (↑ / → / ↓).
  - Piotroski score (e.g., "P 7/9").
  - Analyst upside % (e.g., "+18% to mean").
  - New sub-score breakdown row.
  - Must pass `test_card_has_no_unescaped_markdownv2_parens`.

### Tests (new or rewritten)
- `tests/test_buy_candidates.py` — rewrite to cover 6-factor scoring:
  - Each factor's linear scaling boundaries.
  - Piotroski partial-data behavior (`None` when insufficient).
  - Analyst-target-upside scaling (0% → 0, 25% → 100, capped at 100).
  - Phase + RS integration (UPTREND + high RS → high entry-timing score; DOWNTREND → 0).
  - Backwards compat: existing `BuyCandidate` fields stay populated.
- `tests/test_fundamentals.py` — Piotroski computation against a known example (fixture with
  known financials; verify each component and the partial-score behavior).
- `tests/test_formatters.py` — new buy-list fields render; MarkdownV2 escape regression.

---

## Doc updates (mandatory per CLAUDE.md trigger table)

- `ARCHITECTURE.md`:
  - `src/analytics/fundamentals.py` row — Piotroski-lite, growth, analyst upside, beta.
  - `src/strategies/buy_candidates.py` description — 6-factor model.
- `STATUS.md`:
  - "What is built" buy-to-own section rewritten.
- `README.md`:
  - Buy-to-own card example updated (new fields shown).
- `config/scoring_weights.yaml`:
  - Full comment block for the new `buy_to_own` factors.

---

## Verification checklist

```bash
python -m pytest -q
ruff check .
mypy src
python -m pytest tests/test_eval_skills.py::test_fair_value_stays_in_the_deterministic_tier
python -m pytest tests/test_eval_skills.py::test_macro_never_reaches_the_engine
```

All must pass. Buy-to-own is display-only (the system doesn't place these trades); the
scoring change affects ranking only, not execution. The new fundamental fields are
deterministic (computed from yfinance data via the Phase 2 provider); no enrichment-tier
signal reaches `buy_candidates.py`.

---

## Why this phase is fourth

- Depends on Phase 3 (phase + RS are inputs).
- Piotroski / analyst fields are independent of Phase 2's provider refactor (they read
  `ticker.info` either way), so Phase 4 *could* technically run in parallel with Phase 2 —
  but doing it after keeps the diff surface smaller and lets the provider refactor settle
  first.
- Lowest risk of all five phases (display-only feature); a good "cooldown" phase after the
  bigger Phase 2/3 structural changes.

---

## Decisions locked in (from the planning conversation)

- **Piotroski: partial** — 5-6 of 9 components; `None` when insufficient data, matching the
  existing fail-soft philosophy. Not strict (which would leave ETFs and small caps
  perpetually neutral).
- **No GPL/AGPL code.** Piotroski F-Score is a published academic methodology, not code from
  FinancePy or any other external repo.