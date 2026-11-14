"""The pick menu's economics — what Claude is shown about each gate-approved spread.

Pure and deterministic: no IBKR, no I/O, no LLM. Every number on the menu comes from here; the
prompt (src/spreads_ai/prompts.py) only formats them. Costs follow the cost standard
(risk-envelope Task 5) and are per share and round trip: two legs opened and two closed, each
paying the measured crossing plus its margin and the per-contract commission plus exchange fee
(SPY settles in shares, so every spread is closed, never left to expire). The executor's
simulated fills pay the same per-leg amounts (``slippage_per_leg``, ``cost_per_contract``).
"""

from __future__ import annotations

import string

from src.common.config import SpreadsCfg
from src.common.schemas import GexLevels, SpreadCandidate, SpreadMenuItem, SpreadMenuPosition

LETTERS = string.ascii_uppercase  # 2 sides x menu_size stays well under 26


def slippage_per_leg(cfg: SpreadsCfg) -> float:
    """Per share, per leg: the measured median crossing plus the stated margin."""
    x = cfg.execution
    return x.shadow_slippage_per_leg + x.slippage_margin_per_leg


def fee_per_contract(cfg: SpreadsCfg, instrument: str | None = None) -> float | None:
    """The exchange fee per contract per leg of *instrument* (default: the traded class), or
    None while it has not been filled from IBKR's schedule."""
    return cfg.execution.exchange_fees.get(instrument or cfg.trading_class)


def cost_per_contract(cfg: SpreadsCfg) -> float:
    """USD per contract per leg: IBKR's commission plus the exchange fee. Raises ValueError when
    the fee is unknown (config load refuses an enabled book in that state)."""
    fee = fee_per_contract(cfg)
    if fee is None:
        raise ValueError(f"no exchange fee for {cfg.trading_class}: the cost standard is unknown")
    return cfg.execution.commission_per_contract + fee


def round_trip_cost(cfg: SpreadsCfg) -> float:
    """Per share: 4 × (crossing + margin) + 4 × (commission + fee) / 100."""
    return round(4 * slippage_per_leg(cfg) + 4 * cost_per_contract(cfg) / 100.0, 4)


def breakeven(win: float, loss: float) -> float | None:
    """The win rate at which wins of *win* and losses of *loss* (per share) break even."""
    if win <= 0 or loss <= 0:
        return None
    return round(loss / (win + loss), 4)


def _distance(c: SpreadCandidate, spot: float) -> float:
    return spot - c.short_strike if c.side == "put" else c.short_strike - spot


def build_menu(
    items: list[tuple[SpreadCandidate, SpreadMenuPosition, int]],
    levels: GexLevels,
    cfg: SpreadsCfg,
) -> list[SpreadMenuItem]:
    """Gate-approved (candidate, position, contracts) → lettered items. Puts first, then calls;
    within a side, closest to spot first."""
    cost = round_trip_cost(cfg)
    ex = cfg.exits
    ordered = sorted(
        items, key=lambda it: (0 if it[0].side == "put" else 1, _distance(it[0], levels.spot))
    )
    out: list[SpreadMenuItem] = []
    for letter, (c, position, contracts) in zip(LETTERS, ordered, strict=False):
        credit = c.credit_mid
        dist = _distance(c, levels.spot)
        wall = levels.put_wall if c.side == "put" else levels.call_wall
        beyond = (
            None
            if wall is None
            else (wall - c.short_strike if c.side == "put" else c.short_strike - wall)
        )
        flip = levels.flip
        past_flip = (
            None
            if flip is None
            else (flip - c.short_strike if c.side == "put" else c.short_strike - flip)
        )
        full_loss = c.width - credit
        nominal_loss = min(full_loss, (ex.stop_debit_multiple - 1.0) * credit)
        out.append(
            SpreadMenuItem(
                letter=letter,
                position=position,
                candidate=c,
                contracts=contracts,
                credit_after_costs=round(credit - cost, 4),
                cost_pct_of_credit=round(cost / credit, 4) if credit > 0 else None,
                max_loss_per_contract_usd=round(c.max_loss_per_contract, 2),
                dist_spot_pts=round(dist, 2),
                dist_em_multiple=(
                    round(dist / levels.expected_move, 2) if levels.expected_move else None
                ),
                beyond_wall_pts=None if beyond is None else round(beyond, 2),
                dist_flip_pts=None if past_flip is None else round(past_flip, 2),
                be_full_loss=breakeven(credit - cost, full_loss + cost),
                be_nominal_exits=breakeven(
                    ex.profit_take_pct / 100.0 * credit - cost, nominal_loss + cost
                ),
            )
        )
    return out
