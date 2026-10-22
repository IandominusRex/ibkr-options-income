"""Task 9: three-pile triage (Python presort and floor, one batched model call), and the digest
that uses it in place of the editor pass."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

from src.common.config import get_config
from src.common.schemas import (
    IndexRegime,
    MarketPicture,
    MarketRegime,
    PictureStory,
    RegimeState,
)
from src.news import explain as X
from src.news import triage as T
from src.news.llm import LlmResult
from src.news.schemas import ClusterView, FactSheet, TriageView
from src.news.store import queries
from src.news.store.models import NewsClusterRow, NewsPostRow, StoryTriageRow
from src.news.store.queries import naive_utc
from src.news.store.session import news_session
from src.news.store.state import get_state, set_state

NOW = datetime(2026, 10, 22, 15, 0, tzinfo=UTC)  # Thursday 11:00 ET


def _cv(
    cid: int,
    *,
    category: str = "ticker",
    tickers: tuple[str, ...] = (),
    sources: int = 1,
    topic: str = "other",
    last_seen: datetime = NOW,
) -> ClusterView:
    return ClusterView(
        id=cid,
        headline=f"headline {cid}",
        category=category,
        first_seen=last_seen,
        last_seen=last_seen,
        source_count=sources,
        tickers=list(tickers),
        topic_class=topic,
    )


def _seed_cluster(
    cid: int,
    *,
    category: str = "markets",
    tickers: tuple[str, ...] = (),
    sources: int = 1,
    topic: str = "other",
    age_min: int = 30,
) -> None:
    seen = naive_utc(NOW - timedelta(minutes=age_min))
    with news_session() as s:
        s.add(
            NewsClusterRow(
                id=cid,
                headline=f"headline {cid}",
                category=category,
                first_seen=seen,
                last_seen=seen,
                source_count=sources,
                tickers=list(tickers),
                tags=[],
                topic_class=topic,
            )
        )


def _seed_alert(cluster_ids: list[int], *, kind: str = "ticker_move", age_min: int = 20) -> None:
    with news_session() as s:
        s.add(
            NewsPostRow(
                kind=kind,
                posted_at=naive_utc(NOW - timedelta(minutes=age_min)),
                payload={},
                cluster_ids=cluster_ids,
                silent=False,
                critical=False,
                edits=0,
                stage="facts",
            )
        )


def _rows() -> dict[int, StoryTriageRow]:
    with news_session() as s:
        return {r.cluster_id: r for r in s.scalars(select(StoryTriageRow))}


class FakeLlm:
    """Stands in for ``explain.call_llm``: answers with the given piles, records every call."""

    def __init__(self, piles: dict[int, tuple[int, str]] | None, *, fail: bool = False) -> None:
        self.piles = piles or {}
        self.fail = fail
        self.calls: list[dict] = []

    def __call__(self, prompt: str, **kw) -> LlmResult | None:
        self.calls.append({"prompt": prompt, **kw})
        if self.fail:
            return None
        items = [
            {"cluster_id": cid, "pile": pile, "reason": reason}
            for cid, (pile, reason) in self.piles.items()
        ]
        return LlmResult(json.dumps({"items": items}), "cli")


@pytest.fixture()
def tri(news_db, monkeypatch):
    """A news.db with held = {AAPL} and a fake model; returns (fake-installer, held set)."""
    held = {"AAPL"}
    monkeypatch.setattr(T, "held_underlyings", lambda: set(held))

    def install(piles=None, *, fail=False) -> FakeLlm:
        fake = FakeLlm(piles, fail=fail)
        monkeypatch.setattr(X, "call_llm", fake)
        return fake

    return install


# --- the Python presort -----------------------------------------------------------------


def test_presort_ranks_alert_then_held_then_macro() -> None:
    clusters = [
        _cv(4),  # nothing going for it
        _cv(3, category="macro", sources=2, topic="fed"),
        _cv(2, tickers=("AAPL",), sources=4),
        _cv(1, tickers=("XYZ",), sources=1),
    ]
    out = T.presort(clusters, held={"AAPL"}, alerted_ids={1}, limit=10)
    assert [c.cluster.id for c in out] == [1, 2, 3, 4]
    assert [c.floor for c in out] == ["alert", "held", None, None]
    # 3*[alert] + 2*[held] + min(sources, 5)/5 + [macro-ish category] + [topic != other]
    assert [round(c.rank, 2) for c in out] == [3.2, 2.8, 2.4, 0.2]


def test_presort_limits_and_breaks_ties_by_recency() -> None:
    older = _cv(1, last_seen=NOW - timedelta(hours=2))
    newer = _cv(2, last_seen=NOW - timedelta(minutes=5))
    out = T.presort([older, newer, _cv(3, sources=5)], held=set(), alerted_ids=set(), limit=2)
    assert [c.cluster.id for c in out] == [3, 2]  # one more source wins; the tie goes to the newer


def test_an_alert_floor_beats_a_held_floor() -> None:
    out = T.presort([_cv(1, tickers=("AAPL",))], held={"AAPL"}, alerted_ids={1}, limit=5)
    assert out[0].floor == "alert"


def test_apply_floor_only_moves_a_story_up() -> None:
    assert [T.apply_floor(p, "alert") for p in (1, 2, 3)] == [1, 2, 2]
    assert [T.apply_floor(p, "held") for p in (1, 2, 3)] == [1, 2, 2]
    assert [T.apply_floor(p, None) for p in (1, 2, 3)] == [1, 2, 3]


# --- the batch call ---------------------------------------------------------------------


def test_floor_never_lets_an_alert_or_held_story_fall_to_noise(tri) -> None:
    _seed_cluster(1, tickers=("XYZ",), sources=2)  # an alert rule fired on it
    _seed_cluster(2, tickers=("AAPL",), sources=2)  # a held name
    _seed_cluster(3, tickers=("MSFT",), sources=2)  # neither
    _seed_alert([1])
    fake = tri({1: (3, "just a rumor"), 2: (3, "minor"), 3: (3, "filler")})
    n = T.run_triage(NOW, picture=None)
    rows = _rows()
    assert (rows[1].pile, rows[1].floor) == (2, "alert")
    assert (rows[2].pile, rows[2].floor) == (2, "held")
    assert (rows[3].pile, rows[3].floor) == (3, None)
    assert "floor" in rows[1].reason and "just a rumor" in rows[1].reason
    assert rows[3].reason == "filler" and rows[3].judged_at is not None
    assert n == 3 and len(fake.calls) == 1


def test_claude_may_promote_a_universe_only_story(tri) -> None:
    _seed_cluster(1, tickers=("MSFT",), sources=1)
    tri({1: (1, "reprices the whole sector")})
    T.run_triage(NOW, picture=None)
    row = _rows()[1]
    assert (row.pile, row.floor) == (1, None)


def test_unreviewed_clusters_are_stored_as_not_reviewed(tri, monkeypatch) -> None:
    monkeypatch.setattr(get_config().news.triage, "batch_size", 2)
    for cid, sources in ((1, 5), (2, 4), (3, 3), (4, 2), (5, 1)):
        _seed_cluster(cid, tickers=("MSFT",), sources=sources)
    fake = tri({1: (2, "a"), 2: (3, "b")})
    assert T.run_triage(NOW, picture=None) == 2
    rows = _rows()
    assert sorted(rows) == [1, 2, 3, 4, 5]
    assert [rows[i].pile for i in (1, 2)] == [2, 3]
    assert all(rows[i].pile is None and rows[i].judged_at is None for i in (3, 4, 5))
    assert all(rows[i].reason == "" for i in (3, 4, 5))
    assert rows[3].rank > rows[5].rank > 0  # the presort rank is stored for every cluster
    assert len(fake.calls) == 1  # one call for the batch, not one per cluster


def test_a_not_reviewed_cluster_that_gains_an_alert_is_triaged_again(tri, monkeypatch) -> None:
    monkeypatch.setattr(get_config().news.triage, "batch_size", 1)
    _seed_cluster(1, tickers=("MSFT",), sources=5)
    _seed_cluster(2, tickers=("XYZ",), sources=1)
    tri({1: (2, "worth a line")})
    T.run_triage(NOW, picture=None)
    assert _rows()[2].pile is None  # outside the batch: not reviewed

    _seed_alert([2], age_min=5)  # an alert rule fires on it afterwards
    fake = tri({2: (3, "no")})
    T.run_triage(NOW + timedelta(hours=2), picture=None)
    row = _rows()[2]
    assert (row.pile, row.floor) == (2, "alert")  # judged again, and floored
    assert "C2" in fake.calls[0]["prompt"] and "C1" not in fake.calls[0]["prompt"]


def test_a_judged_noise_cluster_that_gains_a_floor_is_lifted_without_a_call(tri) -> None:
    _seed_cluster(1, tickers=("XYZ",), sources=1)
    tri({1: (3, "filler")})
    T.run_triage(NOW, picture=None)
    assert _rows()[1].pile == 3

    _seed_alert([1], age_min=5)
    fake = tri({})
    T.run_triage(NOW + timedelta(hours=2), picture=None)
    row = _rows()[1]
    assert (row.pile, row.floor) == (2, "alert") and "floor" in row.reason
    assert fake.calls == []  # nothing new to judge: no model call


def test_triage_does_not_rejudge_a_cluster_it_already_has(tri) -> None:
    _seed_cluster(1, tickers=("MSFT",), sources=2)
    tri({1: (1, "x")})
    T.run_triage(NOW, picture=None)
    fake = tri({1: (3, "y")})
    T.run_triage(NOW + timedelta(hours=2), picture=None)
    assert _rows()[1].pile == 1 and fake.calls == []
    assert get_state("triage_last_run") == (NOW + timedelta(hours=2)).isoformat()


def test_triage_ignores_cluster_ids_the_model_made_up(tri) -> None:
    """The replacement for the removed editor pass's 'drops unknown cluster ids' test."""
    _seed_cluster(1, tickers=("MSFT",), sources=2)
    tri({1: (2, "ok"), 99: (1, "ghost")})
    assert T.run_triage(NOW, picture=None) == 1
    assert sorted(_rows()) == [1]


