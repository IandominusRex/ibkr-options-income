"""The IV sanity flag (risk-envelope Task 10, spec §3.10.8, ruling P7).

Nov 5 2026: QQQ's stored IV collapsed to 14.6% against a VXN of 38.3 (ratio 0.38, where its
normal ratio is about 0.87), and everything that reads `iv_history` took it at face value. The
write path now flags an implausible observation (kept as a row, so the daily append stays
idempotent, but marked `flagged`) and every reader skips flagged rows.
"""

from __future__ import annotations

import ast
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

D0 = date(2026, 10, 1)  # first prior session; the "today" of every test is D0 + 40 days


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    import src.storage.db as dbmod
    from src.common.config import Config

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{tmp_path / 't.db'}")
    dbmod.init_db()


@pytest.fixture(autouse=True)
def notices(monkeypatch):
    """No test sends a Telegram message; the notices this module would send are recorded."""
    from src.storage import iv_history

    sent: list[tuple[str, str]] = []

    async def fake(text: str, *, thread: str = "account") -> bool:
        sent.append((thread, text))
        return True

    monkeypatch.setattr("src.notify.notices.send_notice", fake)
    monkeypatch.setattr(iv_history, "_ALERTED", set())
    return sent


def _bar(day: date, close: float):
    from src.storage.price_history import Bar

    return Bar(day, close, close, close, close, 0.0)


def seed_vol_index(symbol: str, closes: dict[date, float]) -> None:
    from src.storage.price_history import append_bars

    append_bars(symbol, [_bar(d, c) for d, c in closes.items()])


def seed_ratio_history(
    symbol: str, vol: str, *, n: int = 15, ratio: float = 0.87, vol_close: float = 30.0
) -> None:
    """*n* prior sessions of *symbol*'s IV at *ratio* of the vol index (a normal week)."""
    from src.storage.iv_history import append_observation

    days = [D0 + timedelta(days=i) for i in range(n)]
    seed_vol_index(vol, {d: vol_close for d in days})
    for d in days:
        assert append_observation(symbol, d, ratio * vol_close / 100.0) is True


def today_for(n: int = 15) -> date:
    return D0 + timedelta(days=n)


def row_for(symbol: str, day: date):
    from src.storage.db import session_scope
    from src.storage.models import IVHistoryRow

    with session_scope() as s:
        row = s.execute(
            select(IVHistoryRow).where(IVHistoryRow.symbol == symbol, IVHistoryRow.obs_date == day)
        ).scalar_one()
        return row.iv, bool(row.flagged)


# --------------------------------------------------------------------------- #
# config
# --------------------------------------------------------------------------- #


def test_the_sanity_block_ships_with_the_documented_values():
    from src.common.config import IvSanityCfg, get_config, get_iv_sanity_cfg

    cfg = get_iv_sanity_cfg()
    assert tuple(cfg.index_ratio_band) == (0.6, 1.4)
    assert tuple(cfg.single_band) == (0.5, 2.0)
    assert cfg.vol_index == {"SPY": "^VIX", "QQQ": "^VXN", "TQQQ": "^VXN"}
    assert cfg.min_history == 10
    assert set(get_config().risk["iv_sanity"]) == set(IvSanityCfg.KEYS)  # the example carries all


# --------------------------------------------------------------------------- #
# the flag
# --------------------------------------------------------------------------- #


def test_a_collapsed_qqq_iv_is_flagged():
    """QQQ 14.6 against VXN 38.3 (ratio 0.38) after a 0.87 median ratio: outside [0.6, 1.4] x 0.87."""
    from src.storage.iv_history import append_observation

    seed_ratio_history("QQQ", "^VXN")
    today = today_for()
    seed_vol_index("^VXN", {today: 38.3})
    assert append_observation("QQQ", today, 0.146) is True  # a row is written...
    assert row_for("QQQ", today) == (0.146, True)  # ...and marked


