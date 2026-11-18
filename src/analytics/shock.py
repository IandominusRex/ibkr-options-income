"""The shock engine: what the whole book loses in each pre-registered scenario (risk-envelope
plan Task 11; spec §3.4.1-3.4.3, rulings E4, E6, H1, H8, H10, P5, P6).

Pure (deterministic tier): no I/O, no config read, and imports only the standard library,
``src.common.envelope_types`` and ``src.analytics.black_scholes``. Callers build the
``ShockInputs`` (``src/analytics/shock_inputs.py``) and read the result.

* **Full revaluation.** Every option is repriced with Black-Scholes at the shocked spot (and, for
  P20, ten days nearer expiry); a linear delta measure would credit a covered call with about
  three times the protection it gives (§2.4).
* **Gross and net (H1, H10).** The gross measures skip every long option, whoever bought it (the
  hedge book, Claude's paper puts, a manual TWS order): no long option creates headroom. Every
  admission test reads gross. The net measures count long options and are display and harness
  only. U_ew counts stock and short-put strike, so a long option adds nothing to it either.
* **Fail closed.** A line with no IV, no spot or no beta is not valued as zero: its symbol is
  returned in ``unmeasured`` and a gate reading the result must refuse.

Units: losses are positive percent of NLV; ``uew`` is a ratio of NLV.
"""

from __future__ import annotations

import math
from collections.abc import Iterable

from src.analytics.black_scholes import bs_price
from src.common.envelope_types import BookLine, ShockInputs, ShockResult

# The pre-registered scenarios. ``index`` is the headline move handed to ``name_move``; ``other``
# is the move of every name outside the scenario's group (as beta x other); ``days`` is how far
# the clock moves before options are repriced; ``steps`` the daily steps of a path.
SCENARIOS: dict[str, dict[str, float]] = {
    # §3.4.1 (E4): SPY -10% in one step; each name by its Blume beta to SPY, a leveraged ETF at
    # leverage x its governing index's beta (P5), capped at -100%.
    "S10": {"index": -0.10, "days": 0},
    # §3.4.1: S20 is reported beside S10, same construction at SPY -20%.
    "S20": {"index": -0.20, "days": 0},
    # §3.4.3 (OR6) and P5: a one-day index gap of -10%; each name beta x -10%, a leveraged ETF at
    # leverage x -10% of its governing index.
    "G10": {"index": -0.10, "days": 0},
    # §3.4.3 and P6: a -20% index path in ten equal daily log steps; each name compounds beta x
    # each step, a leveraged ETF compounds leverage x each step; options repriced at T - 10 days.
    "P20": {"index": -0.20, "days": 10, "steps": 10},
    # §3.4.3 (H8): the regime.tech_linked names -20% (a leveraged ETF at its leverage), every
    # other name beta x -5%.
    "T20": {"index": -0.20, "other": -0.05, "days": 0},
    # §3.4.3 and P5: envelope.semis_names by beta_SMH x -30%, every other name beta x -8%.
    "S_SMH": {"index": -0.30, "other": -0.08, "days": 0},
}
VOL_BUMP = 0.10  # §3.4.1: the +10 vol-point sensitivity on S10
MOVE_FLOOR = -1.0  # a price cannot fall more than 100%

_LONG_KINDS = frozenset({"long_put", "long_call"})
_PUT_KINDS = frozenset({"short_put", "long_put"})
_SHORT_KINDS = frozenset({"short_put", "short_call"})


def _beta(table: dict[str, float], symbol: str) -> float:
    """The beta for *symbol*; KeyError when it is missing (the caller marks it unmeasured)."""
    return float(table[symbol])


def _leveraged(
    symbol: str, lev: int, gov: str | None, index_move: float, beta_of: dict[str, float]
) -> float:
    """A leveraged ETF at leverage x its governing index's beta x the move (P5). With no
    governing index on record the larger of its own measured beta move and leverage x the move
    is taken: the conservative reading."""
    if gov:
        return lev * _beta(beta_of, gov) * index_move
    return min(_beta(beta_of, symbol) * index_move, lev * index_move)


