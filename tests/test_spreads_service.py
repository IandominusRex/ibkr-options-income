from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime

import pytest

from src.common.config import get_config
from src.common.schemas import ChainOption, ChainSnapshot, SessionSnapshot
from src.spreads.executor import SpreadExecutor

TODAY = date(2026, 10, 7)
T0931 = datetime(2026, 10, 7, 13, 31, tzinfo=UTC)
T0936 = datetime(2026, 10, 7, 13, 36, tzinfo=UTC)
T0941 = datetime(2026, 10, 7, 13, 41, tzinfo=UTC)
T0945 = datetime(2026, 10, 7, 13, 45, tzinfo=UTC)
T0947 = datetime(2026, 10, 7, 13, 47, tzinfo=UTC)
T0950 = datetime(2026, 10, 7, 13, 50, tzinfo=UTC)
T1001 = datetime(2026, 10, 7, 14, 1, tzinfo=UTC)
T1005 = datetime(2026, 10, 7, 14, 5, tzinfo=UTC)
T1100 = datetime(2026, 10, 7, 15, 0, tzinfo=UTC)
T1610 = datetime(2026, 10, 7, 20, 10, tzinfo=UTC)
SATURDAY = datetime(2026, 10, 10, 14, 5, tzinfo=UTC)

_BASE = get_config().spreads
# The mechanics tests pin the original rule (map 09:45, entries from 10:00, every check, both
# sides) and one contract (max_contracts 1), so they test the loop, not the trigger or the
# sizing. MOVE below exercises the amendment's rules; the sizing test lifts the contract cap.
CFG = _BASE.model_copy(
    update={
        "enabled": True,
        "mode": "shadow",
        "schedule": _BASE.schedule.model_copy(
            update={
                "map_time": "09:45",
                "entry_start": "10:00",
                "entry_end": "13:30",
                "entry_check_minutes": 5,
                "map_refresh_minutes": 60,
                "force_close": "15:45",
            }
        ),
        "entry": _BASE.entry.model_copy(update={"trigger": "always"}),
        "selection": _BASE.selection.model_copy(
            update={
                "sides": ["put", "call"],
                "width": 5.0,
                "min_credit_pct_of_width": 0.10,
                "short_delta_max": 0.15,
                "max_leg_spread_pct": 0.30,
                "em_multiple": 1.0,
                "em_straddle_factor": 1.0,
                "wall_buffer_pct": 0.001,
            }
        ),
        "risk": _BASE.risk.model_copy(
            update={
                "max_trades_per_day": 2,
                "max_open_spreads": 2,
                "max_contracts": 1,
                "starting_capital_usd": 100_000.0,
                "max_loss_pct_of_capital": 0.10,
                "max_total_risk_pct_of_capital": 0.10,
                "max_daily_loss_pct_of_capital": 0.10,
                "min_excess_liquidity_usd": 10_000.0,
                "max_quote_age_seconds": 20.0,
                "one_side_per_day": True,
                "events": [],
                "ex_dividend_dates": [],
            }
        ),
        "exits": _BASE.exits.model_copy(
            update={"profit_take_pct": 50.0, "stop_debit_multiple": 2.0, "max_hold_minutes": 150}
        ),
        "gex": _BASE.gex.model_copy(
            update={"negative_gamma_action": "skip", "flip_buffer_pct": 0.002}
        ),
    }
)
# One entry per day: the 11:00 entry check would otherwise open a second, identical spread.
ONE_A_DAY = CFG.model_copy(update={"risk": CFG.risk.model_copy(update={"max_trades_per_day": 1})})
# The amendment's rules: opening map and window, the move trigger, negative gamma traded.
MOVE = ONE_A_DAY.model_copy(
    update={
        "schedule": CFG.schedule.model_copy(update={"map_time": "09:31", "entry_start": "09:35"}),
        "entry": _BASE.entry.model_copy(
            update={
                "trigger": "move",
                "min_move_em": 0.5,
                "max_move_em": 1.5,
                "stall_minutes": 10,
                "max_tape_age_seconds": 120.0,
                "gap_day_pct": 0.003,
            }
        ),
        "gex": CFG.gex.model_copy(update={"negative_gamma_action": "allow"}),
    }
)


