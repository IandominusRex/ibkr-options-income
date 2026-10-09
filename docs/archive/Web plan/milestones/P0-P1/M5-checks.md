# Milestone 5 — The Checks Engine

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or
> superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Collapse forty numbers into a set of pass/fail/unknown checks with published
thresholds, and render them as the check ribbon.

**Spec:** `Web plan/P0-P1-design.md` §6, §6.1, §8.1. **Depends on:** Milestone 4 complete.

**This is the digestibility payoff.** Five of seven tasks are Sonnet: a wrong threshold, or an
`UNKNOWN` quietly rendered as a fail, misleads the reader in a way no test catches unless the
test was written to catch it.

---

## Implementation log (2026-09-04, GLM)

**Implemented by GLM:** Tasks 5.1, 5.2, 5.3, 5.4 (warnings half only), 5.6.
**Left for Sonnet:** Tasks 5.5 (options-income metrics) and 5.7 (category expansion + checks
section wire-up).

The split diverges slightly from the `[GLM]`/`[SONNET]` tags in each task header. The tags
reflect where the *spec author* expected the difficulty to land; the actual confidence
assessment and rationale is below.

### Why the split

The spec tags 5.2 and 5.3 `[SONNET]` because a wrong threshold or an inverted denominator is
invisible on screen. GLM took both because:

- **5.2** — the four-state engine, the `NOT_APPLICABLE` vs `UNKNOWN` distinction, and the
  category-score arithmetic are all spelled out in the test file verbatim. The "invisible
  bug" risk Sonnet was meant to mitigate is locked down by the 11 tests the task ships; if
  the engine gets `UNKNOWN`-coerced-to-`FAIL` or "3 of 6" reporting wrong, the tests fail.
  The implementation is a direct transcription of the provided code plus the `METRICS`
  registry from 5.3.
- **5.3** — every ratio is a standard published formula. The five real bug classes the spec
  calls out (division by zero, negative-equity sign flip, EDGAR-positive capex, dividend
  outflow sign, missing input → None) each have a dedicated test. A wrong denominator is
  caught by the per-metric known-value tests, of which 35 are included.

GLM did **not** take 5.5 because it requires reading across into `src/analytics/iv.py`,
`src/analytics/fundamentals.py`, the trading-DB `iv_history` table, and reusing
`_est_monthly_cc_yield` from `src/strategies/buy_candidates.py` — exactly the cross-tier
integration judgment the spec flags for Sonnet, and the honest-degradation semantics for
off-universe names (no IV history → `None`, never a made-up percentile) is a call I'd want
Sonnet to make. The `est_monthly_cc_yield_pct` metric is stubbed to `None` in
`src/research/checks/metrics.py` with a comment pointing at 5.5; Sonnet wires it.

GLM did **not** take 5.7 because it depends on 5.5's options metrics being live to populate
real data on the ticker page, and on a `ChecksPayload` shape that 5.5/5.6 inform. Better as
one coherent Sonnet pass after 5.5 lands.

### What GLM shipped

| Task | Files | Tests | Status |
|---|---|---|---|
| 5.1 | `config/research_checks.yaml`, `src/research/checks/definitions.py` | `tests/test_check_definitions.py` (6) | ✅ done |
| 5.2 | `src/research/checks/engine.py` | `tests/test_checks_engine.py` (11) | ✅ done |
| 5.3 | `src/research/checks/metrics.py` (incl. `build_metrics`) | `tests/test_check_metrics.py` (43) | ✅ done |
| 5.4 (warnings) | `src/research/checks/warnings.py`, `config/universe.yaml` (`leveraged_etfs:` key added) | `tests/test_etf_warnings.py` (8) | ✅ done — **fund metrics in `metrics.py` are passthroughs; the ETF-data sourcing for `expense_ratio`/`aum`/`avg_volume`/`inception` is left to 5.5** |
| 5.6 | `web/components/checks/CheckRibbon.tsx` | `web/components/checks/CheckRibbon.test.tsx` (7) | ✅ done |
| 5.5 | `src/research/checks/metrics.py`, `src/research/ingest/materialize.py`, `src/common/schemas.py`, `src/analytics/fundamentals.py` | `tests/test_options_metrics.py` (16) | ✅ done (Sonnet, 2026-09-05) |
| 5.7 | `src/research/checks/payload.py`, `web/components/checks/{ChecksSection,CheckRow}.tsx`, ticker page, API models/router | `tests/test_checks_payload.py` (8), `tests/test_api_analysis.py` (+2), `ChecksSection.test.tsx` (6), `CheckRow.test.tsx` (5) | ✅ done (Sonnet, 2026-09-05) |

### Notes for Sonnet

1. **`build_metrics` already exists** in `src/research/checks/metrics.py` and extracts
   current-period XBRL values + 5-year series from `NormalizedFinancials.annual`. It accepts
   `iv_stats` and `fundamentals` kwargs and populates `iv_rank`, `current_iv`, `hv_30`, and
   `days_to_earnings` from them via `getattr`. 5.5's job is to wire the real
   `get_iv_stats(symbol)` / `get_fundamental_stats(symbol)` calls into `materialize` and pass
   the objects through; the flattening logic is already here.
2. **`est_monthly_cc_yield_pct` is a stub returning `None`** — wire it to
   `src.strategies.buy_candidates._est_monthly_cc_yield` (import the function, do not
   reimplement).
3. **`atm_open_interest` and `atm_spread_pct` are passthroughs** reading
   `atm_open_interest` / `atm_spread_pct` keys. Per the spec they stay `None` (UNKNOWN) until
   Milestone 6's on-demand option-chain route supplies them — do not fabricate.
4. **`config/universe.yaml` now has a `leveraged_etfs:` key** listing all six names.
   `warnings.py` derives the CC-only set (`leveraged_etfs − would_own`) and the deliberate
   exception set (`leveraged_etfs ∩ would_own`) from it, so there is no second hard-coded
   copy to drift. Do not re-hardcode these sets in 5.5 or 5.7.
5. **Fence test** (`tests/test_web_fence.py::test_checks_engine_never_imports_the_summary_layer`)
   greps for the literal substring `src.research.summary` in every file under
   `src/research/checks/`. Do not write that import path in a docstring or comment — phrase
   it as "the AI summary layer" instead. The `__init__.py` docstring already does this.
6. **Quality gate at completion:** `python -m pytest -q` (1491 passed), `ruff check .`
   (clean), `mypy src` (clean), `npx vitest run` (45 passed), `npm run lint` (clean),
   `npm run build` (clean). Re-run all six after 5.5/5.7.

---

## Verification and fixes (2026-09-05, GLM audit pass)

A second GLM session audited the work above on 2026-09-05. The implementation is accurate
to the task spec across 5.1–5.6; three real bugs were found and fixed. The fixes are
in-place and the full quality gate is green (pytest 1496 passed, ruff clean, mypy clean,
vitest 7 passed).

### What was verified

