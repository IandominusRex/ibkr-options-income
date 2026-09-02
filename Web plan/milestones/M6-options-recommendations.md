# Milestone 6 — Options Lens, Recommendations, Sector Cards, Watchlist

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or
> superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** The site starts doing the Telegram buy-list card's job, with room the card never had.

**Spec:** `Web plan/P0-P1-design.md` §7 (Recommendations), §9.1. **Depends on:** Milestone 5.

**After this milestone**, run the site in parallel with `format_buy_list` for two weeks before
cutting the Telegram card. The cutover is a separate change, not part of this plan.

---

## Task 6.1 — Persist buy candidates `[SONNET]`

**This is the only task in the whole plan that modifies trading-system code.** Sonnet, and
review it carefully.

**Context.** `generate_buy_candidates` is called at `src/orchestrator/scan.py:1403` (the full
scan) and `:1943` (the single-ticker `/scan TICKER` path). Neither result reaches SQLite; both
go straight to `format_buy_list`. There is no `BuyCandidateRow`. So `/research/recommendations`
has nothing to read, and recomputing inside the API would turn a page load into a full scan.

**The writer is the orchestrator, an existing trading process. The API still writes nothing to
the trading database**, so §4.3 holds unchanged.

**Files:**
- Modify: `src/storage/models.py` (add `BuyCandidateRow`)
- Create: `src/storage/buy_candidates.py` (persistence helpers, matching the shape of the
  existing `src/storage/risk_verdicts.py`)
- Modify: `src/orchestrator/scan.py` (two call sites)
- Modify: `ARCHITECTURE.md` (`src/storage/` table and the data-flow section)
- Test: `tests/test_storage_buy_candidates.py`

**Interfaces:**
- Produces:
  - `BuyCandidateRow`: `id, run_id, symbol, score, sector, iv_rank, quality_flag,
    technical_regime, rationale, price, current_iv, hv_30, vrp, rsi_14, sma_50, sma_200,
    next_earnings, dividend_yield, est_monthly_cc_yield, iv_score, fundamental_score,
    technical_score, computed_at`
  - `save_buy_candidates(run_id: str, candidates: list[BuyCandidate]) -> int`
  - `latest_buy_candidates(limit: int = 25) -> list[BuyCandidate]`

- [ ] **Step 1: Write the failing test**

```python
"""Buy candidates round-trip through SQLite, and only the newest run is served."""

from __future__ import annotations

from src.common.schemas import BuyCandidate
from src.storage.buy_candidates import latest_buy_candidates, save_buy_candidates


def _cand(symbol: str, score: float) -> BuyCandidate:
    return BuyCandidate(
        symbol=symbol, score=score, sector="tech", iv_rank=45.0,
        quality_flag=True, technical_regime="UPTREND",
        rationale="high IV rank, quality passes", price=100.0,
        current_iv=52.0, hv_30=38.0, vrp=14.0,
    )


def test_save_returns_the_row_count(db_session) -> None:
    assert save_buy_candidates("run-1", [_cand("NVDA", 80.0), _cand("META", 74.0)]) == 2


def test_round_trip_preserves_the_analysis_context(db_session) -> None:
    save_buy_candidates("run-1", [_cand("NVDA", 80.0)])
    got = latest_buy_candidates()[0]
    assert got.symbol == "NVDA"
    assert got.vrp == 14.0
    assert got.rationale


def test_results_are_ordered_by_score_descending(db_session) -> None:
    save_buy_candidates("run-1", [_cand("META", 74.0), _cand("NVDA", 80.0)])
    assert [c.symbol for c in latest_buy_candidates()] == ["NVDA", "META"]


def test_only_the_latest_run_is_returned(db_session) -> None:
    save_buy_candidates("run-1", [_cand("OLD", 90.0)])
    save_buy_candidates("run-2", [_cand("NEW", 50.0)])
    assert [c.symbol for c in latest_buy_candidates()] == ["NEW"]


def test_saving_an_empty_list_does_not_clear_the_previous_run(db_session) -> None:
    """A scan that produced nothing must not blank the recommendations page."""
    save_buy_candidates("run-1", [_cand("NVDA", 80.0)])
    assert save_buy_candidates("run-2", []) == 0
    assert [c.symbol for c in latest_buy_candidates()] == ["NVDA"]
```

