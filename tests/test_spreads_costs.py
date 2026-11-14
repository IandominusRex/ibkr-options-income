"""The spreads cost standard (risk-envelope Task 5, spec §3.2f and §2.3).

One measured crossing plus a stated margin per leg, IBKR's commission plus the exchange fee per
contract per leg, four legs a round trip. Every simulated fill and every number Claude reads
about costs comes from it.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from src.common.config import get_config
from src.common.schemas import GexLevels, SpreadCandidate, SpreadVerdict
from src.spreads.menu import breakeven, build_menu, fee_per_contract, round_trip_cost

NOW = datetime(2026, 10, 7, 14, 30, tzinfo=UTC)
_BASE = get_config().spreads


def _cfg(**execution):
    return _BASE.model_copy(update={"execution": _BASE.execution.model_copy(update=execution)})


def test_the_shipped_standard_is_the_measured_crossing_plus_a_margin() -> None:
    x = _BASE.execution
    assert (x.shadow_slippage_per_leg, x.slippage_margin_per_leg) == (0.01, 0.01)
    assert x.commission_per_contract == 0.65
    assert x.exchange_fees["SPY"] == 0.0


def test_round_trip_cost_uses_crossing_and_fees() -> None:
    cfg = _cfg(
        shadow_slippage_per_leg=0.01,
        slippage_margin_per_leg=0.01,
        commission_per_contract=0.65,
        exchange_fees={"SPY": 0.0, "SPXW": 0.50, "XSP": None},
    )
    # 4 legs × ($0.01 crossing + $0.01 margin) + 4 × ($0.65 + $0.00) / 100 shares
    assert round_trip_cost(cfg) == pytest.approx(0.08 + 0.026)
    spxw = cfg.model_copy(update={"trading_class": "SPXW"})
    assert fee_per_contract(spxw) == 0.50
    assert round_trip_cost(spxw) == pytest.approx(0.08 + 4 * (0.65 + 0.50) / 100)
    xsp = cfg.model_copy(update={"trading_class": "XSP"})
    assert fee_per_contract(xsp) is None  # not filled from IBKR's schedule yet
    with pytest.raises(ValueError, match="exchange fee"):
        round_trip_cost(xsp)


def test_breakeven_is_recomputed_from_the_cost_standard() -> None:
    cfg = _cfg(shadow_slippage_per_leg=0.01, slippage_margin_per_leg=0.01)
    c = SpreadCandidate(
        spread_id="s1",
        side="put",
        expiry=date(2026, 10, 7),
        short_strike=679.0,
        long_strike=674.0,
        width=5.0,
        credit_mid=0.30,
        credit_natural=0.29,
        short_delta=-0.10,
        spot=690.0,
        quote_time=NOW,
    )
    levels = GexLevels(as_of=NOW, spot=690.0, net_gex=1e9, regime="positive", expected_move=6.0)
    (item,) = build_menu([(c, "baseline", 3)], levels, cfg)
    cost = round_trip_cost(cfg)
    ex = cfg.exits
    nominal = min(5.0 - 0.30, (ex.stop_debit_multiple - 1.0) * 0.30)
    assert item.be_nominal_exits == breakeven(
        ex.profit_take_pct / 100 * 0.30 - cost, nominal + cost
    )
    assert item.credit_after_costs == pytest.approx(0.30 - cost)
    # A wider margin moves the break-even Claude reads: it is recomputed, not stored.
    wide = _cfg(shadow_slippage_per_leg=0.01, slippage_margin_per_leg=0.015)
    (wider,) = build_menu([(c, "baseline", 3)], levels, wide)
    assert wider.be_nominal_exits is not None and item.be_nominal_exits is not None
    assert wider.be_nominal_exits > item.be_nominal_exits


def test_a_shadow_fill_pays_the_standard_on_each_leg() -> None:
    import asyncio

    from src.spreads.executor import SpreadExecutor

    cfg = _cfg(
        shadow_slippage_per_leg=0.01,
        slippage_margin_per_leg=0.01,
        commission_per_contract=0.65,
        exchange_fees={"SPY": 0.10},
    ).model_copy(update={"mode": "shadow"})
    c = SpreadCandidate(
        spread_id="s1",
        side="put",
        expiry=date(2026, 10, 7),
        short_strike=679.0,
        long_strike=674.0,
        width=5.0,
        credit_mid=0.60,
        credit_natural=0.58,
        spot=690.0,
        quote_time=NOW,
    )
    ex = SpreadExecutor(None, None, cfg)  # type: ignore[arg-type]
    fill = asyncio.run(
        ex.open(c, 3, lambda _: SpreadVerdict(spread_id="s1", approved=True, contracts=3))
    )
    assert fill.price == pytest.approx(0.60 - 2 * 0.02)  # two legs, crossing + margin each
    assert fill.commission == pytest.approx(2 * 3 * (0.65 + 0.10))


def _seed_candidates(st, crossings: list[float]) -> None:
    for i, gap in enumerate(crossings):
        c = SpreadCandidate(
            spread_id=f"c{i}",
            side="put",
            expiry=date(2026, 10, 7),
            short_strike=679.0,
            long_strike=674.0,
            width=5.0,
            credit_mid=0.40,
            credit_natural=round(0.40 - gap, 4),
            spot=690.0,
            quote_time=NOW,
        )
        st.record_candidate(
            c, SpreadVerdict(spread_id=c.spread_id, approved=False), "positive", NOW
        )


def test_the_cost_report_measures_the_median_crossing(tmp_path, monkeypatch, capsys) -> None:
    import src.spreads.store as st
    from scripts import spreads_costs

    db = tmp_path / "spreads.db"
    monkeypatch.setattr(st, "_engine", None)
    monkeypatch.setattr(st, "_SessionLocal", None)
    monkeypatch.setattr(st, "_resolve_url", lambda: f"sqlite:///{db}")
    st.init_spreads_db()
    _seed_candidates(st, [0.01] * 8 + [0.02, 0.05])
    # One paper spread filled at $0.34 a leg of commission (2 legs × 2 contracts = $1.36).
    pos = SpreadCandidate(
        spread_id="p1",
        side="put",
        expiry=date(2026, 10, 7),
        short_strike=679.0,
        long_strike=674.0,
        width=5.0,
        credit_mid=0.6,
        credit_natural=0.59,
        spot=690.0,
        quote_time=NOW,
    )
    st.open_position(
        pos, mode="paper", contracts=2, credit=0.6, commission=1.36, now=NOW, perm_id=1
    )
    st.record_order(
        spread_id="p1",
        kind="open",
        order_ref="CS:p1",
        ib_order_id=1,
        perm_id=1,
        filled_qty=2,
        price=0.6,
        commission=1.36,
        reason=None,
        now=NOW,
    )
    report = spreads_costs.measure(db, _BASE)
    (row,) = report.instruments
    assert row.instrument == "SPY" and row.candidates == 10
    assert row.median_crossing == pytest.approx(0.01)
    assert row.p90_crossing == pytest.approx(0.023, abs=1e-3)
    assert row.modelled_commission_per_leg == pytest.approx(0.65)
    assert report.paper_commission_per_leg == pytest.approx(0.34)
    assert report.paper_legs == 4
    spreads_costs.print_report(report)
    out = capsys.readouterr().out
    assert "median crossing $0.010" in out and "paper commission $0.340" in out


def test_the_cost_report_opens_the_file_read_only(tmp_path) -> None:
    import sqlite3

    from scripts import spreads_costs

    db = tmp_path / "spreads.db"
    sqlite3.connect(db).close()
    con = spreads_costs.connect_ro(db)
    with pytest.raises(sqlite3.OperationalError):
        con.execute("CREATE TABLE t (x INTEGER)")


def test_an_unknown_fee_blocks_the_report_for_that_instrument(tmp_path, monkeypatch) -> None:
    import src.spreads.store as st
    from scripts import spreads_costs

    db = tmp_path / "spreads.db"
    monkeypatch.setattr(st, "_engine", None)
    monkeypatch.setattr(st, "_SessionLocal", None)
    monkeypatch.setattr(st, "_resolve_url", lambda: f"sqlite:///{db}")
    st.init_spreads_db()
    _seed_candidates(st, [0.01, 0.01])
    xsp = _BASE.model_copy(
        update={
            "trading_class": "XSP",
            "execution": _BASE.execution.model_copy(update={"exchange_fees": {"XSP": None}}),
        }
    )
    (row,) = spreads_costs.measure(db, xsp).instruments
    assert row.blocked and row.modelled_commission_per_leg is None
