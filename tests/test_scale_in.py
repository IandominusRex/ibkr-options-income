"""The scale-in ladder (Task 6): zones, name-level triggers, anchors, recovery, the loss-exit block.

Pure functions are driven with synthetic numbers and the real week-of-2026-10-13 bars
(`tests/fixtures/week_2026_10_13`); the anchor and loss-exit lookups run against a tmp database
built the way production writes it (an opening order with a snapshot; a close order without
one, whose BUY fill carries the opening order's candidate id).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pandas as pd
import pytest

from src.analytics.scale_in import (
    compute_zone,
    last_broken_support,
    name_drawdown_triggered,
    near_money_short_put,
    recovered,
)
from src.analytics.technicals import _atr14, _sma
from src.common.config import RegimeLadderCfg, get_regime_cfg
from src.common.schemas import (
    MarketRegime,
    OptionRight,
    PositionSnapshot,
    SizingContext,
)
from src.engine.regime_limits import loss_exit_reason, scale_in_reason
from src.regime.anchors import latest_anchor, loss_exits_today, recent_loss_exit
from src.regime.context import build_sizing_context
from src.storage.db import session_scope
from src.storage.models import FillRow, OrderRow
from tests.conftest import week_bars

N = MarketRegime.NORMAL
S = MarketRegime.STRESSED
X = MarketRegime.CRISIS

TODAY = date(2026, 10, 13)


def ladder() -> RegimeLadderCfg:
    return get_regime_cfg().ladder


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    import src.storage.db as dbmod
    from src.common.config import Config

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{tmp_path / 't.db'}")
    dbmod.init_db()


# --------------------------------------------------------------------------- #
# config
# --------------------------------------------------------------------------- #


def test_ladder_block_ships_with_the_documented_values():
    cfg = ladder()
    assert cfg.regimes == [S, X]
    assert cfg.min_gap_pct == {
        N: 5.0,
        MarketRegime.CAUTIOUS: 5.0,
        S: 5.0,
        X: 7.0,
    }
    assert (cfg.min_gap_atr, cfg.band_atr, cfg.broken_atr) == (1.5, 0.5, 1.0)
    assert (cfg.anchor_survival_days, cfg.name_drawdown_atr) == (5, 2.5)
    assert (cfg.name_drawdown_sessions, cfg.recovery_closes) == (10, 2)
    assert cfg.near_money_atr == 0.5
    assert cfg.loss_exit_same_day_block is True


def test_the_example_yaml_carries_every_ladder_key():
    from src.common.config import get_config

    block = get_config().risk["regime"]["ladder"]  # tests run on config/examples/risk_limits.yaml
    assert set(block) == set(RegimeLadderCfg.KEYS)


def test_ladder_cfg_key_list_matches_the_model_and_refuses_unknown_keys():
    assert set(RegimeLadderCfg.KEYS) == set(RegimeLadderCfg.model_fields)
    with pytest.raises(ValueError, match="unknown key"):
        RegimeLadderCfg(near_money_atrs=0.5)  # type: ignore[call-arg]


# --------------------------------------------------------------------------- #
# zones
# --------------------------------------------------------------------------- #


def zone(**kw: Any):
    args: dict[str, Any] = {
        "anchor": 100.0,
        "anchor_source": "order_snapshot",
        "atr": 2.0,
        "supports": [98.0, 93.0, 90.0],
        "regime": N,
        "triggers": ["near_money_put"],
        "cfg": ladder(),
    }
    args.update(kw)
    return compute_zone(**args)


def test_zone_sits_at_the_next_support_below_the_min_gap():
    z = zone()
    # gap = max(5%, 1.5 x 2 / 100 = 3%) = 5% -> ceiling 95; 98 is above it, 93 is the first support under
    assert z.support == 93.0
    assert (z.zone_low, z.zone_high) == (92.0, 94.0)
    assert z.min_gap_pct == 5.0 and z.anchor == 100.0
    assert z.triggers == ["near_money_put"] and z.bottoming_signal is False
    # a support just under the ceiling: the zone is capped at the ceiling
    capped = zone(supports=[94.8])
    assert capped.zone_high == 95.0 and capped.zone_low == pytest.approx(93.8)


def test_zone_found_when_spot_already_below_the_support():
    # anchor 100, gap ceiling 95, support 94, spot 93.5 -> zone around 94 (allowed), not the next
    # level down (90, zone 89-91, which 93.5 would be above and blocked by)
    z = zone(supports=[94.0, 90.0])
    assert z.support == 94.0 and (z.zone_low, z.zone_high) == (93.0, 95.0)
    ctx = SizingContext(regimes={"SPY": N, "QQQ": N}, scale_in={"ABC": z})
    assert scale_in_reason(ctx, "ABC", 93.5) is None
    assert scale_in_reason(ctx, "ABC", 95.0) is None  # at the top of the zone is inside it
    assert scale_in_reason(ctx, "ABC", 95.01) == "scale_in_zone_not_reached"


def test_zone_falls_back_to_the_gap_without_support():
    z = zone(supports=[])
    assert z.support is None
    assert (z.zone_low, z.zone_high) == (94.0, 95.0)  # [ceiling - 0.5 ATR, ceiling]


def test_atr_gap_wins_for_a_volatile_name():
    # SOXL-like: ATR 12 on an anchor of 145 -> 1.5 x 12 / 145 = 12.4% > 5%
    z = zone(anchor=145.0, atr=12.0, supports=[])
    assert z.min_gap_pct == pytest.approx(12.41, abs=0.01)
    assert z.zone_high == pytest.approx(145.0 * (1 - 0.124138), abs=0.01)


def test_the_crisis_gap_is_wider():
    assert zone(regime=X, atr=1.0, supports=[]).zone_high == pytest.approx(93.0)
    assert zone(regime=S, atr=1.0, supports=[]).zone_high == pytest.approx(95.0)


# --------------------------------------------------------------------------- #
# name-level triggers (real bars)
# --------------------------------------------------------------------------- #


def bars_to(symbol: str, day: str) -> pd.DataFrame:
    return week_bars(symbol).loc[:day]


def atr_of(bars: pd.DataFrame) -> float:
    value = _atr14(bars["High"], bars["Low"], bars["Close"])
    assert value is not None
    return value


def drawdown(symbol: str, day: str) -> bool:
    bars = bars_to(symbol, day)
    cfg = ladder()
    return name_drawdown_triggered(
        bars,
        atr_of(bars),
        sessions=cfg.name_drawdown_sessions,
        k_atr=cfg.name_drawdown_atr,
    )


def test_name_drawdown_soxl_triggers_by_oct_13():
    assert drawdown("SOXL", "2026-10-09") is False
    assert drawdown("SOXL", "2026-10-13") is True


def test_name_drawdown_tqqq_triggers_by_oct_14_not_oct_13():
    # Oct 13 alone is covered by the near-the-money put, not by a drawdown
    assert drawdown("TQQQ", "2026-10-13") is False
    assert drawdown("TQQQ", "2026-10-14") is True


def put(strike: float, qty: float = -10, symbol: str = "TQQQ", right=OptionRight.PUT):
    return PositionSnapshot(
        symbol=f"{symbol} 261023{'P' if right == OptionRight.PUT else 'C'}",
        sec_type="OPT",
        position=qty,
        avg_cost=1.0,
        right=right,
        strike=strike,
        expiry=date(2026, 10, 23),
        underlying=symbol,
    )


def test_near_money_short_put_triggers_just_out_of_the_money():
    # 78P held, spot 78.12, ATR 3.4 -> True (78.12 <= 78 + 1.7); spot 80.0 -> False
    held = [put(78.0)]
    assert near_money_short_put(held, "TQQQ", 78.12, 3.4, k_atr=0.5) is True
    assert near_money_short_put(held, "TQQQ", 80.0, 3.4, k_atr=0.5) is False
    # a long put, a call and another name's put are not it
    assert near_money_short_put([put(78.0, qty=5)], "TQQQ", 78.12, 3.4, k_atr=0.5) is False
    assert (
        near_money_short_put([put(78.0, right=OptionRight.CALL)], "TQQQ", 78.12, 3.4, k_atr=0.5)
        is False
    )
    assert near_money_short_put([put(78.0, symbol="SOXL")], "TQQQ", 78.12, 3.4, k_atr=0.5) is False
    # deep in the money is also near/through it
    assert near_money_short_put(held, "TQQQ", 70.0, 3.4, k_atr=0.5) is True


# --------------------------------------------------------------------------- #
# recovery
# --------------------------------------------------------------------------- #


def test_recovery_ignores_closes_before_the_anchor():
    # TQQQ: the anchor 78.12 was filled on 2026-10-13; the closes of 10-09 (81.28) and 10-12
    # (79.61) are above both sma20 and the anchor, but they came BEFORE the lot
    bars = bars_to("TQQQ", "2026-10-12")
    sma20 = _sma(bars["Close"], 20)
    assert sma20 is not None and sma20 < 79.61
    assert recovered(bars, sma20=sma20, level=78.12, closes=2, after=date.min) is True
    assert recovered(bars, sma20=sma20, level=78.12, closes=2, after=date(2026, 10, 13)) is False
    # one close after the anchor is not two
    assert recovered(bars, sma20=sma20, level=78.12, closes=2, after=date(2026, 10, 9)) is False
    assert recovered(bars, sma20=sma20, level=78.12, closes=1, after=date(2026, 10, 9)) is True


def test_recovery_needs_both_the_average_and_the_level():
    bars = bars_to("TQQQ", "2026-10-12")
    sma20 = _sma(bars["Close"], 20)
    assert recovered(bars, sma20=sma20, level=81.0, closes=2, after=date.min) is False
    assert recovered(bars, sma20=None, level=70.0, closes=2, after=date.min) is False
    assert recovered(bars.iloc[:0], sma20=sma20, level=70.0, closes=2, after=date.min) is False


def test_last_broken_support_is_found_only_after_the_anchor():
    bars = bars_to("TQQQ", "2026-10-19")
    atr = atr_of(bars)
    # the 10-14 and 10-16 selloff closed through the late-September lows
    found = last_broken_support(
        bars, anchor=81.79, after=date(2026, 10, 7), atr=atr, broken_atr=1.0
    )
    assert found is not None and found < 81.79
    # nothing had broken between 10-07 and the close of 10-12
    early = bars_to("TQQQ", "2026-10-12")
    assert (
        last_broken_support(
            early, anchor=81.79, after=date(2026, 10, 7), atr=atr_of(early), broken_atr=1.0
        )
        is None
    )


# --------------------------------------------------------------------------- #
# the database lookups: anchors and loss exits
# --------------------------------------------------------------------------- #


def utc(y: int, m: int, d: int, hh: int, mm: int = 0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=UTC)


_ID = [0]


def seed_lot(
    session,
    *,
    symbol: str,
    strike: float,
    filled_at: datetime,
    spot: float | None,
    contracts: int = 1,
    expiry: date = date(2026, 10, 30),
    strategy: str = "cash_secured_put",
    candidate_id: str | None = None,
    state: str = "filled",
) -> tuple[OrderRow, str]:
    """An opening order with its frozen snapshot and one SELL fill, the way production writes it."""
    _ID[0] += 1
    cid = candidate_id or f"cand{_ID[0]:04d}"
    snap: dict[str, Any] = {
        "candidate_id": cid,
        "strategy": strategy,
        "underlying": symbol,
        "right": "P",
        "strike": strike,
        "expiry": expiry.isoformat(),
        "contracts": contracts,
    }
    if spot is not None:
        snap["ideal"] = {"spot": spot}
    row = OrderRow(
        candidate_id=cid,
        state=state,
        filled_qty=float(contracts),
        snapshot=snap,
        created_at=filled_at.replace(tzinfo=None),
    )
    session.add(row)
    session.flush()
    session.add(
        FillRow(
            order_id=row.id,
            candidate_id=cid,
            action="SELL",
            filled_qty=float(contracts),
            avg_price=1.0,
            filled_at=filled_at.replace(tzinfo=None),
        )
    )
    session.flush()
    return row, cid


def seed_close(
    session,
    *,
    opening_cid: str,
    symbol: str,
    at: datetime,
    reason: str | None,
    qty: float = 1.0,
    close_cid: str | None = None,
    fill_cid: str | None = None,
) -> OrderRow:
    """A buy-to-close: the close order has NO snapshot; its BUY fill carries the opening cid."""
    _ID[0] += 1
    close = OrderRow(
        candidate_id=close_cid or f"close:{symbol}:20261030:100:P",
        state="filled",
        filled_qty=qty,
        snapshot=None,
        close_reason=reason,
        created_at=at.replace(tzinfo=None),
    )
    session.add(close)
    session.flush()
    session.add(
        FillRow(
            order_id=close.id,
            candidate_id=fill_cid if fill_cid is not None else opening_cid,
            action="BUY",
            filled_qty=qty,
            avg_price=2.0,
            close_reason=reason,
            filled_at=at.replace(tzinfo=None),
        )
    )
    session.flush()
    return close


def test_anchor_prefers_the_order_snapshot_spot():
    with session_scope() as s:
        seed_lot(s, symbol="TQQQ", strike=78.0, filled_at=utc(2026, 10, 7, 13, 51), spot=81.79)
        anchor = latest_anchor(s, "TQQQ", [], survival_days=5, today=date(2026, 10, 13))
    assert anchor == (81.79, "order_snapshot", date(2026, 10, 7))


def test_anchor_falls_back_to_the_close_on_the_fill_date():
    from src.storage.models import PriceHistoryRow

    with session_scope() as s:
        s.add(
            PriceHistoryRow(
                symbol="TQQQ", obs_date=date(2026, 10, 7), open=82, high=84, low=81, close=83.62
            )
        )
        seed_lot(s, symbol="TQQQ", strike=78.0, filled_at=utc(2026, 10, 7, 13, 51), spot=None)
        anchor = latest_anchor(s, "TQQQ", [], survival_days=5, today=date(2026, 10, 13))
    assert anchor == (83.62, "price_history", date(2026, 10, 7))


def test_the_most_recent_lot_is_the_anchor_and_other_names_are_ignored():
    with session_scope() as s:
        seed_lot(s, symbol="TQQQ", strike=78.0, filled_at=utc(2026, 10, 7, 13, 51), spot=81.79)
        seed_lot(s, symbol="TQQQ", strike=75.0, filled_at=utc(2026, 10, 9, 15, 0), spot=80.0)
        seed_lot(s, symbol="SOXL", strike=100.0, filled_at=utc(2026, 10, 12, 15, 0), spot=122.9)
        anchor = latest_anchor(s, "TQQQ", [], survival_days=5, today=date(2026, 10, 13))
    assert anchor == (80.0, "order_snapshot", date(2026, 10, 9))


def test_anchor_survives_a_loss_exit_for_survival_days():
    with session_scope() as s:
        _, cid = seed_lot(
            s, symbol="SOXL", strike=130.0, filled_at=utc(2026, 10, 8, 17, 48), spot=140.19
        )
        seed_close(
            s, opening_cid=cid, symbol="SOXL", at=utc(2026, 10, 13, 13, 34), reason="loss_exit"
        )
        kept = latest_anchor(s, "SOXL", [], survival_days=5, today=date(2026, 10, 13))
        still = latest_anchor(s, "SOXL", [], survival_days=5, today=date(2026, 10, 18))
        gone = latest_anchor(s, "SOXL", [], survival_days=5, today=date(2026, 10, 19))
    assert kept == (140.19, "order_snapshot", date(2026, 10, 8))
    assert still == (140.19, "order_snapshot", date(2026, 10, 8))
    assert gone is None  # closed on 10-13: more than five days ago


def test_an_expired_lot_survives_for_survival_days_after_expiry():
    with session_scope() as s:
        seed_lot(
            s,
            symbol="SOXL",
            strike=130.0,
            filled_at=utc(2026, 10, 1, 17, 0),
            spot=140.0,
            expiry=date(2026, 10, 9),
        )
        assert latest_anchor(s, "SOXL", [], survival_days=5, today=date(2026, 10, 14)) is not None
        assert latest_anchor(s, "SOXL", [], survival_days=5, today=date(2026, 10, 15)) is None


def test_assigned_shares_are_a_lot():
    shares = PositionSnapshot(symbol="SOXL", sec_type="STK", position=200, avg_cost=131.5)
    with session_scope() as s:
        anchor = latest_anchor(s, "SOXL", [shares], survival_days=5, today=date(2026, 10, 13))
    assert anchor == (131.5, "shares", date.min)


def test_a_short_put_with_no_system_fill_anchors_at_the_higher_of_strike_and_spot():
    held = [put(78.0, symbol="TQQQ")]
    with session_scope() as s:
        anchor = latest_anchor(
            s, "TQQQ", held, survival_days=5, today=date(2026, 10, 13), spot=79.5
        )
        low_spot = latest_anchor(
            s, "TQQQ", held, survival_days=5, today=date(2026, 10, 13), spot=77.0
        )
        none = latest_anchor(s, "TQQQ", [], survival_days=5, today=date(2026, 10, 13), spot=79.5)
    assert anchor == (79.5, "position", date.min)
    assert low_spot == (78.0, "position", date.min)
    assert none is None


def test_roll_fills_never_move_the_anchor():
    with session_scope() as s:
        _, cid = seed_lot(
            s, symbol="GOOGL", strike=350.0, filled_at=utc(2026, 10, 7, 18, 19), spot=348.0
        )
        # the roll: a ROLL-strategy opening order (its own snapshot) and a roll-reason BUY fill
        seed_lot(
            s,
            symbol="GOOGL",
            strike=345.0,
            filled_at=utc(2026, 10, 15, 18, 28),
            spot=349.0,
            strategy="roll",
        )
        seed_close(s, opening_cid=cid, symbol="GOOGL", at=utc(2026, 10, 15, 18, 30), reason="roll")
        anchor = latest_anchor(s, "GOOGL", [], survival_days=5, today=date(2026, 10, 16))
    assert anchor == (348.0, "order_snapshot", date(2026, 10, 7))


def test_a_cancelled_or_unfilled_order_is_not_a_lot():
    with session_scope() as s:
        row, _ = seed_lot(
            s, symbol="TQQQ", strike=70.0, filled_at=utc(2026, 10, 13, 15, 32), spot=77.8
        )
        row.filled_qty = 0.0
        row.state = "cancelled"
        assert latest_anchor(s, "TQQQ", [], survival_days=5, today=TODAY) is None


def test_loss_exit_blocks_the_name_for_the_rest_of_the_day():
    # SOXL loss exit at 13:34 UTC on 10-13 -> a SOXL CSP at 13:52 gets "loss_exit_cooldown";
    # the next day it does not
    with session_scope() as s:
        _, cid = seed_lot(
            s, symbol="SOXL", strike=130.0, filled_at=utc(2026, 10, 8, 17, 48), spot=140.19
        )
        seed_close(
            s, opening_cid=cid, symbol="SOXL", at=utc(2026, 10, 13, 13, 34), reason="loss_exit"
        )
        same_day = build_sizing_context(
            now=utc(2026, 10, 13, 13, 52), session=s, symbols=["SOXL"], bars={}
        )
        next_day = build_sizing_context(
            now=utc(2026, 10, 14, 13, 52), session=s, symbols=["SOXL"], bars={}
        )
        assert loss_exits_today(s, today=date(2026, 10, 13)) == ["SOXL"]
        assert loss_exits_today(s, today=date(2026, 10, 14)) == []
    assert same_day is not None and next_day is not None
    assert same_day.loss_exit_today == ["SOXL"]
    assert loss_exit_reason(same_day, "SOXL") == "loss_exit_cooldown"
    assert loss_exit_reason(same_day, "TQQQ") is None
    assert next_day.loss_exit_today == []
    assert loss_exit_reason(next_day, "SOXL") is None


def test_loss_exit_block_can_be_switched_off(monkeypatch):
    ctx = SizingContext(regimes={"SPY": N, "QQQ": N}, loss_exit_today=["SOXL"])
    assert loss_exit_reason(ctx, "SOXL") == "loss_exit_cooldown"
    from src.common.config import get_config

    cfg = get_config()
    risk = dict(cfg.risk)
    regime = dict(risk["regime"])
    regime["ladder"] = {**regime["ladder"], "loss_exit_same_day_block": False}
    risk["regime"] = regime
    monkeypatch.setattr(cfg, "risk", risk)
    assert loss_exit_reason(ctx, "SOXL") is None
    assert loss_exit_reason(None, "SOXL") is None


def test_loss_exit_cooldown_survives_regime_off():
    # applies whenever the context is present, like the name triggers
    ctx = SizingContext(regimes={"SPY": N, "QQQ": N}, suspended=True, loss_exit_today=["SOXL"])
    assert loss_exit_reason(ctx, "SOXL") == "loss_exit_cooldown"


def test_recent_loss_exit_triggers_within_survival_days_only():
    with session_scope() as s:
        _, cid = seed_lot(
            s, symbol="SOXL", strike=130.0, filled_at=utc(2026, 10, 8, 17, 48), spot=140.19
        )
        seed_close(
            s, opening_cid=cid, symbol="SOXL", at=utc(2026, 10, 13, 13, 34), reason="loss_exit"
        )
        # a profit take on another name is not a loss exit
        _, other = seed_lot(
            s, symbol="AAPL", strike=330.0, filled_at=utc(2026, 10, 9, 16, 22), spot=334.0
        )
        seed_close(
            s, opening_cid=other, symbol="AAPL", at=utc(2026, 10, 12, 13, 45), reason="profit_take"
        )
        assert recent_loss_exit(s, "SOXL", days=5, today=date(2026, 10, 13)) is True
        assert recent_loss_exit(s, "SOXL", days=5, today=date(2026, 10, 18)) is True
        assert recent_loss_exit(s, "SOXL", days=5, today=date(2026, 10, 19)) is False
        assert recent_loss_exit(s, "AAPL", days=5, today=date(2026, 10, 13)) is False
        assert recent_loss_exit(s, "TQQQ", days=5, today=date(2026, 10, 13)) is False


def test_recent_loss_exit_falls_back_to_the_close_candidate_id():
    with session_scope() as s:
        # no opening order with a snapshot exists for this fill's candidate id (an older row)
        seed_close(
            s,
            opening_cid="gone",
            symbol="TQQQ",
            at=utc(2026, 10, 14, 15, 15),
            reason="loss_exit",
            close_cid="close:TQQQ:20261016:78:P",
        )
        assert recent_loss_exit(s, "TQQQ", days=5, today=date(2026, 10, 14)) is True
        assert loss_exits_today(s, today=date(2026, 10, 14)) == ["TQQQ"]
        # and a fill whose own candidate id is the close id
        seed_close(
            s,
            opening_cid="x",
            symbol="NVDA",
            at=utc(2026, 10, 14, 16, 0),
            reason="loss_exit",
            close_cid="close:NVDA:20261016:200:P",
            fill_cid="close:NVDA:20261016:200:P",
        )
        assert sorted(loss_exits_today(s, today=date(2026, 10, 14))) == ["NVDA", "TQQQ"]


def test_a_loss_exit_after_midnight_utc_belongs_to_the_et_day():
    # 02:30 UTC on 10-14 is 22:30 ET on 10-13
    with session_scope() as s:
        _, cid = seed_lot(
            s, symbol="SOXL", strike=130.0, filled_at=utc(2026, 10, 8, 17, 48), spot=140.19
        )
        seed_close(
            s, opening_cid=cid, symbol="SOXL", at=utc(2026, 10, 14, 2, 30), reason="loss_exit"
        )
        assert loss_exits_today(s, today=date(2026, 10, 13)) == ["SOXL"]
        assert loss_exits_today(s, today=date(2026, 10, 14)) == []


# --------------------------------------------------------------------------- #
# the context builder: triggers, zones, recovery
# --------------------------------------------------------------------------- #


def bars_before(symbol: str, day: date) -> pd.DataFrame:
    """Completed daily bars strictly before *day* (what a scan on *day* can see)."""
    return week_bars(symbol).loc[: pd.Timestamp(day) - pd.Timedelta(days=1)]


def seed_tqqq_78p(session) -> None:
    seed_lot(
        session,
        symbol="TQQQ",
        strike=78.0,
        filled_at=utc(2026, 10, 7, 13, 51),
        spot=81.79,
        contracts=10,
        expiry=date(2026, 10, 16),
    )


def test_name_triggers_filled_even_without_an_anchor():
    # SOXL has fallen hard but the book holds no lot: no zone (the first lot is free), but the
    # trigger is recorded for the leveraged tier
    with session_scope() as s:
        ctx = build_sizing_context(
            now=utc(2026, 10, 14, 14, 0),
            session=s,
            symbols=["SOXL"],
            positions=[],
            bars={"SOXL": bars_before("SOXL", date(2026, 10, 14))},
        )
    assert ctx is not None
    assert ctx.name_triggers["SOXL"] == ["name_drawdown"]
    assert "SOXL" not in ctx.scale_in
    from src.engine.regime_limits import leverage_tier

    assert leverage_tier(ctx, "SOXL") == "stressed"


def test_a_quiet_name_has_no_trigger_and_no_zone():
    with session_scope() as s:
        ctx = build_sizing_context(
            now=utc(2026, 10, 9, 14, 0),
            session=s,
            symbols=["TQQQ"],
            positions=[],
            bars={"TQQQ": bars_before("TQQQ", date(2026, 10, 9))},
        )
    assert ctx is not None
    assert ctx.name_triggers.get("TQQQ", []) == []
    assert ctx.scale_in == {}


def test_a_near_money_put_gives_a_zone_below_the_last_lot():
    # 2026-10-13 16:02 UTC: the 78P x10 is held, TQQQ at 78.12 (spot given), anchor = the 78P's 81.79
    with session_scope() as s:
        seed_tqqq_78p(s)
        ctx = build_sizing_context(
            now=utc(2026, 10, 13, 16, 2),
            session=s,
            symbols=["TQQQ"],
            positions=[put(78.0, qty=-10)],
            bars={"TQQQ": bars_before("TQQQ", date(2026, 10, 13))},
            spots={"TQQQ": 78.12},
        )
    assert ctx is not None
    z = ctx.scale_in["TQQQ"]
    assert z.triggers == ["near_money_put"]
    assert z.anchor == 81.79 and z.anchor_source == "order_snapshot"
    assert z.zone_high < 81.79 * (1 - 0.05) + 1e-9  # at least the 5% gap below the last lot
    assert 78.12 > z.zone_high  # the price has not reached it
    assert scale_in_reason(ctx, "TQQQ", 78.12) == "scale_in_zone_not_reached"
    assert ctx.name_triggers["TQQQ"] == ["near_money_put"]


def test_recovery_lifts_a_name_trigger():
    # A lot filled in the dip (idx 49, 92.0), then two closes above both sma20 and the anchor
    idx = pd.bdate_range("2026-08-03", periods=60)
    close = pd.Series([100.0] * 40 + [92.0] * 10 + [103.0, 104.0] + [105.0] * 8, index=idx)
    bars = pd.DataFrame(
        {"Open": close, "High": close + 1, "Low": close - 1, "Close": close, "Volume": 1.0}
    )
    fill_day = idx[49]

    def at(day: pd.Timestamp) -> datetime:
        return datetime(day.year, day.month, day.day, 15, 0, tzinfo=UTC)

    with session_scope() as s:
        seed_lot(
            s,
            symbol="ABC",
            strike=95.0,
            filled_at=at(fill_day),
            spot=92.0,
            contracts=2,
            expiry=(fill_day + pd.Timedelta(days=20)).date(),
        )
        held = [put(95.0, qty=-2, symbol="ABC")]
        # bars through idx 51: two closes (103, 104) after the lot -> recovered, ladder lifted
        lifted = build_sizing_context(
            now=at(idx[52]),
            session=s,
            symbols=["ABC"],
            positions=held,
            bars={"ABC": bars.loc[: idx[51]]},
            spots={"ABC": 96.0},  # still a near-the-money put at this spot
        )
        # bars through idx 50: only ONE close after the lot -> still under the ladder
        not_yet = build_sizing_context(
            now=at(idx[51]),
            session=s,
            symbols=["ABC"],
            positions=held,
            bars={"ABC": bars.loc[: idx[50]]},
            spots={"ABC": 96.0},
        )
    assert lifted is not None and not_yet is not None
    assert "ABC" not in lifted.scale_in
    assert lifted.name_triggers.get("ABC", []) == []
    assert "ABC" in not_yet.scale_in
    assert not_yet.name_triggers["ABC"] == ["near_money_put"]


# --------------------------------------------------------------------------- #
# the send-time context and the tier
# --------------------------------------------------------------------------- #


def test_the_send_time_context_carries_todays_loss_exits_and_fetches_no_bars():
    """A loss exit since the card was made must reach the send-time re-gate (a cheap query)."""
    from src.execution.approval import _send_context

    now = utc(2026, 10, 14, 17, 9)
    with session_scope() as s:
        _, cid = seed_lot(
            s, symbol="TQQQ", strike=78.0, filled_at=utc(2026, 10, 7, 13, 51), spot=81.79
        )
        seed_close(
            s, opening_cid=cid, symbol="TQQQ", at=utc(2026, 10, 14, 15, 15), reason="loss_exit"
        )
    ctx = _send_context(now, [put(78.0, qty=-10)])
    assert ctx is not None and ctx.for_send is True
    assert ctx.loss_exit_today == ["TQQQ"]
    assert ctx.scale_in == {}  # the card's own zone, frozen in its snapshot, is what is re-checked


LADDER_MODULES = (
    "src/analytics/support_levels.py",
    "src/analytics/scale_in.py",
    "src/regime/anchors.py",
    "src/regime/context.py",
    "src/engine/regime_limits.py",
)


def test_ladder_modules_stay_in_the_deterministic_tier():
    """They feed the Rules Engine's gate: no enrichment tier, reasoning layer, reporting or API."""
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    forbidden = (
        "src.analytics.market_conditions",
        "src.analytics.sentiment",
        "src.analytics.sector_context",
        "src.claude",
        "src.news",
        "src.spreads_ai",
        "src.reporting",
        "src.api",
    )
    for rel in LADDER_MODULES:
        tree = ast.parse((root / rel).read_text(encoding="utf-8"))
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
                imported.extend(f"{node.module}.{a.name}" for a in node.names)
            elif isinstance(node, ast.Import):
                imported.extend(a.name for a in node.names)
        bad = [m for m in imported if any(m == f or m.startswith(f + ".") for f in forbidden)]
        assert not bad, f"{rel} reaches outside the deterministic tier: {bad}"
