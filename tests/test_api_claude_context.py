"""GET /claude/context (market picture spec section 11): what each Claude call knows.

Read-only over the trading DB (regime state, held names) and data/news.db (picture, triage,
dossiers) through the API's read-only handles; adds no write.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine

from src.common.config import get_config
from src.common.schemas import (
    DossierEvent,
    DossierFact,
    IndexRegime,
    MarketPicture,
    MarketRegime,
    NoiseSummary,
    PictureFact,
    PictureRegime,
    PictureStory,
    RegimeInputs,
    RegimeState,
    SeasonalityView,
    TickerDossier,
)
from tests.conftest import OWNER, short_put

ROOT = Path(__file__).resolve().parents[1]
ET = ZoneInfo("America/New_York")
NOW = datetime(2026, 10, 22, 15, tzinfo=UTC)
TODAY_ET = NOW.astimezone(ET).date()


@pytest.fixture()
def news_client(client, news_db, monkeypatch):
    """The API client with its read-only news handle pointed at the isolated news.db."""
    import src.api.news_db as nd
    import src.api.routers.claude_context as cc

    nd.reset_engine()
    monkeypatch.setattr(nd, "_resolve_path", lambda: str(news_db))
    monkeypatch.setattr(cc, "_now", lambda: NOW)
    yield client
    nd.reset_engine()


# --- seeds ----------------------------------------------------------------------------------


def _index(index: str, effective: MarketRegime, base: MarketRegime, **kw) -> IndexRegime:
    return IndexRegime(
        index=index,
        base=base,
        base_date=TODAY_ET,
        since=TODAY_ET,
        base_since=TODAY_ET,
        effective=effective,
        inputs=RegimeInputs(vol=23.4, index_close=512.3),
        **kw,
    )


def _seed_regime(*, suspended: bool = False) -> None:
    from src.storage.regime_state import save_regime_state, suspend_regime

    save_regime_state(
        RegimeState(
            as_of=NOW,
            spy=_index("SPY", MarketRegime.NORMAL, MarketRegime.NORMAL),
            qqq=_index(
                "QQQ", MarketRegime.STRESSED, MarketRegime.CAUTIOUS, escalated_by=["QQQ -2.9%"]
            ),
        )
    )
    if suspended:
        suspend_regime(TODAY_ET)


def _picture(**kw) -> MarketPicture:
    base = dict(
        version=NOW.isoformat(),
        built_at=NOW,
        regimes=[
            PictureRegime(
                index="QQQ", effective=MarketRegime.STRESSED, base=MarketRegime.CAUTIOUS, as_of=NOW
            )
        ],
        facts=[PictureFact(label="VIX", value="23.4")],
        seasonality=SeasonalityView(month=10, avg_return_pct=1.2, up_share=0.6, years=5),
        events=["FOMC Wed 14:00 ET"],
        stories=[
            PictureStory(
                id=3,
                title="Tariff escalation",
                started_on=date(2026, 10, 12),
                description="Tariff headlines keep the index under its 50-day average.",
                evidence=["C41", "F2"],
            )
        ],
        noise=NoiseSummary(judged=12, not_reviewed=340, promotions=1),
    )
    base.update(kw)
    return MarketPicture(**base)


def _save_picture(p: MarketPicture, *, stale: bool = False) -> None:
    from src.news.store.models import MarketPictureRow
    from src.news.store.queries import naive_utc
    from src.news.store.session import news_session

    with news_session() as s:
        s.add(
            MarketPictureRow(
                built_at=naive_utc(p.built_at),
                version=p.version,
                payload=p.model_dump(mode="json"),
                stale=stale,
            )
        )


def _dossier(symbol: str, **kw) -> TickerDossier:
    base = dict(
        symbol=symbol,
        version=f"{symbol}@{NOW.isoformat()}",
        facts_at=NOW,
        prose_at=NOW - timedelta(hours=2),
        profile_at=NOW - timedelta(days=2),
        kind="stock",
        health="strong",
        health_why=["passes the quality screen"],
        facts=[DossierFact(id=f"{symbol}:F1", label="RSI14", display="RSI 52")],
        profile="A social-media and AI company; ad revenue and capex drive the shares.",
        story="Launching a new glasses line next week (C8123).",
        story_evidence=["C8123"],
        events=[
            DossierEvent(
                id=f"{symbol}:E1",
                title="MUSE launch event",
                on=date(2026, 10, 29),
                evidence="C8123",
                quote="Meta will unveil MUSE at Connect on Oct 29.",
            )
        ],
    )
    base.update(kw)
    return TickerDossier(**base)


def _save_dossier(d: TickerDossier) -> None:
    from src.news.store.models import TickerDossierRow
    from src.news.store.queries import naive_utc
    from src.news.store.session import news_session

    with news_session() as s:
        s.add(
            TickerDossierRow(
                symbol=d.symbol,
                version=d.version,
                built_at=naive_utc(d.facts_at),
                payload=d.model_dump(mode="json"),
            )
        )


def _cluster(cid: int, *, age_h: float, headline: str | None = None) -> None:
    from src.news.store.models import NewsClusterRow
    from src.news.store.queries import naive_utc
    from src.news.store.session import news_session

    seen = naive_utc(NOW - timedelta(hours=age_h))
    with news_session() as s:
        s.add(
            NewsClusterRow(
                id=cid,
                headline=headline or f"headline {cid}",
                category="macro",
                first_seen=seen,
                last_seen=seen,
                tickers=[],
                tags=[],
            )
        )


def _triage(cid: int, *, pile: int | None, judged_h: float | None = 1.0, **kw) -> None:
    from src.news.store.models import StoryTriageRow
    from src.news.store.queries import naive_utc
    from src.news.store.session import news_session

    with news_session() as s:
        s.add(
            StoryTriageRow(
                cluster_id=cid,
                pile=pile,
                reason=kw.pop("reason", ""),
                judged_at=None if judged_h is None else naive_utc(NOW - timedelta(hours=judged_h)),
                **kw,
            )
        )


def _get(client) -> dict:
    r = client.get("/claude/context", headers=OWNER)
    assert r.status_code == 200, r.text
    return r.json()


# --- the route ------------------------------------------------------------------------------


def test_requires_owner(news_client) -> None:
    assert news_client.get("/claude/context").status_code == 401


def test_context_with_everything(news_client, seed_portfolio_snapshot, monkeypatch) -> None:
    _seed_regime()
    _save_picture(_picture())
    seed_portfolio_snapshot(positions=[short_put(underlying="META")])
    _save_dossier(_dossier("META"))
    _cluster(1, age_h=30)
    _triage(1, pile=3, reason="calendar filler")

    body = _get(news_client)

    assert body["available"] is True
    assert body["as_of"].startswith("2026-10-22T15:00:00")
    assert body["picture"]["stories"][0]["title"] == "Tariff escalation"
    assert body["picture"]["stories"][0]["started_on"] == "2026-10-12"
    assert body["picture"]["seasonality"]["years"] == 5
    assert body["picture"]["stale"] is False
    assert body["regime"]["qqq"]["effective"] == "stressed"
    assert body["regime"]["qqq"]["base"] == "cautious"
    assert body["regime"]["spy"]["effective"] == "normal"
    assert body["suspended_today"] is False
    assert body["regime_enabled"] is True
    assert [(x["index"], x["regime"]) for x in body["limits"]] == [
        ("SPY", "normal"),
        ("QQQ", "stressed"),
    ]
    assert [c["kind"] for c in body["calls"]] == [
        "trade_review",
        "roll_review",
        "spreads_picker",
        "news_expert",
        "eod_journal",
        "scan",
        "dossier_builder",
    ]
    assert [d["cluster_id"] for d in body["dropped"]] == [1]
    assert body["not_reviewed_7d"] == 0
    assert [d["symbol"] for d in body["dossiers"]] == ["META"]
    assert body["dossiers"][0]["held"] is True


def test_context_without_news_db(client, tmp_path, monkeypatch) -> None:
    """No news.db yet (fresh install, news service never started): 200, the regime still shown."""
    import src.api.news_db as nd

    nd.reset_engine()
    monkeypatch.setattr(nd, "_resolve_path", lambda: str(tmp_path / "absent.db"))
    _seed_regime()

    body = _get(client)

    assert body["available"] is False
    assert body["picture"] is None
    assert body["dropped"] == [] and body["dossiers"] == [] and body["without_notes"] == []
    assert body["not_reviewed_7d"] == 0 and body["dropped_total"] == 0
    assert body["regime"]["qqq"]["effective"] == "stressed"
    assert [x["regime"] for x in body["limits"]] == ["normal", "stressed"]
    assert len(body["calls"]) == 7  # the tiles are static: they need no data
    nd.reset_engine()


def test_context_with_old_news_db(client, tmp_path, monkeypatch) -> None:
    """A news.db written before the picture, triage and dossier tables existed: the read-only
    engine cannot create them, so every reader answers 'nothing yet'. Never a 500."""
    import src.api.news_db as nd
    from src.news.store.models import NewsBase

    newer = {"story_triage", "market_pictures", "picture_stories", "ticker_dossiers"}
    path = tmp_path / "old-news.db"
    engine = create_engine(f"sqlite:///{path}")
    NewsBase.metadata.create_all(
        engine, tables=[t for name, t in NewsBase.metadata.tables.items() if name not in newer]
    )
    engine.dispose()
    nd.reset_engine()
    monkeypatch.setattr(nd, "_resolve_path", lambda: str(path))
    _seed_regime()

    body = _get(client)

    assert body["available"] is True
    assert body["picture"] is None
    assert body["dropped"] == [] and body["dossiers"] == []
    assert body["not_reviewed_7d"] == 0
    assert body["regime"] is not None
    nd.reset_engine()


def test_context_without_regime_state(news_client) -> None:
    _save_picture(_picture())

    body = _get(news_client)

    assert body["regime"] is None
    assert body["limits"] == []
    assert body["suspended_today"] is False
    assert body["picture"]["version"] == NOW.isoformat()


def test_context_with_an_unreadable_regime_state(news_client) -> None:
    """A stored state that no longer validates reads as absent, as the trading side does."""
    from src.storage.db import session_scope
    from src.storage.models import SystemSettingRow
    from src.storage.regime_state import STATE_KEY

    with session_scope() as s:
        s.add(SystemSettingRow(key=STATE_KEY, value='{"spy": "oops"}'))

    body = _get(news_client)

    assert body["regime"] is None and body["limits"] == []


def test_a_suspension_counts_only_for_today(news_client) -> None:
    from src.storage.regime_state import suspend_regime

    _seed_regime()
    suspend_regime(TODAY_ET - timedelta(days=1))
    assert _get(news_client)["suspended_today"] is False

    suspend_regime(TODAY_ET)
    body = _get(news_client)
    assert body["suspended_today"] is True
    # the limits are still the regime's own; the flag says they are not in force today
    assert [x["regime"] for x in body["limits"]] == ["normal", "stressed"]


def test_the_limits_are_the_configured_ones_for_each_regime(news_client, monkeypatch) -> None:
    _seed_regime()
    body = _get(news_client)
    spy, qqq = body["limits"]
    # the shipped example: normal 1.0 / 1.0 / no cap / floor 0; stressed 0.4 / 0.3 / 3 / floor 1
    assert (spy["budget_pct"], spy["per_trade_pct"], spy["max_new_per_day"]) == (100.0, 100.0, None)
    assert spy["floor_new_per_day"] == 0
    assert (qqq["budget_pct"], qqq["per_trade_pct"], qqq["max_new_per_day"]) == (40.0, 30.0, 3)
    assert qqq["floor_new_per_day"] == 1

    monkeypatch.setitem(
        get_config().risk,
        "regime",
        {"csp": {"budget_multiplier": {"stressed": 0.35}, "max_new_per_day": {"stressed": 2}}},
    )
    assert _get(news_client)["limits"][1]["budget_pct"] == 35.0
    assert _get(news_client)["limits"][1]["max_new_per_day"] == 2


def test_regime_switched_off_in_config_is_reported(news_client, monkeypatch) -> None:
    _seed_regime()
    monkeypatch.setitem(get_config().risk, "regime", {"enabled": False})
    body = _get(news_client)
    assert body["regime_enabled"] is False
    assert body["regime"]["qqq"]["effective"] == "stressed"  # the record is still shown


def test_an_invalid_regime_block_does_not_500_the_page(news_client, monkeypatch) -> None:
    _seed_regime()
    monkeypatch.setitem(get_config().risk, "regime", {"csp": {"no_such_key": 1}})
    body = _get(news_client)
    assert body["limits"] == []
    assert body["regime"]["qqq"]["effective"] == "stressed"


def test_a_stale_picture_is_marked_stale(news_client) -> None:
    _save_picture(_picture(), stale=True)
    assert _get(news_client)["picture"]["stale"] is True


# --- the dropped list -----------------------------------------------------------------------


def test_dropped_lists_judged_noise_and_promotions_last_7_days(news_client) -> None:
    for cid, age_h in ((1, 20), (2, 30), (3, 40), (4, 24 * 9), (5, 5), (6, 6), (7, 7)):
        _cluster(cid, age_h=age_h)
    # judged noise, newest judgement first
    _triage(1, pile=3, judged_h=3.0, reason="calendar filler")
    # judged noise the market then moved on: pile 2 with a promotion on it
    _triage(
        2,
        pile=2,
        judged_h=2.0,
        reason="promoted late: +1.2% (QQQ); was: thought it was a rehash",
        promoted_at=NOW - timedelta(hours=1),
        promoted_move_pct=1.2,
    )
    _triage(3, pile=3, judged_h=10.0, reason="local story")
    # judged noise, but the story ended nine days ago: outside the window
    _triage(4, pile=3, judged_h=24 * 9, reason="old")
    # live piles are not "dropped"
    _triage(5, pile=1, reason="shapes the picture")
    # nobody judged these two
    _triage(6, pile=None, judged_h=None)
    _triage(7, pile=None, judged_h=None)

    body = _get(news_client)

    assert [d["cluster_id"] for d in body["dropped"]] == [2, 1, 3]
    by_id = {d["cluster_id"]: d for d in body["dropped"]}
    assert by_id[1]["promoted"] is False and by_id[1]["promoted_move_pct"] is None
    assert by_id[1]["reason"] == "calendar filler" and by_id[1]["headline"] == "headline 1"
    assert by_id[2]["promoted"] is True and by_id[2]["promoted_move_pct"] == 1.2
    # the stored reason carries the promotion text first; the page gets the dismissal reason
    assert by_id[2]["reason"] == "thought it was a rehash"
    assert body["not_reviewed_7d"] == 2
    assert body["dropped_total"] == 3


def test_a_promotion_whose_original_reason_was_cut_off_has_an_empty_reason(news_client) -> None:
    _cluster(1, age_h=2)
    _triage(
        1,
        pile=2,
        reason="promoted late: -2.0% (NVDA net of beta); was",
        promoted_at=NOW,
        promoted_move_pct=-2.0,
    )
    d = _get(news_client)["dropped"][0]
    assert d["promoted"] is True and d["reason"] == "" and d["promoted_move_pct"] == -2.0


def test_the_dropped_list_is_capped_and_says_how_many_there_are(news_client) -> None:
    for cid in range(1, 131):
        _cluster(cid, age_h=2)
        _triage(cid, pile=3, judged_h=cid / 100, reason="filler")
    body = _get(news_client)
    assert len(body["dropped"]) == 100 and body["dropped_total"] == 130
    # newest judgement first
    assert body["dropped"][0]["cluster_id"] == 1


# --- dossiers, leveraged limits, the cut mode ------------------------------------------------


def test_context_lists_dossiers_leveraged_limits_and_the_cut_mode(
    news_client, seed_portfolio_snapshot, monkeypatch
) -> None:
    seed_portfolio_snapshot(
        positions=[
            short_put(underlying="META"),
            short_put(underlying="XYZW"),  # held, in no universe list: still covered
            short_put(underlying="SPY"),  # the spreads book's underlying: never a dossier name
        ]
    )
    _save_dossier(_dossier("GOOGL", kind="stock", health="ok", stale=True, prose_at=None))
    _save_dossier(_dossier("META"))  # held: first
    _save_dossier(_dossier("XYZW"))
    _save_dossier(
        _dossier("TQQQ", kind="leveraged_etf", health="n/a", health_why=[], story="", events=[])
    )
    _save_dossier(_dossier("ZZZZ"))  # in no list and not held: not a name the book covers

    body = _get(news_client)

    assert [d["symbol"] for d in body["dossiers"]] == ["META", "XYZW", "GOOGL", "TQQQ"]
    meta, xyzw, googl, tqqq = body["dossiers"]
    assert meta["held"] is True and xyzw["held"] is True and googl["held"] is False
    assert meta["story_evidence"] == ["C8123"] and meta["events"][0]["on"] == "2026-10-29"
    assert meta["events"][0]["quote"].startswith("Meta will unveil")
    assert meta["profile"].startswith("A social-media") and meta["facts"][0]["id"] == "META:F1"
    assert googl["stale"] is True and googl["prose_at"] is None
    assert tqqq["kind"] == "leveraged_etf" and tqqq["health"] == "n/a"
    # covered names that have no dossier yet are named, not silently missing
    assert "AMZN" in body["without_notes"] and "META" not in body["without_notes"]
    assert "SPY" not in body["without_notes"] and "XYZW" not in body["without_notes"]
    assert body["without_notes"] == sorted(body["without_notes"])

    assert body["leveraged_enabled"] is True
    lev = {x["symbol"]: x for x in body["leveraged"]}
    assert lev["TQQQ"] == {
        "symbol": "TQQQ",
        "leverage": 3,
        "calm_fraction": 0.6,
        "stressed_fraction": 0.3,
    }
    assert lev["TSLL"]["leverage"] == 2
    assert (lev["TSLL"]["calm_fraction"], lev["TSLL"]["stressed_fraction"]) == (0.8, 0.5)
    assert [x["symbol"] for x in body["leveraged"]] == sorted(lev)

    assert body["claude_cut_mode"] == "applied" and body["account_mode"] == "paper"


def test_a_leveraged_etf_missing_from_the_map_reads_as_3x(news_client, monkeypatch) -> None:
    monkeypatch.setitem(get_config().risk, "leveraged_sizing", {"leverage": {"TQQQ": 3}})
    lev = {x["symbol"]: x for x in _get(news_client)["leveraged"]}
    assert lev["TSLL"]["leverage"] == 3  # not in the operator's map: the strictest factor


def test_leveraged_ceilings_switched_off(news_client, monkeypatch) -> None:
    monkeypatch.setitem(get_config().risk, "leveraged_sizing", {"enabled": False})
    body = _get(news_client)
    assert body["leveraged_enabled"] is False and body["leveraged"] == []


@pytest.mark.parametrize(
    ("live", "apply_in_paper", "apply_live", "mode", "account"),
    [
        (False, True, False, "applied", "paper"),
        (False, False, True, "record_only", "paper"),
        (True, True, False, "record_only", "live"),
        (True, False, True, "applied", "live"),
    ],
)
def test_the_cut_mode_follows_the_account_and_the_config(
    news_client, monkeypatch, live, apply_in_paper, apply_live, mode, account
) -> None:
    monkeypatch.setattr(get_config().secrets, "live_trading", live)
    monkeypatch.setitem(
        get_config().risk,
        "claude_cut",
        {"apply_in_paper": apply_in_paper, "apply_live": apply_live},
    )
    body = _get(news_client)
    assert (body["claude_cut_mode"], body["account_mode"]) == (mode, account)


# --- the cut breaker, today (OI-F4) -----------------------------------------------------------


def _set_cut_state(raw: str) -> None:
    from src.storage.system_settings import set_setting

    set_setting("claude_cut_state", raw)


def _cut_state(day: date, *, alerted: bool, reviewed=("c1", "c2")) -> str:
    import json

    return json.dumps(
        {"day": day.isoformat(), "reviewed": list(reviewed), "breaker_alerted": alerted}
    )


def test_the_breaker_flag_is_true_when_it_tripped_today(news_client) -> None:
    _set_cut_state(_cut_state(TODAY_ET, alerted=True))
    assert _get(news_client)["claude_cut_breaker_tripped_today"] is True


def test_the_breaker_flag_is_false_while_it_has_not_tripped(news_client) -> None:
    _set_cut_state(_cut_state(TODAY_ET, alerted=False))
    assert _get(news_client)["claude_cut_breaker_tripped_today"] is False


def test_a_breaker_that_tripped_on_another_day_does_not_count(news_client) -> None:
    _set_cut_state(_cut_state(TODAY_ET - timedelta(days=1), alerted=True))
    assert _get(news_client)["claude_cut_breaker_tripped_today"] is False
    _set_cut_state(_cut_state(TODAY_ET + timedelta(days=1), alerted=True))
    assert _get(news_client)["claude_cut_breaker_tripped_today"] is False


def test_a_missing_cut_state_means_the_breaker_has_not_tripped(news_client) -> None:
    body = _get(news_client)
    assert body["claude_cut_breaker_tripped_today"] is False


@pytest.mark.parametrize(
    "raw",
    ["not json", "[]", '"tripped"', "null", '{"day": 5, "breaker_alerted": true}', "{}", ""],
)
def test_a_malformed_cut_state_means_the_breaker_has_not_tripped(news_client, raw) -> None:
    _set_cut_state(raw)
    assert _get(news_client)["claude_cut_breaker_tripped_today"] is False


def test_the_breaker_needs_a_real_true_not_a_missing_or_loose_value(news_client) -> None:
    import json

    for flag in ({}, {"breaker_alerted": "yes"}, {"breaker_alerted": 1}, {"breaker_alerted": None}):
        _set_cut_state(json.dumps({"day": TODAY_ET.isoformat(), "reviewed": [], **flag}))
        assert _get(news_client)["claude_cut_breaker_tripped_today"] is False, flag


def test_the_breaker_flag_is_reported_without_a_news_service(client, tmp_path, monkeypatch) -> None:
    """The regime card does not need news.db: the flag rides the base response."""
    import src.api.news_db as nd
    import src.api.routers.claude_context as cc

    nd.reset_engine()
    monkeypatch.setattr(nd, "_resolve_path", lambda: str(tmp_path / "missing.db"))
    monkeypatch.setattr(cc, "_now", lambda: NOW)
    _set_cut_state(_cut_state(TODAY_ET, alerted=True))
    body = _get(client)
    assert body["available"] is False and body["claude_cut_breaker_tripped_today"] is True
    nd.reset_engine()


def test_the_breaker_key_is_the_one_the_sender_writes() -> None:
    """The API cannot import the sender (it would load the Telegram stack), so the key is spelled
    here and in the router; this keeps the two from drifting."""
    import src.api.routers.claude_context as cc
    from src.notify import sender

    assert cc._CUT_STATE_KEY == sender._CUT_STATE_KEY == "claude_cut_state"


# --- reported figures on a name (OI-E10) ------------------------------------------------------


def test_a_dossiers_reported_figures_come_through_with_their_cluster_ids(news_client) -> None:
    from src.common.schemas import DossierReported

    _save_dossier(
        _dossier(
            "META",
            reported=[
                DossierReported(
                    text="Analysts see glasses sales of $5.2 billion", cluster_id="C8123"
                ),
                DossierReported(text="Launch set for 3 markets", cluster_id="C8124"),
            ],
        )
    )
    meta = next(d for d in _get(news_client)["dossiers"] if d["symbol"] == "META")
    assert meta["reported"] == [
        {"text": "Analysts see glasses sales of $5.2 billion", "cluster_id": "C8123"},
        {"text": "Launch set for 3 markets", "cluster_id": "C8124"},
    ]
    assert "$5.2 billion" not in meta["story"]  # the story and the reported figures stay apart


def test_a_dossier_without_reported_figures_reports_an_empty_list(news_client) -> None:
    _save_dossier(_dossier("META"))
    meta = next(d for d in _get(news_client)["dossiers"] if d["symbol"] == "META")
    assert meta["reported"] == []


def test_a_row_stored_before_the_field_existed_reads_as_an_empty_list(news_client) -> None:
    from src.news.store.models import TickerDossierRow
    from src.news.store.queries import naive_utc
    from src.news.store.session import news_session

    d = _dossier("META")
    payload = d.model_dump(mode="json")
    payload.pop("reported")
    with news_session() as s:
        s.add(
            TickerDossierRow(
                symbol="META", version=d.version, built_at=naive_utc(d.facts_at), payload=payload
            )
        )
    meta = next(x for x in _get(news_client)["dossiers"] if x["symbol"] == "META")
    assert meta["reported"] == []


# --- the static call map ---------------------------------------------------------------------


def test_every_block_header_occurs_in_its_builder_file() -> None:
    """The tiles are static; this is what keeps them honest when a prompt builder changes."""
    from src.api.claude_calls import CALLS

    assert CALLS
    for call in CALLS:
        assert call.blocks, call.kind
        for block in call.blocks:
            path = ROOT / block.builder_file
            assert path.is_file(), f"{call.kind}/{block.label}: {block.builder_file} is not a file"
            assert block.header in path.read_text(encoding="utf-8"), (
                f"{call.kind}/{block.label}: {block.header!r} is not in {block.builder_file}"
            )


def test_the_tiles_are_the_seven_calls_with_the_plans_blocks() -> None:
    from src.api.claude_calls import CALLS

    got = {c.kind: [b.label for b in c.blocks] for c in CALLS}
    assert got["trade_review"] == [
        "Market picture",
        "Your book",
        "Name notes",
        "News",
        "Candidates",
    ]
    assert got["roll_review"] == [
        "Market picture",
        "Name notes",
        "Position",
        "Live quote",
        "System proposal",
    ]
    assert got["spreads_picker"] == [
        "Market picture (as of build)",
        "Tape",
        "Events",
        "Headlines",
        "Menu",
    ]
    assert got["news_expert"] == ["Facts", "Clusters", "Market picture"]
    assert got["eod_journal"] == ["Market picture", "Today's trades"]
    assert got["scan"] == ["Market picture", "Name notes", "Sector", "News", "Candidates"]
    assert got["dossier_builder"] == ["Facts", "Clusters", "Market picture"]
    assert len({c.kind for c in CALLS}) == len(CALLS)
    assert len({c.label for c in CALLS}) == len(CALLS)


def test_the_response_carries_the_tiles_with_block_labels_only(news_client) -> None:
    body = _get(news_client)
    trade = body["calls"][0]
    assert trade["label"] and trade["blocks"][0] == "Market picture"
    assert all(isinstance(b, str) for b in trade["blocks"])


# --- the fences ------------------------------------------------------------------------------


def test_api_still_writes_exactly_one_table(news_client) -> None:
    """A read leaves every write table alone, and the new files name no write handle."""
    from src.storage.db import session_scope
    from src.storage.models import AppCommandRow

    _seed_regime()
    _save_picture(_picture())
    _get(news_client)
    with session_scope() as s:
        assert s.query(AppCommandRow).count() == 0
    for rel in (
        "src/api/routers/claude_context.py",
        "src/api/models/claude_context.py",
        "src/api/claude_calls.py",
    ):
        text = (ROOT / rel).read_text(encoding="utf-8")
        for token in ("get_command_engine", "command_session", "src.news.store.session"):
            assert token not in text, f"{rel} names {token}"
        for token in (".add(", ".merge(", ".delete(", ".commit("):
            assert token not in text, f"{rel} writes: {token}"


def test_the_api_process_still_does_not_load_the_news_process_engine() -> None:
    """The new route imports `src.news.store.queries` (Session-parameterised) and nothing that
    opens the news process's read-write engine, directly or transitively."""
    code = (
        "import src.api.main, sys; "
        "print('src.news.store.session' in sys.modules, 'src.news.dossier' in sys.modules, "
        "'src.news.collectors' in sys.modules)"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env={**os.environ, "IBKR_CONFIG_USE_EXAMPLES": "1"},
    )
    assert out.stdout.strip() == "False False False", out.stderr


