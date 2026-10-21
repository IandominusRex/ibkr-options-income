"""The pure regime limits (Task 3) and the SizingContext builder.

`src/engine/regime_limits.py` is the one place the regime, the leveraged-ETF ceiling, the daily
count and the guaranteed floor are turned into numbers; the sizer and the gate both call it,
so these tests pin the arithmetic both rely on.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta

import pytest

from src.common.config import get_config
from src.common.schemas import (
    IndexRegime,
    MarketRegime,
    RegimeInputs,
    RegimeState,
    SizingContext,
)
from src.engine import regime_limits as rl
from src.engine.capital import Caps, scale_caps

N = MarketRegime.NORMAL
C = MarketRegime.CAUTIOUS
S = MarketRegime.STRESSED
X = MarketRegime.CRISIS

TECH = ["QQQ", "TQQQ", "SOXL", "TSLL", "NVDA"]
LEVERAGE = {"TQQQ": 3, "SOXL": 3, "TSLL": 2}


def ctx(
    spy: MarketRegime = N,
    qqq: MarketRegime = N,
    *,
    suspended: bool = False,
    leverage: dict[str, int] | None = None,
    triggers: dict[str, list[str]] | None = None,
    opens: dict[str, int] | None = None,
    floors: dict[str, int] | None = None,
) -> SizingContext:
    return SizingContext(
        regimes={"SPY": spy, "QQQ": qqq},
        tech_linked=TECH,
        suspended=suspended,
        leverage=LEVERAGE if leverage is None else leverage,
        name_triggers=triggers or {},
        csp_opens_counted=opens or {},
        floor_lots_counted=floors or {},
    )


def set_risk(monkeypatch, **blocks) -> None:
    """Replace whole top-level blocks of the risk dict (e.g. ``regime={...}``)."""
    cfg = get_config()
    risk = dict(cfg.risk)
    risk.update(blocks)
    monkeypatch.setattr(cfg, "risk", risk)


# --------------------------------------------------------------------------- #
# active / multipliers / per-trade ceiling
# --------------------------------------------------------------------------- #


def test_inactive_context_changes_nothing(monkeypatch):
    stressed = ctx(S, S)
    assert rl.active(stressed) is True
    for off in (None, ctx(S, S, suspended=True)):
        assert rl.active(off) is False
        assert rl.multipliers(off, "BAC") == (1.0, 1.0)
        assert rl.per_trade_cap(off, "BAC", 10) == 10
        assert rl.daily_limit(off, "BAC") is None
        assert rl.floor_left(off, "BAC", {}) == 0
    set_risk(monkeypatch, regime={"enabled": False})
    assert rl.active(stressed) is False
    assert rl.multipliers(stressed, "BAC") == (1.0, 1.0)
    assert rl.per_trade_cap(stressed, "BAC", 10) == 10


def test_per_trade_cap_stressed_turns_10_into_3():
    assert rl.per_trade_cap(ctx(S, S), "BAC", 10) == 3
    assert rl.per_trade_cap(ctx(C, C), "BAC", 10) == 6


def test_per_trade_cap_crisis_keeps_one_lot():
    assert rl.per_trade_cap(ctx(X, X), "BAC", 10) == 1  # floor(10 x 0.1)


def test_tech_linked_name_uses_the_stricter_regime():
    c = ctx(spy=N, qqq=S)
    assert rl.name_regime(c, "TQQQ") == (S, "QQQ")
    assert rl.name_regime(c, "BAC") == (N, "SPY")
    # a tie reports QQQ, the index a tech-linked name is bucketed under
    assert rl.name_regime(ctx(S, S), "NVDA") == (S, "QQQ")
    # SPY stricter than QQQ: a tech-linked name still takes the stricter of the two
    d = ctx(spy=X, qqq=C)
    assert rl.name_regime(d, "NVDA") == (X, "SPY")
    assert rl.name_regime(d, "BAC") == (X, "SPY")


def test_book_multiplier_follows_spy_ticker_multiplier_follows_the_name():
    c = ctx(spy=N, qqq=S)
    assert rl.multipliers(c, "TQQQ") == (
        0.4,
        1.0,
    )  # (ticker, book): the name is stressed, SPY is not
    assert rl.multipliers(c, "BAC") == (1.0, 1.0)
    d = ctx(spy=S, qqq=N)
    assert rl.multipliers(d, "BAC") == (0.4, 0.4)
    assert rl.multipliers(d, "TQQQ") == (
        0.4,
        0.4,
    )  # stricter of the two for the name; SPY for the book


def test_daily_limit_by_regime():
    assert rl.daily_limit(ctx(N, N), "BAC") is None
    assert rl.daily_limit(ctx(C, N), "BAC") == 6
    assert rl.daily_limit(ctx(S, N), "BAC") == 3
    assert rl.daily_limit(ctx(X, N), "BAC") == 1
    # a tech-linked name follows the stricter regime
    assert rl.daily_limit(ctx(N, S), "TQQQ") == 3


def test_governing_index_buckets_tech_linked_names_under_qqq():
    c = ctx()
    assert rl.governing_index(c, "TQQQ") == "QQQ"
    assert rl.governing_index(c, "BAC") == "SPY"


def test_scale_caps_scales_only_the_csp_budgets():
    caps = Caps(
        deployable_cash=320_000.0,
        max_csp_collateral=320_000.0,
        max_ticker_risk=25_000.0,
        max_sector_risk=125_000.0,
        max_ticker_collateral=50_000.0,
        max_large_positions=2,
        large_ticker_collateral=125_000.0,
    )
    scaled = scale_caps(caps, ticker=0.4, book=0.1)
    assert scaled.max_csp_collateral == pytest.approx(32_000.0)
    assert scaled.max_ticker_risk == pytest.approx(10_000.0)
    assert scaled.max_sector_risk == pytest.approx(50_000.0)
    # the collateral caps, the cash and the slot count never move with the regime
    assert scaled.max_ticker_collateral == caps.max_ticker_collateral
    assert scaled.large_ticker_collateral == caps.large_ticker_collateral
    assert scaled.deployable_cash == caps.deployable_cash
    assert scaled.max_large_positions == caps.max_large_positions
    assert caps.max_csp_collateral == 320_000.0  # frozen original untouched


# --------------------------------------------------------------------------- #
# the leveraged-ETF ceiling (ruling 35)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("sym", "regime", "triggers", "expected"),
    [
        ("TQQQ", N, [], 6),  # calm 0.6
        ("TQQQ", N, ["recent_loss_exit"], 3),  # stressed 0.3 via a name trigger
        ("TQQQ", C, [], 1),  # stressed: floor(10 x 0.6 x 0.3) = 1
        ("TQQQ", S, [], 1),
        ("TQQQ", X, [], 1),
        ("TSLL", N, [], 8),
        ("TSLL", N, ["name_drawdown"], 5),
        ("TSLL", C, [], 3),
        ("BAC", N, [], 10),
        ("BAC", S, [], 3),
    ],
)
def test_per_trade_cap_with_the_leveraged_tier(sym, regime, triggers, expected):
    c = ctx(regime, regime, triggers={sym: triggers} if triggers else {})
    assert rl.per_trade_cap(c, sym, 10) == expected


def test_leverage_tier_uses_the_stricter_index_for_tech_linked():
    c = ctx(spy=N, qqq=C)
    assert rl.leverage_tier(c, "TQQQ") == "stressed"  # QQQ is cautious
    assert rl.leverage_tier(ctx(N, N), "TQQQ") == "calm"
    assert rl.leverage_tier(ctx(N, N, triggers={"TQQQ": ["near_money_put"]}), "TQQQ") == "stressed"
    # a trigger on another name does not stress this one
    assert rl.leverage_tier(ctx(N, N, triggers={"SOXL": ["near_money_put"]}), "TQQQ") == "calm"


def test_leveraged_cap_applies_when_the_regime_is_suspended_or_disabled(monkeypatch):
    assert rl.per_trade_cap(ctx(N, N, suspended=True), "TQQQ", 10) == 6
    assert rl.per_trade_cap(ctx(S, S, suspended=True), "TQQQ", 10) == 6  # regime reads as normal
    trig = {"TQQQ": ["recent_loss_exit"]}
    assert rl.per_trade_cap(ctx(N, N, suspended=True, triggers=trig), "TQQQ", 10) == 3
    set_risk(monkeypatch, regime={"enabled": False})
    assert rl.per_trade_cap(ctx(N, N), "TQQQ", 10) == 6
    assert rl.per_trade_cap(ctx(N, N, triggers=trig), "TQQQ", 10) == 3


def test_leveraged_sizing_has_its_own_switch(monkeypatch):
    set_risk(monkeypatch, leveraged_sizing={"enabled": False})
    assert rl.per_trade_cap(ctx(N, N), "TQQQ", 10) == 10
    assert rl.per_trade_cap(ctx(S, S), "TQQQ", 10) == 3  # the regime ceiling is unaffected


def test_leveraged_cap_is_zero_when_the_regime_ceiling_is_zero(monkeypatch):
    set_risk(monkeypatch, regime={"csp": {"per_trade_fraction": {"crisis": 0.0}}})
    assert rl.per_trade_cap(ctx(X, X), "TQQQ", 10) == 0
    assert rl.per_trade_cap(ctx(X, X), "BAC", 10) == 0


def test_unmapped_leveraged_etf_is_treated_as_3x(tmp_path, monkeypatch, caplog):
    from src.regime.context import build_sizing_context

    _db(tmp_path, monkeypatch)
    monkeypatch.setattr("src.regime.context._WARNED_UNMAPPED", set())
    cfg = get_config()
    monkeypatch.setattr(
        cfg,
        "universe",
        {**cfg.universe, "leveraged_etfs": ["TQQQ", "TSLL", "NEWX"]},
    )
    from src.storage.db import session_scope

    with caplog.at_level(logging.WARNING, logger="src.regime.context"):
        with session_scope() as s:
            built = build_sizing_context(now=datetime(2026, 10, 21, 15, tzinfo=UTC), session=s)
            built2 = build_sizing_context(now=datetime(2026, 10, 21, 15, tzinfo=UTC), session=s)
    assert built is not None and built2 is not None
    assert built.leverage == {"TQQQ": 3, "TSLL": 2, "NEWX": 3}
    warnings = [r for r in caplog.records if "NEWX" in r.getMessage()]
    assert len(warnings) == 1  # said once, not on every scan


def test_ceiling_kind_names_the_binding_factor():
    assert rl.ceiling_kind(ctx(N, N), "TQQQ", 10, 10) == "leveraged_ceiling"
    assert rl.ceiling_kind(ctx(S, S), "BAC", 10, 10) == "regime_ceiling"
    assert rl.ceiling_kind(ctx(N, N), "BAC", 10, 10) is None
    # not binding when the capital-fitted size is already under the ceiling
    assert rl.ceiling_kind(ctx(N, N), "TQQQ", 10, 4) is None
    assert rl.ceiling_kind(ctx(S, S), "BAC", 10, 2) is None
    # a stressed leveraged name: the leveraged factor is what takes it below the regime ceiling
    assert rl.ceiling_kind(ctx(C, C), "TQQQ", 10, 10) == "leveraged_ceiling"


def test_floor_left_counts_sent_and_batch_lots():
    c = ctx(S, S, floors={"QQQ": 1})
    assert rl.floor_left(c, "TQQQ", {}) == 0  # stressed floor is 1; one already sent today
    assert rl.floor_left(c, "BAC", {}) == 1  # SPY's bucket is separate
    assert rl.floor_left(c, "BAC", {"SPY": 1}) == 0  # one accepted earlier in this batch
    d = ctx(C, C)
    assert rl.floor_left(d, "BAC", {}) == 2  # cautious floor
    assert rl.floor_left(d, "BAC", {"SPY": 1}) == 1
    assert rl.floor_left(ctx(N, N), "BAC", {}) == 0  # normal has no floor (no limit to exceed)


def test_sizing_note_carries_the_numbers_the_card_and_gate_need():
    note = rl.sizing_note(ctx(N, S), "TQQQ", pre=10, hard_max=10)
    assert note is not None
    assert note.pre_regime_contracts == 10
    assert note.regime == S and note.regime_index == "QQQ"
    assert note.per_trade_cap == 1  # floor(10 x 0.3 x 0.3) = 0 -> at least one lot
    assert note.budget_multiplier == 0.4
    assert note.leverage == 3 and note.leverage_tier == "stressed"
    assert note.ceiling_kind == "leveraged_ceiling"
    assert note.floor_lot is False
    plain = rl.sizing_note(ctx(S, S), "BAC", pre=10, hard_max=10)
    assert plain is not None and plain.leverage is None and plain.leverage_tier is None
    assert plain.ceiling_kind == "regime_ceiling"
    assert rl.sizing_note(None, "BAC", pre=10, hard_max=10) is None


# --------------------------------------------------------------------------- #
# build_sizing_context
# --------------------------------------------------------------------------- #


def _db(tmp_path, monkeypatch):
    import src.storage.db as dbmod
    from src.common.config import Config

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{tmp_path / 't.db'}")
    dbmod.init_db()


def _seed_regime(spy: MarketRegime, qqq: MarketRegime) -> None:
    from src.storage.regime_state import save_regime_state

    today = date(2026, 10, 21)

    def ir(index: str, r: MarketRegime) -> IndexRegime:
        return IndexRegime(
            index=index,  # type: ignore[arg-type]
            base=r,
            base_date=today,
            since=today,
            base_since=today,
            effective=r,
            inputs=RegimeInputs(),
        )

    save_regime_state(
        RegimeState(
            as_of=datetime(2026, 10, 21, 15, tzinfo=UTC), spy=ir("SPY", spy), qqq=ir("QQQ", qqq)
        )
    )


NOW = datetime(2026, 10, 21, 15, 0, tzinfo=UTC)  # Wed 11:00 ET


def _order(session, cid, state, strategy, underlying, *, floor_lot=False, created=NOW, close=False):
    from src.storage.models import OrderRow

    # Every real CSP snapshot carries a sizing note; only a floor lot has floor_lot true.
    snapshot = (
        None
        if close
        else {"strategy": strategy, "underlying": underlying, "sizing": {"floor_lot": floor_lot}}
    )
    session.add(OrderRow(candidate_id=cid, state=state, snapshot=snapshot, created_at=created))


def test_context_reads_the_persisted_regimes(tmp_path, monkeypatch):
    from src.regime.context import build_sizing_context
    from src.storage.db import session_scope
    from src.storage.regime_state import suspend_regime

    _db(tmp_path, monkeypatch)
    _seed_regime(C, S)
    with session_scope() as s:
        built = build_sizing_context(now=NOW, session=s)
    assert built is not None
    assert built.regimes == {"SPY": C, "QQQ": S}
    assert built.suspended is False
    assert "TQQQ" in built.tech_linked
    assert built.leverage["TQQQ"] == 3 and built.leverage["TSLL"] == 2
    suspend_regime(date(2026, 10, 21))
    with session_scope() as s:
        assert build_sizing_context(now=NOW, session=s).suspended is True  # type: ignore[union-attr]


def test_context_with_no_regime_state_reads_normal(tmp_path, monkeypatch):
    from src.regime.context import build_sizing_context
    from src.storage.db import session_scope

    _db(tmp_path, monkeypatch)
    with session_scope() as s:
        built = build_sizing_context(now=NOW, session=s)
    assert built is not None and built.regimes == {"SPY": N, "QQQ": N}


def test_context_is_none_when_every_switch_is_off(tmp_path, monkeypatch):
    from src.regime.context import build_sizing_context
    from src.storage.db import session_scope

    _db(tmp_path, monkeypatch)
    set_risk(monkeypatch, regime={"enabled": False}, leveraged_sizing={"enabled": False})
    with session_scope() as s:
        assert build_sizing_context(now=NOW, session=s) is None
    # either switch alone is enough to want a context
    set_risk(monkeypatch, regime={"enabled": False}, leveraged_sizing={"enabled": True})
    with session_scope() as s:
        assert build_sizing_context(now=NOW, session=s) is not None


def test_opens_counted_per_governing_index_and_state(tmp_path, monkeypatch):
    from src.regime.context import build_sizing_context
    from src.storage.db import session_scope

    _db(tmp_path, monkeypatch)
    with session_scope() as s:
        csp = "cash_secured_put"
        _order(s, "a", "filled", csp, "TQQQ")  # QQQ bucket
        _order(s, "b", "submitted", csp, "NVDA")  # QQQ bucket
        _order(s, "c", "partial", csp, "BAC")  # SPY bucket
        _order(s, "d", "queued", csp, "BAC")  # counted at decision time, not at send time
        _order(s, "e", "cancelled", csp, "BAC")  # never opened
        _order(s, "f", "filled", "covered_call", "BAC")  # not a CSP
        _order(s, "g", "filled", "roll", "BAC")
        _order(s, "close:BAC:1", "filled", csp, "BAC", close=True)  # a close, no snapshot
        _order(s, "close:BAC:2", "filled", csp, "BAC")  # a close-prefixed id is never an open
        _order(s, "h", "filled", csp, "BAC", created=NOW - timedelta(days=1))  # yesterday
        _order(s, "i", "filled", csp, "BAC", created=NOW + timedelta(days=1))  # tomorrow (ET)
    with session_scope() as s:
        scan = build_sizing_context(now=NOW, session=s)
        send = build_sizing_context(now=NOW, session=s, for_send=True)
    assert scan is not None and send is not None
    assert scan.csp_opens_counted == {"QQQ": 2, "SPY": 2}
    assert send.csp_opens_counted == {"QQQ": 2, "SPY": 1}  # the queued order is the batch itself
    assert scan.for_send is False and send.for_send is True


def test_floor_lots_counted_from_the_snapshot_flag(tmp_path, monkeypatch):
    from src.regime.context import build_sizing_context
    from src.storage.db import session_scope

    _db(tmp_path, monkeypatch)
    with session_scope() as s:
        csp = "cash_secured_put"
        _order(s, "a", "filled", csp, "TQQQ", floor_lot=True)
        _order(s, "b", "filled", csp, "TQQQ")
        _order(s, "c", "submitted", csp, "BAC", floor_lot=True)
        _order(s, "d", "cancelled", csp, "BAC", floor_lot=True)
    with session_scope() as s:
        built = build_sizing_context(now=NOW, session=s)
    assert built is not None
    assert built.floor_lots_counted == {"QQQ": 1, "SPY": 1}
