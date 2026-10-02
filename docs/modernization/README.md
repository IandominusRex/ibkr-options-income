# Modernization Plan — Analytics, Providers, Stock Recommendations

A phased, incremental modernization of the IBKR Options Income System, taking inspiration
from four external repositories without vendoring any of their code (license stays clean for
future hosting):

| Source | Inspiration taken | Rejected |
|---|---|---|
| `vollib/vollib` | Acknowledged IV-solver idea; not adopted (v2 stored-IV path already serves the backtest) | SWIG/C build, Python 2.7, unmaintained |
| `RyanJHamby/stock-screener` | 4-phase trend classification, relative-strength slope, linear scoring philosophy, earnings-aware disk cache, ATR/swing-low stop math | GitHub Actions runner, Robinhood integration, Minervini buy-signal scoring as-is |
| `OpenBB-finance/OpenBB` | Provider-abstraction pattern (`PriceProvider`, `FundamentalsProvider`, `NewsProvider` protocols) | AGPLv3 vendoring, `pip install openbb[all]`, OpenBB Workspace |
| `domokane/FinancePy` | Full Greeks (gamma/theta/vega), the idea of an American-option early-exercise premium as an economic trigger | GPL-3.0 vendoring, Numba JIT cost, the 95% of products not traded |

---

## Phase index

| Phase | Title | Risk | Depends on | Status |
|---|---|---|---|---|
| **1** | [Extended Greeks + Economic Monitor Triggers + v1 Backtest Deletion](phase-1-greeks.md) | Low | none | **complete** |
| **2** | [Provider Abstraction (`src/data/`) + Repo Cleanup](phase-2-providers.md) | Medium | none (independent) | **complete** |
| **3** | [Phase Classification + Relative Strength](phase-3-phase-rs.md) | Low | Phase 2 (price provider for SPY) | **complete** |
| **4** | [Stock Recommendation Overhaul](phase-4-buy-recommendations.md) | Low | Phase 3 (phase + RS as inputs) | **not started** — `buy_candidates.py` still the 3-factor model; none of the Piotroski/analyst-upside/growth/beta fields exist on `FundamentalStats`/`BuyCandidate` |
| **5** | [Disk-Persisted Fundamentals Cache with Earnings-Aware TTL](phase-5-disk-cache.md) | Low | Phase 2 (provider interface) | **mostly complete** — `FundamentalCacheRow`/`SentimentCacheRow` + TTL logic shipped; `scripts/clear_cache.py` (the operator CLI this phase specifies) was never added |

The proposed execution order is 1 → 2 → 3 → 4 → 5, but only Phase 3, 4, and 5 have hard
dependencies on earlier phases. Phase 1 and Phase 2 are independent and could run in either
order or in parallel.

---

## Cross-phase invariants (maintained throughout)

1. **The fence.** No enrichment-tier signal (`sentiment`, `sector_context`,
   `market_conditions`) ever reaches `fair_value.py`, the risk engine, or position sizing.
   Each phase's test additions include re-running
   `tests/test_eval_skills.py::test_fair_value_stays_in_the_deterministic_tier` and
   `::test_macro_never_reaches_the_engine`.

2. **Rules Engine is the only path to an order.** Any new optional gate
   (`reject_downtrend`, `economic_assignment`, `gamma_dollar`) ships *disabled* by default and
   is deterministic Python with no LLM involvement.

3. **Doc-update trigger table** (from `CLAUDE.md`). Each phase lists the docs touched; no phase
   is declared complete until docs match code:
   - New module added → `README.md` layout table + `ARCHITECTURE.md` folder guide.
   - New config key → `ARCHITECTURE.md` config section + `SETUP.md` if setup-affecting.
   - New script entrypoint → `SETUP.md` scripts table + `README.md` layout table.
   - Feature built/deferred or limitation changes → `STATUS.md`.
   - Bug fix with user-visible behavior change → `SETUP.md` troubleshooting if relevant.

4. **Quality gate** (run after every phase, must all pass):
   ```bash
   python -m pytest -q
   ruff check .
   mypy src
   ```

5. **No GPL/AGPL code vendored.** The American pricer in Phase 1 comes from a public-domain
   binomial-tree reference (Cox-Ross-Rubenstein formulation is widely documented and
   unencumbered). Piotroski F-Score in Phase 4 is a published academic methodology, not code.
   The repo's license posture stays clean for future hosting/distribution.

6. **LLM enrichment is final-design display-only.** Per explicit product decision: Claude /
   Ollama reviews will never gate, size, or place orders. None of these phases route any new
   signal through `src/claude/`. The existing `src/claude/eval/` outcome ledger stays; no
   weight-auto-tuning loop is reintroduced (the deleted skills loop stays deleted).

---

## Execution protocol (for phase-by-phase runs)

1. Load **only** the phase file you intend to execute (e.g. `phase-1-greeks.md`).
2. Implement the listed file changes in order.
3. Add the listed tests.
4. Run the quality gate.
5. Update the docs listed in the phase's "Doc updates" section.
6. Mark the phase's row in this README's phase index as `complete`.
7. Run the cross-phase invariants check (the two `test_eval_skills.py` tests must stay green).

Each phase file is self-contained — it does not assume you have read any other phase file.
When context is cleared between phases, load this README first (for the invariants) and then
the single phase file being executed.

---

## Decisions locked in (from the planning conversation)

- **Phase ordering:** 1 → 2 → 3 → 4 → 5 (proposed order; no user preference given).
- **`reject_downtrend` default:** **off** — paper-trading first; the deterministic gate ships
  disabled and is raised by a human after paper validation.
- **Piotroski F-Score:** **partial** (5-6 of 9 components; `None` when insufficient data,
  matching the existing fail-soft philosophy).
- **American pricer:** **real binomial-tree pricer** (~80 lines, public-domain source — *not*
  FinancePy), not the European lower-bound approximation.
- **Backtest v1 deletion:** **bundled into Phase 1** (smaller combined diff, easier single
  review).
- **`fix_indentation.py` removal:** **part of Phase 2's cleanup** (unrelated utility removed
  from the repo root; its layout-table row is deleted).
- **LLM enrichment:** **final design, display-only** — no phase routes new signals through
  `src/claude/`; the deleted skills loop is not reintroduced.