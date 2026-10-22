"""Task 13: the roll review, the EOD journal and the spreads picker read the market picture too.

Each still does exactly what it did: the roll reviewer only agrees or disagrees with the
deterministic policy, the EOD journal only writes a narrative, the spreads picker only returns a
menu letter. The picture is context in the prompt and nothing else."""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import src.claude.ollama_runner as ollama_mod
import src.spreads_ai.context as ctx
from src.claude import runner
from src.claude.prompts.eod import build_eod_prompt
from src.claude.prompts.roll import build_roll_prompt
from src.common.picture_text import render_picture
from src.common.schemas import (
    MarketConditions,
    MarketPicture,
    MarketRegime,
    OptionQuote,
    OptionRight,
    PictureFact,
    PictureRegime,
    PictureStory,
    PositionSnapshot,
    RollAlert,
    SpreadBriefRequest,
    SpreadMarketSnapshot,
    SpreadTapeStats,
    TechnicalStats,
)
from src.spreads_ai.prompts import build_brief_prompt, build_pick_prompt
from tests.test_eod import _make_eod_summary
from tests.test_spreads_ai_prompts import EXITS, LEVELS, MARKET, request
from tests.test_spreads_ai_prompts import NOW as SPREADS_NOW
from tests.test_spreads_fence import ROOT, SPREADS_AI, imported_modules

NOW = datetime(2026, 10, 22, 15, tzinfo=UTC)
BLOCK = "=== MARKET PICTURE ===\nQQQ: stressed\nS3 Tariff escalation (since Oct 12)"


def _picture(built_at: datetime = NOW) -> MarketPicture:
    return MarketPicture(
        version=built_at.isoformat(),
        built_at=built_at,
        regimes=[
            PictureRegime(
                index="SPY", effective=MarketRegime.NORMAL, base=MarketRegime.NORMAL, as_of=built_at
            ),
            PictureRegime(
                index="QQQ",
                effective=MarketRegime.STRESSED,
                base=MarketRegime.CAUTIOUS,
                as_of=built_at,
            ),
        ],
        facts=[PictureFact(label="VIX", value="23.4")],
        stories=[
            PictureStory(
                id=3,
                title="Tariff escalation",
                started_on=date(2026, 10, 12),
                description="Tariff headlines keep the index under its 50-day average.",
                evidence=["C41"],
            )
        ],
    )


def _save(picture: MarketPicture) -> None:
    from src.news.store.models import MarketPictureRow
    from src.news.store.queries import naive_utc
    from src.news.store.session import news_session

    with news_session() as s:
        s.add(
            MarketPictureRow(
                built_at=naive_utc(picture.built_at),
                version=picture.version,
                payload=picture.model_dump(mode="json"),
                stale=False,
            )
        )


def _alert() -> RollAlert:
    return RollAlert(
        position_symbol="TQQQ 78P", underlying="TQQQ", trigger="delta_drift", detail="delta 0.62"
    )


def _pos() -> PositionSnapshot:
    return PositionSnapshot(
        symbol="TQQQ 78P",
        sec_type="OPT",
        position=-10,
        avg_cost=1.2,
        right=OptionRight.PUT,
        strike=78.0,
        expiry=date(2026, 10, 30),
        underlying="TQQQ",
        delta=-0.3,
    )


def _quote() -> OptionQuote:
    return OptionQuote(
        underlying="TQQQ",
        right=OptionRight.PUT,
        strike=78.0,
        expiry=date(2026, 10, 30),
        bid=2.0,
        ask=2.2,
        delta=-0.6,
        iv=0.8,
    )


# --------------------------------------------------------------------------- #
# Roll review
# --------------------------------------------------------------------------- #


