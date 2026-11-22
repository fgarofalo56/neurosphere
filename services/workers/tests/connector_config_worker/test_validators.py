"""PRP-42 item 2: validators build the worker's own settings; a refusal names a field pointer."""

from __future__ import annotations

from typing import Any

import pytest
from neurosphere_contracts.admin.v1.connector_config import ConnectorConfig
from neurosphere_core.errors import InvalidSchemaError
from neurosphere_workers.connector_config import VALIDATORS

from .support import IDENTITY, WORKSPACE, billing, config, foundry, gateway, monitor


def _check(body: dict[str, Any], cloud: str = "commercial"):
    return VALIDATORS[body["connector_kind"]](ConnectorConfig.model_validate(body), cloud=cloud)  # type: ignore[arg-type]


def _refused(body: dict[str, Any], cloud: str = "commercial") -> InvalidSchemaError:
    with pytest.raises(InvalidSchemaError) as caught:
        _check(body, cloud)
    return caught.value


def test_valid_configs_pass_and_report_producer_identity() -> None:
    check = _check(gateway())
    assert (check.producer_id, check.source_id) == ("apim-gateway-poll", "apim-gateway-poll")
    assert _check(billing()).source_id == "azure-billing-export"
    assert _check(foundry()).warnings == ("credential_not_applied",)
    otel = config("otel", settings={"producer_id": "p", "source_id": "s"}, credential=IDENTITY)
    assert _check(otel).source_id == "s"


def test_partial_billing_config_is_a_422_with_pointer() -> None:
    body = billing()
    del body["settings"]["manifest_blob"]
    error = _refused(body)
    assert error.reason == "billing_export_manifest_blob_missing"
    assert error.errors is not None and error.errors[0].pointer == "/settings/manifest_blob"


def test_gateway_without_api_base_url_or_with_unknown_key_is_refused() -> None:
    assert _refused(config("gateway_poll")).reason == "gateway_poll_api_base_url_missing"
    assert _refused(gateway(bogus=1)).reason == "connector_setting_unknown"


def test_out_of_range_value_is_refused_by_the_settings_class() -> None:
    error = _refused(billing(interval_seconds=60))
    assert error.errors is not None and error.errors[0].pointer == "/settings/interval_seconds"


def test_billing_in_government_is_unsupported_and_url_must_be_commercial_blob() -> None:
    assert _refused(billing(), "government").reason == "billing_export_cloud_unsupported"
    bad = billing(storage_account_url="https://evil.blob.core.windows.net.evil.test")
    assert _refused(bad).reason == "billing_export_storage_account_url_invalid"


def test_foundry_needs_one_domain_and_valid_projects() -> None:
    two = foundry()
    two["domain_ids"].append("commercial:synthco:neurosphere:domain:d2")
    assert _refused(two).reason == "foundry_discovery_single_domain_required"
    assert _refused(foundry(projects="no-slash")).reason == "foundry_discovery_projects_invalid"


def test_secret_bearing_kinds_need_a_key_vault_reference() -> None:
    assert (
        _refused(
            config("gateway_poll", credential=IDENTITY, settings={"api_base_url": "http://x"})
        ).reason
        == "gateway_poll_credential_invalid"
    )
    body = foundry()
    body["credential"] = {
        "kind": "key_vault_secret",
        "secret_uri": "https://ns-kv.vault.azure.net/secrets/x",
    }
    assert _refused(body).reason == "foundry_discovery_credential_invalid"


def test_managed_identity_setting_must_be_a_guid() -> None:
    assert (
        _refused(gateway(managed_identity_client_id="not-a-guid")).reason
        == "connector_setting_invalid"
    )


def test_azure_monitor_ai_valid_config_reports_producer_identity() -> None:
    check = _check(monitor())
    assert (check.producer_id, check.source_id) == ("azure-monitor-ai", "azure-monitor-ai")


def _pointer(error: InvalidSchemaError) -> str:
    assert error.errors is not None
    return error.errors[0].pointer


def test_azure_monitor_ai_refuses_bad_settings_with_pointers() -> None:
    unknown = _refused(monitor(bogus=1))
    assert unknown.reason == "connector_setting_unknown" and _pointer(unknown) == "/settings/bogus"
    assert _pointer(_refused(monitor(workspace_ids="not-a-guid"))) == "/settings/workspace_ids"
    five = ",".join(f"{i}1111111-2222-4333-8444-555555555555" for i in range(5))
    assert _pointer(_refused(monitor(workspace_ids=five))) == "/settings/workspace_ids"
    assert _pointer(_refused(monitor(interval_seconds=30))) == "/settings/interval_seconds"
    assert _check(monitor(workspace_ids=f"{WORKSPACE},{WORKSPACE}")).producer_id is not None


def test_azure_monitor_ai_needs_a_secret_reference_not_an_identity() -> None:
    body = monitor()
    body["credential"] = IDENTITY
    error = _refused(body)
    assert error.reason == "azure_monitor_ai_credential_invalid"
    assert _pointer(error) == "/credential"


def test_azure_monitor_ai_needs_one_domain_and_the_runtime_cloud() -> None:
    two = monitor()
    two["domain_ids"].append("commercial:synthco:neurosphere:domain:d2")
    assert _refused(two).reason == "azure_monitor_ai_single_domain_required"
    error = _refused(monitor(), "government")
    assert error.reason == "cloud_mismatch" and _pointer(error) == "/domain_ids"