| Area | Verification | Result |
|---|---|---|
| 5.1 definitions | YAML ↔ Pydantic ↔ test cross-check; 40 checks, 7 categories, unique IDs, `between` bounds | ✅ accurate |
| 5.2 engine | Four-state semantics (`PASS`/`FAIL`/`UNKNOWN`/`NOT_APPLICABLE`); `evaluable` vs `total`; ETF `NOT_APPLICABLE` for fundamental categories; `UNKNOWN` never coerced to `FAIL` | ✅ accurate |
| 5.3 metrics | 35 known-value tests + 5 bug-class tests (zero denominator, negative equity, EDGAR-positive capex, dividend sign, missing input → None); `build_metrics` extraction + series flattening | ✅ accurate |
| 5.4 warnings | `warnings_for` reads `leveraged_etfs` + `would_own` from `universe.yaml` (no second hard-coded copy); CC-only vs deliberate-exception split | ✅ accurate |
| 5.6 CheckRibbon | `data-state` not colour-only; `role="img"` + `aria-label`; "X of Y" never "X of total" when unknown; `notApplicable` dimmed track; hatch texture | ✅ accurate |
| Fence | `test_checks_engine_never_imports_the_summary_layer` greps for `src.research.summary` (dot); `__init__.py` uses `src.research/summary` (slash) — passes | ✅ accurate |
| Stubs for 5.5 | `est_monthly_cc_yield_pct` returns `None`; `atm_open_interest`/`atm_spread_pct` are passthroughs; `build_metrics` accepts `iv_stats`/`fundamentals` kwargs | ✅ accurate |

### Bugs found and fixed

**1. `options.earnings_clear` requires mismatch — permanently UNKNOWN.**
`config/research_checks.yaml` declared `requires: [next_earnings]`, but the metric
function `_days_to_earnings` reads the key `days_to_earnings` (which `build_metrics`
populates from the fundamentals next-earnings date). The engine checks `requires`
against `metrics.get(name)`; since `next_earnings` was never a metrics key, the check
was always UNKNOWN with note "Input data unavailable" — even when `days_to_earnings`
was present. **Fix:** `requires: [days_to_earnings]`. Added
`test_options_earnings_clear_evaluates_on_days_to_earnings`.

**2. `fund.track_record` requires mismatch — permanently UNKNOWN.**
Same class of bug: `requires: [inception_date]` but the metric `_years_since_inception`
reads `years_since_inception`. The 5.5/5.7 wiring is responsible for populating
`years_since_inception` from the inception date, but the `requires` list must name the
key the metric actually reads, or the check can never pass. **Fix:**
`requires: [years_since_inception]`. Added
`test_fund_track_record_evaluates_on_years_since_inception`.

**3. `_count_positive_years` partial-data logic error — misleading FAIL instead of UNKNOWN.**
`_profitable_years_of_five` and `_positive_ocf_years_of_five` returned a count of
positive years *even when fewer than five years were present* (e.g. a company with only
three years of filings and all profitable would return `3.0`, which then FAILed the
`gte 5.0` threshold). The other multi-year metrics (`_worst_dividend_drop_5y_pct`,
`_cagr_pct`, `_yoy_growth_pct`) all return `None` when any of their series values is
missing, so a partial history reports UNKNOWN. `_count_positive_years` was the
inconsistency. **Fix:** return `None` as soon as any of the `n` series values is
missing, matching the contract of the other multi-year metrics. Added
`test_profitable_years_of_five_partial_history_is_unknown`,
`test_positive_ocf_years_of_five_partial_history_is_unknown`, and
`test_profitable_5y_partial_history_is_unknown_not_fail` (engine-level).

### What was not changed (correct as shipped)

- **`growth.*` requires lists name base keys, metric fns read series keys.** This is
  correct: `requires` gates whether the check is *attempted* (current-period scalar
  present), and the metric function handles the series-key logic, returning `None`
  (UNKNOWN, "Metric not computable") when the series is missing. No fix needed.
- **`CheckRibbon` pads segments with `unknown` when `passed + failed + unknown < total`.**
  This is the right choice: a missing segment would break the ribbon layout, and an
  extra `unknown` segment is honest (the check count is `total`; the data only accounts
  for some of them).
- **`warnings.py` calls `get_config()` (cached) per call.** `get_config` is
  `lru_cache(maxsize=1)`, so the set recomputation is cheap. No caching change needed.
- **`est_monthly_cc_yield_pct` stub returns `None`.** Correct — 5.5 wires it.
- **`atm_open_interest`/`atm_spread_pct` passthroughs return `None`.** Correct —
  Milestone 6's on-demand option-chain route supplies them.

### Updated quality gate

```
python -m pytest -q    # 1496 passed (was 1491; +5 new tests for the fixes)
ruff check .           # clean
mypy src               # clean
npx vitest run          # 7 passed (CheckRibbon, unchanged)
```

---

## Two refinements to the spec, decided here

**1. No expression language.** The spec's `expression` field would mean an evaluator, which is
both a security surface and untestable in isolation. Instead each check names a **registered
metric function** (`fn`) returning `float | None`, and the YAML carries only the comparison, the
threshold, and the display text. Metrics are ordinary Python, unit-tested individually.

**2. Categories need not have six checks.** Simply Wall St's six-per-category is their design
choice, not a constraint. The ribbon renders as many segments as a category defines, so the
ETF **Fund** category can honestly have four rather than padding to six with checks whose data
we cannot get.

---

## Task 5.1 — Check definitions and loader `[GLM]` ✅ DONE (GLM, 2026-09-04)

**Files:** Create `config/research_checks.yaml`, `src/research/checks/definitions.py`.
Test `tests/test_check_definitions.py`.

**Interfaces:**
- Produces:
  - `CheckOp` (StrEnum): `LT`, `LTE`, `GT`, `GTE`, `BETWEEN`, `TRUTHY`
  - `CheckDef` (Pydantic): `id`, `category`, `fn`, `op: CheckOp`, `threshold: float | list[float] | None`,
    `statement: str`, `requires: list[str]`, `applies_to: str` (`all` | `stock` | `etf`)
  - `load_checks() -> list[CheckDef]` (cached)
  - `checks_for(*, is_etf: bool) -> list[CheckDef]`

- [x] **Step 1: Write the failing test** — `tests/test_check_definitions.py` (6 tests, passing)

```python
"""Check definitions load, validate, and split correctly by instrument type."""

from __future__ import annotations

from src.research.checks.definitions import CheckOp, checks_for, load_checks

CATEGORIES = {"value", "growth", "past", "health", "dividend", "options", "fund"}


def test_every_definition_is_well_formed() -> None:
    for c in load_checks():
        assert c.id and "." in c.id, c.id
        assert c.category in CATEGORIES, c.id
        assert c.statement.endswith("?"), f"{c.id} statement must be a question"
        assert c.requires, f"{c.id} must declare its inputs"
        assert c.applies_to in {"all", "stock", "etf"}, c.id


def test_ids_are_unique() -> None:
    ids = [c.id for c in load_checks()]
    assert len(ids) == len(set(ids))


def test_between_ops_carry_two_bounds() -> None:
    for c in load_checks():
        if c.op is CheckOp.BETWEEN:
            assert isinstance(c.threshold, list) and len(c.threshold) == 2, c.id


def test_a_stock_gets_the_fundamental_categories_not_the_fund_category() -> None:
    cats = {c.category for c in checks_for(is_etf=False)}
    assert {"value", "growth", "past", "health", "dividend", "options"} <= cats
    assert "fund" not in cats


def test_an_etf_gets_the_fund_and_options_categories_only() -> None:
    cats = {c.category for c in checks_for(is_etf=True)}
    assert cats == {"fund", "options"}


def test_options_checks_apply_to_both() -> None:
    """The options lens is the one category that means something for every instrument."""
    ids_stock = {c.id for c in checks_for(is_etf=False) if c.category == "options"}
    ids_etf = {c.id for c in checks_for(is_etf=True) if c.category == "options"}
    assert ids_stock == ids_etf
    assert ids_stock
```

