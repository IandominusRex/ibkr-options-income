"""Centralized configuration: loads YAML config files + .env secrets.

Usage:
    from src.common.config import get_config
    cfg = get_config()
    cfg.ibkr.host
    cfg.risk.portfolio["max_risk_units_per_ticker_pct"]
    cfg.secrets.telegram_bot_token
"""

from __future__ import annotations

import functools
import logging
import os
from datetime import date
from pathlib import Path
from typing import Any, Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root = two levels up from this file (src/common/config.py -> root).
ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
EXAMPLES_DIRNAME = "examples"  # config/examples/<name>.yaml: the committed templates

# The operator's own tuning (accounts, limits, weights, universe) lives in these files, which are
# git-ignored; the repo ships a template of each under ``config/examples/`` (same file name). A
# missing private file falls back to its example (loudly), and ``IBKR_CONFIG_USE_EXAMPLES=1`` forces the examples (the test
# suite sets it, so tests never depend on one operator's settings).
PRIVATE_CONFIG_FILES = (
    "settings.yaml",
    "risk_limits.yaml",
    "scoring_weights.yaml",
    "universe.yaml",
    "spreads.yaml",
    "news.yaml",
)
USE_EXAMPLES_ENV = "IBKR_CONFIG_USE_EXAMPLES"

log = logging.getLogger(__name__)


