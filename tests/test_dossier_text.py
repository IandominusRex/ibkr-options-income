"""The one neutral rendering of a ticker dossier (Task 17).

Every reader (the trade and roll reviews, ``/scan``) shows the model the same block, so a name can
never read differently in two places. Compact (a few dozen words, for the many names of a full
scan) and full (for the one name a deep-dive or a roll is about). Neutral module: it imports only
``src.common.schemas``.
"""

from __future__ import annotations

import ast
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from src.common.dossier_text import render_dossier, render_dossiers
from src.common.schemas import DossierEvent, DossierFact, TickerDossier
from tests.test_dossier_store import dossier

NOW = datetime(2026, 10, 22, 15, tzinfo=UTC)
STALENESS = 26.0

LABELS = [
    ("Move today", "+1.0%"),
    ("Move in σ", "0.4σ"),
    ("SPY today", "-1.0%"),
    ("RSI14", "RSI 52"),
    ("Price vs SMA200", "+4.1% vs SMA200"),
    ("Nearest support", "$191.00 (-4.0%)"),
    ("Nearest resistance", "$208.00 (+4.5%)"),
    ("IV rank", "IV rank 55"),
    ("IV30 vs HV30", "IV 40% vs HV 30%"),
    ("IV-implied 1-day move", "±2.5%"),
    ("Earnings date", "2026-11-05 AMC"),
    ("Universe", "would_own, actively_wheeling"),
    ("1-month return", "+11.8% (21 sessions)"),
    ("3-month return", "+46.3% (63 sessions)"),
    ("Regime index", "QQQ"),
]


def fat(symbol: str = "META", *, long: bool = False, **kw) -> TickerDossier:
    facts = [
        DossierFact(id=f"{symbol}:F{i}", label=label, display=display)
        for i, (label, display) in enumerate(LABELS, 1)
    ]
    story = " ".join(["Meta keeps spending heavily on AI infrastructure"] * 5)[:280]
    events = [
        DossierEvent(
            id=f"{symbol}:E{i}",
            title=f"MUSE launch event number {i} with a long descriptive title text here",
            on=date(2026, 10, 22 + i),
            evidence=f"C{8120 + i}",
            quote="x",
        )
        for i in range(1, 4)
    ]
    base = dict(
        facts=facts,
        story=story if long else "Launching a new glasses line next week.",
        story_evidence=["C8123", "C8124"],
        events=events if long else events[:1],
        profile=("A social-media and AI company; ad revenue and capex drive the shares. " * 5)[:400]
        if long
        else "A social-media and AI company.",
        health_why=["passes the quality screen", "debt/equity 1.5x"],
        sentiment_7d=0.12,
        sentiment_items_7d=14,
    )
    base.update(kw)
    return dossier(symbol, NOW, **base)


def words(text: str) -> int:
    return len(text.split())


def test_render_compact_within_80_words_and_full_within_220() -> None:
    for long in (False, True):
        d = fat(long=long)
        compact = render_dossier(d, symbol="META", now=NOW, staleness_hours=STALENESS, compact=True)
        full = render_dossier(d, symbol="META", now=NOW, staleness_hours=STALENESS, compact=False)
        assert words(compact) <= 80, (long, words(compact), compact)
        assert words(full) <= 220, (long, words(full), full)
        assert compact.startswith("--- META (stock · health strong) ---")
        assert len(full) > len(compact)


def test_the_word_budget_holds_for_any_mix_of_lengths() -> None:
    import itertools

    for story_len, n_events, profile_len, n_why, n_facts in itertools.product(
        (0, 60, 280), (0, 1, 3), (0, 400), (0, 1, 3), (0, 3, 15)
    ):
        d = fat(
            long=True,
            story=("steady growth in cloud revenue and heavy capital spending " * 6)[:story_len],
            events=fat(long=True).events[:n_events],
            profile=("a large software and cloud company whose shares track rates " * 8)[
                :profile_len
            ],
            health_why=["passes the quality screen", "debt/equity 1.5x", "free cash flow unknown"][
                :n_why
            ],
            facts=fat().facts[:n_facts],
        )
        for compact, limit in ((True, 80), (False, 220)):
            text = render_dossier(
                d, symbol="META", now=NOW, staleness_hours=STALENESS, compact=compact
            )
            assert words(text) <= limit, (compact, story_len, n_events, profile_len, n_why, n_facts)


