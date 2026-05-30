# Phase 9 Handoff — EOD Reporting + Journaling

> Read this first, then `PLAN.md` (Phase 9 entry) and `CLAUDE.md`.

## Where things stand (end of Phase 8)

**Phases 0–8 are complete and verified** (232/232 tests pass, `ruff` clean, `mypy` clean).

What now exists and Phase 9 can **reuse, not rebuild**:

| File | What it gives you |
|---|---|
| `src/claude/runner.py` | `review_candidates()` + `review_roll()` — subprocess pattern; add `write_journal_narrative()` |
| `src/claude/parser.py` | `parse_claude_output()` + `parse_roll_output()` — add `parse_journal_output()` |
| `src/claude/prompts/strategist.py` | Roll prompt pattern for a new `eod.py` prompt builder |
| `src/ibkr/portfolio.py` | `get_positions(ib)` + `get_account_snapshot(ib, acct)` |
| `src/notify/sender.py` | `send_candidates()` — stateless Bot send pattern; replicate for EOD message |
| `src/storage/models.py` | `JournalRow` table already defined; `FillRow` for fill history |
| `src/storage/db.py` | `session_scope()`, `init_db()` |
| `src/common/schemas.py` | `AccountSnapshot`, `PositionSnapshot`, `ClaudeReview`, `RollReview` |
| `src/common/config.py` | `ClaudeCfg`, `StorageCfg`, `SchedulerCfg` — all needed fields exist |
| `config/settings.yaml` | `scheduler.eod_report = "16:15"`, `ibkr.client_ids.engine = 11` |

## Phase 9 goal (acceptance criterion)

> `eod_report.py` runs as a one-shot script (cron or manual), connects to IBKR with
> clientId 11, computes the day's P&L delta (realized + unrealized), summarises what
> changed in the portfolio, runs the watchlist for tomorrow's top candidates, calls
> Claude to write a narrative journal entry, writes a `JournalRow` to the DB, and
> delivers the summary to Telegram.
>
> **`pytest` green, `mypy` clean, `ruff` clean.** No live TWS needed for unit tests
> (mock IBKR responses).

## Files to create

```
src/orchestrator/eod_report.py   # ONE-SHOT: P&L + what changed + watchlist + Claude journal
src/claude/prompts/eod.py        # EOD journal prompt builder
scripts/run_eod.py               # entrypoint: python -m scripts.run_eod
tests/test_eod.py                # unit tests; mock IBKR + Claude subprocess
```

Also extend:
- `src/common/schemas.py` — add `EODSummary` schema (the object passed to Claude + stored in `JournalRow.payload`)
- `src/notify/formatters.py` — add `format_eod_summary()` for Telegram message

## Implementation notes

### 1. Process model

`eod_report` is a **one-shot process** that:
1. Connects to IBKR (clientId 11 — same as `morning_scan`, but they never run concurrently)
2. Fetches positions + account snapshot
3. Reads today's `fills` table for realized P&L
4. Reads yesterday's `journal` table for the baseline (unrealized P&L comparison)
5. Builds `EODSummary`
6. Calls Claude for a narrative journal entry
7. Writes `JournalRow` to DB
8. Sends Telegram summary
9. Disconnects

### 2. `EODSummary` schema

```python
class EODSummary(BaseModel):
    date: date
    realized_pnl: float        # sum of fills.avg_price * fills.filled_qty * 100 for today
    unrealized_pnl: float      # sum of PositionSnapshot.unrealized_pnl
    unrealized_pnl_delta: float  # vs yesterday's journal entry
    fills_today: int           # count of fills today
    open_positions: int        # count of PositionSnapshot rows
    net_delta_exposure: float  # sum of delta * position * 100 across all options
    account: AccountSnapshot
    top_movers: list[str]      # positions with largest unrealized P&L change
    tomorrow_watchlist: list[str]  # from universe.yaml, for morning context
```

