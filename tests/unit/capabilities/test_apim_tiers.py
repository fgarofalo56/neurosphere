"""APIM tier x feature x cloud matrix rows (PRP-33 item 1)."""

from __future__ import annotations

from datetime import date
from itertools import product

from neurosphere_contracts.deployment.v1.capability_matrix_entry import CapabilityMatrixEntry
from neurosphere_core.capabilities import (
    DeploymentProfile,
    FeatureRequest,
    default_matrix,
    validate_profile,
)
from neurosphere_core.capabilities.validate import TierCapabilityUnknown, tier_capability

TIERS = (
    "consumption",
    "developer",
    "basic",
    "standard",
    "premium",
    "basic_v2",
    "standard_v2",
    "premium_v2",
)
V2 = ("basic_v2", "standard_v2", "premium_v2")
FEATURES = (
    "llm_token_limit",
    "llm_emit_token_metric",
    "anthropic_messages_schema",
    "mcp_server",
    "backend_pool",
    "gateway_llm_logs",
    "gateway_mcp_logs",
)
CLOUDS = ("commercial", "government")
TODAY = date(2026, 10, 29)


def row(tier: str, feature: str, cloud: str) -> CapabilityMatrixEntry:
    found = tier_capability(default_matrix(), tier=tier, feature=feature, cloud=cloud)
    assert isinstance(found, CapabilityMatrixEntry), (tier, feature, cloud)
    return found


def test_every_tier_feature_cloud_row_exists_with_source_and_date() -> None:
    for tier, feature, cloud in product(TIERS, FEATURES, CLOUDS):
        r = row(tier, feature, cloud)
        assert r.source_url.startswith("https://learn.microsoft.com/azure/api-management/")
        assert r.observed_on == "2026-10-29"
        assert r.authorization_scope == "none_claimed"
    tiered = [r for r in default_matrix().rows if r.service == "apim" and r.feature in FEATURES]
    assert len(tiered) == 112


def test_consumption_rows() -> None:
    for feature in ("llm_token_limit", "llm_emit_token_metric"):
        assert row("consumption", feature, "commercial").availability == "unavailable"
    for feature in FEATURES:
        r = row("consumption", feature, "government")
        assert r.availability == "unavailable"
        assert "not available in US Government" in (r.notes or "")


def test_anthropic_schema_available_only_on_commercial_v2() -> None:
    for tier, cloud in product(TIERS, CLOUDS):
        available = row(tier, "anthropic_messages_schema", cloud).availability == "available"
        assert available == (tier in V2 and cloud == "commercial"), (tier, cloud)


def test_v2_government_rows_are_unverified() -> None:
    for tier, feature in product(V2, FEATURES):
        assert row(tier, feature, "government").availability == "unverified"


def test_log_and_backend_rows_unverified_and_never_assumed_available() -> None:
    for tier, feature in product(TIERS, ("backend_pool", "gateway_llm_logs", "gateway_mcp_logs")):
        r = row(tier, feature, "commercial")
        assert r.availability == "unverified"
        assert "tier applicability not stated on the cited page" in (r.notes or "")


def test_notes_carry_token_limit_scope_and_developer_sla() -> None:
    assert "per gateway" in (row("standard_v2", "llm_token_limit", "commercial").notes or "")
    assert "no SLA" in (row("developer", "mcp_server", "commercial").notes or "")


def test_validate_profile_consumption_token_limit_is_capability_unavailable() -> None:
    profile = DeploymentProfile(
        cloud="commercial",
        regions=("eastus",),
        hosting="aks",
        analytics="fabric",
        features=(FeatureRequest(service="apim", feature="llm_token_limit", sku="consumption"),),
    )
    result = validate_profile(profile, today=TODAY)
    hit = next(
        r for r in result.results if r.capability == "feature:apim.llm_token_limit#consumption"
    )
    assert hit.status == "disabled"
    assert hit.cause == "unavailable"
    assert hit.row_id == "apim.llm_token_limit.commercial.global.consumption"
    assert hit.error is not None
    assert hit.error.code == "capability_unavailable"
    assert hit.reason is not None
    assert "not available in commercial" in hit.reason
    assert hit.row_id in hit.reason


def test_validate_profile_standard_v2_token_limit_supported() -> None:
    profile = DeploymentProfile(
        cloud="commercial",
        regions=("eastus",),
        hosting="aks",
        analytics="fabric",
        features=(FeatureRequest(service="apim", feature="llm_token_limit", sku="standard_v2"),),
    )
    result = validate_profile(profile, today=TODAY)
    hit = next(r for r in result.results if r.capability.endswith("#standard_v2"))
    assert hit.status == "supported"


def test_tier_capability_lookup() -> None:
    found = tier_capability(
        default_matrix(), tier="standard_v2", feature="llm_token_limit", cloud="commercial"
    )
    assert isinstance(found, CapabilityMatrixEntry)
    assert found.id == "apim.llm_token_limit.commercial.global.standard_v2"
    unknown = tier_capability(
        default_matrix(), tier="standard_v3", feature="llm_token_limit", cloud="commercial"
    )
    assert isinstance(unknown, TierCapabilityUnknown)
    assert unknown.availability == "unverified"
    assert unknown.reason
