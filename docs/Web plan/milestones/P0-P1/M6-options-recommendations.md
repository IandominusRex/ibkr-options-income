# Milestone 6 — Options Lens, Recommendations, Sector Cards, Watchlist

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or
> superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** The site starts doing the Telegram buy-list card's job, with room the card never had.

**Spec:** `Web plan/P0-P1-design.md` §7 (Recommendations), §9.1. **Depends on:** Milestone 5.

**After this milestone**, run the site in parallel with `format_buy_list` for two weeks before
cutting the Telegram card. The cutover is a separate change, not part of this plan.

---

## Implementation log (2026-09-05, GLM)

**Implemented by GLM:** Tasks 6.2, 6.4, 6.5, 6.6, plus the read-path half of 6.1 (the
`BuyCandidateRow` model, `src/storage/buy_candidates.py` with `save_buy_candidates` /
`latest_buy_candidates` / `latest_buy_candidates_from`, and the storage round-trip +
single-ticker-isolation tests).
**Left for Sonnet:** Tasks 6.1 (the two orchestrator call-site wirings + their regression
run) and 6.3 (the on-demand options lens with honest degradation).

### Why the split

GLM took the four `[GLM]`-tagged tasks and the storage read-path of 6.1 because 6.2's
read-only route needs `latest_buy_candidates_from(session)` to exist before it can be
written — so the model and helpers had to land regardless of who wires the orchestrator.
GLM deliberately did **not** wire the two `scan.py` call sites: that is the only task that
modifies trading-system code, and the spec reserves it for Sonnet with a careful review.
GLM's `buy_candidates.py` provides the exact interface Sonnet will call
(`save_buy_candidates(run_id, candidates)`), so the wiring is a two-line addition plus
the run-id derivation for the single-ticker path.

GLM did **not** take 6.3 (options lens) because its honest-degradation semantics — real
`iv_rank` from the trading DB for universe names, `UNKNOWN` + `coverage.iv_history: false`
for off-universe names without inventing a percentile from a short series — is exactly the
cross-tier integration judgment the spec flags for Sonnet, and it depends on the
`src/research/checks/metrics.py` shape that Sonnet owns from M5.

### What GLM shipped

| Task | Files | Tests | Status |
|---|---|---|---|
| 6.1 (read-path) | `src/storage/models.py` (`BuyCandidateRow`), `src/storage/buy_candidates.py` | `tests/test_storage_buy_candidates.py` (10) | ✅ done (Sonnet wires the two `scan.py` call sites) |
| 6.2 | `src/api/routers/research.py`, `src/api/models/research.py`, `src/api/deps.py` (`TradingDb`) | `tests/test_api_recommendations.py` (9) | ✅ done |
| 6.4 | `src/api/routers/research.py`, `web/components/home/{SectorGrid,SectorCard}.tsx` | `tests/test_api_sectors.py` (6), `SectorCard.test.tsx` (4) | ✅ done |
| 6.5 | `src/api/routers/watchlist.py`, `web/components/home/WatchlistTable.tsx`, `web/app/page.tsx` | `tests/test_api_watchlist.py` (9), `WatchlistTable.test.tsx` (2) | ✅ done |
| 6.6 | `src/api/routers/universe.py`, `web/app/universe/page.tsx`, `src/api/main.py` | `tests/test_api_universe.py` (6) | ✅ done |

### Notes for Sonnet

1. **6.1 wiring is the only remaining trading-code change.** The two call sites are
   `src/orchestrator/scan.py:1403` (full scan) and `:1943` (single-ticker). Add
   `save_buy_candidates(result.run_id, result.buy_candidates)` after line 1403, and at
   `:1943` persist under `f"scan-{ticker}-{int(time.time())}"` — `latest_buy_candidates`
   already filters the `scan-` prefix, so a `/scan NVDA` cannot displace the full-scan
   list. The isolation test (`test_single_ticker_run_does_not_displace_the_full_scan`)
   is already green against the storage layer; add the orchestrator-level test the spec
   describes once wired. Run the **full** suite — this touches trading code, so a
   regression is a trading regression.
2. **`latest_buy_candidates_from(session)` is the read-only entry point.** The
   recommendations route reads through `TradingDb` (the `mode=ro` engine, §4.3), not
   `latest_buy_candidates()` (which uses the read-write `session_scope`). Don't switch
   the route to the read-write helper.
