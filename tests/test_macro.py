"""Tests for the macro backdrop (src/analytics/market_conditions.py).

Before this the entire macro layer was a single VIX number. These cover the added signals —
VIX term structure, 10-year rates, the SPY tape, broad-market headline tone — and, most
importantly, that every one of them is independently fail-soft: no macro source is allowed to
break a scan, because macro is enrichment and the deterministic pipeline must not depend on it.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.analytics import market_conditions as mc_mod
from src.common.cache import clear_all
from src.common.schemas import MarketConditions


@pytest.fixture(autouse=True)
def _clear_caches():
    """The macro fetchers are @daily_cached — clear between tests or stubs leak across them."""
    clear_all()
    yield
    clear_all()


def _stub_all(monkeypatch, **overrides) -> None:
    defaults = {
        "_fetch_index_level": lambda sym: {"^VIX": 18.0, "^VIX3M": 20.0}.get(sym),
        "_fetch_ten_year": lambda: (4.31, 12.0),
        "_fetch_spy_5d_return": lambda: -0.8,
        "_fetch_macro_headlines": lambda: (41.0, 7, "Rates jump on hot CPI print"),
    }
    defaults.update(overrides)
    for name, fn in defaults.items():
        monkeypatch.setattr(mc_mod, name, fn)


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def test_get_market_conditions_assembles_every_signal(monkeypatch) -> None:
    _stub_all(monkeypatch)
    mc = mc_mod.get_market_conditions()
    assert mc.vix == 18.0
    assert mc.vix3m == 20.0
    assert mc.vix_term_ratio == 0.9
    assert mc.ten_year_yield == 4.31
    assert mc.ten_year_change_5d_bp == 12.0
    assert mc.spy_ret_5d_pct == -0.8
    assert mc.macro_headline_score == 41.0
    assert mc.macro_headline_count == 7
    assert mc.top_macro_headline is not None


def test_term_ratio_above_one_is_backwardation(monkeypatch) -> None:
    """Near-term fear above 3-month fear — the regime where a naive IV-rank screen misleads."""
    _stub_all(monkeypatch, _fetch_index_level=lambda sym: {"^VIX": 30.0, "^VIX3M": 25.0}.get(sym))
    assert mc_mod.get_market_conditions().vix_term_ratio == 1.2


def test_term_ratio_is_none_without_both_legs(monkeypatch) -> None:
    _stub_all(monkeypatch, _fetch_index_level=lambda sym: 18.0 if sym == "^VIX" else None)
    mc = mc_mod.get_market_conditions()
    assert mc.vix == 18.0
    assert mc.vix_term_ratio is None


def test_every_source_failing_still_returns_a_snapshot(monkeypatch) -> None:
    """The whole point: a dead macro feed degrades the read, it never fails the scan."""
    _stub_all(
        monkeypatch,
        _fetch_index_level=lambda sym: None,
        _fetch_ten_year=lambda: (None, None),
        _fetch_spy_5d_return=lambda: None,
        _fetch_macro_headlines=lambda: (None, 0, None),
    )
    mc = mc_mod.get_market_conditions()
    assert mc.vix is None and mc.ten_year_yield is None and mc.macro_headline_count == 0


def test_index_level_returns_none_when_provider_raises(monkeypatch) -> None:
    provider = MagicMock()
    provider.get_last_price.side_effect = RuntimeError("network down")
    provider.get_ohlcv.side_effect = RuntimeError("network down")
    from src.data import factory as data_factory

    data_factory.get_price_provider.cache_clear()
    monkeypatch.setattr("src.data.factory.get_price_provider", lambda: provider)
    assert mc_mod._fetch_index_level("^VIX") is None


def test_ten_year_returns_none_when_provider_raises(monkeypatch) -> None:
    provider = MagicMock()
    provider.get_ohlcv.side_effect = RuntimeError("network down")
    from src.data import factory as data_factory

    data_factory.get_price_provider.cache_clear()
    monkeypatch.setattr("src.data.factory.get_price_provider", lambda: provider)
    assert mc_mod._fetch_ten_year() == (None, None)


def test_spy_return_is_none_without_enough_history(monkeypatch) -> None:
    import pandas as pd

    monkeypatch.setattr(
        "src.analytics.price_data.get_ohlcv", lambda s: pd.DataFrame({"Close": [1.0, 2.0]})
    )
    assert mc_mod._fetch_spy_5d_return() is None


def test_spy_return_computes_the_five_session_change(monkeypatch) -> None:
    import pandas as pd

    closes = [100.0, 101.0, 102.0, 103.0, 104.0, 110.0]
    monkeypatch.setattr(
        "src.analytics.price_data.get_ohlcv", lambda s: pd.DataFrame({"Close": closes})
    )
    assert mc_mod._fetch_spy_5d_return() == 10.0


def test_macro_headlines_average_across_sources(monkeypatch) -> None:
    scores = {"SPY": (40.0, 4, "SPY headline"), "QQQ": (60.0, 6, "QQQ headline")}
    monkeypatch.setattr("src.analytics.sentiment._fetch_news", lambda s: scores[s])
    score, count, top = mc_mod._fetch_macro_headlines()
    assert score == 50.0
    assert count == 10
    assert top == "SPY headline"


def test_macro_headlines_tolerate_one_dead_source(monkeypatch) -> None:
    def _news(symbol):
        if symbol == "SPY":
            raise RuntimeError("boom")
        return 60.0, 6, "QQQ headline"

    monkeypatch.setattr("src.analytics.sentiment._fetch_news", _news)
    score, count, _ = mc_mod._fetch_macro_headlines()
    assert score == 60.0 and count == 6


def test_macro_headlines_none_when_no_source_returns_data(monkeypatch) -> None:
    monkeypatch.setattr("src.analytics.sentiment._fetch_news", lambda s: (None, 0, None))
    assert mc_mod._fetch_macro_headlines() == (None, 0, None)


# ---------------------------------------------------------------------------
# Prompt rendering
# ---------------------------------------------------------------------------


def test_render_macro_context_includes_every_available_row() -> None:
    text = mc_mod.render_macro_context(
        MarketConditions(
            vix=18.4,
            vix3m=20.0,
            vix_term_ratio=0.92,
            ten_year_yield=4.31,
            ten_year_change_5d_bp=12.0,
            spy_ret_5d_pct=-0.8,
            macro_headline_score=41.0,
            macro_headline_count=7,
            top_macro_headline="Rates jump on hot CPI print",
        )
    )
    assert "MACRO BACKDROP" in text
    assert "VIX: 18.4" in text
    assert "contango" in text
    assert "4.31%" in text and "+12bp" in text
    assert "SPY 5-session: -0.8%" in text
    assert "Rates jump" in text


def test_render_macro_context_names_backwardation() -> None:
    text = mc_mod.render_macro_context(MarketConditions(vix=30.0, vix_term_ratio=1.2))
    assert "backwardation" in text


def test_render_macro_context_is_empty_without_data() -> None:
    assert mc_mod.render_macro_context(MarketConditions()) == ""
    assert mc_mod.render_macro_context(None) == ""


@pytest.mark.parametrize(
    ("vix", "word"),
    [(12.0, "calm"), (18.0, "normal"), (25.0, "elevated"), (40.0, "stressed")],
)
def test_vix_regime_thresholds(vix: float, word: str) -> None:
    assert word in mc_mod.vix_regime(vix)


def test_prompt_vix_context_delegates_to_the_shared_regime() -> None:
    from src.claude.prompts.strategist import _vix_context

    assert mc_mod.vix_regime(25.0) in _vix_context(25.0)
    assert _vix_context(None) == "VIX: unavailable"
