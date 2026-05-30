# Phase 11 Handoff — Live Cutover + Optional Sentiment

> Read this first, then `PLAN.md` (Phase 11 entry) and `CLAUDE.md`.

## Where things stand (end of Phase 10)

**Phases 0–10 are complete and verified** (297/297 tests pass, `ruff` clean, `mypy` clean on Phase 10 code; two pre-existing `union-attr` errors in `src/analytics/technicals.py` are not from Phase 10).

What now exists and Phase 11 can **reuse, not rebuild**:

| File | What it gives you |
|---|---|
| `dashboard/app.py` + `dashboard/pages/` | Streamlit dashboard: portfolio, candidates, orders, journal, IV conditions |
| `dashboard/data.py` | Pure DB-access helpers: `get_portfolio_summary`, `get_candidates`, `get_orders_pipeline`, `get_journal_feed`, `get_iv_history_by_symbol`, `compute_iv_rank_table` |
| `.streamlit/config.toml` | Dark theme — green primary, dark background |
| `src/engine/risk_engine.py` | Deterministic rules gate — runs twice per order (decision time + send time) |
| `src/engines/execution/executor.py` | Paper execution engine — needs port/flag swap for live |
| `src/ibkr/connection.py` | Connection manager: reads `ibkr_port` from config, prints loud mode banner |
| `src/common/config.py` → `Config.ibkr_port` | Returns `live_port` when `LIVE_TRADING=true` in `.env` |
| `config/settings.yaml` → `ibkr.live_port = 7496` | Live TWS/Gateway port (paper = 7497) |

## Phase 11 goal (acceptance criterion)

> Setting `LIVE_TRADING=true` in `.env` and pointing TWS/Gateway to port 7496 causes the full pipeline (morning scan → approval → execution) to route to the live IBKR account, with the same risk-engine guardrails, a loud startup banner, and an extra Telegram confirmation step before any live order is transmitted.
>
> **`pytest` green, `mypy` clean, `ruff` clean.**

## Files to create / modify

```
src/engines/execution/executor.py   # add extra live confirmation check before transmit
src/orchestrator/morning_scan.py    # print LIVE/PAPER mode banner at startup
scripts/run_morning.py              # add --dry-run flag that suppresses execution
config/settings.yaml                # (already has ibkr.live_port = 7496)
tests/test_live_cutover.py          # verify mode-flag logic without live TWS
```

Optional (sentiment):
```
src/analytics/sentiment.py          # Reddit/news headline fetcher → 0-100 score
config/scoring_weights.yaml         # add "sentiment" weight (suggest 0.05–0.10)
tests/test_sentiment.py
```

## Implementation notes

### 1. Live mode flag chain

The single source of truth is `LIVE_TRADING=true` in `.env`. The config already resolves it:

```python
# src/common/config.py
@property
def ibkr_port(self) -> int:
    return self.ibkr.live_port if self.is_live else self.ibkr.paper_port
```

The connection manager already uses `cfg.ibkr_port`. So flipping the env flag automatically reroutes connections. **Do not add a second flag or a code-level toggle** — the env var is the gating mechanism.

### 2. Extra confirmation before live order transmission

Before calling `ib.placeOrder(contract, order)` in `executor.py`, when `cfg.is_live` is `True`:

1. Re-run the rules engine against a fresh live quote (already done — keep it).
2. Send a Telegram message with order details + `[CONFIRM LIVE]` button.
3. Wait up to `execution.fill_timeout_minutes` for a Telegram `CONFIRMED` callback.
4. If no confirmation arrives, cancel the order and send a timeout alert.

This prevents stale approvals from auto-executing live without a second human touch. Use the existing `ApprovalRow`/Telegram patterns from Phase 6 — this is a second approval step, not a new system.

### 3. Startup banner

In `morning_scan.py` (and `run_eod.py`, `run_monitor.py`) add a prominent banner at the top of `main()`:

```python
cfg = get_config()
mode = "*** LIVE TRADING ***" if cfg.is_live else "paper"
logger.warning("=" * 60)
logger.warning("  MODE: %s", mode)
logger.warning("  Account: %s  Port: %d", cfg.secrets.ibkr_account, cfg.ibkr_port)
logger.warning("=" * 60)
```

The connection manager already prints one — keep both. The redundancy is intentional.

### 4. --dry-run flag

Add `--dry-run` to `scripts/run_morning.py` (argparse). When set, the pipeline runs through risk/scoring/Claude but skips `approval_service` enqueueing and execution. Useful for verifying live-mode config without touching orders.

### 5. Optional sentiment scoring

If implementing Reddit/news sentiment:

- `src/analytics/sentiment.py`: scrape `praw` (Reddit) or a free news API for mentions of universe symbols. Return a normalized 0-100 score (50 = neutral, >70 = positive buzz, <30 = negative buzz).
- Add `sentiment_weight` to `config/scoring_weights.yaml` (suggest 0.05 — keep it low; sentiment is noisy).
- Wire into `orchestrator/morning_scan.py` alongside IV/technical/fundamental scoring.
- Mock the HTTP layer in tests (no real API calls in CI).

### 6. Config keys to read

| Key | Where | Purpose |
|---|---|---|
| `LIVE_TRADING` | `.env` | Master live/paper switch |
| `ibkr.live_port` | `settings.yaml` | TWS live port (7496) |
| `ibkr.paper_port` | `settings.yaml` | TWS paper port (7497) |
| `execution.fill_timeout_minutes` | `settings.yaml` | Live confirmation timeout |
| `ibkr.client_ids.engine` | `settings.yaml` | Engine clientId (must not conflict) |

### 7. Async/sync boundary

The extra live-confirmation step in `executor.py` must stay async (it awaits a Telegram callback). The existing `approval_service.py` pattern (polling `ApprovalRow.status`) is the right model. Don't block the event loop with `time.sleep`.

## Testing approach

- Test `Config.ibkr_port` returns correct port for each `is_live` value (no TWS needed — monkeypatch `Secrets`).
- Test the startup-banner function emits the right mode string.
- Test `--dry-run` flag skips execution by checking no `ApprovalRow` is written.
- Test live-confirmation timeout: monkeypatch the Telegram send, advance time past `fill_timeout_minutes`, verify order is not placed.
- For sentiment (optional): mock HTTP responses, verify score normalization edge cases (empty response, rate-limit 429, missing symbol).

## Open decisions

- **Extra live confirmation UX:** Inline Telegram button vs. reply-with-"CONFIRM" vs. typed command. Inline button (current pattern from Phase 6) is recommended — already implemented, least friction.
- **Sentiment source:** Reddit `r/wallstreetbets` + `r/options` via `praw` (free, requires app credentials) vs. a news headline API (NewsAPI free tier). Start with Reddit; it's the higher-signal source for individual equity options.
- **Sentiment weight:** 0.05 is a safe starting point. Monitor whether it improves or degrades fill quality before raising it.
- **Dry-run scope:** Should `--dry-run` still write candidates/scores to DB (for dashboard inspection) but skip execution? Recommended: yes — write everything up to `approvals`, skip execution and Telegram approval prompts.
