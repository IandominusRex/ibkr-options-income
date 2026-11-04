"""GET /value/{symbol} on open (value book Part 6, Task 14, ruling 24): a stored file that is
current is served as stored; a stale or absent one is computed now from research.db (read-only)
with the pure scorecard, and a `value_snapshot` intent carries the input set to the value process.
The API never writes value.db."""

from __future__ import annotations

import json
import os
import time
from datetime import date, datetime

import pandas as pd
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import src.common.value_inputs as vi
from src.common.config import get_config
from src.common.value_freshness import freshness_key, rules_digest
from src.common.value_types import MarketFacts
from src.research.store.models import Base, CompanyFactsRawRow, DailyBarRow, FinancialRow, SymbolRow
from src.storage.db import session_scope
from src.storage.models import AppCommandRow
from src.value.ruleset import ruleset_hash
from src.value.store import ValueTickerFileRow, value_session
from src.value.ticker_file import freshness_json
from src.value.ticker_file import freshness_key as ticker_freshness_key
from tests.conftest import OWNER
from tests.test_api_value import _seed_file
from tests.test_value_inputs import PAYLOAD


@pytest.fixture()
def vdb_file(value_book_db, monkeypatch):
    import src.api.value_db as vdb

    monkeypatch.setattr(vdb, "_resolve_path", lambda: str(value_book_db))
    vdb.reset_engine()
    yield value_book_db
    vdb.reset_engine()


def _research(tmp_path, monkeypatch, *, filings: bool = True) -> None:
    path = tmp_path / "research.db"
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        s.add(SymbolRow(symbol="STDY", cik="0000000001", name="Steady Co"))
        if filings:
            s.add(
                CompanyFactsRawRow(
                    cik="0000000001",
                    payload_json=json.dumps(PAYLOAD),
                    fetched_at=datetime(2025, 9, 1),
                )
            )
        for sym in ("STDY", "SPY"):
            for i, d in enumerate(pd.bdate_range("2025-08-25", periods=6).date):
                s.add(
                    DailyBarRow(
                        symbol=sym, date=d, open=10, high=11, low=9, close=10 + i, volume=1e6
                    )
                )
        s.add(
            FinancialRow(
                symbol="STDY",
                period_end=date(2025, 6, 30),
                period_type="quarterly",
                line_item="revenue",
                value=1.0,
                accn="q2",
                filed=date(2025, 8, 5),
            )
        )
        s.commit()
    engine.dispose()
    monkeypatch.setattr(vi, "_resolve_path", lambda: str(path))
    vi.reset_engine()
    monkeypatch.setattr(vi, "load_regime", lambda: "normal")
    monkeypatch.setattr(vi, "fetch_market_facts", lambda symbol: MarketFacts())


@pytest.fixture()
def research(tmp_path, monkeypatch):
    _research(tmp_path, monkeypatch)
    yield
    vi.reset_engine()


def _snapshots() -> list[AppCommandRow]:
    with session_scope() as s:
        rows = list(s.scalars(select(AppCommandRow).where(AppCommandRow.kind == "value_snapshot")))
        s.expunge_all()
        return rows


def _fresh_json(symbol: str = "STDY") -> str:
    cfg = get_config().value
    with vi.research_read() as rs:
        assert rs is not None
        parts = vi.current_fingerprint_parts(rs, symbol)
    return freshness_json(
        parts, "normal", cfg.ruleset_version, rules_digest(cfg.rules.model_dump(mode="json"))
    )


def _set_freshness(symbol: str, value: str | None) -> None:
    with value_session() as s:
        row = s.get(ValueTickerFileRow, symbol)
        assert row is not None
        row.freshness_json = value


