"""validate_profile: supported, unavailable, unverified, preview, SKU and staleness."""

from __future__ import annotations

from datetime import date
from typing import Literal

import pytest
from neurosphere_core.capabilities import (
    CapabilityResult,
    DeploymentProfile,
    FeatureRequest,
    ProfileResult,
    default_matrix,
    validate_profile,
)
from pydantic import ValidationError
from rows import entry, matrix

TODAY = date(2026, 10, 11)


def by_cap(result: ProfileResult, capability: str, region: str | None = None) -> CapabilityResult:
    hits = [r for r in result.results if r.capability == capability and region in (None, r.region)]
    assert len(hits) == 1, capability
    return hits[0]


def gov_profile(**kw: object) -> DeploymentProfile:
    base: dict[str, object] = {
        "cloud": "government",
        "regions": ("usgovvirginia",),
        "hosting": "aks",
        "analytics": "fabric",
    }
    return DeploymentProfile.model_validate({**base, **kw})


def test_government_supported_combination_passes_with_synthetic_hosting_rows() -> None:
    m = matrix(
        entry(service="aks", feature="base", region="*"),
        entry(service="fabric", feature="base", region="usgovvirginia"),
    )
    result = validate_profile(gov_profile(), m, TODAY)
    assert result.supported
    assert all(r.error is None and r.cause is None for r in result.results)


def test_real_government_fabric_and_aks_hosting_are_supported() -> None:
    result = validate_profile(gov_profile(), today=TODAY)
    fabric = by_cap(result, "analytics:fabric.base")
    assert fabric.status == "supported"
    assert fabric.row_id == "fabric.base.government.usgovvirginia.any"
    assert fabric.authorization_scope is not None
    hosting = by_cap(result, "hosting:aks.base")
    assert hosting.status == "supported"
    assert any(w.startswith("ga_unverified:") for w in hosting.warnings)
    assert result.supported


def test_real_government_app_service_hosting_is_supported_with_citation_only() -> None:
    result = validate_profile(gov_profile(hosting="appservice"), today=TODAY)
    host = by_cap(result, "hosting:app_service.base")
    assert host.status == "supported"
    assert host.row_id == "app_service.base.government.any.any"
    assert any(w.startswith("ga_unverified:") for w in host.warnings)
    assert host.authorization_scope is not None
    assert "not an agency authorization" in host.authorization_scope


def test_real_commercial_hosting_stays_unverified_and_disabled() -> None:
    cases: tuple[tuple[Literal["aks", "appservice"], str], ...] = (
        ("aks", "aks"),
        ("appservice", "app_service"),
    )
    for hosting, service in cases:
        profile = DeploymentProfile(
            cloud="commercial", regions=("eastus",), hosting=hosting, analytics="fabric"
        )
        host = by_cap(validate_profile(profile, today=TODAY), f"hosting:{service}.base")
        assert host.status == "disabled"
        assert host.cause == "unverified"
        assert host.row_id == f"{service}.base.commercial.global.any"


def test_real_government_foundry_agent_mcp_is_unverified_due_to_source_conflict() -> None:
    request = FeatureRequest(service="foundry", feature="agent_mcp_servers")
    profile = gov_profile(features=(request,))
    result = validate_profile(profile, today=TODAY)
    mcp = by_cap(result, "feature:foundry.agent_mcp_servers")
    assert mcp.status == "disabled"
    assert mcp.cause == "unverified"
    assert mcp.row_id == "foundry.agent_mcp_servers.government.global.any"


def test_unavailable_feature_returns_capability_unavailable_naming_row_and_source() -> None:
    profile = gov_profile(
        features=(FeatureRequest(service="fabric", feature="workspace_identity"),)
    )
    result = validate_profile(profile, today=TODAY)
    res = by_cap(result, "feature:fabric.workspace_identity")
    assert res.status == "disabled"
    assert res.cause == "unavailable"
    assert res.row_id == "fabric.workspace_identity.government.usgovvirginia.any"
    assert res.reason is not None
    assert res.row_id in res.reason
    assert res.source_url is not None
    assert res.source_url in res.reason
    assert res.error is not None
    assert res.error.code == "capability_unavailable"
    assert res.error.status == 409
    assert res.error.retryable is False
    assert res.error.reason == "not_available_in_region"
    assert res.error.detail == res.reason


