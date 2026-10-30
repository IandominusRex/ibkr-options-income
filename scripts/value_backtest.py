"""Stage 1b: the point-in-time backtest of Python's value rules (spec §12), printed for a human.

    python -m scripts.value_backtest [--universe evidence|trading] [--names A,B] [--limit N]
        [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--bars provider|research] [--refresh]
        [--out entries.json]

Filings come from the raw companyfacts payloads already in ``data/research.db``, opened read-only
one name at a time (``select_periods(as_of=)``: what was first filed by each date). Prices: with
``--bars provider`` (the default) ten years of daily bars from the bulk price provider, cached in
``data/value_backtest/`` (``--refresh`` refetches); with ``--bars research`` the ~2 years
research.db already holds (no network). The frozen ruleset is the one scored. Writes nothing but
the cache and ``--out``; no IBKR, no Telegram, no value.db. The caveats print first.
"""

from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from src.common import value_inputs as vi
from src.common.config import ROOT, get_config
from src.common.value_universe import build_value_universe
from src.value import backtest as bt
from src.value.ruleset import ruleset_id

log = logging.getLogger(__name__)

LOOKBACK_DAYS = 3660  # ten years: the provider's 10y period
CACHE_DIR = ROOT / "data" / "value_backtest"
WARMUP_DAYS = 400  # calendar days of bars before the first formation (210 sessions and SMA200)
FORWARD_DAYS = 190  # calendar days after the last formation (126 sessions to mark)
COLUMNS = ["open", "high", "low", "close", "volume"]

Fetch = Callable[[str], pd.DataFrame]


def _provider_fetch(symbol: str) -> pd.DataFrame:
    from src.data.factory import get_bulk_price_provider

    return get_bulk_price_provider().get_daily_bars(symbol, lookback_days=LOOKBACK_DAYS)


def _normalise(raw: pd.DataFrame) -> pd.DataFrame:
    """The provider's ``Open..Volume`` frame as ``read_bars``'s: lower-case, a date index."""
    if raw is None or raw.empty:
        return pd.DataFrame(columns=COLUMNS)
    frame = raw.rename(columns=str.lower)[COLUMNS].astype(float)
    frame.index = pd.Index([pd.Timestamp(i).date() for i in raw.index])
    return frame.sort_index()


def provider_bars(
    symbols: list[str],
    *,
    cache: Path = CACHE_DIR,
    refresh: bool = False,
    fetch: Fetch = _provider_fetch,
) -> dict[str, pd.DataFrame]:
    """Ten years of bars per symbol, from the cache unless *refresh* or absent."""
    cache.mkdir(parents=True, exist_ok=True)
    out: dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        path = cache / f"{symbol}.csv"
        if path.exists() and not refresh:
            frame = pd.read_csv(path, index_col=0)
            frame.index = pd.Index([date.fromisoformat(str(d)[:10]) for d in frame.index])
        else:
            frame = _normalise(fetch(symbol))
            if not frame.empty:
                frame.to_csv(path)
        if not frame.empty:
            out[symbol] = frame
    return out


def research_bars(symbols: list[str], as_of: date) -> dict[str, pd.DataFrame]:
    """The bars research.db already holds (read-only), up to *as_of*."""
    out: dict[str, pd.DataFrame] = {}
    with vi.research_read() as rs:
        if rs is None:
            return out
        for symbol in symbols:
            frame = vi.read_bars(rs, symbol, as_of)
            if not frame.empty:
                out[symbol] = frame
    return out


def load_payload(symbol: str) -> dict | None:
    with vi.research_read() as rs:
        return None if rs is None else vi.read_payload(rs, symbol)[1]


def _names(args: argparse.Namespace) -> list[bt.BacktestName]:
    from src.common.universe import effective_universe

    u = build_value_universe(get_config().value, effective_universe())
    pool = u.trading if args.universe == "trading" else u.evidence
    if args.names:
        pool = [s.strip().upper() for s in args.names.split(",") if s.strip()]
    pool = [s for s in pool if s not in u.etfs]
    if args.limit:
        pool = pool[: args.limit]
    return [bt.BacktestName(s, *u.classification.get(s, (None, None))) for s in pool]


def main(argv: list[str] | None = None, *, fetch: Fetch = _provider_fetch) -> int:
    parser = argparse.ArgumentParser(description="Stage 1b: the value rules, point in time")
    parser.add_argument("--universe", default="evidence", choices=("evidence", "trading"))
    parser.add_argument("--names", default=None, help="comma-separated symbols instead")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--start", type=date.fromisoformat, default=None)
    parser.add_argument("--end", type=date.fromisoformat, default=None)
    parser.add_argument("--bars", default="provider", choices=("provider", "research"))
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    cfg = get_config().value
    try:
        version, digest = ruleset_id(cfg)
    except ValueError as exc:
        print(f"value_backtest: {exc}")
        return 2
    names = _names(args)
    symbols = [n.symbol for n in names]
    if args.bars == "research":
        bars = research_bars([*symbols, "SPY"], date.today())
    else:
        bars = provider_bars([*symbols, "SPY"], refresh=args.refresh, fetch=fetch)
    spy = bars.pop("SPY", None)
    if spy is None or spy.empty:
        print("value_backtest: no SPY bars")
        return 2
    sessions = list(spy.index)
    start = args.start or sessions[0] + timedelta(days=WARMUP_DAYS)
    end = args.end or sessions[-1] - timedelta(days=FORWARD_DAYS)
    dates = bt.formation_dates(sessions, start, end)
    result = bt.run(
        names,
        bars=bars,
        spy=spy,
        load_payload=load_payload,
        dates=dates,
        cfg=cfg,
        version=version,
        digest=digest,
    )
    print(bt.render(result))
    if args.out:
        args.out.write_text(
            json.dumps([e.model_dump(mode="json") for e in result.entries], indent=1),
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
