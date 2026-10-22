"""Adapter availability: capability matrix gating and the Government endpoint boundary."""

from __future__ import annotations

import time
import uuid
from typing import Any

import pytest
from azure.core.credentials import AccessToken
from neurosphere_contracts.deployment.v1.capability_matrix_entry import CapabilityMatrixEntry
from neurosphere_core.capabilities import CapabilityMatrix, matrix_from_rows
from neurosphere_core.copilot.models import (
    AdapterAvailability,
    AdapterConfig,
    ApprovedEndpointAdapter,
    FixtureAdapter,
    FoundryAgentAdapter,
    create_adapter,
    endpoint_problem,
    resolve_adapters,
)
from neurosphere_core.errors import CapabilityUnavailableError

GOV_ENDPOINT = "https://ns-test.openai.azure.us"
COM_ENDPOINT = "https://ns-test.openai.azure.com"
FOUNDRY_GOV = "https://ns-test.services.ai.azure.us/api/projects/ns"
FOUNDRY_COM = "https://ns-test.services.ai.azure.com/api/projects/ns"
SKU = "Data Zone Standard"


class _Credential:
    async def get_token(self, *_scopes: str, **_kwargs: Any) -> AccessToken:
        return AccessToken(f"tok-{uuid.uuid4().hex}", int(time.time()) + 3600)

    async def close(self) -> None:
        return None


def _row(
    feature: str, cloud: str, region: str, availability: str = "available", sku: str | None = None
) -> CapabilityMatrixEntry:
    sku_part = "any" if sku is None else sku.lower().replace(" ", "-")
    region_part = region
    return CapabilityMatrixEntry.model_validate(
        {
            "schema_version": "1.1.0",
            "id": f"foundry.{feature}.{cloud}.{region_part}.{sku_part}",
            "service": "foundry",
            "feature": feature,
            "cloud": cloud,
            "region": region,
            "sku": sku,
            "availability": availability,
            "ga_status": "unverified",
            "authorization_scope": "none_claimed",
            "source_url": "https://learn.microsoft.com/azure/foundry/concepts/foundry-azure-government",
            "observed_on": "2026-10-08",
            "notes": "synthetic test row",
        }
    )


def _matrix(*rows: CapabilityMatrixEntry) -> CapabilityMatrix:
    return matrix_from_rows(list(rows))


def _approved(endpoint: str, feature: str = "model_gpt_4o") -> AdapterConfig:
    return AdapterConfig(
        kind="approved_endpoint",
        endpoint=endpoint,
        deployment="gpt-4o",
        model_feature=feature,
        sku=SKU,
    )


def _foundry(endpoint: str) -> AdapterConfig:
    return AdapterConfig(
        kind="foundry_agent",
        endpoint=endpoint,
        deployment="ns-copilot",
        model_feature="model_gpt_4o",
        sku=SKU,
        oauth_scope="https://ai.azure.us/.default",
    )


def _by_kind(entries: tuple[AdapterAvailability, ...]) -> dict[str, AdapterAvailability]:
    return {e.kind: e for e in entries}


def test_every_kind_is_always_reported() -> None:
    entries = resolve_adapters(cloud="government", region="usgovvirginia", configs=[])
    assert [e.kind for e in entries] == ["fixture", "approved_endpoint", "foundry_agent"]
    by = _by_kind(entries)
    assert by["fixture"].enabled
    assert not by["approved_endpoint"].enabled
    assert by["approved_endpoint"].reason_code == "not_configured"
    assert by["foundry_agent"].reason


def test_government_approved_endpoint_is_enabled_by_the_shipped_matrix() -> None:
    entries = resolve_adapters(
        cloud="government", region="usgovvirginia", configs=[_approved(GOV_ENDPOINT)]
    )
    approved = _by_kind(entries)["approved_endpoint"]
    assert approved.enabled, approved.reason
    assert approved.capabilities
    assert all(c.status == "supported" for c in approved.capabilities)


def test_government_foundry_agent_is_disabled_with_the_matrix_reason() -> None:
    entries = resolve_adapters(
        cloud="government", region="usgovvirginia", configs=[_foundry(FOUNDRY_GOV)]
    )
    foundry = _by_kind(entries)["foundry_agent"]
    assert not foundry.enabled
    assert foundry.reason_code == "not_verified"
    assert foundry.reason is not None
    assert "agent_function_calling" in foundry.reason
    assert foundry.capabilities, "the matrix evidence is returned alongside the reason"


def test_unavailable_model_row_disables_with_its_reason() -> None:
    entries = resolve_adapters(
        cloud="government",
        region="usgovvirginia",
        configs=[
            _approved(GOV_ENDPOINT, "model_gpt_5_1").model_copy(update={"sku": "Regional Standard"})
        ],
    )
    approved = _by_kind(entries)["approved_endpoint"]
    assert not approved.enabled
    assert approved.reason_code == "not_available_in_region"


def test_commercial_deployment_without_matrix_rows_is_disabled_unverified() -> None:
    entries = resolve_adapters(
        cloud="commercial", region="eastus", configs=[_approved(COM_ENDPOINT)]
    )
    approved = _by_kind(entries)["approved_endpoint"]
    assert not approved.enabled
    assert approved.reason_code == "not_verified"


def test_commercial_deployment_is_enabled_only_by_commercial_rows() -> None:
    matrix = _matrix(_row("model_gpt_4o", "commercial", "global", sku=SKU))
    entries = resolve_adapters(
        cloud="commercial", region="eastus", configs=[_approved(COM_ENDPOINT)], matrix=matrix
    )
    assert _by_kind(entries)["approved_endpoint"].enabled


