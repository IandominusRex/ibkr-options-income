"""Research/API configuration loads with the documented defaults."""

from __future__ import annotations

from src.common.config import ROOT, get_config


def test_research_config_loads() -> None:
    cfg = get_config()
    assert cfg.research.database.url == "sqlite:///data/research.db"
    assert cfg.research.api.port == 8787
    assert cfg.research.tiers.materialization_budget_seconds == 8.0
    assert cfg.research.providers.edgar.max_requests_per_second == 10.0
    assert cfg.research.summary.backend == "claude_cli"


def test_research_db_url_resolves_against_project_root() -> None:
    cfg = get_config()
    resolved = cfg.research_db_url_abs()
    assert resolved.startswith("sqlite:///")
    assert resolved.endswith("/data/research.db")
    assert (ROOT / "data").as_posix() in resolved
