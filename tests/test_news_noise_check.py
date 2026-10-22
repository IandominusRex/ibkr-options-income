"""Task 11: safeguard 2, the market-reaction check that promotes a dismissed story late."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest
from sqlalchemy import select

from src.common.config import get_config
from src.news import noise_check as N
from src.news.store.models import NewsClusterRow, NewsItemRow, NewsPostRow, StoryTriageRow
from src.news.store.queries import naive_utc
from src.news.store.session import news_session

NOW = datetime(2026, 10, 22, 15, 0, tzinfo=UTC)  # 11:00 ET, Thursday
WINDOW = timedelta(minutes=60)


# --- fixtures -----------------------------------------------------------------------------


def _seed(
    cid: int,
    *,
    category: str = "macro",
    tickers: tuple[str, ...] = (),
    first_seen: datetime = NOW - timedelta(minutes=75),
    judged_at: datetime | None = None,
    pile: int | None = 3,
    promoted_at: datetime | None = None,
    reason: str = "calendar filler",
) -> None:
    with news_session() as s:
        s.add(
            NewsClusterRow(
                id=cid,
                headline=f"headline {cid}",
                category=category,
                first_seen=naive_utc(first_seen),
                last_seen=naive_utc(first_seen),
                source_count=2,
                tickers=list(tickers),
                tags=[],
                topic_class="other",
            )
        )
        s.add(
            StoryTriageRow(
                cluster_id=cid,
                pile=pile,
                rank=1.0,
                reason=reason,
                judged_at=naive_utc(judged_at or first_seen + timedelta(minutes=10)),
                promoted_at=naive_utc(promoted_at) if promoted_at else None,
                promoted_move_pct=-1.0 if promoted_at else None,
            )
        )


def _bars(first_seen: datetime, move_pct: float) -> pd.DataFrame:
    """1-minute bars flat at 100 until the story is first seen, then moving linearly so the close
    one window later is *move_pct* away from it."""
    idx = pd.date_range(
        first_seen - timedelta(minutes=5), first_seen + timedelta(minutes=70), freq="1min", tz=UTC
    )
    closes = []
    for ts in idx:
        frac = min(max((ts - first_seen).total_seconds() / WINDOW.total_seconds(), 0.0), 1.0)
        closes.append(100.0 * (1 + move_pct / 100 * frac))
    return pd.DataFrame({"Close": closes}, index=idx)


def _bars_for(moves: dict[str, float], first_seen: datetime = NOW - timedelta(minutes=75)):
    def bars_for(symbol: str) -> pd.DataFrame:
        if symbol not in moves:
            return pd.DataFrame()
        return _bars(first_seen, moves[symbol])

    return bars_for


def _rows() -> dict[int, StoryTriageRow]:
    with news_session() as s:
        return {r.cluster_id: r for r in s.scalars(select(StoryTriageRow))}


# --- who is promoted ----------------------------------------------------------------------


def test_a_dismissed_macro_story_is_promoted_on_an_index_move(news_db) -> None:
    _seed(1)
    got = N.find_promotions(
        NOW, bars_for=_bars_for({"SPY": -1.4, "QQQ": -1.8}), beta_for=lambda s: 1.0
    )
    assert [(p.cluster_id, p.basis, p.symbol) for p in got] == [(1, "index", "QQQ")]
    assert got[0].move_pct == pytest.approx(-1.8, abs=0.05)  # signed, the larger of the two
    row = _rows()[1]
    assert row.pile == 2 and row.promoted_at is not None
    assert row.promoted_move_pct == pytest.approx(-1.8, abs=0.05)
    assert "promoted" in row.reason and "calendar filler" in row.reason  # the audit trail stays


def test_a_small_index_move_promotes_nothing(news_db) -> None:
    _seed(1)
    assert (
        N.find_promotions(
            NOW, bars_for=_bars_for({"SPY": 0.4, "QQQ": -0.6}), beta_for=lambda s: 1.0
        )
        == []
    )
    row = _rows()[1]
    assert row.pile == 3 and row.promoted_at is None


@pytest.mark.parametrize(
    ("nvda_move", "promoted"),
    [
        (-5.0, False),  # -5.0 - 1.5 x -2.0 = -2.0: the index explains most of it
        (-6.5, True),  # -6.5 - 1.5 x -2.0 = -3.5: a real residual
        (-3.0, False),  # -3.0 - 1.5 x -2.0 = 0: exactly what its beta predicts
        (+0.5, True),  # +0.5 - 1.5 x -2.0 = +3.5: it held up while the index fell
    ],
)
def test_ticker_story_uses_the_beta_adjusted_move(news_db, nvda_move, promoted) -> None:
    _seed(1, category="ticker", tickers=("NVDA",))
    got = N.find_promotions(
        NOW,
        bars_for=_bars_for({"SPY": -2.0, "QQQ": -2.2, "NVDA": nvda_move}),
        beta_for=lambda s: 1.5,
    )
    assert bool(got) is promoted
    if promoted:
        assert (got[0].basis, got[0].symbol) == ("ticker", "NVDA")
        assert got[0].move_pct == pytest.approx(nvda_move - 1.5 * -2.0, abs=0.1)


def test_a_ticker_story_ignores_the_index_move_alone(news_db) -> None:
    """A ticker cluster is judged on its own name, not on the whole market's drop."""
    _seed(1, category="ticker", tickers=("NVDA",))
    got = N.find_promotions(
        NOW, bars_for=_bars_for({"SPY": -3.0, "QQQ": -3.5, "NVDA": -4.4}), beta_for=lambda s: 1.0
    )
    assert got == []  # -4.4 - (-3.0) = -1.4 residual < 3.0


