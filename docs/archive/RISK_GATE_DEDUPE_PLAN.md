# Risk Gate Per-Symbol Dedupe — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop a symbol's own candidates from competing against each other for its shared per-ticker/sector/CSP/cash budget in `risk_engine.validate_candidates`, so a name that throws off many strikes/expiries in one scan (TQQQ, RKLB, …) is measured against the shared budget exactly once, by its single best candidate — not once per candidate.

**Architecture:** Split `validate_candidates`'s one loop into two passes. Pass 1 runs every per-candidate gate (ROC/yield/VRP, IV rank/RV, DTE, delta, contracts, earnings, margin) — none of these read or write shared state. Among pass-1 survivors that add new exposure, group by `(underlying, strategy)` and keep only the highest-scoring one per group (candidates arrive pre-sorted by `blended_score` desc, so "first survivor per group" is "best survivor per group"); every other survivor in the group is rejected with a new reason, `dedupe_pre_gate`, before it ever touches the shared budget. Pass 2 then runs the existing cumulative checks (concentration, sector, large-position slot, CSP allocation, cash) only against the surviving one-per-group representatives, in the same score order as today — so cross-symbol competition for the shared account-wide budgets (the reason this greedy-by-score design exists at all — see "Background") is completely unchanged.

**Tech Stack:** Python 3.12, pytest, no new dependencies.

**Spec:** No separate spec file — the "Problem" and "Design" sections below are the spec, written from the code as it stands today (`src/engine/risk_engine.py`, `src/engine/capital.py`, `src/engine/decision_engine.py`, `src/orchestrator/scan.py`) and from `tests/test_engine.py`'s existing coverage.

## Global Constraints

- `src/engine/risk_engine.py` is the Rules Engine — the only path to order execution, deterministic, no LLM (CLAUDE.md "Core invariant"). Every change here must stay pure Python with no new imports beyond what's already in the file.
- `capital.py`'s docstring on `_fits` says the generator's sizer and the gate "can never disagree about how big a position may be." This plan does not touch `capital.py` at all (no changes to `Caps`, `Budgets`, `_fits`, `charge`, `risk_units`, `resolve_caps`, `seed_budgets`) — only which candidates from `risk_engine.py` reach the existing cumulative checks changes, not what those checks compute. `_fits` sizes ONE candidate at generation time and never selects among siblings, so it needs no equivalent change.
- Full quality gate before any task is considered done: `python -m pytest -q`, `ruff check .`, `mypy src`. The suite currently has exactly one pre-existing, unrelated failure — `tests/test_write_path_invariants.py::test_every_options_route_requires_owner` (a FastAPI internal-API break, `Dependant` has no `.dependant` attribute on the installed FastAPI version) — confirm it's still the only failure, don't chase it.
- Doc-update rule (CLAUDE.md): this is a bug fix that changes behaviour an operator would notice (which candidates get `concentration_limit`), so `STATUS.md` must get a dated entry, and `ARCHITECTURE.md`'s `risk_engine.py` row (line ~154) must stay accurate — both are Phase 3 below.

## Background — why this needs a "careful" two-pass fix and not a simpler reorder

`select_top_candidates_detailed` (`src/engine/decision_engine.py`) already dedupes "to the single best strike per (underlying, strategy)" — but it runs on `passed`, i.e. *after* the risk gate (`src/orchestrator/scan.py:1505`, called on the survivors of `validate_candidates` + the score floor). By the time it runs, every strike/expiry of a symbol that individually cleared the generator has already been walked through `validate_candidates`'s greedy, score-ordered budget consumption (`src/orchestrator/scan.py:1412-1414`: *"Score first so the risk engine consumes its cumulative budgets... greedily in priority order"*) — so a symbol's own siblings compete against each other for its own per-ticker budget before dedupe ever gets a chance to pick a winner.

Confirmed against two weeks of real scan data (`data/income_system.db`): 95 of 96 `concentration_limit` rejections were TQQQ, a symbol the account held **zero** position in at the time — the budget was being exhausted entirely by TQQQ's own strikes/expiries competing against each other within single scan cycles, not by real cumulative exposure.