def o(strike, right, bid=None, ask=None, *, oi=None, iv=None, delta=None):
    return ChainOption(
        strike=strike,
        right=right,
        expiry=TODAY,
        bid=bid,
        ask=ask,
        open_interest=oi,
        iv=iv,
        delta=delta,
        con_id=int(strike * 10) + (1 if right == "C" else 0),
    )


class FakeBroker:
    """SPX OI makes a positive-gamma day (swap ``spx_oi`` for a negative one); SPY has one
    qualifying put spread (679/674) and an ATM straddle of 5.8; ``session`` is the SPY tape."""

    def __init__(self, clock: list[datetime]) -> None:
        self.clock = clock
        self.calls: list[str] = []
        self.legs: dict[int, float] = {}
        self.fail_requote = False
        self.spx_oi = {"P": 1_000, "C": 40_000}
        self.xsp_atm = {"C": (2.9, 3.1), "P": (2.7, 2.9)}
        self.session: dict[str, float | None] = {
            "last": 690.0,
            "open": 690.0,
            "high": 690.0,
            "low": 690.0,
            "prior_close": 690.0,
        }
        self.leg_quotes = {
            (679.0, "P"): o(679, "P", 0.80, 0.86, delta=-0.12),
            (674.0, "P"): o(674, "P", 0.20, 0.24),
        }

    async def fetch_chain(
        self, *, symbol, trading_class, exchange, expiries, band_pct, spot_hint=None, sec_type="IND"
    ):
        self.calls.append(symbol)
        if symbol == "SPX":
            assert sec_type == "IND"
            return ChainSnapshot(
                symbol="SPX",
                spot=6900.0,
                as_of=self.clock[0],
                options=[
                    o(6800, "P", oi=self.spx_oi["P"], iv=0.40),
                    o(6950, "C", oi=self.spx_oi["C"], iv=0.40),
                ],
            )
        assert (symbol, sec_type) == ("SPY", "STK")
        return ChainSnapshot(
            symbol="SPY",
            spot=690.0,
            as_of=self.clock[0],
            options=[
                o(690, "C", *self.xsp_atm["C"]),
                o(690, "P", *self.xsp_atm["P"]),
                o(679, "P", 0.80, 0.86, delta=-0.12),
                o(674, "P", 0.20, 0.24),
            ],
        )

    async def session_quote(self):
        return SessionSnapshot(as_of=self.clock[0], **self.session)

    async def requote(self, legs):
        if self.fail_requote:
            raise ConnectionError("socket dropped")
        return [
            self.leg_quotes.get((float(x.strike), x.right), x).model_copy(
                update={"con_id": x.con_id}
            )
            for x in legs
        ]

    async def spot(self):
        return 690.0

    async def excess_liquidity(self):
        return 50_000.0

    def broker_legs(self):
        return self.legs


class FakeNotifier:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(self, text: str) -> None:
        self.sent.append(text)


@pytest.fixture()
def spreads_db(tmp_path, monkeypatch):
    import src.spreads.store as st

    monkeypatch.setattr(st, "_engine", None)
    monkeypatch.setattr(st, "_SessionLocal", None)
    monkeypatch.setattr(st, "_resolve_url", lambda: f"sqlite:///{tmp_path / 'spreads.db'}")
    st.init_spreads_db()
    return st


def make(tmp_path, clock, cfg=CFG, broker=None):
    from src.spreads.service import SpreadsService

    broker = broker or FakeBroker(clock)
    notifier = FakeNotifier()
    ex = SpreadExecutor(None, broker, cfg, now=lambda: clock[0])
    svc = SpreadsService(
        broker, ex, notifier, cfg, halt_path=tmp_path / "halt", now=lambda: clock[0]
    )
    return svc, broker, notifier