class Secrets(BaseSettings):
    """Secrets sourced from .env / environment. Never logged, never committed."""

    model_config = SettingsConfigDict(
        env_file=str(ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    ibkr_account: str = Field(default="", alias="IBKR_ACCOUNT")
    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: str = Field(default="", alias="TELEGRAM_CHAT_ID")
    telegram_thread_scan: str = Field(default="2", alias="TELEGRAM_THREAD_SCAN")
    telegram_thread_csp: str = Field(default="52", alias="TELEGRAM_THREAD_CSP")
    telegram_thread_cc: str = Field(default="54", alias="TELEGRAM_THREAD_CC")
    telegram_thread_buy: str = Field(default="56", alias="TELEGRAM_THREAD_BUY")
    telegram_thread_account: str = Field(default="58", alias="TELEGRAM_THREAD_ACCOUNT")
    live_trading: bool = Field(default=False, alias="LIVE_TRADING")
    reddit_client_id: str = Field(default="", alias="REDDIT_CLIENT_ID")
    reddit_client_secret: str = Field(default="", alias="REDDIT_CLIENT_SECRET")
    reddit_user_agent: str = Field(default="ibkr-options-scanner/1.0", alias="REDDIT_USER_AGENT")
    web_api_token: str = Field(default="", alias="WEB_API_TOKEN")
    sec_contact_email: str = Field(default="", alias="SEC_CONTACT_EMAIL")
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    # Trade ledger (docs/superpowers/specs/2026-10-04-trade-ledger-design.md §5.2, §7).
    ibkr_flex_token: str = Field(default="", alias="IBKR_FLEX_TOKEN")
    ibkr_flex_query_id: str = Field(default="", alias="IBKR_FLEX_QUERY_ID")
    google_sheets_credentials_path: str = Field(default="", alias="GOOGLE_SHEETS_CREDENTIALS_PATH")
    ledger_sheet_id: str = Field(default="", alias="LEDGER_SHEET_ID")
    # Daily credit spreads (docs/superpowers/plans/2026-10-07-daily-credit-spreads.md).
    telegram_thread_spreads: str = Field(default="", alias="TELEGRAM_THREAD_SPREADS")
    # News thread (docs/superpowers/specs/2026-10-09-news-thread-design.md).
    telegram_thread_news: str = Field(default="", alias="TELEGRAM_THREAD_NEWS")
    finnhub_api_key: str = Field(default="", alias="FINNHUB_API_KEY")


class ReconnectCfg(BaseModel):
    max_retries: int = 5
    backoff_base_seconds: float = 2.0


class IBKRCfg(BaseModel):
    host: str = "127.0.0.1"
    paper_port: int = 7497
    live_port: int = 7496
    client_ids: dict[str, int] = Field(default_factory=dict)
    market_data_type: int = 1
    connect_timeout_seconds: float = 15.0
    reconnect: ReconnectCfg = Field(default_factory=ReconnectCfg)


class SchedulerCfg(BaseModel):
    timezone: str = "America/New_York"
    eod_report: str = "16:15"
    intraday_poll_seconds: int = 60
    intraday_loop_minutes: int = 15  # how often the intraday scan+profit-take loop fires
    profit_take_pct: float = 50.0  # close a short position once this % of premium is captured
    entry_cutoff: str = "15:00"  # no new entries surfaced/queued after this ET time
    # Hard ceiling on a single EOD run (scripts.run_eod), enforced by the scripts.start
    # supervisor loop, not by run_eod itself. A hung run (IBKR account-summary/IV requests
    # never returning) used to block every later EOD indefinitely — the launcher only spawned
    # a new one once eod_proc.poll() was not None (2026-09-29 incident: one run was still
    # alive >11h after it started). Past this many minutes the launcher SIGTERMs, then
    # SIGKILLs after STOP_GRACE_SECONDS, and a new run may be scheduled the next trading day.
    eod_timeout_minutes: int = 60

    @field_validator("eod_report", "entry_cutoff")
    @classmethod
    def _valid_hhmm(cls, v: str) -> str:
        """Fail loud at config load on a malformed HH:MM time.

        Without this, a typo like ``entry_cutoff: "3pm"`` raises ValueError deep inside
        the intraday loop's ``is_new_entry_window`` call and silently kills the task
        (SYSTEM_REVIEW F3). Catching it here turns a silent runtime death into a clear
        startup error.
        """
        parts = v.split(":")
        if len(parts) != 2:
            raise ValueError(f"time must be 'HH:MM', got {v!r}")
        try:
            h, m = int(parts[0]), int(parts[1])
        except ValueError as exc:
            raise ValueError(f"time must be 'HH:MM' with integer fields, got {v!r}") from exc
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError(f"time out of range (00:00–23:59), got {v!r}")
        return v


class MarketDataCfg(BaseModel):
    max_concurrent_lines: int = 90
    chain_batch_size: int = 40
    request_throttle_seconds: float = 0.25
    quote_sleep_seconds: float = 2.0  # wait after reqMktData(snapshot=True)
    # Per-batch ceiling on the option-chain quote wait (event-driven: a batch returns as soon as
    # every line has bid/ask + OI). Was a hard-coded 2s until 2026-10-09, when a live probe on
    # real-time data showed a 30-line batch's quotes landing at ~2.5-3s (6/30 by 2s, 30/30 by
    # 3s) — so ~94% of quotes were cancelled empty and rejected as `illiquid_no_quote`. 8s, not
    # 4s: ib_async sends at most 45 requests/s, so a later batch's 40 cancels + 40 new requests
    # push its last ticks to 4-6.4s (AMD live: 153/363 quoted at 4s, 363/363 at 8s+).
    chain_quote_ceiling_seconds: float = 8.0
    # A batch whose quotes have stopped arriving for this long (with at least one in) returns:
    # the rest are strikes with no market, and waiting out the ceiling on every such batch would
    # cost the whole ceiling per batch on illiquid symbols.
    chain_quote_settle_seconds: float = 2.5
    # Once every line in a batch has a bid/ask, wait at most this much longer for the remaining
    # open-interest ticks (tick 101). Some OI ticks never arrive (4/30 in the same probe), and
    # without this every batch would burn the full ceiling waiting for them.
    chain_oi_grace_seconds: float = 0.75
    # N6 — strike band. The chain is scanned across strikes within ±band of spot. A fixed 15%
    # band excludes the ~0.25-delta strike on high-IV names (at IV≈100%/30DTE it sits 20–30%
    # OTM), so SOXL/LABU/TSLL/MARA etc. never produced candidates. The band now scales with the
    # symbol's stored IV: band = max(strike_band_pct, strike_band_iv_mult · IV · √(DTE/365)).
    strike_band_pct: float = 0.15  # floor / fallback when IV is unknown
    strike_band_iv_mult: float = 1.5  # ≈1.5σ at the longest in-scope expiry
    # S8 — ceiling on the *IV-scaled* band. At IV≈0.8/45DTE the formula returns ±42%, which on a
    # high-IV ETF explodes the qualified-strike count → many more 40-contract batches → more fixed
    # per-batch waits. Cap the auto-computed band here (an explicit `universe.yaml → strike_bands`
    # per-symbol override is a deliberate choice and is NOT clamped).
    strike_band_max_pct: float = 0.40

    # Hard ceiling on the number of strikes kept per symbol after band-filtering. A high-IV name
    # at a wide band with dense ($2.50) strike spacing can yield 120+ in-band strikes; the full
    # cartesian (strikes × expirations × 2 rights) then becomes a several-hundred-contract
    # qualifyContractsAsync burst. Many (expiration, strike) combos don't exist for weekly
    # expirations, so that burst floods IBKR with reqContractDetails — tripping a pacing lockout
    # that wedges the session (this is exactly what hung the 2026-06-22 scan on SMH: 128 strikes
    # × 3 exp × 2 = 768 contracts). Keep only the N strikes nearest spot — that always covers the
    # in-scope deltas. 0 disables the cap.
    max_strikes_per_symbol: int = 80

    # Per-chunk timeout for chunked option-contract qualification. qualifyContractsAsync is
    # issued in `chain_batch_size` chunks paced by `request_throttle_seconds`; each chunk is
    # bounded by this so a chunk that never resolves (non-existent contracts, pacing) returns
    # whatever qualified instead of hanging the whole symbol and being killed mid-flight by the
    # outer symbol_timeout (the cancellation is what wedged the ib_async session on 2026-06-22).
    qualify_timeout_seconds: float = 20.0

    # Contract lookup cache (2026-10-10, docs/superpowers/plans/2026-10-10-contract-cache.md).
    # Every IBKR process records each option contract's conId — or "IBKR has no such contract" —
    # in one shared SQLite file and asks IBKR only for contracts it hasn't seen today. Prices are
    # never cached; only identity, which can't change before expiry.
    contract_cache_enabled: bool = True
    contract_cache_db_url: str = "sqlite:///data/contracts.db"
    # Every process qualifies contracts one chunk at a time through one shared file lock, so the
    # spreads GEX build and the wheel scan interleave chunks instead of timing each other out.
    # A chunk's qualify_timeout_seconds starts AFTER the lock is acquired. Waiting longer than
    # this proceeds unlocked (logged) — the lock can slow a scan, never stop it.
    qualify_lock_wait_seconds: float = 30.0

    # Hard ceiling on a single symbol's option-chain fetch during /scan. Without this, a
    # qualifyContractsAsync/reqMktData call that never gets a response (IBKR pacing
    # violation, competing-session lockout, or a hung TWS) stalls the whole scan
    # indefinitely — the orchestrator never reaches the next symbol or the Telegram send
    # step. On timeout the symbol is skipped (quotes=[]) and the scan continues.
    symbol_timeout_seconds: float = 90.0

    # Last-resort fallback for the spot price (only reached when the reqMktData snapshot
    # has neither a live tick nor a previous close — both NaN). ib_async's
    # reqHistoricalData defaults to a 60s timeout, which on a weekend/no-subscription
    # session was the dominant cost of /scan (~60s × every symbol). Bound it tightly here
    # since by this point we're just hoping for a cached daily bar, not a live quote.
    spot_history_timeout_seconds: float = 10.0

    # Half-dead-socket guards. When TWS loses its upstream link to IBKR (Error 1100) the
    # exec-socket handshake stays up, so ib.isConnected() returns True and cached calls
    # (account summary) still resolve — but every data-farm request silently never ticks.
    # A scan that trusts isConnected() then grinds the whole universe at
    # symbol_timeout_seconds each (~115 min for 46 symbols), monopolising the single
    # intraday loop so every later 15-min cycle is starved (observed 2026-06-24 02:00 SGT).
    #
    # health_probe_*: before each intraday scan, one snapshot quote on health_probe_symbol
    #   must return a usable tick/close within health_probe_timeout_seconds; if not, the
    #   cycle is skipped and a forced reconnect is triggered (drops the half-dead socket so
    #   AutoReconnect rebuilds it). The probe also classifies the failure from the IBKR
    #   error codes observed during its window (2026-09-09): 1100 lost-farm, 10197
    #   competing live session (reconnect won't fix — close the other login), 354/10089-91
    #   no subscription, 1101/1102 flap, or generic. That diagnosis reaches the operator
    #   messages only, never any gating.
    # max_consecutive_chain_timeouts: mid-scan circuit breaker — this many symbols timing
    #   out back-to-back aborts the run (ScanResult.aborted_unhealthy) instead of plowing
    #   through the rest. 0 disables the breaker.
    health_probe_symbol: str = "SPY"
    health_probe_timeout_seconds: float = 15.0
    max_consecutive_chain_timeouts: int = 3

    # S1 — intraday materiality gate. The 15-min loop re-runs the same scan body ~26×/session;
    # re-fetching the full universe chain (80% of wall-clock) every cycle is wasteful when only
    # held positions and materially-moved would_own names can change a decision. A would_own
    # name is re-fetched intraday only once its live spot drifts ≥ this fraction from the spot at
    # its last fetch; held names and names that cleared the score floor last cycle always fetch.
    # Manual /scan and the first-cycle forced full sweep fetch actively_wheeling ∪ held names
    # unconditionally; dip_watch names get seed-only unless they gapped ≥3% overnight (2026-08-28).
    intraday_rescan_move_pct: float = 0.005  # 0.5%
    # Safety net: force a full intraday sweep of `actively_wheeling` ∪ held names when a symbol
    # hasn't been refreshed in this many minutes, so a quiet-but-drifting name can't go stale
    # indefinitely. Checked PER SYMBOL (2026-08-27), not "the whole core sweeps together the
    # moment the single stalest one goes over the line" — that old rule let one quiet name (e.g.
    # GLD on a slow week) drag every other actively_wheeling name into a synchronized burst each
    # time. Per-symbol staleness means each name's clock runs from its own last fetch, so
    # frequently-moving and rarely-moving names desynchronize naturally — refreshes spread out
    # over time with no explicit batch/rotation schedule needed. 0 disables the periodic sweep
    # entirely (gate purely by move/held/cleared). Overridden to 120 in settings.yaml; this
    # default only matters if that key is ever removed. `dip_pull_in_pct` names are event-
    # triggered only and deliberately excluded from this timer (see below).
    force_full_scan_minutes: float = 120.0
    # Held stock positions used to be unconditionally material every intraday cycle (a CC
    # candidate refresh on every held name, every 15 min, regardless of movement) — the single
    # biggest fixed IBKR chain-fetch cost in the loop. Now gated: re-fetched intraday only once
    # the live spot has *risen* ≥ this fraction from the spot at its last fetch — directional
    # (2026-08-27), since a new CC candidate needs room to sell an OTM strike, which a drop
    # doesn't create; existing-position risk (delta drift, assignment, rolls) is handled
    # continuously by the separate event-driven monitor, not this gate. A dropping held name is
    # still caught within `force_full_scan_minutes`. A brand-new position with no baseline yet is
    # always fetched once.
    held_position_move_pct: float = 0.02  # 2%
    # `would_own` names outside `actively_wheeling` (universe.yaml) are not scanned every cycle
    # at all — they're an opportunistic CSP allowlist, not the core rotation. They're pulled
    # into a cycle's scan only when the live spot has *dropped* at least this fraction from the
    # spot at its last fetch (a rally is never a CSP entry signal, so this check is directional,
    # unlike `intraday_rescan_move_pct`). Excluded from `force_full_scan_minutes`. At startup /
    # manual /scan, the same threshold is checked bidirectionally against the persisted baseline
    # — a gap in either direction ≥3% is a legitimate CSP setup at the open; a quiet overnight
    # name gets seed-only (yfinance baseline, no chain fetch) — 2026-08-28.
    dip_pull_in_pct: float = 0.03  # 3%
    # Per-cycle wall-clock ceiling on option-chain fetching in the intraday loop (2026-08-28).
    # 0 disables it. The gate keeps a normal cycle tiny (measured: median 1 material symbol,
    # mean 3.8 over 125 real cycles), but its filtering power collapses when correlation goes to
    # 1: a broad -3% day makes every would_own name material at once, and at a measured ~37s
    # mean per fetch that is a ~28-minute sweep inside a 15-minute cycle. An overrun doesn't just
    # run long — it sets `scan_running`, so the NEXT cycle's scan is skipped entirely (profit-take
    # and loss-exit checks still run; they precede the scan in the loop). The budget converts one
    # oversized burst into consecutive full-speed cycles that each finish on time, with the
    # remainder carried forward via `ScanResult.unreached_symbols` -> next cycle's
    # `must_include_symbols`. Sized as: cycle (900s) - per-cycle fixed overhead (~120s of
    # analytics+sentiment for EVERY symbol material or not, scoring, review, Telegram) - one
    # worst-case symbol's `symbol_timeout_seconds` (150s) of overshoot, since the budget can only
    # be checked between symbols. Never applies to a manual /scan (intraday=False), which is
    # operator-initiated and expected to sweep in full. Re-derived 2026-09-30 (final review I2)
    # against the bounded review: 350 + 165 (in-flight symbol) + 45 (other fixed work) + 300
    # (review deadline + floor) = 860s < 900s — full arithmetic in config/settings.yaml.
    chain_fetch_budget_seconds: float = 350.0

    # P3-P4 M1 — minimum minutes between automatic portfolio snapshots written by the
    # intraday monitor. A `refresh` command ignores this: an operator asking for a
    # fetch gets one. The gate reads `portfolio_snapshots`' newest captured_at from the
    # DB, so a monitor restart cannot burst snapshots.
    portfolio_snapshot_interval_minutes: int = 15

    @model_validator(mode="after")
    def _enforce_line_budget(self) -> MarketDataCfg:
        """`max_concurrent_lines` is the account's ~100-line market-data cap. A single chain
        batch holds `chain_batch_size` simultaneous lines, so the batch must not exceed the cap
        (N15: previously this key was read by nothing — fail loud at config load instead)."""
        if 0 < self.chain_fetch_budget_seconds < self.symbol_timeout_seconds:
            raise ValueError(
                f"market_data.chain_fetch_budget_seconds ({self.chain_fetch_budget_seconds}) is "
                f"below symbol_timeout_seconds ({self.symbol_timeout_seconds}) — the budget must "
                "leave room for at least one worst-case symbol, or a slow first symbol would "
                "consume the whole cycle and starve every later one. Use 0 to disable it."
            )
        if self.chain_batch_size > self.max_concurrent_lines:
            raise ValueError(
                f"market_data.chain_batch_size ({self.chain_batch_size}) exceeds "
                f"max_concurrent_lines ({self.max_concurrent_lines}) — a batch can't request "
                "more simultaneous market-data lines than the account cap."
            )
        if self.strike_band_max_pct < self.strike_band_pct:
            raise ValueError(
                f"market_data.strike_band_max_pct ({self.strike_band_max_pct}) is below the "
                f"floor strike_band_pct ({self.strike_band_pct}) — the IV-scaled band cap can't "
                "be tighter than its floor."
            )
        return self


class ClaudeCfg(BaseModel):
    cli_command: str = "claude"
    timeout_seconds: float = 180.0
    max_retries: int = 1
    output_format: str = "json"
    enabled: bool = True
    # C11 — inject a per-candidate on-demand backtest (compact) into the strategist prompt so the
    # reasoning layer sees how the exact strike/DTE/delta behaved historically. OFF by default: it
    # adds a yfinance fetch per candidate at prompt-build time. Enrichment only (verdict/ranking).
    backtest_in_prompt: bool = False
    # N3 — headless-subprocess hardening. The CLI runs unattended ~26+×/day on the trading
    # machine; the fence isolates Claude's *output* from execution, but the subprocess itself
    # must be unable to use tools or touch the filesystem. These flags constrain it.
    max_turns: int = 1  # single agentic turn — no tool-use loops (0 = don't pass the flag)
    model: str = ""  # pin a model id (e.g. "claude-sonnet-4-6"); empty = CLI default
    # --effort for the CLI call (low|medium|high|xhigh|max); empty = CLI default, no flag. Bounds
    # thinking tokens — ~60% of a Sonnet 4.6 review's output when measured 2026-10-09.
    effort: Literal["", "low", "medium", "high", "xhigh", "max"] = ""
    # Space-separated tool denylist passed to --disallowedTools. Empty = don't pass the flag.
    disallowed_tools: str = "Bash Edit Write Read Glob Grep WebFetch WebSearch NotebookEdit Task"

    # --- Local-LLM (Ollama) backend ---
    # "cli": claude -p only (default). "ollama": local model only. "cli_then_ollama": try
    # claude -p first, fall back to the local Ollama model if the CLI is unavailable, times
    # out, or returns unparseable output. Same fence applies regardless of backend — Ollama
    # output goes through the same ClaudeReview/RollReview validation before it can influence
    # a verdict.
    backend: str = "cli"
    ollama_host: str = "http://localhost:11434"
    # Defaults match config/settings.yaml (final review minor, 2026-09-30) — see its comments for
    # the measurements behind each value.
    ollama_model: str = "qwen3.5:4b"
    ollama_timeout_seconds: float = 180.0
    # Context window (tokens) requested from Ollama. Must cover the *whole* prompt PLUS the
    # generated JSON, or Ollama silently left-truncates the prompt (dropping the universe context
    # + candidates at the start) and/or cuts the output mid-JSON → unparseable → dropped reviews.
    # MEASURED 2026-09-30 on the production-shaped 10-candidate prompt: 12,461 prompt tokens
    # (13,693-13,863 with the Task 11 NEWS block / research turn) + 2,222-2,630 generated.
    # 24576 leaves ~40% headroom. Larger values cost more KV-cache RAM; lower it if the model OOMs.
    ollama_num_ctx: int = 24576
    # How long Ollama keeps the model resident after a call. A scan fires several calls
    # (candidates, then per-roll intraday); without this each reload adds seconds of latency.
    ollama_keep_alive: str = "2m"
    # Sampling temperature. Low = more deterministic JSON; the review task wants discipline, not
    # creativity. Tunable for experimentation without a code change.
    ollama_temperature: float = 0.2

    # --- Task 11: keyless news search + bounded tool-calling research turn ---
    # Single switch for the whole feature (see SETUP.md "Using the Ollama backend" — set False
    # to fully revert to Task 10's single-shot behaviour with no NEWS block and no research
    # turn). When True, `ollama_runner.review_candidates` builds a static `=== NEWS ===` block
    # (`src.claude.news_context`) and runs a bounded `/api/chat` tool-calling round
    # (`src.claude.ollama_tools`) before the final structured call.
    tool_research_enabled: bool = True
    # Recent headlines per candidate symbol in the static NEWS block.
    news_per_symbol: int = 5
    # Lookback window (days) for both the static NEWS block and the research turn's searches.
    news_days: int = 7
    # Hard cap on the NEWS block's total item count, applied after cross-symbol dedupe — keeps
    # the block bounded regardless of how many candidates/symbols a scan reviews at once.
    news_max_items: int = 25
    # How many `search_news` tool calls the model may make in the bounded research turn.
    max_tool_rounds: int = 2
    # Client-side timeout for the research turn's `/api/chat` POST — separate from
    # `ollama_timeout_seconds` (the final structured call) since the tool round is a smaller,
    # faster exchange (a handful of search results, not a full multi-candidate review).
    tool_research_timeout_seconds: float = 60.0
    # Final review I2 — the review path's single shared deadline is
    # tool_research_timeout_seconds + ollama_timeout_seconds. The NEWS fetch may use only its
    # first `news_fetch_budget_seconds`; `review_min_call_seconds` is the floor below which the
    # final chat is skipped and which the single-shot fallback always gets (so the whole review
    # is bounded by the deadline + this floor). See config/settings.yaml for the sizing.
    news_fetch_budget_seconds: float = 30.0
    review_min_call_seconds: float = 60.0


class DataCfg(BaseModel):
    """Backend selection for the ``src/data/`` provider abstraction layer.

    Each key names the active backend for one of the three Protocols in
    :mod:`src.data.protocols`. Phase 2 ships only the ``yfinance`` backend; ``fmp`` is
    accepted (the stub exists in :mod:`src.data.fmp_backend`) but raises
    ``NotImplementedError`` on use, so the swap path is documented but not wired.
    """

    price_provider: str = "yfinance"
    fundamentals_provider: str = "yfinance"
    news_provider: str = "yfinance"
    # Task 11 — keyless free-text news search (vs. `news_provider`'s per-symbol headlines).
    # Backs the strategist prompt's NEWS block and the Ollama research turn's `search_news`
    # tool. Only "google_news" (src/data/google_news_backend.py) is implemented.
    news_search_provider: str = "google_news"
    symbol_directory_provider: str = "edgar"
    filings_provider: str = "edgar"
    bulk_price_provider: str = "yfinance"
    # News service sources (docs/superpowers/specs/2026-10-09-news-thread-design.md §5.1).
    econ_schedule_provider: str = "forexfactory"
    econ_actuals_provider: str = "nasdaq"
    earnings_calendar_provider: str = "nasdaq"
    intraday_price_provider: str = "yfinance"


class ResearchDatabaseCfg(BaseModel):
    url: str = "sqlite:///data/research.db"


class ResearchApiCfg(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8787
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])


class ResearchTiersCfg(BaseModel):
    materialization_budget_seconds: float = 8.0
    warm_refresh_hour_et: int = 4
    directory_refresh_days: int = 7


class EdgarProviderCfg(BaseModel):
    user_agent_product: str = "IBKR-Income-System/1.0"
    max_requests_per_second: float = 10.0
    timeout_seconds: float = 20.0


class ResearchProvidersCfg(BaseModel):
    edgar: EdgarProviderCfg = Field(default_factory=EdgarProviderCfg)


class ResearchSummaryCfg(BaseModel):
    backend: str = "claude_cli"
    model: str = "claude-sonnet-4-6"
    timeout_seconds: int = 120
    cache_ttl_hours: int = 24

    @field_validator("backend")
    @classmethod
    def _known_backend(cls, v: str) -> str:
        allowed = {"claude_cli", "anthropic", "openai", "ollama"}
        if v not in allowed:
            raise ValueError(
                f"research.summary.backend must be one of {sorted(allowed)}, got {v!r}"
            )
        return v


class ResearchCfg(BaseModel):
    database: ResearchDatabaseCfg = Field(default_factory=ResearchDatabaseCfg)
    api: ResearchApiCfg = Field(default_factory=ResearchApiCfg)
    tiers: ResearchTiersCfg = Field(default_factory=ResearchTiersCfg)
    providers: ResearchProvidersCfg = Field(default_factory=ResearchProvidersCfg)
    summary: ResearchSummaryCfg = Field(default_factory=ResearchSummaryCfg)


class StorageCfg(BaseModel):
    db_url: str = "sqlite:///data/income_system.db"
    iv_history_parquet: str = "data/iv_history.parquet"
    # P3-P4 M1 — days of intraday portfolio history kept. Pruned by the EOD run; see
    # Web plan/P3-P4-design.md §4.2: a year of intraday history needs a rollup, not a
    # longer retention here.
    portfolio_snapshot_retention_days: int = 30


class LoggingCfg(BaseModel):
    level: str = "INFO"
    file: str = "logs/system.log"


class ApprovalCfg(BaseModel):
    ttl_minutes: int = 60


class ExecutionCfg(BaseModel):
    transmit_only_in_rth: bool = True
    fill_timeout_minutes: int = 5
    poll_interval_seconds: int = 30
    quote_timeout_seconds: float = 10.0  # max wait for live bid/ask before order
    # --- Limit-order repricing (chase logic) ---
    # When an order has not filled, step its limit toward the far quote side to chase a fill
    # rather than only waiting out fill_timeout_minutes then cancelling. Default OFF — it is an
    # unverified broker-path behaviour pending live-paper validation (see STATUS.md).
    reprice_enabled: bool = False
    reprice_interval_seconds: float = 45.0  # wait between reprice steps
    max_reprices: int = 2  # number of reprice steps before giving up (then cancel on timeout)
    reprice_step_pct: float = 0.34  # fraction of the remaining distance to the bid/ask per step


class MonitorCfg(BaseModel):
    delta_ceiling: float = 0.45
    dte_threshold: int = 7
    iv_spike_pct: float = 40.0
    ex_div_days_ahead: int = 5
    # N20 — when True, a roll trigger generates a roll candidate and sends it with Approve/Reject
    # buttons (tap → QUEUED ROLL OrderRow → execute_roll), instead of an alert-only message.
    # Default False: the two-leg BAG sign convention is unverified on a live account, so rolls
    # stay alert-only until that is confirmed on paper (see STATUS.md live-verification list).
    roll_execution_enabled: bool = False
    # C4 — assignment-risk alert: fires when |delta| ≥ threshold AND DTE ≤ dte window.
    # Targets deep-ITM shorts near expiry where action (roll/close/assign) is required.
    assignment_alert_delta: float = 0.70
    assignment_alert_dte: int = 21
    # Manage mechanically at this DTE — entries are 21-45 DTE and the roll trigger fires at
    # dte_threshold (7), which is deep into gamma with no room to manoeuvre.
    manage_at_dte: int = 21
    # Defensive-roll economics. A roll that rescues a challenged short is judged on risk
    # reduction, not yield: it may cost a bounded debit and must reduce |delta| materially.
    roll_defensive: dict[str, float | bool] = Field(
        default_factory=lambda: {
            "max_debit": 0.50,
            "min_delta_reduction": 0.10,
            "require_breakeven_improvement": True,
        }
    )


class AutomationCfg(BaseModel):
    """Circuit breakers for AUTOMATED mode (SYSTEM_REVIEW Phase 2).

    These bound *activity* and *losses* — the cumulative risk gate only bounds exposure.
    The `/halt` Telegram kill switch is a separate, persisted toggle in system_settings.
    """

    # Max NEW-exposure entry orders the system may open per ET trading day (auto or manual).
    # 0 disables the cap.
    max_auto_trades_per_day: int = 10
    # Auto-trip the kill switch when today's MARK-TO-MARKET loss exceeds this % of net liq.
    # Measured from the prior position snapshot's unrealized P&L, NOT from fill cashflow —
    # an income desk always has positive cashflow on a day it sells premium, so the old
    # cashflow-based measure read a drawdown as a profit.
    daily_loss_halt_pct: float = 3.0
    # Auto-trip when net liquidation falls this % below its trailing high-water mark. Catches
    # the slow bleed that no single day trips. 0 disables.
    drawdown_halt_pct: float = 10.0
    # Buy to close when cost-to-close reaches this multiple of the entry credit. 0 disables.
    max_loss_multiple: float = 2.0
    # Risk-REDUCING actions run on this switch, independent of the autonomy level — that
    # governs opening exposure. Closing risk should never wait for a tap.
    auto_close_enabled: bool = True
    # Task 12 (scan-loop remediation) — PAPER-ONLY override of the autonomy promotion evidence
    # gate (system_settings.promotion_blockers' >=20 fills / >=60% fill rate / >=1 close
    # requirement) so the paper account can run on FULL to observe end-to-end behaviour without
    # first accumulating that history. `promotion_blockers` ignores this flag entirely — with a
    # warning — whenever `Config.is_live` is True, so it can never bypass the evidence gate on a
    # live account. Code default is False; `config/settings.yaml` sets it True for this paper
    # run. Set back to False before any live cutover (see STATUS.md "Live cutover gate").
    paper_skip_promotion_gate: bool = False


class GatewayRecoveryCfg(BaseModel):
    """Automatic IB Gateway restart on an Error 10197 competing-live-session block
    (``src/ops/gateway_control.py``). A Gateway that hit 10197 does not regain the live-data
    entitlement when the other session logs out — only a fresh login clears it (2026-10-02:
    ~16h blocked until a manual restart). Only acts when the ``com.ibkr.gateway`` launchd
    agent (IBC auto-login) is loaded; a hand-started Gateway can't log itself back in.
    """

    enabled: bool = True
    # Minimum minutes between two restarts — a session still genuinely holding the data
    # would otherwise get a restart every 15-min cycle.
    cooldown_minutes: int = 30
    # Per ET trading day. Once spent, the block message tells the operator to find the
    # other session instead of restarting again.
    max_restarts_per_day: int = 3
    # How long to wait for the old Gateway process group to exit before SIGKILL. Relaunching
    # while it is still alive trips start_gateway.sh's duplicate-instance guard, which exits
    # without starting anything (verified 2026-10-02 with `launchctl kickstart -k`).
    stop_timeout_seconds: int = 30
    # How long to wait for the relaunched Gateway's API port to accept connections.
    port_wait_seconds: int = 90


class WatchdogCfg(BaseModel):
    """Out-of-process health watchdog (``src/ops/watchdog.py``, ``scripts/watchdog.py``),
    run every ``interval_seconds`` under launchd/cron — never inside the processes it
    watches. See ``watchdog.py``'s module docstring for the outage this exists to catch.
    """

    interval_seconds: int = 300
    heartbeat_max_age_minutes: int = 10
    # Two 15-min intraday-loop cycles + slack.
    scan_max_age_minutes: int = 35
    # Ignore the first minutes after the open — the loop's first cycle hasn't landed yet.
    scan_grace_minutes: int = 20
    iv_max_stale_trading_days: int = 3
    # scheduler.eod_report + this many minutes before `eod_completed` is checked.
    eod_grace_minutes: int = 90
    # The news service (scripts/run_news.py) beats data/news.db's heartbeat every loop
    # iteration; checked only while news.enabled.
    news_max_age_minutes: int = 30
    realert_minutes: int = 60
    # Optional external dead-man switch (e.g. a healthchecks.io ping URL), GETed on every run
    # where every check passes — the only thing that can notice the Mac itself being off or
    # asleep, since no local process runs at all in that case.
    deadman_url: str = ""


class LedgerCfg(BaseModel):
    """Trade ledger tunables (docs/superpowers/specs/2026-10-04-trade-ledger-design.md §8).

    ``account`` pins the IBKR account the ledger tracks. Empty means "lock to the account of the
    first CSV/Flex import" (R8) — live fills never set the lock, so a paper session can't claim
    the ledger before the real history is imported.
    """

    account: str = ""
    live_sweep_minutes: int = 5
    sheets_min_interval_seconds: int = 60
    upload_max_bytes: int = 5_242_880
    flex_poll_timeout_seconds: float = 600.0
    flex_poll_interval_seconds: float = 10.0
    fx_max_gap_days: int = 7
    # Google Sheet tab gids the mirror writes into (role -> gid; roles: options, credit_spreads,
    # buy_and_hold, tickers, summary). With credit_spreads mapped, spreads-book legs go to that
    # tab and leave the options tab; without it they stay in options. Empty = legacy mode:
    # create/own the three "(auto)" tabs. A role left out is simply not written, so the
    # operator's other tabs are never touched.
    sheets_tabs: dict[str, int] = Field(default_factory=dict)

    @field_validator("sheets_tabs")
    @classmethod
    def _known_tab_roles(cls, v: dict[str, int]) -> dict[str, int]:
        unknown = set(v) - {"options", "credit_spreads", "buy_and_hold", "tickers", "summary"}
        if unknown:
            raise ValueError(f"unknown ledger.sheets_tabs roles: {sorted(unknown)}")
        if len(set(v.values())) != len(v):
            raise ValueError("ledger.sheets_tabs gids must be distinct")
        return v


def _hhmm(v: str) -> str:
    """Zero-padded 'HH:MM' only — the spreads schedule is compared as strings."""
    parts = v.split(":")
    if len(parts) != 2 or not all(len(p) == 2 and p.isdigit() for p in parts):
        raise ValueError(f"time must be zero-padded 'HH:MM', got {v!r}")
    h, m = int(parts[0]), int(parts[1])
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError(f"time out of range (00:00–23:59), got {v!r}")
    return v


class SpreadsScheduleCfg(BaseModel):
    map_time: str = "09:31"
    map_refresh_minutes: int = 60
    entry_start: str = "09:35"
    entry_end: str = "13:30"
    entry_check_minutes: int = 5
    manage_interval_seconds: int = 30
    force_close: str = "15:45"
    eod_summary: str = "16:10"
    skip_early_close_days: bool = True

    @field_validator("map_time", "entry_start", "entry_end", "force_close", "eod_summary")
    @classmethod
    def _valid_time(cls, v: str) -> str:
        return _hhmm(v)

    @model_validator(mode="after")
    def _ordered(self) -> SpreadsScheduleCfg:
        if not (self.map_time <= self.entry_start < self.entry_end <= self.force_close):
            raise ValueError(
                "spreads schedule must satisfy map_time <= entry_start < entry_end <= force_close"
            )
        if self.force_close >= self.eod_summary:
            raise ValueError("spreads schedule: eod_summary must be after force_close")
        return self


class SpreadsGexCfg(BaseModel):
    symbol: str = "SPX"
    sec_type: Literal["IND", "STK"] = "IND"
    trading_class: str = "SPXW"
    exchange: str = "CBOE"
    # None = the live ratio (traded spot ÷ GEX-source spot), recomputed with every map: SPY drifts
    # below SPX/10 as dividends accrue. A number pins it (0.1 for XSP, 1.0 for SPX itself).
    scale_to_underlying: float | None = None
    strike_band_pct: float = 0.03
    expiries: int = 2
    flip_search_pct: float = 0.03
    flip_buffer_pct: float = 0.002
    # Traded by default and tagged regime="negative" in the trade log (operator decision,
    # 2026-10-07: paper account, gather the data first). "skip" restores the stricter rule.
    negative_gamma_action: Literal["skip", "allow"] = "allow"


class SpreadsEntryCfg(BaseModel):
    """When, and on which side, a spread may be sold (src/spreads/tape.py::trigger)."""

    trigger: Literal["move", "always"] = "move"
    min_move_em: float = 0.5
    max_move_em: float | None = 1.5
    stall_minutes: int = 10
    max_tape_age_seconds: float = 120.0
    gap_day_pct: float = 0.003  # tag only — never gates

    @model_validator(mode="after")
    def _band(self) -> SpreadsEntryCfg:
        if self.min_move_em < 0 or self.stall_minutes < 0:
            raise ValueError("spreads entry: min_move_em and stall_minutes must be >= 0")
        if self.max_move_em is not None and self.max_move_em <= self.min_move_em:
            raise ValueError("spreads entry: max_move_em must be above min_move_em (or null)")
        return self


class SpreadsEventCfg(BaseModel):
    """A scheduled event: no new entries all ``day``, or only until ``until`` ET when it is set."""

    day: date
    until: str | None = None
    label: str = ""

    @field_validator("until")
    @classmethod
    def _valid_until(cls, v: str | None) -> str | None:
        return None if v is None else _hhmm(v)


class SpreadsSelectionCfg(BaseModel):
    sides: list[Literal["put", "call"]] = [
        "put",
        "call",
    ]  # pydantic copies list defaults per instance
    width: float = 5.0
    short_delta_max: float = 0.15
    em_multiple: float = 1.0
    em_straddle_factor: float = 1.0
    wall_buffer_pct: float = 0.001
    min_credit_pct_of_width: float = 0.05
    max_leg_spread_pct: float = 0.30
    strike_band_pct: float = 0.03


class SpreadsRiskCfg(BaseModel):
    # Sizing (Design → "Position sizing"): the book's capital is starting_capital_usd plus the
    # realized P&L of its closed spreads in the current mode, and every cap is a share of it.
    starting_capital_usd: float = 100_000.0
    max_loss_pct_of_capital: float = 0.10
    max_total_risk_pct_of_capital: float = 0.10
    max_daily_loss_pct_of_capital: float = 0.10
    max_contracts: int = 100  # sanity ceiling against a bad quote sizing to an absurd count
    max_open_spreads: int = 2
    max_trades_per_day: int = 2
    one_side_per_day: bool = True
    min_excess_liquidity_usd: float = 10_000.0
    max_quote_age_seconds: float = 20.0
    events: list[SpreadsEventCfg] = Field(default_factory=list)
    ex_dividend_dates: list[date] = Field(default_factory=list)

    @model_validator(mode="after")
    def _fractions(self) -> SpreadsRiskCfg:
        if self.starting_capital_usd <= 0:
            raise ValueError("spreads risk: starting_capital_usd must be positive")
        for name in (
            "max_loss_pct_of_capital",
            "max_total_risk_pct_of_capital",
            "max_daily_loss_pct_of_capital",
        ):
            if not 0 < getattr(self, name) <= 1:
                raise ValueError(f"spreads risk: {name} is a fraction in (0, 1], e.g. 0.10 for 10%")
        return self


class SpreadsExitsCfg(BaseModel):
    profit_take_pct: float = 50.0
    stop_debit_multiple: float = 2.0
    close_on_short_strike_touch: bool = True
    max_hold_minutes: int | None = 150
    let_expire: bool = False  # SPY settles in shares; True only for cash-settled XSP/SPX
    let_expire_max_debit: float = 0.05


class SpreadsExecutionCfg(BaseModel):
    order_ttl_seconds: float = 60.0
    reprice_steps: int = 3
    reprice_tick: float = 0.01
    close_ttl_seconds: float = 30.0
    close_max_concession: float = 0.10
    shadow_slippage_per_leg: float = 0.02
    commission_per_contract: float = 0.65


class SpreadsBacktestCfg(BaseModel):
    thetadata_url: str = "http://127.0.0.1:25503"
    cache_dir: str = "data/spreads_bt"
    option_symbol: str = "SPXW"
    index_symbol: str = "SPX"
    trade_scale: float = 10.0
    fill_haircut: float = 0.5


class SpreadsCfg(BaseModel):
    """Daily credit-spread system (config/spreads.yaml). See the plan's Design section."""

    enabled: bool = False
    mode: Literal["shadow", "paper"] = "shadow"
    underlying: str = "SPY"
    underlying_sec_type: Literal["STK", "IND"] = "STK"
    trading_class: str = "SPY"
    exchange: str = "SMART"
    book_underlyings: list[str] = [
        "SPY",
        "SPX",
        "XSP",
    ]  # pydantic copies list defaults per instance
    order_ref_prefix: str = "CS:"
    db_url: str = "sqlite:///data/spreads.db"
    max_market_data_lines: int = 30
    # Lines the wheel's IntradayMonitor keeps open (one per short option it watches) while a
    # scan batch and the spreads book are both quoting — counted against the login's cap.
    reserved_monitor_lines: int = 20
    halt_file: str = "data/spreads.halt"
    schedule: SpreadsScheduleCfg = Field(default_factory=SpreadsScheduleCfg)
    entry: SpreadsEntryCfg = Field(default_factory=SpreadsEntryCfg)
    gex: SpreadsGexCfg = Field(default_factory=SpreadsGexCfg)
    selection: SpreadsSelectionCfg = Field(default_factory=SpreadsSelectionCfg)
    risk: SpreadsRiskCfg = Field(default_factory=SpreadsRiskCfg)
    exits: SpreadsExitsCfg = Field(default_factory=SpreadsExitsCfg)
    execution: SpreadsExecutionCfg = Field(default_factory=SpreadsExecutionCfg)
    backtest: SpreadsBacktestCfg = Field(default_factory=SpreadsBacktestCfg)

    @model_validator(mode="after")
    def _underlying_in_book(self) -> SpreadsCfg:
        book = {s.upper() for s in self.book_underlyings}
        if self.underlying.upper() not in book:
            raise ValueError(
                f"spreads.underlying {self.underlying!r} must be listed in book_underlyings {sorted(book)}"
            )
        return self


NewsCategory = Literal["government", "geopolitics", "macro", "markets", "ticker"]


class NewsFeedCfg(BaseModel):
    name: str
    url: str
    category: NewsCategory


class NewsSourcesCfg(BaseModel):
    rss_feeds: list[NewsFeedCfg] = Field(default_factory=list)
    macro_queries: list[str] = Field(default_factory=list)
    google_news_days: int = 3
    rss_poll_minutes: int = 5
    macro_poll_minutes: int = 10
    ticker_round_robin_minutes: int = 30
    econ_poll_minutes: int = 60
    econ_fast_poll_seconds: int = 30
    econ_fast_window_before_min: int = 2
    econ_fast_window_after_min: int = 10
    earnings_poll_hours: int = 6
    finnhub_per_minute: int = 50
    # Probed 2026-10-09: Nasdaq's economicevents?date=D returns ET day D-1's US releases.
    # scripts/news_probe.py re-checks this; set to 0 if the probe says so.
    nasdaq_econ_date_offset_days: int = 1
    nasdaq_earnings_date_offset_days: int = 0


class NewsClusterCfg(BaseModel):
    similarity: float = 0.5
    window_hours: int = 48


class NewsTaggingCfg(BaseModel):
    rumor_terms: list[str] = Field(default_factory=list)
    forward_terms: list[str] = Field(default_factory=list)
    topic_terms: dict[str, list[str]] = Field(default_factory=dict)
    aliases: dict[str, list[str]] = Field(default_factory=dict)
    # Law-firm class-action solicitations: they name the ticker and look like stock news, but
    # carry no information about the move. Kept out of ticker cards, headlines and digests.
    noise_terms: list[str] = Field(
        default_factory=lambda: [
            "securities fraud lawsuit",
            "securities class action",
            "class action lawsuit",
            "lead plaintiff",
            "investors have opportunity to lead",
            "investors who lost",
            "shareholder alert",
            "investor alert",
            "reminds investors",
            "encourages investors",
            "deadline alert",
            "law firm",
        ]
    )


class NewsAlertsCfg(BaseModel):
    index_symbols: list[str] = Field(default_factory=lambda: ["SPY", "QQQ", "DIA"])
    index_levels_down: list[float] = Field(default_factory=lambda: [-1.0, -2.0, -3.0])
    index_levels_up: list[float] = Field(default_factory=lambda: [2.0, 3.0])
    critical_index_level: float = -2.0
    vix_jump_pct: float = 15.0
    vix_levels: list[float] = Field(default_factory=lambda: [25.0, 30.0])
    held_sigma: float = 2.0
    universe_sigma: float = 3.0
    ticker_scan_minutes: int = 5
    # A macro print whose actual first arrives more than this long after its release (the
    # service was down, or the source was late) is not alerted: a day-old print posted as news
    # reads as current and is not.
    macro_max_late_minutes: int = 180
    geo_min_sources: int = 2
    geo_reaction_pct: float = 0.5
    geo_reaction_window_min: int = 30
    geo_topics: list[str] = Field(
        default_factory=lambda: [
            "war",
            "ceasefire",
            "sanctions",
            "tariff",
            "fed",
            "fiscal",
            "energy",
        ]
    )
    max_per_hour: int = 6
    max_edits: int = 3


class NewsReactionCfg(BaseModel):
    window_min: int = 15
    max_wait_min: int = 35
    instruments_rth: dict[str, str] = Field(
        default_factory=lambda: {
            "stocks": "SPY",
            "bonds": "^TNX",
            "dollar": "UUP",
            "gold": "GLD",
            "oil": "USO",
            "vol": "^VIX",
        }
    )
    instruments_ext: dict[str, str] = Field(
        default_factory=lambda: {
            "stocks": "ES=F",
            "bonds": "ZN=F",
            "dollar": "DX-Y.NYB",
            "gold": "GC=F",
            "oil": "CL=F",
        }
    )


class NewsQuietCfg(BaseModel):
    tz: str = "Asia/Singapore"
    start: str = "00:00"
    end: str = "07:00"
    critical_breaks_quiet: bool = True

    @field_validator("start", "end")
    @classmethod
    def _valid_hhmm(cls, v: str) -> str:
        return _hhmm(v)

    @field_validator("tz")
    @classmethod
    def _valid_tz(cls, v: str) -> str:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"news.quiet_hours.tz: unknown time zone {v!r}") from exc
        return v