def test_government_never_resolves_from_a_commercial_row() -> None:
    matrix = _matrix(_row("model_gpt_4o", "commercial", "global", sku=SKU))
    entries = resolve_adapters(
        cloud="government", region="usgovvirginia", configs=[_approved(GOV_ENDPOINT)], matrix=matrix
    )
    assert not _by_kind(entries)["approved_endpoint"].enabled


def test_government_deployment_refuses_a_commercial_endpoint() -> None:
    entries = resolve_adapters(
        cloud="government", region="usgovvirginia", configs=[_approved(COM_ENDPOINT)]
    )
    approved = _by_kind(entries)["approved_endpoint"]
    assert not approved.enabled
    assert approved.reason_code == "endpoint_cloud_mismatch"
    assert approved.reason is not None
    assert "Commercial" in approved.reason


def test_commercial_deployment_refuses_a_government_endpoint() -> None:
    matrix = _matrix(_row("model_gpt_4o", "commercial", "global", sku=SKU))
    entries = resolve_adapters(
        cloud="commercial", region="eastus", configs=[_approved(GOV_ENDPOINT)], matrix=matrix
    )
    assert _by_kind(entries)["approved_endpoint"].reason_code == "endpoint_cloud_mismatch"


def test_foundry_enabled_when_every_required_row_is_available() -> None:
    matrix = _matrix(
        _row("base", "government", "usgovvirginia"),
        _row("agent_function_calling", "government", "global"),
        _row("model_gpt_4o", "government", "usgovvirginia", sku=SKU),
    )
    entries = resolve_adapters(
        cloud="government", region="usgovvirginia", configs=[_foundry(FOUNDRY_GOV)], matrix=matrix
    )
    assert _by_kind(entries)["foundry_agent"].enabled


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://ns-test.openai.azure.com",
        "https://evil.example/?next=ns.azure.us",
        "https://ns.azure.us.evil.example",
        "https://evil.example/ns.azure.us",
        "http://ns-test.openai.azure.us",
        "https://user:pass@ns-test.openai.azure.us",
        "https://notazure.us",
        "",
    ],
)
def test_government_endpoint_check_uses_the_parsed_hostname(endpoint: str) -> None:
    assert endpoint_problem("government", endpoint) is not None


@pytest.mark.parametrize(
    "endpoint",
    [GOV_ENDPOINT, "https://ns-test.services.ai.azure.us", "https://ns.x.usgovcloudapi.net"],
)
def test_government_hosts_are_accepted(endpoint: str) -> None:
    assert endpoint_problem("government", endpoint) is None


def test_commercial_requires_an_approved_azure_ai_host() -> None:
    assert endpoint_problem("commercial", COM_ENDPOINT) is None
    code, _ = endpoint_problem("commercial", "https://api.example.com") or ("", "")
    assert code == "endpoint_not_approved"


def test_create_adapter_refuses_a_disabled_entry() -> None:
    entries = resolve_adapters(
        cloud="government", region="usgovvirginia", configs=[_approved(COM_ENDPOINT)]
    )
    with pytest.raises(CapabilityUnavailableError) as info:
        create_adapter(
            _by_kind(entries)["approved_endpoint"],
            cloud="government",
            credential=_Credential(),  # pyright: ignore[reportArgumentType]
        )
    assert info.value.reason == "endpoint_cloud_mismatch"


def test_adapter_constructors_recheck_the_endpoint_themselves() -> None:
    with pytest.raises(CapabilityUnavailableError):
        ApprovedEndpointAdapter(
            _approved(COM_ENDPOINT),
            cloud="government",
            credential=_Credential(),  # pyright: ignore[reportArgumentType]
        )
    with pytest.raises(CapabilityUnavailableError):
        FoundryAgentAdapter(
            _foundry(FOUNDRY_COM),
            cloud="government",
            credential=_Credential(),  # pyright: ignore[reportArgumentType]
        )


def test_create_adapter_builds_enabled_adapters() -> None:
    entries = _by_kind(
        resolve_adapters(
            cloud="government", region="usgovvirginia", configs=[_approved(GOV_ENDPOINT)]
        )
    )
    adapter = create_adapter(
        entries["approved_endpoint"],
        cloud="government",
        credential=_Credential(),  # pyright: ignore[reportArgumentType]
    )
    assert adapter.descriptor.kind == "approved_endpoint"
    fixture = create_adapter(entries["fixture"], cloud="government", scenario="tool_call")
    assert isinstance(fixture, FixtureAdapter)
    assert fixture.descriptor.synthetic


def test_rest_adapters_need_a_credential() -> None:
    entries = _by_kind(
        resolve_adapters(
            cloud="government", region="usgovvirginia", configs=[_approved(GOV_ENDPOINT)]
        )
    )
    with pytest.raises(CapabilityUnavailableError) as info:
        create_adapter(entries["approved_endpoint"], cloud="government")
    assert info.value.reason == "credential_required"


def test_government_foundry_needs_an_explicit_token_scope() -> None:
    config = _foundry(FOUNDRY_GOV).model_copy(update={"oauth_scope": None})
    with pytest.raises(CapabilityUnavailableError) as info:
        FoundryAgentAdapter(
            config,
            cloud="government",
            credential=_Credential(),  # pyright: ignore[reportArgumentType]
        )
    assert info.value.reason == "token_scope_required"


def test_config_has_no_field_for_a_raw_key() -> None:
    from pydantic import ValidationError

    for forbidden in ("api_key", "key", "secret", "connection_string"):
        with pytest.raises(ValidationError):
            AdapterConfig.model_validate({"kind": "approved_endpoint", forbidden: "x"})


def test_duplicate_configs_are_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        resolve_adapters(
            cloud="government",
            region="usgovvirginia",
            configs=[_approved(GOV_ENDPOINT), _approved(GOV_ENDPOINT)],
        )