async def test_a_full_shadow_day_maps_enters_and_takes_profit(tmp_path, spreads_db) -> None:
    clock = [T0945]
    svc, broker, notifier = make(tmp_path, clock, ONE_A_DAY)
    await svc.start()
    await svc.tick()  # 09:45 — map only
    assert svc.levels is not None and svc.levels.regime == "positive"
    assert spreads_db.open_positions("shadow") == []
    clock[0] = T1005
    await svc.tick()  # 10:05 — entry
    (pos,) = spreads_db.open_positions("shadow")
    assert (pos.short_strike, pos.long_strike, pos.entry_credit) == (
        679.0,
        674.0,
        pytest.approx(0.57),
    )
    broker.leg_quotes = {
        (679.0, "P"): o(679, "P", 0.30, 0.34),
        (674.0, "P"): o(674, "P", 0.03, 0.05),
    }
    clock[0] = T1100
    await svc.tick()  # 11:00 — profit take (mid 0.28 ≤ 0.285)
    assert spreads_db.open_positions("shadow") == []
    ((_, reason, pnl),) = spreads_db.closed_results("shadow")
    assert reason == "profit_take" and pnl == pytest.approx((0.57 - 0.32) * 100 - 1.30 - 1.30)
    (t,) = spreads_db.trade_log("shadow")  # every trade is logged with its tags
    assert (t.trigger, t.regime, t.exit_reason) == ("always", "positive", "profit_take")
    assert t.hold_minutes == pytest.approx(55.0) and t.mae_usd == pytest.approx(0.0)
    assert svc.capital() == pytest.approx(100_000.0 + pnl)  # the book's capital grows with it
    clock[0] = T1610
    await svc.tick()  # EOD summary once
    await svc.tick()
    assert sum("trade(s)" in m for m in notifier.sent) == 1


# Review C1 — the typical winner: the far-OTM long has no bid (ib_async NaN → None).
async def test_a_winner_whose_long_nobody_bids_takes_profit(tmp_path, spreads_db) -> None:
    clock = [T0945]
    svc, broker, _ = make(tmp_path, clock, ONE_A_DAY)
    await svc.tick()
    clock[0] = T1005
    await svc.tick()
    broker.leg_quotes = {
        (679.0, "P"): o(679, "P", 0.03, 0.05),
        (674.0, "P"): o(674, "P", None, 0.01),
    }
    clock[0] = T1100
    await svc.tick()
    ((_, reason, pnl),) = spreads_db.closed_results("shadow")
    assert reason == "profit_take" and pnl > 0


async def test_entries_are_sized_to_ten_percent_of_the_books_capital(tmp_path, spreads_db) -> None:
    roomy = ONE_A_DAY.model_copy(
        update={"risk": ONE_A_DAY.risk.model_copy(update={"max_contracts": 100})}
    )
    clock = [T0945]
    svc, _, _ = make(tmp_path, clock, roomy)
    await svc.tick()
    clock[0] = T1005
    await svc.tick()
    (pos,) = spreads_db.open_positions("shadow")
    assert pos.contracts == 22  # ⌊10% × $100,000 ÷ ((5 − 0.61) × 100)⌋


async def test_a_spread_still_open_after_the_time_stop_raises_the_assignment_alert(
    tmp_path, spreads_db
) -> None:
    from src.spreads.executor import FillResult

    clock = [T0945]
    svc, _, notifier = make(tmp_path, clock, ONE_A_DAY)
    await svc.tick()
    clock[0] = T1005
    await svc.tick()
    assert len(spreads_db.open_positions("shadow")) == 1

    class NoFill:
        async def close(self, pos, short_q, long_q, *, urgent):
            return FillResult(0, None, 0.0, reason="not_filled", order_ref="CS:x")

    svc.executor = NoFill()
    clock[0] = datetime(2026, 10, 7, 19, 46, tzinfo=UTC)  # 15:46 ET, past the time stop
    await svc.tick()
    await svc.tick()
    assert len(spreads_db.open_positions("shadow")) == 1
    assert sum("risk assignment" in m for m in notifier.sent) == 1


async def _flush(svc, broker, clock) -> None:
    """09:31 map; the index flushes from a 693.5 prior close to a 689.8 low at 09:36, then holds."""
    broker.session.update(last=692.0, open=692.0, high=692.2, low=691.9, prior_close=693.5)
    clock[0] = T0931
    await svc.tick()
    broker.session.update(last=689.8, low=689.8)
    clock[0] = T0936
    await svc.tick()
    broker.session.update(last=690.4)
    clock[0] = T0941
    await svc.tick()


