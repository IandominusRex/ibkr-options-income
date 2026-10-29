"""src/common/value_inputs.py: the neutral, read-only loader (value book spec §6.9)."""

from __future__ import annotations

import json
import math
from datetime import date, datetime
from types import SimpleNamespace

import pandas as pd
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

import src.common.value_inputs as vi
from src.common.schemas import MarketRegime
from src.research.store.models import (
    Base,
    CompanyFactsRawRow,
    DailyBarRow,
    FinancialRow,
    SymbolRow,
)


def _e(val, end, filed, *, start=None, form="10-K", accn="k25"):
    out = {
        "val": val,
        "end": end,
        "filed": filed,
        "form": form,
        "accn": accn,
        "fy": 2025,
        "fp": "FY",
    }
    if start:
        out["start"] = start
    return out


PAYLOAD = {
    "cik": 1,
    "entityName": "Steady Co",
    "facts": {
        "dei": {
            "EntityCommonStockSharesOutstanding": {
                "units": {
                    "shares": [
                        _e(101e6, "2025-01-31", "2025-02-10"),
                        _e(100e6, "2025-07-25", "2025-08-05", form="10-Q", accn="q2"),
                    ]
                }
            }
        },
        "us-gaap": {
            "Revenues": {
                "units": {
                    "USD": [
                        _e(900e6, "2023-12-31", "2024-02-10", start="2023-01-01", accn="k23"),
                        _e(1000e6, "2024-12-31", "2025-02-10", start="2024-01-01", accn="k24"),
                        _e(
                            520e6,
                            "2025-06-30",
                            "2025-08-05",
                            start="2025-01-01",
                            form="10-Q",
                            accn="q2",
                        ),
                        _e(
                            470e6,
                            "2024-06-30",
                            "2025-08-05",
                            start="2024-01-01",
                            form="10-Q",
                            accn="q2",
                        ),
                    ]
                }
            },
            "InterestExpense": {
                "units": {
                    "USD": [_e(10e6, "2023-12-31", "2024-02-10", start="2023-01-01", accn="k23")]
                }
            },
            "Assets": {
                "units": {
                    "USD": [
                        _e(3000e6, "2024-12-31", "2025-02-10", accn="k24"),
                        _e(3100e6, "2025-06-30", "2025-08-05", form="10-Q", accn="q2"),
                    ]
                }
            },
            "WeightedAverageNumberOfDilutedSharesOutstanding": {
                "units": {
                    "shares": [
                        _e(102e6, "2024-12-31", "2025-02-10", start="2024-01-01", accn="k24"),
                        _e(
                            100.5e6,
                            "2025-06-30",
                            "2025-08-05",
                            start="2025-04-01",
                            form="10-Q",
                            accn="q2",
                        ),
                    ]
                }
            },
        },
    },
}


def test_financials_read_annual_ttm_latest_and_shares() -> None:
    fin = vi.build_value_financials(PAYLOAD, as_of=date(2025, 9, 1))
    assert [p.period_end for p in fin.annual] == [date(2024, 12, 31), date(2023, 12, 31)]
    assert fin.annual[0].items["revenue"] == 1000e6
    assert fin.annual[0].accns["revenue"] == "k24"
    assert fin.ttm["revenue"].value == 1050e6  # 1000 + 520 - 470
    assert fin.ttm["revenue"].basis == "ytd"
    assert fin.latest["total_assets"].value == 3100e6
    assert fin.shares_latest == 100.5e6
    assert fin.cover_shares == 100e6
    assert (fin.latest_accn, fin.latest_filed) == ("q2", date(2025, 8, 5))


def test_a_concept_the_filer_stopped_tagging_is_dropped_from_ttm() -> None:
    """InterestExpense ends 2023-12-31, 547 days before the newest period: stale."""
    fin = vi.build_value_financials(PAYLOAD, as_of=date(2025, 9, 1))
    assert "interest_expense" not in fin.ttm
    assert fin.annual[1].items["interest_expense"] == 10e6  # history keeps it


def test_as_of_sees_only_what_was_filed_by_then() -> None:
    fin = vi.build_value_financials(PAYLOAD, as_of=date(2025, 3, 1))
    assert fin.ttm["revenue"].value == 1000e6 and fin.ttm["revenue"].basis == "fy"
    assert fin.latest["total_assets"].value == 3000e6
    assert fin.cover_shares == 101e6
    assert fin.latest_accn == "k24"


def test_a_filer_without_us_gaap_facts_says_so() -> None:
    fin = vi.build_value_financials({"facts": {"ifrs-full": {}}}, as_of=date(2025, 9, 1))
    assert fin.has_us_gaap is False and fin.annual == []


def _bars(n: int = 300) -> tuple[pd.DataFrame, pd.DataFrame]:
    days = pd.bdate_range("2024-06-03", periods=n).date
    spy_r = [0.01 * math.sin(i / 3.0) for i in range(n)]
    spy_close, stock_close = [400.0], [100.0]
    for r in spy_r[1:]:
        spy_close.append(spy_close[-1] * (1 + r))
        stock_close.append(stock_close[-1] * (1 + 2 * r))

    def frame(close: list[float]) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "high": [c + 1 for c in close],
                "low": [c - 1 for c in close],
                "close": close,
                "volume": [1e6] * n,
            },
            index=pd.Index(days, name="date"),
        )

    return frame(stock_close), frame(spy_close)