def test_roll_prompt_includes_the_picture_and_still_only_agrees_or_disagrees() -> None:
    prompt = build_roll_prompt(
        _alert(), _pos(), _quote(), proposal="ROLL 78P -> 72P for +$0.06", picture_block=BLOCK
    )
    assert BLOCK in prompt
    # The deterministic proposal is still the thing under review, and the model still cannot
    # change it: it agrees (a matching recommendation) or disagrees and says why.
    assert "=== SYSTEM PROPOSAL ===" in prompt
    assert "You may not change it" in prompt
    assert '"recommendation": "<roll | hold | close>"' in prompt
    # The picture is context ahead of the question, not part of the schema.
    assert prompt.index("=== MARKET PICTURE ===") < prompt.index("=== YOUR TASK ===")


def test_a_roll_prompt_without_a_picture_is_what_it_was() -> None:
    assert "MARKET PICTURE" not in build_roll_prompt(_alert(), _pos(), _quote())


def test_the_roll_runners_read_the_stored_picture(news_db) -> None:
    """Both backends put the stored picture in the roll prompt (an explicit block wins)."""
    _save(_picture(datetime.now(UTC)))
    cfg = SimpleNamespace(enabled=True, backend="cli", model_for=lambda kind: "")
    seen: list[str] = []

    def _capture(prompt, *a, **k):
        seen.append(prompt)
        return None, "cli_error"

    with (
        patch.object(runner, "get_config") as get_cfg,
        patch.object(runner, "_run_cli_outcome", side_effect=_capture),
        patch.object(runner, "_build_cmd", return_value=["claude"]),
    ):
        get_cfg.return_value.claude = cfg
        runner.review_roll(_alert(), _pos(), _quote(), proposal="HOLD")
        runner.review_roll(_alert(), _pos(), _quote(), picture_block="EXPLICIT BLOCK")
    assert "Tariff escalation" in seen[0] and "=== MARKET PICTURE ===" in seen[0]
    assert "EXPLICIT BLOCK" in seen[1] and "Tariff escalation" not in seen[1]

    ollama_seen: list[str] = []

    def _answer(prompt, cfg, schema=None):
        ollama_seen.append(prompt)
        return json.dumps(
            {
                "position_symbol": "TQQQ 78P",
                "recommendation": "hold",
                "roll_target": "",
                "rationale": "r",
                "risks": "k",
            }
        )

    with (
        patch.object(ollama_mod, "get_config") as ogc,
        patch.object(ollama_mod, "_generate", side_effect=_answer),
    ):
        ogc.return_value.claude = MagicMock(enabled=True)
        ollama_mod.review_roll(_alert(), _pos(), _quote(), picture_block=BLOCK)
    assert BLOCK in ollama_seen[0]


# --------------------------------------------------------------------------- #
# EOD journal
# --------------------------------------------------------------------------- #


def test_eod_prompt_includes_the_picture() -> None:
    prompt = build_eod_prompt(_make_eod_summary(), picture_block=BLOCK)
    assert BLOCK in prompt
    assert '"narrative"' in prompt  # still a narrative and nothing else
    assert "MARKET PICTURE" not in build_eod_prompt(_make_eod_summary())


def test_the_eod_runners_read_the_stored_picture(news_db) -> None:
    _save(_picture(datetime.now(UTC)))
    cfg = SimpleNamespace(enabled=True, backend="cli", model_for=lambda kind: "")
    seen: list[str] = []

    def _capture(prompt, *a, **k):
        seen.append(prompt)
        return None, "cli_error"

    with (
        patch.object(runner, "get_config") as get_cfg,
        patch.object(runner, "_run_cli_outcome", side_effect=_capture),
        patch.object(runner, "_build_cmd", return_value=["claude"]),
    ):
        get_cfg.return_value.claude = cfg
        runner.write_journal_narrative(_make_eod_summary())
    assert "Tariff escalation" in seen[0]

    ollama_seen: list[str] = []

    def _answer(prompt, cfg, schema=None):
        ollama_seen.append(prompt)
        return json.dumps({"narrative": "A quiet day."})

    with (
        patch.object(ollama_mod, "get_config") as ogc,
        patch.object(ollama_mod, "_generate", side_effect=_answer),
    ):
        ogc.return_value.claude = MagicMock(enabled=True)
        ollama_mod.write_journal_narrative(_make_eod_summary(), picture_block=BLOCK)
    assert BLOCK in ollama_seen[0]


