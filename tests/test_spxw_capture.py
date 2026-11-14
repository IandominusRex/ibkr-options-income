"""SPXW wing capture in shadow, and the E3 cost report (risk-envelope plan Task 17; spec §3.3, E3).

The spreads service quotes SPXW (and XSP) wing legs at the SPY baseline candidate's distance in
expected moves, writes them to ``spread_wing_quotes`` and orders nothing. ``scripts.spxw_cost_report``
compares all-in round-trip cost per $1,000 of max loss against SPY's and writes ``E3.json``.
"""

# ruff: noqa: F811
from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

import src.spreads.store as st
from scripts import spxw_cost_report as e3
from src.common.config import SpreadsCfg, SpreadsWingCaptureCfg, get_config
from src.common.schemas import ChainOption, SpreadCandidate
from src.spreads import wings
from tests.test_spreads_chain import CFG as CHAIN_CFG
from tests.test_spreads_chain import FakeIB, _broker
from tests.test_spreads_service import (
    ONE_A_DAY,
    T0945,
    T1005,
    TODAY,
    FakeBroker,
    make,
    spreads_db,  # noqa: F401 - the shared spreads.db fixture
)

NOW = datetime(2026, 11, 20, 18, 0, tzinfo=UTC)


# ----------------------------------------------------------------------------- the config


def test_the_wing_capture_block_loads_to_the_stated_defaults() -> None:
    wc = get_config().spreads.wing_capture
    assert wc == SpreadsWingCaptureCfg()
    assert (wc.enabled, wc.symbol, wc.trading_class) == (True, "SPX", "SPXW")
    assert wc.widths == [25.0, 10.0] and wc.xsp_width == 5.0
    with pytest.raises(ValueError):
        SpreadsWingCaptureCfg(widths=[])
    with pytest.raises(ValueError):
        SpreadsWingCaptureCfg(widths=[0.0])


# ----------------------------------------------------------------------------- the pure planner


def _cand(side: str = "put", short: float = 679.0, long: float = 674.0) -> SpreadCandidate:
    return SpreadCandidate(
        spread_id="CS-1",
        side=side,  # type: ignore[arg-type]
        expiry=TODAY,
        short_strike=short,
        long_strike=long,
        width=abs(short - long),
        credit_mid=0.60,
        credit_natural=0.58,
        spot=690.0,
        quote_time=NOW,
    )


def test_the_planner_keeps_the_spy_distance_in_index_terms() -> None:
    strikes = [float(k) for k in range(6000, 7200, 5)]
    plan = wings.plan_leg(_cand(), ratio=0.1, strikes=strikes, width=25.0)
    assert plan is not None
    assert (plan.short_strike, plan.long_strike) == (6790.0, 6765.0)  # 679 / 0.1, 25 below
    call = wings.plan_leg(_cand("call", 700.0, 705.0), ratio=0.1, strikes=strikes, width=10.0)
    assert call is not None and (call.short_strike, call.long_strike) == (7000.0, 7010.0)


def test_the_planner_never_sells_closer_to_spot_than_the_spy_leg() -> None:
    strikes = [6000.0, 6010.0, 6020.0, 6030.0]  # a coarse grid: 6785 falls between 6780 and 6790
    strikes = [float(k) for k in range(6700, 6900, 10)]
    put = wings.plan_leg(_cand(short=678.5, long=673.5), ratio=0.1, strikes=strikes, width=20.0)
    assert put is not None and put.short_strike == 6780.0  # at or below 6785, never above
    call = wings.plan_leg(
        _cand("call", 700.5, 705.5),
        ratio=0.1,
        strikes=[float(k) for k in range(6900, 7200, 10)],
        width=20.0,
    )
    assert call is not None and call.short_strike == 7010.0  # at or above 7005


def test_the_planner_gives_up_when_the_long_strike_is_not_listed() -> None:
    assert wings.plan_leg(_cand(), ratio=0.1, strikes=[6790.0], width=25.0) is None
    assert wings.plan_leg(_cand(), ratio=0.0, strikes=[6790.0, 6765.0], width=25.0) is None


# ----------------------------------------------------------------------------- the service


class WingBroker(FakeBroker):
    """The service test's SPY broker, plus the wing hooks: an SPX 5-point grid and an XSP 1-point grid."""

    def __init__(self, clock) -> None:
        super().__init__(clock)
        self.wing_calls: list[tuple[str, str, tuple[float, ...]]] = []
        self.orders = 0

    async def wing_strikes(self, *, symbol, sec_type, exchange, trading_class, expiry):
        assert sec_type == "IND" and exchange == "CBOE"
        if symbol == "SPX":
            return trading_class, [float(k) for k in range(6600, 7000, 5)]
        return trading_class, [float(k) for k in range(660, 700)]

    async def wing_quotes(self, *, symbol, trading_class, expiry, right, strikes):
        self.wing_calls.append((symbol, right, tuple(strikes)))
        out = {}
        for k in strikes:
            mid = max(0.05, (k - 6600) * 0.02) if symbol == "SPX" else max(0.05, (k - 660) * 0.2)
            out[k] = ChainOption(
                strike=k,
                right=right,
                expiry=expiry,
                bid=round(mid - 0.05, 2),
                ask=round(mid + 0.05, 2),
                con_id=int(k * 10),
            )
        return out