class NewsDigestCfg(BaseModel):
    premarket: str = "08:00"
    close: str = "16:30"
    week_ahead_weekday: int = 6  # Monday=0 … Sunday=6
    week_ahead_time: str = "18:00"
    max_threads: int = 6
    max_movers: int = 5
    # A digest whose time passed more than this long ago (the service was down) is skipped,
    # not posted late: a pre-market brief at 15:00 ET reads as current and is not.
    max_late_minutes: int = 120

    @field_validator("premarket", "close", "week_ahead_time")
    @classmethod
    def _valid_hhmm(cls, v: str) -> str:
        return _hhmm(v)


class NewsLlmCfg(BaseModel):
    backend: Literal["cli", "ollama", "cli_then_ollama"] = "cli_then_ollama"
    model: str = "claude-sonnet-5-5"
    ollama_model: str = ""  # empty = claude.ollama_model
    timeout_seconds: float = 120.0
    max_calls_per_day: int = 40


class NewsSentimentCfg(BaseModel):
    model: Literal["vader", "finbert"] = "vader"
    lookback_hours: int = 72
    half_life_hours: float = 24.0


class NewsGroundingCfg(BaseModel):
    rel_tol: float = 0.02


class NewsFlagsCfg(BaseModel):
    large_move_sigma: float = 2.0
    oversold_rsi: float = 30.0
    earnings_outsized: float = 1.5
    earnings_muted: float = 0.5
    sector_share: float = 1 / 3