async def test_the_move_trigger_waits_for_a_stalled_flush_then_sells_puts(
    tmp_path, spreads_db
) -> None:
    clock = [T0931]
    svc, broker, notifier = make(tmp_path, clock, MOVE)
    await svc.start()
    await _flush(svc, broker, clock)
    assert svc.tape is not None and svc.tape.day_em == pytest.approx(5.8)
    assert spreads_db.open_positions("shadow") == []
    assert broker.calls.count("SPY") == 1  # only the 09:31 map: no chain fetch until armed
    broker.session.update(last=690.0)
    clock[0] = T0947
    await svc.tick()  # the 09:36 low has held for 11 minutes
    (pos,) = spreads_db.open_positions("shadow")
    assert (pos.side, pos.short_strike, pos.long_strike) == ("put", 679.0, 674.0)
    (t,) = spreads_db.trade_log("shadow")
    assert (t.trigger, t.regime, t.gap_day, t.minutes_after_open) == ("move", "positive", False, 17)
    assert t.move_em == pytest.approx((693.5 - 690.0) / 5.8)
    assert t.gap_pct == pytest.approx(692.0 / 693.5 - 1)
    assert any("after a 0.60× expected-move drop" in m for m in notifier.sent)


async def test_negative_gamma_is_traded_and_tagged(tmp_path, spreads_db) -> None:
    clock = [T0931]
    svc, broker, notifier = make(tmp_path, clock, MOVE)
    broker.spx_oi = {"P": 40_000, "C": 1_000}  # put-heavy: dealers are short gamma at 6900
    await svc.start()
    await _flush(svc, broker, clock)
    assert svc.levels is not None and svc.levels.regime == "negative"
    broker.session.update(last=690.0)
    clock[0] = T0947
    await svc.tick()
    (t,) = spreads_db.trade_log("shadow")
    assert (t.regime, t.side) == ("negative", "put")
    assert any("NEGATIVE GAMMA" in m for m in notifier.sent)


# Review Focus 6 — a restart mid-move waits a full stall window and keeps the day's first yardstick.
async def test_a_restart_mid_flush_cannot_hurry_an_entry(tmp_path, spreads_db) -> None:
    clock = [T0931]
    svc, broker, _ = make(tmp_path, clock, MOVE)
    await svc.start()
    await _flush(svc, broker, clock)  # the 09:31 map stores the day's expected move, 5.8
    broker.xsp_atm = {"C": (1.9, 2.1), "P": (1.7, 1.9)}  # a later, smaller straddle (3.8)
    broker.session.update(last=690.0)
    clock[0] = T0950
    fresh, _, _ = make(tmp_path, clock, MOVE, broker=broker)  # the restarted process
    await fresh.start()
    await fresh.tick()  # rebuilds the map; the 689.8 low printed before this process existed
    assert fresh.tape is not None and fresh.tape.day_em == pytest.approx(5.8)
    assert spreads_db.open_positions("shadow") == []
    broker.session.update(last=690.2)
    clock[0] = T1001
    await fresh.tick()  # 11 minutes after its first observation
    assert len(spreads_db.open_positions("shadow")) == 1


# Review Focus 4 — a restart counts today's trades from the DB, not memory.
async def test_restart_never_exceeds_max_trades_per_day(tmp_path, spreads_db) -> None:
    one_a_day = ONE_A_DAY
    clock = [T0945]
    svc, _, _ = make(tmp_path, clock, one_a_day)
    await svc.tick()
    clock[0] = T1005
    await svc.tick()
    assert len(spreads_db.open_positions("shadow")) == 1
    clock[0] = datetime(2026, 10, 7, 14, 20, tzinfo=UTC)
    fresh, _, _ = make(tmp_path, clock, one_a_day)  # the restarted process
    await fresh.start()
    await fresh.tick()  # rebuilds the map, then tries to enter
    assert len(spreads_db.open_positions("shadow")) == 1
    with spreads_db.spreads_session() as s:
        last = (
            s.query(spreads_db.SpreadCandidateRow)
            .order_by(spreads_db.SpreadCandidateRow.id.desc())
            .first()
        )
        assert "max_trades_per_day" in last.reasons