def test_no_row_is_unverified_and_disabled_never_supported() -> None:
    result = validate_profile(gov_profile(regions=("usgovarizona",)), today=TODAY)
    fabric = by_cap(result, "analytics:fabric.base")  # fabric rows exist for VA/TX only
    assert fabric.status == "disabled"
    assert fabric.cause == "unverified"
    assert fabric.row_id is None
    assert fabric.error is not None
    assert fabric.error.code == "capability_unavailable"
    assert fabric.reason is not None
    assert "unverified" in fabric.reason


def test_unverified_row_is_distinct_from_unavailable() -> None:
    profile = DeploymentProfile(
        cloud="commercial", regions=("eastus",), hosting="aks", analytics="fabric"
    )
    fabric = by_cap(validate_profile(profile, today=TODAY), "analytics:fabric.base")
    assert fabric.status == "disabled"
    assert fabric.cause == "unverified"
    assert fabric.row_id == "fabric.base.commercial.global.any"
    assert fabric.reason_code == "not_verified"


def test_commercial_supported_via_global_row() -> None:
    m = matrix(
        entry(service="aks", feature="base", cloud="commercial", region="global"),
        entry(service="synapse", feature="base", cloud="commercial", region="global"),
    )
    profile = DeploymentProfile(
        cloud="commercial", regions=("eastus", "westus3"), hosting="aks", analytics="synapse"
    )
    result = validate_profile(profile, m, TODAY)
    assert result.supported
    assert len(result.results) == 4  # two capabilities x two regions


def test_exact_region_row_beats_wildcard_and_global() -> None:
    m = matrix(
        entry(service="aks", feature="base", region="*"),
        entry(service="aks", feature="base", region="global"),
        entry(
            service="aks",
            feature="base",
            region="usgovvirginia",
            availability="unavailable",
            ga_status="not_applicable",
        ),
        entry(service="fabric", feature="base", region="usgovvirginia"),
    )
    result = validate_profile(gov_profile(), m, TODAY)
    aks = by_cap(result, "hosting:aks.base")
    assert aks.status == "disabled"
    assert aks.cause == "unavailable"
    assert aks.row_id == "aks.base.government.usgovvirginia.any"


def test_one_unsupported_region_disables_only_that_region() -> None:
    m = matrix(
        entry(service="aks", feature="base", region="*"),
        entry(service="fabric", feature="base", region="usgovvirginia"),
    )
    result = validate_profile(gov_profile(regions=("usgovvirginia", "usgovtexas")), m, TODAY)
    assert by_cap(result, "analytics:fabric.base", "usgovvirginia").status == "supported"
    assert by_cap(result, "analytics:fabric.base", "usgovtexas").status == "disabled"
    assert not result.supported


def test_preview_is_disabled_unless_allowed() -> None:
    m = matrix(
        entry(service="aks", feature="base", region="*"),
        entry(service="fabric", feature="base", availability="preview", ga_status="preview"),
    )
    blocked = by_cap(validate_profile(gov_profile(), m, TODAY), "analytics:fabric.base")
    assert blocked.status == "disabled"
    assert blocked.reason_code == "preview_only"
    allowed = by_cap(
        validate_profile(gov_profile(allow_preview=True), m, TODAY), "analytics:fabric.base"
    )
    assert allowed.status == "supported"
    assert any(w.startswith("preview:") for w in allowed.warnings)


def test_ga_unverified_is_supported_with_warning() -> None:
    m = matrix(
        entry(service="aks", feature="base", region="*", ga_status="unverified"),
        entry(service="fabric", feature="base"),
    )
    aks = by_cap(validate_profile(gov_profile(), m, TODAY), "hosting:aks.base")
    assert aks.status == "supported"
    assert any(w.startswith("ga_unverified:") for w in aks.warnings)


