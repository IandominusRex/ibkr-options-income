"""The shock engine's inputs (risk-envelope plan Task 12; spec §3.4.1, rulings P5, H7, C7).

* ``betas`` — Blume betas (0.67 β + 0.33) from up to ``envelope.beta_sessions`` (250) daily log
  returns of ``price_history`` against SPY (or SMH); fewer than ``beta_min_sessions`` (120) common
  sessions means ``beta_fallback`` (1.5) and the symbol is flagged. SOXX, which has a short history
  in the store, borrows ``soxx_proxy``'s (SMH) beta until it has its own.
* ``stored_ivs`` — the latest **unflagged** ``iv_history`` row per symbol (decimal), through
  ``iv_history.latest_iv``: the display snapshot's IV, labelled as stored.
* ``build_inputs`` — positions -> ``BookLine``s. ``get_positions()`` already drops value-book stock
  and the spreads legs (C7); the value book's holdings come in once from ``value_by_name``
  (``books.value_exposure().by_name``) and the hedge book's marks from ``hedge_lines``. An option's
  IV is looked up by its ``con_id`` when the caller hands live IV (``live_iv.live_option_ivs``),
  else by its underlying (stored IV): a live map never falls back to stored IV, so a missing live
  IV is unmeasured (H7, Q4).

Deterministic tier: reads ``price_history``, ``iv_history`` and config; imports no enrichment.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Iterable, Mapping
from datetime import date

from src.common.config import (
    get_config,
    get_envelope_cfg,
    get_leveraged_sizing_cfg,
    get_regime_cfg,
)
from src.common.envelope_types import BookLine, ShockInputs
from src.common.market_hours import today_et
from src.common.schemas import OptionRight, PositionSnapshot
from src.storage.iv_history import latest_iv
from src.storage.price_history import load_bars

log = logging.getLogger(__name__)

_BLUME_WEIGHT = 0.67
_BLUME_PRIOR = 0.33
_UNMAPPED_LEVERAGE = 3  # a leveraged ETF missing from the operator's map: the strictest
_NO_LES: Mapping[str, float] = {}  # build_inputs' default: no LES share line (replays, tests)


def _log_returns(symbol: str, sessions: int) -> dict[date, float]:
    bars = load_bars(symbol, limit=sessions + 1)
    out: dict[date, float] = {}
    for prev, cur in zip(bars, bars[1:], strict=False):
        if prev.close > 0 and cur.close > 0:
            out[cur.obs_date] = math.log(cur.close / prev.close)
    return out


def _blume(
    sym_ret: dict[date, float], bench: dict[date, float], sessions: int, minimum: int
) -> float | None:
    days = sorted(set(sym_ret) & set(bench))[-sessions:]
    if len(days) < minimum:
        return None
    xs = [bench[d] for d in days]
    ys = [sym_ret[d] for d in days]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    var = sum((x - mx) ** 2 for x in xs)
    if var <= 0:
        return None
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    return _BLUME_WEIGHT * (cov / var) + _BLUME_PRIOR


def betas(symbols: Iterable[str], *, vs: str = "SPY") -> tuple[dict[str, float], set[str]]:
    """Blume betas of *symbols* to *vs* (P5) and the set flagged as on the fallback."""
    cfg = get_envelope_cfg()
    bench = _log_returns(vs, cfg.beta_sessions)
    cache: dict[str, float | None] = {}

    def own(sym: str) -> float | None:
        if sym not in cache:
            cache[sym] = _blume(
                _log_returns(sym, cfg.beta_sessions),
                bench,
                cfg.beta_sessions,
                cfg.beta_min_sessions,
            )
        return cache[sym]

    out: dict[str, float] = {}
    flagged: set[str] = set()
    for raw in symbols:
        sym = raw.upper()
        if sym in out:
            continue
        b = own(sym)
        if b is None and sym == "SOXX" and cfg.soxx_proxy:
            b = own(cfg.soxx_proxy.upper())
            if b is not None:
                log.info("envelope: SOXX has too little history, using %s's beta", cfg.soxx_proxy)
        if b is None:
            b = cfg.beta_fallback
            flagged.add(sym)
        out[sym] = b
    if flagged:
        log.warning(
            "envelope: beta fallback %.2f (vs %s) for %s", cfg.beta_fallback, vs, sorted(flagged)
        )
    return out, flagged


def stored_ivs(symbols: Iterable[str]) -> dict[str, float]:
    """The latest unflagged stored IV per symbol (decimal); symbols without one are left out."""
    out: dict[str, float] = {}
    for raw in symbols:
        iv = latest_iv(raw.upper())
        if iv is not None and iv > 0:
            out[raw.upper()] = float(iv)
    return out


def leverage_map() -> dict[str, int]:
    """Every known leveraged ETF -> its daily leverage: the operator's ``leveraged_sizing.leverage``
    map plus any ``universe.leveraged_etfs`` name missing from it (3x). Physical leverage, so it
    does not depend on ``leveraged_sizing.enabled`` or on the name still being in the universe."""
    out = {k.upper(): int(v) for k, v in get_leveraged_sizing_cfg().leverage.items()}
    for raw in get_config().universe.get("leveraged_etfs") or []:
        out.setdefault(str(raw).upper(), _UNMAPPED_LEVERAGE)
    return out


def _latest_close(symbol: str) -> float | None:
    bars = load_bars(symbol, limit=1)
    return bars[-1].close if bars and bars[-1].close > 0 else None


def _positive(v: float | None) -> float | None:
    return v if v is not None and v > 0 else None


def build_inputs(
    positions: list[PositionSnapshot],
    *,
    nlv: float,
    value_by_name: Mapping[str, float],
    ivs: Mapping[int, float | None] | Mapping[str, float],
    hedge_lines: Iterable[BookLine] = (),
    les_by_name: Mapping[str, float] | None = _NO_LES,
    spots: Mapping[str, float] | None = None,
    beta_map: Mapping[str, float] | None = None,
    beta_smh_map: Mapping[str, float] | None = None,
    today: date | None = None,
) -> ShockInputs:
    """The book as ``ShockInputs``.

    A spot comes from *spots* (the scan's probes), else the held stock's mark, else the latest
    stored close; none at all leaves the line unmeasured. *beta_map* / *beta_smh_map* skip the
    price-history read (tests, replays).

    *les_by_name* (risk-envelope Task 32a) is the LES share book's market value per ETF
    (``books.les_by_name_for_envelope``): ``get_positions()`` drops LES shares from the wheel's
    view, so they come back here once, as ``book="les"`` stock lines that the shock engine moves
    at leverage x the governing index's beta. None means the LES book could not be read: an
    unmeasurable ``LES`` line is added, so the whole measurement reads unmeasured (fail closed).
    """
    day = today or today_et()
    spots_in = {k.upper(): v for k, v in (spots or {}).items() if v and v > 0}
    held: dict[str, float] = {}
    for p in positions:
        if p.sec_type == "STK" and p.position:
            mark = _positive(p.market_price) or (
                _positive(abs(p.market_value or 0.0) / abs(p.position)) if p.market_value else None
            )
            if mark:
                held[(p.underlying or p.symbol).upper()] = mark
    resolved: dict[str, float | None] = {}

    def spot_of(sym: str) -> float | None:
        if sym not in resolved:
            resolved[sym] = spots_in.get(sym) or held.get(sym) or _latest_close(sym)
        return resolved[sym]

    lines: list[BookLine] = []
    for p in positions:
        sym = (p.underlying or p.symbol).upper()
        if p.sec_type == "STK":
            lines.append(
                BookLine(symbol=sym, kind="stock", qty=float(p.position), spot=spot_of(sym) or 0.0)
            )
            continue
        if p.sec_type != "OPT" or p.right is None or not p.position:
            continue
        short = p.position < 0
        if p.right == OptionRight.PUT:
            kind = "short_put" if short else "long_put"
        else:
            kind = "short_call" if short else "long_call"
        iv = ivs.get(p.con_id) if p.con_id is not None and p.con_id in ivs else ivs.get(sym)  # type: ignore[call-overload]
        lines.append(
            BookLine(
                symbol=sym,
                kind=kind,  # type: ignore[arg-type]
                qty=abs(float(p.position)),
                spot=spot_of(sym) or 0.0,
                strike=p.strike,
                dte=(p.expiry - day).days if p.expiry is not None else None,
                iv=float(iv) if iv is not None else None,
                con_id=p.con_id,
            )
        )
    for raw, mv in value_by_name.items():
        if not mv:
            continue
        sym = raw.upper()
        spot = spot_of(sym)
        # Stock is linear: with no price on record the line is one unit at its market value.
        qty, px = (mv / spot, spot) if spot else (1.0, float(mv))
        lines.append(BookLine(symbol=sym, kind="stock", qty=qty, spot=px, book="value"))
    if les_by_name is None:
        lines.append(BookLine(symbol="LES", kind="stock", qty=0.0, spot=0.0, book="les"))
    else:
        for raw, mv in les_by_name.items():
            if not mv:
                continue
            sym = raw.upper()
            spot = spot_of(sym)
            qty, px = (mv / spot, spot) if spot else (1.0, float(mv))
            lines.append(BookLine(symbol=sym, kind="stock", qty=qty, spot=px, book="les"))
    lines.extend(hedge_lines)

    cfg = get_envelope_cfg()
    lev = leverage_map()
    governing = {k.upper(): v.upper() for k, v in cfg.governing.items()}
    wanted = {
        ln.symbol.upper() for ln in lines if not (ln.book == "les" and ln.symbol == "LES")
    }  # the unreadable-LES marker needs no beta
    wanted |= {governing[s] for s in wanted if s in governing}
    b = dict(beta_map) if beta_map is not None else betas(sorted(wanted))[0]
    b_smh = dict(beta_smh_map) if beta_smh_map is not None else betas(sorted(wanted), vs="SMH")[0]
    return ShockInputs(
        lines=tuple(lines),
        betas=b,
        betas_smh=b_smh,
        leverage=lev,
        governing=governing,
        tech_linked=frozenset(s.upper() for s in get_regime_cfg().tech_linked),
        semis=frozenset(s.upper() for s in cfg.semis_names),
        nlv=float(nlv),
    )


def hedge_lines(today: date | None = None) -> tuple[BookLine, ...]:
    """The hedge book's open legs as ``book="hedge"`` lines (risk-envelope Task 36, code fact C7):
    ``get_positions()`` drops hedge contracts, so they come back here once, for the **net**
    measures. Gross and U_ew skip every ``hedge`` line (H1, H10). Each leg takes the newest
    captured spot and IV of its contract (``hedge_view.leg_quotes``); a leg never captured has no
    IV and is named in ``unmeasured_net`` only. Empty when the hedge book cannot be read."""
    from src.common import hedge_view

    day = today or today_et()
    book = hedge_view.open_hedges() or []
    quotes = hedge_view.leg_quotes([leg.con_id for h in book for leg in h.legs if leg.con_id]) or {}
    out: list[BookLine] = []
    for h in book:
        if h.contracts <= 0:
            continue
        for leg in h.legs:
            q = quotes.get(leg.con_id or -1, {})
            out.append(
                BookLine(
                    symbol=h.instrument,
                    kind="long_put" if leg.action == "BUY" else "short_put",
                    qty=float(h.contracts),
                    spot=float(q.get("spot") or 0.0),
                    strike=leg.strike,
                    dte=(leg.expiry - day).days,
                    iv=float(q["iv"]) if q.get("iv") else None,
                    book="hedge",
                    con_id=leg.con_id,
                )
            )
    return tuple(out)