def test_llm_failure_keeps_the_floor(tri) -> None:
    _seed_cluster(1, tickers=("XYZ",), sources=2)
    _seed_cluster(2, tickers=("AAPL",), sources=2)
    _seed_cluster(3, tickers=("MSFT",), sources=2)
    _seed_alert([1])
    tri(fail=True)
    assert T.run_triage(NOW, picture=None) == 0
    rows = _rows()
    assert (rows[1].pile, rows[1].reason) == (2, "floor: alert rule")
    assert (rows[2].pile, rows[2].reason) == (2, "floor: held name")
    assert rows[3].pile is None and rows[3].reason == ""  # stays not reviewed


def test_triage_uses_the_picture_budget(tri) -> None:
    _seed_cluster(1, tickers=("MSFT",), sources=2)
    fake = tri({1: (2, "ok")})
    T.run_triage(NOW, picture=None)
    assert [c["purpose"] for c in fake.calls] == ["picture"]


def test_the_triage_prompt_carries_the_picture_and_the_clusters(tri) -> None:
    _seed_cluster(1, category="macro", tickers=("MSFT",), sources=3, topic="fed")
    fake = tri({1: (2, "ok")})
    picture = MarketPicture(
        version="v",
        built_at=NOW - timedelta(hours=1),
        stories=[
            PictureStory(
                id=7,
                title="Tariff escalation",
                started_on=date(2026, 10, 12),
                description="Tariffs keep the index weak.",
            )
        ],
    )
    T.run_triage(NOW, picture=picture)
    prompt = fake.calls[0]["prompt"]
    assert "=== MARKET PICTURE ===" in prompt and "S7 Tariff escalation" in prompt
    assert "C1 [macro/fed, 3 sources, MSFT] headline 1" in prompt
    assert "1 = shapes the market picture" in prompt and "3 = noise" in prompt