def test_sku_resolution() -> None:
    m = matrix(
        entry(service="aks", feature="base", region="*"),
        entry(service="fabric", feature="base"),
        entry(service="foundry", feature="model_x", sku="data-zone-standard"),
        entry(
            service="foundry",
            feature="model_x",
            sku="regional-standard",
            availability="unavailable",
            ga_status="not_applicable",
        ),
    )

    def run(sku: str | None) -> CapabilityResult:
        profile = gov_profile(
            features=(FeatureRequest(service="foundry", feature="model_x", sku=sku),)
        )
        return by_cap(
            validate_profile(profile, m, TODAY),
            f"feature:foundry.model_x{'#' + sku if sku else ''}",
        )

    assert run("data-zone-standard").status == "supported"
    assert run("Regional-Standard").cause == "unavailable"
    unknown = run("global-batch")
    assert (unknown.status, unknown.cause) == ("disabled", "unverified")
    none = run(None)
    assert (none.status, none.cause) == ("disabled", "unverified")
    assert none.reason is not None
    assert "SKU" in none.reason


def test_sku_independent_row_covers_requested_sku() -> None:
    m = matrix(
        entry(service="aks", feature="base", region="*"), entry(service="fabric", feature="base")
    )
    profile = gov_profile(features=(FeatureRequest(service="fabric", feature="base", sku="F64"),))
    assert validate_profile(profile, m, TODAY).supported


def test_stale_row_warns_but_never_changes_status() -> None:
    m = matrix(
        entry(service="aks", feature="base", region="*", observed_on="2026-01-01"),
        entry(service="fabric", feature="base", observed_on="2026-10-01"),
        entry(
            service="synapse",
            feature="base",
            availability="unavailable",
            ga_status="not_applicable",
            observed_on="2026-01-01",
        ),
        entry(
            service="foundry",
            feature="x_feature",
            availability="unverified",
            ga_status="unverified",
            observed_on="2026-01-01",
        ),
    )
    profile = gov_profile(
        features=(
            FeatureRequest(service="synapse", feature="base"),
            FeatureRequest(service="foundry", feature="x_feature"),
        )
    )
    result = validate_profile(profile, m, TODAY)
    aks = by_cap(result, "hosting:aks.base")
    assert aks.status == "supported"
    assert aks.stale
    assert any(w.startswith("stale:") and aks.row_id in w for w in aks.warnings if aks.row_id)
    assert not by_cap(result, "analytics:fabric.base").stale
    assert by_cap(result, "feature:synapse.base").status == "disabled"
    assert by_cap(result, "feature:foundry.x_feature").status == "disabled"
    assert len(result.stale) == 3
    assert len(result.warnings) == 3


def test_stale_threshold_is_90_days() -> None:
    m = matrix(
        entry(service="aks", feature="base", region="*", observed_on="2026-07-13"),
        entry(service="fabric", feature="base", observed_on="2026-07-12"),
    )
    result = validate_profile(gov_profile(), m, TODAY)  # 90 and 91 days old
    assert not by_cap(result, "hosting:aks.base").stale
    assert by_cap(result, "analytics:fabric.base").stale


def test_profile_rejects_region_from_wrong_cloud_or_global() -> None:
    with pytest.raises(ValidationError):
        DeploymentProfile(
            cloud="government", regions=("eastus",), hosting="aks", analytics="fabric"
        )
    with pytest.raises(ValidationError):
        DeploymentProfile(
            cloud="commercial", regions=("usgovvirginia",), hosting="aks", analytics="fabric"
        )
    with pytest.raises(ValidationError):
        DeploymentProfile(
            cloud="commercial", regions=("global",), hosting="aks", analytics="fabric"
        )
    with pytest.raises(ValidationError):
        DeploymentProfile(cloud="commercial", regions=(), hosting="aks", analytics="fabric")


def test_result_is_json_serialisable_for_plan_and_ui() -> None:
    result = validate_profile(gov_profile(), default_matrix(), TODAY)
    dumped = result.model_dump(mode="json")
    assert dumped["results"][0]["capability"].startswith("hosting:")
    assert "error" in dumped["results"][0]
