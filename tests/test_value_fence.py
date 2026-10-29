"""The value fence (value book spec §16): src/value/ is deterministic and its own system.

Imports are parsed with ``ast`` (tests/test_spreads_fence.py's parser), so ``from src import x``,
relative imports and ``importlib`` count.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

from tests.test_spreads_fence import _reaches, imported_modules

ROOT = Path(__file__).resolve().parents[1]
VALUE = sorted((ROOT / "src" / "value").rglob("*.py"))
# The pure modules: no I/O, so the API may compute a ticker file during a request (spec §6.9).
PURE = (
    "schemas",
    "metrics",
    "scores",
    "gates",
    "valuation",
    "timing",
    "scorecard",
    "rank",
    "funnel",
    "ruleset",
)

FORBIDDEN_FOR_VALUE = (
    "src.claude",
    "src.news",
    "src.value_ai",
    "src.spreads",
    "src.spreads_ai",
    "src.notify",
    "src.api",
    "src.engine",
    "src.execution",
    "src.strategies",
    "src.orchestrator",
    "src.monitor",
    "src.ledger",
    "src.reporting",
    "src.analytics.sentiment",
    "src.analytics.sector_context",
    "src.analytics.market_conditions",
)
RESEARCH_ALLOWED = ("src.research.ingest.concepts", "src.research.schemas")
ENRICHMENT = (
    "src.claude",
    "src.news",
    "src.value_ai",
    "src.spreads_ai",
    "src.analytics.sentiment",
    "src.analytics.sector_context",
    "src.analytics.market_conditions",
)


def test_the_value_package_exists() -> None:
    assert len(VALUE) >= 12, "the fence must cover the value package"


def test_value_imports_no_enrichment_and_no_other_system() -> None:
    offenders = [
        f"{p.relative_to(ROOT)} -> {m}"
        for p in VALUE
        for m in FORBIDDEN_FOR_VALUE
        if _reaches(imported_modules(p), m)
    ]
    assert offenders == []


def test_value_reads_research_only_through_concepts_and_schemas() -> None:
    offenders = []
    for p in VALUE:
        for m in imported_modules(p):
            if (m == "src.research" or m.startswith("src.research.")) and not any(
                m == ok or m.startswith(ok + ".") for ok in RESEARCH_ALLOWED
            ):
                offenders.append(f"{p.relative_to(ROOT)} -> {m}")
    assert offenders == []


def test_the_pure_modules_do_no_io() -> None:
    io_modules = (
        "sqlalchemy",
        "httpx",
        "requests",
        "yfinance",
        "src.data",
        "src.storage",
        "src.common.value_inputs",
        "src.value.store",
        "src.value.ticker_file",
    )
    offenders = []
    for name in PURE:
        p = ROOT / "src" / "value" / f"{name}.py"
        mods = imported_modules(p)
        offenders += [f"{name} -> {m}" for m in io_modules if _reaches(mods, m)]
        tree = ast.parse(p.read_text(encoding="utf-8"))
        offenders += [
            f"{name}:{n.lineno} open()"
            for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "open"
        ]
    assert offenders == []


def test_the_input_loader_imports_no_enrichment_and_no_value_code() -> None:
    for rel in (
        "src/common/value_inputs.py",
        "src/common/value_types.py",
        "src/common/value_universe.py",
    ):
        mods = imported_modules(ROOT / rel)
        bad = [m for m in (*ENRICHMENT, "src.value") if _reaches(mods, m)]
        assert bad == [], rel


def test_value_types_is_plain_pydantic() -> None:
    mods = imported_modules(ROOT / "src" / "common" / "value_types.py")
    assert {m.split(".")[0] for m in mods} <= {"__future__", "datetime", "typing", "pydantic"}


def test_value_opens_no_sec_client() -> None:
    """The research worker owns every SEC fetch (spec §6.9): src/value reaches no data provider
    and no HTTP client."""
    offenders = [
        f"{p.relative_to(ROOT)} -> {m}"
        for p in VALUE
        for m in ("src.data", "httpx", "requests")
        if _reaches(imported_modules(p), m)
    ]
    assert offenders == []


def test_the_trading_path_never_imports_the_value_book() -> None:
    offenders = [
        f"{p.relative_to(ROOT)}"
        for pkg in (
            "engine",
            "execution",
            "strategies",
            "orchestrator",
            "monitor",
            "notify",
            "spreads",
            "news",
            "claude",
        )
        for p in sorted((ROOT / "src" / pkg).rglob("*.py"))
        if _reaches(imported_modules(p), "src.value")
    ]
    assert offenders == []


def test_only_src_value_constructs_value_rows() -> None:
    rows = ("ValueTickerFileRow(", "ValueTickerHistoryRow(", "ValueRunRow(")
    offenders = []
    for p in (ROOT / "src").rglob("*.py"):
        if (ROOT / "src" / "value") in p.parents:
            continue
        text = p.read_text(encoding="utf-8")
        offenders += [f"{p.relative_to(ROOT)}: {r[:-1]}" for r in rows if r in text]
    assert offenders == []


def test_the_value_scorecard_loads_no_wheel_layer_even_transitively() -> None:
    probe = (
        "import json, sys\n"
        "import src.value.scorecard, src.value.store, src.value.ticker_file, src.value.funnel\n"
        "import src.common.value_inputs, src.common.value_universe\n"
        "print(json.dumps(sorted(m for m in sys.modules if m.startswith('src.'))))\n"
    )
    env = {**os.environ, "IBKR_CONFIG_USE_EXAMPLES": "1"}
    out = subprocess.run(
        [sys.executable, "-c", probe], cwd=ROOT, env=env, capture_output=True, text=True, check=True
    )
    loaded = json.loads(out.stdout)
    bad = [
        m
        for m in loaded
        for f in (
            *FORBIDDEN_FOR_VALUE,
            "src.research.store.session",
            "src.research.ingest.fundamentals",
        )
        if m == f or m.startswith(f + ".")
    ]
    assert bad == []
