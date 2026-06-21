"""Centralized configuration: loads YAML config files + .env secrets.

Usage:
    from src.common.config import get_config
    cfg = get_config()
    cfg.ibkr.host
    cfg.risk.portfolio["max_pct_per_ticker"]
    cfg.secrets.telegram_bot_token
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root = two levels up from this file (src/common/config.py -> root).
ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"


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

    # S1 — intraday materiality gate. The 15-min loop re-runs the same scan body ~26×/session;
    # re-fetching the full universe chain (80% of wall-clock) every cycle is wasteful when only
    # held positions and materially-moved would_own names can change a decision. A would_own
    # name is re-fetched intraday only once its live spot drifts ≥ this fraction from the spot at
    # its last fetch; held names and names that cleared the score floor last cycle always fetch.
    # Manual /scan ignores this gate and always sweeps the full universe.
    intraday_rescan_move_pct: float = 0.005  # 0.5%
    # Safety net: force a full intraday sweep when the oldest fetched symbol hasn't been
    # refreshed in this many minutes, so a quiet-but-drifting name can't go stale indefinitely.
    # 0 disables the periodic full sweep (gate purely by move/held/cleared).
    force_full_scan_minutes: float = 90.0

    @model_validator(mode="after")
    def _enforce_line_budget(self) -> MarketDataCfg:
        """`max_concurrent_lines` is the account's ~100-line market-data cap. A single chain
        batch holds `chain_batch_size` simultaneous lines, so the batch must not exceed the cap
        (N15: previously this key was read by nothing — fail loud at config load instead)."""
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
    # Inject human-promoted reasoning skills into the strategist/roll prompts. Skills shape
    # verdict + ranking only — never gates, weights, or sizing (see CLAUDE.md "the fence").
    skills_enabled: bool = True
    # N3 — headless-subprocess hardening. The CLI runs unattended ~26+×/day on the trading
    # machine; the fence isolates Claude's *output* from execution, but the subprocess itself
    # must be unable to use tools or touch the filesystem. These flags constrain it.
    max_turns: int = 1  # single agentic turn — no tool-use loops (0 = don't pass the flag)
    model: str = ""  # pin a model id (e.g. "claude-sonnet-4-6"); empty = CLI default
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
    ollama_model: str = "qwen3:14b"
    ollama_timeout_seconds: float = 120.0


class StorageCfg(BaseModel):
    db_url: str = "sqlite:///data/income_system.db"
    iv_history_parquet: str = "data/iv_history.parquet"


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
    alert_cooldown_minutes: int = 30
    # N20 — when True, a roll trigger generates a roll candidate and sends it with Approve/Reject
    # buttons (tap → QUEUED ROLL OrderRow → execute_roll), instead of an alert-only message.
    # Default False: the two-leg BAG sign convention is unverified on a live account, so rolls
    # stay alert-only until that is confirmed on paper (see STATUS.md live-verification list).
    roll_execution_enabled: bool = False
    # C4 — assignment-risk alert: fires when |delta| ≥ threshold AND DTE ≤ dte window.
    # Targets deep-ITM shorts near expiry where action (roll/close/assign) is required.
    assignment_alert_delta: float = 0.70
    assignment_alert_dte: int = 21


class AutomationCfg(BaseModel):
    """Circuit breakers for AUTOMATED mode (SYSTEM_REVIEW Phase 2).

    These bound *activity* and *losses* — the cumulative risk gate only bounds exposure.
    The `/halt` Telegram kill switch is a separate, persisted toggle in system_settings.
    """

    # Max NEW-exposure entry orders the system may open per ET trading day (auto or manual).
    # 0 disables the cap.
    max_auto_trades_per_day: int = 10
    # Auto-trip the kill switch when today's net realized cashflow is a loss exceeding this
    # fraction of net liquidation. 0 disables. NOTE: for an income desk this is a conservative
    # proxy — it sums signed FillRows (credits − debits) for the day, so it trips on net debit
    # days (large buy-to-close losses), not full mark-to-market P&L.
    daily_loss_halt_pct: float = 5.0


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


def _load_yaml(name: str) -> dict[str, Any]:
    path = CONFIG_DIR / name
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
        risk=_load_yaml("risk_limits.yaml"),
        universe=_load_yaml("universe.yaml"),
        weights=_load_yaml("scoring_weights.yaml"),
        secrets=Secrets(),
    )
