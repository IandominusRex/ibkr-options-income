# Phase 4 Handoff — Decision + Rules Engine

> Read this first, then `PLAN.md` (Phase 4 entry) and `CLAUDE.md`.

## Where things stand (end of Phase 3)

**Phases 0–3 are complete and verified** (103/103 tests pass, `ruff` clean, `mypy` clean).

What now exists and should be **reused, not rebuilt**:

| File | What it gives you |
|---|---|
| `src/strategies/covered_call.py` | `generate_cc_candidates(symbol, quotes, position, iv_stats, tech_stats, fund_stats) -> list[TradeCandidate]` |
| `src/strategies/cash_secured_put.py` | `generate_csp_candidates(symbol, quotes, account, iv_stats, tech_stats, fund_stats) -> list[TradeCandidate]` |
| `src/strategies/rolling.py` | `generate_roll_candidates(position, quotes, iv_stats, tech_stats) -> list[TradeCandidate]` |
| `src/strategies/_scoring.py` | `make_candidate_id`, `technical_score`, `fundamental_score` helpers shared by all three strategy modules |
| `src/common/schemas.py` | `TradeCandidate`, `ScoreCard`, `RiskVerdict`, `Verdict` — Phase 4 **produces** `RiskVerdict` objects |
| `config/risk_limits.yaml` | All hard limits (delta, DTE, income, liquidity, portfolio concentration) |
| `config/scoring_weights.yaml` | Weights for the blended score — Phase 4 reads these |

Each `TradeCandidate` arrives from Phase 3 with `scores.{iv_score, technical_score, fundamental_score, liquidity_score, assignment_risk_score}` populated and `blended_score=0.0`. Phase 4 fills in `blended_score` and adds `rationale_tags`.

## Phase 4 goal (acceptance criterion)

> Given a `list[TradeCandidate]` (from Phase 3 strategy modules), Phase 4 produces:
> 1. A ranked list with `blended_score` filled in (weighted average of ScoreCard components).
> 2. A `list[RiskVerdict]` — one per candidate — with PASS/REJECT and human-readable reasons.
>
> `pytest` green, `mypy` clean. No live TWS needed for tests.

## Files to create

```
src/engine/scoring.py          # normalize + weight ScoreCard components → blended_score
src/engine/decision_engine.py  # rank candidates, top-N selection, confidence
src/engine/risk_engine.py      # deterministic hard-limit gate → RiskVerdict
tests/test_engine.py           # unit tests; no TWS needed
```

`src/engine/__init__.py` already exists (empty).

## Implementation notes (the parts that bite)

### 1. `scoring.py` — weighted blending

```python
def score_candidates(candidates: list[TradeCandidate]) -> list[TradeCandidate]:
    """Return a new list with blended_score populated on each candidate."""
```

Read weights from `get_config().weights`:

```yaml
# config/scoring_weights.yaml
iv:          0.30
technical:   0.20
fundamental: 0.20
liquidity:   0.15
assignment:  0.15
```

Check `scoring_weights.yaml` exists and has these keys — it was created in Phase 0 but may need
these exact key names. If the file is missing a key, fall back to equal weights (1/5 each).

Formula:
```python
w = get_config().weights
blended = (
    scores.iv_score         * w.get("iv", 0.2)
    + scores.technical_score  * w.get("technical", 0.2)
    + scores.fundamental_score * w.get("fundamental", 0.2)
    + scores.liquidity_score  * w.get("liquidity", 0.2)
    + scores.assignment_risk_score * w.get("assignment", 0.2)
)
```

All component scores are already 0-100, so `blended_score` is also 0-100.

**Return a new list sorted by `blended_score DESC`.**

### 2. `decision_engine.py`

```python
def select_top_candidates(
    candidates: list[TradeCandidate],
    n: int | None = None,
) -> list[TradeCandidate]:
```

- `n` defaults to `config.risk["portfolio"]["max_new_positions_per_run"]` (10).
- Already sorted by blended_score from `score_candidates`. Just slice the top N.
- Add `rationale_tags` — short strings explaining why the candidate ranked high. Useful for
  the Claude prompt and Telegram display. Examples:
  - `"high_iv_rank"` when `scores.iv_score > 70`
  - `"liquid"` when `scores.liquidity_score > 80`
  - `"quality_stock"` when `scores.fundamental_score > 65`
  - `"safe_delta"` when `scores.assignment_risk_score > 75`

  Mutate the candidate's `rationale_tags` list in-place (or return a fresh copy — be consistent).

### 3. `risk_engine.py` — the safety gate

