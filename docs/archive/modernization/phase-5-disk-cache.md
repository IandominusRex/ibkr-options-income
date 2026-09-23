# Phase 5 — Disk-Persisted Fundamentals Cache with Earnings-Aware TTL

**Source of inspiration:** `RyanJHamby/stock-screener` (Git-based fundamentals cache, 74%
API-call reduction, earnings-aware refresh).
**Pain addressed:** `@daily_cached` is in-process — every `approval_service` restart blows
the cache and re-hits yfinance for the whole universe. That's the source of the 2026-08-13
cold-start yfinance storm. Fundamentals change slowly (quarterly earnings); a disk-persisted
cache with earnings-aware TTL is materially better for a long-running daemon.

**Risk:** Low — cache hit/miss is observable via logging; a bug means redundant yfinance calls,
not wrong data. Fail-soft preserved.

**Depends on:** **Phase 2** (provider interface — the cache sits *above* the provider, which
sits *above* yfinance). Phase 1, 3, 4 are not required.

---

## Files touched

### New files
- `src/storage/models.py` — new `FundamentalCacheRow` ORM:
  - `symbol: str` (PK)
  - `data_json: str` (Pydantic-serialized `FundamentalStats`)
  - `fetched_at: datetime`
  - `next_earnings_date: date | None`
- `scripts/clear_cache.py` — **new** CLI: `--fundamentals`, `--sentiment`, `--all` flags for
  manual cache wipe (operator tooling).
- `tests/test_fundamentals_cache.py` — **new**:
  - TTL logic: within ±2 weeks of earnings → refresh if age > 1 day; else refresh if age > 30
    days.
  - Cold-cache fetch path (no row → fetch via provider → persist).
  - Warm-cache no-fetch path (row present, fresh → no provider call).
  - JSON round-trip fidelity (Pydantic `FundamentalStats` → JSON → `FundamentalStats`).
- `tests/test_sentiment_cache.py` — **new**:
  - Sentiment TTL = 1 day regardless of earnings (news moves fast).

### Modified files
- `src/analytics/fundamentals.py`:
  - Replace `@daily_cached` with disk-aware cache:
    - TTL: if `next_earnings_date` is within ±2 weeks → refresh if age > 1 day; else refresh
      if age > 30 days. Matches the stock-screener's earnings-aware strategy.
    - On hit: deserialize `data_json` to `FundamentalStats` (Pydantic round-trip).
    - On miss: fetch via the Phase 2 fundamentals provider, persist, return.
  - Keep `@daily_cached` as a fallback (in case the DB is unavailable — fail-soft to the
    in-process cache rather than raising).
- `src/analytics/sentiment.py`:
  - Same disk-cache pattern for `_fetch_stocktwits`, `_fetch_news`, `fetch_sentiment`.
  - Sentiment TTL = 1 day regardless of earnings (news moves fast).
- `src/common/cache.py`:
  - Keep `@daily_cached` as a public utility — sentiment may still use it for its 1-day TTL;
    the disk cache is the new default for fundamentals.

### Tests
- See "New files" above.
- Existing `test_fundamentals.py`, `test_sentiment.py` unchanged (cache is transparent to
  callers — they see the same `FundamentalStats` / sentiment dict).

---

## Doc updates (mandatory per CLAUDE.md trigger table)

- `ARCHITECTURE.md`:
  - `src/storage/` section — new `FundamentalCacheRow` row.
  - `src/analytics/fundamentals.py` row — disk cache replaces `@daily_cached` as the default.
- `STATUS.md`:
  - "What is built" fundamentals entry updated (disk-persisted, earnings-aware TTL).
- `SETUP.md`:
  - Note the cache lives in `data/ibkr.db` (or wherever the SQLAlchemy DB is configured).
  - Document `scripts/clear_cache.py` in the scripts table.
- `README.md` layout table:
  - `scripts/` row updated with `clear_cache.py`.

---

## Verification checklist

```bash
python -m pytest -q
ruff check .
mypy src
python -m pytest tests/test_eval_skills.py::test_fair_value_stays_in_the_deterministic_tier
python -m pytest tests/test_eval_skills.py::test_macro_never_reaches_the_engine
```

All must pass. The cache is purely an operational efficiency change — no decision quality
impact, no new signal reaches the engine, no gate logic moves.

---

## Why this phase is last

- Pure operational efficiency — no decision quality impact. The right thing to do *after*
  the bigger structural changes (Phases 2-4) are settled.
- Could be moved earlier if the cold-start yfinance pain is acute (the 2026-08-13 incident
  suggests it might be worth prioritizing — but the current ordering reflects dependency
  logic, not urgency).
- Lowest risk of all five phases (cache correctness is observable; a bug means redundant
  calls, not wrong data); a good "polish" phase to end on.

---

## Risk mitigation

- **Fail-soft preserved.** If the DB is unavailable, fall back to `@daily_cached` (the
  current behaviour) rather than raising.
- **Hit/miss observable.** Logging at INFO level reports cache hits and misses, so a TTL
  bug shows up as excessive yfinance calls, not as wrong data.
- **Round-trip fidelity tested.** `test_fundamentals_cache.py` verifies that a
  `FundamentalStats` object serializes to JSON and deserializes back to an equal object —
  no field loss across Pydantic v2 round-trip.