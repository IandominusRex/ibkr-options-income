# Phase 12 Handoff — Sentiment Scoring (Optional) + Hardening

> Read this first, then `PLAN.md` (Phase 11 entry) and `CLAUDE.md`.

## Where things stand (end of Phase 11)

**Phases 0–11 are complete and verified** (310/310 tests pass, `ruff` clean, `mypy` clean on Phase 11 code; two pre-existing `union-attr` errors in `src/analytics/technicals.py` are not from Phase 11).

### What Phase 11 delivered

| File | What changed |
|---|---|
| `src/execution/executor.py` | Live confirmation gate: when `cfg.is_live`, sends a `[CONFIRM LIVE]` Telegram button before `ib.placeOrder`. Times out after `execution.fill_timeout_minutes` and cancels the order if not confirmed. Exposes `register_live_confirm` / `resolve_live_confirm` for the callback handler. |
| `src/notify/approval_service.py` | `handle_live_confirm` callback handler for `confirm_live:{order_id}` button presses. Both handlers now registered with PTB patterns so callbacks are routed cleanly. |
| `src/orchestrator/morning_scan.py` | `_log_startup_banner(cfg)` function + call at `_run()` start. `dry_run: bool = False` parameter on `_run()` and `main()` — skips `send_candidates` when True. |
| `src/orchestrator/eod_report.py` | Same startup banner pattern added to `run()`. |
| `scripts/run_morning.py` | `argparse --dry-run` flag wired to `main(dry_run=...)`. |
| `tests/test_live_cutover.py` | 13 new tests: port switch, startup banner, dry-run behavior, live confirmation timeout and resolve. |

## Switching to live trading

```bash
# 1. Start TWS/IB Gateway on the LIVE port (7496)
# 2. Enable API access in TWS (same steps as paper)
# 3. Flip the flag:
echo "LIVE_TRADING=true" >> .env
# 4. Verify config is right (no TWS needed for this):
python3 -c "from src.common.config import get_config; c=get_config(); print(c.ibkr_port, c.is_live)"
# 5. Run a dry-run to verify the pipeline without placing orders:
python -m scripts.run_morning --dry-run
# 6. When ready, run normally — the approval_service will prompt for [CONFIRM LIVE]
```

The live confirmation flow for each approved order:
1. `approval_service` polls DB, finds QUEUED order, re-validates against Rules Engine + live quote
2. Calls `execute_candidate(ib, bot, chat_id, order_id, candidate)`
3. `executor` sends `[CONFIRM LIVE]` button to Telegram
4. You tap the button within `execution.fill_timeout_minutes` (default 5 min)
5. `handle_live_confirm` in approval_service resolves the asyncio.Event
6. `executor` proceeds to `ib.placeOrder`
7. Fill confirmation is sent back to Telegram

If you do not confirm within the timeout, the order is cancelled and an alert is sent.

## Phase 12 goal (optional — sentiment scoring)

> Implement `src/analytics/sentiment.py`: fetch Reddit (`r/options`, `r/wallstreetbets`) mentions of universe symbols via `praw` and normalize to a 0-100 score (50 = neutral, >70 = positive, <30 = negative). Wire into `morning_scan.py` alongside existing scoring and add `sentiment` weight to `config/scoring_weights.yaml` (suggest 0.05).
>
> **`pytest` green, `mypy` clean, `ruff` clean.**

## Files to create / modify

```
src/analytics/sentiment.py          # praw fetcher → per-symbol score
config/scoring_weights.yaml         # add sentiment weight (0.05)
src/engine/scoring.py               # include sentiment_score in normalization
src/common/schemas.py               # add sentiment_score field to ScoreCard
src/orchestrator/morning_scan.py    # call sentiment scorer alongside IV/technical
tests/test_sentiment.py             # mock HTTP; edge cases
```

## Implementation notes

### 1. praw setup

`praw` requires Reddit app credentials (`REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USER_AGENT`). Add to `.env` and `Secrets` model. If credentials are missing, `sentiment.py` should return a neutral score (50) so the pipeline degrades gracefully.

### 2. Score normalization

Collect mention count + upvote ratio from the last 24h posts mentioning the symbol. Normalize:
- 0 mentions → 50 (neutral)
- > threshold positive sentiment → scale toward 100
- Negative sentiment or put-heavy discussion → scale toward 0

Keep it simple: `score = 50 + clamp(mention_count * avg_upvote_ratio, -50, 50)` is a reasonable starting formula. Tune the scaling constant in `scoring_weights.yaml`.

### 3. Schema change

Add `sentiment_score: float | None = None` to `ScoreCard` in `schemas.py`. `None` means sentiment was not computed (graceful degradation).

### 4. Avoid rate-limit issues

Reddit's rate limit for free tier is ~60 req/min. Cache results per symbol per run (don't re-fetch if already computed). Mock the `praw.Reddit` client in tests.

### 5. Config keys to add

| Key | Where | Purpose |
|---|---|---|
| `REDDIT_CLIENT_ID` | `.env` | praw app client id |
| `REDDIT_CLIENT_SECRET` | `.env` | praw app client secret |
| `REDDIT_USER_AGENT` | `.env` | praw user agent string |
| `sentiment` weight | `scoring_weights.yaml` | weight in covered_call + cash_secured_put blocks |

## Other hardening work (post-Phase 11)

- **End-to-end paper cycle**: run ≥5 full paper cycles (morning scan → Telegram approval → fill confirmation) before flipping `LIVE_TRADING=true`.
- **Cron setup**: add `run_morning.py`, `run_eod.py`, and `run_approval_service.py` to system crontab. `run_approval_service.py` should be a daemon (run via `supervisord` or `launchd`).
- **Alert de-duplication for live confirm**: currently each live-mode order spawns a fresh `[CONFIRM LIVE]` button; if `execute_candidate` is called concurrently for multiple orders (unusual but possible), multiple buttons will appear. The current design handles this correctly (each order_id maps to its own event), but the UX may be confusing. Consider batching live confirmations if >1 order fires at once.

## Open decisions

- **Sentiment source**: `praw` (Reddit) is the recommendation. A free news API (NewsAPI) is an alternative but requires a separate API key and may have stricter rate limits.
- **Sentiment weight**: 0.05 is conservative. After running with it for a few weeks, review whether it improves or degrades fill quality before raising it.
- **`--dry-run` scope**: currently skips `send_candidates` entirely. Consider whether to write candidate/score rows to DB anyway for dashboard inspection (useful for QA); this would require a refactor of morning_scan to separate the DB write from the Telegram send.
