"""The value process's nightly run (value book spec §6.8, §6.9): when a run is due, what it
scores, the follow window, one transaction per night, and the idle-on-a-stale-ruleset check."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import pandas as pd
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import src.common.value_inputs as vi
import src.value.store as store
from src.common.config import get_config
from src.common.value_types import MarketFacts
from src.common.value_universe import ValueUniverse
from src.research.store.models import Base, CompanyFactsRawRow, DailyBarRow, SymbolRow
from src.value import service
from src.value.scorecard import build_scorecard
from src.value.store import (
    ValueRunRow,
    ValueShadowRow,
    ValueTickerFileRow,
    ValueTickerHistoryRow,
    init_value_db,
    record_run,
    value_session,
)
from tests.value_fixtures import AS_OF, companyfacts, price

# 07:00 ET on the session after AS_OF (2026-03-31): its bar may be forming, so AS_OF is scored.
NOW = datetime(2026, 4, 1, 11, 0)


def test_a_run_is_due_for_a_new_settled_session_after_the_hour() -> None:
    at = datetime(2026, 4, 1, 7, 0)
    assert service.is_due(at, AS_OF, None, 6)
    assert service.is_due(at, AS_OF, AS_OF - timedelta(days=1), 6)
    assert not service.is_due(at, AS_OF, AS_OF, 6)  # already scored
    assert not service.is_due(at, None, None, 6)  # no SPY bar at all
    assert not service.is_due(at.replace(hour=5), AS_OF, None, 6)  # the sweep may still run


@pytest.fixture()
def dbs(tmp_path, monkeypatch):
    research = tmp_path / "research.db"
    engine = create_engine(f"sqlite:///{research}")
    Base.metadata.create_all(engine)
    closes = price(30.0).closes
    days = pd.bdate_range(end=AS_OF, periods=len(closes)).date
    with Session(engine) as s:
        s.add(SymbolRow(symbol="STDY", cik="0000000001", name="Steady Co"))
        s.add(
            CompanyFactsRawRow(
                cik="0000000001",
                payload_json=json.dumps(companyfacts()),
                fetched_at=datetime(2026, 3, 30),
            )
        )
        for d, c in zip(days, closes, strict=True):
            s.add(DailyBarRow(symbol="STDY", date=d, open=c, high=c, low=c, close=c, volume=1e6))
            s.add(DailyBarRow(symbol="SPY", date=d, open=500, high=500, low=500, close=500.0))
        # A bar dated "today" (2026-04-01) that may still be forming: never scored.
        s.add(
            DailyBarRow(symbol="SPY", date=date(2026, 4, 1), open=501, high=501, low=501, close=501)
        )
        s.commit()
    monkeypatch.setattr(vi, "_resolve_path", lambda: str(research))
    vi.reset_engine()
    monkeypatch.setattr(
        store, "_resolve_url", lambda: f"sqlite:///{(tmp_path / 'value.db').as_posix()}"
    )
    store.reset_engine()
    init_value_db()
    monkeypatch.setattr(vi, "load_regime", lambda: "normal")
    monkeypatch.setattr(
        service,
        "build_value_universe",
        lambda cfg, universe: ValueUniverse(
            trading=["STDY"],
            evidence=["STDY"],
            classification={"STDY": ("Information Technology", "Application Software")},
        ),
    )
    yield
    vi.reset_engine()
    store.reset_engine()


def test_the_plan_scores_the_newest_settled_session_and_every_name(dbs) -> None:
    with value_session() as s:
        s.add(_file("LOOK", "lookup", viewed=NOW - timedelta(days=10)))
        s.add(_file("GONE", "lookup", viewed=NOW - timedelta(days=40)))
    plan = service.plan_run(NOW, universe={})
    assert plan is not None and plan.as_of == AS_OF  # not the forming 2026-04-01 bar
    assert plan.tags == {"STDY": "trading", "LOOK": "lookup"}  # GONE's window expired
    assert service.plan_run(NOW.replace(hour=9), universe={}) is None  # 05:00 ET: too early


def test_a_night_waits_until_the_research_sweep_has_filed_the_universe(dbs, monkeypatch) -> None:
    monkeypatch.setattr(
        service,
        "build_value_universe",
        lambda cfg, universe: ValueUniverse(trading=["STDY", "NEW"], evidence=["STDY", "NEW"]),
    )
    assert service.plan_run(NOW, universe={}) is None  # filings for 1 of 2 names: 50% < 90%
    monkeypatch.setattr(get_config().value.service, "min_filings_coverage_pct", 50.0)
    assert service.plan_run(NOW, universe={}) is not None


def test_a_session_already_scored_is_not_run_again(dbs) -> None:
    with value_session() as s:
        record_run(
            s,
            kind="nightly",
            started_at=NOW,
            finished_at=NOW,
            as_of=AS_OF,
            ruleset_version="v2",
            ruleset_hash="x",
            names=1,
            rs_cutoff_6m=None,
            summary_json="{}",
        )
    assert service.plan_run(NOW, universe={}) is None


def test_a_night_scores_persists_and_opens_the_shadow_record(dbs) -> None:
    plan = service.plan_run(NOW, universe={})
    assert plan is not None
    out = service.run_nightly(
        plan,
        facts={"STDY": MarketFacts(market_cap=3.0e9)},
        earnings={"STDY": AS_OF + timedelta(days=60)},
        now=NOW,
    )
    assert out["verdicts"]["deep_value"] == {"READY": 1}
    assert out["shadow"]["opened"] == {"ready": 2, "control_valuation": 0, "control_health": 0}
    assert out["shadow"]["ranked_formed"] == 0  # one name: no tenth to form
    with value_session() as s:
        row = s.get(ValueTickerFileRow, "STDY")
        assert (row.universe, row.verdict_deep, row.filed_list) == (
            "trading",
            "READY",
            "deep_value",
        )
        assert s.scalars(select(ValueTickerHistoryRow)).first() is not None
        run = s.scalars(select(ValueRunRow)).one()
        assert (run.kind, run.as_of, run.ruleset_version) == ("nightly", AS_OF, "v2")
        assert {r.status for r in s.scalars(select(ValueShadowRow))} == {"pending"}
    assert service.plan_run(NOW, universe={}) is None  # done for AS_OF


def test_a_held_name_that_left_the_universe_is_scored_but_not_eligible_to_enter(dbs) -> None:
    """Review I4(b): GONE has an open shadow entry but is in neither universe. It is scored
    nightly under ``held:<universe>``, and ``open_signals`` opens entries only for current members."""
    from src.value import shadow
    from tests.value_fixtures import inputs

    gone = build_scorecard(inputs(symbol="GONE", close=30.0), get_config().value)
    with value_session() as s:
        shadow.open_signals(s, [gone], {"GONE": "evidence"}, {}, live_policy="value", now=NOW)
    plan = service.plan_run(NOW, universe={})
    assert plan is not None
    assert plan.tags == {"STDY": "trading", "GONE": "held:evidence"}
    assert shadow.SHADOW_UNIVERSES == ("trading", "evidence")
    with value_session() as s:
        for row in s.scalars(select(ValueShadowRow)):
            row.status = "void"  # nothing blocks a re-entry now
        assert shadow.open_signals(s, [gone], plan.tags, {}, live_policy="value", now=NOW) == {
            "ready": 0,
            "control_valuation": 0,
            "control_health": 0,
        }


def test_a_night_writes_the_keep_fresh_list_for_the_research_sweep(dbs) -> None:
    """Review I4(a): the names the shadow record holds are handed to the sweep as a plain file."""
    import src.common.value_keep_fresh as kf

    plan = service.plan_run(NOW, universe={})
    assert plan is not None
    assert kf.read_keep_fresh() == []
    service.run_nightly(
        plan,
        facts={"STDY": MarketFacts(market_cap=3.0e9)},
        earnings={"STDY": AS_OF + timedelta(days=60)},
        now=NOW,
    )
    assert kf.read_keep_fresh() == ["STDY"]  # tonight's pending entries


def test_a_failed_night_leaves_the_keep_fresh_list_alone(dbs, monkeypatch) -> None:
    import src.common.value_keep_fresh as kf

    kf.write_keep_fresh(["OLD"])
    plan = service.plan_run(NOW, universe={})
    assert plan is not None
    monkeypatch.setattr(service.shadow, "process", lambda *a, **k: 1 / 0)
    with pytest.raises(ZeroDivisionError):
        service.run_nightly(plan, facts={}, earnings={}, now=NOW)
    assert kf.read_keep_fresh() == ["OLD"]


def test_a_failed_night_leaves_value_db_as_it_was(dbs, monkeypatch) -> None:
    plan = service.plan_run(NOW, universe={})
    assert plan is not None

    def boom(*_a, **_k):
        raise RuntimeError("shadow failed")

    monkeypatch.setattr(service.shadow, "process", boom)
    with pytest.raises(RuntimeError):
        service.run_nightly(plan, facts={}, earnings={}, now=NOW)
    with value_session() as s:
        assert s.get(ValueTickerFileRow, "STDY") is None
        assert s.scalars(select(ValueRunRow)).first() is None
    assert service.plan_run(NOW, universe={}) is not None  # the next poll retries


def test_an_old_private_config_idles_the_process_instead_of_crash_looping(monkeypatch) -> None:
    monkeypatch.setattr(get_config().value, "ruleset_version", "v1")  # v1's pin, v2's rules
    problem = service.startup_check()
    assert problem is not None and "frozen" in problem


def _file(symbol: str, universe: str, *, viewed: datetime | None) -> ValueTickerFileRow:
    return ValueTickerFileRow(
        symbol=symbol,
        computed_at=NOW,
        as_of=AS_OF,
        universe=universe,
        fingerprint_key="0" * 16,
        fingerprint_json="{}",
        ruleset_version="v2",
        ruleset_hash="x",
        company_class="operating",
        data_quality="pass",
        health="pass",
        verdict_deep="WAIT",
        verdict_growth="WAIT",
        summary_json="{}",
        scorecard_json="{}",
        last_viewed_at=viewed,
    )