def test_a_current_file_is_served_as_stored_and_marked_viewed_once_a_day(
    client, vdb_file, research
) -> None:
    """Review M7 (reverses Task 14's "fresh file -> no intent"; spec §6.9 / ruling 19): the open
    is recorded so the follow window sees it, as one empty-fingerprint snapshot a name a day."""
    _seed_file("STDY")
    _set_freshness("STDY", _fresh_json())
    body = client.get("/value/STDY", headers=OWNER).json()
    assert body["computed"] == "stored" and body["file"]["symbol"] == "STDY"
    (row,) = _snapshots()
    assert row.payload == {"symbol": "STDY", "fingerprint": {}}
    assert row.dedupe_key.startswith("value_snapshot:STDY:viewed:")
    client.get("/value/STDY", headers=OWNER)  # pending: the same intent
    with session_scope() as s:  # applied: still the same day, still no second one
        s.get(AppCommandRow, row.id).status = "applied"
    client.get("/value/STDY", headers=OWNER)
    assert len(_snapshots()) == 1


def test_a_stale_file_is_computed_now_and_one_snapshot_carries_its_inputs(
    client, vdb_file, research
) -> None:
    _seed_file("STDY")  # no freshness_json: written before the column, stale once
    body = client.get("/value/STDY", headers=OWNER).json()
    assert body["computed"] == "now"
    assert body["file"]["symbol"] == "STDY" and body["file"]["ruleset_version"] == "v4"
    (row,) = _snapshots()
    fp = row.payload["fingerprint"]
    assert row.payload["symbol"] == "STDY" and row.status == "pending"
    assert fp["price_date"] == "2025-09-01"  # the newest settled bar before today
    assert fp["regime"] == "normal" and fp["ruleset_version"] == "v4"
    client.get("/value/STDY", headers=OWNER)
    assert len(_snapshots()) == 1  # a second open while it waits is the same intent


def test_an_absent_file_is_computed_now_too(client, vdb_file, research) -> None:
    body = client.get("/value/STDY", headers=OWNER).json()
    assert body["available"] is True and body["computed"] == "now"
    assert len(_snapshots()) == 1


def test_missing_filings_are_pending_and_queue_the_research_ingest(
    client, vdb_file, tmp_path, monkeypatch
) -> None:
    _research(tmp_path, monkeypatch, filings=False)
    queued: list[tuple[str, str]] = []
    monkeypatch.setattr("src.api.value_lookup._enqueue_ingest", lambda s, k: queued.append((s, k)))
    body = client.get("/value/STDY", headers=OWNER).json()
    assert body["computed"] == "pending" and body["file"] is None
    assert queued == [("STDY", "fundamentals")]
    assert _snapshots() == []
    vi.reset_engine()


def test_past_the_budget_the_stored_file_is_answered(
    client, vdb_file, research, monkeypatch
) -> None:
    _seed_file("STDY")
    monkeypatch.setattr("src.api.value_lookup._budget", lambda: 0.05)

    def slow(symbol: str) -> MarketFacts:
        time.sleep(0.6)
        return MarketFacts()

    monkeypatch.setattr(vi, "fetch_market_facts", slow)
    body = client.get("/value/STDY", headers=OWNER).json()
    assert body["computed"] == "stored" and body["file"]["symbol"] == "STDY"
    assert _snapshots() == []


def test_the_freshness_hash_and_the_ruleset_digest_agree_with_the_value_process() -> None:
    parts = {"latest_accn": "a1", "latest_filed": date(2026, 2, 10), "price_close": 31.5}
    assert freshness_key(parts, "normal", "v4", "be30d1eaa915") == ticker_freshness_key(
        parts, "normal", "v4", "be30d1eaa915"
    )
    rules = get_config().value.rules
    assert rules_digest(rules.model_dump(mode="json")) == ruleset_hash(rules) == "be30d1eaa915"


def test_the_lookup_writes_nothing_to_value_db(client, vdb_file, research) -> None:
    _seed_file("STDY")
    before = (vdb_file.stat().st_mtime_ns, vdb_file.stat().st_size, vdb_file.read_bytes())
    assert client.get("/value/STDY", headers=OWNER).json()["computed"] == "now"
    after = (vdb_file.stat().st_mtime_ns, vdb_file.stat().st_size, vdb_file.read_bytes())
    assert before == after
    assert os.path.exists(vdb_file)
