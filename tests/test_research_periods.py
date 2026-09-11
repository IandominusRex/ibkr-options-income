"""Period selection: duration windows, instant handling, and restatement precedence."""

from __future__ import annotations

from datetime import date

from src.research.ingest.concepts import select_periods
from src.research.schemas import Fact


def _fact(
    *,
    start: date | None,
    end: date,
    val: float,
    filed: date,
    form: str = "10-K",
    accn: str = "a",
    concept: str = "TestConcept",
) -> Fact:
    return Fact(
        value=val,
        unit="USD",
        start=start,
        end=end,
        accn=accn,
        fy=end.year,
        fp="FY",
        form=form,
        filed=filed,
        concept=concept,
    )


def test_annual_duration_keeps_only_year_length_windows() -> None:
    facts = [
        _fact(start=date(2023, 1, 1), end=date(2023, 12, 31), val=100, filed=date(2024, 2, 1)),
        # a quarter, which must not be mistaken for a year
        _fact(start=date(2023, 10, 1), end=date(2023, 12, 31), val=25, filed=date(2024, 2, 1)),
    ]
    out = select_periods(facts, kind="duration", period_type="annual", limit=5)
    assert [f.value for f in out] == [100]


def test_quarterly_duration_keeps_only_quarter_length_windows() -> None:
    facts = [
        _fact(start=date(2023, 1, 1), end=date(2023, 12, 31), val=100, filed=date(2024, 2, 1)),
        _fact(
            start=date(2023, 10, 1),
            end=date(2023, 12, 31),
            val=25,
            filed=date(2024, 2, 1),
            form="10-Q",
        ),
    ]
    out = select_periods(facts, kind="duration", period_type="quarterly", limit=8)
    assert [f.value for f in out] == [25]


def test_a_restated_value_wins_over_the_original() -> None:
    """Same period, two filings. The later filing is the correct current answer."""
    facts = [
        _fact(
            start=date(2023, 1, 1),
            end=date(2023, 12, 31),
            val=100,
            filed=date(2024, 2, 1),
            accn="original",
        ),
        _fact(
            start=date(2023, 1, 1),
            end=date(2023, 12, 31),
            val=94,
            filed=date(2025, 2, 1),
            accn="restated",
        ),
    ]
    out = select_periods(facts, kind="duration", period_type="annual", limit=5)
    assert len(out) == 1
    assert out[0].value == 94
    assert out[0].accn == "restated"


def test_periods_are_returned_newest_first() -> None:
    facts = [
        _fact(start=date(2022, 1, 1), end=date(2022, 12, 31), val=1, filed=date(2023, 2, 1)),
        _fact(start=date(2024, 1, 1), end=date(2024, 12, 31), val=3, filed=date(2025, 2, 1)),
        _fact(start=date(2023, 1, 1), end=date(2023, 12, 31), val=2, filed=date(2024, 2, 1)),
    ]
    out = select_periods(facts, kind="duration", period_type="annual", limit=5)
    assert [f.value for f in out] == [3, 2, 1]


def test_limit_truncates_to_the_most_recent_periods() -> None:
    facts = [
        _fact(start=date(y, 1, 1), end=date(y, 12, 31), val=y, filed=date(y + 1, 2, 1))
        for y in (2019, 2020, 2021, 2022, 2023, 2024)
    ]
    out = select_periods(facts, kind="duration", period_type="annual", limit=5)
    assert [f.value for f in out] == [2024, 2023, 2022, 2021, 2020]


def test_instant_annual_takes_only_annual_report_forms() -> None:
    facts = [
        _fact(start=None, end=date(2023, 12, 31), val=500, filed=date(2024, 2, 1), form="10-K"),
        _fact(start=None, end=date(2023, 9, 30), val=480, filed=date(2023, 11, 1), form="10-Q"),
    ]
    out = select_periods(facts, kind="instant", period_type="annual", limit=5)
    assert [f.value for f in out] == [500]


def test_instant_quarterly_accepts_any_form() -> None:
    facts = [
        _fact(start=None, end=date(2023, 12, 31), val=500, filed=date(2024, 2, 1), form="10-K"),
        _fact(start=None, end=date(2023, 9, 30), val=480, filed=date(2023, 11, 1), form="10-Q"),
    ]
    out = select_periods(facts, kind="instant", period_type="quarterly", limit=8)
    assert [f.value for f in out] == [500, 480]


def test_duration_facts_are_rejected_when_instant_was_asked_for() -> None:
    facts = [_fact(start=date(2023, 1, 1), end=date(2023, 12, 31), val=100, filed=date(2024, 2, 1))]
    assert select_periods(facts, kind="instant", period_type="annual", limit=5) == []


def test_instant_facts_are_rejected_when_duration_was_asked_for() -> None:
    facts = [_fact(start=None, end=date(2023, 12, 31), val=100, filed=date(2024, 2, 1))]
    assert select_periods(facts, kind="duration", period_type="annual", limit=5) == []


def test_empty_input_is_empty_output() -> None:
    assert select_periods([], kind="duration", period_type="annual", limit=5) == []
