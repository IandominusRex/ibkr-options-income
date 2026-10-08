"""The spreads fence: src/spreads/ is a second system beside the wheel, not a wheel module.

Same globbing rule as tests/test_web_fence.py — a hand-kept list goes stale the moment a module
is added, and a fence that silently stops covering new code is worse than none.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from src.common.config import get_config

ROOT = Path(__file__).resolve().parents[1]
SPREADS = sorted((ROOT / "src" / "spreads").rglob("*.py"))

FORBIDDEN_FOR_SPREADS = (
    "src.claude",
    "src.engine",
    "src.execution",
    "src.strategies",
    "src.orchestrator",
    "src.monitor",
    "src.notify",
    "src.reporting",
    "src.api",
    "src.research",
)
WHEEL_DIRS = (
    "engine",
    "execution",
    "strategies",
    "orchestrator",
    "monitor",
    "notify",
    "ledger",
    "reporting",
    "api",
)


def _imports(text: str, module: str) -> bool:
    return f"from {module}" in text or f"import {module}" in text


def test_spreads_package_exists() -> None:
    assert len(SPREADS) >= 10, "fence must cover the spreads package"


def test_spreads_imports_none_of_the_wheel_layers() -> None:
    offenders = [
        f"{p.relative_to(ROOT)} → {m}"
        for p in SPREADS
        for m in FORBIDDEN_FOR_SPREADS
        if _imports(p.read_text(encoding="utf-8"), m)
    ]
    assert offenders == []


def test_only_the_service_reaches_the_ledger_or_the_trading_db() -> None:
    offenders = [
        str(p.relative_to(ROOT))
        for p in SPREADS
        if p.name != "service.py"
        and any(_imports(p.read_text(encoding="utf-8"), m) for m in ("src.ledger", "src.storage"))
    ]
    assert offenders == []


def test_no_wheel_layer_imports_spreads() -> None:
    offenders = [
        str(p.relative_to(ROOT))
        for d in WHEEL_DIRS
        for p in sorted((ROOT / "src" / d).rglob("*.py"))
        if "src.spreads" in p.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_spreads_never_calls_reqmktdata_directly_or_sends_market_orders() -> None:
    for p in SPREADS:
        text = p.read_text(encoding="utf-8")
        assert ".reqMktData(" not in text, f"{p.relative_to(ROOT)}: use req_fresh_mkt_data"
        assert "MarketOrder" not in text, f"{p.relative_to(ROOT)}: LimitOrder only"


def test_spreads_runtime_files_are_gitignored() -> None:
    """The ThetaData cache is licensed market data and the CSV exports are the account's trade
    log; the halt file is a runtime switch. None of them may ever be picked up by ``git add``."""
    spreads = get_config().spreads
    paths = [
        f"{spreads.backtest.cache_dir}/0123456789abcdef.csv",
        spreads.halt_file,
        "data/spreads_trades.csv",  # the paths SETUP.md §16 and the report script's docstring use
        "data/spreads_paper_trades.csv",
        "data/spreads_bt/june.csv",
    ]
    for rel in paths:
        ignored = subprocess.run(["git", "check-ignore", "-q", rel], cwd=ROOT, check=False)
        assert ignored.returncode == 0, f"{rel} must be git-ignored"


def test_spreads_store_has_its_own_declarative_base() -> None:
    assert "src.storage.models" not in (ROOT / "src" / "spreads" / "store.py").read_text(
        encoding="utf-8"
    )