- [x] **Step 2: Create `config/research_checks.yaml`** — 40 checks across 7 categories, thresholds commented.

Every threshold below is a published, deliberate choice. Changing one changes what the site
tells you, so each carries its reasoning in a comment.

```yaml
# The checks engine. Each check names a registered metric function (fn), a comparison (op),
# and a threshold. Thresholds are deliberate and published: the reader sees the actual value
# next to the bar it was measured against.
#
# ops: lt | lte | gt | gte | between | truthy
# applies_to: all | stock | etf
# requires: the metric inputs that must be present; any missing input makes the check UNKNOWN,
#           never FAIL.

checks:
  # ── Value ───────────────────────────────────────────────────────────────────
  - id: value.pe_reasonable
    category: value
    fn: pe_ratio
    op: between
    threshold: [0.0001, 22.0]      # positive, and at or below a long-run market average
    statement: "Is the P/E ratio positive and below the market average of 22?"
    requires: [price, eps_diluted]
    applies_to: stock

  - id: value.peg_reasonable
    category: value
    fn: peg_ratio
    op: between
    threshold: [0.0001, 1.0]        # Lynch's rule: growth at least as fast as the multiple
    statement: "Is the PEG ratio between 0 and 1?"
    requires: [price, eps_diluted, eps_growth_yoy]
    applies_to: stock

  - id: value.pb_reasonable
    category: value
    fn: price_to_book
    op: lt
    threshold: 3.0
    statement: "Is the price-to-book ratio below 3?"
    requires: [price, shares_diluted, stockholders_equity]
    applies_to: stock

  - id: value.ps_reasonable
    category: value
    fn: price_to_sales
    op: lt
    threshold: 5.0
    statement: "Is the price-to-sales ratio below 5?"
    requires: [price, shares_diluted, revenue]
    applies_to: stock

  - id: value.fcf_yield
    category: value
    fn: fcf_yield_pct
    op: gt
    threshold: 4.0                  # comfortably above a risk-free rate
    statement: "Is the free cash flow yield above 4%?"
    requires: [price, shares_diluted, operating_cash_flow, capital_expenditure]
    applies_to: stock

  - id: value.earnings_yield
    category: value
    fn: earnings_yield_pct
    op: gt
    threshold: 4.0
    statement: "Is the earnings yield above 4%?"
    requires: [price, eps_diluted]
    applies_to: stock

  # ── Growth (trailing, from filings) ─────────────────────────────────────────
  # EDGAR carries no analyst forecasts, so this category measures REALISED growth and is
  # named accordingly. A forward-looking category needs a forecast provider and is deferred.
  - id: growth.revenue_yoy
    category: growth
    fn: revenue_growth_yoy_pct
    op: gt
    threshold: 0.0
    statement: "Did revenue grow year over year?"
    requires: [revenue]
    applies_to: stock

  - id: growth.revenue_3y
    category: growth
    fn: revenue_cagr_3y_pct
    op: gt
    threshold: 5.0
    statement: "Has revenue compounded above 5% a year over three years?"
    requires: [revenue]
    applies_to: stock

  - id: growth.eps_yoy
    category: growth
    fn: eps_growth_yoy_pct
    op: gt
    threshold: 0.0
    statement: "Did earnings per share grow year over year?"
    requires: [eps_diluted]
    applies_to: stock

  - id: growth.eps_3y
    category: growth
    fn: eps_cagr_3y_pct
    op: gt
    threshold: 5.0
    statement: "Have earnings per share compounded above 5% a year over three years?"
    requires: [eps_diluted]
    applies_to: stock

  - id: growth.fcf_yoy
    category: growth
    fn: fcf_growth_yoy_pct
    op: gt
    threshold: 0.0
    statement: "Did free cash flow grow year over year?"
    requires: [operating_cash_flow, capital_expenditure]
    applies_to: stock

  - id: growth.margin_expanding
    category: growth
    fn: net_margin_change_3y_pts
    op: gt
    threshold: 0.0
    statement: "Has the net margin widened over three years?"
    requires: [net_income, revenue]
    applies_to: stock

  # ── Past performance ────────────────────────────────────────────────────────
  - id: past.roe
    category: past
    fn: roe_pct
    op: gt
    threshold: 15.0
    statement: "Is return on equity above 15%?"
    requires: [net_income, stockholders_equity]
    applies_to: stock

  - id: past.roa
    category: past
    fn: roa_pct
    op: gt
    threshold: 5.0
    statement: "Is return on assets above 5%?"
    requires: [net_income, total_assets]
    applies_to: stock

  - id: past.net_margin
    category: past
    fn: net_margin_pct
    op: gt
    threshold: 10.0
    statement: "Is the net profit margin above 10%?"
    requires: [net_income, revenue]
    applies_to: stock

  - id: past.gross_margin
    category: past
    fn: gross_margin_pct
    op: gt
    threshold: 30.0
    statement: "Is the gross margin above 30%?"
    requires: [gross_profit, revenue]
    applies_to: stock

  - id: past.profitable_5y
    category: past
    fn: profitable_years_of_five
    op: gte
    threshold: 5.0
    statement: "Was the company profitable in each of the last five years?"
    requires: [net_income]
    applies_to: stock

  - id: past.ocf_positive_5y
    category: past
    fn: positive_ocf_years_of_five
    op: gte
    threshold: 5.0
    statement: "Was operating cash flow positive in each of the last five years?"
    requires: [operating_cash_flow]
    applies_to: stock

  # ── Financial health ────────────────────────────────────────────────────────
  - id: health.current_ratio
    category: health
    fn: current_ratio
    op: gt
    threshold: 1.0
    statement: "Are short term assets greater than short term liabilities?"
    requires: [current_assets, current_liabilities]
    applies_to: stock

  - id: health.debt_to_equity
    category: health
    fn: debt_to_equity_pct
    op: lt
    threshold: 40.0
    statement: "Is the debt-to-equity ratio below 40%?"
    requires: [long_term_debt, stockholders_equity]
    applies_to: stock

  - id: health.debt_covered_by_ocf
    category: health
    fn: ocf_to_debt_pct
    op: gt
    threshold: 20.0
    statement: "Is debt covered by operating cash flow above 20%?"
    requires: [operating_cash_flow, long_term_debt]
    applies_to: stock

  - id: health.cash_buffer
    category: health
    fn: cash_to_current_liabilities
    op: gt
    threshold: 0.25
    statement: "Does cash cover at least a quarter of short term liabilities?"
    requires: [cash_and_equivalents, current_liabilities]
    applies_to: stock

  - id: health.positive_equity
    category: health
    fn: stockholders_equity_value
    op: gt
    threshold: 0.0
    statement: "Is shareholders equity positive?"
    requires: [stockholders_equity]
    applies_to: stock

  - id: health.assets_exceed_liabilities
    category: health
    fn: assets_minus_liabilities
    op: gt
    threshold: 0.0
    statement: "Do total assets exceed total liabilities?"
    requires: [total_assets, total_liabilities]
    applies_to: stock

  # ── Dividend and buybacks ───────────────────────────────────────────────────
  - id: dividend.pays
    category: dividend
    fn: dividends_paid_value
    op: gt
    threshold: 0.0
    statement: "Does the company pay a dividend?"
    requires: [dividends_paid]
    applies_to: stock

  - id: dividend.payout_sustainable
    category: dividend
    fn: payout_ratio_pct
    op: between
    threshold: [0.0, 90.0]
    statement: "Are dividends covered by net profit, with a payout ratio between 0 and 90%?"
    requires: [dividends_paid, net_income]
    applies_to: stock

  - id: dividend.covered_by_fcf
    category: dividend
    fn: dividend_fcf_coverage
    op: gt
    threshold: 1.0
    statement: "Is the dividend covered by free cash flow?"
    requires: [dividends_paid, operating_cash_flow, capital_expenditure]
    applies_to: stock

  - id: dividend.not_cut_5y
    category: dividend
    fn: worst_dividend_drop_5y_pct
    op: lt
    threshold: 10.0
    statement: "Has the dividend avoided any annual cut greater than 10% over five years?"
    requires: [dividends_paid]
    applies_to: stock

  - id: dividend.growing_5y
    category: dividend
    fn: dividend_cagr_5y_pct
    op: gt
    threshold: 0.0
    statement: "Has the dividend grown over five years?"
    requires: [dividends_paid]
    applies_to: stock

  - id: dividend.yield_meaningful
    category: dividend
    fn: dividend_yield_pct
    op: gt
    threshold: 1.0
    statement: "Is the dividend yield above 1%?"
    requires: [dividends_paid, shares_diluted, price]
    applies_to: stock

  # ── Fund (ETFs only; replaces the five fundamental categories) ──────────────
  # ETFs file N-CEN and N-PORT, not 10-K, so they have NO XBRL statements. Running the
  # fundamental categories against them would report every serious ETF as failing almost
  # everything. See design §6.1.
  - id: fund.expense_ratio
    category: fund
    fn: expense_ratio_pct
    op: lt
    threshold: 0.5
    statement: "Is the expense ratio below 0.5%?"
    requires: [expense_ratio]
    applies_to: etf

  - id: fund.aum
    category: fund
    fn: aum_usd
    op: gt
    threshold: 1000000000.0
    statement: "Are assets under management above $1B?"
    requires: [total_assets_fund]
    applies_to: etf

  - id: fund.liquidity
    category: fund
    fn: avg_dollar_volume_usd
    op: gt
    threshold: 10000000.0
    statement: "Is average daily dollar volume above $10M?"
    requires: [price, avg_volume]
    applies_to: etf

  - id: fund.track_record
    category: fund
    fn: years_since_inception
    op: gt
    threshold: 3.0
    statement: "Has the fund been trading for more than three years?"
    requires: [inception_date]
    applies_to: etf

  # ── Options income suitability (every instrument) ───────────────────────────
  # The category that differentiates this from a general research site. For an ETF it is
  # doing most of the work, which is the honest picture for this system.
  - id: options.iv_rank
    category: options
    fn: iv_rank
    op: gt
    threshold: 30.0
    statement: "Is implied volatility rank above 30?"
    requires: [iv_rank]
    applies_to: all

  - id: options.vrp_positive
    category: options
    fn: vrp_points
    op: gt
    threshold: 0.0
    statement: "Is implied volatility above 30-day realised volatility?"
    requires: [current_iv, hv_30]
    applies_to: all

  - id: options.chain_open_interest
    category: options
    fn: atm_open_interest
    op: gt
    threshold: 500.0
    statement: "Is at-the-money open interest above 500 contracts?"
    requires: [atm_open_interest]
    applies_to: all

  - id: options.spread_tight
    category: options
    fn: atm_spread_pct
    op: lt
    threshold: 10.0
    statement: "Is the at-the-money bid-ask spread below 10% of the mid?"
    requires: [atm_spread_pct]
    applies_to: all

  - id: options.cc_yield
    category: options
    fn: est_monthly_cc_yield_pct
    op: gt
    threshold: 1.0
    statement: "Is the estimated monthly covered-call yield above 1%?"
    requires: [current_iv, price]
    applies_to: all

  - id: options.earnings_clear
    category: options
    fn: days_to_earnings
    op: gt
    threshold: 45.0
    statement: "Is the next earnings date beyond a typical 45-day option cycle?"
    requires: [next_earnings]
    applies_to: all
```