async def test_halt_file_blocks_entries_but_not_exits(tmp_path, spreads_db) -> None:
    clock = [T0945]
    svc, broker, notifier = make(tmp_path, clock)
    await svc.tick()
    (tmp_path / "halt").write_text("")
    clock[0] = T1005
    await svc.tick()
    assert spreads_db.open_positions("shadow") == []
    assert broker.calls.count("SPY") == 1  # only the 09:45 map fetched SPY
    assert any("halt" in m for m in notifier.sent)


# Review Focus 1 — a broker/DB mismatch after a reconnect blocks entries until consistent.
async def test_reconcile_mismatch_blocks_entries_until_consistent(tmp_path, spreads_db) -> None:
    from src.common.schemas import SpreadCandidate

    paper = CFG.model_copy(update={"mode": "paper"})
    spreads_db.open_position(
        SpreadCandidate(
            spread_id="old",
            side="put",
            expiry=TODAY,
            short_strike=679,
            long_strike=674,
            width=5,
            short_con_id=6790,
            long_con_id=6740,
            credit_mid=0.6,
            credit_natural=0.55,
            spot=690,
            quote_time=T0945,
        ),
        mode="paper",
        contracts=1,
        credit=0.6,
        commission=1.3,
        now=T0945,
        perm_id=1,
    )
    clock = [T0945]
    svc, broker, notifier = make(tmp_path, clock, paper)
    await svc.start()
    assert svc.entries_blocked and "6790" in svc.entries_blocked
    svc.on_disconnect()
    assert svc.entries_blocked == "disconnected"
    broker.legs = {6790: -1.0, 6740: 1.0}
    await svc.start()
    assert svc.entries_blocked is None


async def test_a_failing_phase_never_kills_the_tick(tmp_path, spreads_db) -> None:
    clock = [T0945]
    svc, broker, notifier = make(tmp_path, clock, ONE_A_DAY)
    await svc.tick()
    clock[0] = T1005
    await svc.tick()
    broker.fail_requote = True
    clock[0] = T1100
    await svc.tick()  # manage raises inside; the tick must survive and alert once
    await svc.tick()
    assert sum("manage" in m for m in notifier.sent) == 1
    assert len(spreads_db.open_positions("shadow")) == 1


async def test_nothing_happens_on_a_weekend(tmp_path, spreads_db) -> None:
    clock = [SATURDAY]
    svc, broker, _ = make(tmp_path, clock)
    await svc.tick()
    assert broker.calls == []


async def test_run_idles_when_disabled_and_refuses_live(monkeypatch) -> None:
    import src.spreads.service as service

    def no_ib(*a, **k):
        raise AssertionError("must not connect")

    monkeypatch.setattr("ib_async.IB", no_ib)
    stop = asyncio.Event()
    stop.set()
    base = get_config()
    monkeypatch.setattr(
        service,
        "get_config",
        lambda: base.model_copy(
            update={"spreads": base.spreads.model_copy(update={"enabled": False})}
        ),
    )
    await service.run(stop)
    live = base.model_copy(
        update={
            "spreads": base.spreads.model_copy(update={"enabled": True}),
            "secrets": base.secrets.model_copy(update={"live_trading": True}),
        }
    )
    monkeypatch.setattr(service, "get_config", lambda: live)
    await service.run(stop)


# Tasks 4-5 note: the gamma-flip search is scipy-heavy, so a map refresh must not run on the
# event loop thread (it would stall the ib_async heartbeat).
async def test_the_gex_map_is_built_off_the_event_loop_thread(
    tmp_path, spreads_db, monkeypatch
) -> None:
    import threading

    import src.spreads.service as service

    seen: list[int] = []
    real = service.build_levels

    def spy(*a, **k):
        seen.append(threading.get_ident())
        return real(*a, **k)

    monkeypatch.setattr(service, "build_levels", spy)
    clock = [T0945]
    svc, _, _ = make(tmp_path, clock, ONE_A_DAY)
    await svc.tick()
    assert svc.levels is not None
    assert seen and seen[0] != threading.get_ident()