def test_an_empty_window_makes_no_call(tri) -> None:
    fake = tri({})
    assert T.run_triage(NOW, picture=None) == 0 and fake.calls == []


# --- when the loop runs -----------------------------------------------------------------


def test_triage_runs_once_after_each_slot_on_a_trading_day() -> None:
    times = ["10:30", "12:30", "14:30"]
    # 10:29 ET (14:29 UTC): nothing yet; 10:31: due; after running at 10:31 it is not due again
    assert not T.triage_due(datetime(2026, 10, 22, 14, 29, tzinfo=UTC), None, times)
    assert T.triage_due(datetime(2026, 10, 22, 14, 31, tzinfo=UTC), None, times)
    ran = datetime(2026, 10, 22, 14, 31, tzinfo=UTC)
    assert not T.triage_due(datetime(2026, 10, 22, 15, 5, tzinfo=UTC), ran, times)
    assert T.triage_due(datetime(2026, 10, 22, 16, 31, tzinfo=UTC), ran, times)  # 12:31 ET
    # a Saturday is not a trading day
    assert not T.triage_due(datetime(2026, 10, 24, 16, 0, tzinfo=UTC), None, times)


# --- the digest -------------------------------------------------------------------------


def test_writer_and_digest_prompts_carry_the_picture() -> None:
    from src.news.prompts import digest_prompt, writer_prompt

    text = "=== MARKET PICTURE ===\nSPY: normal"
    w = writer_prompt(
        "ticker_move",
        headlines="N1 x",
        facts=FactSheet(),
        prior=None,
        reaction=None,
        picture_text=text,
    )
    d = digest_prompt([_cv(1)], FactSheet(), picture_text=text)
    for prompt, anchor in ((w, "EVENT TYPE"), (d, "TASK:")):
        assert "SPY: normal" in prompt
        assert (
            prompt.index("Rules:") < prompt.index("=== MARKET PICTURE ===") < prompt.index(anchor)
        )
        assert "do not quote its numbers" in prompt  # context for framing, not a source of numbers
    # without a picture the prompts are what they were
    assert "MARKET PICTURE" not in writer_prompt(
        "ticker_move", headlines="N1 x", facts=FactSheet(), prior=None, reaction=None
    )
    assert "MARKET PICTURE" not in digest_prompt([_cv(1)], FactSheet())


