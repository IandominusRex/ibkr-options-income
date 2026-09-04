"""Concept resolution: the ordered-candidate map, and honest failure when nothing matches."""

from __future__ import annotations

from datetime import date

from src.research.ingest.concepts import (
    LineItemSpec,
    load_concept_map,
    parse_facts,
    resolve_line_item,
)


def _payload(concepts: dict) -> dict:
    return {"cik": 1, "entityName": "Test", "facts": {"us-gaap": concepts}}


_REVENUE_SPEC = LineItemSpec(
    statement="income",
    kind="duration",
    units=["USD"],
    concepts=[
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ],
)


def test_parse_facts_reads_duration_facts() -> None:
    payload = _payload(
        {
            "Revenues": {
                "units": {
                    "USD": [
                        {
                            "start": "2023-01-01",
                            "end": "2023-12-31",
                            "val": 1000.0,
                            "accn": "acc-1",
                            "fy": 2023,
                            "fp": "FY",
                            "form": "10-K",
                            "filed": "2024-02-01",
                        }
                    ]
                }
            }
        }
    )
    facts = parse_facts(payload, "Revenues", ["USD"])
    assert len(facts) == 1
    assert facts[0].value == 1000.0
    assert facts[0].start == date(2023, 1, 1)
    assert facts[0].end == date(2023, 12, 31)
    assert facts[0].filed == date(2024, 2, 1)


def test_parse_facts_reads_instant_facts_with_no_start() -> None:
    payload = _payload(
        {
            "Assets": {
                "units": {
                    "USD": [
                        {
                            "end": "2023-12-31",
                            "val": 5000.0,
                            "accn": "acc-1",
                            "form": "10-K",
                            "filed": "2024-02-01",
                        }
                    ]
                }
            }
        }
    )
    facts = parse_facts(payload, "Assets", ["USD"])
    assert facts[0].start is None
    assert facts[0].end == date(2023, 12, 31)


def test_parse_facts_ignores_unrequested_units() -> None:
    """A share count reported in USD, or a value in EUR, is not what we asked for."""
    payload = _payload(
        {
            "Revenues": {
                "units": {
                    "EUR": [
                        {
                            "start": "2023-01-01",
                            "end": "2023-12-31",
                            "val": 900.0,
                            "accn": "a",
                            "form": "10-K",
                            "filed": "2024-02-01",
                        }
                    ]
                }
            }
        }
    )
    assert parse_facts(payload, "Revenues", ["USD"]) == []


def test_parse_facts_skips_malformed_entries_without_failing_the_rest() -> None:
    payload = _payload(
        {
            "Revenues": {
                "units": {
                    "USD": [
                        {
                            "start": "2023-01-01",
                            "end": "bogus-date",
                            "val": 1.0,
                            "accn": "a",
                            "form": "10-K",
                            "filed": "2024-02-01",
                        },
                        {
                            "start": "2023-01-01",
                            "end": "2023-12-31",
                            "val": 2.0,
                            "accn": "b",
                            "form": "10-K",
                            "filed": "2024-02-01",
                        },
                        {
                            "start": "2023-01-01",
                            "end": "2023-12-31",
                            "val": None,
                            "accn": "c",
                            "form": "10-K",
                            "filed": "2024-02-01",
                        },
                    ]
                }
            }
        }
    )
    facts = parse_facts(payload, "Revenues", ["USD"])
    assert [f.value for f in facts] == [2.0]


def test_resolve_takes_the_first_candidate_that_has_facts() -> None:
    payload = _payload(
        {
            "Revenues": {
                "units": {
                    "USD": [
                        {
                            "start": "2023-01-01",
                            "end": "2023-12-31",
                            "val": 10.0,
                            "accn": "a",
                            "form": "10-K",
                            "filed": "2024-02-01",
                        }
                    ]
                }
            },
            "SalesRevenueNet": {
                "units": {
                    "USD": [
                        {
                            "start": "2023-01-01",
                            "end": "2023-12-31",
                            "val": 20.0,
                            "accn": "a",
                            "form": "10-K",
                            "filed": "2024-02-01",
                        }
                    ]
                }
            },
        }
    )
    resolved = resolve_line_item(payload, _REVENUE_SPEC)
    assert resolved is not None
    concept, facts = resolved
    # RevenueFromContractWithCustomer... is absent, so Revenues wins over SalesRevenueNet.
    assert concept == "Revenues"
    assert facts[0].value == 10.0


def test_resolve_prefers_the_earliest_listed_candidate() -> None:
    payload = _payload(
        {
            "RevenueFromContractWithCustomerExcludingAssessedTax": {
                "units": {
                    "USD": [
                        {
                            "start": "2023-01-01",
                            "end": "2023-12-31",
                            "val": 99.0,
                            "accn": "a",
                            "form": "10-K",
                            "filed": "2024-02-01",
                        }
                    ]
                }
            },
            "Revenues": {
                "units": {
                    "USD": [
                        {
                            "start": "2023-01-01",
                            "end": "2023-12-31",
                            "val": 10.0,
                            "accn": "a",
                            "form": "10-K",
                            "filed": "2024-02-01",
                        }
                    ]
                }
            },
        }
    )
    concept, facts = resolve_line_item(payload, _REVENUE_SPEC)  # type: ignore[misc]
    assert concept == "RevenueFromContractWithCustomerExcludingAssessedTax"
    assert facts[0].value == 99.0


def test_resolve_returns_none_when_no_candidate_matches() -> None:
    """Honest absence. The caller renders UNKNOWN rather than a zero."""
    assert resolve_line_item(_payload({"SomethingElse": {"units": {}}}), _REVENUE_SPEC) is None


def test_resolve_handles_a_payload_with_no_us_gaap_taxonomy() -> None:
    """Many ETFs and foreign filers have no us-gaap facts at all."""
    assert resolve_line_item({"facts": {"dei": {}}}, _REVENUE_SPEC) is None
    assert resolve_line_item({}, _REVENUE_SPEC) is None


def test_shipped_concept_map_covers_the_core_line_items() -> None:
    m = load_concept_map()
    required = {
        "revenue",
        "gross_profit",
        "operating_income",
        "net_income",
        "eps_diluted",
        "total_assets",
        "total_liabilities",
        "stockholders_equity",
        "current_assets",
        "current_liabilities",
        "long_term_debt",
        "cash_and_equivalents",
        "operating_cash_flow",
        "capital_expenditure",
        "shares_diluted",
    }
    assert required <= set(m)
    for name, spec in m.items():
        assert spec.kind in {"duration", "instant"}, name
        assert spec.concepts, name
