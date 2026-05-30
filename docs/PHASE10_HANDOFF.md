# Phase 10 Handoff — Streamlit Dashboard

> Read this first, then `PLAN.md` (Phase 10 entry) and `CLAUDE.md`.

## Where things stand (end of Phase 9)

**Phases 0–9 are complete and verified** (265/265 tests pass, `ruff` clean, `mypy` clean on Phase 9 files; two pre-existing `union-attr` errors in `src/analytics/technicals.py` are not from Phase 9).

What now exists and Phase 10 can **reuse, not rebuild**:

| File | What it gives you |
|---|---|
| `src/storage/models.py` | All tables: `candidates`, `risk_verdicts`, `claude_reviews`, `approvals`, `orders`, `fills`, `iv_history`, `option_quotes`, `roll_alerts`, `journal` |
| `src/storage/db.py` | `session_scope()`, `init_db()` — single SQLite file at `data/income_system.db` |
| `src/common/schemas.py` | `EODSummary`, `TradeCandidate`, `PositionSnapshot`, `AccountSnapshot`, `RollAlert`, `ClaudeReview`, `RollReview` — all data contracts |
| `src/common/config.py` | Full config including `StorageCfg.db_url` |
| `config/settings.yaml` | `ibkr.client_ids.dashboard = 21` (reserved) |

## Phase 10 goal (acceptance criterion)

> A `streamlit run dashboard/app.py` command launches a read-only Streamlit app that
> displays: current portfolio (positions + account snapshot from the most recent journal),
> today's top candidates (from `candidates` table), open orders/approvals, fill history,
> IV conditions, and the EOD journal feed. No writes to the DB from the dashboard.
>
> **`pytest` green, `mypy` clean, `ruff` clean.** Dashboard itself is tested with Streamlit's
> `AppTest` or by isolating pure data-transformation functions.

## Files to create

```
dashboard/
    __init__.py
    app.py              # main Streamlit entrypoint
    pages/
        01_portfolio.py     # positions + account
        02_candidates.py    # today's top candidates + scores
        03_orders.py        # approvals + orders + fills
        04_journal.py       # EOD journal feed
        05_iv_conditions.py # iv_history chart
```

## Implementation notes

### 1. Process model

Streamlit runs in its own process. It connects to the shared SQLite DB read-only — no IBKR connection, no writes. Give it `clientId = 21` in `settings.yaml` if it ever needs live data (Phase 10 v1 should not need this — pure DB reads).

### 2. DB reads

Use `session_scope()` to pull rows; convert to Pydantic via `.payload` JSON fields or direct column access. Avoid ORM lazy-loading (use `.all()` eagerly). Cache heavy queries with `@st.cache_data(ttl=60)` so the dashboard doesn't hammer SQLite on every rerender.

### 3. Portfolio page

Read the most recent `JournalRow` (by `entry_date`) and decode `payload["eod_summary"]` → `EODSummary.model_validate(...)`. Display account NLV, buying power, unrealized P&L, net delta exposure, and fill history in a table.

### 4. Candidates page

Query `candidates` table ordered by `blended_score DESC`, join with `risk_verdicts` (to show PASS/REJECT), and optionally with `claude_reviews`. Filter by `run_id` (latest run). Display as a sortable `st.dataframe`.

### 5. Orders page

Query `approvals` (status), `orders` (state, limit_price, fill qty), `fills` (avg_price, commission). Show pipeline: pending → approved → queued → submitted → filled. Use color indicators for state.

### 6. Journal page

Query `journal` table ordered by `entry_date DESC`. Show realized P&L, unrealized delta, narrative, and fill count per row. Include a sparkline of cumulative realized P&L if `st.line_chart` is available.

### 7. IV conditions page

Query `iv_history` for the last 252 trading days per symbol. Compute IV Rank/Percentile inline (or use `src/analytics/iv.py` directly). Display as a bar chart or heatmap per symbol.

### 8. Config sidebar

A sidebar with account selector (if multiple), date range filter, and a "Refresh" button that clears `st.cache_data`.

## Testing approach

- Pure data-transformation functions (e.g., `compute_display_rows(journal_rows)`) are unit-testable without Streamlit.
- For page-level smoke tests, use `streamlit.testing.v1.AppTest` (available in Streamlit ≥ 1.18) to render each page and assert it doesn't raise.
- DB fixtures: reuse the `isolated_db` pattern from `test_eod.py` — create a tmp SQLite, seed rows, pass the URL to the dashboard via a monkeypatched config.

## Open decisions

- **Live portfolio refresh:** Phase 10 is DB-only (no IBKR connection). If you want live Greeks or current positions, that's Phase 10.5 — add a background thread that refreshes the DB every 60 seconds from IBKR (clientId 21). Keep it separate from the Streamlit render loop.
- **Auth:** No auth in Phase 10 (local machine only). If you expose it over a network, add `streamlit-authenticator` or run it behind a VPN.
- **Theming:** Streamlit dark theme works well for trading UIs. Set in `.streamlit/config.toml`: `[theme] base = "dark"`.
- **Deployment:** The dashboard reads `data/income_system.db` — it must run on the same machine as the trading system (or mount the DB file). Streamlit Cloud is not suitable for Phase 10.