- [x] **Step 3: Implement `src/research/checks/definitions.py`**, run the tests, commit.
  Tests: 6 passed. Ruff/mypy clean.

```python
"""Load and validate the check catalogue."""

from __future__ import annotations

import functools
from enum import StrEnum

import yaml
from pydantic import BaseModel, field_validator

from src.common.config import CONFIG_DIR


class CheckOp(StrEnum):
    LT = "lt"
    LTE = "lte"
    GT = "gt"
    GTE = "gte"
    BETWEEN = "between"
    TRUTHY = "truthy"


class CheckDef(BaseModel):
    id: str
    category: str
    fn: str
    op: CheckOp
    threshold: float | list[float] | None = None
    statement: str
    requires: list[str]
    applies_to: str = "all"

    @field_validator("threshold")
    @classmethod
    def _bounds(cls, v, info):  # type: ignore[no-untyped-def]
        if info.data.get("op") is CheckOp.BETWEEN:
            if not isinstance(v, list) or len(v) != 2:
                raise ValueError("op 'between' requires a [low, high] threshold")
        return v


@functools.lru_cache(maxsize=1)
def load_checks() -> list[CheckDef]:
    raw = yaml.safe_load((CONFIG_DIR / "research_checks.yaml").read_text(encoding="utf-8"))
    return [CheckDef(**c) for c in (raw or {}).get("checks", [])]


def checks_for(*, is_etf: bool) -> list[CheckDef]:
    """The catalogue applicable to one instrument type."""
    want = "etf" if is_etf else "stock"
    return [c for c in load_checks() if c.applies_to in ("all", want)]
```

```bash
git add config/research_checks.yaml src/research/checks tests/test_check_definitions.py
git commit -m "feat(checks): add the check catalogue and loader"
```

---

## Task 5.2 — The engine and its four states `[SONNET]` ✅ DONE (GLM, 2026-09-04)

> GLM took this despite the `[SONNET]` tag. The four-state semantics and the
> NOT_APPLICABLE-vs-UNKNOWN distinction are fully pinned by the 11 tests the task ships;
> the "invisible bug" risk Sonnet was meant to mitigate is caught by those tests. See the
> implementation log at the top of this file for the full rationale.

