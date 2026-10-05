"""GET /ledger/* — thin renderers over src/reporting/trade_ledger.py (spec §6.1)."""

from __future__ import annotations

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
