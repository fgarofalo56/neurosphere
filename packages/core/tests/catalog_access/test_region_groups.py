"""The region group data file: shape, provenance, Commercial and Government contents."""

from __future__ import annotations

from datetime import date

import pytest
from neurosphere_core.catalog.graph.region_groups import (
    REGION_GROUPS_FILE,
    AccessQueryError,
    load_region_groups,
    normalise_regions,
)


def test_file_has_source_url_and_retrieval_date() -> None:
    groups = load_region_groups()
    assert groups.source_url == "https://learn.microsoft.com/en-us/azure/reliability/regions-list"
    assert date.fromisoformat(groups.source_retrieved) <= date.today()
    assert REGION_GROUPS_FILE.is_file()


def test_commercial_eu_is_a_subset_of_europe_without_uk_norway_switzerland() -> None:
    groups = load_region_groups()
    eu = groups.regions_in("commercial", "eu")
    europe = groups.regions_in("commercial", "europe")
    assert eu < europe
    assert {"northeurope", "westeurope", "francecentral", "swedencentral"} <= eu
    assert not eu & {
        "uksouth",
        "ukwest",
        "norwayeast",
        "norwaywest",
        "switzerlandnorth",
        "switzerlandwest",
    }
    assert len(europe) == 19
    assert len(eu) == 13


def test_government_groups_exist_and_are_empty() -> None:
    groups = load_region_groups()
    assert groups.group_names("government") == ("eu", "europe")
    assert groups.regions_in("government", "eu") == frozenset()
    assert groups.regions_in("government", "europe") == frozenset()


def test_unknown_group_has_a_reason_code() -> None:
    groups = load_region_groups()
    with pytest.raises(AccessQueryError) as caught:
        groups.regions_in("commercial", "mars")
    assert caught.value.reason == "unknown_region_group"
    assert caught.value.http_status == 422
    with pytest.raises(AccessQueryError):
        groups.regions_in("sovereign", "eu")


def test_group_names_are_case_insensitive() -> None:
    assert load_region_groups().regions_in("commercial", " EU ")


def test_normalise_regions() -> None:
    got = normalise_regions(["WestEurope", " eastus "], "commercial")
    assert got == frozenset({"westeurope", "eastus"})
    for bad in ("", "has space", "semi;colon", "atlantis", "mars-central"):
        with pytest.raises(AccessQueryError) as caught:
            normalise_regions([bad], "commercial")
        assert caught.value.reason == "unknown_region"
        assert caught.value.http_status == 422


def test_every_group_member_is_a_known_region_of_its_cloud() -> None:
    groups = load_region_groups()
    for cloud, by_group in groups.clouds.items():
        for name, members in by_group.items():
            assert members <= groups.known_regions[cloud], (cloud, name)


def test_known_regions_are_per_cloud_with_provenance() -> None:
    groups = load_region_groups()
    assert len(groups.known_regions["commercial"]) == 60
    assert groups.known_regions["government"] == frozenset(
        {"usgovarizona", "usgovtexas", "usgovvirginia"}
    )
    assert not groups.known_regions["commercial"] & groups.known_regions["government"]
    assert set(groups.known_regions_source_urls) == {"commercial", "government"}
    assert all(
        u.startswith("https://learn.microsoft.com/")
        for u in groups.known_regions_source_urls.values()
    )
    assert groups.known_regions_retrieved == "2026-11-20"


def test_cross_cloud_region_is_unknown() -> None:
    with pytest.raises(AccessQueryError) as caught:
        normalise_regions(["usgovvirginia"], "commercial")
    assert caught.value.reason == "unknown_region"
    with pytest.raises(AccessQueryError):
        normalise_regions(["eastus"], "government")
    assert normalise_regions(["USGovVirginia"], "government") == frozenset({"usgovvirginia"})


def test_error_text_echoes_only_the_sent_token() -> None:
    with pytest.raises(AccessQueryError) as caught:
        normalise_regions(["atlantis"], "commercial")
    assert str(caught.value).count("atlantis") >= 1
    assert "westeurope" not in str(caught.value)