def name_move(symbol: str, index_move: float, inputs: ShockInputs, *, scenario: str) -> float:
    """The fractional price move of *symbol* in *scenario* (P5, P6), capped at -100%.

    Raises ``KeyError`` when a beta the scenario needs is missing (never a silent zero), and for
    an unknown scenario.
    """
    spec = SCENARIOS[scenario]
    sym = symbol.upper()
    lev = inputs.leverage.get(sym)
    gov = inputs.governing.get(sym) if lev else None
    if scenario in ("S10", "S20"):
        move = (
            _leveraged(sym, lev, gov, index_move, inputs.betas)
            if lev
            else _beta(inputs.betas, sym) * index_move
        )
    elif scenario == "G10":
        move = lev * index_move if lev else _beta(inputs.betas, sym) * index_move
    elif scenario == "P20":
        steps = int(spec["steps"])
        step = math.exp(math.log1p(index_move) / steps) - 1.0  # the index's daily simple step
        factor = float(lev) if lev else _beta(inputs.betas, sym)
        move = max(0.0, 1.0 + factor * step) ** steps - 1.0
    elif scenario == "T20":
        tech = sym in inputs.tech_linked or (gov is not None and gov in inputs.tech_linked)
        other = spec["other"]
        if lev:
            move = lev * index_move if tech else _leveraged(sym, lev, gov, other, inputs.betas)
        else:
            move = index_move if tech else _beta(inputs.betas, sym) * other
    elif scenario == "S_SMH":
        semis = sym in inputs.semis or (gov is not None and gov in inputs.semis)
        other = spec["other"]
        if lev:
            move = (
                _leveraged(sym, lev, gov, index_move, inputs.betas_smh)
                if semis
                else _leveraged(sym, lev, gov, other, inputs.betas)
            )
        else:
            move = (
                _beta(inputs.betas_smh, sym) * index_move
                if semis
                else _beta(inputs.betas, sym) * other
            )
    else:  # pragma: no cover - SCENARIOS[scenario] above already raised
        raise KeyError(scenario)
    return max(MOVE_FLOOR, move)


def _option_value(spot: float, strike: float, dte: int, iv: float, right: str) -> float | None:
    """Black-Scholes per share; intrinsic value at or past expiry, or at a zero spot."""
    if dte <= 0 or spot <= 0:
        return max(0.0, strike - spot) if right == "P" else max(0.0, spot - strike)
    return bs_price(spot, strike, dte, iv, right)


def line_pnl(line: BookLine, move: float, *, days: int = 0, vol_bump: float = 0.0) -> float | None:
    """The dollar P&L of *line* when its underlying moves by *move* (a fraction).

    Stock: ``qty x spot x move``. An option: ``(BS(new) - BS(now)) x 100 x signed qty``, BS(new)
    at the shocked spot, ``dte - days`` and ``iv + vol_bump``; short lines carry the minus sign.
    None (unmeasured, never zero) when the spot, or an option's strike, DTE or IV, is missing.
    """
    if line.spot is None or not line.spot > 0:
        return None
    if line.kind == "stock":
        return line.qty * line.spot * move
    if line.strike is None or not line.strike > 0 or line.dte is None:
        return None
    if line.iv is None or not line.iv > 0:
        return None
    right = "P" if line.kind in _PUT_KINDS else "C"
    now = _option_value(line.spot, line.strike, line.dte, line.iv, right)
    new = _option_value(
        line.spot * (1.0 + move), line.strike, line.dte - days, line.iv + vol_bump, right
    )
    if now is None or new is None:
        return None
    sign = -1.0 if line.kind in _SHORT_KINDS else 1.0
    return (new - now) * 100.0 * abs(line.qty) * sign


