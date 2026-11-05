"""GET /value/top, /value/book, /value/positions and /value/{symbol}: read-only, through
src/api/value_db.py (Part 6, Task 13).

The API may not import ``src.value`` beyond the scorecard's shapes; the tests may, to build a real
value.db with the store's own ORM (test files are not fenced).
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import pytest

from src.common.value_commands import proposal_fingerprint
from src.common.value_types import Classification
from src.value.schemas import Check, Fingerprint, ListEvaluation, MethodValue, ValueScorecard
from src.value.store import (
    ValueBookStateRow,
    ValueClaudeFactRow,
    ValueClaudeNoteRow,
    ValueClaudeVerdictRow,
    ValueEffectiveRow,
    ValueKillTriggerRow,
    ValueOrderRow,
    ValuePositionRow,
    ValueProposalRow,
    ValueTickerFileRow,
    value_session,
)
from tests.conftest import OWNER

NOW = datetime(2026, 11, 2, 15, 0)  # naive UTC
TODAY = date(2026, 11, 2)


@pytest.fixture()
def vdb_file(value_book_db, monkeypatch):
    """value.db in tmp (the store's schema), with the API's read-only module pointed at it."""
    import src.api.value_db as vdb

    monkeypatch.setattr(vdb, "_resolve_path", lambda: str(value_book_db))
    vdb.reset_engine()
    yield value_book_db
    vdb.reset_engine()


@pytest.fixture()
def no_vdb_file(tmp_path, monkeypatch):
    import src.api.value_db as vdb

    monkeypatch.setattr(vdb, "_resolve_path", lambda: str(tmp_path / "missing" / "value.db"))
    vdb.reset_engine()
    yield
    vdb.reset_engine()


def _card(symbol: str, *, fair: float = 140.0, price: float = 98.0) -> ValueScorecard:
    ev = ListEvaluation(
        list_name="deep_value",
        entry="pass",
        methods=[
            MethodValue(method="A", value=130.0, state="ok"),
            MethodValue(method="B", value=140.0, state="ok"),
            MethodValue(method="C", value=150.0, state="ok"),
        ],
        fair_value=fair,
        required_mos_pct=30.0,
        margin_of_safety=(fair - price) / fair,
        entry_ceiling=fair * 0.7,
        timing="pass",
        timing_checks=[Check(id="timing.rsi", state="pass", actual=41.0, threshold=70.0)],
        verdict="READY",
        reasons=["healthy, cheap enough, timing passes", "second", "third", "fourth"],
    )
    return ValueScorecard(
        symbol=symbol,
        as_of=TODAY,
        ruleset_version="v4",
        ruleset_hash="be30d1eaa915",
        company_class="operating",
        classification=Classification(),
        data_quality="pass",
        data_quality_checks=[Check(id="dq.shares", state="pass", actual=1.0, threshold=2.0)],
        health="pass",
        health_checks=[Check(id="health.altman", state="pass", actual=4.2, threshold=1.8)],
        price=price,
        lists={"deep_value": ev},
        fingerprint=Fingerprint(ruleset_version="v4", ruleset_hash="be30d1eaa915"),
    )


def _seed_file(
    symbol: str,
    verdict: str = "READY",
    *,
    rank: float | None = 50.0,
    by: str = "python",
    universe: str = "trading",
    ceiling: float | None = 98.0,
) -> None:
    card = _card(symbol)
    with value_session() as s:
        s.add(
            ValueTickerFileRow(
                symbol=symbol,
                computed_at=NOW,
                as_of=TODAY,
                universe=universe,
                fingerprint_key="k" * 16,
                fingerprint_json="{}",
                ruleset_version="v4",
                ruleset_hash="be30d1eaa915",
                company_class="operating",
                data_quality="pass",
                health="pass",
                verdict_deep=verdict,
                verdict_growth="NO",
                fair_value_deep=140.0,
                mos_deep=0.3,
                rank_deep=rank,
                price=98.0,
                summary_json="{}",
                scorecard_json=card.model_dump_json(),
            )
        )
        s.add(
            ValueEffectiveRow(
                symbol=symbol,
                list_name="deep_value",
                as_of=TODAY,
                verdict=verdict,
                decided_by=by,
                python_verdict=verdict,
                fair_value=140.0,
                entry_ceiling=ceiling,
                margin_of_safety=0.3,
                updated_at=NOW,
            )
        )


def test_top_orders_ready_then_watch_then_wait_by_rank(client, vdb_file) -> None:
    _seed_file("WAITER", "WAIT", rank=99.0)
    _seed_file("WATCHER", "WATCH", rank=90.0)
    _seed_file("LOW", "READY", rank=10.0)
    _seed_file("HIGH", "READY", rank=70.0, by="claude")
    _seed_file("EVID", "READY", rank=95.0, universe="evidence")
    body = client.get("/value/top?list=deep_value", headers=OWNER).json()
    assert body["available"] is True and body["list_name"] == "deep_value"
    assert [i["symbol"] for i in body["items"]] == ["HIGH", "LOW", "WATCHER", "WAITER"]
    top = body["items"][0]
    assert top["decided_by"] == "claude" and top["verdict"] == "READY"
    assert top["fair_value"] == 140.0 and top["half_sell"] == 140.0
    assert top["stop"] is None  # the live policy sets no stop before the half sale: n/a
    assert top["put_ceiling"] == 98.0 and top["reasons"] == [
        "healthy, cheap enough, timing passes",
        "second",
        "third",
    ]
    assert client.get("/value/top?list=quality_growth", headers=OWNER).json()["items"] == []


def test_book_carries_the_proposal_fingerprint_and_the_state(client, vdb_file, monkeypatch) -> None:
    import src.api.routers.value as router

    monkeypatch.setattr(router, "_now", lambda: NOW.replace(tzinfo=UTC) + timedelta(hours=1))
    created = NOW - timedelta(hours=1)
    with value_session() as s:
        s.add(
            ValueProposalRow(
                id=7,
                kind="buy",
                symbol="GOOGL",
                list_name="deep_value",
                shares=10,
                price=98.0,
                cost_usd=980.0,
                reason="tranche 1",
                status="pending",
                created_at=created,
                expires_at=NOW + timedelta(hours=29),
            )
        )
        s.add(
            ValueProposalRow(
                id=8,
                kind="buy",
                symbol="DONE",
                list_name="deep_value",
                shares=1,
                reason="x",
                status="done",
                created_at=created,
                expires_at=NOW,
            )
        )
        s.add(
            ValueOrderRow(
                symbol="GOOGL",
                list_name="deep_value",
                side="buy",
                shares=10,
                filled=10,
                avg_price=100.0,
                status="filled",
                created_at=created,
            )
        )
        s.add(
            ValueBookStateRow(
                key="snapshot", value=json.dumps({"net_liq": 100000.0}), updated_at=NOW
            )
        )
        s.add(
            ValueBookStateRow(
                key="high_water",
                value=json.dumps(
                    {
                        "high": 2000.0,
                        "value": 1400.0,
                        "stop": True,
                        "episode": "abc1234567",
                        "trim_offered_at": NOW.isoformat(),
                    }
                ),
                updated_at=NOW,
            )
        )
        s.add(ValueBookStateRow(key="trend", value=json.dumps({"brake": True}), updated_at=NOW))
    body = client.get("/value/book", headers=OWNER).json()
    assert body["available"] is True and body["enabled"] is False
    assert body["release_max_closes"] == 3
    assert [p["id"] for p in body["proposals"]] == [7]  # a done proposal is not open
    assert body["proposals"][0]["fingerprint"] == proposal_fingerprint(
        7, "buy", "GOOGL", 10, created
    )
    assert body["proposals"][0]["needs_tap"] is True
    assert body["used_usd"] == 1000.0
    assert body["ceiling_usd"] == 100000.0 * 0.30 * 0.50  # the trend brake halves the ceiling
    b = body["breakers"]
    assert b["trend"] is True and b["drawdown"] is True and b["trim_offered"] is True
    assert b["trim_episode"] == "abc1234567" and b["drawdown_pct"] == pytest.approx(30.0)


def test_home_does_not_say_trim_offered_over_a_stale_card(client, vdb_file, monkeypatch) -> None:
    import src.api.routers.value as router

    with value_session() as s:
        s.add(
            ValueBookStateRow(
                key="high_water",
                value=json.dumps(
                    {
                        "high": 2000.0,
                        "value": 1400.0,
                        "stop": True,
                        "episode": "abc1234567",
                        "trim_offered_at": NOW.isoformat(),
                    }
                ),
                updated_at=NOW,
            )
        )
    for hours, offered in ((1, True), (40, False)):  # the card is good for 30 hours
        monkeypatch.setattr(
            router, "_now", lambda h=hours: NOW.replace(tzinfo=UTC) + timedelta(hours=h)
        )
        body = client.get("/value/book", headers=OWNER).json()
        assert body["breakers"]["trim_offered"] is offered


def _seed_position(symbol: str, *, status: str, sells: bool) -> None:
    with value_session() as s:
        s.add(
            ValuePositionRow(
                symbol=symbol,
                list_name="deep_value",
                status=status,
                opened_on=date(2026, 10, 20),
                closed_on=date(2026, 10, 30) if status == "closed" else None,
                plan_json=json.dumps(
                    {"effective_fair_value": 140.0, "fair_value": 135.0, "half_sold": False}
                ),
            )
        )
        s.add(
            ValueOrderRow(
                symbol=symbol,
                list_name="deep_value",
                side="buy",
                shares=10,
                filled=10,
                avg_price=100.0,
                status="filled",
                created_at=datetime(2026, 10, 20, 15, 0),
            )
        )
        if sells:
            s.add(
                ValueOrderRow(
                    symbol=symbol,
                    list_name="deep_value",
                    side="sell",
                    shares=10,
                    filled=10,
                    avg_price=112.0,
                    status="filled",
                    created_at=datetime(2026, 10, 30, 15, 0),
                )
            )


def test_positions_open_show_shares_cost_and_the_next_exit(client, vdb_file) -> None:
    _seed_position("OPEN", status="open", sells=False)
    _seed_position("SHUT", status="closed", sells=True)
    body = client.get("/value/positions?status=open", headers=OWNER).json()
    assert [p["symbol"] for p in body["positions"]] == ["OPEN"]
    p = body["positions"][0]
    assert p["shares"] == 10 and p["avg_cost"] == 100.0
    assert p["next_exit"] == {"kind": "sell_half", "level": 140.0}
    assert p["realised_usd"] is None  # nothing sold: unknown, never 0.0


def test_positions_closed_show_the_realised_dollars(client, vdb_file) -> None:
    _seed_position("OPEN", status="open", sells=False)
    _seed_position("SHUT", status="closed", sells=True)
    body = client.get("/value/positions?status=closed", headers=OWNER).json()
    assert [p["symbol"] for p in body["positions"]] == ["SHUT"]
    p = body["positions"][0]
    assert p["shares"] == 0 and p["realised_usd"] == pytest.approx(120.0)
    assert p["next_exit"] is None and p["closed_on"] == "2026-10-30"


def test_ticker_labels_claudes_block_and_keeps_python_fields_python(client, vdb_file) -> None:
    _seed_file("GOOGL")
    with value_session() as s:
        s.add(
            ValueClaudeVerdictRow(
                read_id=1,
                symbol="GOOGL",
                list_name="deep_value",
                verdict="READY",
                why="cheap on FCF",
                drivers_json=json.dumps({"growth": 0.10, "terminal": 0.03}),
                clamps_json=json.dumps(["growth 0.2000 -> 0.1000"]),
                fair_value=150.0,
                python_fair_value=140.0,
                clamp_bound=True,
                fingerprint_key="k" * 16,
                backend="cli",
                created_at=NOW,
            )
        )
        s.add(
            ValueClaudeNoteRow(
                read_id=1,
                symbol="GOOGL",
                thesis="Search cash machine.",
                bear_case="Antitrust.",
                backend="cli",
                created_at=NOW,
            )
        )
        s.add(
            ValueKillTriggerRow(
                read_id=1,
                symbol="GOOGL",
                kind="dilution_above",
                threshold=4.0,
                chosen_at=NOW,
                last_state="near",
                last_actual=3.0,
            )
        )
        s.add(
            ValueClaudeFactRow(
                read_id=1,
                symbol="GOOGL",
                accn="0001-26-000001",
                kind="buyback",
                value=70.0,
                unit="usd_bn",
                quote="repurchased $70 billion",
                grounded=True,
                created_at=NOW,
            )
        )
    body = client.get("/value/GOOGL", headers=OWNER).json()
    assert body["available"] is True and body["computed"] == "stored"
    f = body["file"]
    deep = f["lists"][0]
    assert deep["fair_value"] == 140.0 and deep["decided_by"] == "python"
    assert [m["median"] for m in deep["methods"]] == [False, True, False]
    assert {g["id"] for g in f["gates"]} == {"dq.shares", "health.altman"}
    c = body["claude"]
    assert c["source"] == "claude"
    cl = c["lists"][0]
    assert cl["fair_value"] == 150.0 and cl["cap_applied"] is True
    growth = next(d for d in cl["drivers"] if d["name"] == "growth")
    assert growth["chosen"] == 0.2 and growth["used"] == 0.1 and growth["bound"] == "hi"
    assert {n["kind"] for n in c["notes"]} == {"thesis", "bear_case"}
    trig = c["kill_triggers"][0]
    assert trig["name"] == "dilution_above" and trig["distance_pct"] == pytest.approx(25.0)
    assert c["facts"][0]["quote"] == "repurchased $70 billion"


def test_ticker_without_a_read_has_a_null_claude_block(client, vdb_file) -> None:
    _seed_file("GOOGL")
    body = client.get("/value/googl", headers=OWNER).json()
    assert body["claude"] is None and body["reevaluations"] == [] and body["plan"] is None
    assert body["file"]["symbol"] == "GOOGL" and body["age_days"] == body["age_days"]


@pytest.mark.parametrize("path", ["/value/top", "/value/book", "/value/positions", "/value/GOOGL"])
def test_a_missing_value_db_is_unavailable_not_an_error(client, no_vdb_file, path) -> None:
    r = client.get(path, headers=OWNER)
    assert r.status_code == 200
    assert r.json()["available"] is False


def test_an_unknown_symbol_is_404(client, vdb_file) -> None:
    _seed_file("GOOGL")
    assert client.get("/value/NOPE", headers=OWNER).status_code == 404


def test_book_says_whether_the_value_drain_is_checking(client, vdb_file, monkeypatch) -> None:
    """Web overhaul Part 4 (V2): the value process's drain heartbeat. Never run is false with a null
    time; within five minutes (the floor over twice the 15 s poll) is healthy; older is stale, and
    its time is still shown so the receipt can say when the process last checked."""
    import src.api.routers.value as router
    from src.common.value_commands import VALUE_DRAIN_HEARTBEAT_KEY
    from src.storage.system_settings import set_setting

    now = NOW.replace(tzinfo=UTC)
    monkeypatch.setattr(router, "_now", lambda: now)
    body = client.get("/value/book", headers=OWNER).json()
    assert body["drain_healthy"] is False and body["drain_last_seen"] is None
    set_setting(VALUE_DRAIN_HEARTBEAT_KEY, (now - timedelta(seconds=290)).isoformat())
    body = client.get("/value/book", headers=OWNER).json()
    assert body["drain_healthy"] is True
    set_setting(VALUE_DRAIN_HEARTBEAT_KEY, (now - timedelta(seconds=310)).isoformat())
    body = client.get("/value/book", headers=OWNER).json()
    assert body["drain_healthy"] is False
    assert body["drain_last_seen"].startswith("2026-11-02T14:54:50")


def test_a_missing_value_db_still_says_whether_the_drain_runs(
    client, no_vdb_file, monkeypatch
) -> None:
    """The heartbeat lives in the trading DB: a book with no value.db yet still reports it."""
    import src.api.routers.value as router
    from src.common.value_commands import VALUE_DRAIN_HEARTBEAT_KEY
    from src.storage.system_settings import set_setting

    now = NOW.replace(tzinfo=UTC)
    monkeypatch.setattr(router, "_now", lambda: now)
    set_setting(VALUE_DRAIN_HEARTBEAT_KEY, now.isoformat())
    body = client.get("/value/book", headers=OWNER).json()
    assert body["available"] is False and body["drain_healthy"] is True


def test_every_value_route_needs_the_owner_token(client, vdb_file) -> None:
    for path in ("/value/top", "/value/book", "/value/positions", "/value/GOOGL"):
        assert client.get(path).status_code == 401
        assert client.get(path, headers={"Authorization": "Bearer nope"}).status_code == 401


def test_a_re_entry_starts_the_average_cost_again(value_book_db) -> None:
    """Review I1: a sale's shares leave the running average, so a later buy is not blended with
    the cost of shares already sold (buy 100 @ 50, sell @ 60, buy 100 @ 100, sell @ 110)."""
    import src.api.value_db as vdb

    steps = [
        ("buy", 50.0, datetime(2026, 10, 1, 15, 0)),
        ("sell", 60.0, datetime(2026, 10, 5, 15, 0)),
        ("buy", 100.0, datetime(2026, 10, 10, 15, 0)),
        ("sell", 110.0, datetime(2026, 10, 15, 15, 0)),
    ]
    with value_session() as s:
        for side, price, at in steps:
            s.add(
                ValueOrderRow(
                    symbol="REEN",
                    list_name="deep_value",
                    side=side,
                    shares=100,
                    filled=100,
                    avg_price=price,
                    status="filled",
                    created_at=at,
                )
            )
    with value_session() as s:
        fills = vdb.read_fills(s)
    assert fills is not None
    assert [f["realised_usd"] for f in fills] == [None, 1000.0, None, 1000.0]