def test_a_normal_row_is_not_flagged():
    from src.storage.iv_history import append_observation

    seed_ratio_history("QQQ", "^VXN")
    today = today_for()
    seed_vol_index("^VXN", {today: 38.3})
    assert append_observation("QQQ", today, 0.87 * 0.383) is True
    assert row_for("QQQ", today)[1] is False
    # a move inside the band (ratio 1.1, inside 1.4 x 0.87 = 1.22) is a real change, not a flag
    nxt = today + timedelta(days=1)
    seed_vol_index("^VXN", {nxt: 38.3})
    assert append_observation("QQQ", nxt, 1.1 * 0.383) is True
    assert row_for("QQQ", nxt)[1] is False


def test_a_single_name_outside_its_own_band_is_flagged():
    from src.storage.iv_history import append_observation

    for i in range(20):
        append_observation("AAPL", D0 + timedelta(days=i), 0.25)
    today = today_for(20)
    assert append_observation("AAPL", today, 0.60) is True  # 2.4 x its 20-session median
    assert row_for("AAPL", today)[1] is True
    assert (
        append_observation("AAPL", today + timedelta(days=1), 0.40) is True
    )  # 1.6 x: a real spike
    assert row_for("AAPL", today + timedelta(days=1))[1] is False
    assert append_observation("AAPL", today + timedelta(days=2), 0.10) is True  # 0.4 x
    assert row_for("AAPL", today + timedelta(days=2))[1] is True


def test_too_little_history_never_flags():
    from src.storage.iv_history import append_observation

    # an index with 9 prior ratio rows: one short of `min_history`
    seed_ratio_history("QQQ", "^VXN", n=9)
    today = today_for(9)
    seed_vol_index("^VXN", {today: 38.3})
    assert append_observation("QQQ", today, 0.146) is True
    assert row_for("QQQ", today)[1] is False
    # a single name with 9 prior rows likewise
    for i in range(9):
        append_observation("MSFT", D0 + timedelta(days=i), 0.25)
    assert append_observation("MSFT", today_for(9), 1.50) is True
    assert row_for("MSFT", today_for(9))[1] is False


def test_a_missing_vol_index_close_never_flags():
    """No VXN bar on or shortly before the day: the index ratio cannot be measured, so no flag."""
    from src.storage.iv_history import append_observation

    seed_ratio_history("QQQ", "^VXN")
    far = today_for() + timedelta(days=30)  # the last VXN bar is a month old
    assert append_observation("QQQ", far, 0.146) is True
    assert row_for("QQQ", far)[1] is False


def test_a_flagged_row_still_blocks_a_second_write_for_its_day():
    """The unique (symbol, date) constraint: the daily append stays idempotent."""
    from src.storage.iv_history import append_observation

    seed_ratio_history("QQQ", "^VXN")
    today = today_for()
    seed_vol_index("^VXN", {today: 38.3})
    assert append_observation("QQQ", today, 0.146) is True
    assert append_observation("QQQ", today, 0.333) is False  # first write wins


def test_a_flag_raises_one_data_alert(notices, monkeypatch):
    """One notice per symbol per day, however many flagged rows."""
    from src.storage import iv_history
    from src.storage.iv_history import append_observation

    monkeypatch.setattr(iv_history, "today_et", lambda: date(2026, 11, 5))
    seed_ratio_history("QQQ", "^VXN")
    t1, t2 = today_for(), today_for() + timedelta(days=1)
    seed_vol_index("^VXN", {t1: 38.3, t2: 38.3})
    assert append_observation("QQQ", t1, 0.146) is True
    assert append_observation("QQQ", t2, 0.150) is True  # a second flagged row, same ET day
    assert len(notices) == 1
    thread, text = notices[0]
    assert thread == "account" and "QQQ" in text and "flagged" in text.lower()
    # a normal row raises nothing
    append_observation("AAPL", D0, 0.25)
    assert len(notices) == 1


# --------------------------------------------------------------------------- #
# readers
# --------------------------------------------------------------------------- #


