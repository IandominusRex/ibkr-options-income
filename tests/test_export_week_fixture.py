"""The fixture exporter's database half (Task 5): read-only, one CSV per symbol.

The network half (^VIX / ^VIX3M through the price provider) is not tested here: tests never
touch the network. The exporter is the only script allowed to.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from scripts.export_week_fixture import CSV_COLUMNS, read_price_history, write_csv


def _make_db(path: Path) -> None:
    con = sqlite3.connect(path)
    con.execute(
        "create table price_history (id integer primary key, symbol text, obs_date text, "
        "open real, high real, low real, close real, volume real, source text)"
    )
    rows = [
        ("TQQQ", "2026-10-12", 80.0, 81.0, 79.0, 79.61, 1000.0),
        ("TQQQ", "2026-10-13", 79.0, 80.0, 77.5, 78.00, 1200.0),
        ("TQQQ", "2026-10-20", 70.0, 71.0, 69.0, 70.50, 900.0),  # outside the range
        ("SPY", "2026-10-12", 600.0, 601.0, 598.0, 599.0, 5000.0),
    ]
    con.executemany(
        "insert into price_history (symbol, obs_date, open, high, low, close, volume, source) "
        "values (?, ?, ?, ?, ?, ?, ?, 'test')",
        rows,
    )
    con.commit()
    con.close()


def test_reads_one_symbol_in_range_ascending(tmp_path: Path) -> None:
    db = tmp_path / "t.db"
    _make_db(db)
    frame = read_price_history(db, "TQQQ", date(2026, 10, 12), date(2026, 10, 19))
    assert list(frame.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert [d.date() for d in frame.index] == [date(2026, 10, 12), date(2026, 10, 13)]
    assert float(frame["Close"].iloc[0]) == 79.61


def test_database_is_opened_read_only(tmp_path: Path) -> None:
    db = tmp_path / "t.db"
    _make_db(db)
    read_price_history(db, "TQQQ", date(2026, 10, 12), date(2026, 10, 19))
    con = sqlite3.connect(db)
    assert con.execute("select count(*) from price_history").fetchone()[0] == 4
    con.close()
    # a missing database is an error, not a silently created empty file
    with pytest.raises(sqlite3.OperationalError):
        read_price_history(tmp_path / "missing.db", "TQQQ", date(2026, 10, 12), date(2026, 10, 19))
    assert not (tmp_path / "missing.db").exists()


def test_csv_round_trip(tmp_path: Path) -> None:
    db = tmp_path / "t.db"
    _make_db(db)
    frame = read_price_history(db, "TQQQ", date(2026, 10, 12), date(2026, 10, 19))
    out = tmp_path / "TQQQ.csv"
    write_csv(frame, out)
    assert out.read_text(encoding="utf-8").splitlines()[0] == ",".join(CSV_COLUMNS)
    back = pd.read_csv(out, index_col=0, parse_dates=True)
    assert list(back.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert float(back["Low"].iloc[1]) == 77.5