def _rows():
    with st.spreads_session() as s:
        return list(s.query(st.SpreadWingQuoteRow).order_by(st.SpreadWingQuoteRow.id))


async def _enter(tmp_path, wing_enabled: bool = True):
    clock = [T0945]
    cfg = ONE_A_DAY.model_copy(
        update={
            "wing_capture": SpreadsWingCaptureCfg(enabled=wing_enabled),
        }
    )
    broker = WingBroker(clock)
    svc, broker, _ = make(tmp_path, clock, cfg, broker)
    await svc.tick()  # the map
    clock[0] = T1005
    await svc.tick()  # the entry check
    return svc, broker


async def test_wing_capture_quotes_spxw_25_wide_legs_beside_the_spy_candidate(
    tmp_path, spreads_db
) -> None:
    svc, broker = await _enter(tmp_path)
    rows = _rows()
    by = {(r.instrument, r.width): r for r in rows}
    assert set(by) == {("SPXW", 25.0), ("SPXW", 10.0), ("XSP", 5.0)}
    w25 = by[("SPXW", 25.0)]
    # the SPY candidate sold the 679/674 put; GEX scale is SPY/SPX = 0.1
    assert (w25.spy_short_strike, w25.spy_long_strike) == (679.0, 674.0)
    assert (w25.side, w25.expiry, w25.session_date) == ("put", TODAY, TODAY)
    assert (w25.short_strike, w25.long_strike) == (6790.0, 6765.0)
    assert (by[("SPXW", 10.0)].short_strike, by[("SPXW", 10.0)].long_strike) == (6790.0, 6780.0)
    xsp = by[("XSP", 5.0)]
    assert (xsp.short_strike, xsp.long_strike) == (679.0, 674.0)  # XSP trades SPX / 10
    # both legs' bid and ask are stored
    assert w25.short_bid is not None and w25.short_ask > w25.short_bid
    assert w25.long_bid is not None and w25.long_ask > w25.long_bid
    # and the SPY candidate's own economics, for the cost comparison
    with st.spreads_session() as s:
        cand = s.query(st.SpreadCandidateRow).filter_by(spread_id=w25.spy_spread_id).first()
        assert cand is not None
        assert (w25.spy_credit_mid, w25.spy_credit_natural) == (
            cand.credit_mid,
            cand.credit_natural,
        )
    # one quote call per instrument, six lines at most (the strikes of one capture)
    assert sorted(c[0] for c in broker.wing_calls) == ["SPX", "XSP"]
    assert all(len(strikes) <= 6 for _, _, strikes in broker.wing_calls)


async def test_wing_capture_never_orders(tmp_path, spreads_db) -> None:
    from sqlalchemy import func

    await _enter(tmp_path)
    with st.spreads_session() as s:
        on = (
            s.query(func.count(st.SpreadOrderRow.id)).scalar(),
            s.query(func.count(st.SpreadPositionRow.id)).scalar(),
        )
        s.query(st.SpreadWingQuoteRow).delete()
        s.query(st.SpreadOrderRow).delete()
        s.query(st.SpreadPositionRow).delete()
        s.query(st.SpreadCandidateRow).delete()
    await _enter(tmp_path, wing_enabled=False)
    with st.spreads_session() as s:
        off = (
            s.query(func.count(st.SpreadOrderRow.id)).scalar(),
            s.query(func.count(st.SpreadPositionRow.id)).scalar(),
        )
    assert on == off and on[1] == 1  # the same one SPY spread, wings or not
    assert _rows() == []  # disabled: nothing captured
    # and the code has no order path: wings.py and the broker's wing methods never build or place one
    for path in (Path(wings.__file__),):
        text = path.read_text()
        for needle in ("placeOrder", "LimitOrder", "MarketOrder", "ComboLeg", "Order("):
            assert needle not in text


async def test_wing_capture_failure_never_blocks_the_entry(tmp_path, spreads_db) -> None:
    clock = [T0945]
    broker = WingBroker(clock)

    async def boom(**_kw):
        raise ConnectionError("gateway hiccup")

    broker.wing_strikes = boom  # type: ignore[method-assign]
    svc, broker, _ = make(tmp_path, clock, ONE_A_DAY, broker)
    await svc.tick()
    clock[0] = T1005
    await svc.tick()
    with st.spreads_session() as s:
        assert s.query(st.SpreadPositionRow).count() == 1  # the SPY spread opened regardless
    assert _rows() == []


