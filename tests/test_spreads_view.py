"""The wheel's read-only window onto the spreads book's P&L (risk-envelope Task 6, spec §3.2c).

``src/common/spreads_view.py`` opens ``data/spreads.db`` with SQLite ``mode=ro`` and plain SQL,
imports no ``src.spreads``, and counts only the book's real mode (ruling P12).
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime

import pytest

import src.common.spreads_view as _view
from src.common.schemas import SpreadCandidate

_REAL_PATH = _view._path  # captured before conftest points the view at a missing file
DAY = date(2026, 10, 7)
T1000 = datetime(2026, 10, 7, 14, 0, tzinfo=UTC)  # 10:00 EDT
T1100 = datetime(2026, 10, 7, 15, 0, tzinfo=UTC)
YESTERDAY = datetime(2026, 10, 6, 15, 0, tzinfo=UTC)


@pytest.fixture()
def spreads_file(tmp_path, monkeypatch):
    """A spreads.db built by the spreads store, and the view pointed at the same file."""
    import src.common.spreads_view as view
    import src.spreads.store as st

    path = tmp_path / "spreads.db"
    monkeypatch.setattr(st, "_engine", None)
    monkeypatch.setattr(st, "_SessionLocal", None)
    monkeypatch.setattr(st, "_resolve_url", lambda: f"sqlite:///{path}")
    monkeypatch.setattr(view, "_path", lambda: path)
    st.init_spreads_db()
    return st, path


def test_the_view_reads_the_configured_spreads_file() -> None:
    from pathlib import Path

    from src.common.config import get_config

    url = get_config().spreads_db_url_abs()
    assert _REAL_PATH() == Path(url.removeprefix("sqlite:///"))


def _spread(st, spread_id: str, *, mode: str, at: datetime, contracts: int = 2, credit=0.60):
    return st.open_position(
        SpreadCandidate(
            spread_id=spread_id,
            side="put",
            expiry=at.date(),
            short_strike=679.0,
            long_strike=674.0,
            width=5.0,
            credit_mid=credit,
            credit_natural=credit - 0.01,
            spot=690.0,
            quote_time=at,
        ),
        mode=mode,
        contracts=contracts,
        credit=credit,
        commission=2.6,
        now=at,
        perm_id=None,
    )


def test_spreads_view_opens_read_only(spreads_file) -> None:
    from src.common import spreads_view

    _, path = spreads_file
    con = spreads_view.connect()
    assert con is not None
    with pytest.raises(sqlite3.OperationalError):
        con.execute("DELETE FROM spread_positions")
    con.close()
    from pathlib import Path

    assert "mode=ro" in Path(spreads_view.__file__).read_text(encoding="utf-8")


def test_pnl_today_counts_only_the_real_mode(spreads_file) -> None:
    from src.common.spreads_view import pnl_today

    st, _ = spreads_file
    # A paper spread closed today at a loss: −(1.50 − 0.60) × 100 × 2 − commissions.
    _spread(st, "p-closed", mode="paper", at=T1000)
    realized = st.close_position(
        "p-closed", contracts=2, debit=1.50, commission=2.6, reason="stop_loss", now=T1100
    )
    # A paper spread still open, marked at 0.90 against a 0.60 credit: −$60 open.
    _spread(st, "p-open", mode="paper", at=T1000)
    st.note_mark("p-open", 0.90)
    # Shadow and baseline rows never count (P12), nor a paper spread closed yesterday.
    _spread(st, "s1", mode="shadow", at=T1000)
    st.close_position("s1", contracts=2, debit=4.0, commission=2.6, reason="stop_loss", now=T1100)
    _spread(st, "b1-BL", mode="baseline", at=T1000)
    st.note_mark("b1-BL", 3.0)
    _spread(st, "p-old", mode="paper", at=YESTERDAY)
    st.close_position(
        "p-old", contracts=2, debit=4.0, commission=2.6, reason="stop_loss", now=YESTERDAY
    )
    assert pnl_today(DAY) == pytest.approx(realized + (0.60 - 0.90) * 100 * 2)


def test_pnl_today_is_none_when_the_file_is_missing(tmp_path, monkeypatch) -> None:
    from src.common.spreads_view import pnl_today

    monkeypatch.setattr(_view, "_path", lambda: tmp_path / "absent.db")
    assert pnl_today(DAY) is None
    assert not (tmp_path / "absent.db").exists()  # a read-only open never creates the file


def test_pnl_today_is_zero_on_a_quiet_day(spreads_file) -> None:
    from src.common.spreads_view import pnl_today

    assert pnl_today(DAY) == 0.0


def test_the_view_imports_nothing_from_the_spreads_package() -> None:
    import ast
    from pathlib import Path

    import src.common.spreads_view as view

    tree = ast.parse(Path(view.__file__).read_text(encoding="utf-8"))
    mods = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | {
        a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names
    }
    assert not any(m == "src.spreads" or m.startswith("src.spreads.") for m in mods)
    assert {m for m in mods if m.startswith("src.")} <= {"src.common.config"}
