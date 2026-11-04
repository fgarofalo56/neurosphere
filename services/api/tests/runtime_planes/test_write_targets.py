"""API write targets from settings (PRP-35 item 4, issue #132).

The planes builder fills the action plane's ``WriteTargetRegistry`` at startup from
``NS_FOUNDRY_*``/``NS_APIM_*``: Foundry with a fake ARM registers ``foundry-model-swap`` and a
``model_deployment_swap`` validation dry-runs it for a real diff; a permission shortfall
(advisory connector) registers nothing; APIM over ``InMemoryApim`` registers ``apim-gateway``.
The API only plans: the composed connector view never applies.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from azure.core.credentials import AccessToken
from neurosphere_api.actions import get_action_plane
from neurosphere_api.runtime.builders.write_targets import WriteTargetSeams
from neurosphere_connector_apim_gateway import ApplyRecord, InMemoryApim
from neurosphere_core.gateway import (
    DiagnosticsState,
    GatewayRegistration,
    InMemoryGatewayRecordStore,
    InMemoryGatewayStore,
)
from neurosphere_core.gateway.mode import evaluate_permissions
from starlette.requests import Request

from .planes_helpers import (
    ALICE,
    CUSTOMER,
    FINANCE,
    compose_planes,
    configure_auth_env,
    plane_backends,
)

INTENTS = f"/api/v1/actions/domains/{FINANCE}/intents"
SUB = "00000000-1111-2222-3333-444444444444"
TARGET = f"commercial:{CUSTOMER}:foundry:model_deployment:dep1"
GW = "gw-" + "e" * 32
ARM_ID = (
    "/subscriptions/33333333-4444-4555-8666-777777777777/resourceGroups/rg-ai"
    "/providers/Microsoft.ApiManagement/service/apim-demo"
)
START = datetime(2026, 11, 4, 12, 0, 0, tzinfo=UTC)
WRITE_PERMS = {"value": [{"actions": ["Microsoft.CognitiveServices/*"], "notActions": []}]}
READ_PERMS = {"value": [{"actions": ["Microsoft.CognitiveServices/*/read"], "notActions": []}]}
FOUNDRY_ENV = {
    "NS_FOUNDRY_ENABLED": "true",
    "NS_FOUNDRY_SUBSCRIPTION_ID": SUB,
    "NS_FOUNDRY_RESOURCE_GROUP": "rg-ai",
    "NS_FOUNDRY_ACCOUNT": "acct1",
    "NS_FOUNDRY_LOCATION": "eastus2",
}


class FakeCredential:
    async def get_token(self, *scopes: str, **_: Any) -> AccessToken:
        return AccessToken("fake-token-not-a-secret", 0)

    async def close(self) -> None:
        return None


def _model(name: str, version: str) -> dict[str, Any]:
    return {
        "kind": "OpenAI",
        "skuName": "S0",
        "model": {
            "format": "OpenAI",
            "name": name,
            "version": version,
            "capabilities": {"chatCompletion": "true"},
            "lifecycleStatus": "GenerallyAvailable",
            "skus": [{"name": "Standard", "capacity": {"default": 1}}],
        },
    }


class FoundryArm:
    """Scripted ARM for one Foundry deployment (``dep1``) over ``httpx.MockTransport``."""

    def __init__(self, permissions: dict[str, Any]) -> None:
        self.permissions = permissions
        self.requests: list[httpx.Request] = []
        self.deployment: dict[str, Any] = {
            "name": "dep1",
            "etag": "etag-1",
            "sku": {"name": "Standard", "capacity": 3},
            "properties": {
                "model": {"format": "OpenAI", "name": "gpt-4o", "version": "2024-08-06"},
                "provisioningState": "Succeeded",
                "capabilities": {"chatCompletion": "true"},
            },
        }
        self.models = [_model("gpt-4o", "2024-08-06"), _model("gpt-4.1", "2025-04-14")]

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self._handle))

    def writes(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.method != "GET"]

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path.endswith("/providers/Microsoft.Authorization/permissions"):
            return httpx.Response(200, json=self.permissions)
        if path.endswith("/models"):
            return httpx.Response(200, json={"value": self.models})
        if path.endswith("/deployments/dep1") and request.method == "GET":
            return httpx.Response(200, json=self.deployment)
        return httpx.Response(405, json={"error": {"code": "NotAllowedInTest"}})


def _request(app: Any) -> Request:
    return Request({"type": "http", "app": app, "headers": []})


def _swap_body() -> dict[str, Any]:
    return {
        "action_kind": "model_deployment_swap",
        "target": {"canonical_id": TARGET, "entity_type": "model_deployment"},
        "target_version": "etag-1",
        "proposed_diff": {
            "format": "json_patch",
            "operations": [
                {"op": "test", "path": "/properties/model/name", "value": "gpt-4o"},
                {"op": "replace", "path": "/properties/model/name", "value": "gpt-4.1"},
                {"op": "replace", "path": "/properties/model/version", "value": "2025-04-14"},
            ],
        },
        "evidence": [],
        "idempotency_key": "idem-2026-11-04-write-targets-01",
        "channel": "rest",
    }


@pytest.fixture(autouse=True)
def _auth(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_auth_env(monkeypatch)


def _env(monkeypatch: pytest.MonkeyPatch, values: dict[str, str]) -> None:
    for name, value in values.items():
        monkeypatch.setenv(name, value)


def _seams(arm: FoundryArm | None = None, apim: InMemoryApim | None = None) -> WriteTargetSeams:
    return WriteTargetSeams(
        credential=FakeCredential(),  # type: ignore[arg-type]
        foundry_http=None if arm is None else arm.client(),
        apim_arm=apim,
        apim_records=InMemoryGatewayRecordStore(ApplyRecord),
    )


def test_foundry_settings_register_the_swap_and_validation_dry_runs_a_real_diff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _env(monkeypatch, FOUNDRY_ENV)
    arm = FoundryArm(WRITE_PERMS)
    planes = compose_planes(backends=plane_backends(write_target_seams=_seams(arm)))
    assert planes.registry.get("action_plane").state == "ok"
    with planes.composed.client() as client:
        plane = get_action_plane(_request(planes.app))
        assert plane.write_targets.names() == ("foundry-model-swap",)  # type: ignore[attr-defined]
        assert plane.connector_for("model_deployment_swap") is not None
        drafted = client.post(INTENTS, json=_swap_body(), headers=planes.auth(ALICE))
        assert drafted.status_code == 201, drafted.text
        intent_id = drafted.json()["intent"]["intent_id"]
        validated = client.post(f"{INTENTS}/{intent_id}/validate", headers=planes.auth(ALICE))
    assert validated.status_code == 200, validated.text
    view = validated.json()
    assert view["advisory"] is False
    checks = {c["check_id"]: c for c in view["intent"]["prerequisite_results"]}
    assert checks["write_connector_supported"]["status"] == "passed"
    # A real plan against the (fake) ARM deployment: the model changes, nothing is written.
    assert checks["target_dry_run"]["status"] == "passed", checks["target_dry_run"]
    assert any(r.url.path.endswith("/deployments/dep1") for r in arm.requests)
    assert arm.writes() == []


def test_a_permission_shortfall_registers_nothing_and_the_intent_stays_advisory(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING, logger="neurosphere.workers.runtime")
    _env(monkeypatch, FOUNDRY_ENV)
    arm = FoundryArm(READ_PERMS)
    planes = compose_planes(backends=plane_backends(write_target_seams=_seams(arm)))
    with planes.composed.client():
        plane = get_action_plane(_request(planes.app))
        assert plane.write_targets.names() == ()  # type: ignore[attr-defined]
        assert plane.connector_for("model_deployment_swap") is None
    reasons = [getattr(r, "reason", None) for r in caplog.records]
    assert "connector_advisory" in reasons
    assert arm.writes() == []


def test_incomplete_foundry_settings_register_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    _env(monkeypatch, {**FOUNDRY_ENV, "NS_FOUNDRY_ACCOUNT": ""})
    arm = FoundryArm(WRITE_PERMS)
    planes = compose_planes(backends=plane_backends(write_target_seams=_seams(arm)))
    with planes.composed.client():
        plane = get_action_plane(_request(planes.app))
        assert plane.write_targets.names() == ()  # type: ignore[attr-defined]
    assert arm.requests == []


def test_malformed_write_target_settings_fail_the_action_plane_by_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _env(monkeypatch, {"NS_FOUNDRY_ENABLED": "perhaps"})
    planes = compose_planes()
    assert planes.registry.get("action_plane").code == "write_target_settings_invalid"


def _gateway() -> GatewayRegistration:
    return GatewayRegistration.model_validate(
        {
            "id": GW,
            "customer_id": CUSTOMER,
            "domain_id": FINANCE,
            "cloud": "commercial",
            "arm_resource_id": ARM_ID,
            "name": "apim-demo",
            "tier": "standard_v2",
            "workspace_id": None,
            "diagnostics": DiagnosticsState(gateway_logs=False),
            "created_at": START,
            "updated_at": START,
            "registered_by": "pn-admin",
            "mode": "manage",
            "mode_changed_by": "pn-switch",
            "mode_changed_at": START,
            "mode_revision": 1,
            "preflight": evaluate_permissions(
                [{"actions": ["Microsoft.ApiManagement/service/*"]}], now=START
            ),
        }
    )


def test_apim_settings_with_an_in_memory_gateway_register_the_gateway_connector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _env(monkeypatch, {"NS_APIM_ENABLED": "true", "NS_APIM_GATEWAY_ID": GW})
    monkeypatch.setenv("NS_APIM_DOMAIN_ID", FINANCE)
    store = InMemoryGatewayStore()
    asyncio.run(store.create(_gateway()))
    apim = InMemoryApim()
    planes = compose_planes(
        backends=plane_backends(write_target_seams=_seams(apim=apim), gateway_store=store)
    )
    with planes.composed.client():
        plane = get_action_plane(_request(planes.app))
        assert plane.write_targets.names() == ("apim-gateway",)  # type: ignore[attr-defined]
    assert apim.writes() == []
