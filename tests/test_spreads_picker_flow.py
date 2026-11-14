from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from src.common.schemas import (
    SpreadBriefResult,
    SpreadDayPlan,
    SpreadLlmCall,
    SpreadMarketSnapshot,
    SpreadPick,
)
from src.spreads.executor import SpreadExecutor
from tests.test_spreads_service import (  # noqa: F401 — spreads_db is a fixture
    CFG,
    MOVE,
    ONE_A_DAY,
    T0931,
    T0945,
    T1005,
    T1100,
    FakeBroker,
    FakeNotifier,
    _flush,
    o,
    spreads_db,
)

# Claude's menu on the FakeBroker day: A = 680/675 (inside), B = 679/674 (the baseline pick),
# C = 678/673 (outer). The call side has no strike beyond its boundary.
EXTRA = [
    o(680, "P", 1.00, 1.06, delta=-0.14),
    o(675, "P", 0.25, 0.29),
    o(678, "P", 0.70, 0.76, delta=-0.11),
    o(673, "P", 0.15, 0.19),
]


def ai(cfg, **ai_kw):
    return cfg.model_copy(
        update={
            "ai": cfg.ai.model_copy(update={"enabled": True, **ai_kw}),
            "selection": cfg.selection.model_copy(update={"menu_size": 4}),
        }
    )


AI = ai(ONE_A_DAY)


class MenuBroker(FakeBroker):
    def __init__(self, clock):
        super().__init__(clock)
        for q in EXTRA:
            self.leg_quotes[(float(q.strike), q.right)] = q

    async def fetch_chain(self, **kw):
        snap = await super().fetch_chain(**kw)
        if kw["symbol"] == "SPY":
            snap = snap.model_copy(update={"options": [*snap.options, *EXTRA]})
        return snap


NEUTRAL = SpreadDayPlan(bias="neutral")


class FakePicker:
    def __init__(self, choice="C", *, fallback=None, delay=0.0, plan=NEUTRAL):
        self.choice, self.fallback, self.delay, self.plan = choice, fallback, delay, plan
        self.briefs: list = []
        self.picks: list = []

    async def brief(self, req):
        self.briefs.append(req)
        return SpreadBriefResult(
            plan=self.plan,
            market=SpreadMarketSnapshot(),
            call=SpreadLlmCall(model="fake", effort="", prompt_text="B"),
        )

    async def pick(self, req):
        self.picks.append(req)
        if self.delay:
            await asyncio.sleep(self.delay)
        return SpreadPick(
            choice=self.choice,
            reason="because",
            fallback_reason=self.fallback,
            market=SpreadMarketSnapshot(vix=17.0),
            call=SpreadLlmCall(model="fake", effort="", prompt_text="P"),
        )


async def settle() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


def make(tmp_path, clock, cfg=AI, picker=None, broker=None):
    from src.spreads.service import SpreadsService

    broker = broker or MenuBroker(clock)
    notifier = FakeNotifier()
    picker = picker or FakePicker()
    ex = SpreadExecutor(None, broker, cfg, now=lambda: clock[0])
    svc = SpreadsService(
        broker, ex, notifier, cfg, halt_path=tmp_path / "halt", now=lambda: clock[0], picker=picker
    )
    return svc, broker, notifier, picker


async def _decide(svc, clock):
    """09:45 map + brief; 10:05 menu (baseline opens); 10:05:30 the pick resolves."""
    clock[0] = T0945
    await svc.tick()
    await settle()
    clock[0] = T1005
    await svc.tick()
    await settle()
    clock[0] = T1005 + timedelta(seconds=30)
    await svc.tick()