def _state(spy: MarketRegime, qqq: MarketRegime) -> RegimeState:
    day = date(2026, 10, 22)

    def ir(index, eff):
        return IndexRegime(
            index=index, base=eff, base_date=day, since=day, base_since=day, effective=eff
        )

    return RegimeState(as_of=NOW, spy=ir("SPY", spy), qqq=ir("QQQ", qqq))


def test_regime_line_is_deterministic_text() -> None:
    from src.news.digests import regime_line

    assert regime_line(_state(MarketRegime.NORMAL, MarketRegime.STRESSED)) == (
        "SPY normal · QQQ stressed"
    )
    assert regime_line(None) is None


def test_ranked_threads_orders_by_pile_then_rank_and_keeps_floored() -> None:
    def view(cid, pile, rank, floor=None):
        return TriageView(cluster_id=cid, headline="h", pile=pile, floor=floor, rank=rank)

    views = [
        view(1, 2, 1.0),
        view(2, 1, 0.5),
        view(3, 3, 9.0),  # noise: never shown, however high its rank
        view(4, None, 0.9),  # not reviewed: not shown
        view(5, 2, 3.0, floor="alert"),
        view(6, None, 2.0, floor="held"),  # floored but never given a pile: still shown
    ]
    assert T.ranked_threads(views, limit=10) == [2, 5, 6, 1]
    assert T.ranked_threads(views, limit=2) == [2, 5]


async def test_digest_orders_threads_by_pile_and_shows_the_deterministic_regime(
    news_db, monkeypatch
) -> None:
    from src.news import service as S
    from src.news.digests import DigestInputs
    from src.news.schemas import CardPayload, DigestRead

    svc = S.NewsService(get_config())
    svc.publisher = None
    monkeypatch.setattr(svc, "_backdrop", lambda now: None)
    monkeypatch.setattr(
        S, "load_regime_state", lambda: _state(MarketRegime.NORMAL, MarketRegime.STRESSED)
    )
    now = datetime(2026, 10, 22, 12, 5, tzinfo=UTC)
    for cid in (1, 2, 3, 4):
        _seed_cluster(cid, category="macro", sources=2, age_min=60)
    # 4 is a floored single-source story the digest's own 30-cluster query never returned
    with news_session() as s:
        for cid, pile, rank, floor in (
            (1, 2, 1.0, None),
            (2, 1, 0.5, None),
            (3, 3, 9.0, None),
            (4, 2, 3.0, "held"),
        ):
            s.add(StoryTriageRow(cluster_id=cid, pile=pile, rank=rank, floor=floor, reason="r"))
    cls = [_cv(i, category="macro", sources=2) for i in (1, 2, 3)]
    captured: list[DigestInputs] = []

    def fake_build(name, inp):
        captured.append(inp)
        return CardPayload(kind="digest_premarket", title="Pre-market", emoji="🗞️", when=now)

    monkeypatch.setattr(
        S,
        "gather_inputs",
        lambda name, **kw: DigestInputs(
            now=now,
            tape={},
            clusters=list(cls),
            econ=[],
            earnings=[],
            held=set(),
            positions=[],
            movers=[],
            max_threads=3,
        ),
    )
    monkeypatch.setattr(S, "build_digest", fake_build)
    ran: list[datetime] = []
    monkeypatch.setattr(S, "run_triage", lambda n, *, picture: ran.append(n) or 0)
    set_state("triage_last_ok", (now - timedelta(hours=1)).isoformat())  # the model judged them
    asked: list[list[int]] = []

    def fake_reads(threads, b, now, picture_text=None):
        asked.append([t.id for t in threads])
        return {2: DigestRead(cluster_id=2, headline="h", read="r", verdict="priced_in")}

    monkeypatch.setattr(X, "digest_reads", fake_reads)
    await svc._digests(now)

    assert ran == [now]  # triage ran inside the digest, before ranking
    assert asked == [[2, 4, 1]]  # pile 1 first, then the floored held story, then pile 2
    inp = captured[0]
    assert inp.thread_order == [[2], [4], [1]]
    assert [c.id for c in inp.clusters] == [2, 4, 1]  # 3 is noise; 4 was loaded from the store
    assert inp.regime == "SPY normal · QQQ stressed"
    assert set(inp.reads) == {2}


