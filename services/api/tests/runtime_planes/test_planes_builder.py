"""The planes builder: action plane, HITL, reports and MCP admin composed from shared inputs."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from authz.authz_helpers import FakeClock, make_validator  # pyright: ignore[reportMissingImports]
from neurosphere_api.actions import get_action_plane
from neurosphere_api.app import create_app
from neurosphere_api.mcp.admin import McpAdminPlane
from neurosphere_api.reports.dependencies import get_report_service
from neurosphere_api.runtime import CompositionOverrides, compose_app
from neurosphere_api.runtime.builders.planes import (
    SUPPORTED_WRITE_CONNECTORS,
    PolicyReviewerDirectory,
)
from neurosphere_connector.write import WriteTargetRegistry
from neurosphere_core.actions import ActionService
from neurosphere_core.actions.cosmos_store import CosmosExecutionControl, CosmosIntentStore
from neurosphere_core.actions.recheck import PolicyPermissionRechecker
from neurosphere_core.auth.revocation import InMemoryRevocationStore
from neurosphere_core.cloud import Settings
from neurosphere_core.mcp import McpRegistry
from runtime_api.runtime_helpers import FakeCosmosClient  # pyright: ignore[reportMissingImports]
from starlette.requests import Request

from .planes_helpers import (
    ALICE,
    BOB,
    CAROL,
    CUSTOMER,
    FINANCE,
    DataFakes,
    builders,
    compose_planes,
    composed_principal_id,
    configure_auth_env,
    plane_backends,
    policy_repository,
    stub_data_builder,
)

PLANE_COMPONENTS = ("hitl", "action_plane", "reports", "mcp_admin")
INTENTS = f"/api/v1/actions/domains/{FINANCE}/intents"
TARGET = "commercial:contoso:foundry:agent:chat-prod"


def _request(app: Any) -> Request:
    return Request({"type": "http", "app": app, "headers": []})


def _pid(object_id: str) -> str:
    return composed_principal_id(object_id)


@pytest.fixture(autouse=True)
def _auth(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_auth_env(monkeypatch)


def test_every_plane_component_is_ok_with_fakes_and_the_app_is_ready() -> None:
    planes = compose_planes()
    for name in PLANE_COMPONENTS:
        assert planes.registry.get(name).state == "ok", planes.registry.get(name)
    with planes.composed.client() as client:
        response = client.get("/readyz")
    assert response.status_code == 200, response.json()
    deps = response.json()["dependencies"]
    assert deps["composition.copilot.disabled"] == "ok"
    assert deps["composition.mcp_server.disabled"] == "ok"


def test_the_plane_is_installed_from_the_shared_inputs() -> None:
    planes = compose_planes()
    plane = get_action_plane(_request(planes.app))
    assert plane.intents is planes.backends["intent_store"]
    assert plane.control is planes.backends["execution_control"]
    assert plane.hitl is planes.fakes.hitl
    assert plane.audit is planes.fakes.audit
    assert isinstance(plane.actions, ActionService)
    assert isinstance(plane.reviewer_directory, PolicyReviewerDirectory)


def test_the_rechecker_reads_the_policy_store_the_deriver_reads() -> None:
    planes = compose_planes()
    plane = get_action_plane(_request(planes.app))
    assert isinstance(plane.rechecker, PolicyPermissionRechecker)

    def check(who: str, permission: str) -> bool:
        return asyncio.run(plane.rechecker.check(_pid(who), CUSTOMER, FINANCE, permission))

    assert check(ALICE, "action.propose") is True
    assert check(CAROL, "action.propose") is False
    # A change in the shared policy store is seen at once (nothing is cached as an allow).
    current = asyncio.run(planes.repo.get_principal_policy(CUSTOMER, _pid(ALICE)))
    assert current is not None
    planes.repo.put_principal(current.model_copy(update={"role_assignments": ()}))
    assert check(ALICE, "action.propose") is False


def test_production_write_targets_hold_no_connector_so_every_intent_is_advisory() -> None:
    planes = compose_planes()
    plane = get_action_plane(_request(planes.app))
    assert isinstance(plane.write_targets, WriteTargetRegistry)
    assert plane.write_targets.names() == ()
    # No write connector for the model swap kind: advisory, never a metadata-only stand-in.
    assert plane.connector_for("model_deployment_swap") is None
    assert frozenset({"foundry-model-swap", "apim-gateway"}) == SUPPORTED_WRITE_CONNECTORS


class _ForeignTargets(WriteTargetRegistry):
    def names(self) -> tuple[str, ...]:
        return ("arbitrary-writer",)


def test_an_unsupported_write_target_is_refused() -> None:
    planes = compose_planes(backends=plane_backends(write_targets=_ForeignTargets()))
    assert planes.registry.get("action_plane").code == "write_target_unsupported"
    assert planes.registry.get("hitl").code == "write_target_unsupported"


def test_a_rest_draft_lands_in_the_composed_store_and_is_never_executed() -> None:
    planes = compose_planes()
    body = {
        "action_kind": "model_deployment_swap",
        "target": {"canonical_id": TARGET, "entity_type": "agent"},
        "target_version": "etag-1",
        "proposed_diff": {
            "format": "json_patch",
            "operations": [{"op": "replace", "path": "/model/version", "value": "2026-06-15"}],
        },
        "evidence": [],
        "idempotency_key": "idem-2026-10-25-planes-0001",
        "channel": "rest",
    }
    with planes.composed.client() as client:
        drafted = client.post(INTENTS, json=body, headers=planes.auth(ALICE))
        assert drafted.status_code == 201, drafted.text
        intent_id = drafted.json()["intent"]["intent_id"]
        viewer = client.get(f"{INTENTS}/{intent_id}", headers=planes.auth(CAROL))
    assert viewer.status_code == 200, viewer.text
    assert viewer.json()["intent"]["state"] == "drafted"
    assert viewer.json()["execution"] is None
    store: Any = planes.backends["intent_store"]
    stored = asyncio.run(store.get(CUSTOMER, FINANCE, intent_id))
    assert stored is not None
    assert stored.state == "drafted"


def test_review_routes_are_served_by_the_configured_plane() -> None:
    planes = compose_planes()
    with planes.composed.client() as client:
        response = client.get(f"/api/v1/review/domains/{FINANCE}/items", headers=planes.auth(BOB))
    assert response.status_code == 200, response.text
    assert response.json()["items"] == []


def test_without_the_hitl_service_the_plane_and_hitl_fail_by_name() -> None:
    planes = compose_planes(skip=("hitl",))
    assert planes.registry.get("action_plane").code == "hitl_service_unavailable"
    assert planes.registry.get("hitl").code == "hitl_service_unavailable"
    with planes.composed.client() as client:
        ready = client.get("/readyz")
        listing = client.get(INTENTS, headers=planes.auth(ALICE))
    assert ready.status_code == 503
    deps = ready.json()["dependencies"]
    assert deps["composition.hitl.hitl_service_unavailable"] == "unavailable"
    assert listing.status_code == 503
    assert listing.json()["reason"] == "action_plane_unconfigured"


def test_without_audit_the_audited_planes_fail() -> None:
    planes = compose_planes(skip=("audit",))
    assert planes.registry.get("action_plane").code == "audit_repository_unavailable"
    assert planes.registry.get("mcp_admin").code == "audit_repository_unavailable"
    assert planes.registry.get("reports").state == "ok"  # report runs write no audit


def test_without_the_catalog_reader_reports_fail_by_name() -> None:
    planes = compose_planes(skip=("catalog",))
    assert planes.registry.get("reports").code == "catalog_repository_unavailable"
    assert planes.registry.get("action_plane").state == "ok"


def test_without_cosmos_the_cosmos_backed_stores_fail_as_unconfigured() -> None:
    planes = compose_planes(backends={})
    for name in PLANE_COMPONENTS:
        assert planes.registry.get(name).code == "cosmos_unconfigured", name


def test_with_a_cosmos_client_the_cosmos_stores_are_built() -> None:
    clock = FakeClock()
    cosmos = FakeCosmosClient()
    settings = Settings()
    app = create_app(settings)
    registry = compose_app(
        app,
        settings,
        CompositionOverrides(
            authenticator=make_validator(clock),
            policy_repository=policy_repository(),
            revocation_store=InMemoryRevocationStore(),
            clock=clock,
            cosmos_client_factory=lambda: cosmos,
        ),
        builders=builders(stub_data_builder(DataFakes())),
        env_probes=(),
    )
    for name in PLANE_COMPONENTS:
        assert registry.get(name).state == "ok", registry.get(name)
    plane = get_action_plane(_request(app))
    assert isinstance(plane.intents, CosmosIntentStore)
    assert isinstance(plane.control, CosmosExecutionControl)
    admin = app.state.mcp_admin
    assert isinstance(admin, McpAdminPlane)
    assert isinstance(admin.registry, McpRegistry)
    get_report_service(_request(app))  # resolves: report store + bounded tool registry
    # Builders never create containers (the composition does, only for a settings-built client).
    assert cosmos.created_databases == []


def test_mcp_admin_requires_config_manage() -> None:
    planes = compose_planes()
    with planes.composed.client() as client:
        steward = client.get("/api/v1/mcp/admin/servers", headers=planes.auth(ALICE))
    assert steward.status_code == 403, steward.text


def test_reviewer_directory_resolves_known_principals_only() -> None:
    planes = compose_planes()
    directory = PolicyReviewerDirectory(planes.repo)
    actor = asyncio.run(directory.actor_for(CUSTOMER, _pid(BOB)))
    assert actor is not None
    assert actor.principal_kind == "user"
    assert actor.principal_pseudonym == _pid(BOB).rsplit(":", 1)[-1]
    unknown = _pid("aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee")
    assert asyncio.run(directory.actor_for(CUSTOMER, unknown)) is None
    assert asyncio.run(directory.actor_for("fabrikam", _pid(BOB))) is None
    assert asyncio.run(directory.actor_for(CUSTOMER, "not-a-canonical-id")) is None