async def test_claude_takes_an_outer_strike_and_the_baseline_takes_its_own(
    tmp_path,
    spreads_db,  # noqa: F811
) -> None:
    clock = [T0945]
    svc, _, notifier, picker = make(tmp_path, clock)
    await _decide(svc, clock)
    (main,) = spreads_db.open_positions("shadow")
    (base,) = spreads_db.open_positions("baseline")
    assert (main.short_strike, base.short_strike) == (678.0, 679.0)
    assert base.spread_id.endswith("-BL") and base.episode_key == main.episode_key
    (rec,) = spreads_db.picks()
    assert main.pick_id == rec.pick_id
    assert [(i.letter, i.position) for i in rec.menu] == [
        ("A", "inside"),
        ("B", "baseline"),
        ("C", "outer"),
    ]
    assert (rec.choice, rec.executed_letter, rec.filled, rec.fallback_reason) == (
        "C",
        "C",
        True,
        None,
    )
    assert rec.market.vix == 17.0 and rec.snapshot.plan_bias == "neutral"
    assert picker.picks[0].plan == SpreadDayPlan(bias="neutral")  # the brief fed the pick
    assert any("<b>Plan</b>" in m for m in notifier.seen)
    assert any(
        "Claude chose C</b> (outer)" in m and "Baseline: sold 679/674" in m for m in notifier.sent
    )


async def test_a_skip_trades_nothing_but_the_baseline_still_trades(tmp_path, spreads_db) -> None:  # noqa: F811
    clock = [T0945]
    svc, _, notifier, _ = make(tmp_path, clock, picker=FakePicker("skip"))
    await _decide(svc, clock)
    assert (
        spreads_db.open_positions("shadow") == []
        and len(spreads_db.open_positions("baseline")) == 1
    )
    (rec,) = spreads_db.picks()
    assert (rec.choice, rec.executed_letter) == ("skip", None)
    assert any("Claude skipped" in m for m in notifier.sent)


async def test_an_off_menu_letter_falls_back_to_the_baseline_item(tmp_path, spreads_db) -> None:  # noqa: F811
    clock = [T0945]
    svc, _, notifier, _ = make(tmp_path, clock, picker=FakePicker("Z"))
    await _decide(svc, clock)
    (main,) = spreads_db.open_positions("shadow")
    assert main.short_strike == 679.0
    (rec,) = spreads_db.picks()
    assert (rec.fallback_reason, rec.executed_letter) == ("off_menu", "B")
    assert any("picker failed (off_menu)" in m for m in notifier.sent)


async def test_a_picker_failure_falls_back_to_the_baseline_item(tmp_path, spreads_db) -> None:  # noqa: F811
    clock = [T0945]
    svc, _, _, _ = make(tmp_path, clock, picker=FakePicker("skip", fallback="unparseable"))
    await _decide(svc, clock)
    assert spreads_db.open_positions("shadow")[0].short_strike == 679.0
    assert spreads_db.picks()[0].fallback_reason == "unparseable"


async def test_a_hung_pick_times_out_without_holding_up_exits(tmp_path, spreads_db) -> None:  # noqa: F811
    clock = [T0945]
    svc, broker, _, _ = make(tmp_path, clock, picker=FakePicker(delay=3600))
    clock[0] = T0945
    await svc.tick()
    await settle()
    clock[0] = T1005
    await svc.tick()  # baseline opens at 679/674; the pick hangs
    assert svc._pending is not None
    broker.leg_quotes[(679.0, "P")] = o(679, "P", 0.30, 0.34)
    broker.leg_quotes[(674.0, "P")] = o(674, "P", 0.03, 0.05)
    clock[0] = T1005 + timedelta(seconds=40)
    await svc.tick()  # still waiting — but the baseline's profit take runs
    assert spreads_db.closed_results("baseline")[0][1] == "profit_take" and svc._pending is not None
    clock[0] = T1005 + timedelta(seconds=80)  # past 45 s + 30 s grace
    await svc.tick()
    assert svc._pending is None
    (rec,) = spreads_db.picks()
    assert (rec.fallback_reason, rec.executed_letter) == ("timeout", "B")
    assert rec.latency_ms is not None and rec.latency_ms >= 75_000  # the service's own wait


async def test_a_pick_resolving_after_entry_end_is_regated_and_not_sent(
    tmp_path,
    spreads_db,  # noqa: F811
) -> None:
    clock = [T0945]
    svc, _, _, _ = make(tmp_path, clock)
    await svc.tick()
    await settle()
    clock[0] = datetime(2026, 10, 7, 17, 29, 30, tzinfo=UTC)  # 13:29:30 ET, last check before 13:30
    await svc.tick()
    await settle()
    clock[0] = datetime(2026, 10, 7, 17, 30, 20, tzinfo=UTC)  # 13:30:20 ET
    await svc.tick()
    (rec,) = spreads_db.picks()
    assert rec.send_rejected and "outside_entry_window" in rec.send_reasons and not rec.filled
    assert spreads_db.open_positions("shadow") == []