async def test_a_broker_without_wing_hooks_is_left_alone(tmp_path, spreads_db) -> None:
    clock = [T0945]
    svc, _, _ = make(tmp_path, clock, ONE_A_DAY)  # the plain FakeBroker has no wing methods
    await svc.tick()
    clock[0] = T1005
    await svc.tick()
    assert _rows() == []


async def test_wing_capture_fits_the_spreads_line_budget() -> None:
    ib = FakeIB()
    broker = _broker(ib)
    got = await broker.wing_quotes(
        symbol="SPX",
        trading_class="SPXW",
        expiry=date(2026, 10, 7),
        right="P",
        strikes=[float(k) for k in range(660, 730)],  # 70 strikes: far more than one capture asks
    )
    assert len(got) == 70
    assert ib.max_open <= CHAIN_CFG.max_market_data_lines  # chunked, cancelled between chunks
    assert ib.open == 0
    # a real capture (six legs) is a single chunk
    ib2 = FakeIB()
    await _broker(ib2).wing_quotes(
        symbol="SPX",
        trading_class="SPXW",
        expiry=date(2026, 10, 7),
        right="P",
        strikes=[670.0, 675.0, 680.0, 685.0, 690.0, 695.0],
    )
    assert ib2.max_open == 6 and ib2.open == 0


async def test_wing_strikes_prefers_the_configured_class_that_lists_the_expiry() -> None:
    ib = FakeIB()
    broker = _broker(ib)
    got = await broker.wing_strikes(
        symbol="XSP",
        sec_type="IND",
        exchange="CBOE",
        trading_class="XSP",
        expiry=date(2026, 10, 7),
    )
    assert got is not None and got[0] == "XSP" and got[1][0] == 650.0
    none = await broker.wing_strikes(
        symbol="XSP",
        sec_type="IND",
        exchange="CBOE",
        trading_class="XSP",
        expiry=date(2026, 12, 1),  # no class lists it
    )
    assert none is None


async def test_wing_strikes_falls_back_to_the_class_that_lists_the_expiry() -> None:
    from types import SimpleNamespace

    class WeeklyOnly(FakeIB):
        async def reqSecDefOptParamsAsync(self, *args):  # noqa: N802
            return [
                SimpleNamespace(
                    exchange="SMART",
                    tradingClass="XSPW",
                    expirations=["20261007"],
                    strikes=[float(k) for k in range(650, 731)],
                ),
                SimpleNamespace(
                    exchange="SMART", tradingClass="XSP", expirations=["20261120"], strikes=[1.0]
                ),
            ]

    got = await _broker(WeeklyOnly()).wing_strikes(
        symbol="XSP",
        sec_type="IND",
        exchange="CBOE",
        trading_class="XSP",
        expiry=date(2026, 10, 7),
    )
    assert got is not None and got[0] == "XSPW"


# ----------------------------------------------------------------------------- the E3 report

FEES = {"SPY": 0.0, "SPXW": 0.5, "XSP": 0.2}
SPY_COST_PER_1K = 15.0  # (2 x 0.02 x 100 + 4 x 0.65) / 440 x 1000 = 6.6 / 440 x 1000


def _obs(
    day: int,
    instrument: str = "SPXW",
    width: float = 25.0,
    *,
    tight: bool = True,
    quoted: bool = True,
) -> e3.WingObs:
    if instrument == "SPXW":
        s = (4.15, 4.25) if tight else (3.0, 5.4)
        lg = (2.12, 2.18) if tight else (1.0, 3.3)
    else:  # XSP 5-wide
        s = (0.42, 0.44) if tight else (0.3, 0.6)
        lg = (0.10, 0.11) if tight else (0.02, 0.3)
    return e3.WingObs(
        session_date=date(2026, 12, 1 + day),
        instrument=instrument,
        width=width,
        spy_width=5.0,
        spy_credit_mid=0.60,
        spy_credit_natural=0.58,
        short_bid=s[0] if quoted else None,
        short_ask=s[1],
        long_bid=lg[0],
        long_ask=lg[1],
    )


def _all(sessions: int, **kw) -> list[e3.WingObs]:
    out: list[e3.WingObs] = []
    for d in range(sessions):
        out += [_obs(d, **kw), _obs(d, "XSP", 5.0, **kw)]
    return out


def _cfg(fees=FEES) -> SpreadsCfg:
    base = get_config().spreads
    return base.model_copy(
        update={"execution": base.execution.model_copy(update={"exchange_fees": dict(fees)})}
    )