async def test_digest_keeps_the_deterministic_order_when_the_model_judged_nothing(
    news_db, monkeypatch
) -> None:
    """The model was down or capped: the stored piles are floors and not-reviewed rows only, so
    the digest must not turn into an empty one."""
    from src.news import service as S
    from src.news.digests import DigestInputs
    from src.news.schemas import CardPayload

    svc = S.NewsService(get_config())
    svc.publisher = None
    monkeypatch.setattr(svc, "_backdrop", lambda now: None)
    monkeypatch.setattr(S, "load_regime_state", lambda: None)
    now = datetime(2026, 10, 22, 12, 5, tzinfo=UTC)
    for cid in (1, 2):
        _seed_cluster(cid, category="macro", sources=2, age_min=60)
    with news_session() as s:
        s.add(StoryTriageRow(cluster_id=1, pile=None, rank=0.4))
        s.add(StoryTriageRow(cluster_id=2, pile=None, rank=0.4))
    captured: list[DigestInputs] = []
    monkeypatch.setattr(
        S,
        "gather_inputs",
        lambda name, **kw: DigestInputs(
            now=now,
            tape={},
            clusters=[_cv(1), _cv(2)],
            econ=[],
            earnings=[],
            held=set(),
            positions=[],
            movers=[],
        ),
    )
    monkeypatch.setattr(
        S,
        "build_digest",
        lambda name, inp: (
            captured.append(inp)
            or CardPayload(kind="digest_premarket", title="Pre-market", emoji="🗞️", when=now)
        ),
    )
    monkeypatch.setattr(S, "run_triage", lambda n, *, picture: 0)
    monkeypatch.setattr(X, "digest_reads", lambda t, b, now, picture_text=None: {})
    await svc._digests(now)
    assert [c.id for c in captured[0].clusters] == [1, 2]
    assert captured[0].thread_order is None  # no pile ordering: the deterministic default


def test_triage_ok_since_follows_the_last_usable_answer(tri) -> None:
    assert not T.triage_ok_since(NOW - timedelta(hours=1))
    _seed_cluster(1, tickers=("MSFT",), sources=2)
    tri({1: (2, "ok")})
    T.run_triage(NOW, picture=None)
    assert T.triage_ok_since(NOW - timedelta(hours=1))
    assert not T.triage_ok_since(NOW + timedelta(minutes=1))
    # a failed call does not refresh it
    _seed_cluster(2, tickers=("MSFT",), sources=2)
    tri(fail=True)
    T.run_triage(NOW + timedelta(hours=3), picture=None)
    assert not T.triage_ok_since(NOW + timedelta(hours=2))


