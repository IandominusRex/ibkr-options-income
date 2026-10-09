"""config/examples/news.yaml loads into NewsCfg and its validators bite."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.common.config import NewsCfg, NewsDigestCfg, NewsQuietCfg, get_config


def test_example_config_loads_with_spec_defaults() -> None:
    cfg = get_config().news
    assert cfg.enabled is True
    assert cfg.llm.backend == "cli_then_ollama"
    assert cfg.llm.model == "claude-sonnet-5-5"
    assert cfg.llm.max_calls_per_day == 40
    assert cfg.quiet_hours.tz == "Asia/Singapore"
    assert (cfg.quiet_hours.start, cfg.quiet_hours.end) == ("00:00", "07:00")
    assert cfg.digests.premarket == "08:00" and cfg.digests.close == "16:30"
    assert cfg.alerts.held_sigma == 2.0 and cfg.alerts.universe_sigma == 3.0
    assert cfg.reaction.window_min == 15 and cfg.reaction.max_wait_min == 35
    assert cfg.sentiment.model == "vader"
    assert any(f.category == "government" for f in cfg.sources.rss_feeds)
    assert get_config().news_db_url_abs().endswith("data/news.db")


def test_bad_time_and_tz_are_refused() -> None:
    with pytest.raises(ValidationError):
        NewsDigestCfg(premarket="8:00")
    with pytest.raises(ValidationError):
        NewsQuietCfg(tz="Mars/Olympus")


def test_unknown_llm_backend_is_refused() -> None:
    with pytest.raises(ValidationError):
        NewsCfg.model_validate({"llm": {"backend": "gpt"}})


def test_new_secrets_and_data_keys_have_defaults() -> None:
    cfg = get_config()
    assert isinstance(cfg.secrets.telegram_thread_news, str)
    assert isinstance(cfg.secrets.finnhub_api_key, str)
    assert cfg.data.econ_schedule_provider == "forexfactory"
    assert cfg.data.econ_actuals_provider == "nasdaq"
    assert cfg.data.earnings_calendar_provider == "nasdaq"
    assert cfg.data.intraday_price_provider == "yfinance"
