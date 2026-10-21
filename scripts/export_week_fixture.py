"""Export the real daily bars the week-of-2026-10-13 replay tests run on.

The replay (`tests/test_week_replay.py`) and the support-detector tests must run on real bars,
but no test may read ``data/``. This one-off script writes ``Date,Open,High,Low,Close,Volume``
CSVs that are committed under ``tests/fixtures/week_2026_10_13/``:

* SPY, QQQ, TQQQ, SOXL from the ``price_history`` table of ``--db`` (opened read-only);
* ^VIX and ^VIX3M through the active price provider (the **only** place in this change that
  touches the network; the index bars are not in ``price_history``).

Run it once, from the repo root, against the main checkout's database::

    python -m scripts.export_week_fixture \\
        --db "$MAIN/data/income_system.db" --out tests/fixtures/week_2026_10_13

If the provider is unavailable the index files are skipped with a clear message; nothing is
invented.
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from datetime import date
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

CSV_COLUMNS = ("Date", "Open", "High", "Low", "Close", "Volume")
DB_SYMBOLS = ("SPY", "QQQ", "TQQQ", "SOXL")
INDEX_SYMBOLS = {"^VIX": "VIX", "^VIX3M": "VIX3M"}
START = date(2025, 9, 1)
END = date(2026, 10, 19)


def read_price_history(db_path: Path, symbol: str, start: date, end: date) -> pd.DataFrame:
    """Daily bars for *symbol* between *start* and *end* inclusive, from ``price_history``.

    The database is opened with ``mode=ro`` (a missing file is an error, never a new empty
    database). Ascending, indexed by date, columns Open/High/Low/Close/Volume.
    """
    con = sqlite3.connect(f"file:{Path(db_path).as_posix()}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "select obs_date, open, high, low, close, volume from price_history "
            "where symbol = ? and obs_date between ? and ? order by obs_date",
            (symbol, start.isoformat(), end.isoformat()),
        ).fetchall()
    finally:
        con.close()
    frame = pd.DataFrame(rows, columns=list(CSV_COLUMNS))
    frame["Date"] = pd.to_datetime(frame["Date"])
    return frame.set_index("Date")


def write_csv(frame: pd.DataFrame, path: Path) -> None:
    """Write *frame* (a date-indexed OHLCV frame) as ``Date,Open,High,Low,Close,Volume``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    out = frame.copy()
    out.index.name = "Date"
    out[list(CSV_COLUMNS[1:])].to_csv(path, float_format="%.6g")


def read_index(symbol: str, start: date, end: date) -> pd.DataFrame:
    """An index (``^VIX``...) through the active price provider, cut to ``[start, end]``."""
    from src.data.factory import get_price_provider  # network: this script only

    raw = get_price_provider().get_ohlcv(symbol, lookback_days=500)
    if raw is None or raw.empty:
        return pd.DataFrame(columns=list(CSV_COLUMNS[1:]))
    idx = pd.DatetimeIndex(raw.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    frame = raw.copy()
    frame.index = idx.normalize()
    frame = frame[(frame.index >= pd.Timestamp(start)) & (frame.index <= pd.Timestamp(end))]
    return frame[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", required=True, type=Path, help="income_system.db (read-only)")
    parser.add_argument("--out", required=True, type=Path, help="fixture directory")
    args = parser.parse_args(argv)

    for symbol in DB_SYMBOLS:
        frame = read_price_history(args.db, symbol, START, END)
        write_csv(frame, args.out / f"{symbol}.csv")
        print(
            f"{symbol}: {len(frame)} bars {frame.index.min():%Y-%m-%d}..{frame.index.max():%Y-%m-%d}"
        )

    missing = 0
    for symbol, name in INDEX_SYMBOLS.items():
        frame = read_index(symbol, START, END)
        if frame.empty:
            print(f"{symbol}: provider returned nothing - {name}.csv NOT written", file=sys.stderr)
            missing += 1
            continue
        write_csv(frame, args.out / f"{name}.csv")
        print(
            f"{symbol}: {len(frame)} bars {frame.index.min():%Y-%m-%d}..{frame.index.max():%Y-%m-%d}"
        )
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
