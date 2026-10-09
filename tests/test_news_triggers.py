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
    assert T.detect_breaking([c], reactions={1: 0.7}, cfg=A)[0].cluster_ids == [1]
    assert T.detect_breaking([c], reactions={1: -0.7}, cfg=A)[0].detail["reaction_pct"] == -0.7
    assert T.detect_breaking([c], reactions={1: 0.2}, cfg=A) == []
    assert T.detect_breaking([c], reactions={}, cfg=A) == []
    assert (
        T.detect_breaking([c.model_copy(update={"source_count": 1})], reactions={1: 0.9}, cfg=A)
        == []
    )
    assert (
        T.detect_breaking(
            [c.model_copy(update={"topic_class": "other"})], reactions={1: 0.9}, cfg=A
        )
        == []
    )


def test_breaking_reaction_is_measured_from_the_story_not_the_day() -> None:
    """Spec §7.2: |ES/SPY move| ≥ 0.5 % within 30 min of first_seen. The day's change is not a
    reaction: on a −1 % day every two-source fed/energy story would otherwise fire critically."""
    import pandas as pd

    from src.news.reaction import move_after

    first = datetime(2026, 10, 14, 15, 0, tzinfo=UTC)
    idx = pd.date_range(first - timedelta(minutes=5), periods=60, freq="1min", tz=UTC)
    flat = pd.DataFrame({"Close": [99.0] * 60}, index=idx)  # already −1 % on the day, no reaction
    assert move_after(flat, first, window_min=30, now=first + timedelta(minutes=40)) == 0.0
    jump = pd.DataFrame(
        {"Close": [100.0 if t < first + timedelta(minutes=10) else 100.8 for t in idx]}, index=idx
    )
    mv = move_after(jump, first, window_min=30, now=first + timedelta(minutes=12))
    assert mv is not None and round(mv, 2) == 0.8
    late = pd.DataFrame(
        {"Close": [100.0 if t < first + timedelta(minutes=45) else 102.0 for t in idx]}, index=idx
    )
    assert move_after(late, first, window_min=30, now=first + timedelta(minutes=50)) == 0.0
    assert move_after(pd.DataFrame(), first, window_min=30, now=first) is None


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


def test_capped_alert_is_held_for_the_digest_and_released_if_it_posts(news_db) -> None:
    """Spec §7.2: a non-critical alert the hourly cap drops rolls into the next digest."""
    from src.news.store.models import NewsPostRow
    from src.news.store.queries import naive_utc
    from src.news.store.session import news_session
    from src.news.store.state import held_alerts

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
    msft = T.AlertCandidate(
        kind="ticker_move",
        subject="MSFT",
        critical=False,
        detail={"change_pct": 4.1, "abnormal_pct": 3.9, "sigma": 3.2},
    )
    assert not g.admit(msft, now=NOW, day=DAY)
    assert not g.admit(msft, now=NOW + timedelta(minutes=1), day=DAY)  # re-detected: held once
    held = held_alerts()
    assert [t for _, _, t in held] == ["MSFT · +4.1% · 3.2σ"]
    assert held[0][1] == NOW
    # The window empties and the alert posts after all: the digest no longer needs it.
    assert g.admit(msft, now=NOW + timedelta(hours=2), day=DAY)
    assert held_alerts() == []


def test_held_text_for_every_non_breaking_kind() -> None:
    mk = lambda kind, subject, **d: T.AlertCandidate(  # noqa: E731
        kind=kind, subject=subject, critical=False, detail=d
    )
    assert (
        T.held_text(mk("macro_print", "x", primary="ISM Services PMI"))
        == "ISM Services PMI released"
    )
    assert T.held_text(mk("earnings", "ORCL")) == "ORCL reported earnings"
    assert (
        T.held_text(mk("market_move", "QQQ:-2", level=-2.0, change_pct=-2.4))
        == "QQQ -2.4% (crossed -2.0%)"
    )
    assert T.held_text(mk("vix_spike", "VIX:jump", change_pct=21.0)) == "VIX +21.0%"
    assert T.held_text(mk("vix_spike", "VIX:30", level=30.0, last=31.2)) == "VIX at 31.2"
