"""PRP-42 item 4: the admin_connectors builder composes the plane or reports disabled."""

from __future__ import annotations

import pytest
from connectors_harness import ConnectorsWorld, configure_env  # pyright: ignore[reportMissingImports]
from neurosphere_api.admin.sources.connectors import ConnectorAdminPlane
from neurosphere_api.runtime import CompositionOverrides
from neurosphere_api.runtime.builders import BuilderSpec, default_builders
from neurosphere_api.runtime.builders import admin_connectors as builder
from neurosphere_api.runtime.status import OPTIONAL_COMPONENTS
from runtime_api.runtime_helpers import FakeCosmosClient, compose  # pyright: ignore[reportMissingImports]


@pytest.fixture(autouse=True)
def _auth(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_env(monkeypatch)


def test_builder_is_registered_and_optional() -> None:
    assert "admin_connectors" in [spec.name for spec in default_builders()]
    assert "admin_connectors" in OPTIONAL_COMPONENTS


def test_with_an_override_repository_the_component_is_ok_and_the_plane_installed() -> None:
    world = ConnectorsWorld.build()
    assert world.composed.registry.get("admin_connectors").state == "ok"
    plane = world.composed.app.state.admin_connectors
    assert isinstance(plane, ConnectorAdminPlane)


def test_cosmos_repository_is_built_on_the_shared_client() -> None:
    cosmos = FakeCosmosClient()
    world = ConnectorsWorld.build()
    overrides = CompositionOverrides(
        authenticator=world.composed.app.state.authz.authenticator,
        cosmos_client_factory=lambda: cosmos,
        clock=world.composed.clock,
    )
    from neurosphere_api.runtime.builders import AUDIT_REPOSITORY, BuildContext
    from neurosphere_core.audit import AuditRepository, InMemoryAuditStore

    audit = AuditRepository(InMemoryAuditStore())

    def build_data(ctx: BuildContext) -> None:
        ctx.publish(AUDIT_REPOSITORY, audit)
        ctx.ok("audit")

    composed = compose(
        overrides,
        builders=(BuilderSpec("stub-data", ("audit",), build_data), builder.BUILDER),
        clock=world.composed.clock,
    )
    assert composed.registry.get("admin_connectors").state == "ok"


def test_without_cosmos_the_component_is_disabled_and_routes_answer_503() -> None:
    world = ConnectorsWorld.build()
    overrides = CompositionOverrides(
        authenticator=world.composed.app.state.authz.authenticator, clock=world.composed.clock
    )
    from neurosphere_api.runtime.builders import AUDIT_REPOSITORY, BuildContext
    from neurosphere_core.audit import AuditRepository, InMemoryAuditStore

    audit = AuditRepository(InMemoryAuditStore())

    def build_data(ctx: BuildContext) -> None:
        ctx.publish(AUDIT_REPOSITORY, audit)
        ctx.ok("audit")

    composed = compose(
        overrides,
        builders=(BuilderSpec("stub-data", ("audit",), build_data), builder.BUILDER),
        clock=world.composed.clock,
    )
    assert composed.registry.get("admin_connectors").state == "disabled"
    assert composed.app.state.admin_connectors is None


def test_without_cosmos_or_backend_the_component_is_disabled() -> None:
    composed = compose(CompositionOverrides(backends={}), builders=(builder.BUILDER,))
    assert composed.registry.get("admin_connectors").state == "disabled"
