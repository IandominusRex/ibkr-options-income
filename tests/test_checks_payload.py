"""Task 5.7: category expansion — the asymmetric fund/fundamental exclusion."""

from __future__ import annotations

from src.research.checks.payload import build_checks_payload


def test_a_stock_gets_six_categories_never_fund() -> None:
    payload = build_checks_payload({}, symbol="AAPL", is_etf=False)
    cats = [c.category for c in payload.categories]
    assert "fund" not in cats
    assert set(cats) == {"value", "growth", "past", "health", "dividend", "options"}


def test_an_etf_gets_all_seven_categories_five_not_applicable() -> None:
    payload = build_checks_payload({}, symbol="SPY", is_etf=True)
    cats = {c.category: c for c in payload.categories}
    assert set(cats) == {"value", "growth", "past", "health", "dividend", "options", "fund"}
    for name in ("value", "growth", "past", "health", "dividend"):
        assert cats[name].not_applicable is True
        assert cats[name].note
    assert cats["fund"].not_applicable is False
    assert cats["options"].not_applicable is False


def test_categories_preserve_catalogue_order() -> None:
    payload = build_checks_payload({}, symbol="AAPL", is_etf=False)
    cats = [c.category for c in payload.categories]
    assert cats == ["value", "growth", "past", "health", "dividend", "options"]


def test_each_category_carries_its_checks_for_expansion() -> None:
    payload = build_checks_payload({}, symbol="AAPL", is_etf=False)
    value = next(c for c in payload.categories if c.category == "value")
    assert len(value.checks) == value.total
    assert all(chk.category == "value" for chk in value.checks)
    assert all(chk.state.value == "UNKNOWN" for chk in value.checks)  # no metrics supplied


def test_not_applicable_category_note_explains_why() -> None:
    payload = build_checks_payload({}, symbol="SPY", is_etf=True)
    past = next(c for c in payload.categories if c.category == "past")
    assert "XBRL" in (past.note or "")


def test_a_leveraged_etf_carries_its_decay_warning_in_the_payload() -> None:
    payload = build_checks_payload({}, symbol="SOXL", is_etf=True)
    assert any("decay" in w.title.lower() for w in payload.warnings)


def test_a_plain_stock_carries_no_warnings() -> None:
    payload = build_checks_payload({}, symbol="AAPL", is_etf=False)
    assert payload.warnings == []


def test_evaluable_data_flows_through_the_payload() -> None:
    metrics = {"price": 100.0, "eps_diluted": 5.0}  # P/E = 20, within (0, 22)
    payload = build_checks_payload(metrics, symbol="AAPL", is_etf=False)
    value = next(c for c in payload.categories if c.category == "value")
    pe_check = next(chk for chk in value.checks if chk.id == "value.pe_reasonable")
    assert pe_check.state.value == "PASS"
    assert pe_check.actual == 20.0
