"""The copilot builder: disabled by default, managed identity only, gated by cloud and matrix.

No test here reaches a model endpoint: the REST adapters are only constructed (construction opens
no connection), and every conversation runs against a scripted adapter override.
"""

from __future__ import annotations

from typing import Any

import pytest
from neurosphere_api.runtime.builders import copilot as copilot_builder
from neurosphere_api.runtime.builders.copilot import (
    CopilotCredentialConfigError,
    refuse_credential_shaped_env,
)
from neurosphere_core.cloud import CloudName, Settings
from neurosphere_core.copilot.models import ApprovedEndpointAdapter
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
