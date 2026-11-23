"""The copilot builder: disabled by default, managed identity only, gated by cloud and matrix.

No test here reaches a model endpoint: the REST adapters are only constructed (construction opens
no connection), and every conversation runs against a scripted adapter override.
"""

from __future__ import annotations

from typing import Any

import pytest
from neurosphere_api.copilot.evidence import StoreEvidenceReader
from neurosphere_api.copilot.tooling import CopilotExtraPorts, CopilotToolAuditor
from neurosphere_api.runtime.builders import copilot as copilot_builder
from neurosphere_api.runtime.builders.copilot import (
    CopilotCredentialConfigError,
    CopilotRuntimeSettings,
    refuse_credential_shaped_env,
)
from neurosphere_contracts.admin.v1.system_setting import SystemSetting
from neurosphere_core.admin.runtime import copilot_init_args
from neurosphere_core.cloud import CloudName, Settings
from neurosphere_core.copilot.models import ApprovedEndpointAdapter, RecordedDemoAdapter
from pydantic import ValidationError
from runtime_api.runtime_helpers import compose  # pyright: ignore[reportMissingImports]

from .planes_helpers import ALICE, ch, compose_planes, configure_auth_env

CONVERSATIONS = "/api/v1/copilot/conversations"
GOV_ENDPOINT = "https://ns-test.openai.azure.us"
COM_ENDPOINT = "https://ns-test.openai.azure.com"


