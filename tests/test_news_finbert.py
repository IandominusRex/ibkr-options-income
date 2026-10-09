from __future__ import annotations

import sys

from src.common.config import get_config
from src.data.protocols import NewsItem
from src.news import tagging


def test_finbert_maps_labels(monkeypatch) -> None:
    monkeypatch.setattr(
        tagging,
        "_finbert_pipeline",
        lambda: lambda text, truncation=True: [{"label": "negative", "score": 0.9}],
    )
    assert tagging.det_sentiment("Profit warning", model="finbert") == -0.9
    monkeypatch.setattr(
        tagging,
        "_finbert_pipeline",
        lambda: lambda text, truncation=True: [{"label": "neutral", "score": 0.99}],
    )
    assert tagging.det_sentiment("Company holds meeting", model="finbert") == 0.0


def test_finbert_positive_label_is_positive(monkeypatch) -> None:
    monkeypatch.setattr(
        tagging,
        "_finbert_pipeline",
        lambda: lambda text, truncation=True: [{"label": "Positive", "score": 0.8}],
    )
    assert tagging.det_sentiment("Record profit", model="finbert") == 0.8


def test_finbert_unavailable_falls_back_to_vader(monkeypatch) -> None:
    monkeypatch.setattr(tagging, "_finbert_pipeline", lambda: None)
    assert tagging.det_sentiment("Stocks crash", model="finbert") == tagging.det_sentiment(
        "Stocks crash", model="vader"
    )


def test_a_failing_finbert_call_falls_back_to_vader(monkeypatch) -> None:
    def boom(text, truncation=True):
        raise RuntimeError("model blew up")

    monkeypatch.setattr(tagging, "_finbert_pipeline", lambda: boom)
    assert tagging.det_sentiment("Stocks crash", model="finbert") == tagging.det_sentiment(
        "Stocks crash", model="vader"
    )


def test_vader_is_the_default_and_never_loads_finbert(monkeypatch) -> None:
    def must_not_load():
        raise AssertionError("FinBERT must not load unless model='finbert'")

    monkeypatch.setattr(tagging, "_finbert_pipeline", must_not_load)
    assert tagging.det_sentiment("Stocks crash as recession fears grow") < 0
    assert tagging.det_sentiment("", model="finbert") == 0.0


def test_pipeline_is_none_without_transformers_and_is_cached(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "transformers", None)  # `import transformers` -> ImportError
    tagging._finbert_pipeline.cache_clear()
    try:
        assert tagging._finbert_pipeline() is None
        assert tagging._finbert_pipeline() is None
        assert tagging._finbert_pipeline.cache_info().hits == 1  # loaded (and warned) once
    finally:
        tagging._finbert_pipeline.cache_clear()


def test_ingest_scores_with_the_configured_model(news_db, monkeypatch) -> None:
    from datetime import UTC, datetime

    from src.news.ingest import ingest
    from src.news.store.models import NewsItemRow
    from src.news.store.session import news_session

    seen: list[str] = []

    def fake(text: str, model: str = "vader") -> float:
        seen.append(model)
        return 0.25

    monkeypatch.setattr(tagging, "det_sentiment", fake)
    cfg = get_config().news.model_copy(deep=True)
    cfg.sentiment.model = "finbert"
    ingest(
        [NewsItem(title="Nvidia beats estimates", url="https://reuters.com/1")],
        category="ticker",
        origin="google",
        alias_index=tagging.build_alias_index(["NVDA"], {}),
        cfg=cfg,
        now=datetime(2026, 10, 9, 14, 0, tzinfo=UTC),
    )
    assert seen == ["finbert"]
    with news_session() as s:
        assert [r.det_sentiment for r in s.query(NewsItemRow)] == [0.25]