async def test_a_failing_triage_does_not_stop_the_digest(news_db, monkeypatch) -> None:
    from src.news import service as S
    from src.news.digests import DigestInputs
    from src.news.schemas import CardPayload

    svc = S.NewsService(get_config())
    svc.publisher = None
    monkeypatch.setattr(svc, "_backdrop", lambda now: None)
    monkeypatch.setattr(S, "load_regime_state", lambda: None)
    now = datetime(2026, 10, 22, 12, 5, tzinfo=UTC)
    cls = [_cv(i, category="macro", sources=2) for i in (1, 2)]
    captured: list[DigestInputs] = []
    monkeypatch.setattr(
        S,
        "gather_inputs",
        lambda name, **kw: DigestInputs(
            now=now,
            tape={},
            clusters=list(cls),
            econ=[],
            earnings=[],
            held=set(),
            positions=[],
            movers=[],
        ),
    )
    monkeypatch.setattr(
        S,
        "build_digest",
        lambda name, inp: (
            captured.append(inp)
            or CardPayload(kind="digest_premarket", title="Pre-market", emoji="🗞️", when=now)
        ),
    )

    def boom(n, *, picture):
        raise RuntimeError("triage exploded")

    monkeypatch.setattr(S, "run_triage", boom)
    monkeypatch.setattr(X, "digest_reads", lambda t, b, now, picture_text=None: {})
    await svc._digests(now)
    assert [c.id for c in captured[0].clusters] == [1, 2]  # the deterministic order, regime-less
    assert captured[0].regime is None


async def test_digest_no_longer_calls_the_editor(news_db, monkeypatch) -> None:
    from src.news import prompts as P
    from src.news import service as S
    from src.news.digests import DigestInputs
    from src.news.schemas import CardPayload

    assert not hasattr(X, "edit_digest") and not hasattr(P, "editor_prompt")
    svc = S.NewsService(get_config())
    svc.publisher = None
    monkeypatch.setattr(svc, "_backdrop", lambda now: None)
    monkeypatch.setattr(S, "load_regime_state", lambda: None)
    now = datetime(2026, 10, 22, 12, 5, tzinfo=UTC)
    monkeypatch.setattr(
        S,
        "gather_inputs",
        lambda name, **kw: DigestInputs(
            now=now,
            tape={},
            clusters=[_cv(1)],
            econ=[],
            earnings=[],
            held=set(),
            positions=[],
            movers=[],
        ),
    )
    monkeypatch.setattr(
        S,
        "build_digest",
        lambda name, inp: CardPayload(
            kind="digest_premarket", title="Pre-market", emoji="🗞️", when=now
        ),
    )
    monkeypatch.setattr(S, "run_triage", lambda n, *, picture: 0)
    fake = FakeLlm({})
    monkeypatch.setattr(X, "call_llm", fake)
    await svc._digests(now)
    assert [c["prefix"] for c in fake.calls] == ["news:digest"]  # the writer read; no editor


async def test_triage_loop_runs_only_when_a_slot_has_passed(news_db, monkeypatch) -> None:
    from src.news import service as S
    from src.news.store.state import set_state

    svc = S.NewsService(get_config())
    ran: list[datetime] = []
    monkeypatch.setattr(S, "run_triage", lambda n, *, picture: ran.append(n) or 0)
    await svc._triage(datetime(2026, 10, 22, 13, 0, tzinfo=UTC))  # 09:00 ET: no slot yet
    assert ran == []
    at = datetime(2026, 10, 22, 14, 40, tzinfo=UTC)  # 10:40 ET
    await svc._triage(at)
    assert ran == [at]
    set_state("triage_last_run", at.isoformat())
    await svc._triage(at + timedelta(minutes=1))
    assert ran == [at]  # already ran for that slot

    monkeypatch.setattr(svc.ncfg.triage, "enabled", False)
    await svc._triage(datetime(2026, 10, 22, 17, 0, tzinfo=UTC))
    assert ran == [at]  # switched off: the 12:30 slot does nothing


def test_the_triage_loop_is_registered() -> None:
    from src.news import service as S

    names = [n for n, _i, _f in S.NewsService(get_config()).loops()]
    assert "triage" in names


def test_latest_picture_text_is_none_before_a_picture_exists(news_db) -> None:
    assert X.latest_picture_text(NOW) is None


def test_latest_picture_text_renders_the_stored_picture(news_db) -> None:
    from src.news.store.models import MarketPictureRow

    pic = MarketPicture(version="v1", built_at=NOW - timedelta(hours=1))
    with news_session() as s:
        s.add(
            MarketPictureRow(
                built_at=naive_utc(pic.built_at),
                version=pic.version,
                payload=pic.model_dump(mode="json"),
                stale=False,
            )
        )
    with news_session() as s:
        assert queries.latest_picture(s) is not None
    text = X.latest_picture_text(NOW)
    assert text is not None and text.startswith("=== MARKET PICTURE ===")