def test_sizing_lists_the_days_actions_newest_first(news_client) -> None:
    from src.storage.db import session_scope
    from src.storage.models import SizingActionRow

    def row(sym: str, kind: str, day: date, minute: int, sent: int) -> SizingActionRow:
        return SizingActionRow(
            created_at=datetime(2026, 10, 22, 15, minute),
            candidate_id=f"c-{sym}",
            record_key=f"csp:{sym}:{kind}:{day}",
            underlying=sym,
            strategy="cash_secured_put",
            right="P",
            strike=35.0,
            expiry=date(2026, 11, 13),
            premium=2.0,
            kind=kind,
            regime="stressed",
            deterministic_contracts=2,
            sent_contracts=sent,
            reason="stopped by the scale-in ladder",
            action_day=day,
        )

    with session_scope() as s:
        s.add_all(
            [
                row("ASTS", "scale_in_zone", TODAY_ET, 1, 0),
                row("NVDA", "claude_cut", TODAY_ET, 2, 1),
                row("OLD", "scale_in_zone", date(2026, 10, 21), 3, 0),
            ]
        )

    body = news_client.get("/claude/sizing", headers=OWNER).json()
    assert body["day"] == TODAY_ET.isoformat()
    assert [a["underlying"] for a in body["actions"]] == ["NVDA", "ASTS"]
    assert body["actions"][0]["sent_contracts"] == 1
    past = news_client.get("/claude/sizing?day=2026-10-21", headers=OWNER).json()
    assert [a["underlying"] for a in past["actions"]] == ["OLD"]