# ---------------------------------------------------------------- review fixes (paper mode)

PAPER = CFG.model_copy(update={"mode": "paper"})


def _paper_spread(st, spread_id="p1", contracts=2, at=T0945, expiry=TODAY):
    from src.common.schemas import SpreadCandidate

    return st.open_position(
        SpreadCandidate(
            spread_id=spread_id,
            side="put",
            expiry=expiry,
            short_strike=679,
            long_strike=674,
            width=5,
            short_con_id=6790,
            long_con_id=6740,
            credit_mid=0.6,
            credit_natural=0.55,
            spot=690,
            quote_time=at,
        ),
        mode="paper",
        contracts=contracts,
        credit=0.6,
        commission=2.6,
        now=at,
        perm_id=1,
    )


class RecordingExecutor:
    """Closes fill at 0.30 for whatever quantity is asked; opens report *open_result*."""

    def __init__(self, open_result=None) -> None:
        self.closes: list[int] = []
        self.opens = 0
        self.open_result = open_result

    async def open(self, c, contracts, recheck):
        from src.spreads.executor import FillResult

        self.opens += 1
        return self.open_result or FillResult(0, None, 0.0, reason="not_filled", order_ref="CS:x")

    async def close(self, pos, short_q, long_q, *, urgent):
        from src.spreads.executor import FillResult

        self.closes.append(pos.contracts)
        return FillResult(pos.contracts, 0.30, 1.3, order_ref=f"CS:{pos.spread_id}:X")


class PaperBroker(FakeBroker):
    def __init__(self, clock) -> None:
        super().__init__(clock)
        self.working: set[str] = set()
        # the profit-take quotes: mid 0.28 on a 0.60 credit
        self.leg_quotes = {
            (679.0, "P"): o(679, "P", 0.30, 0.34),
            (674.0, "P"): o(674, "P", 0.03, 0.05),
        }

    def working_refs(self):
        return self.working


def _paper(tmp_path, clock, executor):
    from src.spreads.service import SpreadsService

    broker = PaperBroker(clock)
    notifier = FakeNotifier()
    svc = SpreadsService(
        broker, executor, notifier, PAPER, halt_path=tmp_path / "halt", now=lambda: clock[0]
    )
    return svc, broker, notifier


# Review I1 — a close is capped at what the broker still holds (it may have filled during a drop).
async def test_a_paper_close_never_exceeds_what_the_broker_holds(tmp_path, spreads_db) -> None:
    _paper_spread(spreads_db, contracts=2)
    clock = [T1100]
    ex = RecordingExecutor()
    svc, broker, notifier = _paper(tmp_path, clock, ex)
    broker.legs = {6790: -1.0, 6740: 1.0}  # one of the two already closed at IBKR
    await svc.tick()
    assert ex.closes == [1]
    assert any("holds 1 of 2" in m for m in notifier.sent)
    (p,) = spreads_db.open_positions("paper")
    assert p.contracts == 1  # left for the operator to settle; never closed twice


async def test_a_paper_spread_the_broker_no_longer_holds_is_not_closed(
    tmp_path, spreads_db
) -> None:
    _paper_spread(spreads_db, contracts=1)
    clock = [T1100]
    ex = RecordingExecutor()
    svc, broker, notifier = _paper(tmp_path, clock, ex)
    broker.legs = {}
    await svc.tick()
    assert ex.closes == []  # a BUY combo now would open a reversed SPY spread nothing manages
    assert any("holds 0 of 1" in m for m in notifier.sent)


async def test_no_second_close_while_the_first_is_still_working(tmp_path, spreads_db) -> None:
    _paper_spread(spreads_db, contracts=1)
    clock = [T1100]
    ex = RecordingExecutor()
    svc, broker, _ = _paper(tmp_path, clock, ex)
    broker.legs = {6790: -1.0, 6740: 1.0}
    broker.working = {"CS:p1:X"}
    await svc.tick()
    assert ex.closes == []
    broker.working = set()
    await svc.tick()
    assert ex.closes == [1]


