# Phase 1 — Extended Greeks + Economic Monitor Triggers + v1 Backtest Deletion

**Source of inspiration:** `domokane/FinancePy` (full Greeks, American-option early-exercise premium).
**Pain addressed:** `src/analytics/black_scholes.py` computes only delta. The system sells
theta for a living and doesn't compute it. The monitor's `delta_drift`, `iv_spike`, and
`assignment_risk` triggers are *heuristics* (`|delta| ≥ 0.70 ∧ DTE ≤ 21`), not *economic* truths.
The v1 backtest is dead weight (STATUS.md already concedes it "validates plumbing, not the edge"
— and plumbing is already covered by the live test suite).

**Risk:** Low. All additive, all default-off, v1 deletion is dead code removal. Existing
heuristic triggers stay intact and remain the default.

**Depends on:** nothing. Can run first or in parallel with Phase 2.

---

## Files touched

### New files
- `src/analytics/american_option.py` — ~80 lines: binomial-tree American option pricer from a
  public-domain Cox-Ross-Rubenstein formulation (widely documented, unencumbered — *not*
  FinancePy). Exposes:
  - `american_price(spot, strike, dte, iv, right, r, n_steps, q) -> float | None`
  - `early_exercise_premium(...) -> float | None` = `american_price − bs_price_european`
  No Numba, no FinancePy, no GPL/AGPL code.
- `tests/test_american_option.py` — American ≥ European (no-arb invariant); early-exercise
  premium is zero for non-dividend-paying puts deep OTM; parity against a known example.

### Modified files
- `src/analytics/black_scholes.py` — add `bs_gamma`, `bs_theta`, `bs_vega`, `bs_rho`. Each is
  ~10 lines, same signature as `bs_delta` / `bs_price` (no new dependencies). Uses the same
  `d1`/`d2` already computed by the existing functions.
- `src/common/schemas.py` — extend `OptionQuote` (or a new `Greeks` submodel referenced by
  `OptionQuote`) with `gamma: float | None`, `theta: float | None`, `vega: float | None`
  (all `None` by default). Pydantic v2, additive — existing deserialization stays valid.
- `src/ibkr/option_chains.py` — populate the new Greeks wherever `_pick_greeks` /
  `_enrich_greeks_from_ibkr_iv` / `_enrich_greeks_yf` currently set `delta`:
  - IBKR's `modelGreeks` already carries gamma/theta/vega — read them via `_pick_greeks`.
  - BS fallback path: compute them from the same `d1`/`d2` already calculated for delta.
- `src/monitor/triggers.py` — add two optional triggers, **both default off**:
  - `check_economic_assignment` — fires when
    `early_exercise_premium ≤ monitor.economic_assignment.threshold_pct × spot` AND
    `ex_div_date − today ≤ monitor.economic_assignment.ex_div_window_days`. This is the
    economic condition under which covered-call early assignment actually happens.
  - `check_gamma_dollar` — fires when
    `|gamma| × spot × 100 × contracts ≥ monitor.gamma_dollar.threshold_usd`. This is what
    market-makers actually watch; "7-DTE" is its proxy.
- `src/notify/formatters.py` — surface `gamma` and `theta` on the `/scan TICKER` card and
  the approval card. Theta especially: "you're paid $X/day to hold this position." Format
  must pass `test_card_has_no_unescaped_markdownv2_parens` (use existing `_md_escape`).
- `config/risk_limits.yaml` — new `monitor.economic_assignment_*` and
  `monitor.gamma_dollar_*` keys, **all default off**:
  ```yaml
  monitor:
    economic_assignment_enabled: false
    economic_assignment:
      threshold_pct: 0.05      # fire when early-exercise premium ≤ 5% of spot
      ex_div_window_days: 5
    gamma_dollar_enabled: false
    gamma_dollar:
      threshold_usd: 500.0
  ```

### Deleted files
- `src/backtest/` v1 path — the Black-Scholes-from-HV synthesizer. Keep v2
  (`--use-stored-iv`), `on_demand.py`, `earnings.py`, `report.py` (v2-era, reused). Keep the
  `src/backtest/` package itself; only remove the v1-specific code paths and their tests.
- `tests/test_backtest.py` v1 tests — remove; keep v2 tests.

### Tests (added or modified)
- `tests/test_black_scholes.py` — parity checks (bs_price + put-call parity; gamma/vega
  closed-form sanity vs finite-difference; theta sign correctness).
- `tests/test_american_option.py` — see "New files" above.
- `tests/test_monitor_triggers.py` — economic-assignment fires only when *both* conditions
  met; gamma trigger fires independent of DTE; both default-off (no fire when flag is false).
- `tests/test_backtest.py` — remove v1 tests; keep v2.
- `tests/test_eval_skills.py` — re-run `test_fair_value_stays_in_the_deterministic_tier` and
  `test_macro_never_reaches_the_engine`; both must stay green (no enrichment-tier imports
  added to `fair_value.py` or the engine path).

---

## Doc updates (mandatory per CLAUDE.md trigger table)

- `ARCHITECTURE.md`:
  - `src/analytics/` table — extend `black_scholes.py` description (now full Greeks); add row
    for `american_option.py`.
  - `src/monitor/` table — add the two new triggers.
  - Remove all v1-backtest references.
- `STATUS.md`:
  - "What is built" — Greeks entry updated (full delta/gamma/theta/vega/rho); monitor
    triggers updated (economic assignment + gamma-dollar, default off).
  - Follow the "Removed 2026-08-10" pattern for the v1 deletion: add a "Removed" entry
    noting *why* ("validates plumbing not edge; plumbing covered by the test suite; v2
    stored-IV path already serves the real backtest use case").
- `README.md` layout table:
  - `src/analytics/` row — mention full Greeks + American pricer.
  - Remove v1 backtest mention.
- `SETUP.md`:
  - Note the new `monitor.economic_assignment_*` and `monitor.gamma_dollar_*` config keys
    (default off, operator raises them after paper validation).

---

## Verification checklist

```bash
python -m pytest -q                # all tests pass, including new ones
ruff check .                        # no lint issues
mypy src                            # no type errors
```

Then verify the cross-phase invariants:
```bash
python -m pytest tests/test_eval_skills.py::test_fair_value_stays_in_the_deterministic_tier
python -m pytest tests/test_eval_skills.py::test_macro_never_reaches_the_engine
```

Both must pass. The new Greeks and the American pricer live entirely in the deterministic
tier; the new monitor triggers are deterministic Python with no LLM involvement; the v1
backtest deletion removes code, doesn't add any path to the engine.

---

## Why this phase is first

- Greeks are *self-contained* — no dependency on any other phase.
- The American pricer unblocks Phase 3's economic signals (and is generally the right tool
  to have in an options-income system).
- The v1 backtest deletion is pure cleanup with no behaviour change — bundling it here keeps
  the diff surface small and avoids a separate micro-PR.
- Lowest risk of all five phases; the highest-leverage quick win.