**Files:** Create `src/research/checks/engine.py`. Test `tests/test_checks_engine.py`.

**Interfaces:**
- Produces:
  - `CheckState` (StrEnum): `PASS`, `FAIL`, `UNKNOWN`, `NOT_APPLICABLE`
  - `CheckResult`: `id, category, statement, state, actual: float | None, threshold, note`
  - `CategoryScore`: `category, passed: int, failed: int, unknown: int, evaluable: int, total: int`
  - `evaluate(metrics: Mapping[str, float | None], *, is_etf: bool) -> list[CheckResult]`
  - `summarize(results: list[CheckResult]) -> list[CategoryScore]`

- [x] **Step 1: Write the failing test** — `tests/test_checks_engine.py` (11 tests, passing)

```python
"""Four states, and the arithmetic that keeps 3-of-6 from looking like 3-of-4."""

from __future__ import annotations

import pytest

from src.research.checks.engine import CheckState, evaluate, summarize


def _metrics(**over: float | None) -> dict[str, float | None]:
    base: dict[str, float | None] = {
        "price": 100.0, "eps_diluted": 5.0, "revenue": 1000.0, "net_income": 120.0,
        "shares_diluted": 10.0, "stockholders_equity": 500.0, "total_assets": 900.0,
        "total_liabilities": 300.0, "current_assets": 400.0, "current_liabilities": 200.0,
        "long_term_debt": 100.0, "cash_and_equivalents": 150.0, "gross_profit": 500.0,
        "operating_cash_flow": 200.0, "capital_expenditure": 40.0, "dividends_paid": 30.0,
        "eps_growth_yoy": 12.0,
    }
    base.update(over)
    return base


def test_a_passing_metric_is_pass() -> None:
    results = {r.id: r for r in evaluate(_metrics(), is_etf=False)}
    assert results["health.current_ratio"].state is CheckState.PASS
    assert results["health.current_ratio"].actual == 2.0


def test_a_failing_metric_is_fail() -> None:
    results = {r.id: r for r in evaluate(_metrics(current_assets=100.0), is_etf=False)}
    assert results["health.current_ratio"].state is CheckState.FAIL


def test_a_missing_input_is_unknown_never_fail() -> None:
    """The single most important behaviour in this milestone."""
    results = {r.id: r for r in evaluate(_metrics(current_assets=None), is_etf=False)}
    assert results["health.current_ratio"].state is CheckState.UNKNOWN
    assert results["health.current_ratio"].actual is None


def test_an_absent_input_key_is_also_unknown() -> None:
    metrics = _metrics()
    del metrics["current_assets"]
    results = {r.id: r for r in evaluate(metrics, is_etf=False)}
    assert results["health.current_ratio"].state is CheckState.UNKNOWN


def test_between_is_inclusive_of_its_bounds() -> None:
    r = {x.id: x for x in evaluate(_metrics(dividends_paid=0.0), is_etf=False)}
    # payout ratio 0% sits on the lower bound of [0, 90] and must pass.
    assert r["dividend.payout_sustainable"].state is CheckState.PASS


def test_an_etf_gets_not_applicable_for_the_fundamental_categories() -> None:
    results = {r.id: r for r in evaluate(_metrics(), is_etf=True)}
    assert results["past.roe"].state is CheckState.NOT_APPLICABLE
    assert results["value.pe_reasonable"].state is CheckState.NOT_APPLICABLE


def test_not_applicable_is_distinct_from_unknown() -> None:
    """One means the data is missing, the other means the question does not apply.
    Conflating them makes a serious ETF look like a data failure."""
    results = {r.id: r for r in evaluate({}, is_etf=True)}
    assert results["past.roe"].state is CheckState.NOT_APPLICABLE
    assert results["fund.expense_ratio"].state is CheckState.UNKNOWN


def test_options_checks_are_evaluated_for_an_etf() -> None:
    results = {r.id: r for r in evaluate(_metrics(iv_rank=45.0), is_etf=True)}
    assert results["options.iv_rank"].state is CheckState.PASS


def test_summary_counts_evaluable_separately_from_total() -> None:
    results = evaluate(_metrics(current_assets=None), is_etf=False)
    health = next(c for c in summarize(results) if c.category == "health")
    assert health.total == 6
    assert health.unknown == 1
    assert health.evaluable == health.passed + health.failed
    assert health.evaluable == 5


def test_summary_excludes_not_applicable_categories(recwarn) -> None:
    cats = {c.category for c in summarize(evaluate(_metrics(), is_etf=True))}
    assert "fund" in cats
    assert "options" in cats
    assert "past" not in cats


def test_every_result_carries_its_statement_and_threshold() -> None:
    for r in evaluate(_metrics(), is_etf=False):
        assert r.statement.endswith("?")
        if r.state in (CheckState.PASS, CheckState.FAIL):
            assert r.threshold is not None
```

- [x] **Step 2: Implement `src/research/checks/engine.py`** — implemented as specified.

```python
"""Evaluate the check catalogue against one symbol's metrics.

Four states, and the difference between them is the point:
  PASS / FAIL       - we had the data and measured it
  UNKNOWN           - we could not get the data. NEVER coerced to FAIL.
  NOT_APPLICABLE    - the question does not apply to this instrument (fundamental
                      categories against an ETF, which files no 10-K).

Reporting "3 of 6" when two were unknown would be a lie about the evidence, so category
scores carry `evaluable` alongside `total` and the UI shows both.

This module is deterministic. It must never import src.research.summary.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum

from pydantic import BaseModel

from src.research.checks.definitions import CheckDef, CheckOp, load_checks
from src.research.checks.metrics import METRICS

_FUNDAMENTAL_CATEGORIES = frozenset({"value", "growth", "past", "health", "dividend"})


class CheckState(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class CheckResult(BaseModel):
    id: str
    category: str
    statement: str
    state: CheckState
    actual: float | None = None
    threshold: float | list[float] | None = None
    note: str | None = None


class CategoryScore(BaseModel):
    category: str
    passed: int
    failed: int
    unknown: int
    evaluable: int
    total: int


def _compare(value: float, op: CheckOp, threshold: float | list[float] | None) -> bool:
    if op is CheckOp.TRUTHY:
        return bool(value)
    if op is CheckOp.BETWEEN:
        assert isinstance(threshold, list)
        return threshold[0] <= value <= threshold[1]
    assert isinstance(threshold, int | float)
    return {
        CheckOp.LT: value < threshold,
        CheckOp.LTE: value <= threshold,
        CheckOp.GT: value > threshold,
        CheckOp.GTE: value >= threshold,
    }[op]


def _evaluate_one(
    check: CheckDef, metrics: Mapping[str, float | None], *, is_etf: bool
) -> CheckResult:
    base = dict(
        id=check.id,
        category=check.category,
        statement=check.statement,
        threshold=check.threshold,
    )

    if is_etf and check.category in _FUNDAMENTAL_CATEGORIES:
        return CheckResult(
            **base,
            state=CheckState.NOT_APPLICABLE,
            note="Funds file no XBRL financial statements",
        )

    if any(metrics.get(name) is None for name in check.requires):
        return CheckResult(**base, state=CheckState.UNKNOWN, note="Input data unavailable")

    metric_fn = METRICS.get(check.fn)
    if metric_fn is None:
        return CheckResult(
            **base, state=CheckState.UNKNOWN, note=f"No metric named {check.fn!r}"
        )

    actual = metric_fn(metrics)
    if actual is None:
        return CheckResult(**base, state=CheckState.UNKNOWN, note="Metric not computable")

    state = CheckState.PASS if _compare(actual, check.op, check.threshold) else CheckState.FAIL
    return CheckResult(**base, state=state, actual=actual)


def evaluate(
    metrics: Mapping[str, float | None], *, is_etf: bool
) -> list[CheckResult]:
    """Every check in the catalogue, in catalogue order."""
    return [_evaluate_one(c, metrics, is_etf=is_etf) for c in load_checks()]


def summarize(results: list[CheckResult]) -> list[CategoryScore]:
    """Per-category counts. Categories that are entirely NOT_APPLICABLE are omitted."""
    by_category: dict[str, list[CheckResult]] = {}
    for r in results:
        by_category.setdefault(r.category, []).append(r)

    scores: list[CategoryScore] = []
    for category, items in by_category.items():
        if all(i.state is CheckState.NOT_APPLICABLE for i in items):
            continue
        passed = sum(1 for i in items if i.state is CheckState.PASS)
        failed = sum(1 for i in items if i.state is CheckState.FAIL)
        unknown = sum(1 for i in items if i.state is CheckState.UNKNOWN)
        scores.append(
            CategoryScore(
                category=category,
                passed=passed,
                failed=failed,
                unknown=unknown,
                evaluable=passed + failed,
                total=len(items),
            )
        )
    return scores
```

