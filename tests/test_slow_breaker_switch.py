"""Review fix 5: every reader of the slow breaker's trip honours the ``slow_breaker`` switch."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from src.storage import slow_breaker
from src.storage.envelope_switches import set_switch
from src.storage.system_settings import set_setting


@pytest.fixture()
def tripped(db):
    set_setting(slow_breaker.KEY, json.dumps({"tripped": True, "at": "2026-11-17T15:00:00+00:00"}))


def test_a_trip_blocks_only_while_the_switch_is_on(tripped) -> None:
    set_switch("slow_breaker", "10", source="cli")
    assert slow_breaker.blocks_new_entries() is True
    set_switch("slow_breaker", "off", source="cli")
    assert slow_breaker.blocks_new_entries() is False
    assert slow_breaker.is_tripped() is True  # the record itself is untouched


def test_an_unreadable_record_with_the_switch_on_fails_closed(db) -> None:
    set_switch("slow_breaker", "10", source="cli")
    set_setting(slow_breaker.KEY, "not json")
    assert slow_breaker.blocks_new_entries() is True
    set_switch("slow_breaker", "off", source="cli")
    assert slow_breaker.blocks_new_entries() is False


def test_in_live_every_switch_reads_off_so_nothing_blocks(tripped, monkeypatch) -> None:
    from src.common.config import Config

    set_switch("slow_breaker", "10", source="cli")
    monkeypatch.setattr(Config, "is_live", property(lambda self: True))
    assert slow_breaker.blocks_new_entries() is False


def test_the_hedge_context_reads_the_switch(tripped, monkeypatch) -> None:
    """build_context's slow_breaker_tripped follows the switch, not the raw record."""
    import src.hedge.context as hc
    import src.ibkr.portfolio as portfolio

    monkeypatch.setattr(portfolio, "get_positions", lambda *a, **k: [])
    monkeypatch.setattr(hc, "read_stress", lambda cfg: hc.Stress(18.0, 22.0, 30.0))
    monkeypatch.setattr("src.common.hedge_view.open_hedges", lambda: [])

    def ctx():
        return asyncio.run(
            hc.build_context(
                object(),
                cfg=SimpleNamespace(),  # type: ignore[arg-type]
                now=datetime(2026, 11, 18, 15, tzinfo=UTC),
                nlv0=650_000.0,
                months=0.0,
                book=None,
                instrument_beta=1.1,
            )
        )

    set_switch("slow_breaker", "10", source="cli")
    assert ctx().slow_breaker_tripped is True
    set_switch("slow_breaker", "off", source="cli")
    assert ctx().slow_breaker_tripped is False
