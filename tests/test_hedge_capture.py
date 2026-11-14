"""Hedge-menu quote capture and the H4 report (risk-envelope plan Task 16; spec §3.10.4-§3.10.8).

A mocked IB: subscriptions go through ``req_fresh_mkt_data``, at most ten lines are open at once, each
chunk is cancelled before the next opens, and nothing here can place an order.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import hedge_capture_report as report
from src.common.config import HedgeCfg, get_hedge_cfg
from src.hedge import capture, menu, store
from src.hedge.menu import HedgeQuote

CFG = HedgeCfg()
TODAY = date(2026, 11, 16)
NOW = datetime(2026, 11, 16, 15, 45, tzinfo=UTC)  # 10:45 ET, after the 10:30 slot
SPOT = 100.0


def _q(
    strike: float,
    days: int,
    delta: float | None,
    *,
    bid: float | None = 1.0,
    ask: float | None = 1.1,
    right: str = "P",
) -> HedgeQuote:
    return HedgeQuote(
        strike=strike,
        right=right,
        expiry=TODAY + timedelta(days=days),
        bid=bid,
        ask=ask,
        bid_size=40,
        ask_size=40,
        delta=delta,
        con_id=int(strike * 10) + days,
    )


# ----------------------------------------------------------------------------- the menu


def test_the_menu_holds_only_allowed_shapes() -> None:
    chain = [
        _q(95, 90, -0.28),  # long candidate
        _q(90, 90, -0.20),  # long candidate; 5% below the 95: too narrow a vertical
        _q(84, 90, -0.10),  # 11% below the 95: a vertical short leg (its own delta is not limited)
        _q(80, 90, -0.06),
        _q(95, 30, -0.28),  # under the DTE floor: no item
        _q(95, 150, -0.28),  # beyond the window: no item
        _q(75, 90, -0.04, right="P"),  # delta under the 0.15 floor: never a long leg
        _q(105, 90, 0.30, right="C"),  # a call: never in the menu
    ]
    items = menu.build_menu(chain, SPOT, CFG, today=TODAY)
    assert items
    for it in items:
        assert it.kind in ("outright", "vertical")
        assert it.long.right == "P" and it.expiry == it.long.expiry
        assert it.dte >= CFG.dte_floor and CFG.dte_window[0] <= it.dte <= CFG.dte_window[1]
        assert 0.15 <= it.delta <= 0.30
        if it.kind == "vertical":
            assert it.short is not None and it.short.right == "P"
            assert it.short.expiry == it.long.expiry  # never a calendar
            assert it.short.strike < it.long.strike  # never short-only, never inverted
            assert it.width_pct is not None and it.width_pct >= CFG.vertical_min_width_pct
            assert len(it.legs) == 2  # 1:1, never a ratio
        else:
            assert it.short is None and len(it.legs) == 1
    keys = {it.item_key for it in items}
    assert any("/" not in k for k in keys) and any("/" in k for k in keys)
    assert not any(it.item_key.startswith("P90/84@") for it in items)  # 6% wide: too narrow
    assert any(it.item_key.startswith("P90/80@") for it in items)  # 10% wide: allowed
    assert not any(it.long.strike == 75 for it in items)  # the 0.04-delta long leg


def test_the_default_item_is_the_best_minimum_protection_per_dollar() -> None:
    cheap_far = _q(88, 90, -0.16, bid=0.20, ask=0.24)  # cheap, pays nothing at -10%
    rich_near = _q(97, 90, -0.28, bid=2.00, ask=2.10)
    items = menu.build_menu([cheap_far, rich_near], SPOT, CFG, today=TODAY)
    best = menu.default_item(items, SPOT)
    assert best is not None
    # intrinsic payoff at -10% per mid debit: 0/0.22 for the 88 put, 7/2.05 for the 97
    assert best.long.strike == 97
    # an item with no two-sided price can never be the default
    assert (
        menu.default_item(
            menu.build_menu([_q(95, 90, -0.28, bid=None)], SPOT, CFG, today=TODAY), SPOT
        )
        is None
    )


def test_candidate_strikes_stay_in_the_window_and_are_few() -> None:
    expirations = [TODAY + timedelta(days=d) for d in (10, 30, 62, 91, 118, 200)]
    strikes = [float(k) for k in range(50, 130)]
    wanted = menu.candidate_strikes(strikes, expirations, SPOT, CFG, today=TODAY)
    assert {e for e, _ in wanted} == {TODAY + timedelta(days=91), TODAY + timedelta(days=62)}
    assert 0 < len(wanted) <= 2 * 20  # a few chunks of ten lines, not the whole chain
    assert wanted == sorted(set(wanted))
    # every short candidate leaves room for a vertical at least 10% of spot wide
    assert min(k for _, k in wanted) <= 0.87 * SPOT - 0.10 * SPOT + 1


# ----------------------------------------------------------------------------- the capture


class FakeIB:
    def __init__(self) -> None:
        self.open: set[int] = set()
        self.max_open = 0
        self.cancelled: list[int] = []

    async def qualifyContractsAsync(self, c):  # noqa: N802 - ib_async's name
        c.conId = 900
        return [c]

    async def reqSecDefOptParamsAsync(self, symbol, exch, sec_type, con_id):  # noqa: N802
        exps = [f"{TODAY + timedelta(days=d):%Y%m%d}" for d in (10, 62, 91, 200)]
        return [
            SimpleNamespace(
                tradingClass=symbol, exchange="SMART", expirations=exps, strikes=range(50, 130)
            ),
            SimpleNamespace(
                tradingClass=f"{symbol}W", exchange="SMART", expirations=[], strikes=[]
            ),
        ]

    def cancelMktData(self, contract) -> None:  # noqa: N802
        self.open.discard(int(contract.conId))
        self.cancelled.append(int(contract.conId))


@pytest.fixture()
def ib(monkeypatch):
    fake = FakeIB()
    subs: list[int] = []

    async def qualify(_ib, contracts, **_kw):
        for c in contracts:
            c.conId = int(float(c.strike) * 10) + int(str(c.lastTradeDateOrContractMonth)[6:8])
        return contracts

    def fresh(_ib, contract, *args):
        subs.append(int(contract.conId))
        fake.open.add(int(contract.conId))
        fake.max_open = max(fake.max_open, len(fake.open))
        if not getattr(contract, "strike", 0):  # the underlying
            return SimpleNamespace(last=SPOT, bid=float("nan"), ask=float("nan"))
        m = float(contract.strike) / SPOT
        delta = -max(0.01, (m - 0.84) * 2.5)
        return SimpleNamespace(
            bid=0.9,
            ask=1.0,
            bidSize=25.0,
            askSize=30.0,
            modelGreeks=SimpleNamespace(delta=delta),
        )

    async def no_sleep(_s):
        return None

    monkeypatch.setattr(capture, "qualify_options_async", qualify)
    monkeypatch.setattr(capture, "req_fresh_mkt_data", fresh)
    monkeypatch.setattr(capture.asyncio, "sleep", no_sleep)
    fake.subs = subs  # type: ignore[attr-defined]
    return fake


async def test_capture_writes_bid_ask_size_per_leg(ib, db) -> None:
    out = await capture.capture_once(ib, NOW, cfg=CFG)
    assert out.errors == {} and set(out.rows) == {"XND", "QQQ"} and all(out.rows.values())
    rows = store.load_quotes(instrument="XND")
    assert rows and {r.instrument for r in rows} == {"XND"}
    for r in rows:
        assert r.right == "P" and r.leg in ("long", "short")
        assert (r.bid, r.ask, r.bid_size, r.ask_size) == (0.9, 1.0, 25.0, 30.0)
        assert r.mid == pytest.approx(0.95) and r.delta is not None and r.spot == SPOT
        assert r.needed_contracts == 0  # Task 36's size rule does not exist yet
        assert r.session_date == date(2026, 11, 16)
    assert {r.leg for r in rows} == {"long", "short"}
    assert len({r.captured_at for r in rows}) == 1  # one capture, one timestamp
    defaults = {r.item_key for r in rows if r.is_default}
    assert len(defaults) == 1  # exactly one default item per capture


async def test_capture_stays_inside_its_line_budget(ib, db) -> None:
    await capture.capture_once(ib, NOW, cfg=CFG)
    assert 0 < ib.max_open <= CFG.capture_max_lines <= 10
    assert not ib.open  # every line cancelled
    assert len(ib.subs) == len(ib.cancelled)  # each subscription cancelled exactly once


async def test_capture_never_exceeds_ten_lines_even_if_configured_higher(ib, db) -> None:
    quotes = await capture.quote_contracts(
        ib,
        [
            SimpleNamespace(
                conId=i, strike=90.0, right="P", lastTradeDateOrContractMonth="20270101"
            )
            for i in range(1, 36)
        ],
        max_lines=50,
    )
    assert len(quotes) == 35 and ib.max_open <= 10 and not ib.open


async def test_one_instruments_failure_does_not_stop_the_next(ib, db, monkeypatch) -> None:
    real = capture.capture_instrument

    async def flaky(ib_, name, icfg, cfg, now):
        if name == "XND":
            raise RuntimeError("no contract")
        return await real(ib_, name, icfg, cfg, now)

    monkeypatch.setattr(capture, "capture_instrument", flaky)
    out = await capture.capture_once(ib, NOW, cfg=CFG)
    assert "XND" in out.errors and out.rows.get("QQQ")
    assert store.load_quotes(instrument="XND") == [] and store.load_quotes(instrument="QQQ")


def test_the_capture_module_has_no_order_path() -> None:
    text = Path(capture.__file__).read_text()
    assert ".reqMktData(" not in text and "req_fresh_mkt_data(" in text
    assert "placeOrder" not in text and "LimitOrder" not in text


# ----------------------------------------------------------------------------- when it runs


def _et(day: int, hhmm: str) -> datetime:
    h, m = (int(x) for x in hhmm.split(":"))
    return datetime(2026, 11, day, h + 5, m, tzinfo=UTC)  # EST in November


def test_due_slot_is_the_newest_passed_time_not_yet_attempted() -> None:
    times = ["10:30", "14:30"]
    assert capture.due_slot(_et(16, "10:00"), times, "") is None
    assert capture.due_slot(_et(16, "10:30"), times, "") == "2026-11-16 10:30"
    assert capture.due_slot(_et(16, "10:40"), times, "2026-11-16 10:30") is None
    assert capture.due_slot(_et(16, "14:31"), times, "2026-11-16 10:30") == "2026-11-16 14:30"
    # a late restart runs the newest slot once, not one per missed time
    assert capture.due_slot(_et(16, "15:50"), times, "") == "2026-11-16 14:30"
    assert capture.due_slot(_et(17, "10:31"), times, "2026-11-16 14:30") == "2026-11-17 10:30"


async def test_capture_runs_twice_a_session_at_fixed_times(db, monkeypatch) -> None:
    calls: list[str] = []

    async def fake_once(_ib, now, *, cfg=None):
        out = capture.CaptureOutcome(slot=now.strftime("%H:%M"))
        calls.append(out.slot)
        return out

    monkeypatch.setattr(capture, "capture_once", fake_once)
    for day, hhmm in [
        (16, "10:15"),  # before the first slot
        (16, "10:31"),  # first slot: runs
        (16, "10:46"),  # the same slot: no
        (16, "13:00"),
        (16, "14:31"),  # second slot: runs
        (16, "15:00"),
        (17, "10:30"),  # next session
    ]:
        await capture.run_due_capture(object(), _et(day, hhmm))  # type: ignore[arg-type]
    assert len(calls) == 3
    assert [c for c in calls[:2]] == ["15:31", "19:31"]  # UTC of 10:31 and 14:31 ET


async def test_a_running_scan_defers_the_capture_without_marking_the_slot(db, monkeypatch) -> None:
    calls: list[str] = []

    async def fake_once(_ib, now, *, cfg=None):
        calls.append("x")
        return capture.CaptureOutcome(slot="s")

    monkeypatch.setattr(capture, "capture_once", fake_once)
    assert await capture.run_due_capture(object(), _et(16, "10:45"), scan_running=True) is None  # type: ignore[arg-type]
    assert calls == []
    assert await capture.run_due_capture(object(), _et(16, "11:00")) is not None  # type: ignore[arg-type]
    assert calls == ["x"]


async def test_a_failing_capture_never_raises_and_is_not_retried_every_cycle(
    db, monkeypatch
) -> None:
    n = 0

    async def boom(_ib, now, *, cfg=None):
        nonlocal n
        n += 1
        raise RuntimeError("gateway gone")

    monkeypatch.setattr(capture, "capture_once", boom)
    assert await capture.run_due_capture(object(), _et(16, "10:45")) is None  # type: ignore[arg-type]
    assert await capture.run_due_capture(object(), _et(16, "11:00")) is None  # type: ignore[arg-type]
    assert n == 1  # the slot was marked attempted


# ----------------------------------------------------------------------------- the config


def test_the_hedge_block_in_the_example_loads_to_the_stated_defaults() -> None:
    cfg = get_hedge_cfg()  # tests read config/examples
    assert cfg == HedgeCfg()
    assert set(cfg.instruments) == {"XND", "QQQ"}
    assert (
        cfg.instruments["XND"].trading_class == "XND" and cfg.instruments["XND"].sec_type == "IND"
    )
    assert cfg.capture_times_et == ["10:30", "14:30"] and cfg.capture_max_lines == 10
    assert cfg.dte_window == (60, 120) and cfg.dte_floor == 45
    assert cfg.long_delta == (0.15, 0.30) and cfg.vertical_min_width_pct == 10.0
    assert cfg.quote_max_spread_pct == 8.0


def test_hedge_keys_equal_the_models_fields_and_refuse_a_typo() -> None:
    assert set(HedgeCfg.KEYS) == set(HedgeCfg.model_fields)
    with pytest.raises(ValueError, match="unknown key"):
        HedgeCfg(capture_max_line=10)  # type: ignore[call-arg]
    with pytest.raises(ValueError):
        HedgeCfg(capture_max_lines=11)  # chunks of at most ten lines


# ----------------------------------------------------------------------------- the H4 report


def _rec(
    instrument: str,
    day: int,
    hour: int,
    *,
    bid: float = 0.98,
    ask: float = 1.02,
    size: float = 40.0,
    leg: str = "long",
    strike: float = 95.0,
    needed: int = 0,
    default: bool = True,
) -> store.QuoteRecord:
    return store.QuoteRecord(
        captured_at=datetime(2026, 12, 1, hour, 0, tzinfo=UTC) + timedelta(days=day),
        session_date=date(2026, 12, 1) + timedelta(days=day),
        instrument=instrument,
        item_key=f"P{strike:g}@20270301",
        leg=leg,
        is_default=default,
        con_id=1,
        strike=strike,
        right="P",
        expiry=date(2027, 3, 1),
        spot=SPOT,
        bid=bid,
        ask=ask,
        bid_size=size,
        ask_size=size,
        mid=(bid + ask) / 2,
        delta=-0.25,
        needed_contracts=needed,
    )


def _history(sessions: int, **xnd_kw) -> list[store.QuoteRecord]:
    out: list[store.QuoteRecord] = []
    for d in range(sessions):
        for h in (15, 19):
            out.append(_rec("XND", d, h, **xnd_kw))
            out.append(_rec("QQQ", d, h))
    return out


def test_the_report_picks_xnd_on_the_h4_bar() -> None:
    results = report.h4_results(_history(20), CFG, now=NOW)
    assert [r.id for r in results] == ["H4"]
    (h4,) = results
    assert h4.passed is True and h4.switch == "hedge_instrument" and h4.value_on_pass == "XND"
    assert h4.metrics["sessions"] == 20
    assert h4.metrics["xnd_median_spread_pct"] == pytest.approx(4.0)
    assert h4.metrics["xnd_size_share"] == 1.0


def test_the_report_picks_qqq_when_xnd_fails() -> None:
    # XND's default item quotes 30% wide: the median spread bar (8%) fails
    results = report.h4_results(_history(20, bid=0.85, ask=1.15), CFG, now=NOW)
    h4, fallback = results
    assert (h4.id, h4.passed, h4.value_on_pass) == ("H4", False, "XND")
    assert (fallback.id, fallback.passed, fallback.value_on_pass) == ("H4_fallback", True, "QQQ")
    assert fallback.switch == "hedge_instrument"


def test_nothing_displayed_fails_the_size_bar_even_before_the_bridge_exists() -> None:
    results = report.h4_results(_history(20, size=0.0), CFG, now=NOW)
    assert results[0].passed is False and results[0].metrics["xnd_size_share"] == 0.0
    assert results[1].value_on_pass == "QQQ"


def test_displayed_size_must_cover_the_bridges_contract_count() -> None:
    results = report.h4_results(_history(20, size=10.0, needed=15), CFG, now=NOW)
    assert results[0].passed is False and results[0].metrics["xnd_size_share"] == 0.0


def test_a_tight_cheap_xnd_clears_the_cost_bar() -> None:
    h4 = report.h4_results(_history(20, bid=0.50, ask=0.54), CFG, now=NOW)[0]
    assert h4.passed is True


def test_the_cost_bar_compares_with_qqq() -> None:
    # same spread and size, but XND's default item costs far more per protected point
    results = report.h4_results(_history(20, bid=3.9, ask=4.1), CFG, now=NOW)
    assert results[0].passed is False
    assert results[0].metrics["xnd_cost_per_point"] > 1.5 * results[0].metrics["qqq_cost_per_point"]  # type: ignore[operator]


def test_a_one_sided_default_leg_is_an_infinite_spread() -> None:
    quotes = [replace(r, bid=None, mid=None) if r.instrument == "XND" else r for r in _history(20)]
    h4 = report.h4_results(quotes, CFG, now=NOW)[0]
    assert h4.passed is False and h4.metrics["xnd_median_spread_pct"] == "inf"


def test_fewer_than_20_sessions_is_insufficient() -> None:
    results = report.h4_results(_history(19, bid=0.85, ask=1.15), CFG, now=NOW)
    assert [r.id for r in results] == ["H4"]  # no fallback on thin data
    assert results[0].passed is None


def test_a_missing_qqq_cost_is_insufficient_not_a_pass() -> None:
    quotes = [r for r in _history(20) if r.instrument == "XND"]
    h4 = report.h4_results(quotes, CFG, now=NOW)[0]
    assert h4.passed is None and "QQQ" in str(h4.metrics["note"])


def test_write_results_removes_a_stale_fallback(tmp_path) -> None:
    bad = report.h4_results(_history(20, bid=0.85, ask=1.15), CFG, now=NOW)
    paths = report.write_results(bad, tmp_path)
    assert {p.name for p in paths} == {"H4.json", "H4_fallback.json"}
    assert json.loads((tmp_path / "H4_fallback.json").read_text())["passed"] is True
    good = report.h4_results(_history(20), CFG, now=NOW)
    report.write_results(good, tmp_path)
    assert not (tmp_path / "H4_fallback.json").exists()  # else it would flip XND back to QQQ at EOD
    assert json.loads((tmp_path / "H4.json").read_text())["passed"] is True


def test_a_pass_sets_the_instrument_switch_through_apply_reports(tmp_path, db) -> None:
    from src.storage.envelope_switches import apply_reports, get_switch

    report.write_results(
        report.h4_results(_history(20, bid=0.85, ask=1.15), CFG, now=NOW), tmp_path
    )
    notices = apply_reports(tmp_path)
    assert len(notices) == 1 and "hedge_instrument -> QQQ" in notices[0]
    assert get_switch("hedge_instrument") == "QQQ"
