"""Task 5.3 — `GET /pnl/ledger.csv`.

The same rows `/pnl/ledger` returns, under the same filters, as CSV — built
from the same `build_legs` call, so the two cannot drift. `None` serialises
as an empty cell, never `0` (a spreadsheet zero is harder to spot than a page
zero), and the header row names the units (`credit_usd`, not `credit`).
"""

from __future__ import annotations

import csv
import io

import pytest

from tests.conftest import OWNER


@pytest.fixture()
def db(api_db):
    """Local override for these route tests: the storage engine bound to the
    API client's file, so seeds cross the boundary the routes read. M4's
    builder tests keep the private-t.db `db` in tests/conftest.py."""
    return api_db


def test_an_open_legs_net_pnl_cell_is_empty_not_zero(client, seed_leg) -> None:
    """A zero in a spreadsheet is harder to spot than a zero on a page."""
    seed_leg(candidate_id="c1", sold=(1, 1.50), expiry_in_days=30)
    rows = list(csv.DictReader(io.StringIO(client.get("/pnl/ledger.csv", headers=OWNER).text)))
    assert rows[0]["net_pnl_usd"] == ""


def test_the_csv_row_count_matches_the_json_route(client, seed_wheel) -> None:
    seed_wheel()
    n_legs = client.get("/pnl/ledger", headers=OWNER).json()["n_legs"]
    rows = list(csv.DictReader(io.StringIO(client.get("/pnl/ledger.csv", headers=OWNER).text)))
    assert len(rows) == n_legs


def test_the_header_row_names_the_units(client, seed_leg) -> None:
    seed_leg(candidate_id="c1", sold=(1, 1.50), expiry_in_days=30)
    reader = csv.DictReader(io.StringIO(client.get("/pnl/ledger.csv", headers=OWNER).text))
    for name in ("credit_usd", "debit_usd", "net_pnl_usd", "roc_pct", "days_held"):
        assert name in (reader.fieldnames or []), f"{name} missing from the CSV header"


def test_content_disposition_is_present_with_a_dated_filename(client) -> None:
    r = client.get("/pnl/ledger.csv", headers=OWNER)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    disposition = r.headers["content-disposition"]
    assert 'attachment; filename="pnl-ledger-' in disposition
    assert disposition.endswith('.csv"')
    assert "20" in disposition  # a dated name: pnl-ledger-YYYY-MM-DD.csv


def test_the_book_column_distinguishes_paper_from_live_rows(client, seed_leg) -> None:
    seed_leg(candidate_id="p1", sold=(1, 1.0), is_live=False, expiry_in_days=-1)
    seed_leg(candidate_id="l1", sold=(1, 3.0), is_live=True, expiry_in_days=-1)

    rows = list(csv.DictReader(io.StringIO(client.get("/pnl/ledger.csv", headers=OWNER).text)))
    books = {row["candidate_id"]: row["book"] for row in rows}
    assert books["p1"] == "paper"
    assert books["l1"] == "live"


def test_there_is_no_mixed_book_refusal_on_the_csv(client, seed_leg) -> None:
    """A CSV has no headline total to be wrong; both books export together."""
    seed_leg(candidate_id="p1", sold=(1, 1.0), is_live=False, expiry_in_days=-1)
    seed_leg(candidate_id="l1", sold=(1, 3.0), is_live=True, expiry_in_days=-1)

    r = client.get("/pnl/ledger.csv?book=all", headers=OWNER)
    assert r.status_code == 200
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert len(rows) == 2


def test_the_csv_respects_the_same_filters_as_the_json_route(client, seed_wheel) -> None:
    seed_wheel()
    rows = list(
        csv.DictReader(io.StringIO(client.get("/pnl/ledger.csv?symbol=NVDA", headers=OWNER).text))
    )
    assert all(row["underlying"] == "NVDA" for row in rows)
    json_n = client.get("/pnl/ledger?symbol=NVDA", headers=OWNER).json()["n_legs"]
    assert len(rows) == json_n


def test_a_non_owner_is_refused(client, monkeypatch) -> None:
    from src.api.auth import Role, User

    viewer = User(id="viewer", role=Role.VIEWER)
    monkeypatch.setattr("src.api.deps.authenticate", lambda token: viewer if token else None)
    assert client.get("/pnl/ledger.csv", headers=OWNER).status_code == 403
