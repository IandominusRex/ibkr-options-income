"""Tests for the Phase 2 data provider abstraction layer (``src/data/``).

Three concerns:

1. **Protocol conformance** — each backend (yfinance active, FMP stub) implements the
   ``Protocol`` shapes from :mod:`src.data.protocols`.
2. **Golden-master** — the yfinance backend wraps the exact yfinance calls the analytics
   layer used to make directly (``yf.Ticker(...).info`` / ``.history`` / ``.news`` /
   ``.fast_info``). The wrapper reproduces the prior output shape byte-for-byte: same
   DataFrame columns, same info dict, same news list. No behaviour change is the contract.
3. **FMP stub raises NotImplementedError** — the swap path is documented but not wired;
   no accidental backend can silently do nothing.

IBKR is *not* a provider and is not tested here — it is the broker + execution path
(``src/ibkr/``) and stays untouched by Phase 2.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.data import factory as data_factory
from src.data.factory import (
    get_bulk_price_provider,
    get_fundamentals_provider,
    get_news_provider,
    get_price_provider,
)
from src.data.fmp_backend import (
    FMPFundamentalsProvider,
    FMPNewsProvider,
    FMPPriceProvider,
)
from src.data.protocols import (
    BulkPriceProvider,
    FundamentalsProvider,
    NewsProvider,
    PriceProvider,
)
from src.data.yfinance_backend import (
    YFinanceBulkPriceProvider,
    YFinanceFundamentalsProvider,
    YFinanceNewsProvider,
    YFinancePriceProvider,
)


@pytest.fixture(autouse=True)
def _clear_provider_cache():
    """The factories cache the provider instance process-wide via ``lru_cache`` — clear it
    before and after each test so a monkeypatch of ``get_config().data.*`` takes effect
    and no stub leaks across cases.
    """
    data_factory.get_price_provider.cache_clear()
    data_factory.get_fundamentals_provider.cache_clear()
    data_factory.get_news_provider.cache_clear()
    data_factory.get_bulk_price_provider.cache_clear()
    yield
    data_factory.get_price_provider.cache_clear()
    data_factory.get_fundamentals_provider.cache_clear()
    data_factory.get_news_provider.cache_clear()
    data_factory.get_bulk_price_provider.cache_clear()


# --------------------------------------------------------------------------- #
# Protocol conformance — structural subtyping
# --------------------------------------------------------------------------- #


class TestProtocolConformance:
    def test_yfinance_price_provider_satisfies_protocol(self):
        assert isinstance(YFinancePriceProvider(), PriceProvider)

    def test_yfinance_fundamentals_provider_satisfies_protocol(self):
        assert isinstance(YFinanceFundamentalsProvider(), FundamentalsProvider)

    def test_yfinance_news_provider_satisfies_protocol(self):
        assert isinstance(YFinanceNewsProvider(), NewsProvider)

    def test_fmp_price_provider_satisfies_protocol(self):
        # Protocol conformance is structural; the stubs have the right method shapes.
        assert isinstance(FMPPriceProvider(), PriceProvider)

    def test_fmp_fundamentals_provider_satisfies_protocol(self):
        assert isinstance(FMPFundamentalsProvider(), FundamentalsProvider)

    def test_fmp_news_provider_satisfies_protocol(self):
        assert isinstance(FMPNewsProvider(), NewsProvider)

    def test_yfinance_bulk_price_provider_satisfies_protocol(self):
        assert isinstance(YFinanceBulkPriceProvider(), BulkPriceProvider)


# --------------------------------------------------------------------------- #
# Factory — reads config/settings.yaml → data.*
# --------------------------------------------------------------------------- #


class TestFactory:
    def test_default_factory_returns_yfinance_backends(self):
        assert isinstance(get_price_provider(), YFinancePriceProvider)
        assert isinstance(get_fundamentals_provider(), YFinanceFundamentalsProvider)
        assert isinstance(get_news_provider(), YFinanceNewsProvider)
        assert isinstance(get_bulk_price_provider(), YFinanceBulkPriceProvider)

    def test_factory_caches_instance_process_wide(self):
        assert get_price_provider() is get_price_provider()
        assert get_fundamentals_provider() is get_fundamentals_provider()
        assert get_news_provider() is get_news_provider()
        assert get_bulk_price_provider() is get_bulk_price_provider()

    def test_factory_rejects_unknown_backend(self, monkeypatch):
        from src.common.config import get_config

        cfg = get_config()
        monkeypatch.setattr(cfg.data, "price_provider", "unknown_backend")
        with pytest.raises(ValueError, match="Unknown data.price_provider"):
            data_factory._make_price_provider("unknown_backend")

    def test_factory_routes_fmp_to_stubs(self):
        # The factory recognises "fmp" and returns the stub class (which raises on use).
        assert isinstance(data_factory._make_price_provider("fmp"), FMPPriceProvider)
        assert isinstance(data_factory._make_fundamentals_provider("fmp"), FMPFundamentalsProvider)
        assert isinstance(data_factory._make_news_provider("fmp"), FMPNewsProvider)

    def test_bulk_price_provider_rejects_stooq(self):
        # Task 4.1 licence check (docs/web/data-sources.md, 2026-09-04): stooq is not
        # usable for unattended access, so it was never wired.
        with pytest.raises(ValueError, match="not usable"):
            data_factory._make_bulk_price_provider("stooq")

    def test_bulk_price_provider_rejects_unknown_backend(self):
        with pytest.raises(ValueError, match="Unknown data.bulk_price_provider"):
            data_factory._make_bulk_price_provider("unknown_backend")


# --------------------------------------------------------------------------- #
# FMP stub — documented swap path, raises NotImplementedError, never silently no-ops
# --------------------------------------------------------------------------- #


class TestFMPStubsRaise:
    def test_price_provider_stubs_raise(self):
        p = FMPPriceProvider()
        with pytest.raises(NotImplementedError):
            p.get_ohlcv("AAPL")
        with pytest.raises(NotImplementedError):
            p.get_last_price("AAPL")

    def test_fundamentals_provider_stubs_raise(self):
        p = FMPFundamentalsProvider()
        with pytest.raises(NotImplementedError):
            p.get_info("AAPL")
        with pytest.raises(NotImplementedError):
            p.get_calendar("AAPL")

    def test_news_provider_stubs_raise(self):
        p = FMPNewsProvider()
        with pytest.raises(NotImplementedError):
            p.get_headlines("AAPL")


# --------------------------------------------------------------------------- #
# Golden-master — yfinance backend reproduces the exact prior call shapes
# --------------------------------------------------------------------------- #


def _make_ticker(*, info=None, calendar=None, news=None, fast_info=None, history_df=None):
    """A yfinance.Ticker-shaped mock matching the old direct call sites."""
    t = MagicMock()
    t.info = info
    t.calendar = calendar
    t.news = news
    t.fast_info = fast_info if fast_info is not None else {}
    t.history.return_value = history_df if history_df is not None else pd.DataFrame()
    return t


def _patch_yf(ticker=None, *, side_effect=None):
    """Patch the ``yf`` name inside ``src.data.yfinance_backend`` (the module-level
    ``import yfinance as yf``). Returns the ``patch`` context manager.
    """
    fake_yf = MagicMock()
    if side_effect is not None:
        fake_yf.Ticker.side_effect = side_effect
    else:
        fake_yf.Ticker.return_value = ticker
    return patch("src.data.yfinance_backend.yf", fake_yf)


class TestYFinancePriceProviderGoldenMaster:
    def test_get_ohlcv_returns_the_history_dataframe_unchanged(self):
        """The backend returns yfinance's ``Ticker.history`` frame verbatim — same columns,
        same index, same rows. Callers (``price_data._fetch_yf_bars``) do the Bar mapping.
        """
        df = pd.DataFrame(
            {"Open": [1.0], "High": [2.0], "Low": [0.5], "Close": [1.5], "Volume": [100]},
            index=pd.DatetimeIndex(["2026-01-02"]),
        )
        ticker = _make_ticker(history_df=df)
        with _patch_yf(ticker) as fake_yf:
            out = YFinancePriceProvider().get_ohlcv("AAPL", lookback_days=80)
        fake_yf.Ticker.assert_called_once_with("AAPL")
        ticker.history.assert_called_once_with(period="3mo")  # 80 days → "3mo"
        pd.testing.assert_frame_equal(out, df)

    def test_get_ohlcv_empty_history_returns_empty_dataframe(self):
        ticker = _make_ticker(history_df=pd.DataFrame())
        with _patch_yf(ticker):
            out = YFinancePriceProvider().get_ohlcv("BAD")
        assert out.empty

    def test_get_ohlcv_exception_returns_empty_dataframe(self):
        with _patch_yf(side_effect=RuntimeError("network")):
            out = YFinancePriceProvider().get_ohlcv("AAPL")
        assert out.empty

    def test_lookback_to_period_mapping(self):
        cases = [
            (5, "5d"),
            (25, "1mo"),
            (80, "3mo"),
            (170, "6mo"),
            (365, "1y"),
            (400, "2y"),  # BulkPriceProvider's documented default lookback (Task 4.1)
            (730, "2y"),
            (999, "5y"),
        ]
        for lookback, expected in cases:
            ticker = _make_ticker(history_df=pd.DataFrame())
            with _patch_yf(ticker):
                YFinancePriceProvider().get_ohlcv("X", lookback_days=lookback)
            assert ticker.history.call_args.kwargs["period"] == expected, f"{lookback}→{expected}"

    def test_get_last_price_reads_fast_info_last_price(self):
        ticker = _make_ticker(fast_info={"lastPrice": 123.45})
        with _patch_yf(ticker):
            assert YFinancePriceProvider().get_last_price("AAPL") == 123.45

    def test_get_last_price_none_fast_info_returns_none(self):
        ticker = _make_ticker(fast_info={"lastPrice": None})
        with _patch_yf(ticker):
            assert YFinancePriceProvider().get_last_price("AAPL") is None

    def test_get_last_price_exception_returns_none(self):
        with _patch_yf(side_effect=RuntimeError("network")):
            assert YFinancePriceProvider().get_last_price("AAPL") is None


class TestYFinanceFundamentalsProviderGoldenMaster:
    def test_get_info_returns_ticker_info_dict(self):
        info = {"quoteType": "EQUITY", "trailingPE": 15.0, "sector": "Technology"}
        ticker = _make_ticker(info=info)
        with _patch_yf(ticker):
            assert YFinanceFundamentalsProvider().get_info("AAPL") == info

    def test_get_info_none_info_returns_empty_dict(self):
        ticker = MagicMock()
        ticker.info = None
        with _patch_yf(ticker):
            assert YFinanceFundamentalsProvider().get_info("AAPL") == {}

    def test_get_info_exception_returns_empty_dict(self):
        with _patch_yf(side_effect=RuntimeError("network")):
            assert YFinanceFundamentalsProvider().get_info("AAPL") == {}

    def test_get_calendar_returns_ticker_calendar(self):
        cal = {"Earnings Date": [pd.Timestamp("2030-12-31")]}
        ticker = _make_ticker(calendar=cal)
        with _patch_yf(ticker):
            assert YFinanceFundamentalsProvider().get_calendar("AAPL") == cal

    def test_get_calendar_none_returns_empty_dict(self):
        ticker = MagicMock()
        ticker.calendar = None
        with _patch_yf(ticker):
            assert YFinanceFundamentalsProvider().get_calendar("AAPL") == {}

    def test_get_calendar_exception_returns_empty_dict(self):
        with _patch_yf(side_effect=RuntimeError("network")):
            assert YFinanceFundamentalsProvider().get_calendar("AAPL") == {}


class TestYFinanceNewsProviderGoldenMaster:
    def test_get_headlines_returns_ticker_news_list(self):
        items = [
            {"content": {"title": "Shares surge"}},
            {"title": "Legacy flat shape"},
        ]
        ticker = _make_ticker(news=items)
        with _patch_yf(ticker) as fake_yf:
            assert YFinanceNewsProvider().get_headlines("AAPL") == items
        # News is fetched uppercased, matching the prior direct call.
        fake_yf.Ticker.assert_called_once_with("AAPL")

    def test_get_headlines_truncates_to_limit(self):
        items = [{"title": f"Headline {i}"} for i in range(10)]
        ticker = _make_ticker(news=items)
        with _patch_yf(ticker):
            out = YFinanceNewsProvider().get_headlines("AAPL", limit=3)
        assert len(out) == 3

    def test_get_headlines_none_news_returns_empty_list(self):
        ticker = MagicMock()
        ticker.news = None
        with _patch_yf(ticker):
            assert YFinanceNewsProvider().get_headlines("AAPL") == []

    def test_get_headlines_exception_returns_empty_list(self):
        with _patch_yf(side_effect=RuntimeError("network")):
            assert YFinanceNewsProvider().get_headlines("AAPL") == []


class TestYFinanceBulkPriceProviderGoldenMaster:
    """The cold-tier fallback: wraps ``YFinancePriceProvider.get_ohlcv`` so the
    ``BulkPriceProvider`` Protocol is satisfied without stooq (Task 4.1 licence check).
    """

    def test_get_daily_bars_wraps_get_ohlcv(self):
        df = pd.DataFrame(
            {"Open": [1.0], "High": [2.0], "Low": [0.5], "Close": [1.5], "Volume": [100]},
            index=pd.DatetimeIndex(["2026-01-02"]),
        )
        ticker = _make_ticker(history_df=df)
        with _patch_yf(ticker):
            out = YFinanceBulkPriceProvider().get_daily_bars("AAPL", lookback_days=400)
        assert list(out.columns) == ["Open", "High", "Low", "Close", "Volume"]
        assert out.index.name == "Date"
        assert out["Close"].iloc[-1] == 1.5

    def test_get_daily_bars_empty_history_returns_empty_frame_with_the_right_shape(self):
        with _patch_yf(_make_ticker(history_df=pd.DataFrame())):
            out = YFinanceBulkPriceProvider().get_daily_bars("BAD")
        assert out.empty
        assert list(out.columns) == ["Open", "High", "Low", "Close", "Volume"]

    def test_get_daily_bars_exception_returns_empty_frame(self):
        with _patch_yf(side_effect=RuntimeError("network")):
            out = YFinanceBulkPriceProvider().get_daily_bars("AAPL")
        assert out.empty

    def test_default_construction_uses_the_real_price_provider(self):
        provider = YFinanceBulkPriceProvider()
        assert isinstance(provider._provider, YFinancePriceProvider)


# --------------------------------------------------------------------------- #
# Fence invariants — the provider layer must not move signals across the tier boundary
# --------------------------------------------------------------------------- #


def test_provider_layer_does_not_import_enrichment_or_engine():
    """The data layer is structural plumbing — it must not pull in enrichment-tier
    modules (sentiment, sector_context, market_conditions) or the deterministic layer
    (engine, execution, strategies). Enforced by a src-level import check so a future
    edit can't accidentally wire a gate to a provider.
    """
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    data_dir = root / "src" / "data"
    forbidden_prefixes = (
        "src.analytics.sentiment",
        "src.analytics.sector_context",
        "src.analytics.market_conditions",
        "src.engine",
        "src.execution",
        "src.strategies",
        "src.claude",
    )
    offenders: list[str] = []
    for path in sorted(data_dir.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith(forbidden_prefixes):
                    offenders.append(f"{path.name}: {node.module}")
            elif isinstance(node, ast.Import):
                for a in node.names:
                    if a.name.startswith(forbidden_prefixes):
                        offenders.append(f"{path.name}: {a.name}")
    assert not offenders, f"src/data/ imports forbidden tiers: {offenders}"
