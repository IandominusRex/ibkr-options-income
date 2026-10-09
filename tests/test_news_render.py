from __future__ import annotations

import time
from datetime import UTC, datetime

import pytest

from src.news.render import fmt_when, render_card, split_message
from src.news.schemas import (
    CardPayload,
    DigestItem,
    DigestSection,
    Explanation,
    GridRow,
    SourceLink,
)

WHEN = datetime(2026, 10, 14, 12, 30, tzinfo=UTC)


def _macro(**kw) -> CardPayload:
    base = dict(
        kind="macro_print",
        title="CPI hotter than expected",
        emoji="🔴",
        when=WHEN,
        headline_line="Sep CPI +0.4% m/m vs +0.3% est",
        grid=[
            GridRow(asset="stocks", textbook="🔴", actual="🔴 ES=F -1.20%"),
            GridRow(asset="bonds", textbook="🔴", actual=None),
        ],
        links=[SourceLink(name="BLS", url="https://www.bls.gov/x?a=1&b=2")],
    )
    base.update(kw)
    return CardPayload(**base)


def test_when_shows_sgt_and_et() -> None:
    assert fmt_when(WHEN) == "20:30 SGT (08:30 ET)"
    assert (
        fmt_when(datetime(2026, 11, 3, 13, 30, tzinfo=UTC)) == "21:30 SGT (08:30 ET)"
    )  # after US DST ends


def test_macro_card_layout() -> None:
    m = render_card(_macro())
    assert m.text.startswith("🔴 <b>CPI hotter than expected</b> · 20:30 SGT (08:30 ET)")
    assert "<pre>" in m.text and "📘 Textbook" in m.text and "Stocks" in m.text
    assert '<a href="https://www.bls.gov/x?a=1&amp;b=2">BLS</a>' in m.text


def test_explanation_sections_and_verdict_label() -> None:
    e = Explanation(
        headline="h",
        what_happened="w",
        read="Inflation re-accelerating.",
        bull="core cooling",
        bear="shelter sticky",
        verdict="further_downside_likely",
        confidence="medium",
        book_impact="NVDA 165P 3.1% OTM",
        setup_impact="",
        evidence=["F1"],
    )
    t = render_card(_macro(explanation=e)).text
    assert "🧠 Inflation re-accelerating." in t
    assert "⚖️ Bull: core cooling · Bear: shelter sticky" in t
    assert "🎯 Further downside likely · medium" in t
    assert "💼 NVDA 165P 3.1% OTM" in t and "🛒" not in t


def test_every_dynamic_field_is_escaped() -> None:
    evil = "<b>x</b> & <script>"
    e = Explanation(
        headline=evil,
        what_happened=evil,
        read=evil,
        bull=evil,
        bear=evil,
        verdict="unclear",
        confidence="low",
        book_impact=evil,
        setup_impact=evil,
        evidence=[],
    )
    p = _macro(
        title=evil,
        headline_line=evil,
        facts_line=evil,
        explanation=e,
        grid=[GridRow(asset=evil, textbook=evil, actual=evil)],
        links=[SourceLink(name=evil, url='https://x.com/"><script>')],
        updates=[evil],
        sections=[DigestSection(title=evil, items=[DigestItem(text=evil, read=evil, links=[])])],
    )
    t = render_card(p).text
    assert "<script>" not in t and "<b>x</b>" not in t
    assert "&lt;b&gt;x&lt;/b&gt; &amp; &lt;script&gt;" in t


def test_preview_prefers_image() -> None:
    m = render_card(_macro(image_url="https://img/x.png", preview_url="https://article"))
    assert m.preview_url == "https://img/x.png" and m.show_above
    m2 = render_card(_macro(preview_url="https://article"))
    assert m2.preview_url == "https://article" and not m2.show_above


def test_split_respects_limit_and_blocks() -> None:
    text = "\n\n".join(["A" * 3000, "B" * 3000, "C" * 5000])
    parts = split_message(text, 4096)
    assert all(len(p) <= 4096 for p in parts)
    assert parts[0] == "A" * 3000 and parts[1] == "B" * 3000


def test_naive_when_is_read_as_utc_not_local(monkeypatch: pytest.MonkeyPatch) -> None:
    # The store keeps naive-UTC; a card built from a DB row must not shift by the host's zone.
    monkeypatch.setenv("TZ", "America/Los_Angeles")
    time.tzset()
    try:
        assert fmt_when(WHEN.replace(tzinfo=None)) == "20:30 SGT (08:30 ET)"
    finally:
        monkeypatch.undo()
        time.tzset()