async def test_a_fallback_without_a_baseline_item_trades_nothing(tmp_path, spreads_db) -> None:  # noqa: F811
    clock = [T0945]
    broker = MenuBroker(clock)
    wide = o(674, "P", 0.10, 0.30)  # 100% leg spread: the gate drops the baseline item B
    broker.leg_quotes[(674.0, "P")] = wide

    async def fetch(**kw):
        snap = await MenuBroker.fetch_chain(broker, **kw)
        if kw["symbol"] == "SPY":
            snap = snap.model_copy(
                update={
                    "options": [
                        wide if (x.strike, x.right) == (674, "P") else x for x in snap.options
                    ]
                }
            )
        return snap

    broker.fetch_chain = fetch  # type: ignore[method-assign]
    svc, _, _, _ = make(
        tmp_path, clock, picker=FakePicker("skip", fallback="timeout"), broker=broker
    )
    await _decide(svc, clock)
    (rec,) = spreads_db.picks()
    assert [i.position for i in rec.menu] == ["inside", "outer"]
    assert rec.executed_letter is None and rec.send_reasons == ["no_baseline_item"]
    assert spreads_db.open_positions("shadow") == [] and spreads_db.open_positions("baseline") == []


async def test_the_daily_cap_stops_main_entries_and_alerts_once(tmp_path, spreads_db) -> None:  # noqa: F811
    cfg = ai(CFG, max_pick_calls_per_day=1)  # CFG: every check is its own episode, 2 trades/day
    clock = [T0945]
    svc, _, notifier, picker = make(tmp_path, clock, cfg=cfg, picker=FakePicker("skip"))
    await _decide(svc, clock)
    clock[0] = T1100
    await svc.tick()
    await settle()
    assert len(picker.picks) == 1
    assert sum("pick calls used today" in m for m in notifier.sent) == 1
    assert len(spreads_db.open_positions("baseline")) == 2  # the baseline is not capped


async def test_a_skip_stands_for_its_episode_even_across_a_restart(tmp_path, spreads_db) -> None:  # noqa: F811
    cfg = ai(MOVE)
    clock = [T0931]
    svc, broker, _, picker = make(tmp_path, clock, cfg=cfg, picker=FakePicker("skip"))
    await _flush(svc, broker, clock)  # low 689.80 at 09:36, holding
    clock[0] = datetime(2026, 10, 7, 13, 47, tzinfo=UTC)  # armed: stalled 11 min
    await svc.tick()
    await settle()
    clock[0] = datetime(2026, 10, 7, 13, 47, 30, tzinfo=UTC)
    await svc.tick()
    assert len(picker.picks) == 1 and spreads_db.picks()[0].choice == "skip"
    clock[0] = datetime(2026, 10, 7, 13, 53, tzinfo=UTC)  # next check, same low: no new call
    await svc.tick()
    await settle()
    assert len(picker.picks) == 1
    # Restart: a fresh service rebuilds the tape from the session stats, same 689.80 low.
    svc2, _, _, picker2 = make(tmp_path, clock, cfg=cfg, picker=FakePicker("C"), broker=broker)
    for minute in (54, 59, 65):
        clock[0] = datetime(2026, 10, 7, 13, 0, tzinfo=UTC) + timedelta(minutes=minute)
        await svc2.tick()
        await settle()
    assert picker2.picks == []  # the episode was already decided before the restart


async def test_the_brief_runs_once_a_day(tmp_path, spreads_db) -> None:  # noqa: F811
    clock = [T0945]
    svc, _, _, picker = make(tmp_path, clock)
    await svc.tick()
    await settle()
    clock[0] = T0945 + timedelta(minutes=61)  # map refresh
    await svc.tick()
    await settle()
    assert len(picker.briefs) == 1 and spreads_db.day_plan(T0945.date()) == SpreadDayPlan(
        bias="neutral"
    )


async def test_a_halt_during_the_pick_records_it_without_trading(tmp_path, spreads_db) -> None:  # noqa: F811
    clock = [T0945]
    svc, _, _, _ = make(tmp_path, clock)
    await svc.tick()
    await settle()
    clock[0] = T1005
    await svc.tick()
    await settle()
    (tmp_path / "halt").touch()
    clock[0] = T1005 + timedelta(seconds=30)
    await svc.tick()
    (rec,) = spreads_db.picks()
    assert rec.send_reasons == ["halted"] and spreads_db.open_positions("shadow") == []


