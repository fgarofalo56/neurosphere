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
    assert normalise_regions(["WestEurope", " eastus "]) == frozenset({"westeurope", "eastus"})
    for bad in ("", "has space", "semi;colon"):
        with pytest.raises(AccessQueryError) as caught:
            normalise_regions([bad])
        assert caught.value.reason == "unknown_region"