def test_price_series_computes_the_fixed_window_technicals() -> None:
    bars, spy = _bars()
    ps = vi.build_price_series(bars, spy)
    assert ps is not None
    close = bars["close"]
    assert ps.sessions == 300 and len(ps.closes) == 260 and len(ps.sma20s) == 260
    assert ps.close == pytest.approx(close.iloc[-1])
    assert ps.sma20 == pytest.approx(close.iloc[-20:].mean())
    assert ps.sma200 == pytest.approx(close.iloc[-200:].mean())
    assert ps.ret_6m == pytest.approx(close.iloc[-1] / close.iloc[-127] - 1)
    assert ps.beta_250 == pytest.approx(2.0, rel=1e-6)
    assert ps.adv_dollar_20 == pytest.approx((close.iloc[-20:] * 1e6).mean())


def test_price_series_is_none_without_bars() -> None:
    empty = pd.DataFrame(columns=["high", "low", "close", "volume"])
    assert vi.build_price_series(empty, None) is None


@pytest.fixture()
def research_file(tmp_path, monkeypatch):
    path = tmp_path / "research.db"
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        s.add(SymbolRow(symbol="STDY", cik="0000000001", name="Steady Co"))
        s.add(
            CompanyFactsRawRow(
                cik="0000000001", payload_json=json.dumps(PAYLOAD), fetched_at=datetime(2025, 9, 1)
            )
        )
        for i, d in enumerate(pd.bdate_range("2025-08-25", periods=6).date):
            s.add(
                DailyBarRow(
                    symbol="STDY", date=d, open=10, high=11, low=9, close=10 + i, volume=1e6
                )
            )
        s.add(
            FinancialRow(
                symbol="STDY",
                period_end=date(2025, 6, 30),
                period_type="quarterly",
                line_item="revenue",
                value=1.0,
                accn="q2",
                filed=date(2025, 8, 5),
            )
        )
        s.add(
            FinancialRow(
                symbol="STDY",
                period_end=date(2024, 12, 31),
                period_type="annual",
                line_item="revenue",
                value=1.0,
                accn="k24",
                filed=date(2025, 2, 10),
            )
        )
        s.commit()
    monkeypatch.setattr(vi, "_resolve_path", lambda: str(path))
    vi.reset_engine()
    yield path
    vi.reset_engine()


def test_reads_come_from_a_read_only_research_db(research_file) -> None:
    with vi.research_read() as s:
        assert s is not None
        cik, payload = vi.read_payload(s, "STDY")
        assert cik == "0000000001" and payload is not None and payload["entityName"] == "Steady Co"
        bars = vi.read_bars(s, "STDY", date(2025, 8, 28))
        assert list(bars["close"]) == [10.0, 11.0, 12.0, 13.0]
        parts = vi.current_fingerprint_parts(s, "STDY")
        assert parts == {
            "latest_accn": "q2",
            "latest_filed": date(2025, 8, 5),
            "price_date": date(2025, 9, 1),
            "price_close": 15.0,
        }
        with pytest.raises(OperationalError):
            s.execute(text("DELETE FROM symbols"))


def test_a_missing_research_db_is_none_not_an_error(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(vi, "_resolve_path", lambda: str(tmp_path / "absent.db"))
    vi.reset_engine()
    with vi.research_read() as s:
        assert s is None


def test_an_unknown_symbol_has_no_payload(research_file) -> None:
    with vi.research_read() as s:
        assert s is not None
        assert vi.read_payload(s, "NOPE") == (None, None)


def test_market_facts_come_from_the_provider_and_never_raise(monkeypatch) -> None:
    class Provider:
        def get_info(self, symbol):
            return {
                "marketCap": 3.2e12,
                "sector": "Technology",
                "industry": "Internet Content & Information",
                "quoteType": "EQUITY",
            }

        def get_calendar(self, symbol):
            return {"Earnings Date": [date(2026, 2, 3), date(2026, 2, 5)]}

    monkeypatch.setattr("src.data.factory.get_fundamentals_provider", lambda: Provider())
    mf = vi.fetch_market_facts("GOOGL")
    assert (mf.market_cap, mf.industry, mf.next_earnings) == (
        3.2e12,
        "Internet Content & Information",
        date(2026, 2, 3),
    )

    class Broken:
        def get_info(self, symbol):
            raise RuntimeError("down")

        def get_calendar(self, symbol):
            raise RuntimeError("down")

    monkeypatch.setattr("src.data.factory.get_fundamentals_provider", lambda: Broken())
    assert vi.fetch_market_facts("GOOGL").market_cap is None


def test_the_regime_is_spys_effective_regime_or_unknown(monkeypatch) -> None:
    state = SimpleNamespace(spy=SimpleNamespace(effective=MarketRegime.CAUTIOUS))
    monkeypatch.setattr("src.storage.regime_state.load_regime_state", lambda: state)
    assert vi.load_regime() == "cautious"
    monkeypatch.setattr("src.storage.regime_state.load_regime_state", lambda: None)
    assert vi.load_regime() == "unknown"