# ------------------------------------------------------------ checkpoint B: pin the invariants

SLIP = AI.execution.shadow_slippage_per_leg


def _reprice_outer(broker, bid, ask) -> None:
    """Move the market under Claude's pick C (678/673) between the menu and the send."""
    broker.leg_quotes[(678.0, "P")] = o(678, "P", bid, ask, delta=-0.11)


async def _to_pending(svc, clock) -> None:
    """09:45 map + brief; 10:05 menu (baseline opens, the pick is in flight)."""
    clock[0] = T0945
    await svc.tick()
    await settle()
    clock[0] = T1005
    await svc.tick()
    await settle()
    assert svc._pending is not None


async def test_the_send_uses_the_requoted_credit_not_the_menus(tmp_path, spreads_db) -> None:  # noqa: F811
    clock = [T0945]
    svc, broker, _, _ = make(tmp_path, clock)
    await _to_pending(svc, clock)
    menu_mid = svc._pending.menu[2].candidate.credit_mid
    assert menu_mid == pytest.approx(0.56)  # 678: 0.73 mid, 673: 0.17 mid
    _reprice_outer(broker, 0.80, 0.86)  # the short now mids 0.83: a 0.66 credit
    clock[0] = T1005 + timedelta(seconds=30)
    await svc.tick()
    (main,) = spreads_db.open_positions("shadow")
    assert main.entry_credit == pytest.approx(0.66 - 2 * SLIP)  # not 0.56 - 2 * SLIP
    assert main.entry_credit != pytest.approx(menu_mid - 2 * SLIP)


async def test_the_contract_count_comes_from_the_regate_not_the_menu(tmp_path, spreads_db) -> None:  # noqa: F811
    roomy = AI.model_copy(update={"risk": AI.risk.model_copy(update={"max_contracts": 100})})
    clock = [T0945]
    svc, broker, _, _ = make(tmp_path, clock, cfg=roomy)
    broker.nlv = 612_000.0  # 0.5% = $3,060 of max loss per trade
    await _to_pending(svc, clock)
    assert svc._pending.menu[2].contracts == 6  # ⌊$3,060 ÷ ((5 − 0.56) × 100)⌋
    _reprice_outer(broker, 0.80, 0.86)  # a richer credit risks less per contract: 7 fit
    clock[0] = T1005 + timedelta(seconds=30)
    await svc.tick()
    (main,) = spreads_db.open_positions("shadow")
    assert main.contracts == 7


# 09:47 ET arms the put side (low 689.80 stalled 11 min); the baseline book may take two trades
# a day, so only the per-episode rule keeps it to one spread per episode.
TWO_A_DAY = ai(
    MOVE.model_copy(
        update={
            "risk": MOVE.risk.model_copy(update={"max_trades_per_day": 2, "max_open_spreads": 2})
        }
    )
)
T1347 = datetime(2026, 10, 7, 13, 47, tzinfo=UTC)


async def _armed_skip(svc, broker, clock) -> None:
    await _flush(svc, broker, clock)  # low 689.80 at 09:36, holding
    clock[0] = T1347
    await svc.tick()
    await settle()
    clock[0] = T1347 + timedelta(seconds=30)
    await svc.tick()


async def test_the_baseline_takes_one_spread_per_episode(tmp_path, spreads_db) -> None:  # noqa: F811
    clock = [T0931]
    svc, broker, _, picker = make(tmp_path, clock, cfg=TWO_A_DAY, picker=FakePicker("skip"))
    await _armed_skip(svc, broker, clock)
    assert len(spreads_db.open_positions("baseline")) == 1 and len(picker.picks) == 1
    for minute in (53, 58):  # two more entry checks inside the same armed episode
        clock[0] = datetime(2026, 10, 7, 13, minute, tzinfo=UTC)
        await svc.tick()
        await settle()
    assert len(picker.picks) == 1
    assert len(spreads_db.open_positions("baseline")) == 1  # not one per five-minute check