# --------------------------------------------------------------------------- #
# Spreads picker
# --------------------------------------------------------------------------- #


def test_render_picture_can_label_the_regime_as_of() -> None:
    text = render_picture(_picture(), now=NOW, staleness_hours=26, regime_as_of=True)
    assert "QQQ: stressed (base cautious; as of Oct 22 11:00 ET)" in text
    assert "SPY: normal (as of Oct 22 11:00 ET)" in text
    # The default rendering (every other reader) is unchanged.
    assert "as of" not in render_picture(_picture(), now=NOW, staleness_hours=26)


def test_spreads_prompt_includes_the_picture_labelled_as_of() -> None:
    picture_text = render_picture(_picture(), now=NOW, staleness_hours=26, regime_as_of=True)
    market = MARKET.model_copy(update={"picture_text": picture_text})
    pick = build_pick_prompt(request(), market)
    brief = build_brief_prompt(
        SpreadBriefRequest(now=SPREADS_NOW, levels=LEVELS, tape=SpreadTapeStats(), exits=EXITS),
        market,
    )
    for prompt in (pick, brief):
        assert "=== MARKET PICTURE ===" in prompt
        assert "QQQ: stressed (base cautious; as of Oct 22 11:00 ET)" in prompt
        assert "S3 Tariff escalation" in prompt
    # It still asks for a menu letter or skip and nothing else.
    assert '"choice": "<one of A, B, C, or skip>"' in pick
    # And with no picture the prompt has no such block.
    assert "MARKET PICTURE" not in build_pick_prompt(request(), MARKET)


def test_market_snapshot_fills_the_picture_text(news_db, monkeypatch) -> None:
    _save(_picture(datetime.now(UTC) - timedelta(hours=2)))
    monkeypatch.setattr(ctx, "get_market_conditions", lambda: MarketConditions())
    monkeypatch.setattr(
        ctx, "get_technical_stats", lambda symbol: TechnicalStats(symbol="SPY", price=663.0)
    )
    monkeypatch.setattr(ctx, "compute_realized_vol", lambda symbol, window: 18.5)
    snap = ctx.market_snapshot(datetime.now(UTC), symbol="SPY", max_headlines=0)
    assert snap.picture_text is not None
    assert "=== MARKET PICTURE ===" in snap.picture_text and "(as of" in snap.picture_text
    assert "QQQ: stressed" in snap.picture_text
    assert snap.unavailable == []


def test_market_snapshot_without_a_picture_has_none(monkeypatch) -> None:
    @contextmanager
    def _no_db():
        yield None

    monkeypatch.setattr(ctx, "get_market_conditions", lambda: MarketConditions())
    monkeypatch.setattr(
        ctx, "get_technical_stats", lambda symbol: TechnicalStats(symbol="SPY", price=663.0)
    )
    monkeypatch.setattr(ctx, "compute_realized_vol", lambda symbol, window: 18.5)
    monkeypatch.setattr(ctx, "read_only_session", _no_db)
    snap = ctx.market_snapshot(NOW, symbol="SPY", max_headlines=0)
    assert snap.picture_text is None and snap.unavailable == []


def test_spreads_snapshot_field_defaults_to_none() -> None:
    assert SpreadMarketSnapshot().picture_text is None
    assert json.loads(SpreadMarketSnapshot().model_dump_json())["picture_text"] is None


def test_spreads_ai_still_imports_neither_claude_nor_storage() -> None:
    """The picture is read through the news read-only store and the neutral renderer; the
    package gained no import of the wheel's prompt stack or the trading database."""
    offenders = []
    for path in SPREADS_AI:
        for m in imported_modules(path):
            claude = (m == "src.claude" or m.startswith("src.claude.")) and not (
                m == "src.claude.cli" or m.startswith("src.claude.cli.")
            )
            storage = m == "src.storage" or m.startswith("src.storage.")
            if claude or storage:
                offenders.append(f"{path.relative_to(ROOT)} -> {m}")
    assert offenders == []
