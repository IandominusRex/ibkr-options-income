"""Safeguard 2 (spec section 7): the market-reaction check on stories judged noise.

The triage may call a story noise and be wrong. After the reaction window has passed, this check
measures what the market did since the story first appeared (reusing ``reaction.move_after`` on
1-minute bars): for a ticker story, that ticker's move **net of what the index explains** (its
beta times SPY's move over the same window); for a macro story, the larger of SPY's and QQQ's
move. Above the configured threshold the story is promoted to pile 2 and posted late, with the
exact copy ``render.late_post_line`` holds ("Cause not confirmed": the check proves a move, never
a cause).

Promotions are capped per hour and each story is promoted once, so a single index move cannot
promote every dismissed story at once. Everything here is deterministic Python: no model is
called, and no verdict is changed by a model.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

import numpy as np
import pandas as pd
from sqlalchemy import func, or_, select

from src.common.config import NewsTriageCfg, get_config
from src.data.factory import get_price_provider
from src.news.reaction import move_after
from src.news.store.models import NewsClusterRow, StoryTriageRow
from src.news.store.queries import aware_utc, naive_utc
from src.news.store.session import news_session

log = logging.getLogger(__name__)

_INDEX_SYMBOLS = ("SPY", "QQQ")
_BAND = timedelta(
    minutes=30
)  # how long after its window closes (or its judgement) a row is checked
_MIN_BETA_RETURNS = 30
_MAX_TICKERS = 5  # tickers examined per cluster (a cluster can name many)


@dataclass
class Promotion:
    cluster_id: int
    move_pct: float  # signed: the index move, or the ticker's move net of beta x SPY
    basis: Literal["index", "ticker"]
    symbol: str  # the index or ticker the move was measured on


def beta_vs_spy(symbol: str, *, sessions: int = 60) -> float | None:
    """The slope of *symbol*'s daily returns on SPY's over the last *sessions* sessions (OLS).

    None when either history is missing or fewer than 30 sessions overlap: a beta from a short
    window is noise, and the caller must then decide what to assume.
    """
    try:
        provider = get_price_provider()
        lookback = int(sessions * 1.6) + 10  # calendar days that hold `sessions` sessions
        closes = {
            sym: provider.get_ohlcv(sym, lookback_days=lookback) for sym in ("SPY", symbol.upper())
        }
    except Exception:
        log.debug("noise check: no history to estimate the beta of %s", symbol, exc_info=True)
        return None
    series: dict[str, pd.Series] = {}
    for sym, df in closes.items():
        if df is None or df.empty or "Close" not in df:
            return None
        series[sym] = df["Close"].dropna().astype(float).pct_change().dropna()
    both = pd.concat([series["SPY"].rename("spy"), series[symbol.upper()].rename("sym")], axis=1)
    both = both.dropna().iloc[-sessions:]
    if len(both) < _MIN_BETA_RETURNS:
        return None
    var = float(np.var(both["spy"], ddof=1))
    if var <= 0:
        return None
    return float(np.cov(both["spy"], both["sym"], ddof=1)[0, 1] / var)


def find_promotions(
    now: datetime,
    *,
    bars_for: Callable[[str], pd.DataFrame],
    beta_for: Callable[[str], float | None],
) -> list[Promotion]:
    """Promote judged-noise stories the market has since moved against; return what was promoted.

    A row is considered once the reaction window since the story first appeared has completed
    and while it is recent: its first appearance, or its judgement (the triage runs a few times
    a day, so a story is usually judged long after it first appeared), is within the last
    ``promote_window_min + 30`` minutes. Each promoted row becomes pile 2 with ``promoted_at``
    and ``promoted_move_pct`` set; at most ``max_promotions_per_hour`` less those already made in
    the last hour are promoted, strongest move first. A story whose bars or beta-adjustment
    inputs are missing is left alone.
    """
    cfg = get_config().news.triage
    window = timedelta(minutes=cfg.promote_window_min)
    recent_from = naive_utc(now - window - _BAND)  # not older than this (by appearance or verdict)
    window_done = naive_utc(now - window)  # the reaction window has closed by now

    bars_cache: dict[str, pd.DataFrame] = {}

    def bars(symbol: str) -> pd.DataFrame:
        if symbol not in bars_cache:
            try:
                bars_cache[symbol] = bars_for(symbol)
            except Exception:
                log.debug("noise check: no bars for %s", symbol, exc_info=True)
                bars_cache[symbol] = pd.DataFrame()
        return bars_cache[symbol]

    def move(symbol: str, since: datetime) -> float | None:
        return move_after(bars(symbol), since, window_min=cfg.promote_window_min, now=now)

    with news_session() as s:
        made = (
            s.scalar(
                select(func.count(StoryTriageRow.id)).where(
                    StoryTriageRow.promoted_at >= naive_utc(now - timedelta(hours=1))
                )
            )
            or 0
        )
        room = cfg.max_promotions_per_hour - made
        if room <= 0:
            return []
        rows = s.execute(
            select(StoryTriageRow, NewsClusterRow)
            .join(NewsClusterRow, NewsClusterRow.id == StoryTriageRow.cluster_id)
            .where(
                StoryTriageRow.pile == 3,
                StoryTriageRow.promoted_at.is_(None),
                NewsClusterRow.first_seen < window_done,
                or_(
                    NewsClusterRow.first_seen >= recent_from,
                    StoryTriageRow.judged_at >= recent_from,
                ),
            )
            .order_by(StoryTriageRow.id)
        ).all()

        found: list[tuple[StoryTriageRow, Promotion]] = []
        for row, cluster in rows:
            since = aware_utc(cluster.first_seen)
            promo = _measure(cluster, since, cfg, move, beta_for)
            if promo is not None:
                found.append((row, promo))
        found.sort(key=lambda rp: (-abs(rp[1].move_pct), rp[1].cluster_id))
        chosen = found[:room]
        for row, promo in chosen:
            row.pile = 2
            row.promoted_at = naive_utc(now)
            row.promoted_move_pct = promo.move_pct
            row.reason = (
                f"promoted late: {promo.move_pct:+.1f}% ({promo.basis}); was: {row.reason}"[:160]
            )
        return [promo for _row, promo in chosen]


def _measure(
    cluster: NewsClusterRow,
    since: datetime,
    cfg: NewsTriageCfg,
    move: Callable[[str, datetime], float | None],
    beta_for: Callable[[str], float | None],
) -> Promotion | None:
    """The reaction to one story, or None when it does not clear its threshold (or cannot be
    measured). A ticker story is judged on its own name; any other on the two indices."""
    if cluster.category == "ticker" and cluster.tickers:
        spy = move("SPY", since)
        if spy is None:
            return None  # the index move cannot be netted out: do not guess
        best: tuple[float, str] | None = None
        for sym in [t for t in cluster.tickers if t not in _INDEX_SYMBOLS][:_MAX_TICKERS]:
            raw = move(sym, since)
            if raw is None:
                continue
            beta = beta_for(sym)
            residual = raw - (1.0 if beta is None else beta) * spy
            if best is None or abs(residual) > abs(best[0]):
                best = (residual, sym)
        if best is not None and abs(best[0]) >= cfg.promote_ticker_residual_pct:
            return Promotion(cluster.id, best[0], "ticker", best[1])
        return None
    moves = [(m, sym) for sym in _INDEX_SYMBOLS if (m := move(sym, since)) is not None]
    if not moves:
        return None
    biggest = max(moves, key=lambda ms: abs(ms[0]))
    if abs(biggest[0]) >= cfg.promote_index_move_pct:
        return Promotion(cluster.id, biggest[0], "index", biggest[1])
    return None