async def test_a_new_session_extreme_is_a_new_episode(tmp_path, spreads_db) -> None:  # noqa: F811
    clock = [T0931]
    svc, broker, _, picker = make(tmp_path, clock, cfg=TWO_A_DAY, picker=FakePicker("skip"))
    await _armed_skip(svc, broker, clock)
    assert len(picker.picks) == 1
    broker.session.update(last=689.2, low=689.2)  # a new low, then it stalls again
    clock[0] = datetime(2026, 10, 7, 13, 55, tzinfo=UTC)
    await svc.tick()
    clock[0] = datetime(2026, 10, 7, 14, 7, tzinfo=UTC)  # 12 minutes after the new low
    await svc.tick()
    await settle()
    clock[0] = datetime(2026, 10, 7, 14, 7, 30, tzinfo=UTC)
    await svc.tick()
    assert len(picker.picks) == 2
    first, second = spreads_db.picks()
    assert first.episode_key != second.episode_key and "689.20" in second.episode_key
    assert len(spreads_db.open_positions("baseline")) == 2  # one per episode


class RaisingPicker(FakePicker):
    async def pick(self, req):
        self.picks.append(req)
        raise RuntimeError("the CLI exploded")


async def test_a_picker_that_raises_falls_back_to_the_baseline_item(tmp_path, spreads_db) -> None:  # noqa: F811
    clock = [T0945]
    svc, _, notifier, _ = make(tmp_path, clock, picker=RaisingPicker())
    await _decide(svc, clock)
    assert svc._pending is None
    (main,) = spreads_db.open_positions("shadow")
    assert main.short_strike == 679.0
    (rec,) = spreads_db.picks()
    assert (rec.fallback_reason, rec.executed_letter, rec.filled) == ("picker_error", "B", True)
    assert any("picker failed (picker_error)" in m for m in notifier.sent)


class ExplodingExecutor:
    async def open(self, c, contracts, recheck):
        raise RuntimeError("socket died inside the send")


async def test_an_error_inside_the_send_marks_the_row_and_clears_the_pick(
    tmp_path,
    spreads_db,  # noqa: F811
) -> None:
    clock = [T0945]
    svc, _, notifier, _ = make(tmp_path, clock)
    svc.executor = ExplodingExecutor()
    await _decide(svc, clock)
    assert svc._pending is None
    (rec,) = spreads_db.picks()
    assert rec.send_rejected and rec.send_reasons == ["send_error"] and not rec.filled
    assert any("the pick phase failed" in m for m in notifier.sent)
    assert spreads_db.open_positions("shadow") == []


class NoSpotBroker(MenuBroker):
    """The index quote drops out after the menu is built (``spot`` answers None)."""

    spot_gone = False

    async def spot(self):
        return None if self.spot_gone else await super().spot()


async def test_a_pick_is_not_sent_without_a_fresh_spot(tmp_path, spreads_db) -> None:  # noqa: F811
    clock = [T0945]
    broker = NoSpotBroker(clock)
    svc, _, _, _ = make(tmp_path, clock, broker=broker)
    await _to_pending(svc, clock)
    broker.spot_gone = True
    clock[0] = T1005 + timedelta(seconds=30)
    await svc.tick()
    (rec,) = spreads_db.picks()
    assert rec.send_rejected and rec.send_reasons == ["no_fresh_spot"] and not rec.filled
    assert spreads_db.open_positions("shadow") == []
    assert svc._pending is None


async def test_a_pick_that_finished_long_ago_is_recorded_but_not_sent(
    tmp_path,
    spreads_db,  # noqa: F811
) -> None:
    clock = [T0945]
    svc, _, _, _ = make(tmp_path, clock)
    await _to_pending(svc, clock)  # the picker answers at once; nobody collects it for a while
    assert svc._pending.task.done()
    clock[0] = T1005 + timedelta(seconds=151)  # > 2 x (45 s timeout + 30 s grace), e.g. a reconnect
    await svc.tick()
    (rec,) = spreads_db.picks()
    assert (rec.choice, rec.executed_letter) == ("C", "C")
    assert rec.send_rejected and rec.send_reasons == ["stale_pick"] and not rec.filled
    assert spreads_db.open_positions("shadow") == [] and svc._pending is None


# ------------------------------------------------------------ final review: I1, M2


