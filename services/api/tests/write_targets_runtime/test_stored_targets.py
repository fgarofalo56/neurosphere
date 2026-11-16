"""PRP-54 item 3: the API registers write targets from stored entries, per domain."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

import pytest
from neurosphere_api.actions import get_action_plane
from neurosphere_api.runtime.builders.write_targets import WriteTargetSeams
from neurosphere_connector_apim_gateway import ApplyRecord, InMemoryApim
from neurosphere_contracts.admin.v1.system_setting import SystemSetting
from neurosphere_core.admin.runtime import StoredSetting, StoredSettingsSnapshot
from neurosphere_core.gateway import (
    DiagnosticsState,
    GatewayRegistration,
    InMemoryGatewayRecordStore,
    InMemoryGatewayStore,
)
from neurosphere_core.gateway.mode import evaluate_permissions
from runtime_planes.planes_helpers import (  # pyright: ignore[reportMissingImports]
    CUSTOMER,
    FINANCE,
    OPERATIONS,
    compose_planes,
    configure_auth_env,
    plane_backends,
)
from starlette.requests import Request

START = datetime(2026, 11, 4, 12, 0, 0, tzinfo=UTC)
GW_A = "gw-" + "a" * 32
GW_B = "gw-" + "b" * 32
ARM_A = (
    "/subscriptions/33333333-4444-4555-8666-777777777777/resourceGroups/rg-ai"
    "/providers/Microsoft.ApiManagement/service/apim-a"
)
ARM_B = ARM_A.replace("apim-a", "apim-b")
MI = {"kind": "managed_identity", "managed_identity_client_id": None}


class _Credential:
    async def get_token(self, *scopes: str, **_: Any) -> Any:
        from azure.core.credentials import AccessToken

        return AccessToken("fake-token-not-a-secret", 0)

    async def close(self) -> None:
        return None


def _gateway(gateway_id: str, domain: str, arm: str, name: str) -> GatewayRegistration:
    return GatewayRegistration.model_validate(
        {
            "id": gateway_id,
            "customer_id": CUSTOMER,
            "domain_id": domain,
            "cloud": "commercial",
            "arm_resource_id": arm,
            "name": name,
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


def _entry(arm: str, name: str) -> StoredSetting:
    setting = SystemSetting.model_validate(
        {
            "schema_version": "1.0.0",
            "setting_key": "write_target",
            "enabled": True,
            "write_target": {"target_kind": "apim", "resource_id": arm, "credential": MI},
        }
    )
    return StoredSetting("write_targets", f"system.write_target.{name}", setting, 1, '"1"')


def _snapshot(*entries: StoredSetting) -> StoredSettingsSnapshot:
    return StoredSettingsSnapshot(status="loaded", write_targets=entries)


def _store() -> InMemoryGatewayStore:
    store = InMemoryGatewayStore()
    asyncio.run(store.create(_gateway(GW_A, FINANCE, ARM_A, "apim-a")))
    asyncio.run(store.create(_gateway(GW_B, OPERATIONS, ARM_B, "apim-b")))
    return store


def _compose(snapshot: StoredSettingsSnapshot) -> Any:
    seams = WriteTargetSeams(
        credential=_Credential(),  # type: ignore[arg-type]
        apim_arm=InMemoryApim(),
        apim_records=InMemoryGatewayRecordStore(ApplyRecord),
    )
    return compose_planes(
        backends=plane_backends(
            write_target_seams=seams, gateway_store=_store(), stored_settings=snapshot
        )
    )


def _plane(planes: Any) -> Any:
    return get_action_plane(Request({"type": "http", "app": planes.app, "headers": []}))


def _bound(connector: Any) -> str:
    inner = connector._connectors["apim-gateway"]  # the planning view's APIM connector
    return str(inner.gateway.gateway_id)


@pytest.fixture(autouse=True)
def _auth(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_auth_env(monkeypatch)


def test_two_stored_gateways_each_domain_plans_against_its_own(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NS_WRITE_TARGETS_FROM_STORE", "true")
    planes = _compose(_snapshot(_entry(ARM_A, "a"), _entry(ARM_B, "b")))
    with planes.composed.client():
        plane = _plane(planes)
        assert _bound(plane.connector_for("gateway_mode_change", FINANCE)) == GW_A
        assert _bound(plane.connector_for("gateway_mode_change", OPERATIONS)) == GW_B
        # A domain with no target is advisory, exactly as an unregistered connector.
        assert (
            plane.connector_for("gateway_mode_change", "commercial:x:catalog:domain:none") is None
        )


def test_the_switch_off_ignores_stored_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NS_WRITE_TARGETS_FROM_STORE", raising=False)
    planes = _compose(_snapshot(_entry(ARM_A, "a")))
    with planes.composed.client():
        plane = _plane(planes)
        assert plane.write_targets.names() == ()
        assert plane.connector_for("gateway_mode_change", FINANCE) is None


def test_the_switch_on_without_entries_keeps_the_env_path(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING)
    monkeypatch.setenv("NS_WRITE_TARGETS_FROM_STORE", "true")
    planes = _compose(_snapshot())
    with planes.composed.client():
        assert _plane(planes).write_targets.names() == ()
    assert any("write_targets_store_empty" in r.getMessage() for r in caplog.records)


def test_an_unregistered_stored_gateway_is_skipped_the_other_registers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NS_WRITE_TARGETS_FROM_STORE", "true")
    missing = ARM_A.replace("apim-a", "apim-missing")
    planes = _compose(_snapshot(_entry(missing, "m"), _entry(ARM_B, "b")))
    with planes.composed.client():
        plane = _plane(planes)
        assert plane.write_targets.target_keys("apim-gateway") == (OPERATIONS,)
        assert plane.connector_for("gateway_mode_change", FINANCE) is None