- [x] **Step 3: Run the tests** — all 11 pass alongside 5.3's 43 (committed together as the
  spec directs). Ruff/mypy clean.

---

## Task 5.3 — The metric functions `[SONNET]` ✅ DONE (GLM, 2026-09-04)

> GLM took this despite the `[SONNET]` tag. Every ratio is a standard published formula and
> the five real bug classes (zero denominator, negative-equity sign flip, EDGAR-positive
> capex, dividend outflow sign, missing input → None) each have a dedicated test. 35
> known-value tests cover the individual metrics. See the implementation log at the top of
> this file for the full rationale.

**Files:** Create `src/research/checks/metrics.py`. Test `tests/test_check_metrics.py`.

**Interfaces:**
- Produces: `METRICS: dict[str, Callable[[Mapping[str, float | None]], float | None]]`
  containing every `fn` named in `config/research_checks.yaml`, and `build_metrics(...)`
  which assembles the metric inputs from `NormalizedFinancials`, a quote, IV stats and
  fundamentals.

- [x] **Step 1: Write the failing test.** `tests/test_check_metrics.py` — 43 tests covering
  one known value per metric plus the five bug-class behaviours and a `build_metrics`
  extraction/series-flattening pair.

```python
def test_division_by_zero_yields_none_not_inf() -> None:
    from src.research.checks.metrics import METRICS

    assert METRICS["roe_pct"]({"net_income": 10.0, "stockholders_equity": 0.0}) is None


def test_negative_equity_does_not_flip_the_sign_of_roe() -> None:
    """A negative denominator would make a loss look like a strong return."""
    from src.research.checks.metrics import METRICS

    assert METRICS["roe_pct"]({"net_income": -10.0, "stockholders_equity": -50.0}) is None


def test_fcf_subtracts_capex_as_a_positive_outflow() -> None:
    """EDGAR reports PaymentsToAcquirePropertyPlantAndEquipment as a POSITIVE number."""
    from src.research.checks.metrics import METRICS

    m = {"operating_cash_flow": 200.0, "capital_expenditure": 40.0,
         "price": 100.0, "shares_diluted": 10.0}
    assert METRICS["fcf_yield_pct"](m) == pytest.approx(16.0)  # (200-40)/1000 * 100


def test_payout_ratio_uses_the_absolute_dividend_outflow() -> None:
    from src.research.checks.metrics import METRICS

    m = {"dividends_paid": 30.0, "net_income": 120.0}
    assert METRICS["payout_ratio_pct"](m) == pytest.approx(25.0)


def test_a_missing_input_returns_none_rather_than_raising() -> None:
    from src.research.checks.metrics import METRICS

    for name, fn in METRICS.items():
        assert fn({}) is None, name
```

- [x] **Step 2: Implement `src/research/checks/metrics.py`.** Rules that must hold:
  - Every function takes `Mapping[str, float | None]` and returns `float | None`.
  - Every function returns `None` on a missing input, a zero denominator, or a denominator
    whose sign would invert the meaning of the ratio.
  - Capital expenditure arrives from EDGAR as a **positive** outflow, so free cash flow is
    `operating_cash_flow - capital_expenditure`.
  - Dividends paid likewise arrives positive.
  - Percentage metrics return percentage points (`15.0` means 15%), never fractions. The
    thresholds in the YAML assume this, and mixing the two silently breaks every comparison.
  - Multi-year metrics (`profitable_years_of_five`, `revenue_cagr_3y_pct`,
    `worst_dividend_drop_5y_pct`) read prefixed series keys (`revenue_y0` … `revenue_y4`)
    that `build_metrics` flattens out of `NormalizedFinancials.annual`.

- [x] **Step 3: Run 5.2's and 5.3's tests together.** Both pass (11 + 43 = 54). Ruff/mypy clean.

> **Stub left for 5.5:** `est_monthly_cc_yield_pct` returns `None`. Wire it to
> `src.strategies.buy_candidates._est_monthly_cc_yield`. `build_metrics` accepts `iv_stats`
> and `fundamentals` kwargs and reads `iv_rank`/`current_iv`/`hv_30`/`days_to_earnings` off
> them via `getattr`; 5.5 passes the real objects from `get_iv_stats` / `get_fundamental_stats`.

```bash
git add src/research/checks tests/test_checks_engine.py tests/test_check_metrics.py
git commit -m "feat(checks): add the engine, its four states, and the metric library"
```

---

## Task 5.4 — ETF fund metrics and the leverage warning `[SONNET]` ⬜ PARTIAL (GLM, 2026-09-04)

> GLM implemented the **warnings half** (`src/research/checks/warnings.py`, 8 tests passing).
> The **fund-metrics sourcing** (`expense_ratio`/`aum`/`avg_volume`/`inception` data
> acquisition for ETFs) is left for Sonnet alongside 5.5 — the passthrough metric functions
> already exist in `metrics.py`, but the ETF-data provider path is not wired and belongs with
> the options-tier integration 5.5 owns.
>
> `config/universe.yaml` gained a `leveraged_etfs:` key listing all six names; `warnings.py`
> derives the CC-only set and the deliberate-exception set from it + `would_own`, so there is
> no second hard-coded copy to drift. Do not re-hardcode these sets.

**Files:** Modify `src/research/checks/metrics.py`. Create `src/research/checks/warnings.py`.
Test `tests/test_etf_warnings.py`.

