"""The hedge fence, first version (risk-envelope plan Task 16; spec §3.10.9, ruling H9).

``src/hedge/`` is a deterministic package with its own tables:

* it imports no enrichment and nothing from the reasoning layer (a sentiment, news or Claude term
  there could move a hedge quote or, later, a hedge order); and
* it is the only package that constructs ``hedge_*`` rows (``HedgeQuoteRow`` now; Task 33 adds the
  book's tables to ``ROW_CLASSES``). Reading them is allowed anywhere; writing is one package.

Task 33 extends this file with the order-path half of the fence (the reconciler skip, the clash
rules, ``src/common/hedge_view.py`` as everyone else's window).
"""

from __future__ import annotations

from pathlib import Path

from tests.test_spreads_fence import imported_modules

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

ENRICHMENT = (
    "src.claude",
    "src.news",
    "src.spreads_ai",
    "src.value_ai",
    "src.analytics.market_conditions",
    "src.analytics.sentiment",
    "src.analytics.sector_context",
)
ROW_CLASSES = ("HedgeQuoteRow(",)


def _reaches(modules: set[str], prefix: str) -> bool:
    return any(m == prefix or m.startswith(prefix + ".") for m in modules)


def test_the_hedge_package_exists() -> None:
    names = {p.name for p in (SRC / "hedge").glob("*.py")}
    assert {"__init__.py", "capture.py", "menu.py", "store.py"} <= names


def test_hedge_imports_no_enrichment() -> None:
    offenders = [
        f"{p.relative_to(ROOT)} -> {m}"
        for p in sorted((SRC / "hedge").rglob("*.py"))
        for m in ENRICHMENT
        if _reaches(imported_modules(p), m)
    ]
    assert offenders == []


def test_only_src_hedge_writes_hedge_rows() -> None:
    offenders = []
    for base in (SRC, ROOT / "scripts"):
        for path in sorted(base.rglob("*.py")):
            rel = path.relative_to(ROOT)
            if rel.parts[:2] == ("src", "hedge"):
                continue
            if rel == Path("src/storage/models.py"):  # the class definitions themselves
                continue
            text = path.read_text(encoding="utf-8")
            offenders += [f"{rel}: {cls}" for cls in ROW_CLASSES if cls in text]
    assert offenders == [], f"only src/hedge/ may construct hedge rows: {offenders}"


def test_hedge_places_no_order() -> None:
    """Task 16 is capture only: no order object, no order call, no direct market-data call."""
    for p in sorted((SRC / "hedge").rglob("*.py")):
        text = p.read_text(encoding="utf-8")
        for needle in ("placeOrder", "LimitOrder", "MarketOrder", ".reqMktData("):
            assert needle not in text, f"{p.name}: {needle}"