async def test_every_paper_tick_rereconciles_and_unblocks_once_consistent(
    tmp_path, spreads_db
) -> None:
    _paper_spread(spreads_db, contracts=1)
    clock = [T0945]
    svc, broker, notifier = _paper(tmp_path, clock, RecordingExecutor())
    broker.legs = {6790: -1.0, 6740: 1.0}
    await svc.start()
    assert svc.entries_blocked is None
    broker.legs = {6790: -1.0}  # the long leg vanished at the broker
    await svc.tick()
    assert svc.entries_blocked and "6740" in svc.entries_blocked
    assert not any("disagree" in m for m in notifier.sent)  # one tick of lag is not alerted
    await svc.tick()
    assert sum("disagree" in m for m in notifier.sent) == 1
    broker.legs = {6790: -1.0, 6740: 1.0}
    await svc.tick()
    assert svc.entries_blocked is None
    broker.working = {"CS:20261007-P680-675-100000"}  # an opening order still live at IBKR
    await svc.tick()
    assert svc.entries_blocked and "still working" in svc.entries_blocked


async def test_an_unresolved_open_blocks_entries(tmp_path, spreads_db) -> None:
    from src.spreads.executor import FillResult

    clock = [T0945]
    ex = RecordingExecutor(FillResult(0, None, 0.0, reason="cancel_unconfirmed", order_ref="CS:o"))
    svc, broker, notifier = _paper(tmp_path, clock, ex)
    await svc.tick()
    clock[0] = T1005
    await svc.tick()
    assert ex.opens == 1
    assert svc.entries_blocked and "cancel_unconfirmed" in svc.entries_blocked
    assert any("may still be live" in m for m in notifier.sent)


# Review I2 (trading core) — the Gateway down through the close still reaches the operator.
async def test_open_spreads_are_alerted_while_disconnected(tmp_path, spreads_db) -> None:
    _paper_spread(spreads_db, contracts=1)
    clock = [T1100]
    svc, _, notifier = _paper(tmp_path, clock, RecordingExecutor())
    await svc.while_disconnected()
    await svc.while_disconnected()
    assert svc.entries_blocked == "disconnected"
    assert sum("disconnected with 1 paper spread" in m for m in notifier.sent) == 1
    assert not any("URGENT" in m for m in notifier.sent)
    clock[0] = datetime(2026, 10, 7, 19, 46, tzinfo=UTC)  # 15:46 ET
    await svc.while_disconnected()
    assert sum("URGENT" in m for m in notifier.sent) == 1


async def test_nothing_is_alerted_while_disconnected_with_nothing_open(
    tmp_path, spreads_db
) -> None:
    clock = [T1100]
    svc, _, notifier = _paper(tmp_path, clock, RecordingExecutor())
    await svc.while_disconnected()
    assert notifier.sent == []


# Review minor — a spread past its expiry is not retried every tick; the operator is told how
# to settle it.
async def test_an_expired_but_open_spread_is_alerted_not_closed(tmp_path, spreads_db) -> None:
    from datetime import timedelta

    yesterday = TODAY - timedelta(days=1)
    _paper_spread(spreads_db, contracts=1, at=T0945 - timedelta(days=1), expiry=yesterday)
    clock = [T1100]
    ex = RecordingExecutor()
    svc, broker, notifier = _paper(tmp_path, clock, ex)
    broker.legs = {}
    await svc.tick()
    await svc.tick()
    assert ex.closes == []
    assert sum("spreads_resolve" in m and "expired" in m for m in notifier.sent) == 1


# Review minor — a map that fails to build never leaves the previous one in use.
async def test_a_failed_map_rebuild_drops_the_old_map(tmp_path, spreads_db, monkeypatch) -> None:
    import src.spreads.service as service

    clock = [T0945]
    svc, _, _ = make(tmp_path, clock, ONE_A_DAY)
    await svc.tick()
    assert svc.levels is not None

    def boom(*a, **k):
        raise RuntimeError("scipy blew up")

    monkeypatch.setattr(service, "build_levels", boom)
    clock[0] = datetime(2026, 10, 7, 14, 46, tzinfo=UTC)  # 10:46, an hour later: refresh due
    await svc.tick()
    assert svc.levels is None and svc.map_failed_at == clock[0]
