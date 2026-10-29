"""The ranked monthly record's arithmetic (value book spec §6.8): tenths, ties, dropped members
and the monthly formation date."""

from __future__ import annotations

from datetime import date

import pytest

from src.value.ranked import buckets, equal_weight_return, is_new_month


def test_the_tenths_are_n_over_ten_names_ties_broken_by_symbol() -> None:
    scores: dict[str, float | None] = {f"N{i:02d}": float(i) for i in range(25)}
    scores["TIE"] = 24.0  # ties N24 at the top: the symbol orders them
    scores["NONE"] = None  # unscored: never in a portfolio
    picked = buckets(scores)
    assert picked is not None
    assert picked["top"] == ["N24", "TIE"]  # 26 scored names: 26 // 10 = 2
    assert picked["bottom"] == ["N01", "N00"]
    assert len(picked["all"]) == 26 and "NONE" not in picked["all"]
    assert buckets({f"N{i}": float(i) for i in range(9)}) is None  # under ten: no tenth


def test_equal_weight_drops_and_counts_members_without_a_close() -> None:
    ret, missing = equal_weight_return(
        ["A", "B", "C"], {"A": 10.0, "B": 20.0, "C": 5.0}, {"A": 11.0, "B": 19.0}
    )
    assert ret == pytest.approx((0.10 - 0.05) / 2)
    assert missing == 1
    assert equal_weight_return(["A"], {}, {}) == (None, 1)


def test_a_formation_on_the_first_run_of_each_month() -> None:
    assert is_new_month(None, date(2026, 11, 2))
    assert not is_new_month(date(2026, 11, 2), date(2026, 11, 30))
    assert is_new_month(date(2026, 11, 2), date(2026, 12, 1))
    assert is_new_month(date(2026, 12, 1), date(2027, 1, 4))
