"""The API's handle on the trading database rejects writes at the SQLite layer."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import OperationalError

from src.api.trading_db import read_only_url


def test_read_only_url_shape() -> None:
    url = read_only_url("/tmp/income_system.db")
    assert url == "sqlite:///file:/tmp/income_system.db?mode=ro&uri=true"


def test_reads_succeed_and_writes_are_refused(tmp_path) -> None:
    db = tmp_path / "income_system.db"

    # Build a database with a row, using a normal read-write engine.
    rw = sa.create_engine(f"sqlite:///{db.as_posix()}")
    with rw.begin() as conn:
        conn.execute(sa.text("CREATE TABLE positions (symbol TEXT, qty INTEGER)"))
        conn.execute(sa.text("INSERT INTO positions VALUES ('AAPL', 100)"))
    rw.dispose()

    ro = sa.create_engine(read_only_url(db.as_posix()))

    with ro.connect() as conn:
        assert conn.execute(sa.text("SELECT qty FROM positions")).scalar_one() == 100

    with pytest.raises(OperationalError, match="readonly database"):
        with ro.connect() as conn:
            conn.execute(sa.text("INSERT INTO positions VALUES ('MSFT', 50)"))
            conn.commit()