```python
def validate_candidates(
    candidates: list[TradeCandidate],
    account: AccountSnapshot,
    positions: list[PositionSnapshot],
) -> list[RiskVerdict]:
```

This is the **only path to order execution**. It runs twice: once here (decision time),
once again in the execution engine against a fresh live quote (Phase 7). It is purely
deterministic — **no LLM, no external calls**.

Check each candidate against these hard limits from `config/risk_limits.yaml`:

| Check | Source | Reject reason |
|---|---|---|
| `roc_pct >= income.min_roc_pct` | already filtered by strategy modules; re-check here for defense-in-depth | `"roc_below_minimum"` |
| `annualized_yield_pct >= income.min_annualized_yield_pct` | same | `"yield_below_minimum"` |
| `dte in [covered_call/csp].dte_min … dte_max` | | `"dte_out_of_range"` |
| `abs(delta) in [delta_min … delta_max]` | use `candidate.delta`; skip if None | `"delta_out_of_range"` |
| Per-ticker concentration: existing position value + new collateral ≤ `portfolio.max_pct_per_ticker * account.net_liquidation` | sum `pos.market_value` for matching symbol | `"concentration_limit"` |
| Total margin usage: `account.maintenance_margin / account.net_liquidation * 100 <= portfolio.max_margin_usage_pct` | | `"margin_limit"` |
| Buying-power buffer: `account.buying_power >= account.net_liquidation * portfolio.min_buying_power_buffer_pct / 100` | | `"buying_power_buffer"` |
| `candidate.contracts >= 1` | | `"no_contracts"` |

**Earnings blackout:** read `fund_stats` or leave it to a later phase — the `TradeCandidate`
schema does not carry earnings date. For Phase 4, you can add a `next_earnings: date | None`
field to `TradeCandidate` in `schemas.py` OR skip the earnings check and mark it as
`# TODO(Phase 4): earnings blackout requires fund_stats passthrough`. Phase 5/8 handles it
if you skip it now.

**Return:** one `RiskVerdict(candidate_id=..., verdict=Verdict.PASS/REJECT, reasons=[...])` per
input candidate. PASS candidates have `reasons=[]`.

### 4. Integration: calling all three in sequence

The orchestrator (Phase 5) will do:
```python
raw = generate_cc_candidates(...) + generate_csp_candidates(...)
scored = score_candidates(raw)
top = select_top_candidates(scored, n=10)
verdicts = validate_candidates(top, account, positions)
approved = [c for c, v in zip(top, verdicts) if v.verdict == Verdict.PASS]
```

Phase 4 does NOT need to wire the orchestrator — just make each function testable standalone.

## Testing without live data

Build `TradeCandidate` objects directly from known values — no strategy modules needed.

Minimum coverage:
- `score_candidates` fills `blended_score` in [0, 100]
- `score_candidates` sorts DESC by blended_score
- `score_candidates` result is a new list (originals not mutated), or documented otherwise
- `select_top_candidates` returns ≤ N candidates
- `select_top_candidates` adds expected `rationale_tags` for high-iv, liquid, quality, safe-delta
- `validate_candidates` PASS: candidate within all limits → PASS verdict, no reasons
- `validate_candidates` REJECT: roc below minimum → REJECT with `"roc_below_minimum"` in reasons
- `validate_candidates` REJECT: concentration limit exceeded
- `validate_candidates` REJECT: margin limit exceeded
- `validate_candidates` REJECT: dte out of range
- Multiple REJECT reasons on the same candidate (reasons list can have >1 entry)
- Empty input → empty output (not an error)

## Quick verification when ready

```bash
source .venv/bin/activate
python -c "
from src.engine.scoring import score_candidates
from src.engine.decision_engine import select_top_candidates
from src.engine.risk_engine import validate_candidates
# ... build canned TradeCandidate list and run the pipeline
"
python -m pytest -q && ruff check . && mypy src
```

## Open decisions

- **Earnings blackout:** skip for Phase 4 or add `next_earnings` to `TradeCandidate`. If you
  skip, add `# TODO(Phase 4)` at the check site in `risk_engine.py`.
- **`rationale_tags` mutation vs copy:** decide whether `select_top_candidates` mutates the
  incoming list in-place or returns new objects. Either is fine; just be consistent with
  what the orchestrator expects.
- **Weight validation:** should scoring fail loudly if weights don't sum to 1, or silently
  renormalize? Recommend silent renormalization so user can add/remove weight keys in YAML
  without code changes.
- **`validate_candidates` signature:** passing `positions` as `list[PositionSnapshot]` gives
  you everything for concentration checks. You may also want to accept the full `AccountSnapshot`
  for margin/buying-power checks (already in the signature above).