The naive fix — move `select_top_candidates_detailed` to run *before* `validate_candidates` instead of after — has a real cost: today, if the single best-scored candidate for a symbol fails a per-candidate economic gate (e.g. `roc_below_minimum` on that specific strike) while a different strike/expiry of the same symbol would have passed easily, the current order lets that runner-up become the symbol's pick. Deduping on raw `blended_score` before *any* gate runs would throw that runner-up away even though it never competed with anyone for budget — a real, if narrow, regression. The two-pass design in this plan avoids it: every candidate still gets its **individual** economic/liquidity gates checked before dedupe ever excludes it; only the **shared-budget** gates are deferred to a single representative per symbol.

**Deliberately not fixed here:** the pre-existing "closest near-miss" ranking bug (`_rank_assessed` in `scan.py`, documented in `STATUS.md` → "Remaining known issues") — an unpriced $0.00 contract can still outrank a genuinely-priced near-miss on `blended_score`. Unrelated mechanism, separate fix.

**Deliberately not touched:** `run_ticker_scan`'s single-ticker deep-dive path (`src/orchestrator/scan.py:1858-1930`, the `/scan TICKER` command). It calls `validate_candidates` too, but it never calls `select_top_candidates_detailed` — showing every passing strike for the one ticker under discussion is the point of that view (an operator comparing strikes manually), not a bug. Applying this plan's dedupe there would silently hide strikes the deep-dive exists to show.

## Phase 1: Two-pass split in `validate_candidates`

### Task 1.1 — Add the representative-selection helper and rewrite `validate_candidates`

**Files:**
- Modify: `src/engine/risk_engine.py:44-250` (the whole `validate_candidates` function)
- Test: `tests/test_engine.py`

**Interfaces:**
- Produces: `_select_budget_representatives(candidates: list[TradeCandidate], survivor_ids: set[str]) -> set[str]` — a new pure helper in `risk_engine.py`, placed directly above `validate_candidates`.
- `validate_candidates`'s public signature and return type (`list[RiskVerdict]`) are unchanged.

- [ ] **Write the failing tests first**, in `tests/test_engine.py`. Add this new test class right after `class TestConcentrationInRiskUnits:` (after line 819, before the `# --- risk_engine.py — validate_live_quote` section header at line 822):