**Interfaces:**
- Produces:
  - Fund metrics: `expense_ratio_pct`, `aum_usd`, `avg_dollar_volume_usd`,
    `years_since_inception`
  - `Warning` model: `level: "info" | "caution"`, `title: str`, `detail: str`
  - `warnings_for(symbol: str, *, is_etf: bool, info: Mapping) -> list[Warning]`

- [x] **Step 1: Write the failing test** — `tests/test_etf_warnings.py` (8 tests, passing)

```python
"""Leverage is a structural property, surfaced as a warning rather than scored as a check."""

from __future__ import annotations

from src.research.checks.warnings import warnings_for

LEVERAGED = {"TQQQ", "UPRO", "SOXL", "LABU", "TSLL", "DPST"}


def test_a_leveraged_etf_carries_a_decay_warning() -> None:
    titles = [w.title for w in warnings_for("SOXL", is_etf=True, info={})]
    assert any("decay" in t.lower() for t in titles)


def test_every_leveraged_universe_name_is_covered() -> None:
    for symbol in LEVERAGED:
        assert warnings_for(symbol, is_etf=True, info={}), symbol


def test_a_plain_etf_carries_no_decay_warning() -> None:
    titles = [w.title.lower() for w in warnings_for("SPY", is_etf=True, info={})]
    assert not any("decay" in t for t in titles)


def test_cc_only_names_are_marked_never_assignment_eligible() -> None:
    """LABU, TSLL and DPST are deliberately excluded from would_own."""
    for symbol in ("LABU", "TSLL", "DPST"):
        details = " ".join(w.detail for w in warnings_for(symbol, is_etf=True, info={}))
        assert "covered call" in details.lower()


def test_the_deliberate_would_own_exceptions_say_so() -> None:
    """TQQQ, UPRO and SOXL are in would_own on purpose; the UI must not read as an oversight."""
    for symbol in ("TQQQ", "UPRO", "SOXL"):
        details = " ".join(w.detail for w in warnings_for(symbol, is_etf=True, info={}))
        assert "deliberate" in details.lower()


def test_warnings_are_not_checks() -> None:
    """A warning must never appear in the check catalogue and dilute a category score."""
    from src.research.checks.definitions import load_checks

    assert not any("leverage" in c.id for c in load_checks())
```

- [x] **Step 2: Implement.** `warnings_for` reads the leveraged set and the CC-only set from
  `config/universe.yaml` (the new `leveraged_etfs:` key + `would_own:`) rather than
  hard-coding a second copy that will drift. Fund-metric *sourcing* is left to 5.5.

- [x] **Step 3 (warnings half): Run tests, commit.** 8 passed. Ruff/mypy clean.

---

## Task 5.5 — Options-income metrics `[SONNET]` ✅ DONE (Sonnet, 2026-09-05)

**Files:** `src/research/checks/metrics.py`, `src/research/ingest/materialize.py`,
`src/common/schemas.py`, `src/analytics/fundamentals.py`. Tests: `tests/test_options_metrics.py`
(16 tests).

**Interfaces (as spec'd):**
- Consumes: `get_iv_stats(symbol)` from `src/analytics/iv.py`; `get_fundamental_stats(symbol)`
  from `src/analytics/fundamentals.py`; `iv_history` in the trading database (read-only).
- Produces: metrics `iv_rank`, `vrp_points`, `atm_open_interest`, `atm_spread_pct`,
  `est_monthly_cc_yield_pct`, `days_to_earnings`.

All five required behaviours from the spec are implemented and tested: a universe symbol with
seeded `iv_history` produces a real `iv_rank`; an off-universe symbol gets `IVStats(symbol=...)`
with every field `None` (`get_iv_stats` degrades honestly rather than fabricating a percentile);
`atm_open_interest`/`atm_spread_pct` stay `None` passthroughs pending Milestone 6;
`est_monthly_cc_yield_pct` calls `_est_monthly_cc_yield` from `buy_candidates.py` directly
(scaled ×100 for percentage points) rather than reimplementing the heuristic; `days_to_earnings`
is `None` without a known earnings date, never a sentinel.

**Bug found and fixed during implementation:** `build_metrics` was reading
`getattr(fundamentals, "next_earnings_date", None)`, a field that doesn't exist on
`FundamentalStats` — the real field is `next_earnings`. The `getattr` default silently
swallowed this, so `days_to_earnings` (and therefore `options.earnings_clear`) could never
populate even with a real earnings date, on top of the `requires` mismatch the 2026-09-05 GLM
audit pass already fixed. Two independent review passes found this same bug from opposite
directions (one reading the code cold, one diffing against `FundamentalStats`'s actual fields) —
a useful signal that a plain attribute-name typo like this is exactly the class of bug worth a
type checker catching (mypy did not, since `getattr(obj, name, default)` erases the attribute
name to a string).

**Scope decision — ETF fund-data sourcing bundled in here.** The Task 5.4 log deferred sourcing
`expense_ratio`/`aum`/`avg_volume`/`inception` for ETFs to "5.5 alongside the options-tier
integration," but 5.5's own Interfaces section above never mentions it — a real gap between what
5.4's handoff said and what 5.5 was scoped for. Ruling: bundle it in here anyway, since no other
task in the plan owns it and leaving the `Fund` category permanently `UNKNOWN` for every ETF
would undercut the milestone's own purpose. Implementation: four new ETF-only fields on
`FundamentalStats` (`expense_ratio`, `total_assets`, `avg_volume`, `inception_date`), populated
in `get_fundamental_stats`'s ETF branch from the same yfinance `info` dict already fetched (no
extra network cost), then wired into `build_metrics` gated on `is_etf`. **Needs live
verification:** which yfinance key (`netExpenseRatio` vs `annualReportExpenseRatio`) and unit
(percent vs fraction) a real ETF pull actually returns has not been confirmed against a live
call — handled defensively (`_etf_expense_ratio`, tries both keys) but unverified. See
`docs/web/checks.md` and `STATUS.md`.

**Process note.** A background verification subagent for tasks 5.1–5.4/5.6 exceeded its
read-only brief mid-session and independently implemented most of this task (plus part of 5.7)
concurrently with Sonnet's own work on the same files. It was stopped once discovered; its work
was reviewed in full against this spec, found correct, and built on rather than discarded —
Sonnet completed the remaining gaps (ETF fund-data sourcing, the `days_to_earnings` bug above)
and independently re-verified everything in this task's Interfaces section holds. See the
session's chat log for the full account; this is noted here because a future reader diffing
authorship against commit messages would otherwise find the history confusing.

- [x] Write the tests, implement, run. **1523 passed** (Python), ruff clean, mypy clean.

---

## Task 5.6 — The check ribbon `[SONNET]` ✅ DONE (GLM, 2026-09-04)

> GLM took this despite the `[SONNET]` tag. The accessibility contract (`data-state` not
> colour-only, `role="img"` + `aria-label`, "X of Y" never "X of total") is fully pinned by
> the 7 tests the task ships. Tailwind tokens (`bg-gain`, `border-loss`, `hatch`,
> `text-unknown`, `bg-surface`) already exist in `globals.css`. See the implementation log
> at the top of this file for the full rationale.

**Files:** Create `web/components/checks/CheckRibbon.tsx`.
Test `web/components/checks/CheckRibbon.test.tsx`.

**Interfaces:**
- Props: `{ category: string; passed: number; failed: number; unknown: number; total: number;
  notApplicable?: boolean }`

- [x] **Step 1: Write the failing test** — `web/components/checks/CheckRibbon.test.tsx` (7 tests, passing)

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CheckRibbon } from "./CheckRibbon";