@pytest.fixture(autouse=True)
def _auth(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_auth_env(monkeypatch)


def _copilot_env(monkeypatch: pytest.MonkeyPatch, **values: str) -> None:
    for name, value in values.items():
        monkeypatch.setenv(f"NS_COPILOT_{name}", value)


def _readyz(planes: Any) -> tuple[int, dict[str, str]]:
    with planes.composed.client() as client:
        response = client.get("/readyz")
    return response.status_code, response.json()["dependencies"]


def _copilot_only() -> Any:
    """Compose only the copilot builder under the environment's settings (cloud included)."""
    return compose(builders=(copilot_builder.BUILDER,), settings=Settings())


def test_default_mode_is_disabled_and_routes_stay_unconfigured() -> None:
    planes = compose_planes()
    assert planes.registry.get("copilot").state == "disabled"
    status, deps = _readyz(planes)
    assert status == 200
    assert deps["composition.copilot.disabled"] == "ok"
    with planes.composed.client() as client:
        response = client.post(CONVERSATIONS, headers=planes.auth(ALICE))
    assert response.status_code == 503
    assert response.json()["reason"] == "copilot_unconfigured"


def test_approved_endpoint_without_an_endpoint_is_misconfigured_and_blocks_readiness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _copilot_env(monkeypatch, MODE="approved_endpoint", DEPLOYMENT="gpt-4o")
    planes = compose_planes()
    copilot = planes.registry.get("copilot")
    assert (copilot.state, copilot.code) == ("failed", "misconfigured")
    status, deps = _readyz(planes)
    # status.py: a FAILED optional component blocks readiness; only ``disabled`` does not.
    assert status == 503
    assert deps["composition.copilot.misconfigured"] == "unavailable"


@pytest.mark.parametrize(
    "values",
    [
        {"MODE": "foundry_agent", "ENDPOINT": COM_ENDPOINT},  # no agent name
        {"MODE": "approved_endpoint", "ENDPOINT": COM_ENDPOINT, "DEPLOYMENT": "gpt-4o"},  # region
        {"MODE": "no_such_mode"},
        {
            "MODE": "approved_endpoint",
            "ENDPOINT": COM_ENDPOINT,
            "DEPLOYMENT": "has spaces",
            "REGION": "eastus2",
            "MODEL_FEATURE": "model_gpt_4o",
        },
    ],
)
def test_incomplete_or_invalid_settings_are_misconfigured(
    monkeypatch: pytest.MonkeyPatch, values: dict[str, str]
) -> None:
    _copilot_env(monkeypatch, **values)
    planes = compose_planes()
    assert planes.registry.get("copilot").code == "misconfigured"


def test_a_government_endpoint_is_refused_in_a_commercial_deployment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _copilot_env(
        monkeypatch,
        MODE="approved_endpoint",
        ENDPOINT=GOV_ENDPOINT,
        DEPLOYMENT="gpt-4o",
        REGION="eastus2",
        MODEL_FEATURE="model_gpt_4o",
    )
    planes = compose_planes()  # NS_ENV=local, no NS_CLOUD: Commercial
    assert planes.registry.get("copilot").code == "endpoint_cloud_mismatch"


def test_a_government_deployment_never_uses_a_commercial_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NS_CLOUD", "government")
    _copilot_env(
        monkeypatch,
        MODE="approved_endpoint",
        ENDPOINT=COM_ENDPOINT,
        DEPLOYMENT="gpt-4o",
        REGION="usgovvirginia",
        MODEL_FEATURE="model_gpt_4o",
    )
    assert Settings().cloud is CloudName.GOVERNMENT
    assert _copilot_only().registry.get("copilot").code == "endpoint_cloud_mismatch"


def test_an_unapproved_host_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    _copilot_env(
        monkeypatch,
        MODE="approved_endpoint",
        ENDPOINT="https://models.example.com",
        DEPLOYMENT="gpt-4o",
        REGION="eastus2",
        MODEL_FEATURE="model_gpt_4o",
    )
    planes = compose_planes()
    assert planes.registry.get("copilot").code == "endpoint_not_approved"


def test_the_capability_matrix_gates_the_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    # Government Foundry agents are not verified in the shipped matrix: disabled with its reason.
    monkeypatch.setenv("NS_CLOUD", "government")
    _copilot_env(
        monkeypatch,
        MODE="foundry_agent",
        ENDPOINT="https://ns-test.services.ai.azure.us/api/projects/ns",
        DEPLOYMENT="ns-copilot",
        REGION="usgovvirginia",
        MODEL_FEATURE="model_gpt_4o",
        SKU="Data Zone Standard",
        OAUTH_SCOPE="https://ai.azure.us/.default",
    )
    assert _copilot_only().registry.get("copilot").code == "not_verified"


def test_an_enabled_government_endpoint_builds_the_managed_identity_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NS_CLOUD", "government")
    _copilot_env(
        monkeypatch,
        MODE="approved_endpoint",
        ENDPOINT=GOV_ENDPOINT,
        DEPLOYMENT="gpt-4o",
        REGION="usgovvirginia",
        MODEL_FEATURE="model_gpt_4o",
        SKU="Data Zone Standard",
        API_VERSION="2024-10-21",
    )
    built: list[Any] = []
    real_install = copilot_builder._install  # pyright: ignore[reportPrivateUsage]

    def capture(ctx: Any, adapter: Any) -> None:
        built.append(adapter)
        real_install(ctx, adapter)

    monkeypatch.setattr(copilot_builder, "_install", capture)
    composed = _copilot_only()
    [adapter] = built
    assert isinstance(adapter, ApprovedEndpointAdapter)
    assert adapter.url == (
        f"{GOV_ENDPOINT}/openai/deployments/gpt-4o/chat/completions?api-version=2024-10-21"
    )
    # Composed alone (no data builder) the tool read ports are missing, and that is named.
    assert composed.registry.get("copilot").code == "catalog_repository_unavailable"


def test_a_scripted_adapter_override_serves_chat() -> None:
    planes = compose_planes(model_adapter=ch.ScriptedAdapter(ch.say("Nothing changed.")))
    assert planes.registry.get("copilot").state == "ok"
    with planes.composed.client() as client:
        created = client.post(CONVERSATIONS, headers=planes.auth(ALICE))
    assert created.status_code == 201, created.text


def test_installing_the_copilot_wires_the_store_backed_evidence_reader() -> None:
    planes = compose_planes(model_adapter=ch.ScriptedAdapter(ch.say("Nothing changed.")))
    assert planes.registry.get("copilot").state == "ok"
    assert isinstance(planes.app.state.copilot_evidence_reader, StoreEvidenceReader)


@pytest.mark.parametrize(
    "name",
    ["NS_COPILOT_API_KEY", "NS_COPILOT_CLIENT_SECRET", "NS_COPILOT_KEY", "NS_COPILOT_PASSWORD"],
)
def test_a_credential_shaped_copilot_variable_refuses_startup(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    monkeypatch.setenv(name, "placeholder")
    with pytest.raises(CopilotCredentialConfigError) as refused:
        compose_planes()
    assert name in str(refused.value)
    assert "placeholder" not in str(refused.value)


def test_the_refusal_applies_even_when_the_copilot_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _copilot_env(monkeypatch, MODE="disabled", ENDPOINT_KEY="placeholder")
    with pytest.raises(CopilotCredentialConfigError):
        compose_planes()


def test_the_refusal_names_variables_never_values() -> None:
    marker = "value-that-must-not-appear"
    with pytest.raises(CopilotCredentialConfigError) as refused:
        refuse_credential_shaped_env({"NS_COPILOT_SECRET": marker, "NS_OTHER_KEY": marker})
    assert marker not in str(refused.value)
    assert "NS_OTHER_KEY" not in str(refused.value)  # only NS_COPILOT_* is in scope


def test_non_credential_copilot_variables_are_accepted() -> None:
    refuse_credential_shaped_env(
        {"NS_COPILOT_MODE": "disabled", "NS_COPILOT_OAUTH_SCOPE": "x", "NS_OTHER_SECRET": "x"}
    )


# -- recorded demo mode (PRP-78 item 6): env-only, NS_ENV=local only ------------------------------


def test_recorded_mode_in_a_local_environment_composes_the_synthetic_demo_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _copilot_env(monkeypatch, MODE="recorded")
    planes = compose_planes()  # NS_ENV=local
    assert planes.registry.get("copilot").state == "ok"
    adapter = planes.app.state.copilot_model_adapter
    assert isinstance(adapter, RecordedDemoAdapter)
    assert adapter.descriptor.synthetic is True
    assert adapter.descriptor.name == "recorded-demo"
    with planes.composed.client() as client:
        created = client.post(CONVERSATIONS, headers=planes.auth(ALICE))
    assert created.status_code == 201, created.text


@pytest.mark.parametrize("env", ["dev", "test", "staging", "prod"])
def test_recorded_mode_outside_local_is_misconfigured(
    monkeypatch: pytest.MonkeyPatch, env: str
) -> None:
    monkeypatch.setenv("NS_ENV", env)
    monkeypatch.setenv("NS_CLOUD", "commercial")
    _copilot_env(monkeypatch, MODE="recorded")
    copilot = _copilot_only().registry.get("copilot")
    assert (copilot.state, copilot.code) == ("failed", "misconfigured")


def test_a_stored_setting_cannot_select_recorded_mode() -> None:
    stored = SystemSetting.model_validate(
        {
            "schema_version": "1.0.0",
            "setting_key": "copilot",
            "enabled": True,
            "copilot": {
                "endpoint": COM_ENDPOINT,
                "deployment": "gpt-4o",
                "api_version": "2024-10-21",
                "resource_id": (
                    "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-ns"
                    "/providers/Microsoft.CognitiveServices/accounts/acct"
                ),
                "credential": {
                    "kind": "managed_identity",
                    "managed_identity_client_id": "0b5d0c6e-1f2a-4b3c-8d4e-5f6a7b8c9d0e",
                },
            },
        }
    )
    # With the env mode disabled a stored setting picks the endpoint adapter, never recorded.
    args = copilot_init_args(stored, env_mode="disabled")
    assert CopilotRuntimeSettings(**args).mode == "approved_endpoint"
    # The stored member has no mode field to carry one.
    body = stored.model_dump(mode="json", by_alias=True)
    body["copilot"]["mode"] = "recorded"
    with pytest.raises(ValidationError):
        SystemSetting.model_validate(body)


def test_extra_tool_ports_and_the_tool_auditor_are_wired_for_every_mode() -> None:
    planes = compose_planes(model_adapter=ch.ScriptedAdapter(ch.say("Nothing changed.")))
    assert planes.registry.get("copilot").state == "ok"
    assert isinstance(planes.app.state.copilot_extra_ports, CopilotExtraPorts)
    assert isinstance(planes.app.state.copilot_tool_auditor, CopilotToolAuditor)


def test_recorded_mode_also_wires_the_extra_ports_and_auditor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _copilot_env(monkeypatch, MODE="recorded")
    planes = compose_planes()
    assert isinstance(planes.app.state.copilot_extra_ports, CopilotExtraPorts)
    assert isinstance(planes.app.state.copilot_tool_auditor, CopilotToolAuditor)
