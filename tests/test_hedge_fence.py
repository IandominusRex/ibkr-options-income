"""The hedge fence, first version (risk-envelope plan Task 16; spec §3.10.9, ruling H9).

``src/hedge/`` is a deterministic package with its own tables:

* it imports no enrichment and nothing from the reasoning layer (a sentiment, news or Claude term
  there could move a hedge quote or, later, a hedge order); and
* it is the only package that constructs ``hedge_*`` rows (``HedgeQuoteRow`` now; Task 33 adds the
  book's tables to ``ROW_CLASSES``). Reading them is allowed anywhere; writing is one package.

Task 33 extends it with the book's half: the four book tables join ``ROW_CLASSES``, the hedge
package never constructs a wheel ``orders`` / ``fills`` row, and ``src/common/hedge_view.py`` is
everyone else's window (``mode=ro``, plain SQL, imports only ``src.common.config`` and the standard
library). The reconciler skip and the attribution are tested in ``tests/test_hedge_book.py``.
"""

from __future__ import annotations

import re
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
ROW_CLASSES = (
    "HedgeQuoteRow(",
    "HedgeProgrammeRow(",
    "HedgeOrderRow(",
    "HedgeFillRow(",
    "HedgeMarkRow(",
)


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
    """Re-based in Task 35 (it pinned Task 16's capture-only package, before the buy-to-open build
    existed): the hedge package never constructs an order object (``src/execution/order_builder.py``
    builds every one), never uses a market order or ``ib.reqMktData`` directly, and only
    ``executor.py`` sends an order."""
    for p in sorted((SRC / "hedge").rglob("*.py")):
        text = p.read_text(encoding="utf-8")
        for needle in ("LimitOrder(", "MarketOrder", "StopOrder", ".reqMktData("):
            assert needle not in text, f"{p.name}: {needle}"
        assert not re.search(r"\bOrder\(", text), f"{p.name}: Order("
        if p.name != "executor.py":
            assert "placeOrder" not in text, f"{p.name}: placeOrder"


def test_the_hedge_package_never_writes_a_wheel_order_or_fill() -> None:
    """Item 7: the wheel's ``orders`` / ``fills`` never receive a hedge row, so the 20+ sites that
    read SELL as an open never see one."""
    for p in sorted((SRC / "hedge").rglob("*.py")):
        text = p.read_text(encoding="utf-8")
        for cls in ("OrderRow(", "FillRow("):
            hits = [ln for ln in text.splitlines() if cls in ln and f"Hedge{cls}" not in ln]
            assert hits == [], f"{p.name} constructs {cls[:-1]}: {hits}"


def test_hedge_view_is_read_only_plain_sql_and_imports_only_config() -> None:
    path = SRC / "common" / "hedge_view.py"
    text = path.read_text(encoding="utf-8")
    assert "mode=ro" in text
    modules = imported_modules(path)
    src_imports = {m for m in modules if m.startswith("src")}
    assert src_imports <= {"src.common.config", "src.common.config.get_config"}, src_imports
    assert not _reaches(modules, "sqlalchemy")
    for writer in ("INSERT", "UPDATE ", "DELETE", "session_scope"):
        assert writer not in text, writer


def test_other_books_and_the_reasoning_layer_never_import_the_hedge_package() -> None:
    offenders = [
        f"{p.relative_to(ROOT)}"
        for pkg in ("spreads", "spreads_ai", "value", "value_ai", "claude", "news")
        for p in sorted((SRC / pkg).rglob("*.py"))
        if _reaches(imported_modules(p), "src.hedge")
    ]
    assert offenders == []
