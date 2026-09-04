"""Check definitions load, validate, and split correctly by instrument type."""

from __future__ import annotations

from src.research.checks.definitions import CheckOp, checks_for, load_checks

CATEGORIES = {"value", "growth", "past", "health", "dividend", "options", "fund"}


def test_every_definition_is_well_formed() -> None:
    for c in load_checks():
        assert c.id and "." in c.id, c.id
        assert c.category in CATEGORIES, c.id
        assert c.statement.endswith("?"), f"{c.id} statement must be a question"
        assert c.requires, f"{c.id} must declare its inputs"
        assert c.applies_to in {"all", "stock", "etf"}, c.id


def test_ids_are_unique() -> None:
    ids = [c.id for c in load_checks()]
    assert len(ids) == len(set(ids))


def test_between_ops_carry_two_bounds() -> None:
    for c in load_checks():
        if c.op is CheckOp.BETWEEN:
            assert isinstance(c.threshold, list) and len(c.threshold) == 2, c.id


def test_a_stock_gets_the_fundamental_categories_not_the_fund_category() -> None:
    cats = {c.category for c in checks_for(is_etf=False)}
    assert {"value", "growth", "past", "health", "dividend", "options"} <= cats
    assert "fund" not in cats


def test_an_etf_gets_the_fund_and_options_categories_only() -> None:
    cats = {c.category for c in checks_for(is_etf=True)}
    assert cats == {"fund", "options"}


def test_options_checks_apply_to_both() -> None:
    """The options lens is the one category that means something for every instrument."""
    ids_stock = {c.id for c in checks_for(is_etf=False) if c.category == "options"}
    ids_etf = {c.id for c in checks_for(is_etf=True) if c.category == "options"}
    assert ids_stock == ids_etf
    assert ids_stock