class NewsBriefsCfg(BaseModel):
    poll_seconds: int = 5
    dedupe_minutes: int = 10


class NewsCfg(BaseModel):
    """News service (config/news.yaml). See docs/superpowers/specs/2026-10-09-news-thread-design.md."""

    enabled: bool = True
    db_url: str = "sqlite:///data/news.db"
    charts_dir: str = "data/news_charts"
    retention_days: int = 30
    lookback_hours: dict[str, int] = Field(
        default_factory=lambda: {
            "government": 168,
            "geopolitics": 168,
            "macro": 168,
            "markets": 36,
            "ticker": 72,
        }
    )
    source_rank: list[str] = Field(default_factory=list)
    tape_symbols_rth: list[str] = Field(
        default_factory=lambda: ["SPY", "QQQ", "DIA", "IWM", "^VIX", "^TNX", "UUP", "GLD", "USO"]
    )
    tape_symbols_ext: list[str] = Field(
        default_factory=lambda: ["ES=F", "NQ=F", "ZN=F", "DX-Y.NYB", "GC=F", "CL=F"]
    )
    sources: NewsSourcesCfg = Field(default_factory=NewsSourcesCfg)
    cluster: NewsClusterCfg = Field(default_factory=NewsClusterCfg)
    tagging: NewsTaggingCfg = Field(default_factory=NewsTaggingCfg)
    alerts: NewsAlertsCfg = Field(default_factory=NewsAlertsCfg)
    reaction: NewsReactionCfg = Field(default_factory=NewsReactionCfg)
    quiet_hours: NewsQuietCfg = Field(default_factory=NewsQuietCfg)
    digests: NewsDigestCfg = Field(default_factory=NewsDigestCfg)
    llm: NewsLlmCfg = Field(default_factory=NewsLlmCfg)
    sentiment: NewsSentimentCfg = Field(default_factory=NewsSentimentCfg)
    grounding: NewsGroundingCfg = Field(default_factory=NewsGroundingCfg)
    flags: NewsFlagsCfg = Field(default_factory=NewsFlagsCfg)
    briefs: NewsBriefsCfg = Field(default_factory=NewsBriefsCfg)


