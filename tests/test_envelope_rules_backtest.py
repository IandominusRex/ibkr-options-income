"""The tech-cap and stacking backtest (risk-envelope plan Task 27; spec §3.4.4, ruling E15).

Synthetic situations and a synthetic trading DB only; the rules under test are the production
functions in ``src/engine/regime_limits.py``.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path

from scripts import envelope_rules_backtest as bt
from src.common.schemas import PositionSnapshot
from src.storage import envelope_switches as sw

NOW = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
D = date(2026, 10, 20)
EXP = date(2026, 11, 20)


def _stock(sym: str, mv: float) -> PositionSnapshot:
    return PositionSnapshot(
        symbol=sym,
        sec_type="STK",
        position=100.0,
        avg_cost=1.0,
        market_value=mv,
        market_price=mv / 100,
    )


def _short_put(sym: str, strike: float, expiry: date) -> PositionSnapshot:
    return PositionSnapshot(
        symbol=f"{sym}P",
        sec_type="OPT",
        position=-1.0,
        avg_cost=1.0,
        right="P",
        strike=strike,
        expiry=expiry,
        underlying=sym,
    )


def _sit(
    key: str,
    sym: str = "NVDA",
    *,
    positions: tuple[PositionSnapshot, ...] = (),
    fills: int = 0,
    spot: float = 130.0,
    strike: float = 100.0,
    contracts: int = 2,
) -> bt.Situation:
    return bt.Situation(key, sym, strike, EXP, contracts, spot, 100_000.0, positions, fills)


# A book already holding 55k of tech: the 60k cap leaves 5k, and a 100-strike put is 10k.
TECH_FULL = (_stock("NVDA", 55_000.0),)
STACKED = (_short_put("XOM", 95.0, date(2026, 11, 23)),)  # 3 days from EXP, out of the money
ITM = (_short_put("XOM", 140.0, date(2026, 12, 18)),)  # strike above the 130 spot


def _acts():
    ctx = bt._context()
    return (
        lambda s: bt.tech_cap_action(s, ctx, 60.0),
        lambda s: bt.stacking_rule_action(s, 7, 2),
    )


def test_the_backtest_replays_the_ten_claude_cut_rows() -> None:
    tech, stack = _acts()
    # ten cut rows: seven the tech cap trims or blocks (a tech name with the book full of tech),
    # five the stacking rule halves or blocks (an overlapping short, an ITM short, two same-day fills)
    cuts = (
        [bt.Opening(_sit(f"t{i}", "NVDA", positions=TECH_FULL), cut=True) for i in range(7)]
        + [bt.Opening(_sit("s1", "XOM", positions=STACKED), cut=True)]
        + [bt.Opening(_sit("s2", "XOM", positions=ITM), cut=True)]
        + [bt.Opening(_sit("s3", "XOM", fills=2), cut=True)]
    )
    assert len(cuts) == 10
    assert sum(tech(o.situation) != "none" for o in cuts) == 7
    assert sum(stack(o.situation) != "none" for o in cuts) == 3
    assert tech(cuts[0].situation) == "block"  # room 5k, a 100 put at 10k: not one lot fits
    assert stack(cuts[8].situation) == "block" and stack(cuts[7].situation) == "trim"
    wins = [bt.Opening(_sit(f"w{i}", "XOM"), cut=False, profitable=True) for i in range(4)]
    tech_result = bt.judge("E15_tech_cap", "tech_cap", cuts + wins, tech, now=NOW)
    stack_result = bt.judge("E15_stacking", "stacking_rule", cuts + wins, stack, now=NOW)
    # tech: 7 of 10 >= 6 and no profitable open blocked -> PASS; stacking: 3 of 10 < 6 -> FAIL
    assert tech_result.passed is True and tech_result.metrics["cut_rows_trimmed_or_blocked"] == 7
    assert stack_result.passed is False and stack_result.metrics["cut_rows_needed"] == 6.0


def test_the_false_block_rate_uses_profitable_uncut_opens() -> None:
    tech, _ = _acts()
    cuts = [bt.Opening(_sit(f"t{i}", "NVDA", positions=TECH_FULL), cut=True) for i in range(10)]

    def wins(blocked: int, total: int) -> list[bt.Opening]:
        # `blocked` profitable opens on a full tech book (blocked), the rest on a name the cap ignores
        hit = [
            bt.Opening(_sit(f"b{i}", "NVDA", positions=TECH_FULL), cut=False, profitable=True)
            for i in range(blocked)
        ]
        ok = [
            bt.Opening(_sit(f"o{i}", "XOM"), cut=False, profitable=True)
            for i in range(total - blocked)
        ]
        return hit + ok

    # a loss the rule would block, an open one, and a cut row are not "profitable uncut opens"
    noise = [
        bt.Opening(_sit("loss", "NVDA", positions=TECH_FULL), cut=False, profitable=False),
        bt.Opening(_sit("open", "NVDA", positions=TECH_FULL), cut=False, profitable=None),
    ]
    edge = bt.judge("E15_tech_cap", "tech_cap", cuts + wins(2, 8) + noise, tech, now=NOW)
    assert edge.metrics["profitable_uncut_opens"] == 8.0
    assert edge.metrics["profitable_blocked"] == 2.0 and edge.metrics["false_block_rate"] == 0.25
    assert edge.passed is True  # 25% is the ceiling, inclusive
    over = bt.judge("E15_tech_cap", "tech_cap", cuts + wins(3, 8) + noise, tech, now=NOW)
    assert over.metrics["false_block_rate"] == 0.375 and over.passed is False
    # without a profitable uncut open there is nothing to measure the false-block rate on
    none_yet = bt.judge("E15_tech_cap", "tech_cap", cuts + noise, tech, now=NOW)
    assert none_yet.passed is None
    # and fewer than ten cut rows is no result either
    few = bt.judge("E15_tech_cap", "tech_cap", cuts[:5] + wins(0, 4), tech, now=NOW)
    assert few.passed is None


def test_each_rule_writes_its_own_result(tmp_path: Path, monkeypatch) -> None:
    tech, stack = _acts()
    cuts = [bt.Opening(_sit(f"t{i}", "NVDA", positions=TECH_FULL), cut=True) for i in range(10)]
    wins = [bt.Opening(_sit(f"w{i}", "XOM"), cut=False, profitable=True) for i in range(4)]
    a = bt.judge("E15_tech_cap", "tech_cap", cuts + wins, tech, now=NOW)
    b = bt.judge("E15_stacking", "stacking_rule", cuts + wins, stack, now=NOW)
    pa, pb = bt.write_result(a, tmp_path), bt.write_result(b, tmp_path)
    assert (pa.name, pb.name) == ("E15_tech_cap.json", "E15_stacking.json")
    assert (a.switch, b.switch) == ("tech_cap", "stacking_rule")
    assert a.passed is True and b.passed is False  # the rules are judged separately

    import src.storage.db as dbmod
    from src.common.config import Config

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{tmp_path / 't.db'}")
    dbmod.init_db()
    notices = sw.apply_reports(tmp_path)
    assert len(notices) == 1 and sw.get_switch("tech_cap") == "on"
    assert sw.get_switch("stacking_rule") == "off"  # a FAIL turns nothing on, or off


# --------------------------------------------------------------------------- the estate reader


def test_the_reader_rebuilds_each_open_from_the_estate_read_only(db) -> None:
    from src.reporting.replay import trading_db_path
    from src.storage.models import (
        FillRow,
        OrderRow,
        PortfolioSnapshotRow,
        PriceHistoryRow,
        SizingActionRow,
    )

    account = {
        "account": "DU1",
        "net_liquidation": 100_000.0,
        "total_cash": 10_000.0,
        "buying_power": 1.0,
        "maintenance_margin": 1.0,
        "excess_liquidity": 1.0,
    }
    stock = _stock("NVDA", 55_000.0).model_dump(mode="json")
    t0 = datetime(2026, 10, 20, 14, 0)  # naive UTC, 10:00 ET

    def order(cid: str, sym: str, strike: float, n: int, at: datetime) -> OrderRow:
        snap = {
            "strategy": "cash_secured_put",
            "underlying": sym,
            "strike": strike,
            "expiry": "2026-11-20",
            "contracts": n,
        }
        return OrderRow(
            candidate_id=cid, state="filled", filled_qty=float(n), snapshot=snap, created_at=at
        )

    with db() as s:
        s.add(
            PortfolioSnapshotRow(
                captured_at=datetime(2026, 10, 20, 13, 0),
                source="monitor",
                account=account,
                positions=[stock],
            )
        )
        for i in range(10):
            s.add(
                SizingActionRow(
                    candidate_id=f"cut{i}",
                    underlying="NVDA",
                    strategy="cash_secured_put",
                    right="P",
                    strike=100.0,
                    expiry=date(2026, 11, 20),
                    premium=1.0,
                    kind="claude_cut",
                    regime="normal",
                    deterministic_contracts=2,
                    sent_contracts=1,
                    action_day=date(2026, 10, 20),
                    record_key=f"cut{i}",
                    created_at=t0,
                )
            )
        # two uncut opens on a non-tech name: one bought back for a profit, one for a loss
        s.add(order("win", "XOM", 100.0, 1, t0))
        s.add(order("lose", "XOM", 100.0, 1, t0))
        s.flush()
        for cid, close in (("win", 0.5), ("lose", 3.0)):
            s.add(
                FillRow(
                    order_id=1,
                    candidate_id=cid,
                    action="SELL",
                    filled_qty=1.0,
                    avg_price=1.0,
                    commission=1.0,
                )
            )
            s.add(
                FillRow(
                    order_id=1,
                    candidate_id=cid,
                    action="BUY",
                    filled_qty=1.0,
                    avg_price=close,
                    commission=1.0,
                )
            )
        s.add(
            PriceHistoryRow(
                symbol="XOM", obs_date=date(2026, 10, 19), open=1, high=1, low=1, close=110.0
            )
        )

    path = trading_db_path()
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    text, results = bt.run(path)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert results is not None, text
    tech, stack = results["E15_tech_cap"], results["E15_stacking"]
    assert tech.metrics["cut_rows"] == 10.0 and tech.metrics["cut_rows_trimmed_or_blocked"] == 10.0
    assert tech.metrics["profitable_uncut_opens"] == 1.0  # only the bought-back winner
    assert tech.passed is True
    # the second XOM open the same morning sees the first as a same-day fill, but not enough to block
    assert stack.metrics["cut_rows_trimmed_or_blocked"] == 0.0 and stack.passed is False
    assert json.loads(tech.model_dump_json())["switch"] == "tech_cap"


def test_a_missing_database_writes_nothing(tmp_path: Path) -> None:
    text, results = bt.run(tmp_path / "absent.db")
    assert results is None and "nothing to replay" in text
