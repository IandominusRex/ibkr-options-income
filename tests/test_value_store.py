"""value.db and the ticker file: latest row, history on change, one session row, freshness
(value book spec §6.9)."""

from __future__ import annotations

import json

import pytest

import src.value.store as store
from src.common.config import get_config
from src.value.scorecard import build_scorecard
from src.value.store import ValueTickerFileRow, ValueTickerHistoryRow, init_value_db, value_session
from src.value.ticker_file import is_fresh, persist, stored_fingerprint, what_changed
from tests.value_fixtures import inputs

CFG = get_config().value


@pytest.fixture()
def value_db(tmp_path, monkeypatch):
    monkeypatch.setattr(
        store, "_resolve_url", lambda: f"sqlite:///{(tmp_path / 'value.db').as_posix()}"
    )
    store.reset_engine()
    init_value_db()
    yield
    store.reset_engine()


def _save(card, *, session_row: bool = True):
    with value_session() as s:
        return persist(
            s,
            card,
            universe="trading",
            ranks={"deep_value": 0.7},
            filed="deep_value",
            cfg=CFG.ticker_file,
            session_row=session_row,
        )


def _history():
    with value_session() as s:
        return [
            (r.reason, json.loads(r.changed), r.scorecard_json is not None)
            for r in s.query(ValueTickerHistoryRow).order_by(ValueTickerHistoryRow.id)
        ]


def test_a_new_name_writes_its_file_and_a_full_history_row(value_db) -> None:
    result = _save(build_scorecard(inputs(close=30.0), CFG))
    assert result.changed == ["new"] and result.history_reason == "changed"
    with value_session() as s:
        row = s.get(ValueTickerFileRow, "STDY")
        assert row is not None
        assert (row.verdict_deep, row.verdict_growth, row.filed_list, row.rank_deep) == (
            "READY",
            "READY",
            "deep_value",
            0.7,
        )
        assert row.fair_value_deep == pytest.approx(46.853626592284414)
    assert _history() == [("changed", ["new"], True)]


def test_the_same_day_again_writes_no_second_row(value_db) -> None:
    _save(build_scorecard(inputs(close=30.0), CFG))
    result = _save(build_scorecard(inputs(close=30.0), CFG))
    assert result.changed == [] and result.history_reason is None
    assert len(_history()) == 1


def test_a_new_session_with_nothing_changed_writes_one_compact_row(value_db) -> None:
    card = build_scorecard(inputs(close=30.0), CFG)
    _save(card)
    later = card.model_copy(update={"as_of": card.as_of.replace(day=card.as_of.day - 1)})
    assert _save(later).history_reason == "session"
    assert _save(later).history_reason is None
    assert _history()[-1] == ("session", [], False)


def test_a_verdict_or_a_band_change_is_recorded_with_what_changed(value_db) -> None:
    _save(build_scorecard(inputs(close=30.0), CFG))
    result = _save(build_scorecard(inputs(close=40.0), CFG))
    assert "deep_value.verdict" in result.changed and "deep_value.mos_band" in result.changed
    assert _history()[-1][0] == "changed"


def test_a_small_fair_value_move_is_not_a_change() -> None:
    prev = {"lists": {"deep_value": {"fair_value": 100.0, "mos": 0.30}}}
    new = {"lists": {"deep_value": {"fair_value": 100.5, "mos": 0.31}}}
    assert what_changed(prev, new, CFG.ticker_file) == []
    new["lists"]["deep_value"]["fair_value"] = 102.0
    assert what_changed(prev, new, CFG.ticker_file) == ["deep_value.fair_value"]


def test_freshness_is_fingerprint_equality(value_db) -> None:
    card = build_scorecard(inputs(close=30.0), CFG)
    _save(card)
    with value_session() as s:
        stored = stored_fingerprint(s, "STDY")
    assert is_fresh(stored, card.fingerprint)
    assert not is_fresh(stored, build_scorecard(inputs(close=31.0), CFG).fingerprint)
    assert not is_fresh(None, card.fingerprint)
