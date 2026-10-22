"""Task 8: the one neutral renderer every reader uses for the market picture."""

from __future__ import annotations

import ast
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from src.common.picture_text import render_picture
from src.common.schemas import (
    MarketPicture,
    MarketRegime,
    NoiseSummary,
    PictureFact,
    PictureRegime,
    PictureStory,
    SeasonalityView,
)

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 22, 15, tzinfo=UTC)  # 11:00 ET


def _regime(index, effective, base=None, *, eased=False, suspended=False) -> PictureRegime:
    return PictureRegime(
        index=index,
        effective=effective,
        base=base or effective,
        eased_by_bottoming=eased,
        suspended=suspended,
        as_of=NOW,
    )


def _picture(**kw) -> MarketPicture:
    base = dict(
        version=NOW.isoformat(),
        built_at=NOW - timedelta(hours=2),
        regimes=[
            _regime("SPY", MarketRegime.NORMAL),
            _regime("QQQ", MarketRegime.STRESSED, MarketRegime.CAUTIOUS, eased=True),
        ],
        facts=[
            PictureFact(label="SPY close", value="560.12"),
            PictureFact(label="VIX", value="23.4"),
        ],
        seasonality=SeasonalityView(month=10, avg_return_pct=1.2, up_share=0.6, years=5),
        events=["FOMC Wed 14:00 ET", "NVDA earnings Thu AMC"],
        stories=[
            PictureStory(
                id=3,
                title="Tariff escalation",
                started_on=date(2026, 10, 12),
                description="Tariff headlines keep the index under its 50-day average.",
                evidence=["C41"],
            )
        ],
        noise=NoiseSummary(judged=12, not_reviewed=340, promotions=1),
    )
    base.update(kw)
    return MarketPicture(**base)


def test_render_picture_lines_and_stale_prefix() -> None:
    text = render_picture(_picture(), now=NOW, staleness_hours=26)
    lines = text.splitlines()
    assert lines[0] == "=== MARKET PICTURE ==="
    assert "SPY: normal" in lines
    assert "QQQ: stressed (base cautious; eased by a bottoming signal)" in lines
    assert "SPY close: 560.12" in text and "VIX: 23.4" in text
    assert any(
        ln.startswith("Seasonality (weak signal):") and "5-year" in ln and "October" in ln
        for ln in lines
    )
    assert "FOMC Wed 14:00 ET" in text and "NVDA earnings Thu AMC" in text
    assert (
        "S3 Tariff escalation (since Oct 12): "
        "Tariff headlines keep the index under its 50-day average." in lines
    )
    assert "STALE" not in text

    # older than the staleness limit, or flagged stale by a failed rebuild: say so up front
    old = render_picture(_picture(built_at=NOW - timedelta(hours=30)), now=NOW, staleness_hours=26)
    assert old.splitlines()[1].startswith("PICTURE IS STALE (built ")
    flagged = render_picture(_picture(stale=True), now=NOW, staleness_hours=26)
    assert flagged.splitlines()[1].startswith("PICTURE IS STALE (built ")


def test_render_picture_says_when_the_limits_are_suspended_and_where_the_regime_came_from() -> None:
    p = _picture(
        regimes=[_regime("SPY", MarketRegime.CRISIS, suspended=True)], regime_source="news"
    )
    text = render_picture(p, now=NOW, staleness_hours=26)
    assert "SPY: crisis (limits suspended today)" in text
    assert "estimated by the news service" in text  # not the trading process's own record


def test_render_picture_unavailable() -> None:
    assert (
        render_picture(None, now=NOW, staleness_hours=26) == "=== MARKET PICTURE ===\n(unavailable)"
    )


def test_render_picture_omits_what_it_does_not_have() -> None:
    p = _picture(facts=[], seasonality=None, events=[], stories=[])
    text = render_picture(p, now=NOW, staleness_hours=26)
    assert "Seasonality" not in text and "Upcoming" not in text and "S3" not in text


def test_render_picture_stays_short() -> None:
    stories = [
        PictureStory(
            id=i,
            title=f"Story number {i} about the market",
            started_on=date(2026, 10, 1),
            description=(
                "Tariff headlines and a firmer dollar keep the index under its fifty day "
                "average while volatility stays high."
            ),
            evidence=["C1"],
        )
        for i in range(1, 6)
    ]
    facts = [PictureFact(label=f"Fact label {i}", value=f"{i}.5%") for i in range(12)]
    text = render_picture(_picture(stories=stories, facts=facts), now=NOW, staleness_hours=26)
    assert len(text.split()) <= 300


def test_picture_text_imports_only_common() -> None:
    tree = ast.parse((ROOT / "src" / "common" / "picture_text.py").read_text(encoding="utf-8"))
    mods: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            mods.append(node.module)
        elif isinstance(node, ast.Import):
            mods.extend(a.name for a in node.names)
    internal = [m for m in mods if m == "src" or m.startswith("src.")]
    assert internal == ["src.common.schemas"], internal
