from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from tests.conftest import OWNER

NOW = datetime.now(UTC)


@pytest.fixture()
def news_client(client, news_db, monkeypatch):
    import src.api.news_db as nd

    nd.reset_engine()
    monkeypatch.setattr(nd, "_resolve_path", lambda: str(news_db))
    yield client
    nd.reset_engine()


def _post(kind="ticker_move", subject="NVDA", chart_path=None, **payload):
    from src.news.schemas import CardPayload
    from src.news.store.models import NewsPostRow
    from src.news.store.queries import naive_utc
    from src.news.store.session import news_session

    p = CardPayload(
        kind=kind,
        subject=subject,
        title=payload.get("title", f"{subject} -6.2%"),
        emoji="📉",
        when=NOW,
    )
    with news_session() as s:
        row = NewsPostRow(
            kind=kind,
            subject=subject,
            posted_at=naive_utc(NOW),
            payload=p.model_dump(mode="json"),
            cluster_ids=[],
            silent=False,
            critical=False,
            edits=0,
            stage="explained",
            chart_path=chart_path,
        )
        s.add(row)
        s.flush()
        return row.id


def test_requires_owner(news_client) -> None:
    assert news_client.get("/news/feed").status_code == 401


def test_feed_filters_and_paginates(news_client) -> None:
    a = _post()
    _post(kind="earnings", subject="AAPL")
    _post(kind="digest_close", subject=None, title="Close recap")
    body = news_client.get("/news/feed", headers=OWNER).json()
    assert body["available"] is True and len(body["posts"]) == 3
    assert [
        p["kind"]
        for p in news_client.get("/news/feed?group=earnings", headers=OWNER).json()["posts"]
    ] == ["earnings"]
    assert [
        p["subject"]
        for p in news_client.get("/news/feed?symbol=nvda", headers=OWNER).json()["posts"]
    ] == ["NVDA"]
    older = news_client.get(f"/news/feed?before={a + 1}", headers=OWNER).json()["posts"]
    assert all(p["id"] <= a for p in older)
    assert news_client.get("/news/feed?group=bogus", headers=OWNER).status_code == 422


def test_post_detail_inlines_chart(news_client, tmp_path, monkeypatch) -> None:
    from src.common.config import get_config

    charts = tmp_path / "charts"
    charts.mkdir()
    (charts / "1.png").write_bytes(b"\x89PNG\r\n")
    monkeypatch.setattr(get_config().news, "charts_dir", str(charts))
    pid = _post(chart_path=str(charts / "1.png"))
    body = news_client.get(f"/news/posts/{pid}", headers=OWNER).json()
    assert body["post"]["payload"]["title"] == "NVDA -6.2%"
    assert body["chart_data_uri"].startswith("data:image/png;base64,")
    assert news_client.get("/news/posts/999", headers=OWNER).status_code == 404


def test_chart_outside_charts_dir_is_refused(news_client, tmp_path, monkeypatch) -> None:
    from src.common.config import get_config

    monkeypatch.setattr(get_config().news, "charts_dir", str(tmp_path / "charts"))
    evil = tmp_path / "secret.png"
    evil.write_bytes(b"x")
    pid = _post(chart_path=str(evil))
    assert news_client.get(f"/news/posts/{pid}", headers=OWNER).json()["chart_data_uri"] is None


def test_ticker_and_status(news_client) -> None:
    from src.news.briefs import enqueue_brief
    from src.news.store.state import set_state

    _post(kind="brief", subject="TSM", title="TSM brief")
    enqueue_brief("TSM", "web")
    set_state("heartbeat", NOW.isoformat())
    t = news_client.get("/news/ticker/tsm", headers=OWNER).json()
    assert (
        t["latest_brief"]["payload"]["title"] == "TSM brief" and t["request"]["status"] == "pending"
    )
    st = news_client.get("/news/status", headers=OWNER).json()
    assert st["available"] and st["heartbeat_age_s"] is not None and st["llm_cap"] == 40


def test_news_routes_when_db_missing(client, tmp_path, monkeypatch) -> None:
    import src.api.news_db as nd

    nd.reset_engine()
    monkeypatch.setattr(nd, "_resolve_path", lambda: str(tmp_path / "absent.db"))
    for path in ("/news/feed", "/news/calendar", "/news/ticker/NVDA", "/news/status"):
        r = client.get(path, headers=OWNER)
        assert r.status_code == 200 and r.json()["available"] is False, path


def test_calendar_lists_the_window_and_flags_held_names(
    news_client, seed_portfolio_snapshot
) -> None:
    from datetime import date

    from src.news.store.models import EarningsEventRow, EconEventRow
    from src.news.store.queries import naive_utc
    from src.news.store.session import news_session

    seed_portfolio_snapshot(
        positions=[
            {"symbol": "NVDA", "sec_type": "STK", "position": 100.0, "avg_cost": 120.0},
            {
                "symbol": "AAPL  261120P00200000",
                "sec_type": "OPT",
                "position": -1.0,
                "avg_cost": 2.0,
                "right": "P",
                "strike": 200.0,
                "expiry": "2026-11-20",
                "underlying": "AAPL",
            },
        ]
    )
    today = NOW.astimezone(__import__("zoneinfo").ZoneInfo("America/New_York")).date()
    with news_session() as s:
        for key, when in (
            ("cpi", NOW + timedelta(days=1)),
            ("old", NOW - timedelta(days=2)),
            ("far", NOW + timedelta(days=30)),
        ):
            s.add(
                EconEventRow(
                    event_key=key,
                    title=key.upper(),
                    scheduled_at=naive_utc(when),
                    impact="high",
                    alerted=False,
                )
            )
        for sym, d in (
            ("NVDA", today + timedelta(days=2)),
            ("AAPL", today + timedelta(days=3)),
            ("TSM", today + timedelta(days=4)),
            ("MSFT", today + timedelta(days=40)),
        ):
            s.add(
                EarningsEventRow(
                    symbol=sym, report_date=d, timing="amc", status="scheduled", alerted=False
                )
            )
    body = news_client.get("/news/calendar", headers=OWNER).json()
    assert body["available"] is True
    assert [e["title"] for e in body["econ"]] == ["CPI"]
    assert {e["symbol"]: e["held"] for e in body["earnings"]} == {
        "NVDA": True,
        "AAPL": True,
        "TSM": False,
    }
    assert isinstance(date.fromisoformat(body["earnings"][0]["report_date"]), date)


def test_status_survives_corrupt_state_and_shows_breakers(news_client) -> None:
    """Only the news service writes news_state, but a hand-edited or truncated value must
    read as missing, never a 500."""
    from src.news.store.state import set_state

    set_state("heartbeat", "not-a-time")
    set_state("source_ok:rss", "garbage")
    set_state("source_ok:macro", NOW.isoformat())
    set_state("breakers", '{"finnhub": "open"}')
    set_state(f"llm_calls:{NOW.date().isoformat()}", "x")
    r = news_client.get("/news/status", headers=OWNER)
    assert r.status_code == 200
    st = r.json()
    assert st["heartbeat_at"] is None and st["heartbeat_age_s"] is None
    assert list(st["sources_ok"]) == ["macro"]
    assert st["breakers"] == {"finnhub": "open"}
    set_state("breakers", "[not json")
    assert news_client.get("/news/status", headers=OWNER).json()["breakers"] == {}