Use whatever database fixture the existing storage tests use; match
`tests/test_storage_*.py` rather than inventing a new one.

- [ ] **Step 2: Implement the model and helpers**, mirroring `src/storage/risk_verdicts.py`'s
  structure so the file reads like its neighbours.

- [ ] **Step 3: Wire the two call sites**

At `src/orchestrator/scan.py:1403`:

```python
    # --- 5. Buy-to-own recommendations ---
    result.buy_candidates = generate_buy_candidates(would_own, holdings_symbols, analytics_map)
    # Persisted so the web layer can read them without recomputing (which would mean a
    # full scan per page load). Display-only data; nothing reads this back into a gate.
    save_buy_candidates(result.run_id, result.buy_candidates)
```

At `:1943`, persist under a run id derived from the single-ticker path so it cannot displace a
full scan's results. Use a distinct prefix, for example `f"scan-{ticker}-{timestamp}"`, and make
`latest_buy_candidates` ignore single-ticker runs by filtering on the prefix. **A `/scan NVDA`
must never replace the whole recommendations list with one name.** Add a test for exactly that.

- [ ] **Step 4: Run the full suite.** `python -m pytest -q` must be green, including every
  pre-existing orchestrator test. This task touches trading code, so a regression here is a
  trading regression.

- [ ] **Step 5: Update `ARCHITECTURE.md`**, then commit.

```bash
git add src/storage src/orchestrator/scan.py ARCHITECTURE.md tests/test_storage_buy_candidates.py
git commit -m "feat(storage): persist buy candidates for the web recommendations view"
```

---

## Task 6.2 — `GET /research/recommendations` `[GLM]`

**Files:** Modify `src/api/routers/research.py`, `src/api/models/research.py`,
`docs/web/api.md`. Test `tests/test_api_recommendations.py`.

**Interfaces:**
- Consumes: `latest_buy_candidates()` (6.1) through the **read-only** trading session (1.5).
- Produces: `GET /research/recommendations?limit=25` returning
  `{as_of, computed_at, candidates: [BuyCandidate]}`.

**The rule that matters:** the web layer does **no re-scoring**. It renders what
`generate_buy_candidates` produced, so the site and Telegram can never disagree about what the
system thinks. A test asserts the returned scores equal the stored scores exactly.

- [ ] Write the tests (including: empty table returns an empty list with a 200, not a 404; the
  route reads through the read-only engine; scores are unmodified), implement, run, commit.

---

## Task 6.3 — `GET /research/{symbol}/options` `[SONNET]`

Sonnet: this is the on-demand best-effort path, and its honesty about degradation is the whole
point. You asked for universe names to be the core priority with any other ticker analysable on
request, and this route is that contract.

**Files:** Modify `src/api/routers/research.py`, `src/research/checks/metrics.py`.
Test `tests/test_api_options_lens.py`.

**Interfaces:**
- Produces: `GET /research/{symbol}/options` returning
  `{as_of, symbol, in_universe: bool, tier: "hot"|"cold", checks: [CheckResult],
    warnings: [Warning], coverage: {iv_history: bool, option_chain: bool}}`

Required behaviours, each with a test:
- **A universe symbol** returns real `iv_rank` and `vrp_points` from the trading database's
  `iv_history`, read-only, with `coverage.iv_history` true.
- **An off-universe symbol** returns the same shape with `iv_rank` `UNKNOWN` and
  `coverage.iv_history` false. It must **not** invent a percentile from a short series.
- `coverage.option_chain` is always false in P1, because the API holds no IBKR connection.
  `atm_open_interest` and `atm_spread_pct` are therefore `UNKNOWN`, and the response says so
  rather than the UI quietly showing blanks.
- Leverage warnings from Task 5.4 are included for leveraged names.
- The route is registered **after** `/search` and before `/{symbol}` cannot swallow it; add a
  test that `/research/search` and `/research/NVDA/options` both resolve correctly.

- [ ] Write the tests, implement, run, update `docs/web/api.md`, commit.

---

## Task 6.4 — Sector cards `[GLM]`