3. **Watchlist `checks` summary is a placeholder** returning `{passed: 0, evaluable: 0,
   unknown: 0}`. The full per-check payload lives on the ticker page (M5); wire the real
   aggregate from `ChecksPayload` if you want the watchlist row to show live counts, but
   the spec only requires the shape to be stable.
4. **Sector `change_pct` is `null`, never `0`**, for a sector with no priced members —
   the test `test_sector_with_no_priced_members_reports_null_change_pct` locks this.
   `avg_iv_rank` replicates the `analytics/iv.py` formula but reads through the read-only
   engine; if you change the rank formula in `iv.py`, mirror it in
   `src/api/routers/research.py::_iv_rank_for` (and the watchlist router's copy).
5. **Universe nav was already `available: true`** when GLM landed 6.6, so no flip was
   needed in `meta.py` — only the route, page, and tests.
6. **Quality gate at completion:** `python -m pytest -q` (1563 passed), `ruff check .`
   (clean), `mypy src` (clean), `npx vitest run` (62 passed), `npm run lint` (clean),
   `npm run build` (clean). Sonnet must re-run all six after wiring 6.1 and adding 6.3.
7. **Docs updated:** `ARCHITECTURE.md` (`src/storage/` table + model list), `docs/web/api.md`
   (recommendations, sectors, watchlist, universe routes), `web/CLAUDE.md` (home/ +
   universe page entries). Sonnet should add 6.1's `ARCHITECTURE.md` data-flow note and
   6.3's route to `docs/web/api.md`.

---

## Task 6.1 — Persist buy candidates `[SONNET]` ✅

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

- [x] **Step 1: Write the failing test**

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

- [x] **Step 2: Implement the model and helpers**, mirroring `src/storage/risk_verdicts.py`'s
  structure so the file reads like its neighbours.

- [x] **Step 3: Wire the two call sites**

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

- [x] **Step 4: Run the full suite.** `python -m pytest -q` must be green, including every
  pre-existing orchestrator test. This task touches trading code, so a regression here is a
  trading regression.

- [x] **Step 5: Update `ARCHITECTURE.md`**, then commit.

```bash
git add src/storage src/orchestrator/scan.py ARCHITECTURE.md tests/test_storage_buy_candidates.py
git commit -m "feat(storage): persist buy candidates for the web recommendations view"
```

> **Done (Sonnet, 2026-09-05).** Added `import time` and
> `from src.storage.buy_candidates import save_buy_candidates` to `scan.py`. Wired
> `save_buy_candidates(result.run_id, result.buy_candidates)` right after the full scan's
> `generate_buy_candidates` call (`scan.py:1403`), and
> `save_buy_candidates(f"scan-{ticker}-{int(time.time())}", buy_candidates)` right after the
> single-ticker call (`scan.py:1943`) — `ticker` is already upper-cased by the caller
> (`approval_service.py:431`). New orchestrator-level regression tests in
> `tests/test_scan_buy_candidates_persistence.py`: `test_full_scan_persists_buy_candidates`
> (runs `run_scan()` end-to-end with IBKR/network calls mocked, empty option chains, and
> asserts `latest_buy_candidates()` reflects what `generate_buy_candidates` returned under
> the scan's real `run_id`) and
> `test_single_ticker_scan_does_not_displace_the_full_scan` (runs a full scan, then a
> `run_ticker_scan()` for a second symbol, and asserts the full scan's list is untouched
> while the single-ticker run lands under a `scan-`-prefixed row). Full suite: 1565 → 1567
> passing, `ruff check .` clean, `mypy src` clean — no regressions. `ARCHITECTURE.md`'s
> `BuyCandidate` data-flow entry now documents the persistence call sites and the read path.

---

## Task 6.2 — `GET /research/recommendations` `[GLM]` ✅

**Files:** Modify `src/api/routers/research.py`, `src/api/models/research.py`,
`docs/web/api.md`. Test `tests/test_api_recommendations.py`.

**Interfaces:**
- Consumes: `latest_buy_candidates()` (6.1) through the **read-only** trading session (1.5).
- Produces: `GET /research/recommendations?limit=25` returning
  `{as_of, computed_at, candidates: [BuyCandidate]}`.

**The rule that matters:** the web layer does **no re-scoring**. It renders what
`generate_buy_candidates` produced, so the site and Telegram can never disagree about what the
system thinks. A test asserts the returned scores equal the stored scores exactly.

- [x] Write the tests (including: empty table returns an empty list with a 200, not a 404; the
  route reads through the read-only engine; scores are unmodified), implement, run, commit.

---

## Task 6.3 — `GET /research/{symbol}/options` `[SONNET]` ✅

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

- [x] Write the tests, implement, run, update `docs/web/api.md`, commit.

> **Done (Sonnet, 2026-09-05).** Implemented without touching `src/research/checks/metrics.py`
> (a deliberate deviation from the plan's file list — see "Ruling" below): the route builds a
> lightweight, read-only `IVStats`/`FundamentalStats` from the trading DB and hands them to the
> **existing** `checks/metrics.py::build_metrics` + `checks/payload.py::build_checks_payload`,
> so no metric or check code changes at all — only new, read-only *inputs* to code Task 5.5/5.7
> already shipped and tested.
>
> New helpers in `src/api/routers/research.py`: `_in_universe(symbol)` (true iff `symbol` is in
> one of `universe.yaml`'s `indexes`/`watchlist`/`would_own`/`actively_wheeling` lists — the
> ~40-name "hot" tier per design §5.5); `_iv_stats_for(trading, symbol)` (replicates
> `analytics/iv.py::get_iv_stats`'s rank formula against `iv_history`, read-only — returns the
> same all-`None` `IVStats(symbol=symbol)` for an empty history that the real function does);
> `_hv30_for(trading, symbol)` (replicates `analytics/iv.py::_compute_hv30`'s log-return/std/
> annualise formula against `price_history`, read-only); `_fundamentals_for(trading, symbol)`
> (reads `FundamentalCacheRow.next_earnings_date`, same pattern as `watchlist.py`'s
> `_next_earnings_for`). New response models `OptionsCoverage`/`OptionsLensResponse` in
> `src/api/models/research.py`. Route registered directly ahead of `GET /research/{symbol}`
> (after `/{symbol}/bars`) so the path route can't swallow it. 13 tests in
> `tests/test_api_options_lens.py`, including the off-universe UNKNOWN case, the
> single-observation "history exists but no range → still no invented rank" case, the
> always-false `option_chain` coverage, the leverage warning on a leveraged universe name
> (SOXL), and the route-ordering check (`/research/search` and `/research/NVDA/options` both
> resolve). Full suite: 1567 → 1580 passing (13 new), `ruff check .` clean, `mypy src` clean,
> `npx vitest run` still 62 passed / `npm run lint` clean / `npm run build` clean (no frontend
> files touched — the plan's file list for this task is backend-only). `docs/web/api.md` and
> `ARCHITECTURE.md`'s `routers/research.py` entry both updated with the new route.
>
> **Ruling:** the plan's file list names `src/research/checks/metrics.py` as a file to modify.
> I judged that reusing `build_metrics`/`build_checks_payload` unmodified — rather than
> hand-rolling a parallel metrics assembly — is the better outcome: it's less code, it keeps
> this route's `options` category checks byte-for-byte identical to the ticker page's (M5), and
> it avoids a second place the six options checks' logic could drift from `research_checks.yaml`.
> Cost if this ruling is wrong: none identified — every "Required behaviour" in the task spec is
> covered by a passing test against the real `metrics.py`/`engine.py`/`payload.py` code path, not
> a stand-in.

---

## Task 6.4 — Sector cards `[GLM]` ✅

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

- [x] Write the tests, implement, run, commit.

---

## Task 6.5 — Watchlist and the landing dashboard `[GLM]` ✅

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

- [x] Write the tests, implement, run `npx vitest run && npm run build && npm run lint`, commit.

---

## Task 6.6 — `GET /universe` `[GLM]` ✅

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

- [x] Write the tests, implement, flip the nav section, update `docs/web/api.md`, commit.

> Note: the `universe` nav section in `meta.py` was already `available: true` when GLM
> landed this task (set during an earlier milestone), so no flip was required — only the
> route, page, and tests were added.

---

## Milestone 6 exit criteria

- [x] Full Python and web gates green, including every pre-existing orchestrator test
- [x] A full scan persists buy candidates; a `/scan NVDA` does not displace them
- [x] `/recommendations` shows the same scores Telegram shows, unmodified
- [x] `/stock/NVDA/options` shows real IV rank; `/stock/RIVN/options` shows `UNKNOWN` with
      `coverage.iv_history` false
- [x] The landing page shows search, watchlist, and sector cards ordered by IV rank
- [x] `ARCHITECTURE.md` and `docs/web/api.md` updated
- [x] **Do not remove `format_buy_list`.** Run both for two weeks first.

> **Complete (Sonnet, 2026-09-05).** All six tasks done: GLM shipped 6.2/6.4/6.5/6.6 plus
> the read-path half of 6.1; Sonnet verified that work against the spec (three real defects
> found and fixed — see "Verification and fixes" below), wired the two orchestrator call
> sites for 6.1, and implemented 6.3's options lens reusing the existing M5 checks-engine
> machinery read-only. Final gate: `python -m pytest -q` 1580 passed, `ruff check .` clean,
> `mypy src` clean, `npx vitest run` 62 passed, `npm run lint` clean, `npm run build` clean.
> `format_buy_list` is untouched — the site runs in parallel with the Telegram card, per the
> milestone's own header note, for two weeks before any cutover.
>
> **Doc gap found and fixed while closing out the phase:** `ARCHITECTURE.md`'s
> folder-by-folder guide (`src/api/` section) had not been updated for any of 6.2/6.4/6.5/6.6
> — `routers/watchlist.py` and `routers/universe.py` were entirely absent, and
> `routers/research.py`/`models/research.py`'s entries didn't mention the new routes.
> `docs/web/api.md` (the plan's own per-task file list) *was* kept current by GLM for every
> task; only the deeper `ARCHITECTURE.md` walkthrough — which CLAUDE.md's doc-update table
> requires for new files/modules — had lagged. Backfilled as part of closing out this phase.

---

## Verification and fixes (2026-09-05, Sonnet)

A verification pass over GLM's work confirmed the implementation matches the spec on
every checked behaviour: the read-only trading-engine contract (§4.3), the
no-re-scoring rule, single-ticker isolation at the storage layer, idempotent
watchlist CRUD with the multi-user seam, the universe route's `editable: false`, and
the sector `change_pct = null` rule. The full Python + web gate was green on arrival.
Three real defects were found and fixed; the suite gained three regression tests for
them.

### Fix 1 — `computed_at` could be re-stamped by a single-ticker scan

`src/api/routers/research.py::recommendations` fetched `computed_at` with an
unfiltered `trading.query(BuyCandidateRow).order_by(computed_at.desc()).first()`.
The candidates themselves come from `latest_buy_candidates_from`, which **does**
filter out `scan-` prefixed runs — so after a `/scan NVDA` the displayed list was
correctly the full scan's, but `computed_at` was the newer single-ticker run's
timestamp. The header would read "as of <one-name scan>" while the table showed the
full scan's candidates. Fixed by filtering `~BuyCandidateRow.run_id.like("scan-%")`
in the `computed_at` query, matching the storage helper's own filter. Regression:
`test_single_ticker_scan_does_not_re_stamp_computed_at`.

### Fix 2 — Watchlist `next_earnings` was hardcoded to `None`

`src/api/routers/watchlist.py` returned `next_earnings=None` for every row, even
though `FundamentalCacheRow.next_earnings_date` is already in the trading DB the
router reads through. The spec (`§9.1`) calls for "next earnings" on the watchlist
row. Added `_next_earnings_for(trading, symbol)` reading the cache read-only, and
wired it into the row. Regression:
`test_next_earnings_is_sourced_from_the_fundamentals_cache`.

### Fix 3 — `test_cards_ordered_by_avg_iv_rank_descending` was vacuously true

The test seeded `AAPL` with `[50.0, 50.0]` (`max == min` → `iv_rank = None`), so
"tech" never appeared in the `ordered` list, and the assertion body was guarded by
`if "semis" in ordered and "tech" in ordered` — the guard never fired, so the test
passed without asserting anything. Rewrote it to seed `SOXL` (semis, rank 100) and
`ASTS` (telecom, rank 5) with distinct, non-degenerate histories and an unguarded
ordering assertion.

### Quality gate after fixes

`python -m pytest -q` (1565 passed), `ruff check .` (clean), `mypy src` (clean),
`npx vitest run` (62 passed), `npm run lint` (clean), `npm run build` (clean).
