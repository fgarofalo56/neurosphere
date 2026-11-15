"""PRP-39 item 2: the admin builder composes the policy write repository and RevocationService."""

from __future__ import annotations

import pytest
from identity_harness import IdentityWorld, configure_env  # pyright: ignore[reportMissingImports]
from neurosphere_api.admin.identity import IdentityAdminPlane
from neurosphere_api.runtime import CompositionOverrides
from neurosphere_api.runtime.builders import (
    REVOCATION_HOOKS,
    BuildContext,
    BuilderSpec,
    default_builders,
)
from neurosphere_api.runtime.builders import admin as admin_builder
from neurosphere_api.runtime.status import OPTIONAL_COMPONENTS
from neurosphere_core.auth.revocation import RevocationHookRegistry, RevocationService
from neurosphere_core.auth.scope.policy_admin import InMemoryPolicyAdminRepository
from runtime_api.runtime_helpers import FakeCosmosClient, compose  # pyright: ignore[reportMissingImports]


@pytest.fixture(autouse=True)
def _auth(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_env(monkeypatch)


def test_admin_builder_runs_after_authz_data_and_realtime_and_is_optional() -> None:
    names = [spec.name for spec in default_builders()]
    # After every builder that publishes or extends REVOCATION_HOOKS / AUDIT_REPOSITORY.
    assert names.index("admin") == len(names) - 2
    assert names.index("authz") < names.index("data") < names.index("planes")
    assert names.index("planes") < names.index("lifecycle") < names.index("admin")
    assert {"policy_admin", "revocation_service"} <= set(OPTIONAL_COMPONENTS)


def test_with_authz_configured_both_components_are_ok() -> None:
    captured: list[RevocationHookRegistry] = []

    def capture(ctx: BuildContext) -> None:
        captured.append(ctx.shared(REVOCATION_HOOKS))

    world = IdentityWorld.build(extra_builders=(BuilderSpec("capture", (), capture),))
    registry = world.composed.registry
    assert registry.get("policy_admin").state == "ok"
    assert registry.get("revocation_service").state == "ok"
    plane = world.composed.app.state.identity_admin
    assert isinstance(plane, IdentityAdminPlane)
    assert isinstance(plane.revocation, RevocationService)
    # The service fans out through THE published registry (push closers included), not a copy.
    assert plane.revocation.hooks is captured[0]
    assert isinstance(plane.policy_admin, InMemoryPolicyAdminRepository)
    # Writes land in the reader derivation uses.
    assert plane.policy_admin.reader is world.policies


def test_with_authz_disabled_both_components_are_disabled_and_routes_fail_closed() -> None:
    composed = compose(CompositionOverrides(backends={}), builders=(admin_builder.BUILDER,))
    assert composed.registry.get("policy_admin").state == "disabled"
    assert composed.registry.get("revocation_service").state == "disabled"
    plane = composed.app.state.identity_admin
    assert plane.policy_admin is None and plane.revocation is None


def test_cosmos_policy_admin_repository_is_built_on_the_shared_client() -> None:
    cosmos = FakeCosmosClient()
    world = IdentityWorld.build()
    # Without an in-memory reader override the builder uses the Cosmos repository.
    from neurosphere_api.runtime.builders import authz as authz_builder
    from neurosphere_core.auth.revocation import InMemoryRevocationStore

    overrides = CompositionOverrides(
        authenticator=world.composed.app.state.authz.authenticator,
        revocation_store=InMemoryRevocationStore(),
        cosmos_client_factory=lambda: cosmos,
        clock=world.clock,
    )
    composed = compose(
        overrides, builders=(authz_builder.BUILDER, admin_builder.BUILDER), clock=world.clock
    )
    assert composed.registry.get("policy_admin").state == "ok"
    plane = composed.app.state.identity_admin
    assert type(plane.policy_admin).__name__ == "CosmosPolicyAdminRepository"
    assert cosmos.created_databases == []


def test_invalid_policy_admin_override_is_a_named_failure() -> None:
    world = IdentityWorld.build(policy_admin_repository=object())
    status = world.composed.registry.get("policy_admin")
    assert status.state == "failed"
    assert status.code == "policy_admin_override_invalid"
    assert world.composed.registry.get("revocation_service").state == "ok"


def test_invalid_revocation_settings_fail_only_the_service(monkeypatch: pytest.MonkeyPatch) -> None:
    world = IdentityWorld.build()
    assert world.composed.registry.get("revocation_service").state == "ok"
    monkeypatch.setenv("NS_REVOCATION_TTL_SECONDS", "0")
    # authz's own checker also reads the settings; reuse its published store and hooks.
    store = world.revocations
    hooks = RevocationHookRegistry()

    def publish(ctx: BuildContext) -> None:
        from neurosphere_api.runtime.builders import POLICY_REPOSITORY, REVOCATION_STORE

        ctx.publish(POLICY_REPOSITORY, world.policies)
        ctx.publish(REVOCATION_STORE, store)
        ctx.publish(REVOCATION_HOOKS, hooks)

    composed = compose(
        CompositionOverrides(policy_repository=world.policies),
        builders=(BuilderSpec("publish", (), publish), admin_builder.BUILDER),
    )
    assert composed.registry.get("revocation_service").code == "revocation_settings_invalid"
    assert composed.registry.get("policy_admin").state == "ok"
