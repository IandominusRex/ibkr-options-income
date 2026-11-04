"""Grounded facts (value book spec §8.2): verbatim quotes, numbers in the quote, XBRL matches."""

from __future__ import annotations

from src.common.value_ai_types import FilingSection, ProposedFact
from src.value.grounding import check_fact, number_in_quote
from tests.value_fixtures import financials

ACCN = "0000000001-26-000001"
SECTIONS = [
    FilingSection(
        accn=ACCN,
        form="10-K",
        section="Item 7 MD&A",
        text="Revenue grew 12% to $1,600 million. We recorded a one-time   restructuring "
        "charge of $45.2 million in the fourth quarter. We now expect revenue to decline.",
    )
]


def _fact(**kw) -> ProposedFact:
    base = dict(
        kind="one_off",
        value=45.2,
        unit="USD_millions",
        accn=ACCN,
        quote="a one-time restructuring charge of $45.2 million",
    )
    base.update(kw)
    return ProposedFact(**base)


def test_a_verbatim_quote_with_its_number_is_grounded() -> None:
    assert check_fact(_fact(), SECTIONS) == (True, "")  # whitespace normalised, nothing else


def test_a_paraphrase_a_wrong_number_or_a_wrong_filing_is_dropped() -> None:
    assert check_fact(_fact(quote="a restructuring charge of $45.2 million"), SECTIONS)[1] == (
        "the quote is not in the filing verbatim"
    )
    assert check_fact(_fact(value=52.4), SECTIONS)[1] == "the number is not in the quote"
    assert check_fact(_fact(accn="0000000001-25-000009"), SECTIONS)[1] == (
        "the accession is not a filing this read was given"
    )
    cut = _fact(kind="guidance_cut", value=None, quote="We now expect revenue to decline.")
    assert check_fact(cut, SECTIONS) == (True, "")


def test_an_xbrl_item_must_match_companyfacts_for_that_filing() -> None:
    fin = financials()  # revenue 1600 tagged by ACCN (the fixture's units are $ millions)
    good = _fact(
        kind="segment_revenue",
        value=1600,
        unit="USD",
        item="revenue",
        quote="Revenue grew 12% to $1,600 million",
    )
    assert check_fact(good, SECTIONS, fin) == (True, "")
    bad = good.model_copy(update={"unit": "USD_millions"})  # 1.6e9 against a tagged 1,600
    ok, why = check_fact(bad, SECTIONS, fin)
    assert not ok and why == "companyfacts tags revenue 1,600 for this filing"


def test_a_number_is_matched_to_the_precision_written() -> None:
    assert number_in_quote(1600.0, "to $1,600 million")
    assert number_in_quote(45.2, "$45.2 million") and not number_in_quote(45.3, "$45.2 million")
    assert number_in_quote(18.0, "18% of revenue")