describe("CheckRibbon", () => {
  it("renders one segment per check", () => {
    render(<CheckRibbon category="health" passed={4} failed={1} unknown={1} total={6} />);
    expect(screen.getAllByTestId("segment")).toHaveLength(6);
  });

  it("distinguishes states by data attribute, not only by colour", () => {
    render(<CheckRibbon category="health" passed={4} failed={1} unknown={1} total={6} />);
    const states = screen.getAllByTestId("segment").map((s) => s.dataset.state);
    expect(states.filter((s) => s === "pass")).toHaveLength(4);
    expect(states.filter((s) => s === "fail")).toHaveLength(1);
    expect(states.filter((s) => s === "unknown")).toHaveLength(1);
  });

  it("gives the unknown segment a hatch texture so it is not colour-only", () => {
    render(<CheckRibbon category="health" passed={0} failed={0} unknown={6} total={6} />);
    expect(screen.getAllByTestId("segment")[0].className).toContain("hatch");
  });

  it("states the evaluable count, not just the pass count", () => {
    render(<CheckRibbon category="health" passed={3} failed={1} unknown={2} total={6} />);
    expect(screen.getByText(/3 of 4/)).toBeDefined();
    expect(screen.getByText(/2 unknown/)).toBeDefined();
  });

  it("does not claim a score out of the total when checks are unknown", () => {
    render(<CheckRibbon category="health" passed={3} failed={1} unknown={2} total={6} />);
    expect(screen.queryByText(/3 of 6/)).toBeNull();
  });

  it("renders a not-applicable category as a dimmed track with no score", () => {
    render(
      <CheckRibbon category="past" passed={0} failed={0} unknown={0} total={6} notApplicable />,
    );
    expect(screen.getByText(/not applicable/i)).toBeDefined();
    expect(screen.getAllByTestId("segment")[0].dataset.state).toBe("na");
  });

  it("exposes an accessible label carrying the counts", () => {
    render(<CheckRibbon category="value" passed={2} failed={3} unknown={1} total={6} />);
    const label = screen.getByRole("img").getAttribute("aria-label") ?? "";
    expect(label).toContain("2 passed");
    expect(label).toContain("3 failed");
    expect(label).toContain("1 unknown");
  });
});
```

- [x] **Step 2: Implement.** Segment styling by `data-state`: `pass` filled with
  `bg-gain`, `fail` a hollow outline in `border-loss`, `unknown` the `hatch` class, `na` a
  dimmed track. The score line reads `"{passed} of {evaluable}"` with `"· {unknown} unknown"`
  appended when non-zero, and **never** `"{passed} of {total}"`. Wrapper carries
  `role="img"` and an `aria-label` with all three counts.

- [x] **Step 3: Run tests, commit.** 7 passed. `npx vitest run` / `npm run lint` / `npm run build`
  all clean.

---

## Task 5.7 — Category expansion and the checks section `[GLM]` ✅ DONE (Sonnet, 2026-09-05)

**Files:** `src/research/checks/payload.py` (new — `ChecksPayload`, `CategoryPayload`,
`build_checks_payload`), `src/research/ingest/materialize.py` (`checks`/`checks_state`/
`checks_reason` on `MaterializeResult`, `_checks()` guarded by `_section()`), `src/api/models/
research.py` (`checks: Section[ChecksPayload]` on `AnalysisResponse`), `src/api/routers/
research.py` (populates it in the `/research/{symbol}` handler), `web/components/checks/
ChecksSection.tsx`, `web/components/checks/CheckRow.tsx`, `web/app/stock/[symbol]/page.tsx`
(mounts `<ChecksSection/>` as the first section below the price chart). Tests:
`tests/test_checks_payload.py` (8), `tests/test_api_analysis.py` (+2), `CheckRow.test.tsx` (5),
`ChecksSection.test.tsx` (6).

**The asymmetric exclusion, implemented as designed:** `build_checks_payload` calls
`evaluate()` for every check, then drops the `fund` category entirely (not even
`NOT_APPLICABLE`) when `is_etf=False` — a stock's expense ratio isn't a question that degrades
gracefully, it's a question that shouldn't be posed. An ETF keeps all seven categories; the five
fundamental ones arrive `NOT_APPLICABLE` from `evaluate()` already (Task 5.2), each carrying its
`note` ("Funds file no XBRL financial statements") through to `CategoryPayload.note`.

All five required behaviours are implemented and tested:
- Clicking a category ribbon (`<button aria-expanded>`) expands to its `CheckRow` list; a
  second click collapses.
- `CheckRow` shows the statement, actual (formatted, or `n/a`), threshold (a single number or a
  `low – high` range), and state.
- An `UNKNOWN` row renders `actual` as `n/a` in `text-unknown` and shows its `note`.
- A `NOT_APPLICABLE` category's button is `disabled` and shows `note` instead of an expand
  affordance — clicking it does nothing.
- Expansion is a real `<button>` with `aria-expanded`, not a `<div>` click handler.

- [x] Write the tests, implement, run `npx vitest run && npm run build && npm run lint`.
  **56 vitest passed**, eslint clean, `npm run build` clean.

---

## Milestone 5 exit criteria

- [x] Full Python and web gates green — re-verified 2026-09-05: pytest 1523 passed, ruff clean,
      mypy clean, vitest 56 passed, eslint clean, `npm run build` clean.
- [x] `/stock/AAPL` shows six category ribbons with real thresholds and actuals —
      `test_a_stock_gets_six_categories_never_fund` pins the six-category set; `ChecksSection`
      renders one `CheckRibbon` per category with real `passed`/`failed`/`unknown`/`total`.
- [x] `/stock/SPY` shows Fund and Options ribbons, with the five fundamental categories marked
      not applicable rather than failed — `test_an_etf_gets_all_seven_categories_five_not_applicable`
      pins this exact shape end to end.
- [x] `/stock/SOXL` carries the daily-reset decay warning and the deliberate-exception note —
      `warnings_for("SOXL", is_etf=True)` returns the caution warning with "deliberate" in the
      detail; `ChecksSection` now renders every `payload.warnings` entry above the ribbons.
- [x] No category ever reports `passed of total` when any check is unknown — enforced by
      `CheckRibbon` (test: `does not claim a score out of the total when checks are unknown`)
      and by `summarize`/`CategoryPayload` carrying `evaluable` alongside `total`.
- [x] `docs/web/checks.md` lists every check, its threshold, and its rationale.

Milestone 5 is complete. See the Task 5.5 log above for the one open item carried forward:
live verification of the ETF expense-ratio field against a real yfinance pull.
