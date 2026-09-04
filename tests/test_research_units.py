"""Units are enforced, never coerced. A unit we do not understand is a config error."""

from __future__ import annotations

import pytest

from src.research.ingest.concepts import LineItemSpec, assert_units_supported, load_concept_map


def test_supported_units_pass() -> None:
    for unit in ("USD", "USD/shares", "shares", "pure"):
        assert_units_supported(
            LineItemSpec(statement="income", kind="duration", units=[unit], concepts=["X"])
        )


def test_an_unsupported_unit_raises() -> None:
    spec = LineItemSpec(statement="income", kind="duration", units=["EUR"], concepts=["X"])
    with pytest.raises(ValueError, match="Unsupported unit"):
        assert_units_supported(spec)


def test_every_shipped_line_item_uses_a_supported_unit() -> None:
    for spec in load_concept_map().values():
        assert_units_supported(spec)
