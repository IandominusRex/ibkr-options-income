"""Claude's kill triggers, evaluated by Python (value book spec §8.4, §7.1 trigger 6)."""

from __future__ import annotations

from datetime import date, datetime

import pytest
from sqlalchemy import select

import src.value.store as store
from src.common.config import get_config
from src.value.claude_verdicts import update_kill_triggers
from src.value.kill_triggers import check
from src.value.scorecard import build_scorecard
from src.value.store import ValueClaudeFactRow, ValueKillTriggerRow, init_value_db, value_session
from tests.value_fixtures import inputs

CFG = get_config().value
CARD = build_scorecard(inputs(close=30.0), CFG)  # revenue growth 12.68%, gross margin 60%
NOW = datetime(2026, 11, 2, 15, 0)


@pytest.mark.parametrize(
    ("kind", "threshold", "state"),
    [
        ("revenue_growth_below", 15.0, "fired"),  # 12.68 < 15
        ("revenue_growth_below", 12.0, "near"),  # 12.68 <= 12 + 10% x 12 = 13.2
        ("revenue_growth_below", 5.0, "far"),  # band 10% x 10 = 1 point: 6.0
        ("gross_margin_below", 56.0, "near"),  # 60 <= 56 + 5.6
        ("gross_margin_below", 50.0, "far"),
        ("dilution_above", 1.0, "far"),  # the share count fell: dilution is negative
        ("fcf_ttm_negative", None, "far"),  # 300 of FCF
        ("guidance_cut", None, "far"),
    ],
)
def test_each_predicate_on_tonights_scorecard(kind, threshold, state) -> None:
    assert check(kind, threshold, CARD, near_pct=10.0, facts_since=set()).state == state


def test_above_predicates_and_unknown_numbers() -> None:
    card = CARD.model_copy(
        update={
            "health_checks": [
                c.model_copy(update={"actual": 2.8}) if c.id == "health.net_debt_to_ebitda" else c
                for c in CARD.health_checks
            ]
        }
    )
    assert (
        check("net_debt_to_ebitda_above", 3.0, card, near_pct=10.0, facts_since=set()).state
        == "near"
    )
    assert (
        check("net_debt_to_ebitda_above", 2.5, card, near_pct=10.0, facts_since=set()).state
        == "fired"
    )
    blank = CARD.model_copy(update={"metrics": {**CARD.metrics, "gross_margin_latest": None}})
    out = check("gross_margin_below", 50.0, blank, near_pct=10.0, facts_since=set())
    assert out.state == "unknown" and out.actual is None  # unknown is never zero


def test_a_fact_based_trigger_fires_on_a_grounded_fact_after_it_was_chosen() -> None:
    assert (
        check("customer_loss", None, CARD, near_pct=10.0, facts_since={"customer_loss"}).state
        == "fired"
    )


@pytest.fixture()
def value_db(tmp_path, monkeypatch):
    monkeypatch.setattr(
        store, "_resolve_url", lambda: f"sqlite:///{(tmp_path / 'value.db').as_posix()}"
    )
    store.reset_engine()
    init_value_db()
    yield
    store.reset_engine()


def test_the_night_records_each_trigger_and_hands_trigger_6_its_lines(value_db) -> None:
    with value_session() as s:
        for kind, threshold in (("revenue_growth_below", 12.0), ("gross_margin_below", 50.0)):
            s.add(
                ValueKillTriggerRow(
                    read_id=1, symbol="STDY", kind=kind, threshold=threshold, chosen_at=NOW
                )
            )
        s.add(ValueKillTriggerRow(read_id=1, symbol="STDY", kind="guidance_cut", chosen_at=NOW))
        s.add(
            ValueClaudeFactRow(
                read_id=2,
                symbol="STDY",
                accn="a",
                kind="guidance_cut",
                quote="we now expect",
                grounded=True,
                created_at=NOW,
            )
        )
    with value_session() as s:
        near = update_kill_triggers(s, [CARD], CFG, date(2026, 11, 2))
    assert near == {"STDY": ["revenue_growth_below near (12.68 vs 12)", "guidance_cut fired (n/a)"]}
    with value_session() as s:
        rows = {r.kind: r for r in s.scalars(select(ValueKillTriggerRow))}
        assert rows["gross_margin_below"].last_state == "far"
        assert rows["guidance_cut"].fired_on == date(2026, 11, 2)
