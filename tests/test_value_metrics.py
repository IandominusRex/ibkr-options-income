"""src/value/metrics.py: per-year figures, split normalisation, series helpers (Part 1)."""

from __future__ import annotations

from datetime import date

import pytest

from src.value.metrics import (
    build_years,
    cagr,
    count_positive,
    median_of,
    normalise_shares,
    roic,
    stdev_of,
)
from tests.value_fixtures import financials

ENDS = [date(y, 12, 31) for y in (2025, 2024, 2023, 2022, 2021, 2020)]


def test_a_twenty_for_one_split_rescales_every_older_year() -> None:
    shares, note = normalise_shares(12.3, [12.23, 12.45, 12.72, 13.16, 0.68, 0.69], ENDS)
    assert shares[4] == pytest.approx(13.6) and shares[5] == pytest.approx(13.8)
    assert shares[:4] == [12.23, 12.45, 12.72, 13.16]
    assert note.adjustments == ["shares FY2021 and earlier x20 (split)"]
    assert note.unexplained == []


def test_a_split_after_the_last_10k_rescales_the_whole_series() -> None:
    shares, note = normalise_shares(24.3, [2.43, 2.45, 2.47, 2.48, 0.62, 0.61], ENDS)
    assert shares[0] == pytest.approx(24.3) and shares[5] == pytest.approx(24.4)
    assert note.adjustments == [
        "shares FY2025 and earlier x10 (split)",
        "shares FY2021 and earlier x4 (split)",
    ]


def test_an_acquisition_sized_change_is_left_alone() -> None:
    shares, note = normalise_shares(None, [100, 101, 137, 140, 141, 142], ENDS)
    assert shares == [100, 101, 137, 140, 141, 142]
    assert note.adjustments == [] and note.unexplained == []


def test_a_jump_that_is_no_split_is_unexplained() -> None:
    _, note = normalise_shares(None, [100, 37, 37, 37, 37, 37], ENDS)
    assert note.unexplained == ["share count jumps 2.70x into FY2024"]


def test_cagr_uses_up_to_five_years_and_needs_positive_ends() -> None:
    assert cagr([200, None, 150, 120, 110, 100]) == pytest.approx(2 ** (1 / 5) - 1)
    assert cagr([200, 180, 160, 140, 100]) == pytest.approx(2 ** (1 / 4) - 1)  # 4-year span
    assert cagr([200, 150, None, None, None]) is None
    assert cagr([-1, 1, 1, 1, 1]) is None


def test_series_helpers_ignore_missing_years() -> None:
    assert median_of([5, None, 1, 3, 9, 100]) == 4.0  # the newest five: 5, 1, 3, 9
    assert stdev_of([1.0, None]) is None
    assert stdev_of([2.0, 4.0, 4.0, 4.0, 5.0]) == pytest.approx(0.9797958971)
    assert count_positive([1, -1, None, 2, 0, 5]) == 2


def test_years_derive_gross_profit_debt_cash_and_cet1() -> None:
    fin = financials(
        gross_profit=[None, None, None, None, None],
        cost_of_revenue=[640, 568, 508, 452, 400],
        long_term_debt_current=[50, 0, 0, 0, 0],
        marketable_securities=[100, 0, 0, 0, 0],
        cet1_ratio=[0.118, None, None, None, None],
        total_liabilities=[None, 1150, 1100, 1060, 1020],
    )
    years, _ = build_years(fin)
    y = years[0]
    assert y.gross_profit == 960.0 and y.gross_margin == pytest.approx(0.6)
    assert y.debt == 450.0 and y.cash == 600.0
    assert y.cet1_pct == pytest.approx(11.8)
    assert y.total_liabilities == 1200.0  # assets less equity when the total is untagged
    assert y.fcf == 300.0 and y.fcf_margin == pytest.approx(0.1875)


def test_roic_is_nopat_over_invested_capital() -> None:
    years, _ = build_years(financials())
    # 400 x (1 - 80/380) / (1800 + 400 - 500)
    assert roic(years[0]) == pytest.approx(0.18575851393188855)