def test_the_storage_readers_skip_a_flagged_row():
    from src.storage.iv_history import (
        append_observation,
        latest_iv,
        latest_obs_dates,
        stale_symbols,
    )

    seed_ratio_history("QQQ", "^VXN")
    today = today_for()
    seed_vol_index("^VXN", {today: 38.3})
    append_observation("QQQ", today, 0.146)  # flagged
    assert latest_iv("QQQ") == pytest.approx(0.87 * 0.30)  # the last unflagged row
    assert latest_obs_dates(["QQQ"]) == {"QQQ": today - timedelta(days=1)}
    assert ("QQQ", None) not in stale_symbols(["QQQ"], 10_000)


def test_iv_rank_ignores_a_flagged_row(monkeypatch):
    """`get_iv_stats` reads the stored history: a collapsed, flagged observation is neither the
    current IV nor the minimum the rank is measured against."""
    from src.analytics import iv as iv_mod
    from src.storage.iv_history import append_observation

    monkeypatch.setattr(iv_mod, "_compute_hv30", lambda symbol: None)
    monkeypatch.setattr(iv_mod, "compute_realized_vol", lambda symbol, window: None)
    seed_ratio_history("QQQ", "^VXN")
    today = today_for()
    seed_vol_index("^VXN", {today: 38.3})
    before = iv_mod.get_iv_stats("QQQ")
    append_observation("QQQ", today, 0.146)  # flagged
    after = iv_mod.get_iv_stats("QQQ")
    assert after.current_iv == before.current_iv  # not 14.6
    assert after.iv_rank == before.iv_rank


# Writers that must SEE a flagged row: the existence check behind the unique (symbol, date)
# constraint. Every other select over IVHistoryRow in `src/` must name `flagged`.
_MAY_SEE_FLAGGED = {("src/storage/iv_history.py", "append_observation")}


def _enclosing(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    parent: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent[child] = node
    return parent


def test_every_reader_skips_flagged_rows():
    """Structural (Q7): each statement under `src/` that selects from or queries `IVHistoryRow`
    names `flagged`, except the one existence check that must see every row."""
    offenders: list[str] = []
    checked = 0
    for path in sorted(SRC.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if "IVHistoryRow" not in text or path.name == "models.py":
            continue
        tree = ast.parse(text)
        parent = _enclosing(tree)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and "IVHistoryRow" in ast.unparse(node)):
                continue
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", "")
            if name not in ("select", "query"):
                continue
            stmt: ast.AST = node
            while stmt in parent and not isinstance(
                stmt, ast.Assign | ast.AnnAssign | ast.Return | ast.Expr
            ):
                stmt = parent[stmt]
            func_name = ""
            up: ast.AST = node
            while up in parent:
                up = parent[up]
                if isinstance(up, ast.FunctionDef | ast.AsyncFunctionDef):
                    func_name = up.name
                    break
            rel = str(path.relative_to(ROOT))
            checked += 1
            if (rel, func_name) in _MAY_SEE_FLAGGED:
                continue
            if "flagged" not in ast.unparse(stmt):
                offenders.append(f"{rel}:{node.lineno} ({func_name})")
    assert checked >= 8, "the scan no longer finds the iv_history readers"
    assert offenders == []


def test_an_existing_database_gains_the_flagged_column(tmp_path, monkeypatch):
    """A trading.db created before Task 10 has no `flagged` column: `init_db` adds it, with its
    old rows reading as unflagged (the API process reads it, so the trading service restarts first)."""
    import sqlite3

    import src.storage.db as dbmod
    from src.common.config import Config
    from src.storage.iv_history import latest_iv

    old = tmp_path / "old.db"
    conn = sqlite3.connect(old)
    conn.execute(
        "CREATE TABLE iv_history (id INTEGER PRIMARY KEY AUTOINCREMENT, symbol VARCHAR(16), "
        "obs_date DATE, iv FLOAT, source VARCHAR(16), UNIQUE (symbol, obs_date))"
    )
    conn.execute(
        "INSERT INTO iv_history (symbol, obs_date, iv, source) VALUES ('QQQ', '2026-10-01', 0.26, 'ibkr')"
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{old}")
    dbmod.init_db()
    conn = sqlite3.connect(old)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(iv_history)")}
    conn.close()
    assert "flagged" in columns
    assert latest_iv("QQQ") == 0.26  # the pre-existing row is not flagged
