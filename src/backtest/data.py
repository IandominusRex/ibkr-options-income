"""Historical price loader for the backtest harness (yfinance).

Isolated from `engine.py` so the simulation core stays pure and unit-testable without a network.
"""

from __future__ import annotations

from datetime import date

import yfinance as yf

from src.common.logging import get_logger

log = get_logger(__name__)


def load_price_series(
    symbol: str,
    start: date | None = None,
    end: date | None = None,
    period: str = "2y",
) -> list[tuple[date, float]]:
    """Return ascending ``(date, close)`` daily closes for ``symbol``.

    Uses an explicit ``start``/``end`` window when given, else the rolling ``period``. Returns an
    empty list (never raises) when the fetch fails or the symbol has no history.
    """
    try:
        ticker = yf.Ticker(symbol)
        if start is not None:
            df = ticker.history(start=start.isoformat(), end=end.isoformat() if end else None)
        else:
            df = ticker.history(period=period)
        if df.empty:
            log.warning("backtest: no price history for %s", symbol)
            return []
        return [
            (idx.date(), float(close)) for idx, close in zip(df.index, df["Close"], strict=False)
        ]
    except Exception as exc:
        log.warning("backtest: price load failed for %s: %s", symbol, exc)
        return []


def load_iv_series(symbol: str, dates: list[date]) -> list[float | None]:
    """Stored daily IV (fraction) aligned to ``dates`` — the v2 backtest's entry-IV source (N21).

    Forward-fills the most recent `iv_history` observation on/before each price date (markets
    close on weekends but the option's IV anchor is the last known reading). Returns a list the
    same length as ``dates`` with None where no observation exists yet. Never raises.
    """
    if not dates:
        return []
    try:
        from sqlalchemy import select

        from src.storage.db import session_scope
        from src.storage.models import IVHistoryRow

        with session_scope() as sess:
            rows = sess.execute(
                select(IVHistoryRow.obs_date, IVHistoryRow.iv)
                .where(IVHistoryRow.symbol == symbol)
                .order_by(IVHistoryRow.obs_date)
            ).all()
    except Exception as exc:
        log.warning("backtest: iv_history load failed for %s: %s", symbol, exc)
        return [None] * len(dates)

    obs = [(d, float(v)) for d, v in rows if v is not None]
    if not obs:
        return [None] * len(dates)

    out: list[float | None] = []
    i = 0  # pointer into obs (ascending)
    last: float | None = None
    for d in dates:
        while i < len(obs) and obs[i][0] <= d:
            last = obs[i][1]
            i += 1
        out.append(last)
    return out
