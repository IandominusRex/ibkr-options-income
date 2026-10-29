"""scripts/value_dry_run.py end to end on temporary databases (value book spec §17).

Importing the script is safe: it has a ``__main__`` guard and starts nothing at import.
"""

from __future__ import annotations

import json
import py_compile
from datetime import datetime

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import src.common.value_inputs as vi
import src.common.value_universe as vu
import src.value.store as store
from scripts import value_dry_run
from src.common.value_types import MarketFacts
from src.research.store.models import Base, CompanyFactsRawRow, DailyBarRow, SymbolRow
from src.value.store import ValueRunRow, ValueTickerFileRow, value_session
from tests.value_fixtures import AS_OF, companyfacts, price


def test_the_script_compiles() -> None:
    py_compile.compile("scripts/value_dry_run.py", doraise=True)
    py_compile.compile("scripts/value_universe_snapshot.py", doraise=True)


@pytest.fixture()
def dbs(tmp_path, monkeypatch):
    research = tmp_path / "research.db"
    engine = create_engine(f"sqlite:///{research}")
    Base.metadata.create_all(engine)
    closes = price(30.0).closes
    days = pd.bdate_range(end=AS_OF, periods=len(closes)).date
    with Session(engine) as s:
        s.add(SymbolRow(symbol="STDY", cik="0000000001", name="Steady Co"))
        s.add(
            CompanyFactsRawRow(
                cik="0000000001",
                payload_json=json.dumps(companyfacts()),
                fetched_at=datetime(2026, 3, 30),
            )
        )
        for d, c in zip(days, closes, strict=True):
            s.add(
                DailyBarRow(
                    symbol="STDY", date=d, open=c, high=c * 1.01, low=c * 0.99, close=c, volume=1e6
                )
            )
            s.add(
                DailyBarRow(
                    symbol="SPY", date=d, open=500, high=505, low=495, close=500.0, volume=1e8
                )
            )
        s.commit()
    monkeypatch.setattr(vi, "_resolve_path", lambda: str(research))
    vi.reset_engine()
    monkeypatch.setattr(
        store, "_resolve_url", lambda: f"sqlite:///{(tmp_path / 'value.db').as_posix()}"
    )
    store.reset_engine()
    monkeypatch.setattr(
        vi, "fetch_market_facts", lambda symbol: MarketFacts(market_cap=3.0e9, next_earnings=None)
    )
    monkeypatch.setattr(vi, "load_regime", lambda: "normal")
    monkeypatch.setattr(
        vu,
        "build_value_universe",
        lambda cfg, universe: vu.ValueUniverse(
            trading=["STDY"],
            classification={"STDY": ("Information Technology", "Application Software")},
        ),
    )
    monkeypatch.setattr(value_dry_run, "_earnings", lambda as_of: {})
    monkeypatch.setattr(value_dry_run, "_universe", lambda path: {})
    yield
    vi.reset_engine()
    store.reset_engine()


def test_the_dry_run_scores_persists_and_prints_the_funnel(dbs, capsys, tmp_path) -> None:
    report = tmp_path / "report.txt"
    assert (
        value_dry_run.main(
            ["run", "--as-of", AS_OF.isoformat(), "--names", "STDY", "--report", str(report)]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert report.read_text() == out
    assert "== Trading universe: 1 names ==" in out
    assert "## STDY  class=operating  price=30.00  data_quality=pass  health=pass" in out
    assert "timing.earnings" in out and "no earnings date" in out
    assert "run time:" in out
    with value_session() as s:
        row = s.get(ValueTickerFileRow, "STDY")
        assert row is not None and row.universe == "trading"
        assert row.verdict_deep == "WATCH"  # cheap enough; no earnings date is unknown timing
        run = s.query(ValueRunRow).one()
        assert (run.kind, run.names, run.ruleset_version) == ("dry_run", 1, "v0-dryrun")


def test_no_persist_leaves_value_db_alone(dbs, tmp_path) -> None:
    assert (
        value_dry_run.main(
            [
                "run",
                "--as-of",
                AS_OF.isoformat(),
                "--no-persist",
                "--out",
                str(tmp_path / "cards.json"),
            ]
        )
        == 0
    )
    assert not (tmp_path / "value.db").exists()
    cards = json.loads((tmp_path / "cards.json").read_text())
    assert [c["symbol"] for c in cards] == ["STDY"]