class Config(BaseModel):
    """Top-level config: settings.yaml sections + the rules/universe/weights dicts."""

    ibkr: IBKRCfg
    scheduler: SchedulerCfg
    market_data: MarketDataCfg
    claude: ClaudeCfg
    storage: StorageCfg
    logging: LoggingCfg
    approval: ApprovalCfg
    execution: ExecutionCfg
    monitor: MonitorCfg
    automation: AutomationCfg
    watchdog: WatchdogCfg
    gateway_recovery: GatewayRecoveryCfg = Field(default_factory=GatewayRecoveryCfg)
    data: DataCfg = Field(default_factory=DataCfg)
    research: ResearchCfg = Field(default_factory=ResearchCfg)
    ledger: LedgerCfg = Field(default_factory=LedgerCfg)
    spreads: SpreadsCfg = Field(default_factory=SpreadsCfg)
    news: NewsCfg = Field(default_factory=NewsCfg)
    # These three stay as plain dicts — they are tuning tables, not typed schemas,
    # so users can extend them in YAML without touching code.
    risk: dict[str, Any]
    universe: dict[str, Any]
    weights: dict[str, Any]
    secrets: Secrets

    @property
    def is_live(self) -> bool:
        return self.secrets.live_trading

    @property
    def ibkr_port(self) -> int:
        """Resolve the active port from the live/paper switch."""
        return self.ibkr.live_port if self.is_live else self.ibkr.paper_port

    def db_url_abs(self) -> str:
        """Resolve a relative sqlite path against the project root."""
        url = self.storage.db_url
        if url.startswith("sqlite:///") and not url.startswith("sqlite:////"):
            rel = url[len("sqlite:///") :]
            return f"sqlite:///{(ROOT / rel).as_posix()}"
        return url

    def research_db_url_abs(self) -> str:
        """Resolve the relative research sqlite path against the project root."""
        url = self.research.database.url
        if url.startswith("sqlite:///") and not url.startswith("sqlite:////"):
            rel = url[len("sqlite:///") :]
            return f"sqlite:///{(ROOT / rel).as_posix()}"
        return url

    def spreads_db_url_abs(self) -> str:
        """Resolve the relative spreads sqlite path against the project root."""
        url = self.spreads.db_url
        if url.startswith("sqlite:///") and not url.startswith("sqlite:////"):
            rel = url[len("sqlite:///") :]
            return f"sqlite:///{(ROOT / rel).as_posix()}"
        return url

    def news_db_url_abs(self) -> str:
        """Resolve the relative news sqlite path against the project root."""
        url = self.news.db_url
        if url.startswith("sqlite:///") and not url.startswith("sqlite:////"):
            rel = url[len("sqlite:///") :]
            return f"sqlite:///{(ROOT / rel).as_posix()}"
        return url

    def contract_cache_url_abs(self) -> str:
        """Resolve the relative contract-cache sqlite path against the project root."""
        url = self.market_data.contract_cache_db_url
        if url.startswith("sqlite:///") and not url.startswith("sqlite:////"):
            rel = url[len("sqlite:///") :]
            return f"sqlite:///{(ROOT / rel).as_posix()}"
        return url

    def spreads_halt_path(self) -> Path:
        return ROOT / self.spreads.halt_file

    @model_validator(mode="after")
    def _spreads_isolated(self) -> Config:
        """The wheel and the spreads book may never share an underlying or overrun the line cap.

        Book membership is decided by underlying alone (positions carry no order tag; IBKR nets
        same-contract positions across clientIds), so an overlap here would silently merge the
        two books. Checked on every load, enabled or not.
        """
        book = {s.upper() for s in self.spreads.book_underlyings}
        wheel = {
            str(sym).upper()
            for value in self.universe.values()
            if isinstance(value, list)
            for sym in value
        }
        clash = sorted(book & wheel)
        if clash:
            raise ValueError(
                f"spreads.book_underlyings {clash} also appear in config/universe.yaml — the "
                "wheel and the spreads book may never share an underlying"
            )
        if self.spreads.enabled:
            budget = (
                self.market_data.chain_batch_size
                + self.spreads.max_market_data_lines
                + self.spreads.reserved_monitor_lines
            )
            cap = self.market_data.max_concurrent_lines
            if budget > cap:
                raise ValueError(
                    f"market_data.chain_batch_size + spreads.max_market_data_lines + "
                    f"spreads.reserved_monitor_lines = {budget} exceeds "
                    f"market_data.max_concurrent_lines ({cap}), the market-data budget shared "
                    "by every clientId on the login"
                )
            if "spreads" not in self.ibkr.client_ids:
                raise ValueError("ibkr.client_ids.spreads must be set when spreads.enabled is true")
        return self


