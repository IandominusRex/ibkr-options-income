from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from src.common.config import get_config
from src.news import triggers as T
from src.news.playbook import load_playbook
from src.news.schemas import ClusterView, EarningsView, EconEventView
from src.news.tape import Quote

A = get_config().news.alerts
NOW = datetime(2026, 10, 14, 15, 0, tzinfo=UTC)
DAY = date(2026, 10, 14)


def _ev(title, at, actual="1"):
    return EconEventView(
        event_key=f"{at:%H:%M}|{title}",
        title=title,
        scheduled_at=at,
        impact="High",
        actual=actual,
    )


def test_simultaneous_releases_group_into_one_alert() -> None:
    at = datetime(2026, 10, 14, 12, 30, tzinfo=UTC)
    evs = [
        _ev("Core CPI m/m", at),
        _ev("CPI m/m", at),
        _ev("CPI y/y", at),
        _ev("Unemployment Claims", at),
    ]
    cands = T.group_macro_releases(evs, load_playbook())
    assert len(cands) == 1
    c = cands[0]
    assert c.critical and c.detail["primary"] == "CPI m/m" and len(c.event_keys) == 4


def test_earnings_critical_only_for_held() -> None:
    rel = [
        EarningsView(symbol="NVDA", report_date=DAY, status="released"),
        EarningsView(symbol="AAPL", report_date=DAY, status="released"),
        EarningsView(symbol="ZZZ", report_date=DAY, status="released"),
    ]
    cands = {c.subject: c for c in T.detect_earnings(rel, held={"NVDA"}, universe={"NVDA", "AAPL"})}
    assert cands["NVDA"].critical and not cands["AAPL"].critical and "ZZZ" not in cands


def test_index_levels_pick_most_extreme_unfired() -> None:
    tape = {
        "SPY": Quote(symbol="SPY", change_pct=-2.4),
        "QQQ": Quote(symbol="QQQ", change_pct=0.3),
    }
    crossed = T.detect_index_levels(tape, A)
    assert {c.subject for c in crossed} == {"SPY:-1", "SPY:-2"}
    new = T.pick_new_levels(crossed, fired=set())
    assert [c.subject for c in new] == ["SPY:-2"] and new[0].critical
    assert T.pick_new_levels(crossed, fired={"SPY:-1", "SPY:-2"}) == []


def test_vix_jump_and_level() -> None:
    subs = {
        c.subject
        for c in T.detect_vix(Quote(symbol="^VIX", last=26.0, prev_close=21.0, change_pct=23.8), A)
    }
    assert subs == {"VIX:jump", "VIX:25"}


def test_ticker_moves_thresholds() -> None:
    moves = [
        T.TickerMove(symbol="NVDA", change_pct=-6, abnormal_pct=-5, sigma=2.2),
        T.TickerMove(symbol="AAPL", change_pct=-4, abnormal_pct=-3, sigma=2.5),
        T.TickerMove(symbol="PLTR", change_pct=-9, abnormal_pct=-8, sigma=3.4),
    ]
    subs = {
        c.subject: c
        for c in T.detect_ticker_moves(
            moves, held={"NVDA"}, universe={"NVDA", "AAPL", "PLTR"}, cfg=A
        )
    }
    assert set(subs) == {"NVDA", "PLTR"} and subs["NVDA"].critical and not subs["PLTR"].critical


def test_breaking_needs_sources_topic_and_reaction() -> None:
    c = ClusterView(
        id=1,
        headline="Ceasefire agreed",
        category="geopolitics",
        first_seen=NOW,
        last_seen=NOW,
        source_count=3,
        topic_class="ceasefire",
    )
    assert T.detect_breaking([c], reaction_pct=0.7, cfg=A)[0].cluster_ids == [1]
    assert T.detect_breaking([c], reaction_pct=0.2, cfg=A) == []
    assert (
        T.detect_breaking([c.model_copy(update={"source_count": 1})], reaction_pct=0.9, cfg=A) == []
    )
    assert (
        T.detect_breaking([c.model_copy(update={"topic_class": "other"})], reaction_pct=0.9, cfg=A)
        == []
    )


def test_gate_once_per_day_and_hourly_cap(news_db) -> None:
    from src.news.store.models import NewsPostRow
    from src.news.store.queries import naive_utc
    from src.news.store.session import news_session

    g = T.AlertGate(A)
    c = T.AlertCandidate(kind="ticker_move", subject="AAPL", critical=False)
    assert g.admit(c, now=NOW, day=DAY)
    assert not g.admit(c, now=NOW, day=DAY)
    with news_session() as s:
        for i in range(A.max_per_hour):
            s.add(
                NewsPostRow(
                    kind="ticker_move",
                    posted_at=naive_utc(NOW - timedelta(minutes=i)),
                    critical=False,
                    payload={},
                    cluster_ids=[],
                    silent=False,
                    edits=0,
                    stage="facts",
                )
            )
    other = T.AlertCandidate(kind="ticker_move", subject="MSFT", critical=False)
    assert not g.admit(other, now=NOW, day=DAY)
    assert g.admit(other.model_copy(update={"critical": True}), now=NOW, day=DAY)


def test_gate_mark_twice_is_idempotent(news_db) -> None:
    g = T.AlertGate(A)
    g.mark("ticker_move", "AAPL", DAY, NOW)
    g.mark("ticker_move", "AAPL", DAY, NOW)  # unique (trigger, subject, day): no raise, no dup
    assert g.fired_subjects("ticker_move", DAY) == {"AAPL"}
    assert g.fired_subjects("ticker_move", DAY + timedelta(days=1)) == set()


def test_capped_alert_is_not_marked_fired_so_it_can_retry(news_db) -> None:
    from src.news.store.models import NewsPostRow
    from src.news.store.queries import naive_utc
    from src.news.store.session import news_session

    with news_session() as s:
        for i in range(A.max_per_hour):
            s.add(
                NewsPostRow(
                    kind="ticker_move",
                    posted_at=naive_utc(NOW - timedelta(minutes=i)),
                    critical=False,
                    payload={},
                    cluster_ids=[],
                    silent=False,
                    edits=0,
                    stage="facts",
                )
            )
    g = T.AlertGate(A)
    msft = T.AlertCandidate(kind="ticker_move", subject="MSFT", critical=False)
    assert not g.admit(msft, now=NOW, day=DAY)
    assert "MSFT" not in g.fired_subjects("ticker_move", DAY)
    # An hour later the window has emptied and the same alert is admitted.
    assert g.admit(msft, now=NOW + timedelta(hours=2), day=DAY)


def test_macro_alerts_only_for_high_impact_or_playbook_releases() -> None:
    """Spec §7.2: the macro-print alert is for high-impact releases. Medium releases alert only
    when the playbook knows them (claims, ISM services, UoM), and never as critical; a medium
    release with no playbook entry (e.g. crude inventories) does not alert at all."""
    at = datetime(2026, 10, 14, 14, 30, tzinfo=UTC)
    crude = _ev("Crude Oil Inventories", at).model_copy(update={"impact": "Medium"})
    assert T.group_macro_releases([crude], load_playbook()) == []
    claims = _ev("Unemployment Claims", at).model_copy(update={"impact": "Medium"})
    (c,) = T.group_macro_releases([claims, crude], load_playbook())
    assert not c.critical and c.event_keys == [claims.event_key]
    cpi = _ev("CPI m/m", at)
    (c,) = T.group_macro_releases([claims, cpi, crude], load_playbook())
    assert c.critical and set(c.event_keys) == {claims.event_key, cpi.event_key}