def test_the_ticker_with_the_largest_residual_is_the_one_named(news_db) -> None:
    _seed(1, category="ticker", tickers=("AAPL", "NVDA", "SPY"))
    got = N.find_promotions(
        NOW,
        bars_for=_bars_for({"SPY": 0.0, "QQQ": 0.0, "AAPL": -3.2, "NVDA": -4.6}),
        beta_for=lambda s: 1.0,
    )
    assert [(p.symbol, round(p.move_pct, 1)) for p in got] == [("NVDA", -4.6)]


def test_missing_bars_promote_nothing(news_db) -> None:
    _seed(1)
    _seed(2, category="ticker", tickers=("NVDA",))
    assert N.find_promotions(NOW, bars_for=lambda s: pd.DataFrame(), beta_for=lambda s: 1.0) == []
    # a ticker with bars but no SPY bars to net out cannot be beta-adjusted either
    assert N.find_promotions(NOW, bars_for=_bars_for({"NVDA": -9.0}), beta_for=lambda s: 1.0) == []
    assert all(r.pile == 3 and r.promoted_at is None for r in _rows().values())


# --- which rows are looked at -------------------------------------------------------------


def test_only_judged_noise_is_considered(news_db) -> None:
    _seed(1, pile=2)  # worth telling: already shown
    _seed(2, pile=1)
    _seed(3, pile=None)  # not reviewed: nobody judged it noise
    got = N.find_promotions(
        NOW, bars_for=_bars_for({"SPY": -2.0, "QQQ": -2.0}), beta_for=lambda s: 1.0
    )
    assert got == []


def test_a_story_is_not_checked_before_its_window_has_closed(news_db) -> None:
    first_seen = NOW - timedelta(minutes=50)  # the 60-minute window is still open
    _seed(1, first_seen=first_seen)
    got = N.find_promotions(
        NOW, bars_for=_bars_for({"SPY": -2.0, "QQQ": -2.0}, first_seen), beta_for=lambda s: 1.0
    )
    assert got == []  # a partial window is not the reaction: it is measured once it has closed
    later = N.find_promotions(
        NOW + timedelta(minutes=15),
        bars_for=_bars_for({"SPY": -2.0, "QQQ": -2.0}, first_seen),
        beta_for=lambda s: 1.0,
    )
    assert [p.cluster_id for p in later] == [1]


def test_an_old_story_judged_long_ago_is_not_checked(news_db) -> None:
    first_seen = NOW - timedelta(hours=5)
    _seed(1, first_seen=first_seen, judged_at=NOW - timedelta(hours=4))
    _seed(2, first_seen=NOW - timedelta(minutes=89))  # just inside the band
    got = N.find_promotions(
        NOW,
        bars_for=lambda s: pd.concat(
            [_bars(first_seen, -2.0), _bars(NOW - timedelta(minutes=89), -2.0)]
        ).sort_index(),
        beta_for=lambda s: 1.0,
    )
    assert [p.cluster_id for p in got] == [2]


def test_a_story_judged_late_is_still_checked(news_db) -> None:
    """Triage runs a few times a day, so a story is usually judged long after it was first seen.
    The check follows the judgement: its reaction window is measured from when the story first
    appeared, but a row is eligible for 90 minutes after it was judged."""
    first_seen = NOW - timedelta(hours=3)
    _seed(1, first_seen=first_seen, judged_at=NOW - timedelta(minutes=5))
    got = N.find_promotions(
        NOW, bars_for=_bars_for({"SPY": -1.6, "QQQ": -1.2}, first_seen), beta_for=lambda s: 1.0
    )
    assert [(p.cluster_id, p.symbol) for p in got] == [(1, "SPY")]


