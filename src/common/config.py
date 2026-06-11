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
from pydantic import BaseModel, Field
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
    telegram_thread_id: str = Field(default="", alias="TELEGRAM_THREAD_ID")
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
    morning_scan: str = "09:45"
    eod_report: str = "16:15"
    intraday_poll_seconds: int = 60
    intraday_loop_minutes: int = 15  # how often the intraday scan+profit-take loop fires
    profit_take_pct: float = 50.0   # close a short position once this % of premium is captured


class MarketDataCfg(BaseModel):
    max_concurrent_lines: int = 90
    chain_batch_size: int = 40
    request_throttle_seconds: float = 0.25
    quote_sleep_seconds: float = 2.0  # wait after reqMktData(snapshot=True)


class ClaudeCfg(BaseModel):
    cli_command: str = "claude"
    timeout_seconds: float = 180.0
    max_retries: int = 1
    output_format: str = "json"
    enabled: bool = True
    # Inject human-promoted reasoning skills into the strategist/roll prompts. Skills shape
    # verdict + ranking only — never gates, weights, or sizing (see CLAUDE.md "the fence").
    skills_enabled: bool = True


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


class MonitorCfg(BaseModel):
    delta_ceiling: float = 0.45
    dte_threshold: int = 7
    iv_spike_pct: float = 40.0
    ex_div_days_ahead: int = 5
    alert_cooldown_minutes: int = 30


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
        risk=_load_yaml("risk_limits.yaml"),
        universe=_load_yaml("universe.yaml"),
        weights=_load_yaml("scoring_weights.yaml"),
        secrets=Secrets(),
    )