def test_the_report_compares_cost_per_1k_of_max_loss() -> None:
    cfg = _cfg()
    spy = e3.spy_cost_per_1k(_obs(0), cfg)
    assert spy == pytest.approx(SPY_COST_PER_1K)
    # SPXW 25-wide: credit mid 2.05, natural 1.97, crossing 0.08 -> 2 x 0.08 x 100 = 16; plus
    # 4 x (0.65 + 0.50) = 4.6; max loss (25 - 2.05) x 100 = 2295: 20.6 / 2295 x 1000
    spxw = e3.wing_cost_per_1k(_obs(0), cfg)
    assert spxw == pytest.approx(20.6 / 2295 * 1000)
    assert spxw < spy
    # a leg nobody bids cannot be traded: an infinite cost, never skipped
    assert e3.wing_cost_per_1k(_obs(0, quoted=False), cfg) == float("inf")
    # an unknown exchange fee blocks the instrument
    assert e3.wing_cost_per_1k(_obs(0), _cfg({"SPY": 0.0, "SPXW": None, "XSP": None})) is None


def test_the_report_needs_15_sessions() -> None:
    r = e3.e3_result(_all(14), _cfg(), paper_bar_passed=True, now=NOW)
    assert r.passed is None and r.metrics["sessions"] == 14
    r15 = e3.e3_result(_all(15), _cfg(), paper_bar_passed=True, now=NOW)
    assert r15.passed is True and r15.value_on_pass == "spxw"


def test_e3_pass_needs_the_spreads_paper_bar_too() -> None:
    r = e3.e3_result(_all(20), _cfg(), paper_bar_passed=False, now=NOW)
    assert r.passed is None and "paper" in str(r.metrics["note"]).lower()
    assert e3.e3_result(_all(20), _cfg(), paper_bar_passed=True, now=NOW).passed is True


def test_xsp_is_the_fallback_when_spxw_fails_its_cost_test() -> None:
    obs = [_obs(d, tight=False) for d in range(20)] + [_obs(d, "XSP", 5.0) for d in range(20)]
    r = e3.e3_result(obs, _cfg(), paper_bar_passed=True, now=NOW)
    assert r.passed is True and r.value_on_pass == "xsp"


def test_both_failing_is_a_recorded_fail_to_stay_on_spy() -> None:
    r = e3.e3_result(_all(20, tight=False), _cfg(), paper_bar_passed=True, now=NOW)
    assert r.passed is False and r.value_on_pass == "stay" and r.switch == "spxw_ready"


def test_an_unknown_fee_leaves_the_verdict_open() -> None:
    r = e3.e3_result(
        _all(20), _cfg({"SPY": 0.0, "SPXW": None, "XSP": None}), paper_bar_passed=True, now=NOW
    )
    assert r.passed is None and "fee" in str(r.metrics["note"]).lower()


def test_e3_pass_only_notifies(tmp_path, db) -> None:
    """A PASS sets spxw_ready and nothing else, and the notice names Task 39."""
    from src.storage import envelope_switches as sw

    result = e3.e3_result(_all(20), _cfg(), paper_bar_passed=True, now=NOW)
    e3.write_result(result, tmp_path)
    before = {n: sw.get_switch(n) for n in sw.SWITCHES}
    notices = sw.apply_reports(tmp_path)
    after = {n: sw.get_switch(n) for n in sw.SWITCHES}
    changed = {n for n in sw.SWITCHES if before[n] != after[n]}
    assert changed == {"spxw_ready"} and after["spxw_ready"] == "spxw"
    assert [n for n in sw.SWITCHES if sw.switch_record(n)] == ["spxw_ready"]
    (notice,) = notices
    assert "Run Task 39 of the risk-envelope plan at a flat-book cutover" in notice
    assert json.loads((tmp_path / "E3.json").read_text())["value_on_pass"] == "spxw"


def test_the_paper_bar_is_read_from_the_spreads_paper_report(tmp_path) -> None:
    assert e3.paper_bar_passed(tmp_path) is False  # no file
    (tmp_path / "spreads_paper.json").write_text(
        json.dumps(
            {
                "id": "spreads_paper",
                "passed": True,
                "criterion": "x",
                "metrics": {},
                "switch": "spreads_paper",
                "value_on_pass": "on",
                "written_at": NOW.isoformat(),
            }
        )
    )
    assert e3.paper_bar_passed(tmp_path) is True


async def test_the_report_reads_what_the_service_captured(
    tmp_path,
    spreads_db,
) -> None:
    await _enter(tmp_path)
    obs = e3.load_observations(tmp_path / "spreads.db")
    assert {(o.instrument, o.width) for o in obs} == {("SPXW", 25.0), ("SPXW", 10.0), ("XSP", 5.0)}
    assert {o.session_date for o in obs} == {TODAY}
    assert all(o.spy_width == 5.0 for o in obs)
    # a database that does not exist yet is nothing captured, not an error
    assert e3.load_observations(tmp_path / "missing.db") == []