### 3. Realized P&L from fills

Query `FillRow` for today's date:
```python
with session_scope() as session:
    today_fills = (
        session.query(FillRow)
        .filter(FillRow.filled_at >= today_start, FillRow.filled_at < tomorrow_start)
        .all()
    )
realized_pnl = sum(f.avg_price * f.filled_qty * 100 for f in today_fills)
```

Note: option fills are credits (positive = income received). The fill `avg_price` is the per-share premium; multiply by `filled_qty` (contracts) × 100 for dollar value.

### 4. Unrealized P&L delta

Load yesterday's `JournalRow` (by `entry_date = date.today() - 1 day`) and compare:
```python
with session_scope() as session:
    yesterday = (
        session.query(JournalRow)
        .filter(JournalRow.entry_date == date.today() - timedelta(days=1))
        .first()
    )
yesterday_unrealized = yesterday.unrealized_pnl if yesterday else 0.0
unrealized_delta = today_unrealized - yesterday_unrealized
```

### 5. Claude EOD prompt

Narrower than the morning prompt — Claude writes a journal narrative:
```
=== EOD JOURNAL REQUEST ===
Date: 2026-05-30
Realized P&L today: $+142.50
Unrealized P&L: $-320.00 (delta: -$85.00 vs yesterday)
Fills today: 2 (AAPL CC sold, SPY CSP expired worthless)
Open positions: 7
Net delta exposure: -0.34 (effectively short 34 shares)
...

Write a 3-4 sentence journal entry summarizing the day's performance,
what changed, and any notable observations for tomorrow.
Return a single JSON object: {"narrative": "<journal text>"}
```

### 6. Telegram EOD message format

```
EOD Report — 2026-05-30

Realized: +$142.50
Unrealized: -$320.00 (Δ -$85.00)
Open positions: 7 | Net delta: -0.34

Today's fills: AAPL CC sold ($1.55/sh), SPY P180 expired

Journal: [Claude's 3-4 sentence narrative]

Tomorrow's watchlist: AAPL, SPY, QQQ, NVDA
```

No Approve/Reject keyboard — purely informational.
Use `async with Bot(token=token) as bot: await bot.send_message(...)` (same pattern as `sender.py`).

### 7. `JournalRow.payload` structure

```python
payload = {
    "eod_summary": summary.model_dump(mode="json"),
    "fills": [f.id for f in today_fills],
}
```

## Testing without live TWS

Mock `get_positions`, `get_account_snapshot`, and `session_scope`. Test:
- `EODSummary` computes correct P&L from mocked fills
- Unrealized delta vs mocked yesterday JournalRow
- Claude prompt builds correctly for an `EODSummary`
- `format_eod_summary()` produces expected Telegram text
- `JournalRow` written to DB (tmp SQLite)
- Telegram message sent with correct fields

## Open decisions

- **Weekend/holiday handling:** if there are no fills and positions didn't change, should EOD still run? Recommended: yes — always write a JournalRow so the baseline for the next day is current.
- **Net delta calculation:** sum of `(pos.delta or 0) * pos.position * 100` — or fetch live Greeks from IBKR? Recommended for Phase 9: use `PositionSnapshot.delta` if available (set from portfolio Greeks); fall back to 0 if None. This avoids extra market data requests at EOD.
- **Tomorrow's watchlist:** just return `cfg.universe["watchlist"]` as-is, or run the morning scanner for a quick score? Recommended: just pass the raw watchlist to Claude for context — no scoring at EOD (keeps it fast and avoids the full pipeline overhead).
- **Client ID:** `morning_scan` and `eod_report` share clientId 11 (they never run concurrently). If you ever want to run them simultaneously, give `eod_report` its own id.
- **Claude narrative fallback:** if Claude is unavailable, write `JournalRow` with `narrative = None` and send Telegram without the journal paragraph. Never block EOD on Claude availability.
