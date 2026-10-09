from __future__ import annotations

import pytest

from src.news import playbook as pb


def test_titles_from_both_sources_map_to_one_key() -> None:
    p = pb.load_playbook()
    assert p.match("Unemployment Claims").key == "jobless_claims"  # ForexFactory
    assert p.match("Initial Jobless Claims").key == "jobless_claims"  # Nasdaq
    assert p.match("CPI m/m").key == "cpi" and p.match("CPI (YoY)").key == "cpi"
    assert p.match("Core CPI m/m").key == "core_cpi"
    assert p.match("Non-Farm Employment Change").key == "nfp"
    assert p.match("Fed Waller Speaks") is None


def test_priority_orders_cpi_before_core() -> None:
    p = pb.load_playbook()
    assert p.priority("fomc_rate") < p.priority("cpi") < p.priority("core_cpi")


@pytest.mark.parametrize(
    "raw, val",
    [
        ("0.4%", 0.4),
        ("1,716K", 1_716_000.0),
        ("197K", 197_000.0),
        ("8.28B", 8.28e9),
        ("-3.186M", -3_186_000.0),
        ("(0.2)%", -0.2),
        ("&nbsp;", None),
        ("", None),
        (None, None),
        ("abc", None),
        ("5.300%", 5.3),
    ],
)
def test_parse_value(raw, val) -> None:
    assert pb.parse_value(raw) == val


def test_surprise_direction_incl_inverse() -> None:
    p = pb.load_playbook()
    cpi = p.match("CPI m/m")
    assert pb.surprise_dir(cpi, "0.4%", "0.3%") == "hot"
    assert pb.surprise_dir(cpi, "0.3%", "0.3%") == "inline"
    assert pb.surprise_dir(cpi, "0.2%", "0.3%") == "cold"
    claims = p.match("Initial Jobless Claims")
    assert pb.surprise_dir(claims, "180K", "200K") == "hot"  # fewer claims = stronger economy
    assert pb.surprise_dir(claims, "230K", "200K") == "cold"
    assert pb.surprise_dir(cpi, None, "0.3%") is None


def test_prior_arrows() -> None:
    p = pb.load_playbook()
    prior = pb.prior_for(p.match("CPI m/m"), "hot")
    assert (
        prior.arrows["stocks"] == "🔴"
        and prior.arrows["bonds"] == "🔴"
        and prior.arrows["dollar"] == "🟢"
    )
    assert set(prior.arrows) == set(pb.ASSETS)
    assert pb.prior_for(p.match("CPI m/m"), "inline") is None


def test_every_entry_is_complete() -> None:
    for e in pb.load_playbook().entries:
        assert set(e.hot) == set(pb.ASSETS) and set(e.cold) == set(pb.ASSETS), e.key
        assert e.tolerance > 0 and e.aliases and e.rationale_hot and e.rationale_cold
