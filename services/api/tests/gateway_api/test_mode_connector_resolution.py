"""``ActionPlane.connector_for`` with the APIM gateway connector (PRP-34 item 2).

Target-kind routing (``model_deployment_swap`` stays on Foundry for Foundry targets, goes to the
APIM connector for an ``apim_backend``), the observe-mode refusal before any APIM plan, and the
planning view never executing.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

import pytest
from neurosphere_api.actions import ActionApiSettings
from neurosphere_api.actions.dependencies import ActionPlane
from neurosphere_connector import build_manifest
from neurosphere_connector.write import (
    DryRunResult,
    WriteConnector,
    WriteRequest,
    WriteTargetRegistry,
)
from neurosphere_contracts.actions.v1.action_intent import ProposedDiff
from neurosphere_contracts.actions.v1.target_ref import TargetRef
from neurosphere_contracts.connectors.v1.connector_manifest import ConnectorManifest, Granularity
from neurosphere_core.errors import CapabilityUnavailableError, DependencyTransientError
from neurosphere_core.gateway import GatewayRegistration, InMemoryGatewayStore
from neurosphere_core.gateway.mode import evaluate_permissions

T0 = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)
GW = "gw-" + "c" * 32
RID = (
    "/subscriptions/11111111-2222-4333-8444-555555555555/resourceGroups/rg"
    "/providers/Microsoft.ApiManagement/service/apim-demo"
)


class FakeConnector:
    def __init__(self, name: str, kinds: list[str], gateway_id: str | None = None) -> None:
        self.name = name
        self.kinds = kinds
        self.dry_runs: list[str] = []
        if gateway_id is not None:
            self.gateway = type("Ref", (), {"gateway_id": gateway_id})()

    @property
    def manifest(self) -> ConnectorManifest:
        return build_manifest(
            name=self.name,
            version="0.1.0",
            capabilities=["health_reporting"],
            supported_clouds=["commercial"],
            granularity=Granularity(time_grain="unknown", subject_level="deployment"),
            scopes=["https://management.azure.com/.default"],
            write_actions=self.kinds,  # type: ignore[arg-type]
        )

    @property
    def advisory(self) -> bool:
        return False

    async def dry_run(self, request: WriteRequest) -> DryRunResult:
        self.dry_runs.append(request.target.entity_type)
        return DryRunResult(
            target=request.target,
            target_version=request.target_version,
            planned_diff=request.proposed_diff,
            would_change=True,
        )

    async def apply(self, request: WriteRequest) -> Any:
        raise AssertionError("never")

    async def verify(self, request: WriteRequest) -> Any:
        raise AssertionError("never")

    async def rollback(self, applied: Any) -> Any:
        raise AssertionError("never")


def _plane(registry: WriteTargetRegistry, modes: InMemoryGatewayStore | None) -> ActionPlane:
    unused = cast(Any, object())
    return ActionPlane(
        actions=unused,
        intents=unused,
        hitl=unused,
        policies=unused,
        write_targets=registry,
        rechecker=unused,
        control=unused,
        audit=unused,
        settings=ActionApiSettings(),
        clock=lambda: T0,
        gateway_modes=modes,
    )


def _request(entity_type: str, canonical_id: str) -> WriteRequest:
    return WriteRequest(
        target=TargetRef(canonical_id=canonical_id, entity_type=entity_type),
        target_version="v1",
        proposed_diff=ProposedDiff.model_validate(
            {"format": "json_patch", "operations": [{"op": "replace", "path": "/x", "value": 1}]}
        ),
    )


async def _store(mode: str) -> InMemoryGatewayStore:
    store = InMemoryGatewayStore()
    data: dict[str, Any] = {
        "id": GW,
        "customer_id": "contoso",
        "domain_id": "commercial:contoso:catalog:domain:finance",
        "cloud": "commercial",
        "arm_resource_id": RID,
        "name": "apim-demo",
        "tier": "standard_v2",
        "created_at": T0,
        "updated_at": T0,
        "registered_by": "pn-admin",
    }
    if mode == "manage":
        data.update(
            mode="manage",
            mode_changed_by="pn-x",
            mode_changed_at=T0,
            mode_revision=1,
            preflight=evaluate_permissions(
                [{"actions": ["Microsoft.ApiManagement/service/*"]}], now=T0
            ),
        )
    await store.create(GatewayRegistration.model_validate(data))
    return store


FOUNDRY_TARGET = ("model_deployment", "commercial:contoso:foundry:model_deployment:eastus2/chat")
BACKEND_TARGET = ("apim_backend", "commercial:contoso:apim:apim_backend:foundry-pool")


def _registry() -> tuple[WriteTargetRegistry, FakeConnector, FakeConnector]:
    foundry = FakeConnector("foundry-model-swap", ["model_deployment_swap"])
    apim = FakeConnector(
        "apim-gateway", ["model_deployment_swap", "budget_cap_change", "gateway_mode_change"], GW
    )
    registry = WriteTargetRegistry()
    registry.register(foundry)
    registry.register(apim)
    return registry, foundry, apim


async def test_single_foundry_connector_is_returned_as_is() -> None:
    foundry = FakeConnector("foundry-model-swap", ["model_deployment_swap"])
    registry = WriteTargetRegistry()
    registry.register(foundry)
    plane = _plane(registry, None)
    assert plane.connector_for("model_deployment_swap") is foundry
    assert plane.connector_for("budget_cap_change") is None  # APIM kind, no APIM connector


async def test_model_swap_routes_by_target_kind_and_guards_apim_backends() -> None:
    registry, foundry, apim = _registry()
    plane = _plane(registry, await _store("observe"))
    view = plane.connector_for("model_deployment_swap")
    assert view is not None and isinstance(view, WriteConnector)
    assert view.advisory is False
    assert view.manifest.name == "foundry-model-swap"
    await view.dry_run(_request(*FOUNDRY_TARGET))
    assert foundry.dry_runs == ["model_deployment"]  # Foundry mapping unchanged, no mode check
    with pytest.raises(CapabilityUnavailableError) as info:
        await view.dry_run(_request(*BACKEND_TARGET))
    assert info.value.reason == "gateway_observe_mode"
    assert apim.dry_runs == []


async def test_manage_mode_lets_the_apim_plan_through() -> None:
    registry, _, apim = _registry()
    plane = _plane(registry, await _store("manage"))
    view = plane.connector_for("budget_cap_change")
    assert view is not None
    await view.dry_run(_request("grant", "commercial:contoso:apim:grant:g1"))
    assert apim.dry_runs == ["grant"]


async def test_mode_change_itself_is_not_blocked_by_observe_mode() -> None:
    registry, _, apim = _registry()
    plane = _plane(registry, await _store("observe"))
    view = plane.connector_for("gateway_mode_change")
    assert view is not None
    await view.dry_run(
        _request("apim_gateway_mode", f"commercial:contoso:apim:apim_gateway_mode:{GW}")
    )
    assert apim.dry_runs == ["apim_gateway_mode"]


async def test_missing_registry_and_unknown_customer_fail_closed() -> None:
    registry, _, apim = _registry()
    view = _plane(registry, None).connector_for("budget_cap_change")
    assert view is not None
    with pytest.raises(DependencyTransientError):
        await view.dry_run(_request("grant", "commercial:contoso:apim:grant:g1"))
    other = _plane(registry, await _store("manage")).connector_for("budget_cap_change")
    assert other is not None
    with pytest.raises(CapabilityUnavailableError) as info:
        await other.dry_run(_request("grant", "commercial:fabrikam:apim:grant:g1"))
    assert info.value.reason == "gateway_not_registered"
    assert apim.dry_runs == []


async def test_the_planning_view_never_executes() -> None:
    registry, _, _ = _registry()
    view = _plane(registry, await _store("manage")).connector_for("budget_cap_change")
    assert view is not None
    request = _request("grant", "commercial:contoso:apim:grant:g1")
    for call in (view.apply, view.verify):
        with pytest.raises(CapabilityUnavailableError) as info:
            await call(request)
        assert info.value.reason == "api_never_executes"
    with pytest.raises(CapabilityUnavailableError):
        await view.rollback(cast(Any, None))
