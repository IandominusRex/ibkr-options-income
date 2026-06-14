"""Tests for the incremental OHLCV cache: price_history store + price_data.get_ohlcv.

The point of this layer is that `/scan` and the 15-min loop read settled daily bars from
SQLite and only fetch the *missing tail* from yfinance — instead of pulling a full 1y/3mo
history per symbol every run. These tests drive a temp DB and a mocked yfinance fetch.
"""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

from src.common import cache
from src.storage.price_history import Bar, append_bars, latest_bar_date, load_bars


def _db_setup(tmp_path, monkeypatch) -> None:
    import src.storage.db as dbmod
    from src.common.config import Config

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{tmp_path / 't.db'}")
    dbmod.init_db()


def _bars(end: date, n: int, start_price: float = 100.0) -> list[Bar]:
    """n consecutive calendar-day bars ending at *end* (weekends don't matter for the test)."""
    out = []
    for i in range(n):
        d = end - timedelta(days=n - 1 - i)
        p = start_price + i
        out.append(Bar(obs_date=d, open=p, high=p + 1, low=p - 1, close=p, volume=1000.0))
    return out


# --------------------------------------------------------------------------- #
# price_history accessor
# --------------------------------------------------------------------------- #


def test_append_and_load_roundtrip(tmp_path, monkeypatch):
    _db_setup(tmp_path, monkeypatch)
    bars = _bars(date(2026, 1, 30), 5)
    assert append_bars("AAA", bars) == 5
    loaded = load_bars("AAA")
    assert [b.obs_date for b in loaded] == [b.obs_date for b in bars]  # ascending
    assert latest_bar_date("AAA") == date(2026, 1, 30)


def test_append_is_idempotent(tmp_path, monkeypatch):
    _db_setup(tmp_path, monkeypatch)
    bars = _bars(date(2026, 1, 30), 5)
    append_bars("AAA", bars)
    # Re-appending the same dates plus one new day inserts only the new day.
    extended = bars + [Bar(date(2026, 1, 31), 105, 106, 104, 105, 1000.0)]
    assert append_bars("AAA", extended) == 1
    assert len(load_bars("AAA")) == 6


# --------------------------------------------------------------------------- #
# get_ohlcv — incremental fetch behaviour
# --------------------------------------------------------------------------- #


def test_cold_store_fetches_full_history_and_persists(tmp_path, monkeypatch):
    _db_setup(tmp_path, monkeypatch)
    from src.analytics import price_data

    today = date.today()
    fetched = _bars(today, 40)  # includes today (forming) + 39 prior

    with patch.object(price_data, "_fetch_yf_bars", return_value=fetched) as mk:
        df = price_data.get_ohlcv("AAA")

    mk.assert_called_once()
    # Settled bars persisted; today's forming bar excluded from the store.
    stored = [b.obs_date for b in load_bars("AAA")]
    assert today not in stored
    assert (today - timedelta(days=1)) in stored
    assert not df.empty
    assert today not in [ts.date() for ts in df.index]


def test_warm_store_makes_no_fetch(tmp_path, monkeypatch):
    _db_setup(tmp_path, monkeypatch)
    from src.analytics import price_data
    from src.common.market_hours import previous_session

    today = date.today()
    # Seed the store right up to the last completed session → nothing to fetch.
    append_bars("AAA", _bars(previous_session(today), 30))

    with patch.object(price_data, "_fetch_yf_bars") as mk:
        df = price_data.get_ohlcv("AAA")

    mk.assert_not_called()
    assert not df.empty


def test_gap_triggers_tail_fetch(tmp_path, monkeypatch):
    _db_setup(tmp_path, monkeypatch)
    from src.analytics import price_data

    today = date.today()
    # Store is stale (ends well before the last completed session) → a fetch must happen.
    append_bars("AAA", _bars(today - timedelta(days=20), 10))
    tail = _bars(today, 20)

    with patch.object(price_data, "_fetch_yf_bars", return_value=tail) as mk:
        price_data.get_ohlcv("AAA")

    mk.assert_called_once()
    # The tail was appended up to the day before today (the current session is still forming).
    assert latest_bar_date("AAA") == today - timedelta(days=1)


def test_get_ohlcv_cached_per_day(tmp_path, monkeypatch):
    _db_setup(tmp_path, monkeypatch)
    cache.clear_all()
    from src.analytics import price_data

    today = date.today()
    fetched = _bars(today, 40)
    with patch.object(price_data, "_fetch_yf_bars", return_value=fetched) as mk:
        price_data.get_ohlcv("AAA")
        price_data.get_ohlcv("AAA")  # second call served from the daily cache
    assert mk.call_count == 1
