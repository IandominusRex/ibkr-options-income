"""The deterministic market regime: pure rules over SPY, QQQ and the VIX complex.

Deterministic tier. The regime this module classifies feeds the Rules Engine's sizing limits
(`src/engine/regime_limits.py`), so it reads price data through `src/data/` and nothing else: no
macro backdrop, sentiment or sector context (the enrichment tier), and nothing from the
reasoning layer. `tests/test_regime_classifier.py` asserts it.

Regimes run normal -> cautious -> stressed -> crisis, classified **separately for SPY and QQQ**
(tech-linked names follow the stricter one). What drives them (spec section 4):

* **fast signals decide it** — the VIX close for both indices (ruling 15), its 1-year percentile
  (counted only at the 90th percentile *and* a VIX of at least 20, ruling 39), and the
  VIX/VIX3M term ratio (above 1 is backwardation);
* **slow signals may add at most one notch** — drawdown from the 52-week high, price under the
  200-day, or under the 50-day with a falling month;
* **intraday escalation** — an index's move on the day, or the live VIX, can lift the daily
  base at once (one-way within the day; the persisted state expires it at the close, ruling 40).

**Data freshness is part of the rule.** A field that could not be read, or a "live" value that
is really a last close, is `None` and named in `RegimeInputs.stale`: the classifier skips it,
and a skipped input is never read as calm (a stale -5% cannot escalate; a stale VIX cannot make
the day look quiet). Every fetcher here is fail-soft: it returns what it could read.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any, Literal

import numpy as np
import pandas as pd

from src.analytics.price_data import get_ohlcv
from src.common.config import RegimeThresholdsCfg
from src.common.market_hours import is_rth, previous_session, today_et
from src.common.schemas import MarketRegime, RegimeInputs
from src.data.factory import get_price_provider

log = logging.getLogger(__name__)

ORDER: tuple[MarketRegime, ...] = (
    MarketRegime.NORMAL,
    MarketRegime.CAUTIOUS,
    MarketRegime.STRESSED,
    MarketRegime.CRISIS,
)

IndexName = Literal["SPY", "QQQ"]
_VOL_SYMBOL = "^VIX"
_VOL3M_SYMBOL = "^VIX3M"
# A daily bar older than the last completed session by more than this many calendar days is a
# store served while the data source is down, not "yesterday's close" (covers a long weekend).
_STALE_BAR_DAYS = 4
_TRADING_YEAR = 252

_INDEX_DERIVED = (
    "index_close",
    "sma50",
    "sma200",
    "drawdown_52w_pct",
    "ret_1m_pct",
    "ret_3m_pct",
    "rv20",
    "rv_1y_avg",
)
_COLUMNS = ["Open", "High", "Low", "Close", "Volume"]


# --------------------------------------------------------------------------- #
# Ordering
# --------------------------------------------------------------------------- #


def stricter(a: MarketRegime, b: MarketRegime) -> MarketRegime:
    """The more severe of two regimes."""
    return a if ORDER.index(a) >= ORDER.index(b) else b


def escalate_one(r: MarketRegime) -> MarketRegime:
    """One notch more severe, clamped at crisis."""
    return ORDER[min(ORDER.index(r) + 1, len(ORDER) - 1)]


def ease_one(r: MarketRegime) -> MarketRegime:
    """One notch calmer, clamped at normal."""
    return ORDER[max(ORDER.index(r) - 1, 0)]


# --------------------------------------------------------------------------- #
# Bars
# --------------------------------------------------------------------------- #


def _empty() -> pd.DataFrame:
    return pd.DataFrame(columns=_COLUMNS)


def _load_raw(symbol: str) -> pd.DataFrame:
    """The unfiltered daily frame for *symbol* (the only network-touching call in this module).

    Stocks and ETFs come from the shared settled-bar store (`price_data.get_ohlcv`); indices
    (``^``-prefixed) are not in that store and come from the price provider, whose frame ends
    with today's forming bar.
    """
    if symbol.startswith("^"):
        return get_price_provider().get_ohlcv(symbol, lookback_days=400)
    return get_ohlcv(symbol)


def get_bars(symbol: str, *, today: date | None = None) -> pd.DataFrame:
    """Daily OHLCV for *symbol*: ascending, tz-naive, and never including a bar dated today.

    Ruling 39: the index provider's frame includes today's forming bar
    (``yfinance_backend.py``) while ``price_data.get_ohlcv`` does not, so every symbol is cut
    at the same place — a partial day must never enter a daily input. *today* is the ET date
    (default now). Empty frame on any failure; never raises.
    """
    cutoff = today if today is not None else today_et()
    try:
        raw = _load_raw(symbol)
    except Exception:
        log.warning("regime: bars for %s failed", symbol, exc_info=True)
        return _empty()
    if raw is None or raw.empty or "Close" not in raw.columns:
        return _empty()
    df = raw.copy()
    idx = pd.DatetimeIndex(df.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)  # keep the wall-clock (exchange) date
    df.index = idx.normalize()
    df = df.sort_index()
    df = df[df.index < pd.Timestamp(cutoff)]
    return df[df["Close"].notna()]


def _closes(df: pd.DataFrame | None, *, floor: date) -> pd.Series | None:
    """The close series, or None when empty or last dated before *floor* (a stale store)."""
    if df is None or df.empty or "Close" not in df.columns:
        return None
    closes = df["Close"].astype(float).dropna()
    if closes.empty or closes.index[-1].date() < floor:
        return None
    return closes


def _round(x: float | None, nd: int = 4) -> float | None:
    if x is None or not math.isfinite(x):
        return None
    return round(float(x), nd)


# --------------------------------------------------------------------------- #
# Inputs
# --------------------------------------------------------------------------- #


def fetch_daily_inputs(
    index: IndexName,
    *,
    bars: Callable[[str], pd.DataFrame] = get_bars,
    today: date | None = None,
) -> RegimeInputs:
    """Every daily field of one index's regime inputs; the live fields are left ``None``.

    Reads settled closes only (`get_bars` drops today's bar). Never raises: a frame that is
    empty, missing, or older than the last completed session leaves its fields ``None`` and
    names them in ``stale`` so the classifier skips them rather than reading them as calm.
    """
    day = today if today is not None else today_et()
    floor = previous_session(day) - timedelta(days=_STALE_BAR_DAYS)

    def safe(symbol: str) -> pd.DataFrame | None:
        try:
            return bars(symbol)
        except Exception:
            log.warning("regime: bars for %s failed", symbol, exc_info=True)
            return None

    stale: list[str] = []
    values: dict[str, Any] = {}

    # --- the index itself ---
    closes = _closes(safe(index), floor=floor)
    if closes is None:
        stale.extend(_INDEX_DERIVED)
    else:
        last = float(closes.iloc[-1])
        values["index_close"] = _round(last)
        if len(closes) >= 50:
            values["sma50"] = _round(float(closes.iloc[-50:].mean()))
        if len(closes) >= 200:
            values["sma200"] = _round(float(closes.iloc[-200:].mean()))
        window = closes.iloc[-_TRADING_YEAR:]
        values["drawdown_52w_pct"] = _round(max(0.0, (1.0 - last / float(window.max())) * 100.0), 3)
        if len(closes) >= 22:
            values["ret_1m_pct"] = _round((last / float(closes.iloc[-22]) - 1.0) * 100.0, 3)
        if len(closes) >= 64:
            values["ret_3m_pct"] = _round((last / float(closes.iloc[-64]) - 1.0) * 100.0, 3)
        rets = np.log(closes.astype(float)).diff().dropna()
        rolling = (rets.rolling(20).std() * math.sqrt(252) * 100.0).dropna()
        if len(rolling) >= 1:
            values["rv20"] = _round(float(rolling.iloc[-1]), 3)
            values["rv_1y_avg"] = _round(float(rolling.iloc[-_TRADING_YEAR:].mean()), 3)

    # --- the vol complex ---
    vix = _closes(safe(_VOL_SYMBOL), floor=floor)
    if vix is None:
        stale.extend(["vol", "vol_pct_1y"])
    else:
        values["vol"] = _round(float(vix.iloc[-1]), 3)
        recent = vix.iloc[-_TRADING_YEAR:]
        if len(recent) >= 100:
            values["vol_pct_1y"] = _round(float((recent <= recent.iloc[-1]).mean() * 100.0), 2)

    vix3m = _closes(safe(_VOL3M_SYMBOL), floor=floor)
    ratio: pd.Series | None = None
    if vix is not None and vix3m is not None:
        both = pd.concat([vix.rename("vix"), vix3m.rename("vix3m")], axis=1, join="inner").dropna()
        both = both[both["vix3m"] > 0]
        if not both.empty:
            ratio = both["vix"] / both["vix3m"]
    if ratio is None:
        stale.append("term_ratio")
    else:
        values["term_ratio"] = _round(float(ratio.iloc[-1]), 4)
        streak = 0
        for v in reversed(ratio.to_numpy()):
            if v < 1.0:
                streak += 1
            else:
                break
        values["contango_streak"] = streak

    return RegimeInputs(**values, stale=list(dict.fromkeys(stale)))


def _default_last_price(symbol: str) -> float | None:
    return get_price_provider().get_last_price(symbol)


def last_price(symbol: str) -> float | None:
    """The live last price of *symbol* (None on any failure), through the price provider.

    The one entry the sizing context uses for a live spot; tests stub ``_default_last_price``
    and so stub this too.
    """
    try:
        value = _default_last_price(symbol)
    except Exception:
        log.warning("regime: last price for %s failed", symbol, exc_info=True)
        return None
    if value is None or not math.isfinite(float(value)) or float(value) <= 0:
        return None
    return float(value)


def fetch_live_inputs(
    index: IndexName,
    prior_close: float | None,
    *,
    now: datetime,
    last_price: Callable[[str], float | None] | None = None,
    prior_vol_close: float | None = None,
) -> dict[str, Any]:
    """The live fields (``index_live``, ``day_change_pct``, ``live_vol``) and a ``stale`` list.

    A live value is **stale** — returned as ``None`` and named in ``stale`` — when the price
    provider returned nothing or raised, when *now* is outside regular trading hours (no live
    fetch is made then), or when it equals the prior close rounded to 4 decimals (ruling 39:
    yfinance's ``lastPrice`` carries no timestamp, so an unchanged value is a last close
    served as live). ``day_change_pct = (index_live / prior_close - 1) x 100``. The VIX is
    compared against *prior_vol_close* (the VIX's last settled close) the same way.
    """
    out: dict[str, Any] = {"index_live": None, "day_change_pct": None, "live_vol": None}
    stale: list[str] = []
    out["stale"] = stale
    if not is_rth(now):
        stale.extend(["index_live", "day_change_pct", "live_vol"])
        return out

    fetch = last_price if last_price is not None else _default_last_price

    def live(symbol: str, prior: float | None) -> float | None:
        try:
            value = fetch(symbol)
        except Exception:
            log.warning("regime: live price for %s failed", symbol, exc_info=True)
            return None
        if value is None or not math.isfinite(float(value)) or float(value) <= 0:
            return None
        if prior is not None and round(float(value), 4) == round(float(prior), 4):
            return None  # a last close served as live
        return float(value)

    index_live = live(index, prior_close)
    if index_live is None:
        stale.extend(["index_live", "day_change_pct"])
    else:
        out["index_live"] = round(index_live, 4)
        if prior_close is not None and prior_close > 0:
            out["day_change_pct"] = round((index_live / prior_close - 1.0) * 100.0, 4)
        else:
            stale.append("day_change_pct")

    live_vol = live(_VOL_SYMBOL, prior_vol_close)
    if live_vol is None:
        stale.append("live_vol")
    else:
        out["live_vol"] = round(live_vol, 3)
    return out


# --------------------------------------------------------------------------- #
# Classification
# --------------------------------------------------------------------------- #


def classify_base(inp: RegimeInputs, th: RegimeThresholdsCfg) -> tuple[MarketRegime, list[str]]:
    """The daily base regime and the reasons behind it.

    Fast regime = the strictest of the VIX level, the VIX percentile rule (>= the 90th
    percentile *and* a VIX >= 20) and the term ratio; then one notch stricter when the slow
    rule fires. A stale field is skipped and named (``stale:<field>``): it is never treated
    as calm, and with nothing fast to read the slow signals alone still add their notch.
    """
    stale = set(inp.stale)
    why: list[str] = []

    def read(name: str) -> Any:
        if name in stale:
            why.append(f"stale:{name}")
            return None
        return getattr(inp, name)

    vol = read("vol")
    pct = read("vol_pct_1y")
    term = read("term_ratio")

    fast = MarketRegime.NORMAL
    if vol is not None:
        if vol >= th.vol_crisis:
            fast = stricter(fast, MarketRegime.CRISIS)
            why.append(f"VIX {vol:.1f}")
        elif vol >= th.vol_stressed:
            fast = stricter(fast, MarketRegime.STRESSED)
            why.append(f"VIX {vol:.1f}")
        elif vol >= th.vol_cautious:
            fast = stricter(fast, MarketRegime.CAUTIOUS)
            why.append(f"VIX {vol:.1f}")
        if pct is not None and pct >= th.vol_pct_cautious and vol >= th.vol_pct_min_vol:
            fast = stricter(fast, MarketRegime.CAUTIOUS)
            why.append(f"VIX at the {pct:.0f}th percentile of the year")
    if term is not None:
        if term >= th.term_crisis:
            fast = stricter(fast, MarketRegime.CRISIS)
            why.append(f"VIX/VIX3M {term:.2f} (backwardation)")
        elif term >= th.term_stressed:
            fast = stricter(fast, MarketRegime.STRESSED)
            why.append(f"VIX/VIX3M {term:.2f} (backwardation)")

    if _slow_signal(inp, th, why, stale):
        return escalate_one(fast), why
    return fast, why


def _slow_signal(
    inp: RegimeInputs, th: RegimeThresholdsCfg, why: list[str], stale: set[str]
) -> bool:
    """Pinned slow rule: a drawdown from the 52-week high, a close under the 200-day, or a close
    under the 50-day with a falling month. A stale or missing field never fires it."""
    if "index_close" in stale:
        why.append("stale:index_close")
        return False
    close = inp.index_close
    fired = False
    dd = inp.drawdown_52w_pct
    if dd is not None and "drawdown_52w_pct" not in stale and dd >= th.slow_drawdown_pct:
        why.append(f"slow: {dd:.1f}% below the 52-week high")
        fired = True
    if close is not None and inp.sma200 is not None and close < inp.sma200:
        why.append("slow: below the 200-day average")
        fired = True
    if (
        close is not None
        and inp.sma50 is not None
        and close < inp.sma50
        and inp.ret_1m_pct is not None
        and inp.ret_1m_pct <= th.slow_ret_1m_pct
    ):
        why.append(f"slow: below the 50-day average with {inp.ret_1m_pct:+.1f}% on the month")
        fired = True
    return fired


def intraday_escalation(
    index: IndexName, inp: RegimeInputs, th: RegimeThresholdsCfg
) -> tuple[MarketRegime, list[str]]:
    """The regime today's live moves call for (normal when nothing breached).

    Triggers (spec section 4): the index's move on the day, or the live VIX. A stale input
    cannot escalate and is named (``stale:<field>``) — it also cannot calm anything, because
    this only ever returns a floor the persisted base is raised to, never a lower regime.
    """
    cfg = th.intraday
    limits = cfg.SPY if index == "SPY" else cfg.QQQ
    stale = set(inp.stale)
    level = MarketRegime.NORMAL
    why: list[str] = []

    for name in ("day_change_pct", "live_vol"):
        if name in stale:
            why.append(f"stale:{name}")

    pct = inp.day_change_pct
    if pct is not None and "day_change_pct" not in stale:
        if pct <= limits.crisis:
            level = stricter(level, MarketRegime.CRISIS)
            why.append(f"{index} {pct:+.1f}% today")
        elif pct <= limits.stressed:
            level = stricter(level, MarketRegime.STRESSED)
            why.append(f"{index} {pct:+.1f}% today")

    live_vol = inp.live_vol
    if live_vol is not None and "live_vol" not in stale:
        if live_vol >= cfg.vix_crisis:
            level = stricter(level, MarketRegime.CRISIS)
            why.append(f"live VIX {live_vol:.1f}")
        elif live_vol >= cfg.vix_stressed:
            level = stricter(level, MarketRegime.STRESSED)
            why.append(f"live VIX {live_vol:.1f}")

    return level, why
