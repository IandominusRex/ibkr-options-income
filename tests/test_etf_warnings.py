"""Leverage is a structural property, surfaced as a warning rather than scored as a check."""

from __future__ import annotations

from src.research.checks.warnings import warnings_for

LEVERAGED = {"TQQQ", "UPRO", "SOXL", "LABU", "TSLL", "DPST"}


def test_a_leveraged_etf_carries_a_decay_warning() -> None:
    titles = [w.title for w in warnings_for("SOXL", is_etf=True, info={})]
    assert any("decay" in t.lower() for t in titles)


def test_every_leveraged_universe_name_is_covered() -> None:
    for symbol in LEVERAGED:
        assert warnings_for(symbol, is_etf=True, info={}), symbol


def test_a_plain_etf_carries_no_decay_warning() -> None:
    titles = [w.title.lower() for w in warnings_for("SPY", is_etf=True, info={})]
    assert not any("decay" in t for t in titles)


def test_cc_only_names_are_marked_never_assignment_eligible() -> None:
    """LABU, TSLL and DPST are deliberately excluded from would_own."""
    for symbol in ("LABU", "TSLL", "DPST"):
        details = " ".join(w.detail for w in warnings_for(symbol, is_etf=True, info={}))
        assert "covered call" in details.lower()


def test_the_deliberate_would_own_exceptions_say_so() -> None:
    """TQQQ, UPRO and SOXL are in would_own on purpose; the UI must not read as an oversight."""
    for symbol in ("TQQQ", "UPRO", "SOXL"):
        details = " ".join(w.detail for w in warnings_for(symbol, is_etf=True, info={}))
        assert "deliberate" in details.lower()


def test_warnings_are_not_checks() -> None:
    """A warning must never appear in the check catalogue and dilute a category score."""
    from src.research.checks.definitions import load_checks

    assert not any("leverage" in c.id for c in load_checks())


def test_a_plain_stock_carries_no_warning() -> None:
    assert warnings_for("AAPL", is_etf=False, info={}) == []


def test_warnings_carry_a_level() -> None:
    for w in warnings_for("SOXL", is_etf=True, info={}):
        assert w.level in {"info", "caution"}
