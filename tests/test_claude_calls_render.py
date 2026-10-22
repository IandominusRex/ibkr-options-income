"""OI-F3: every block the What Claude knows page claims a Claude call reads is in the real prompt.

`src/api/claude_calls.py::CALLS` is a static map (the API process must not load the prompt
builders). `tests/test_api_claude_context.py::test_every_block_header_occurs_in_its_builder_file`
only checks that each header's text occurs in the *source file* that emits it, which cannot tell a
header that a builder really prints from one that sits in a docstring, a comment or a branch that
never runs. This renders each real prompt builder with fixture data (the real block renderers
feed it, so the headers are the ones the model is sent) and requires every block of the call's
tile to appear in the rendered prompt. All seven calls render offline; nothing here touches the
network, a model, IBKR or the stored picture.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from src.api.claude_calls import CALLS, Call
from src.claude import news_context
from src.claude.book_context import render_book
from src.claude.dossier_context import dossier_block
from src.claude.prompts.eod import build_eod_prompt
from src.claude.prompts.roll import build_roll_prompt
from src.claude.prompts.strategist import build_prompt
from src.common.picture_text import render_picture
from src.common.schemas import Strategy
from src.data.protocols import NewsItem
from src.news.prompts import DossierPromptEntry, digest_prompt, dossier_prompt
from src.news.schemas import ClusterView, FactSheet
from src.spreads_ai.prompts import build_pick_prompt
from tests.test_claude import _make_account, _make_candidate
from tests.test_dossier_build import facts_for
from tests.test_dossier_readers import _alert, _pos, _quote
from tests.test_dossier_store import dossier
from tests.test_eod import _make_eod_summary
from tests.test_picture_readers import _picture
from tests.test_spreads_ai_prompts import MARKET, request

NOW = datetime(2026, 10, 22, 15, tzinfo=UTC)


def _picture_text(*, regime_as_of: bool = False) -> str:
    return render_picture(_picture(NOW), now=NOW, staleness_hours=26, regime_as_of=regime_as_of)


def _notes(compact: bool = True) -> str:
    return dossier_block(
        ["TQQQ"], {"TQQQ": dossier("TQQQ", NOW)}, now=NOW, compact=compact, max_names=8
    )


def _book() -> str:
    return render_book(
        [_csp()],
        [_pos()],
        stopouts={},
        tech_linked=["TQQQ"],
        net_delta=-120.0,
        spots={"TQQQ": 76.1},
    )


def _news(monkeypatch: pytest.MonkeyPatch) -> str:
    items = [
        NewsItem(id="", title="TQQQ slides with the index", source="A", published=None, url=None)
    ]
    monkeypatch.setattr(news_context, "_fetch", lambda sym, days, limit: items)
    block, _index = news_context.build_news_block(["TQQQ"], per_symbol=5, days=7)
    assert block  # the fixture really produced a block
    return block


def _sector() -> str:
    from src.analytics.sector_context import SectorContext, render_sector_context

    return render_sector_context(
        SectorContext(
            symbol="TQQQ",
            sector="Index",
            industry="Leveraged",
            sector_etf="QQQ",
            sector_ret_1mo_pct=-3.2,
            spy_ret_1mo_pct=-1.4,
            symbol_ret_1mo_pct=-9.1,
            rel_strength_1mo_pct=-7.7,
        )
    )


def _csp():
    from src.common.schemas import OptionRight

    return _make_candidate(
        "c-1",
        strategy=Strategy.CASH_SECURED_PUT,
        underlying="TQQQ",
        strike=60.0,
        right=OptionRight.PUT,
    )


def _cluster(cid: int = 101) -> ClusterView:
    return ClusterView(
        id=cid,
        headline="Tariffs widen to chips",
        category="macro",
        first_seen=NOW,
        last_seen=NOW,
        source_count=3,
        tickers=["TQQQ"],
        topic_class="tariff",
    )


# One renderer per call kind: the real builder, fed the real block renderers and fixtures.
Renderer = Callable[[pytest.MonkeyPatch], str]

RENDER: dict[str, Renderer] = {
    "trade_review": lambda mp: build_prompt(
        [_csp()],
        _make_account(),
        news_block=_news(mp),
        picture_block=_picture_text(),
        book_block=_book(),
        dossier_block=_notes(compact=True),
    ),
    "roll_review": lambda mp: build_roll_prompt(
        _alert(),
        _pos(),
        _quote(),
        proposal="ROLL 78P -> 72P for +$0.06",
        picture_block=_picture_text(),
        dossier_block=_notes(compact=False),
    ),
    "spreads_picker": lambda mp: build_pick_prompt(
        request(), MARKET.model_copy(update={"picture_text": _picture_text(regime_as_of=True)})
    ),
    "news_expert": lambda mp: digest_prompt(
        [_cluster()], FactSheet(), picture_text=_picture_text()
    ),
    "eod_journal": lambda mp: build_eod_prompt(_make_eod_summary(), picture_block=_picture_text()),
    "scan": lambda mp: build_prompt(
        [_csp()],
        _make_account(),
        single_ticker=True,
        sector_context=_sector(),
        news_block=_news(mp),
        picture_block=_picture_text(),
        dossier_block=_notes(compact=False),
    ),
    "dossier_builder": lambda mp: dossier_prompt(
        [DossierPromptEntry("TQQQ", "leveraged_etf", facts_for("TQQQ"), [_cluster()], True)],
        _picture_text(),
    ),
}


def has_block(prompt: str, header: str) -> bool:
    """True when *header* is a block banner of *prompt*: a line that starts with ``===`` and holds
    it, or a bare label line that is exactly it. A mention inside the rules' prose does not count
    (the strategist's rubric names the sector backdrop in a sentence whether or not the block is
    there)."""
    for raw in prompt.splitlines():
        line = raw.strip()
        if line == header or (line.startswith("===") and header in line):
            return True
    return False


def missing_blocks(call: Call, prompt: str) -> list[str]:
    """The labels of the call's blocks whose header is not a block banner of *prompt*."""
    return [b.label for b in call.blocks if not has_block(prompt, b.header)]


