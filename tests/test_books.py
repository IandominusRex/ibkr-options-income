from src.common.books import is_spreads_underlying, spreads_underlyings


def test_book_underlyings_are_case_insensitive() -> None:
    assert spreads_underlyings() == frozenset({"SPY", "SPX", "XSP"})
    assert (
        is_spreads_underlying("spy")
        and is_spreads_underlying("xsp")
        and is_spreads_underlying("SPX")
    )


def test_wheel_names_and_missing_symbols_are_not_spreads() -> None:
    assert not is_spreads_underlying("UPRO")
    assert not is_spreads_underlying(None)
    assert not is_spreads_underlying("")


# Review minor — an Activity Statement names an SPX daily by its SPXW root.
def test_an_spxw_root_belongs_to_the_spreads_book() -> None:
    from src.common.books import is_spreads_underlying

    assert is_spreads_underlying("SPXW") and is_spreads_underlying("spx")
    assert not is_spreads_underlying("UPRO")
