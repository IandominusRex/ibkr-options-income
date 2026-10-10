from __future__ import annotations

from src.common.config import NewsTaggingCfg, get_config
from src.news import tagging, text


def test_canonical_url_strips_tracking_and_case() -> None:
    a = text.canonical_url("HTTPS://WWW.Reuters.com/markets/x?utm_source=tw&id=3&fbclid=zz#frag")
    assert a == "https://www.reuters.com/markets/x?id=3"
    assert text.url_hash("https://a.com/x?utm_medium=y", "T") == text.url_hash(
        "https://a.com/x", "T"
    )
    assert text.url_hash(None, "Fed holds rates").startswith("t:")


def test_normalize_title_drops_google_news_source_suffix() -> None:
    assert (
        text.normalize_title("Fed Holds Rates Steady - Reuters", "Reuters")
        == "fed holds rates steady"
    )
    assert text.title_hash("Fed holds rates steady!", None) == text.title_hash(
        "fed holds  rates steady", None
    )


def test_tokens_and_jaccard() -> None:
    a = text.title_tokens("Nvidia shares fall after export curbs on China")
    b = text.title_tokens("Nvidia stock falls on new China export curbs")
    assert "the" not in a and "nvidia" in a
    assert 0.3 < text.jaccard(a, b) <= 1.0
    assert text.jaccard([], []) == 0.0


def test_domain_of() -> None:
    assert text.domain_of("https://www.cnbc.com/2026/10/09/x.html") == "cnbc.com"
    assert text.domain_of(None) is None


def test_ticker_tagging_requires_word_cashtag_or_alias() -> None:
    idx = tagging.build_alias_index(
        ["NVDA", "GOOGL", "V", "BRK.B"], {"GOOGL": ["Alphabet", "Google"]}
    )
    assert tagging.tag_tickers("Alphabet unveils new chip; NVDA slips", idx) == ["GOOGL", "NVDA"]
    assert tagging.tag_tickers("$V beats on volume", idx) == ["V"]
    # A one-letter ticker never matches as a bare word inside prose ("V-shaped recovery").
    assert tagging.tag_tickers("Markets see a V-shaped recovery", idx) == []
    assert tagging.tag_tickers("BRK.B adds to stake", idx) == ["BRK.B"]
    assert tagging.tag_tickers("Investors cheer Nvidia-adjacent names", idx) == []


def test_event_tags_and_topic() -> None:
    cfg = get_config().news.tagging
    tags = tagging.tag_events(
        "Apple reportedly in talks to buy studio for $5 billion", scheduled=False, cfg=cfg
    )
    assert set(tags) == {"rumor", "quantified"}
    tags = tagging.tag_events("Microsoft raises guidance", scheduled=True, cfg=cfg)
    assert set(tags) == {"forward_looking", "scheduled"}
    assert tagging.topic_class("Ceasefire agreed in Gaza after talks", cfg) == "ceasefire"
    assert tagging.topic_class("Apple launches phone", cfg) == "other"


def test_det_sentiment_range() -> None:
    assert -1.0 <= tagging.det_sentiment("Stocks crash as recession fears grow") < 0
    assert tagging.det_sentiment("") == 0.0


def test_empty_tagging_cfg_is_safe() -> None:
    assert tagging.tag_events("x", scheduled=False, cfg=NewsTaggingCfg()) == []


def test_newsitem_new_fields_default_none() -> None:
    from src.data.protocols import NewsItem

    item = NewsItem(title="x")
    assert item.summary is None and item.image_url is None
    assert NewsItem(title="x", summary="s", image_url="u").image_url == "u"


def test_cluster_tokens_drop_template_words() -> None:
    """Benzinga's "Why Is X Stock Falling Thursday?" template must not join two companies."""
    arm = text.title_tokens("Why Is Arm Stock Falling Thursday?")
    asts = text.title_tokens("Why Is AST SpaceMobile Stock Falling Thursday?")
    assert text.jaccard(arm, asts) >= 0.5  # the raw tokens DID clear the 0.5 threshold
    assert text.cluster_tokens(arm) == {"arm"}
    assert text.jaccard(text.cluster_tokens(arm), text.cluster_tokens(asts)) == 0.0


def test_is_noise_flags_law_firm_solicitations() -> None:
    terms = get_config().news.tagging.noise_terms
    assert tagging.is_noise(
        "ASTS Investors Have Opportunity to Lead AST SpaceMobile, Inc. Securities Fraud Lawsuit",
        terms,
    )
    assert not tagging.is_noise(
        "AST SpaceMobile Falls 6% as SpaceX Spectrum Deal Closes Off Low-Band Option", terms
    )
