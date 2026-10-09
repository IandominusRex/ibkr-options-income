"""📈 Measured post-release reaction (spec §6.4). Deterministic.

Windows on BAR TIMESTAMPS, never wall clock: yfinance futures/index bars can lag ~10 min,
so "15 minutes after" means the first bar stamped ≥ release + 15m. Missing → move None.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal

import pandas as pd
from pydantic import BaseModel

from src.common.config import NewsReactionCfg
from src.common.market_hours import is_rth
from src.data.protocols import IntradayPriceProvider

YIELD_SYMBOLS = frozenset({"^TNX", "^FVX", "^TYX", "^IRX"})
_FLAT_PCT = 0.05
_FLAT_BP = 0.5


class AssetMove(BaseModel):
    asset: str
    symbol: str
    move: float | None = None
    unit: Literal["%", "bp"] = "%"
    arrow: str = "⚪"


class Reaction(BaseModel):
    release_at: datetime
    window_min: int
    complete: bool
    moves: list[AssetMove]

    def display(self, asset: str) -> str | None:
        m = next((x for x in self.moves if x.asset == asset), None)
        if m is None or m.move is None:
            return None
        return (
            f"{m.arrow} {m.symbol} {m.move:+.2f}{m.unit}"
            if m.unit == "%"
            else f"{m.arrow} 10y {m.move:+.0f}bp"
        )


def instruments_for(release_at: datetime, cfg: NewsReactionCfg) -> dict[str, str]:
    return cfg.instruments_rth if is_rth(release_at) else cfg.instruments_ext


def _utc_index(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty or "Close" not in df:
        return pd.DataFrame()
    out = df.copy()
    idx = pd.DatetimeIndex(out.index)
    out.index = idx.tz_localize(UTC) if idx.tz is None else idx.tz_convert(UTC)
    return out.sort_index()


def _arrow(move: float, unit: str, inverse: bool) -> str:
    flat = _FLAT_BP if unit == "bp" else _FLAT_PCT
    if abs(move) < flat:
        return "⚪"
    up = move > 0
    if inverse:
        up = not up
    return "🟢" if up else "🔴"


def measure_reaction(
    release_at: datetime, *, cfg: NewsReactionCfg, provider: IntradayPriceProvider | None = None
) -> Reaction:
    if provider is None:
        from src.data.factory import get_intraday_price_provider

        provider = get_intraday_price_provider()
    rel = release_at.astimezone(UTC)
    target = rel + timedelta(minutes=cfg.window_min)
    moves: list[AssetMove] = []
    complete = True
    for asset, sym in instruments_for(rel, cfg).items():
        df = _utc_index(provider.get_intraday(sym, interval="1m", days=2))
        unit: Literal["%", "bp"] = "bp" if sym in YIELD_SYMBOLS else "%"
        before = df[df.index < rel]["Close"] if not df.empty else pd.Series(dtype=float)
        after = df[df.index >= target]["Close"] if not df.empty else pd.Series(dtype=float)
        if before.empty or after.empty:
            complete = False
            moves.append(AssetMove(asset=asset, symbol=sym, unit=unit))
            continue
        b, a = float(before.iloc[-1]), float(after.iloc[0])
        mv = (a - b) * 10 if unit == "bp" else (a / b - 1) * 100
        moves.append(
            AssetMove(
                asset=asset,
                symbol=sym,
                move=mv,
                unit=unit,
                arrow=_arrow(mv, unit, inverse=unit == "bp"),
            )
        )
    return Reaction(release_at=rel, window_min=cfg.window_min, complete=complete, moves=moves)


def move_after(
    df: pd.DataFrame, start: datetime, *, window_min: int, now: datetime
) -> float | None:
    """% move from the last bar before *start* to the latest bar inside ``[start, start +
    window_min]`` (and not after *now*) — the reaction to a story first seen at *start*
    (spec §7.2). None when either side has no bar."""
    bars = _utc_index(df)
    if bars.empty:
        return None
    s = start.astimezone(UTC)
    end = min(s + timedelta(minutes=window_min), now.astimezone(UTC))
    before = bars[bars.index < s]["Close"].dropna()
    inside = bars[(bars.index >= s) & (bars.index <= end)]["Close"].dropna()
    if before.empty or inside.empty or not float(before.iloc[-1]):
        return None
    return (float(inside.iloc[-1]) / float(before.iloc[-1]) - 1) * 100


def waited_too_long(release_at: datetime, now: datetime, cfg: NewsReactionCfg) -> bool:
    return now >= release_at + timedelta(minutes=cfg.max_wait_min)