```python
class TestBudgetDedupeAcrossSameSymbol:
    """The 2026-09-11 fix: a symbol's own candidates must not compete against each other
    for its shared per-ticker/sector/CSP/cash budget. Exactly one candidate per
    (underlying, strategy) — the highest-scoring pass-1 survivor — ever reaches the
    cumulative checks; every other survivor in the group is rejected with
    "dedupe_pre_gate" without the shared budget being touched at all."""

    def test_only_the_best_scoring_sibling_reaches_the_budget(self) -> None:
        # Three TQQQ CSPs, same collateral/IV/DTE as the old
        # test_cumulative_concentration_across_same_ticker fixture (each ~2,216 risk units,
        # well under the 5,000 ticker-risk cap on its own) but DIFFERENT blended_score, so
        # there's an unambiguous "best" one. Under the old greedy-per-candidate design all
        # three would be walked through the budget in list order and the first two would
        # both pass (4,432 <= 5,000); under the two-pass design only the highest-scoring one
        # (c_best) is ever tested against the budget, and it must pass alone.
        c_low = _candidate(
            candidate_id="c_low",
            underlying="TQQQ",
            collateral=10_000.0,
            dte=28,
            current_iv=80.0,
            scores=_scores(
                iv=40, technical=40, fundamental=40, liquidity=40, assignment=40, symbol="TQQQ"
            ),
        )
        c_best = _candidate(
            candidate_id="c_best",
            underlying="TQQQ",
            collateral=10_000.0,
            dte=28,
            current_iv=80.0,
            scores=_scores(
                iv=90, technical=90, fundamental=90, liquidity=90, assignment=90, symbol="TQQQ"
            ),
        )
        c_mid = _candidate(
            candidate_id="c_mid",
            underlying="TQQQ",
            collateral=10_000.0,
            dte=28,
            current_iv=80.0,
            scores=_scores(
                iv=65, technical=65, fundamental=65, liquidity=65, assignment=65, symbol="TQQQ"
            ),
        )
        # score_candidates sorts DESC by blended_score — feed validate_candidates already
        # sorted, exactly as scan.py does.
        scored = score_candidates([c_low, c_best, c_mid])
        verdicts = validate_candidates(scored, _account(net_liquidation=100_000.0), [])
        vm = {v.candidate_id: v for v in verdicts}

        assert vm["c_best"].verdict == Verdict.PASS, vm["c_best"].reasons
        assert vm["c_low"].verdict == Verdict.REJECT
        assert vm["c_low"].reasons == ["dedupe_pre_gate"]
        assert vm["c_mid"].verdict == Verdict.REJECT
        assert vm["c_mid"].reasons == ["dedupe_pre_gate"]

    def test_different_symbols_still_compete_for_the_shared_budget_by_score(self) -> None:
        # Cross-symbol behaviour (the actual reason the greedy-by-score design exists) must
        # be untouched: two DIFFERENT tickers, each individually under the ticker-risk cap,
        # but together they blow the shared deployable-cash buffer. The higher-scored one
        # (by feed order, since score_candidates sorts DESC) still wins the shared resource.
        acc = _account(net_liquidation=100_000.0, cash=16_000.0, maintenance_margin=10_000.0)
        c_a = _candidate(
            candidate_id="a",
            underlying="AAPL",
            collateral=4_000.0,
            scores=_scores(iv=90, technical=90, fundamental=90, liquidity=90, assignment=90),
        )
        c_b = _candidate(
            candidate_id="b",
            underlying="MSFT",
            collateral=4_000.0,
            scores=_scores(
                iv=10, technical=10, fundamental=10, liquidity=10, assignment=10, symbol="MSFT"
            ),
        )
        scored = score_candidates([c_a, c_b])
        verdicts = validate_candidates(scored, acc, [])
        vm = {v.candidate_id: v for v in verdicts}
        assert vm["a"].verdict == Verdict.PASS  # higher score, spends the buffer first
        assert vm["b"].verdict == Verdict.REJECT
        assert "buying_power_buffer" in vm["b"].reasons

    def test_representative_that_fails_the_budget_is_not_replaced_by_a_sibling(self) -> None:
        # Deliberate, documented non-goal (see the plan's Background section): if the sole
        # representative fails a cumulative check, the whole group is done for this cycle —
        # no retry against a lower-scored sibling.
        acc = _account(net_liquidation=100_000.0, cash=100_000.0)
        c_best = _candidate(
            candidate_id="c_best",
            underlying="MARA",
            collateral=60_000.0,  # blows the 10%-of-NLV (10,000) raw-collateral fallback cap
            current_iv=None,
            scores=_scores(
                iv=90, technical=90, fundamental=90, liquidity=90, assignment=90, symbol="MARA"
            ),
        )
        c_small = _candidate(
            candidate_id="c_small",
            underlying="MARA",
            collateral=1_000.0,  # would easily fit alone
            current_iv=None,
            scores=_scores(
                iv=10, technical=10, fundamental=10, liquidity=10, assignment=10, symbol="MARA"
            ),
        )
        scored = score_candidates([c_best, c_small])
        verdicts = validate_candidates(scored, acc, [])
        vm = {v.candidate_id: v for v in verdicts}
        assert vm["c_best"].verdict == Verdict.REJECT
        assert "concentration_limit" in vm["c_best"].reasons
        assert vm["c_small"].verdict == Verdict.REJECT
        assert vm["c_small"].reasons == ["dedupe_pre_gate"]

    def test_covered_calls_are_not_grouped_or_deduped(self) -> None:
        # CCs never touch the shared budget (adds_new_exposure is False for them), so
        # multiple CC strikes on the same underlying must ALL be able to pass — the
        # pre-gate dedupe must only ever apply to strategies that add new exposure.
        pos = PositionSnapshot(
            symbol="AAPL", sec_type="STK", position=200.0, avg_cost=150.0, market_value=30_000.0
        )
        cc_a = _cc_candidate(underlying="AAPL", strike=180.0, contracts=1)
        cc_b = _cc_candidate(underlying="AAPL", strike=190.0, contracts=1)
        verdicts = validate_candidates(
            score_candidates([cc_a, cc_b]), _account(net_liquidation=100_000.0), [pos]
        )
        assert all(v.verdict == Verdict.PASS for v in verdicts)
```

