"""Daily-bar ingest upserts and never truncates on a failed fetch."""

from __future__ import annotations

import pandas as pd
import pytest

from src.research.ingest.prices import ingest_daily_bars
from src.research.store.models import DailyBarRow
from src.research.store.session import init_research_db, research_session


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "src.research.store.session._resolve_url",
        lambda: f"sqlite:///{(tmp_path / 'research.db').as_posix()}",
    )
    monkeypatch.setattr("src.research.store.session._engine", None)
    init_research_db()


def _frame(closes: dict[str, float]) -> pd.DataFrame:
    idx = pd.DatetimeIndex(list(closes), name="Date")
    return pd.DataFrame(
        {
            "Open": list(closes.values()),
            "High": list(closes.values()),
            "Low": list(closes.values()),
            "Close": list(closes.values()),
            "Volume": [1000.0] * len(closes),
        },
        index=idx,
    )


class _Stub:
    def __init__(self, df: pd.DataFrame) -> None:
        self._df = df

    def get_daily_bars(self, symbol: str, lookback_days: int = 400) -> pd.DataFrame:
        return self._df


def test_writes_bars(db, monkeypatch) -> None:
    monkeypatch.setattr(
        "src.research.ingest.prices.get_bulk_price_provider",
        lambda: _Stub(_frame({"2026-08-28": 221.4, "2026-08-29": 223.8})),
    )
    assert ingest_daily_bars("AAPL") == 2
    with research_session() as s:
        assert s.query(DailyBarRow).filter_by(symbol="AAPL").count() == 2


def test_reingest_updates_rather_than_duplicating(db, monkeypatch) -> None:
    monkeypatch.setattr(
        "src.research.ingest.prices.get_bulk_price_provider",
        lambda: _Stub(_frame({"2026-08-28": 221.4})),
    )
    ingest_daily_bars("AAPL")
    monkeypatch.setattr(
        "src.research.ingest.prices.get_bulk_price_provider",
        lambda: _Stub(_frame({"2026-08-28": 999.0})),
    )
    ingest_daily_bars("AAPL")
    with research_session() as s:
        rows = s.query(DailyBarRow).filter_by(symbol="AAPL").all()
        assert len(rows) == 1
        assert rows[0].close == 999.0


def test_empty_fetch_leaves_history_intact(db, monkeypatch) -> None:
    monkeypatch.setattr(
        "src.research.ingest.prices.get_bulk_price_provider",
        lambda: _Stub(_frame({"2026-08-28": 221.4})),
    )
    ingest_daily_bars("AAPL")
    monkeypatch.setattr(
        "src.research.ingest.prices.get_bulk_price_provider",
        lambda: _Stub(pd.DataFrame()),
    )
    assert ingest_daily_bars("AAPL") == 0
    with research_session() as s:
        assert s.query(DailyBarRow).filter_by(symbol="AAPL").count() == 1
