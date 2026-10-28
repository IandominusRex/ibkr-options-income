"""GET /ledger/* — thin renderers over src/reporting/trade_ledger.py (spec §6.1)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from tests.conftest import OWNER

FIXTURE = Path(__file__).parent / "fixtures" / "ledger" / "activity_statement_sample.csv"


@pytest.fixture()
def seeded(client, api_db):
    from src.ledger.activity_csv import parse_activity_csv
    from src.ledger.ingest import ingest

    ingest(parse_activity_csv(FIXTURE.read_text()), source="csv", filename="sample.csv")
    return client


def test_requires_owner(client) -> None:
    assert client.get("/ledger/summary").status_code == 401


def test_empty_ledger_is_empty_not_an_error(client) -> None:
    body = client.get("/ledger/summary", headers=OWNER).json()
    assert body["summary"]["n_trades"] == 0
    assert body["summary"]["contributed_usd"] is None
    assert client.get("/ledger/trades", headers=OWNER).json()["trades"] == []


def test_trades_and_sheet_percentage(seeded) -> None:
    body = seeded.get("/ledger/trades", headers=OWNER).json()
    assert body["n"] == 6  # NVDA, AMZN 207.5P, AMZN 215P, AMZN 235C, OPEN 3C, OPEN1 5C
    nvda = next(t for t in body["trades"] if t["underlying"] == "NVDA")
    assert round(nvda["pct_profit"], 2) == 34.65


def test_trade_filters(seeded) -> None:
    amzn = seeded.get("/ledger/trades?symbol=AMZN", headers=OWNER).json()
    assert amzn["n"] == 3 and amzn["filters"]["symbol"] == "AMZN"
    assert seeded.get("/ledger/trades?outcome=Expired", headers=OWNER).json()["n"] == 1
    # AMZN 235C, OPEN 3C, OPEN1 5C.
    calls = seeded.get("/ledger/trades?right=C", headers=OWNER).json()
    assert calls["n"] == 3 and all(t["right"] == "C" for t in calls["trades"])
    assert seeded.get("/ledger/trades?right=X", headers=OWNER).status_code == 422
    assert seeded.get("/ledger/trades?outcome=bogus", headers=OWNER).status_code == 422
    assert seeded.get("/ledger/trades?sort=bogus", headers=OWNER).status_code == 422


def test_ticker_detail_and_404(seeded) -> None:
    d = seeded.get("/ledger/tickers/amzn", headers=OWNER).json()["detail"]
    assert d["ticker"]["symbol"] == "AMZN" and len(d["disposals"]) == 1
    assert seeded.get("/ledger/tickers/ZZZZ", headers=OWNER).status_code == 404


def test_trade_detail_shows_its_executions(seeded) -> None:
    key = seeded.get("/ledger/trades?symbol=NVDA", headers=OWNER).json()["trades"][0]["order_key"]
    body = seeded.get(f"/ledger/trades/{key}", headers=OWNER).json()
    assert len(body["executions"]) == 2
    assert seeded.get("/ledger/trades/0000000000000000", headers=OWNER).status_code == 404


def test_csv_export_uses_the_sheet_header(seeded) -> None:
    r = seeded.get("/ledger/trades.csv?symbol=NVDA", headers=OWNER)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    lines = r.text.strip().splitlines()
    assert lines[0].startswith("Sell/Buy,Put/Call,Order Date,Expiration Date,Ticker")
    assert len(lines) == 2


def test_imports_lists_runs_and_feed_status(seeded) -> None:
    body = seeded.get("/ledger/imports", headers=OWNER).json()
    assert body["runs"][0]["filename"] == "sample.csv" and body["runs"][0]["status"] == "ok"
    assert isinstance(body["flex"]["configured"], bool)
    assert len(body["corporate_actions"]) == 1 and body["corporate_actions"][0]["reviewed"] is False


def test_annotation_goes_through_post_commands(seeded) -> None:
    key = seeded.get("/ledger/trades?symbol=NVDA", headers=OWNER).json()["trades"][0]["order_key"]
    r = seeded.post(
        "/commands",
        headers=OWNER,
        json={"kind": "ledger_annotate", "payload": {"order_key": key, "notes": "x"}},
    )
    assert r.status_code in (200, 201, 202)
    assert r.json()["status"] == "pending"


def test_nav_has_a_ledger_section(client) -> None:
    sections = {s["key"]: s for s in client.get("/nav", headers=OWNER).json()["sections"]}
    assert sections["ledger"]["available"] is True


NOW = datetime(2026, 10, 22, 15, 0, tzinfo=UTC)


def _exec(n: int, **over):
    from src.storage.models import BrokerExecutionRow

    base = dict(
        dedupe_key=f"live-{n}",
        source_kind="exec",
        source="live",
        exec_id=f"0000{n}",
        perm_id=900 + n,
        ib_order_id=10 + n,
        account="DU1",
        trade_time=datetime(2026, 10, 20, 14, 31, 7),
        trade_date=date(2026, 10, 20),
        contract_ident="NVDA 20261120 165 P",
        underlying="NVDA",
        sec_type="OPT",
        right="P",
        strike=165.0,
        expiry=date(2026, 11, 20),
        multiplier=100.0,
        currency="USD",
        quantity=-1.0,
        price=2.35,
        proceeds=235.0,
        commission=-1.3,
        codes="O",
        book="system",
    )
    base.update(over)
    return BrokerExecutionRow(**base)


@pytest.fixture()
def frozen_ledger_now(monkeypatch):
    import src.api.routers.ledger as routes

    monkeypatch.setattr(routes, "_now", lambda: NOW)


def test_executions_require_owner(client) -> None:
    assert client.get("/ledger/executions").status_code == 401


def test_executions_list_real_fills_newest_first_with_their_contract(
    client, api_db, frozen_ledger_now
) -> None:
    with api_db() as s:
        s.add_all(
            [
                _exec(1, trade_time=datetime(2026, 10, 19, 14, 0), trade_date=date(2026, 10, 19)),
                _exec(2, quantity=1.0, price=1.1, proceeds=-110.0, codes="C"),
            ]
        )
    body = client.get("/ledger/executions", headers=OWNER).json()
    assert [e["exec_id"] for e in body["executions"]] == ["00002", "00001"]
    first = body["executions"][0]
    assert (first["underlying"], first["right"], first["strike"], first["expiry"]) == (
        "NVDA",
        "P",
        165.0,
        "2026-11-20",
    )
    assert (first["quantity"], first["price"], first["commission"], first["book"]) == (
        1.0,
        1.1,
        -1.3,
        "system",
    )
    assert first["trade_time"].endswith(("Z", "+00:00"))
    assert (body["days"], body["limit"], body["truncated"]) == (30, 200, False)


def test_executions_leave_out_statement_rows_superseded_twins_and_old_days(
    client, api_db, frozen_ledger_now
) -> None:
    with api_db() as s:
        s.add_all(
            [
                _exec(1),
                _exec(2, source_kind="order"),
                _exec(3, superseded_by=1),
                _exec(4, trade_date=date(2026, 8, 1), trade_time=datetime(2026, 8, 1, 14, 0)),
            ]
        )
    ids = [
        e["exec_id"] for e in client.get("/ledger/executions", headers=OWNER).json()["executions"]
    ]
    assert ids == ["00001"]
    wide = client.get("/ledger/executions?days=120", headers=OWNER).json()["executions"]
    assert {e["exec_id"] for e in wide} == {"00001", "00004"}


def test_executions_filter_by_book_and_symbol(client, api_db, frozen_ledger_now) -> None:
    with api_db() as s:
        s.add_all(
            [
                _exec(1),
                _exec(2, book="spreads", underlying="SPY", contract_ident="SPY 20261022 763 P"),
                _exec(3, book="manual", underlying="AAPL", contract_ident="AAPL 20261120 185 P"),
            ]
        )
    spreads = client.get("/ledger/executions?book=spreads", headers=OWNER).json()["executions"]
    assert [e["underlying"] for e in spreads] == ["SPY"]
    aapl = client.get("/ledger/executions?symbol=aapl", headers=OWNER).json()["executions"]
    assert [e["book"] for e in aapl] == ["manual"]
    assert client.get("/ledger/executions?book=bogus", headers=OWNER).status_code == 422


def test_executions_say_when_the_list_was_cut_short(client, api_db, frozen_ledger_now) -> None:
    with api_db() as s:
        s.add_all([_exec(n) for n in range(1, 5)])
    body = client.get("/ledger/executions?limit=3", headers=OWNER).json()
    assert len(body["executions"]) == 3 and body["truncated"] is True
    assert client.get("/ledger/executions?limit=0", headers=OWNER).status_code == 422
    assert client.get("/ledger/executions?days=366", headers=OWNER).status_code == 422