- [ ] **Run the new tests and confirm they fail** against the current code (the old code has no `dedupe_pre_gate` reason at all, and `test_only_the_best_scoring_sibling_reaches_the_budget` will show `c_mid` passing too):

```bash
python -m pytest tests/test_engine.py -k "TestBudgetDedupeAcrossSameSymbol" -v
```

Expected: `test_only_the_best_scoring_sibling_reaches_the_budget` and `test_representative_that_fails_the_budget_is_not_replaced_by_a_sibling` FAIL; the other two already pass by coincidence (they don't exercise the new grouping) — that's fine, they're here as a permanent regression guard, not to prove the fix.

- [ ] **Update the one existing test that encodes the old, now-incorrect behaviour.** `test_cumulative_concentration_across_same_ticker` (`tests/test_engine.py:450-472`) builds three *identical* AAPL CSPs and asserts the first two pass and the third is rejected — that was the greedy-per-candidate consumption this plan removes. Replace it with:

```python
    def test_cumulative_concentration_across_same_ticker(self) -> None:
        # Two-pass design (2026-09-11): identical-score candidates for the same
        # (underlying, strategy) are deduped to a single representative BEFORE the
        # cumulative budget is ever checked, so only one of the three ever reaches it —
        # and it fits comfortably (one candidate's ~2,216 risk units vs the 5,000 cap).
        # The other two are rejected pre-gate, not by the budget.
        cands = [
            _candidate(
                candidate_id=f"c{i}",
                underlying="AAPL",
                collateral=10_000.0,
                dte=28,
                current_iv=80.0,
            )
            for i in range(3)
        ]
        verdicts = validate_candidates(cands, _account(net_liquidation=100_000.0), [])
        passed = [v for v in verdicts if v.verdict == Verdict.PASS]
        assert len(passed) == 1
        rejected = [v for v in verdicts if v.verdict == Verdict.REJECT]
        assert len(rejected) == 2
        assert all(v.reasons == ["dedupe_pre_gate"] for v in rejected)
```

(This test does not call `score_candidates` first — `_candidate()`'s three instances have identical `ScoreCard`s, so they tie on `blended_score`; the two-pass code must not require a strict score ordering to work, only that ties resolve to *some* single representative deterministically by list order — confirm this by reading Task 1.1's implementation below.)

- [ ] **Implement `_select_budget_representatives` and the two-pass `validate_candidates`.** Replace the entire function body at `src/engine/risk_engine.py:44-250` (keep the `_INCOME_STRATEGIES`, `_strategy_limits`, `_sector_of` module-level helpers above it unchanged) with:

```python
def _select_budget_representatives(
    candidates: list[TradeCandidate], survivor_ids: set[str]
) -> set[str]:
    """Keep exactly one candidate per (underlying, strategy) among *survivor_ids*.

    *candidates* must already be sorted by priority (blended_score desc) — the first
    survivor encountered per group is kept as that group's representative for the shared
    cumulative budgets in pass 2; every later survivor in the same group is left out (the
    caller rejects them with "dedupe_pre_gate"). Pure and side-effect-free so it can be
    tested without any config/account setup.
    """
    seen_groups: set[tuple[str, str]] = set()
    representatives: set[str] = set()
    for cand in candidates:
        if cand.candidate_id not in survivor_ids:
            continue
        key = (cand.underlying, cand.strategy.value)
        if key in seen_groups:
            continue
        seen_groups.add(key)
        representatives.add(cand.candidate_id)
    return representatives


def validate_candidates(
    candidates: list[TradeCandidate],
    account: AccountSnapshot,
    positions: list[PositionSnapshot],
    iv_by_symbol: dict[str, float] | None = None,
) -> list[RiskVerdict]:
    """Gate each candidate against hard limits. One RiskVerdict per candidate.

    Candidates should be pre-sorted by priority (blended_score desc). Two passes:

    1. Per-candidate gates (ROC/yield/VRP, IV rank/RV, DTE, delta, contracts, earnings,
       margin) — independent of every other candidate, no shared state touched.
    2. Cumulative, shared-budget gates (per-ticker/per-sector risk units, the large-position
       slot, total CSP collateral, cash) — evaluated at most ONCE per (underlying, strategy),
       against the single highest-scoring pass-1 survivor in that group. Every other
       survivor in the same group is rejected with "dedupe_pre_gate" *without* being run
       through the shared budgets at all.

    Before this split, EVERY pass-1 survivor for a symbol — a scan can produce a dozen+
    strikes/expiries for one active name — was walked through the cumulative checks
    individually in score order, so a name's own candidates competed against each other for
    its own shared per-ticker budget (2026-09-11 finding: 95 of 96 concentration_limit
    rejects over two weeks were TQQQ, a name the account held zero position in — the
    budget was being spent entirely within single scan cycles, by TQQQ's own siblings). The
    cross-symbol behaviour this cumulative design was built for (D1/Phase B: "multiple
    candidates can't each claim the whole account") is unchanged: representatives from
    different symbols still compete for the shared sector/CSP/cash caps in score order.

    *iv_by_symbol* (optional) lets an existing option position charge the RISK-UNIT tallies,
    not just the raw-collateral one. Without it `budgets.ticker_risk` starts empty, so a
    candidate whose own IV is known is measured against a per-ticker/per-sector budget that
    counts nothing already held. Callers that already have IV for the whole portfolio in hand
    pass it (the full scan sweep); callers on a latency-sensitive path where it would cost a
    fresh network round-trip — the order-approval re-validation gate, a single-ticker
    deep-dive — deliberately do not, and rely on the raw-collateral tally instead.
    """
    if not candidates:
        return []

    risk = get_config().risk
    income = risk.get("income", {})
    portfolio = risk.get("portfolio", {})
    iv_cfg = risk.get("iv", {})
    events = risk.get("events", {})
    today = today_et()

    net_liq = account.net_liquidation
    margin_usage_pct = account.maintenance_margin / net_liq * 100 if net_liq > 0 else 0.0
    margin_exceeded = margin_usage_pct > portfolio.get("max_margin_usage_pct", 50.0)

    min_iv_rank = iv_cfg.get("min_iv_rank")
    min_iv_rv = iv_cfg.get("min_iv_rv_ratio")
    blackout_days = events.get("earnings_blackout_days", 0)

    caps = resolve_caps(account, risk)
    sector_of_fn = get_config().universe.get("sectors", {}).get
    budgets: Budgets = seed_budgets(
        positions, sector_of_fn, iv_by_symbol.get if iv_by_symbol else None
    )

    # --- Pass 1: per-candidate gates. No shared budget is read or written here, so these
    # can run in any order and never depend on what else is in *candidates*.
    candidate_reasons: dict[str, list[str]] = {}
    for cand in candidates:
        reasons: list[str] = []
        limits = _strategy_limits(cand.strategy)

        if cand.strategy in _INCOME_STRATEGIES:
            if cand.roc_pct < income.get("min_roc_pct", 1.0):
                reasons.append("roc_below_minimum")
            if cand.annualized_yield_pct < income.get("min_annualized_yield_pct", 12.0):
                reasons.append("yield_below_minimum")
            if income.get("require_vrp_edge", True) and cand.ideal is not None:
                floor = cand.ideal.min_credit
                if floor is not None and floor > 0 and cand.premium < floor:
                    reasons.append("premium_below_fair_value")

        if min_iv_rank is not None and cand.iv_rank is not None and cand.iv_rank < min_iv_rank:
            reasons.append("iv_rank_below_minimum")

        if (
            min_iv_rv is not None
            and cand.iv_rv_ratio is not None
            and cand.iv_rv_ratio < float(min_iv_rv)
        ):
            reasons.append("iv_rv_below_minimum")

        if limits and not (limits.get("dte_min", 0) <= cand.dte <= limits.get("dte_max", 999)):
            reasons.append("dte_out_of_range")

        if cand.strategy in _INCOME_STRATEGIES:
            if cand.delta is None:
                reasons.append("delta_missing")
            else:
                if cand.right == OptionRight.PUT and cand.delta > 0:
                    reasons.append("delta_sign_mismatch")
                elif cand.right == OptionRight.CALL and cand.delta < 0:
                    reasons.append("delta_sign_mismatch")
                elif limits and not (
                    limits.get("delta_min", 0.0) <= abs(cand.delta) <= limits.get("delta_max", 1.0)
                ):
                    reasons.append("delta_out_of_range")

        max_contracts = limits.get("max_contracts") if limits else None
        if max_contracts is not None and cand.contracts > max_contracts:
            reasons.append("contracts_exceeds_max")

        if cand.next_earnings is not None:
            days_to_earnings = (cand.next_earnings - today).days
            if cand.next_earnings <= cand.expiry or 0 <= days_to_earnings <= blackout_days:
                reasons.append("earnings_blackout")

        if cand.contracts < 1:
            reasons.append("no_contracts")

        if margin_exceeded:
            reasons.append("margin_limit")

        candidate_reasons[cand.candidate_id] = reasons

    # --- Select the one representative per (underlying, strategy) allowed to spend the
    # shared cumulative budgets. Every other pass-1 survivor in the same group is rejected
    # right here, before ever touching `budgets` or `caps`. Only strategies that add new
    # exposure are grouped at all — a covered call never reaches the shared budget either
    # way, so there is nothing to dedupe among CC candidates.
    survivor_ids = {
        cand.candidate_id
        for cand in candidates
        if not candidate_reasons[cand.candidate_id]
        and cand.strategy not in (Strategy.COVERED_CALL, Strategy.ROLL)
    }
    representative_ids = _select_budget_representatives(candidates, survivor_ids)
    for cand in candidates:
        if cand.candidate_id in survivor_ids and cand.candidate_id not in representative_ids:
            candidate_reasons[cand.candidate_id].append("dedupe_pre_gate")

    # --- Pass 2: cumulative, shared-budget gates. Representatives only, walked in the same
    # score-sorted order as *candidates* so cross-symbol competition for the shared
    # sector/CSP/cash budgets is still resolved by priority, exactly as before this split.
    for cand in candidates:
        if cand.candidate_id not in representative_ids:
            continue
        reasons = candidate_reasons[cand.candidate_id]
        sector = _sector_of(cand.underlying)

        cum_collateral = budgets.ticker_collateral.get(cand.underlying, 0.0) + cand.collateral
        units = risk_units(cand.collateral, cand.current_iv, cand.dte)
        if units is None:
            if cum_collateral > caps.max_ticker_collateral:
                reasons.append("concentration_limit")
        else:
            if budgets.ticker_risk.get(cand.underlying, 0.0) + units > caps.max_ticker_risk:
                reasons.append("concentration_limit")
            if sector and budgets.sector_risk.get(sector, 0.0) + units > caps.max_sector_risk:
                reasons.append("sector_limit")

        if cum_collateral > caps.max_ticker_collateral:
            if budgets.large_slots_used >= caps.max_large_positions:
                reasons.append("large_position_slot_full")
            elif cum_collateral > caps.large_ticker_collateral:
                reasons.append("concentration_limit")

        if cand.strategy == Strategy.CASH_SECURED_PUT:
            if budgets.csp_collateral + cand.collateral > caps.max_csp_collateral:
                reasons.append("csp_allocation_limit")
        if budgets.cash_used + cand.collateral > caps.deployable_cash:
            reasons.append("buying_power_buffer")

        # Two independent checks above (the ticker-risk breach and the large-slot ceiling)
        # can both append "concentration_limit" for the same candidate — collapse here,
        # preserving order, exactly as the single-pass version always did.
        reasons = list(dict.fromkeys(reasons))
        candidate_reasons[cand.candidate_id] = reasons

        if not reasons:
            charge(
                contracts=cand.contracts,
                unit_collateral=cand.collateral / max(1, cand.contracts),
                current_iv=cand.current_iv,
                dte=cand.dte,
                symbol=cand.underlying,
                sector=sector,
                caps=caps,
                budgets=budgets,
            )

    return [
        RiskVerdict(
            candidate_id=cand.candidate_id,
            verdict=Verdict.PASS if not candidate_reasons[cand.candidate_id] else Verdict.REJECT,
            reasons=candidate_reasons[cand.candidate_id],
        )
        for cand in candidates
    ]
```

Do not touch `validate_live_quote`, which follows immediately after in the same file — it is untouched by this plan.

- [ ] **Run the full `TestValidateCandidates` + `TestConcentrationInRiskUnits` + new `TestBudgetDedupeAcrossSameSymbol` classes and confirm everything passes:**

```bash
python -m pytest tests/test_engine.py -v
```

Expected: all PASS, including the updated `test_cumulative_concentration_across_same_ticker` and every new test from this task.

- [ ] **Run the rest of the suite that touches `validate_candidates`** to catch anything this plan's review missed:

```bash
python -m pytest tests/test_write_path_invariants.py tests/test_execution.py tests/test_scan_review_reuse.py tests/test_drain_promote.py tests/test_capital.py -q
```

Expected: all PASS (these were confirmed single-candidate-per-symbol scenarios during planning — see the plan's Background section — but re-run for real rather than trusting that analysis).

- [ ] **Commit:**

```bash
git add src/engine/risk_engine.py tests/test_engine.py
git commit -m "fix(risk-engine): dedupe a symbol's own candidates before the shared budget gate

Same-symbol strikes/expiries no longer compete against each other for the
per-ticker/sector/CSP/cash budget in validate_candidates. Two-pass split:
per-candidate gates run for everyone, then the cumulative gates run once per
(underlying, strategy) against the single highest-scoring survivor. Fixes 95
of 96 concentration_limit rejects observed on TQQQ, a symbol the account held
zero position in — the budget was being exhausted by TQQQ's own siblings
within single scan cycles."
```

## Phase 2: Surface `dedupe_pre_gate` to operators

### Task 2.1 — Add the new reason code to both reason-label dictionaries

**Files:**
- Modify: `src/notify/formatters.py:532-563` (`_REJECT_REASON_LABELS`)
- Modify: `src/api/routers/options.py:69-97` (`_humanize_reason`'s `_LABELS`)
- Test: `tests/test_ticker_scan_format.py`

**Interfaces:**
- Consumes: nothing new — both dicts already exist; this task only adds one key to each.

Without this, `dedupe_pre_gate` still renders (both humanizers fall back to `code.replace("_", " ")` → `"dedupe pre gate"`), just without a proper phrase — matching neither dict's existing style.

- [ ] **Write the failing test.** In `tests/test_ticker_scan_format.py`, next to the existing `_humanize_reject_reason("iv_rank_below_minimum")` assertion (around line 94), add:

```python
def test_dedupe_pre_gate_has_a_readable_label():
    assert _humanize_reject_reason("dedupe_pre_gate") == (
        "a better strike on this name already claimed the shared risk budget"
    )
```

- [ ] **Run it and confirm it fails** (falls back to `"dedupe pre gate"`):

```bash
python -m pytest tests/test_ticker_scan_format.py -k dedupe_pre_gate -v
```

- [ ] **Add the key to `formatters.py`.** In `src/notify/formatters.py`, in the `# Post-gate drops` section of `_REJECT_REASON_LABELS` (line ~560-562), add the new key. Since the dedupe this reason describes now happens *inside* the gate, not after it, reword the section comment too:

```python
    # Dedupe / slate-capacity drops — the trade itself was fine, there wasn't room for it.
    "dedupe_pre_gate": "a better strike on this name already claimed the shared risk budget",
    "dedupe_not_surfaced": "a better strike on this name won the slot",
    "top_n_not_surfaced": "max new positions per run already full",
```

(replacing the old `# Post-gate drops — the trade was fine, the slate was not.` comment line directly above `"dedupe_not_surfaced"`.)

- [ ] **Mirror the same key in `src/api/routers/options.py`**, in `_humanize_reason`'s `_LABELS` dict (line ~95), directly above the existing `"dedupe_not_surfaced"` entry:

```python
        "dedupe_pre_gate": "a better strike on this name already claimed the shared risk budget",
        "dedupe_not_surfaced": "a better strike on this name won the slot",
```

- [ ] **Run the test again and confirm it passes:**

```bash
python -m pytest tests/test_ticker_scan_format.py -k dedupe_pre_gate -v
```

- [ ] **Commit:**

```bash
git add src/notify/formatters.py src/api/routers/options.py tests/test_ticker_scan_format.py
git commit -m "feat(notify): human-readable label for the new dedupe_pre_gate reason code"
```

## Phase 3: Docs and full verification

### Task 3.1 — Update STATUS.md and ARCHITECTURE.md

**Files:**
- Modify: `STATUS.md` (new dated entry, above the existing `## Bugs fixed (2026-09-11 — IV-history circuit breaker...)` section)
- Modify: `ARCHITECTURE.md:154` (the `risk_engine.py` row of the module table)

- [ ] **Add a new dated `STATUS.md` entry** above the most recent `## Bugs fixed (2026-09-11 — ...)` heading, following the file's existing style (see any entry above for the format). Write it from the real, final state — do not copy numbers from this plan without re-checking them:
  - What the bug was (95/96 TQQQ `concentration_limit` rejects were siblings competing for one shared budget, not real exposure) and the mechanism (`validate_candidates` walked every pass-1 survivor through the cumulative checks in score order, so a symbol's own strikes competed against each other).
  - The fix (two-pass split; one representative per `(underlying, strategy)` reaches the cumulative checks; new `dedupe_pre_gate` reason).
  - What test file(s) cover it (`tests/test_engine.py::TestBudgetDedupeAcrossSameSymbol`, plus the rewritten `test_cumulative_concentration_across_same_ticker`).
  - The real `python -m pytest -q` pass count from Task 3.2 below, and the one known pre-existing unrelated failure.

- [ ] **Update `ARCHITECTURE.md`'s `risk_engine.py` row (line 154).** It currently says the gate "walks the ranked batch in priority order and enforces cumulative limits... so multiple candidates can't each claim the whole account" — true for cross-symbol competition, but now incomplete: it doesn't mention that same-symbol candidates are deduped to one representative first. Insert a clause (exact wording is the implementer's call — match the row's existing dense, single-paragraph style) explaining that before the cumulative checks run, candidates are grouped by `(underlying, strategy)` and only the single highest-scoring survivor per group is measured against the shared budget, citing `_select_budget_representatives`.

- [ ] **Commit:**

```bash
git add STATUS.md ARCHITECTURE.md
git commit -m "docs: record the risk-gate per-symbol dedupe fix"
```

### Task 3.2 — Full quality gate

- [ ] Run the complete suite and confirm only the one known pre-existing failure remains:

```bash
python -m pytest -q
```

- [ ] Lint:

```bash
ruff check .
ruff format --check .
```

- [ ] Type-check:

```bash
mypy src
```

- [ ] Explicitly confirm the fence tests that guard `risk_engine.py` are unaffected (this plan adds no new imports to the file, but verify directly rather than assuming):

```bash
python -m pytest tests/test_eval_skills.py tests/test_web_fence.py -v
```

- [ ] If everything is green, this plan is complete. If `ruff format` reformats anything, run `ruff format .` and re-run the full suite once more before the final commit.
