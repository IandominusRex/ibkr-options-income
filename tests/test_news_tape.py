from __future__ import annotations

from datetime import date

import pandas as pd

from src.news import tape


def _daily(dates, closes):
    return pd.DataFrame({"Close": closes}, index=pd.DatetimeIndex(pd.to_datetime(dates)))


def test_prev_close_skips_todays_forming_bar() -> None:
    df = _daily(["2026-10-07", "2026-10-08", "2026-10-09"], [100.0, 102.0, 99.0])
    assert tape.prev_close_from(df, date(2026, 10, 9)) == 102.0
    assert tape.prev_close_from(df, date(2026, 10, 10)) == 99.0
    assert tape.prev_close_from(pd.DataFrame(), date(2026, 10, 9)) is None


def test_quote_change_pct(monkeypatch) -> None:
    class P:
        def get_last_price(self, s):
            return 97.92

        def get_ohlcv(self, s, lookback_days=10):
            return _daily(["2026-10-08", "2026-10-09"], [102.0, 98.0])

    monkeypatch.setattr(tape, "get_price_provider", lambda: P())
    q = tape.quote("SPY", today=date(2026, 10, 9))
    assert q.prev_close == 102.0 and round(q.change_pct, 2) == -4.0


def test_quote_degrades_to_none(monkeypatch) -> None:
    class P:
        def get_last_price(self, s):
            return None

        def get_ohlcv(self, s, lookback_days=10):
            return pd.DataFrame()

    monkeypatch.setattr(tape, "get_price_provider", lambda: P())
    q = tape.quote("ZZZ", today=date(2026, 10, 9))
    assert q.last is None and q.change_pct is None