**Files:** Modify `src/api/routers/research.py`. Create `web/components/home/SectorGrid.tsx`,
`web/components/home/SectorCard.tsx`. Test both sides.

**Interfaces:**
- Produces: `GET /research/sectors` returning
  `{as_of, sectors: [{sector, count, change_pct, best: {symbol, change_pct},
    worst: {symbol, change_pct}, avg_iv_rank}]}`

Sector membership comes from `config/universe.yaml`'s `sectors` map for universe names and from
`symbols.sector` for everything else. `avg_iv_rank` is the differentiator: it answers "where is
premium rich today" at a glance, and no consumer research site shows it.

Required behaviours, each with a test:
- A sector with no priced members reports `change_pct` as `null`, never `0`.
- `avg_iv_rank` averages only members that actually have IV history, and the card shows the
  contributing count so a one-name average is visible as such.
- Cards are ordered by `avg_iv_rank` descending, since premium richness is the reason to look.
- The card renders gain and loss with both a sign and a colour, never colour alone.

- [ ] Write the tests, implement, run, commit.

---

## Task 6.5 — Watchlist and the landing dashboard `[GLM]`

**Files:** Create `src/api/routers/watchlist.py`, `web/components/home/WatchlistTable.tsx`.
Modify `web/app/page.tsx`. Test both sides.

**Interfaces:**
- `GET /watchlist` → `{as_of, items: [{symbol, name, price: Sourced[float], change_pct,
  iv_rank, checks: {passed, evaluable, unknown}, next_earnings}]}`
- `POST /watchlist/{symbol}` → 201, idempotent (a repeat is 200, not an error)
- `DELETE /watchlist/{symbol}` → 204, idempotent

Required behaviours, each with a test:
- Every row is scoped by `user_id`, defaulting to `"owner"`. A test asserts a second user's
  items are not returned, so the multi-user seam is proven before it is needed.
- Adding an unknown symbol returns 404 rather than creating a row that can never resolve.
- Adding a symbol promotes it to the warm tier, so `warm_symbols()` includes it immediately.
- The landing page composes: search entry point, then `WatchlistTable`, then `SectorGrid`.
- An empty watchlist renders **one line of text plus the action**, with no decorative icon
  circle above a heading. That template is banned in `web/CLAUDE.md`.

- [ ] Write the tests, implement, run `npx vitest run && npm run build && npm run lint`, commit.

---

## Task 6.6 — `GET /universe` `[GLM]`

**Spec:** §4.6. Read-only in P1; editing needs the `universe_overrides` write path and belongs
with P2.

**Files:** Create `src/api/routers/universe.py`, `web/app/universe/page.tsx`.
Modify `src/api/main.py`, `src/api/routers/meta.py` (flip the `universe` nav section to
available). Test `tests/test_api_universe.py`.

**Interfaces:**
- Consumes: `get_config().universe` (the parsed `config/universe.yaml`).
- Produces: `GET /universe` returning
  `{as_of, indexes: [str], watchlist: [str], would_own: [str], actively_wheeling: [str],
    sectors: {symbol: sector}, strike_bands: {symbol: float}, editable: false}`

Required behaviours, each with a test:
- Every list from `universe.yaml` is returned, unmodified and in file order.
- `editable` is `false`, so the client cannot render an edit affordance that has no write path
  behind it. That is the "never claim more than the backend did" rule from §4.5.
- The route requires auth.
- The page groups by list, marks which `would_own` names are `actively_wheeling` and which are
  dip-watch, and shows each name's sector and any strike-band override.

- [ ] Write the tests, implement, flip the nav section, update `docs/web/api.md`, commit.

---

## Milestone 6 exit criteria

- [ ] Full Python and web gates green, including every pre-existing orchestrator test
- [ ] A full scan persists buy candidates; a `/scan NVDA` does not displace them
- [ ] `/recommendations` shows the same scores Telegram shows, unmodified
- [ ] `/stock/NVDA/options` shows real IV rank; `/stock/RIVN/options` shows `UNKNOWN` with
      `coverage.iv_history` false
- [ ] The landing page shows search, watchlist, and sector cards ordered by IV rank
- [ ] `ARCHITECTURE.md` and `docs/web/api.md` updated
- [ ] **Do not remove `format_buy_list`.** Run both for two weeks first.