def _counted(lines: Iterable[BookLine], include_long: bool) -> Iterable[BookLine]:
    """The lines a measure counts. Gross leaves out every long option and the whole hedge book
    (risk-envelope Task 36, H1/H10): a hedge vertical's short leg is part of a net-long structure
    the Rules Engine validated, so it neither adds to nor takes from the book's headroom."""
    return (
        ln for ln in lines if include_long or (ln.kind not in _LONG_KINDS and ln.book != "hedge")
    )


def scenario_loss(
    inputs: ShockInputs,
    scenario: str,
    *,
    include_long: bool,
    vol_bump: float = 0.0,
) -> tuple[float, tuple[str, ...]]:
    """The book's loss in *scenario* as percent of NLV (positive = a loss), and the symbols it
    could not value. ``include_long=False`` is the gross measure (no long option, H1)."""
    if not inputs.nlv > 0:
        return 0.0, ("NLV",)
    spec = SCENARIOS[scenario]
    days = int(spec["days"])
    total = 0.0
    missing: set[str] = set()
    for line in _counted(inputs.lines, include_long):
        try:
            move = name_move(line.symbol, spec["index"], inputs, scenario=scenario)
        except KeyError:
            missing.add(line.symbol.upper())
            continue
        pnl = line_pnl(line, move, days=days, vol_bump=vol_bump)
        if pnl is None:
            missing.add(line.symbol.upper())
            continue
        total += pnl
    return -total / inputs.nlv * 100.0, tuple(sorted(missing))


def uew(inputs: ShockInputs) -> float:
    """U_ew (spec §3.4.2, E5): ``(sum |stock MV| x leverage + sum short-put strike x 100 x
    |contracts| x leverage) / NLV``, every book's lines included (value holdings by their
    ``book``). ITM puts count at strike; short calls and long options add nothing (H10).
    Raises ``ValueError`` when NLV is not positive."""
    if not inputs.nlv > 0:
        raise ValueError("U_ew needs a positive NLV")
    gross = 0.0
    for line in inputs.lines:
        if line.book == "hedge":
            continue  # H10: the hedge book (a vertical's short leg too) adds nothing to U_ew
        lev = float(inputs.leverage.get(line.symbol.upper(), 1))
        if line.kind == "stock":
            gross += abs(line.qty * (line.spot or 0.0)) * lev
        elif line.kind == "short_put" and line.strike:
            gross += line.strike * 100.0 * abs(line.qty) * lev
    return gross / inputs.nlv


def measure(inputs: ShockInputs) -> ShockResult:
    """Every scenario, gross and net, plus U_ew, in one result."""
    gross: dict[str, float] = {}
    net: dict[str, float] = {}
    miss_gross: set[str] = set()
    miss_net: set[str] = set()
    for name in SCENARIOS:
        g, mg = scenario_loss(inputs, name, include_long=False)
        n, mn = scenario_loss(inputs, name, include_long=True)
        gross[name], net[name] = g, n
        miss_gross.update(mg)
        miss_net.update(mn)
    g_vol, mg = scenario_loss(inputs, "S10", include_long=False, vol_bump=VOL_BUMP)
    n_vol, mn = scenario_loss(inputs, "S10", include_long=True, vol_bump=VOL_BUMP)
    miss_gross.update(mg)
    miss_net.update(mn)
    try:
        u = uew(inputs)
    except ValueError:
        u = 0.0
        miss_gross.add("NLV")
    return ShockResult(
        s10=gross["S10"],
        s20=gross["S20"],
        g10=gross["G10"],
        p20=gross["P20"],
        t20=gross["T20"],
        s_smh=gross["S_SMH"],
        s10_vol10=g_vol,
        s10_net=net["S10"],
        s20_net=net["S20"],
        g10_net=net["G10"],
        p20_net=net["P20"],
        t20_net=net["T20"],
        s_smh_net=net["S_SMH"],
        s10_vol10_net=n_vol,
        uew=u,
        unmeasured=tuple(sorted(miss_gross)),
        unmeasured_net=tuple(sorted(miss_net - miss_gross)),
    )
