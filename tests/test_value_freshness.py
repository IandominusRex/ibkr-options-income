"""The ticker file's freshness on the cheap fingerprint (Part 6, ruling 16)."""

from __future__ import annotations

import json
from datetime import date

from src.value.ticker_file import freshness_json, freshness_key, is_current

PARTS = {
    "latest_accn": "0001-26-000001",
    "latest_filed": date(2026, 2, 10),
    "price_date": date(2026, 3, 31),
    "price_close": 31.5,
}


def test_a_file_is_current_only_when_the_cheap_parts_match() -> None:
    stored = freshness_json(PARTS, "normal", "v4", "be30d1eaa915")
    assert json.loads(stored)["key"] == freshness_key(PARTS, "normal", "v4", "be30d1eaa915")
    assert len(freshness_key(PARTS, "normal", "v4", "be30d1eaa915")) == 16
    assert is_current(stored, dict(PARTS), "normal", "v4", "be30d1eaa915")
    # a new bar, a new filing, a regime step or a ruleset change each make it stale
    assert not is_current(
        stored, {**PARTS, "price_date": date(2026, 4, 1)}, "normal", "v4", "be30d1eaa915"
    )
    assert not is_current(
        stored, {**PARTS, "latest_accn": "0001-26-000002"}, "normal", "v4", "be30d1eaa915"
    )
    assert not is_current(stored, PARTS, "stressed", "v4", "be30d1eaa915")
    assert not is_current(stored, PARTS, "normal", "v5", "be30d1eaa915")
    # a file written before Part 6 has no freshness_json: stale once, then recomputed
    assert not is_current(None, PARTS, "normal", "v4", "be30d1eaa915")
    assert not is_current("not json", PARTS, "normal", "v4", "be30d1eaa915")