def test_already_promoted_is_not_promoted_again(news_db) -> None:
    _seed(1)
    # a row that somehow reads noise again after a promotion is still never promoted twice
    _seed(2, pile=3, promoted_at=NOW - timedelta(hours=3))
    bars = _bars_for({"SPY": -2.0, "QQQ": -2.0})
    got = N.find_promotions(NOW, bars_for=bars, beta_for=lambda s: 1.0)
    assert [p.cluster_id for p in got] == [1]
    assert (
        N.find_promotions(NOW + timedelta(minutes=5), bars_for=bars, beta_for=lambda s: 1.0) == []
    )
    row = _rows()[2]
    assert row.pile == 3 and row.promoted_at == naive_utc(NOW - timedelta(hours=3))


def test_one_index_move_promotes_at_most_the_cap(news_db) -> None:
    for cid in range(1, 6):
        _seed(cid)
    bars = _bars_for({"SPY": -2.0, "QQQ": -2.0})
    got = N.find_promotions(NOW, bars_for=bars, beta_for=lambda s: 1.0)
    assert len(got) == 2  # news.triage.max_promotions_per_hour
    # the two just promoted use the whole hour's budget: a minute later nothing more goes out
    assert (
        N.find_promotions(NOW + timedelta(minutes=1), bars_for=bars, beta_for=lambda s: 1.0) == []
    )
    assert sum(1 for r in _rows().values() if r.promoted_at is not None) == 2


def test_the_strongest_moves_are_promoted_first(news_db, monkeypatch) -> None:
    monkeypatch.setattr(get_config().news.triage, "max_promotions_per_hour", 1)
    _seed(1, category="ticker", tickers=("AAA",))
    _seed(2, category="ticker", tickers=("BBB",))
    got = N.find_promotions(
        NOW,
        bars_for=_bars_for({"SPY": 0.0, "QQQ": 0.0, "AAA": -3.5, "BBB": 6.0}),
        beta_for=lambda s: 1.0,
    )
    assert [(p.cluster_id, p.symbol) for p in got] == [(2, "BBB")]


def test_a_promotion_budget_of_zero_promotes_nothing(news_db, monkeypatch) -> None:
    monkeypatch.setattr(get_config().news.triage, "max_promotions_per_hour", 0)
    _seed(1)
    assert (
        N.find_promotions(
            NOW, bars_for=_bars_for({"SPY": -2.0, "QQQ": -2.0}), beta_for=lambda s: 1.0
        )
        == []
    )


# --- beta ---------------------------------------------------------------------------------


def _daily(closes: list[float], end: str = "2026-10-21") -> pd.DataFrame:
    idx = pd.bdate_range(end=end, periods=len(closes))
    return pd.DataFrame({"Close": closes}, index=idx)


def test_beta_vs_spy_is_none_on_short_history(monkeypatch) -> None:
    spy = [100.0 * (1.001**i) * (1 + 0.01 * ((-1) ** i)) for i in range(20)]

    class Prov:
        def get_ohlcv(self, symbol, lookback_days):
            return _daily(spy)

    monkeypatch.setattr(N, "get_price_provider", lambda: Prov())
    assert N.beta_vs_spy("NVDA") is None  # 19 overlapping returns < 30


def test_beta_vs_spy_is_the_slope_of_the_symbols_returns_on_spys(monkeypatch) -> None:
    import numpy as np

    rng = np.random.default_rng(7)
    spy_ret = rng.normal(0.0004, 0.01, 80)
    spy = list(100.0 * np.cumprod(1 + spy_ret))
    stock = list(50.0 * np.cumprod(1 + 2.0 * spy_ret))  # exactly twice SPY's daily returns
    frames = {"SPY": _daily(spy), "NVDA": _daily(stock)}

    class Prov:
        def get_ohlcv(self, symbol, lookback_days):
            return frames[symbol]

    monkeypatch.setattr(N, "get_price_provider", lambda: Prov())
    beta = N.beta_vs_spy("NVDA", sessions=60)
    assert beta == pytest.approx(2.0, abs=0.05)
    assert N.beta_vs_spy("SPY") == pytest.approx(1.0, abs=1e-6)


