"""Part 6, Task 6: the nightly digest and the review cards (ruling 13, spec §7 "Review cards, not exits")."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from sqlalchemy import func, select

from src.value import digest
from src.value.store import (
    ValueBookStateRow,
    ValueKillTriggerRow,
    ValueOrderRow,
    ValuePositionRow,
    ValueProposalRow,
    ValueReevaluationRow,
    ValueTickerHistoryRow,
    value_session,
)
from tests.value_book_fixtures import ticker_file

NOW = datetime(2026, 11, 2, 22, 0)
TODAY = NOW.date()
SINCE = NOW - timedelta(days=1)


def _cfg():
    from src.common.config import get_config

    return get_config().value


def _build(vs, since: datetime = SINCE) -> str | None:
    return digest.build(vs, since=since, now=NOW, cfg=_cfg())


def _position(
    symbol: str = "GOOGL",
    *,
    opened_on: date = date(2026, 10, 1),
    entry: float = 100.0,
    fair_value: float | None = 150.0,
    highest: float = 110.0,
    list_name: str = "deep_value",
    shares: float = 10.0,
) -> int:
    plan = {
        "entry_price": entry,
        "fair_value": fair_value,
        "highest_close": highest,
        "entry_date": opened_on.isoformat(),
    }
    with value_session() as vs:
        pos = ValuePositionRow(
            symbol=symbol,
            list_name=list_name,
            status="open",
            opened_on=opened_on,
            plan_json=json.dumps(plan),
        )
        vs.add(pos)
        vs.add(
            ValueOrderRow(
                symbol=symbol,
                list_name=list_name,
                side="buy",
                shares=shares,
                filled=shares,
                avg_price=entry,
                status="filled",
                created_at=NOW,
            )
        )
        vs.flush()
        return pos.id


def _minor(pos_id: int, *, created: datetime = NOW - timedelta(hours=3)) -> None:
    with value_session() as vs:
        vs.add(
            ValueReevaluationRow(
                shadow_id=0,
                position_id=pos_id,
                symbol="GOOGL",
                list_name="deep_value",
                session=created.date(),
                last_session=created.date(),
                severity="minor",
                triggers_json=json.dumps(
                    [{"day": created.date().isoformat(), "kind": "drift", "detail": "drifted 4%"}]
                ),
                plan_before_json=json.dumps({"stop": 90.0}),
                plan_after_json=json.dumps({"stop": 95.0}),
                verdict_at_entry="READY",
                ruleset_version="v4",
                ruleset_hash="be30d1eaa915",
                created_at=created,
            )
        )


def test_an_empty_night_sends_nothing(value_book_db) -> None:
    with value_session() as vs:
        assert _build(vs) is None


def test_minor_reevaluations_are_listed_once(value_book_db) -> None:
    pos_id = _position(highest=130.0)  # progress made: no review card muddies this test
    _minor(pos_id)
    with value_session() as vs:
        d = digest.compose(vs, since=SINCE, now=NOW, cfg=_cfg())
        assert d.text is not None and "GOOGL" in d.text and "drifted 4%" in d.text
        assert "$90.00" in d.text and "$95.00" in d.text
        digest.mark_sent(vs, d, NOW)
    with value_session() as vs:
        stored = digest.last_sent(vs)
        assert stored == NOW
        again = digest.compose(vs, since=stored, now=NOW + timedelta(days=1), cfg=_cfg())
    assert again.text is not None  # the book line still reads
    assert "drifted 4%" not in again.text


def test_a_fired_kill_trigger_is_a_review_card(value_book_db) -> None:
    _position(highest=130.0)
    with value_session() as vs:
        vs.add(
            ValueKillTriggerRow(
                read_id=1,
                symbol="GOOGL",
                kind="gross_margin_below",
                threshold=40.0,
                chosen_at=NOW - timedelta(days=30),
                last_state="fired",
                last_actual=37.5,
                fired_on=TODAY,
            )
        )
    with value_session() as vs:
        text = _build(vs)
    assert text is not None and "GOOGL" in text
    assert "kill trigger fired" in text and "gross margin below" in text and "37.5" in text
    assert "never sells" in text or "nothing here sells" in text.lower()


def test_nine_months_without_progress_is_a_review_card(value_book_db) -> None:
    # entry 100, fair value 150: progress needs a close above 105; the best close was 104
    _position(opened_on=date(2026, 1, 15), entry=100.0, fair_value=150.0, highest=104.0)
    _position("META", opened_on=date(2026, 1, 15), entry=100.0, fair_value=150.0, highest=120.0)
    _position("MU", opened_on=date(2026, 10, 1), entry=100.0, fair_value=150.0, highest=101.0)
    with value_session() as vs:
        text = _build(vs)
    assert text is not None
    assert "GOOGL: no progress" in text
    assert "META: no progress" not in text  # a close well above entry + 10% of the distance
    assert "MU: no progress" not in text  # held under nine months


def test_fair_value_down_while_price_is_not_is_a_review_card(value_book_db) -> None:
    _position(opened_on=date(2026, 10, 1), highest=130.0)
    ticker_file("GOOGL", fair_value_deep=120.0, price=108.0)  # fair value -20%, price +8%
    with value_session() as vs:
        vs.add(
            ValueTickerHistoryRow(
                symbol="GOOGL",
                recorded_at=datetime(2026, 10, 1, 22, 0),
                as_of=date(2026, 10, 1),
                reason="session",
                changed="[]",
                fingerprint_key="k" * 16,
                ruleset_version="v4",
                summary_json=json.dumps({"lists": {"deep_value": {"fair_value": 150.0}}}),
            )
        )
    with value_session() as vs:
        text = _build(vs)
    assert text is not None
    assert "GOOGL" in text and "fair value is down 20%" in text and "$150.00" in text
    assert "$120.00" in text


def test_the_book_line_says_the_breakers_in_words(value_book_db) -> None:
    _position(highest=130.0)
    with value_session() as vs:
        vs.add(ValueBookStateRow(key="trend", value=json.dumps({"brake": True}), updated_at=NOW))
        vs.add(
            ValueBookStateRow(
                key="high_water",
                value=json.dumps({"high": 12_000.0, "value": 10_000.0, "stop": True}),
                updated_at=NOW,
            )
        )
        vs.add(
            ValueProposalRow(
                kind="buy",
                symbol="MSFT",
                list_name="quality_growth",
                shares=5,
                price=400.0,
                reason="tranche 1",
                status="pending",
                created_at=NOW,
                expires_at=NOW + timedelta(hours=30),
            )
        )
    with value_session() as vs:
        text = _build(vs)
    assert text is not None
    assert "1 open position" in text and "$1,000" in text  # cost 10 x 100
    assert "down 17% from its high" in text
    assert "trend brake is on" in text and "drawdown breaker has stopped new entries" in text
    assert "MSFT" in text and "waiting for your tap" in text.lower()


def test_review_cards_never_create_a_proposal(value_book_db) -> None:
    _position(opened_on=date(2026, 1, 15), highest=101.0)
    with value_session() as vs:
        before = vs.scalar(select(func.count()).select_from(ValueProposalRow))
        assert _build(vs) is not None
    with value_session() as vs:
        assert vs.scalar(select(func.count()).select_from(ValueProposalRow)) == before == 0