def test_every_call_on_the_page_has_a_renderer_and_every_renderer_a_call() -> None:
    """A new call kind must come with a render test; none is left on the source-text check alone."""
    assert {c.kind for c in CALLS} == set(RENDER)


@pytest.mark.parametrize("call", CALLS, ids=[c.kind for c in CALLS])
def test_every_block_of_a_call_is_in_the_prompt_the_builder_really_renders(
    call: Call, monkeypatch: pytest.MonkeyPatch
) -> None:
    prompt = RENDER[call.kind](monkeypatch)
    assert prompt.strip(), call.kind
    assert missing_blocks(call, prompt) == [], (
        f"{call.kind}: the page lists blocks the rendered prompt does not contain"
    )


def test_the_check_has_teeth_a_dropped_block_is_reported() -> None:
    """The same builders without a block: the check names exactly the block that went missing."""
    by_kind = {c.kind: c for c in CALLS}
    no_notes = build_prompt(
        [_csp()], _make_account(), picture_block=_picture_text(), book_block=_book()
    )
    assert "Name notes" in missing_blocks(by_kind["trade_review"], no_notes)
    no_picture = build_roll_prompt(_alert(), _pos(), _quote(), proposal="HOLD")
    assert missing_blocks(by_kind["roll_review"], no_picture) == ["Market picture", "Name notes"]
    bare_eod = build_eod_prompt(_make_eod_summary())
    assert missing_blocks(by_kind["eod_journal"], bare_eod) == ["Market picture"]


def test_a_header_named_in_the_rules_prose_is_not_a_block() -> None:
    """The scan prompt's rubric talks about the sector backdrop; only the block itself counts."""
    by_kind = {c.kind: c for c in CALLS}
    prompt = build_prompt([_csp()], _make_account(), single_ticker=True)  # no sector block
    assert "SECTOR & MARKET BACKDROP" in prompt  # said in the rubric
    assert "Sector" in missing_blocks(by_kind["scan"], prompt)
    assert not has_block(prompt, "SECTOR & MARKET BACKDROP")
    with_block = build_prompt(
        [_csp()], _make_account(), single_ticker=True, sector_context=_sector()
    )
    assert has_block(with_block, "SECTOR & MARKET BACKDROP")


def test_the_market_picture_header_is_the_one_the_neutral_renderer_emits() -> None:
    """Every reader gets the picture block from `common/picture_text.py`; its header is the
    page's "Market picture" chip for every call that carries one."""
    headers = {b.header for c in CALLS for b in c.blocks if b.label.startswith("Market picture")}
    assert headers == {"MARKET PICTURE"}
    assert "=== MARKET PICTURE ===" in _picture_text()
