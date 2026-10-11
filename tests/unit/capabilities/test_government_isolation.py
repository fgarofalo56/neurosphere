"""A Government profile never resolves a Commercial row/region, and vice versa."""

from __future__ import annotations

from datetime import date

from neurosphere_core.capabilities import DeploymentProfile, validate_profile
from rows import entry, matrix

TODAY = date(2026, 10, 11)


def profile(cloud: str, region: str) -> DeploymentProfile:
    return DeploymentProfile.model_validate(
        {"cloud": cloud, "regions": (region,), "hosting": "aks", "analytics": "synapse"}
    )


def test_government_profile_ignores_commercial_rows_even_global_and_wildcard() -> None:
    m = matrix(
        entry(service="aks", feature="base", cloud="commercial", region="global"),
        entry(service="aks", feature="base", cloud="commercial", region="*"),
        entry(service="aks", feature="base", cloud="commercial", region="eastus"),
        entry(service="synapse", feature="base", cloud="commercial", region="global"),
    )
    result = validate_profile(profile("government", "usgovvirginia"), m, TODAY)
    assert not result.supported
    for res in result.results:
        assert res.status == "disabled"
        assert res.cause == "unverified"
        assert res.row_id is None


def test_commercial_profile_ignores_government_rows() -> None:
    m = matrix(
        entry(service="aks", feature="base", cloud="government", region="*"),
        entry(service="aks", feature="base", cloud="government", region="global"),
        entry(service="synapse", feature="base", cloud="government", region="global"),
    )
    result = validate_profile(profile("commercial", "eastus"), m, TODAY)
    assert all(r.status == "disabled" and r.row_id is None for r in result.results)


def test_government_wildcard_does_not_cover_commercial_region() -> None:
    m = matrix(
        entry(service="aks", feature="base", cloud="government", region="*"),
        entry(service="synapse", feature="base", cloud="government", region="*"),
    )
    assert validate_profile(profile("government", "usdodeast"), m, TODAY).supported
    assert not validate_profile(profile("commercial", "eastus"), m, TODAY).supported


def test_real_data_government_never_resolves_commercial_rows() -> None:
    result = validate_profile(profile("government", "usgovvirginia"), today=TODAY)
    for res in result.results:
        assert res.row_id is None or ".government." in res.row_id
    result = validate_profile(profile("commercial", "eastus"), today=TODAY)
    for res in result.results:
        assert res.row_id is None or ".commercial." in res.row_id


def test_government_unavailable_is_never_filled_from_commercial() -> None:
    m = matrix(
        entry(service="aks", feature="base", cloud="government", region="*"),
        entry(
            service="synapse",
            feature="base",
            cloud="government",
            region="usgovvirginia",
            availability="unavailable",
            ga_status="not_applicable",
        ),
        entry(service="synapse", feature="base", cloud="commercial", region="global"),
    )
    synapse = next(
        r
        for r in validate_profile(profile("government", "usgovvirginia"), m, TODAY).results
        if r.service == "synapse"
    )
    assert synapse.status == "disabled"
    assert synapse.cause == "unavailable"
    assert synapse.row_id == "synapse.base.government.usgovvirginia.any"
