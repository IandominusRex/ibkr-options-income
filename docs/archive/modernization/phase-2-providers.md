# Phase 2 — Provider Abstraction (`src/data/`) + Repo Cleanup

**Source of inspiration:** `OpenBB-finance/OpenBB` (provider abstraction), without vendoring
any of its code.
**Pain addressed:** `analytics/*.py` calls `yfinance.*` directly. The 2026-08-13 OI-wait bug
and the recurring yfinance rate-limit pain show the cost. A future migration to FMP/Polygon
would require rewriting every analytics module. Additionally, `fix_indentation.py` at the repo
root is an unrelated desktop utility that clutters the layout table.

**Risk:** Medium — touches every analytics module. Mitigated by golden-master tests and the
fact that the yfinance backend is literally the existing code wrapped in a class. Single PR,
single review.

**Depends on:** nothing. Can run first or in parallel with Phase 1.

---

## Files touched

### New files
- `src/data/__init__.py` — package marker.
- `src/data/protocols.py` — `Protocol` classes:
  - `PriceProvider`: `get_ohlcv(symbol, lookback_days) -> pd.DataFrame`,
    `get_last_price(symbol) -> float | None`
  - `FundamentalsProvider`: `get_info(symbol) -> dict`, `get_calendar(symbol) -> dict`
  - `NewsProvider`: `get_headlines(symbol, limit) -> list[dict]`
- `src/data/factory.py` — `get_price_provider()`, `get_fundamentals_provider()`,
  `get_news_provider()` factories. Read `config/settings.yaml → data.*` to pick the backend;
  cache the instance process-wide.
- `src/data/yfinance_backend.py` — concrete `YFinancePriceProvider`,
  `YFinanceFundamentalsProvider`, `YFinanceNewsProvider`. Each method wraps the current
  `yf.Ticker(...).info` / `yf.download(...)` / `yf.Ticker(...).news` call. **No behaviour
  change** — the wrapper is the existing code in a class.
- `src/data/fmp_backend.py` — stub classes raising `NotImplementedError`. Documents the
  swap path; not wired in Phase 2. The *interface* is the deliverable.
- `tests/test_data_providers.py` — verify each backend implements the Protocol; golden-master
  test that the yfinance backend produces output identical to captured fixtures (current
  behaviour preserved exactly).

### Modified files
- `src/analytics/technicals.py` — replace `yf.Ticker(symbol).fast_info["lastPrice"]` and
  `get_ohlcv` internals with `get_price_provider().get_last_price(symbol)` /
  `get_ohlcv(symbol)` (where `get_ohlcv` itself routes through the provider).
- `src/analytics/fundamentals.py` — replace `yf.Ticker(symbol).info` / `.calendar` with
  `get_fundamentals_provider().get_info(symbol)` / `.get_calendar(symbol)`.
- `src/analytics/sentiment.py` — replace `_fetch_stocktwits`, `_fetch_news`,
  `_fetch_reddit` internals with `get_news_provider()` calls. The StockTwits and Reddit paths
  stay as they are (no StockTwits/Reddit provider abstraction in Phase 2 — they're not yfinance;
  the news-headlines path through yfinance *is* abstracted).
- `src/analytics/market_conditions.py` — replace `^VIX` / `^VIX3M` yfinance fetches with
  `get_price_provider().get_last_price("^VIX")` etc.
- `src/analytics/realized_vol.py`, `src/analytics/price_data.py` — already abstracted via
  `get_ohlcv`; route `get_ohlcv` itself through the provider.
- `src/common/cache.py` — `@daily_cached` stays; providers sit *below* it (the cache is
  process-level; the provider is the data source).
- `config/settings.yaml` — new `data:` block:
  ```yaml
  data:
    price_provider: yfinance
    fundamentals_provider: yfinance
    news_provider: yfinance
  ```

### Deleted files
- `fix_indentation.py` (repo root) — unrelated desktop utility.
- Its row in `README.md` layout table.

### Tests
- `tests/test_data_providers.py` — see "New files" above.
- All existing tests pass unchanged (the yfinance backend *is* the existing code wrapped).
- `tests/test_eval_skills.py::test_fair_value_stays_in_the_deterministic_tier` and
  `::test_macro_never_reaches_the_engine` stay green (no enrichment-tier imports added).

---

## Doc updates (mandatory per CLAUDE.md trigger table)

- `ARCHITECTURE.md`:
  - New "Data abstraction layer" section in the `src/` walkthrough.
  - Add `src/data/` row in the folder guide.
  - Note explicitly that IBKR is *not* a "provider" — it's the broker + execution path and
    stays untouched.
- `README.md` layout table:
  - New `src/data/` row.
  - **Remove the `fix_indentation.py` row.**
- `STATUS.md`:
  - "What is built" mentions the data abstraction layer.
  - "Future ideas" line "Postgres migration" extended: "FMP/Polygon provider swap is now a
    config change."
- `CLAUDE.md`:
  - New invariant line under "Conventions": "analytics/strategies/engine never call
    yfinance directly; they go through `src/data/`."
- `SETUP.md`:
  - Note the new `data:` config block.

---

## Verification checklist

```bash
python -m pytest -q                # all tests pass
ruff check .                        # no lint issues
mypy src                            # no type errors
```

Cross-phase invariants:
```bash
python -m pytest tests/test_eval_skills.py::test_fair_value_stays_in_the_deterministic_tier
python -m pytest tests/test_eval_skills.py::test_macro_never_reaches_the_engine
```

Both must pass. The provider layer is purely a structural refactor — no gating logic moves,
no new signals reach the engine.

---

## Why this phase is second

- Phase 3 (phase classification + relative strength) needs SPY OHLCV via a price provider;
  Phase 2 is the structural prerequisite.
- Doing Phase 1 first is deliberate: Greeks are self-contained and unblock Phase 3's
  economic signals, while the provider refactor is bigger and riskier — better second.
- Phase 2 is the right place to bundle the `fix_indentation.py` cleanup: both are "tidy the
  repo's interface with the outside world" concerns.

---

## Risk mitigation

- **Single PR, single review.** The diff is broad but mechanical.
- **Golden-master tests** capture the exact output of every yfinance call before the refactor;
  the wrapped backend must reproduce it byte-for-byte.
- **The yfinance backend is literally the existing code wrapped in a class.** No behaviour
  change is the contract.
- **FMP stubs raise `NotImplementedError`.** No accidental swap path exists; the swap is a
  future config change, not a default change.