def test_beta_vs_spy_is_none_when_the_provider_fails(monkeypatch) -> None:
    class Prov:
        def get_ohlcv(self, symbol, lookback_days):
            raise RuntimeError("down")

    monkeypatch.setattr(N, "get_price_provider", lambda: Prov())
    assert N.beta_vs_spy("NVDA") is None


# --- the post -----------------------------------------------------------------------------


def test_late_post_copy_is_exact() -> None:
    from src.news.render import late_post_line

    assert late_post_line(-1.4) == (
        "Dismissed earlier; the market moved -1.4% after it. Cause not confirmed."
    )
    assert late_post_line(2.04) == (
        "Dismissed earlier; the market moved +2.0% after it. Cause not confirmed."
    )


def _late_candidate(*, basis: str = "index", symbol: str = "QQQ", move: float = -1.8, cid: int = 1):
    from src.news.triggers import AlertCandidate

    return AlertCandidate(
        kind="late_promotion",
        subject=symbol if basis == "ticker" else f"cluster:{cid}",
        critical=False,
        symbols=[symbol],
        cluster_ids=[cid],
        detail={"move_pct": move, "basis": basis, "headline": f"headline {cid}"},
    )


def _ctx():
    from src.news.alerts import AlertContext
    from src.news.facts import Analytics
    from src.news.playbook import load_playbook

    return AlertContext(
        cfg=get_config(),
        an=Analytics.live(),
        pb=load_playbook(),
        now=NOW,
        today=NOW.date(),
        positions=[],
        held=set(),
        universe=set(),
        backdrop=None,
        tape={},
    )


def test_the_late_card_carries_the_exact_copy_and_the_story(news_db) -> None:
    from src.news.alerts import build_card
    from src.news.render import render_card

    _seed(1)
    with news_session() as s:
        s.add(
            NewsItemRow(
                url_hash="u1",
                title_hash="t1",
                title="Fed minutes show split",
                url="https://www.reuters.com/x",
                source="Reuters",
                source_domain="reuters.com",
                category="macro",
                origin="rss",
                fetched_at=naive_utc(NOW - timedelta(minutes=75)),
                tickers=[],
                tags=[],
                cluster_id=1,
            )
        )
    payload = build_card(_late_candidate(), _ctx())
    assert payload.kind == "late_promotion" and payload.critical is False
    assert payload.title == "headline 1" and payload.cluster_ids == [1]
    assert payload.headline_line == (
        "Dismissed earlier; the market moved -1.8% after it. Cause not confirmed."
    )
    assert payload.facts_line is not None and "QQQ -1.8%" in payload.facts_line
    text = render_card(payload).text
    assert "Dismissed earlier; the market moved -1.8% after it. Cause not confirmed." in text
    assert "Reuters" in text  # a link back to the story


def test_a_ticker_late_card_says_the_move_is_net_of_beta(news_db) -> None:
    from src.news.alerts import build_card

    _seed(1, category="ticker", tickers=("NVDA",))
    payload = build_card(_late_candidate(basis="ticker", symbol="NVDA", move=-3.5), _ctx())
    assert payload.subject == "NVDA"
    assert payload.facts_line is not None and "NVDA -3.5%" in payload.facts_line
    assert "net of" in payload.facts_line


def test_late_promotions_count_against_the_hourly_cap(news_db, monkeypatch) -> None:
    from src.news.triggers import AlertGate

    monkeypatch.setattr(get_config().news.alerts, "max_per_hour", 1)
    with news_session() as s:
        s.add(
            NewsPostRow(
                kind="late_promotion",
                subject="cluster:9",
                posted_at=naive_utc(NOW - timedelta(minutes=10)),
                payload={},
                cluster_ids=[9],
                silent=False,
                critical=False,
                edits=0,
                stage="facts",
            )
        )
    gate = AlertGate(get_config().news.alerts)
    assert gate.hourly_noncritical(NOW) == 1
    assert (
        gate.admit(_late_candidate(cid=2), now=NOW, day=NOW.date()) is False
    )  # held for the digest


def test_a_held_back_late_promotion_reads_properly_in_the_digest() -> None:
    from src.news.triggers import held_text

    text = held_text(_late_candidate(move=-1.8))
    assert text == "Dismissed earlier, then the market moved -1.8%: headline 1"


def test_a_late_promotion_is_not_explained_afterwards(news_db) -> None:
    from src.news import followup as FU

    with news_session() as s:
        s.add(
            NewsPostRow(
                kind="late_promotion",
                posted_at=naive_utc(NOW - timedelta(minutes=1)),
                payload={
                    "kind": "late_promotion",
                    "title": "t",
                    "emoji": "x",
                    "when": NOW.isoformat(),
                },
                cluster_ids=[1],
                silent=False,
                critical=False,
                edits=0,
                stage="facts",
            )
        )
    assert FU.pending_posts(NOW) == []  # the card is deterministic: no writer pass


