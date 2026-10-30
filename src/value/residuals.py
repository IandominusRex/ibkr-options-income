"""The sector-ETF residual model behind re-evaluation triggers 1 and 2 (spec §7.1). Pure: no I/O.

A name's daily return net of what its sector ETF explains: ``e = r - (alpha + beta x r_etf)``, with
alpha and beta fitted by least squares over the ``beta_sessions`` aligned returns before the day
(the day itself excluded) and the residual's standard deviation over the last ``sigma_sessions``
of them. Trigger 1 reads the day's residual in those units (``z``); trigger 2 reads the residual
summed over ``drift_sessions`` sessions, scaled by ``sigma x sqrt(n)`` from a fit that ends where
the drift window starts. Fewer than ``min_history_sessions`` aligned returns leaves both None:
the raw move is the backstop then.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from statistics import fmean, stdev

from src.common.config import ValueReevaluationCfg


@dataclass(frozen=True, slots=True)
class Move:
    day: date
    ret: float | None  # the name's close over its previous close, minus one
    z: float | None  # the day's residual in residual standard deviations
    drift_z: float | None  # the residual summed over drift_sessions, in the same units
    beta: float | None


@dataclass(frozen=True, slots=True)
class _Fit:
    alpha: float
    beta: float
    sigma: float


def daily_returns(closes: list[tuple[date, float]]) -> dict[date, float]:
    """Close over the previous close, minus one, keyed by the later date."""
    out: dict[date, float] = {}
    for (_, prev), (day, close) in zip(closes, closes[1:], strict=False):
        if prev > 0:
            out[day] = close / prev - 1.0
    return out


def _fit(xs: list[float], ys: list[float], cfg: ValueReevaluationCfg) -> _Fit | None:
    if len(xs) < cfg.min_history_sessions:
        return None
    mx, my = fmean(xs), fmean(ys)
    var = sum((x - mx) ** 2 for x in xs)
    if var <= 0:
        return None
    beta = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / var
    alpha = my - beta * mx
    tail = list(zip(xs, ys, strict=True))[-cfg.sigma_sessions :]
    sigma = stdev([y - alpha - beta * x for x, y in tail])
    return _Fit(alpha, beta, sigma) if sigma > 0 else None


def moves(
    name: list[tuple[date, float]],
    etf: list[tuple[date, float]],
    days: list[date],
    cfg: ValueReevaluationCfg,
) -> dict[date, Move]:
    """Each of *days*' move for a name (ascending ``(date, close)`` lists, the ETF's likewise).
    A day the ETF has no bar for keeps its raw return with no z."""
    rn, re = daily_returns(name), daily_returns(etf)
    aligned = sorted(d for d in rn if d in re)
    index = {d: i for i, d in enumerate(aligned)}

    def fit_before(i: int) -> _Fit | None:
        window = aligned[max(0, i - cfg.beta_sessions) : i]
        return _fit([re[d] for d in window], [rn[d] for d in window], cfg)

    def resid(f: _Fit, d: date) -> float:
        return rn[d] - f.alpha - f.beta * re[d]

    out: dict[date, Move] = {}
    for day in days:
        i = index.get(day)
        if i is None:
            out[day] = Move(day, rn.get(day), None, None, None)
            continue
        f = fit_before(i)
        z = None if f is None else resid(f, day) / f.sigma
        start = i - cfg.drift_sessions + 1
        drift = None
        if start >= 0:
            g = fit_before(start)
            if g is not None:
                total = sum(resid(g, d) for d in aligned[start : i + 1])
                drift = total / (g.sigma * math.sqrt(cfg.drift_sessions))
        out[day] = Move(day, rn[day], z, drift, None if f is None else f.beta)
    return out
