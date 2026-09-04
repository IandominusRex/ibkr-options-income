# The check catalogue

Every check the checks engine evaluates, its threshold, and why that threshold — generated
from `config/research_checks.yaml`, the single source of truth. Change a threshold there, not
here; this file documents what ships, it doesn't define it.

Four states, and the difference between them is the point (`src/research/checks/engine.py`):

| State | Meaning |
|---|---|
| `PASS` / `FAIL` | the data was available and the check was measured |
| `UNKNOWN` | a `requires` input was missing — **never** coerced to `FAIL` |
| `NOT_APPLICABLE` | the question does not apply to this instrument (a fundamental category against an ETF, which files no XBRL) |

A category score is reported as `passed / evaluable` (`evaluable = passed + failed`), with
`unknown` shown alongside — never `passed / total` when anything is unknown. See
`docs/web/api.md`'s `GET /research/{symbol}` section for the wire format.

Two deliberate refinements to the source design doc, decided during Milestone 5: no expression
language (each check names a registered, unit-tested metric function instead — see
`src/research/checks/metrics.py`), and categories need not have six checks apiece (the ETF
`Fund` category honestly has four).

---

## Value *(stock only)*

| Check | Threshold | Why |
|---|---|---|
| P/E ratio positive and reasonable | `0.0001 < P/E < 22` | positive, and at or below a long-run market average |
| PEG ratio reasonable | `0.0001 < PEG < 1` | Lynch's rule: growth at least as fast as the multiple |
| Price-to-book | `< 3` | |
| Price-to-sales | `< 5` | |
| Free cash flow yield | `> 4%` | comfortably above a risk-free rate |
| Earnings yield | `> 4%` | |

## Growth *(stock only, trailing)*

EDGAR carries no analyst forecasts, so this category measures **realised** growth and is named
accordingly. A forward-looking category needs a forecast provider and is deferred.

| Check | Threshold | Why |
|---|---|---|
| Revenue grew year over year | `> 0%` | |
| Revenue CAGR (3y) | `> 5%/yr` | |
| EPS grew year over year | `> 0%` | |
| EPS CAGR (3y) | `> 5%/yr` | |
| Free cash flow grew year over year | `> 0%` | |
| Net margin widened (3y) | `> 0 pts` | |

## Past performance *(stock only)*

| Check | Threshold | Why |
|---|---|---|
| Return on equity | `> 15%` | |
| Return on assets | `> 5%` | |
| Net profit margin | `> 10%` | |
| Gross margin | `> 30%` | |
| Profitable in each of the last 5 years | `5 of 5` | a partial history (fewer than 5 years of filings) reports `UNKNOWN`, never a misleadingly low count |
| Positive operating cash flow, each of the last 5 years | `5 of 5` | same partial-history rule |

## Financial health *(stock only)*

| Check | Threshold | Why |
|---|---|---|
| Current ratio | `> 1` | short-term assets exceed short-term liabilities |
| Debt-to-equity | `< 40%` | |
| Debt covered by operating cash flow | `> 20%` | |
| Cash buffer | `> 0.25×` current liabilities | |
| Shareholders' equity positive | `> 0` | |
| Total assets exceed total liabilities | `> 0` | |

## Dividend and buybacks *(stock only)*

| Check | Threshold | Why |
|---|---|---|
| Pays a dividend | `> 0` | |
| Payout ratio sustainable | `0% ≤ payout ≤ 90%` | covered by net profit |
| Covered by free cash flow | `> 1×` | |
| No cut greater than 10% in 5 years | `< 10%` worst annual drop | |
| Dividend grew over 5 years | `> 0%` CAGR | |
| Dividend yield meaningful | `> 1%` | |

## Fund *(ETF only — replaces the five categories above)*

ETFs file N-CEN and N-PORT, not 10-K, so they carry **no XBRL financial statements at all**.
Running the five fundamental categories against them would report every serious ETF as failing
almost everything — see `Web plan/P0-P1-design.md` §6.1. The engine renders those five as
`NOT_APPLICABLE` for an ETF instead, and this category replaces them.

| Check | Threshold | Why |
|---|---|---|
| Expense ratio | `< 0.5%` | |
| Assets under management | `> $1B` | |
| Average daily dollar volume | `> $10M` | liquidity |
| Track record | `> 3 years` since inception | |

**Data sourcing (Task 5.5):** `expense_ratio`, `total_assets` (AUM), `avg_volume`, and
`inception_date` are ETF-only fields on `FundamentalStats` (`src/common/schemas.py`), populated
in `get_fundamental_stats`'s ETF branch (`src/analytics/fundamentals.py`) from the same
yfinance `info` dict the stock-side fields already read — no extra network cost. **Needs live
verification**: the expense-ratio key/unit yfinance returns has not been confirmed against a
real ETF pull in this deployment (see `STATUS.md`).

## Options income suitability *(every instrument)*

The category that differentiates this from a general fundamentals screen. For an ETF it is
doing most of the work, which is the honest picture for this system.

| Check | Threshold | Why |
|---|---|---|
| IV rank | `> 30` | percentile of current IV within its trailing range (`src/analytics/iv.py`) |
| VRP positive | `IV30 − HV30 > 0` | implied vol priced above realised — the seller's edge |
| ATM open interest | `> 500 contracts` | **`UNKNOWN` until Milestone 6's on-demand option-chain route** — no chain data reaches the research API yet |
| ATM bid-ask spread | `< 10%` of mid | **same M6 dependency** |
| Estimated monthly covered-call yield | `> 1%` | reuses `_est_monthly_cc_yield` (`src/strategies/buy_candidates.py`) rather than a second heuristic |
| Next earnings clear of the option cycle | `> 45 days` out | a typical 30-45 DTE cycle; `UNKNOWN` (never a large sentinel) when no earnings date is known |

**Off-universe symbols.** `iv_rank`, `current_iv`, and `hv_30` come from `get_iv_stats`
(`src/analytics/iv.py`), which reads the trading database's `iv_history` table. A symbol with
no seeded history — anything outside `config/universe.yaml`'s watchlist — gets an all-`None`
`IVStats`, so these three report `UNKNOWN` honestly rather than a fabricated percentile.

---

## Warnings (not checks)

Leveraged-ETF daily-reset decay is a structural property, not a pass/fail question, so it
surfaces as a `Warning` (`src/research/checks/warnings.py`) alongside the checks — never as a
check itself, and never diluting a category score. The leveraged set and the `would_own`
deliberate-exception set both derive from `config/universe.yaml`'s `leveraged_etfs:` and
`would_own:` keys, so there is no second hard-coded copy to drift:

- **CC-only, never assignment-eligible:** `leveraged_etfs − would_own` (LABU, TSLL, DPST)
- **Deliberate `would_own` exception** (confirmed 2026-08-27): `leveraged_etfs ∩ would_own`
  (TQQQ, UPRO, SOXL) — the UI states plainly that this is a considered choice, not an oversight.

## Fence

`src/research/checks/` must never import the AI summary layer (`src/research/summary`) —
enforced by `tests/test_web_fence.py::test_checks_engine_never_imports_the_summary_layer`. The
engine reads the deterministic analytics tier and the normalised financials only.