async def test_a_pick_the_regate_refuses_is_reported_not_sent_not_as_a_take(
    tmp_path,
    spreads_db,  # noqa: F811
) -> None:
    from src.spreads import store
    from src.spreads.report import build_decisions, compare_by

    clock = [T0945]
    svc, broker, _, _ = make(tmp_path, clock)
    await _to_pending(svc, clock)
    _reprice_outer(broker, 0.25, 0.29)  # the short mids 0.27 against the 0.17 long: 0.10 credit
    clock[0] = T1005 + timedelta(seconds=30)
    await svc.tick()
    (rec,) = spreads_db.picks()
    assert (rec.choice, rec.executed_letter) == ("C", "C")
    assert rec.send_rejected and not rec.filled and "credit_below_min" in rec.send_reasons
    assert spreads_db.open_positions("shadow") == []
    (base,) = spreads_db.open_positions("baseline")
    decisions = build_decisions(
        store.picks(), store.trade_log("shadow"), store.trade_log("baseline")
    )
    assert [d.kind for d in decisions] == ["not_sent"]
    assert decisions[0].main_pnl is None and base.episode_key == rec.episode_key
    assert compare_by(decisions, "regime") == {}


class DriftingExcessBroker(MenuBroker):
    """Excess liquidity is healthy when the menu is built and gone by the time the pick sends."""

    def __init__(self, clock):
        super().__init__(clock)
        self.excess: float | None = 400_000.0
        self.reads = 0

    async def excess_liquidity(self):
        self.reads += 1
        return self.excess


async def test_the_send_regates_on_fresh_excess_liquidity(tmp_path, spreads_db) -> None:  # noqa: F811
    clock = [T0945]
    broker = DriftingExcessBroker(clock)
    svc, _, _, _ = make(tmp_path, clock, broker=broker)
    await _to_pending(svc, clock)
    broker.excess = 1_000.0  # below the floor (40% of NLV) now
    clock[0] = T1005 + timedelta(seconds=30)
    await svc.tick()
    (rec,) = spreads_db.picks()
    assert rec.send_rejected and rec.send_reasons == ["excess_liquidity_floor"]
    assert spreads_db.open_positions("shadow") == []


async def test_an_unreadable_excess_liquidity_at_send_time_blocks_the_send(
    tmp_path,
    spreads_db,  # noqa: F811
) -> None:
    clock = [T0945]
    broker = DriftingExcessBroker(clock)
    svc, _, _, _ = make(tmp_path, clock, broker=broker)
    await _to_pending(svc, clock)
    broker.excess = None
    clock[0] = T1005 + timedelta(seconds=30)
    await svc.tick()
    (rec,) = spreads_db.picks()
    assert rec.send_rejected and rec.send_reasons == ["account_unknown"]


async def test_the_compare_report_says_what_it_is_scoped_to(
    tmp_path,
    spreads_db,  # noqa: F811
    monkeypatch,
    capsys,
) -> None:
    import sys

    from scripts import spreads_report

    clock = [T0945]
    svc, _, _, _ = make(tmp_path, clock)
    await _decide(svc, clock)
    monkeypatch.setattr(sys, "argv", ["spreads_report", "--mode", "shadow", "--compare"])
    spreads_report.main()
    out = capsys.readouterr().out
    assert "scope: --mode shadow picks only, trades opened since the first pick" in out
    assert "pre-AI trades excluded" in out and "took_outer: n=1" not in out  # still open, unsettled
    assert "decisions: 1 (0 settled)" in out


async def test_the_day_view_shows_only_the_requested_main_mode(
    tmp_path,
    spreads_db,  # noqa: F811
    monkeypatch,
    capsys,
) -> None:
    import sys

    import pytest

    from scripts import spreads_report

    clock = [T0945]
    svc, _, _, _ = make(tmp_path, clock)
    await _decide(svc, clock)  # a shadow-mode pick
    day = "2026-10-07"
    for mode, shown in (("shadow", True), ("paper", False)):
        monkeypatch.setattr(sys, "argv", ["spreads_report", "--mode", mode, "--day", day])
        spreads_report.main()
        assert ("--- pick " in capsys.readouterr().out) is shown, mode
    monkeypatch.setattr(sys, "argv", ["spreads_report", "--mode", "baseline", "--day", day])
    with pytest.raises(SystemExit):
        spreads_report.main()