# --- the loop -----------------------------------------------------------------------------


async def test_the_loop_posts_each_promotion_through_the_alert_path(news_db, monkeypatch) -> None:
    from src.news import service as S

    svc = S.NewsService(get_config())
    svc.publisher = None
    monkeypatch.setattr(S, "is_rth", lambda now: True)
    monkeypatch.setattr(
        S,
        "find_promotions",
        lambda now, *, bars_for, beta_for: [
            N.Promotion(cluster_id=1, move_pct=-1.8, basis="index", symbol="QQQ"),
            N.Promotion(cluster_id=2, move_pct=-3.5, basis="ticker", symbol="NVDA"),
        ],
    )
    _seed(1)
    _seed(2, category="ticker", tickers=("NVDA",))
    sent: list = []

    async def fake_dispatch(cands, now, *, tape_now=None):
        sent.extend(cands)
        return [1]

    monkeypatch.setattr(svc, "_dispatch", fake_dispatch)
    await svc._noise_check(NOW)
    assert [(c.kind, c.subject, c.critical, c.symbols, c.cluster_ids) for c in sent] == [
        ("late_promotion", "cluster:1", False, ["QQQ"], [1]),
        ("late_promotion", "NVDA", False, ["NVDA"], [2]),
    ]
    assert sent[0].detail["move_pct"] == -1.8 and sent[0].detail["basis"] == "index"
    assert sent[0].detail["headline"] == "headline 1"


async def _run_loop_with(monkeypatch, promos):
    from src.news import service as S

    svc = S.NewsService(get_config())
    svc.publisher = None
    monkeypatch.setattr(S, "is_rth", lambda now: True)
    monkeypatch.setattr(S, "find_promotions", lambda now, *, bars_for, beta_for: list(promos))
    monkeypatch.setattr(svc, "_alert_ctx", lambda now, tape_now=None: _ctx())
    await svc._noise_check(NOW)
    return svc


async def test_a_promotion_is_stored_as_a_late_post_once(news_db, monkeypatch) -> None:
    _seed(1)
    promo = N.Promotion(cluster_id=1, move_pct=-1.8, basis="index", symbol="QQQ")
    await _run_loop_with(monkeypatch, [promo])
    await _run_loop_with(monkeypatch, [promo])  # the same promotion again: once a day per subject
    with news_session() as s:
        posts = list(s.scalars(select(NewsPostRow)))
    assert [(p.kind, p.subject, p.critical, p.cluster_ids, p.stage) for p in posts] == [
        ("late_promotion", "cluster:1", False, [1], "facts")
    ]
    assert posts[0].payload["headline_line"] == (
        "Dismissed earlier; the market moved -1.8% after it. Cause not confirmed."
    )


async def test_a_promotion_the_hourly_cap_holds_back_rolls_into_the_digest(
    news_db, monkeypatch
) -> None:
    from src.news.store.state import held_alerts

    monkeypatch.setattr(get_config().news.alerts, "max_per_hour", 0)
    _seed(1)
    await _run_loop_with(monkeypatch, [N.Promotion(1, -1.8, "index", "QQQ")])
    with news_session() as s:
        assert s.scalar(select(NewsPostRow)) is None  # nothing posted now
    assert [text for _key, _at, text in held_alerts()] == [
        "Dismissed earlier, then the market moved -1.8%: headline 1"
    ]


async def test_the_loop_only_runs_in_the_regular_session_and_when_enabled(
    news_db, monkeypatch
) -> None:
    from src.news import service as S

    svc = S.NewsService(get_config())
    calls: list[datetime] = []
    monkeypatch.setattr(
        S, "find_promotions", lambda now, *, bars_for, beta_for: calls.append(now) or []
    )
    monkeypatch.setattr(S, "is_rth", lambda now: False)
    await svc._noise_check(NOW)
    assert calls == []
    monkeypatch.setattr(S, "is_rth", lambda now: True)
    await svc._noise_check(NOW)
    assert calls == [NOW]
    monkeypatch.setattr(svc.ncfg.triage, "enabled", False)
    await svc._noise_check(NOW)
    assert calls == [NOW]


def test_the_noise_check_loop_is_registered() -> None:
    from src.news import service as S

    loops = {n: i for n, i, _f in S.NewsService(get_config()).loops()}
    assert loops["noise_check"] == 300