def test_compact_shows_health_story_events_and_three_preferred_facts() -> None:
    d = fat()
    text = render_dossier(d, symbol="META", now=NOW, staleness_hours=STALENESS, compact=True)
    assert "passes the quality screen" in text
    assert "debt/equity 1.5x" not in text  # compact: the first health reason only
    assert "Launching a new glasses line next week." in text and "C8123" in text
    assert "META:E1 MUSE launch event number 1" in text and "2026-10-23" in text
    # the preference order: Price vs SMA200, RSI14, IV rank (then resistance, support)
    shown = [line for line in text.splitlines() if line.startswith("META:F")]
    assert [line.split(" ", 1)[0] for line in shown] == ["META:F5", "META:F4", "META:F8"]
    assert "Profile" not in text and "Sentiment" not in text


def test_full_adds_the_profile_every_fact_and_the_sentiment() -> None:
    d = fat()
    text = render_dossier(d, symbol="META", now=NOW, staleness_hours=STALENESS, compact=False)
    assert "Profile (Claude's summary, general knowledge): A social-media and AI company." in text
    assert "debt/equity 1.5x" in text and "passes the quality screen" in text
    assert "META:F1 Move today: +1.0%" in text and "META:F15 Regime index: QQQ" in text
    assert "7-day news sentiment +0.12 over 14 items" in text


def test_render_labels_the_profile_and_the_stale_prefix() -> None:
    d = fat()
    fresh = render_dossier(d, symbol="META", now=NOW, staleness_hours=STALENESS, compact=False)
    assert "PROSE IS STALE" not in fresh
    # prose older than the limit
    old = fat(prose_at=NOW - timedelta(hours=30))
    text = render_dossier(old, symbol="META", now=NOW, staleness_hours=STALENESS, compact=True)
    assert "PROSE IS STALE (built Oct 21 05:00 ET)" in text
    # or marked stale because a rebuild failed
    failed = fat(stale=True)
    text = render_dossier(failed, symbol="META", now=NOW, staleness_hours=STALENESS, compact=False)
    assert "PROSE IS STALE (built Oct 22 09:00 ET)" in text
    # the stale line sits right under the header, before the prose it qualifies
    lines = text.splitlines()
    assert lines[0].startswith("--- META") and lines[1].startswith("PROSE IS STALE")


def test_a_dossier_with_numbers_only_says_the_prose_is_not_written() -> None:
    d = fat(prose_at=None, profile_at=None, story="", story_evidence=[], events=[], profile="")
    text = render_dossier(d, symbol="META", now=NOW, staleness_hours=STALENESS, compact=True)
    assert "Notes not written yet (numbers only)" in text
    assert "Story" not in text and "PROSE IS STALE" not in text


def test_render_without_a_dossier() -> None:
    text = render_dossier(None, symbol="AMD", now=NOW, staleness_hours=STALENESS, compact=True)
    assert text == "--- AMD --- (no notes yet)"
    block = render_dossiers(
        [("AMD", None), ("META", fat())], now=NOW, staleness_hours=STALENESS, compact=True
    )
    assert block.startswith("=== NAME NOTES ===\n--- AMD --- (no notes yet)\n")
    assert "--- META (stock · health strong) ---" in block
    assert render_dossiers([], now=NOW, staleness_hours=STALENESS, compact=True) == ""


def test_kind_and_health_read_in_the_header() -> None:
    etf = fat("TQQQ", kind="leveraged_etf", health="n/a", health_why=[])
    text = render_dossier(etf, symbol="TQQQ", now=NOW, staleness_hours=STALENESS, compact=True)
    assert text.splitlines()[0] == "--- TQQQ (leveraged ETF · health n/a) ---"
    plain = fat("QQQ", kind="etf", health="n/a", health_why=[])
    text = render_dossier(plain, symbol="QQQ", now=NOW, staleness_hours=STALENESS, compact=True)
    assert text.splitlines()[0] == "--- QQQ (ETF · health n/a) ---"
    weak = fat(health="weak", health_why=["free cash flow negative"])
    text = render_dossier(weak, symbol="META", now=NOW, staleness_hours=STALENESS, compact=True)
    assert "health weak" in text.splitlines()[0] and "free cash flow negative" in text


def test_dossier_text_imports_only_common() -> None:
    path = Path(__file__).resolve().parents[1] / "src" / "common" / "dossier_text.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "relative import"
            mods.add(node.module or "")
    src_mods = {m for m in mods if m.startswith("src")}
    assert src_mods == {"src.common.schemas"}, src_mods