def example_path(name: str) -> Path:
    """``config/settings.yaml`` → ``config/examples/settings.yaml``."""
    return CONFIG_DIR / EXAMPLES_DIRNAME / name


def config_path(name: str) -> Path:
    """The file ``name`` is read from: the private copy, else its committed example."""
    path = CONFIG_DIR / name
    if name not in PRIVATE_CONFIG_FILES:
        return path
    example = example_path(name)
    if os.environ.get(USE_EXAMPLES_ENV) == "1":
        return example
    if path.exists() or not example.exists():
        return path
    log.warning(
        "config/%s not found; using the shipped defaults in config/%s/%s. Copy it to config/%s "
        "to keep your own settings (see SETUP.md §2).",
        name,
        EXAMPLES_DIRNAME,
        name,
        name,
    )
    return example


def _load_yaml(name: str) -> dict[str, Any]:
    path = config_path(name)
    if not path.exists():
        raise FileNotFoundError(f"Missing config file: {path}")
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


@functools.lru_cache(maxsize=1)
def get_config() -> Config:
    """Load and cache the full configuration. Call once; reused thereafter."""
    load_dotenv(ROOT / ".env", override=False)
    settings = _load_yaml("settings.yaml")
    return Config(
        ibkr=IBKRCfg(**settings.get("ibkr", {})),
        scheduler=SchedulerCfg(**settings.get("scheduler", {})),
        market_data=MarketDataCfg(**settings.get("market_data", {})),
        claude=ClaudeCfg(**settings.get("claude", {})),
        storage=StorageCfg(**settings.get("storage", {})),
        logging=LoggingCfg(**settings.get("logging", {})),
        approval=ApprovalCfg(**settings.get("approval", {})),
        execution=ExecutionCfg(**settings.get("execution", {})),
        monitor=MonitorCfg(**settings.get("monitor", {})),
        automation=AutomationCfg(**settings.get("automation", {})),
        watchdog=WatchdogCfg(**settings.get("watchdog", {})),
        gateway_recovery=GatewayRecoveryCfg(**settings.get("gateway_recovery", {})),
        data=DataCfg(**settings.get("data", {})),
        research=ResearchCfg(**_load_yaml("research.yaml")),
        ledger=LedgerCfg(**settings.get("ledger", {})),
        spreads=SpreadsCfg(**_load_yaml("spreads.yaml")),
        news=NewsCfg(**_load_yaml("news.yaml")),
        risk=_load_yaml("risk_limits.yaml"),
        universe=_load_yaml("universe.yaml"),
        weights=_load_yaml("scoring_weights.yaml"),
        secrets=Secrets(),
    )
