"""The gateway builder: the plane is installed by the composition root, fails alone."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from authz.authz_helpers import (  # pyright: ignore[reportMissingImports]
    CUSTOMER,
    FINANCE,
    POLICY_VERSION,
    FakeClock,
    make_validator,
    role,
)
from gateway_harness import RID, FakeArm, fake_arm  # pyright: ignore[reportMissingImports]
from neurosphere_api.gateway import GatewayPlane, GatewaySettings
from neurosphere_api.runtime import CompositionOverrides
from neurosphere_api.runtime.builders import (
    AUDIT_REPOSITORY,
    BuildContext,
    BuilderSpec,
    default_builders,
)
from neurosphere_api.runtime.builders import authz as authz_builder
from neurosphere_api.runtime.builders import gateway as gateway_builder
from neurosphere_core.audit import AuditRepository, InMemoryAuditStore
from neurosphere_core.auth.revocation import InMemoryRevocationStore
from neurosphere_core.auth.scope import (
    InMemoryPolicyRepository,
    PolicyHead,
    PrincipalPolicy,
    Role,
    principal_document_id,
)
from neurosphere_core.clients import arm_client
from neurosphere_core.cloud import CloudName, CloudProfile
from neurosphere_core.gateway import InMemoryGatewayStore
from runtime_api import runtime_helpers  # pyright: ignore[reportMissingImports]
from runtime_api.runtime_helpers import (  # pyright: ignore[reportMissingImports]
    Composed,
    FakeCosmosClient,
    compose,
)

ADMIN = "9f4a5b6c-7d8e-4f90-a1b2-c3d4e5f6a7b8"


@pytest.fixture(autouse=True)
def _auth(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime_helpers.configure_auth_env(monkeypatch)


def _stub_data() -> BuilderSpec:
    audit = AuditRepository(InMemoryAuditStore())

    def build(ctx: BuildContext) -> None:
        ctx.publish(AUDIT_REPOSITORY, audit)
        ctx.ok("audit")

    return BuilderSpec("stub-data", ("audit",), build)


def _policies() -> InMemoryPolicyRepository:
    repo = InMemoryPolicyRepository()
    repo.put_head(PolicyHead(customer_id=CUSTOMER, policy_version=POLICY_VERSION))
    pid = str(runtime_helpers.composed_principal_id(ADMIN))
    repo.put_principal(
        PrincipalPolicy(
            id=principal_document_id(pid),
            customer_id=CUSTOMER,
            principal_id=pid,
            domain_memberships=(FINANCE,),
            role_assignments=(role(Role.ADMIN, FINANCE),),
        )
    )
    return repo


def _compose(**backends: object) -> Composed:
    clock = FakeClock()
    fake = FakeArm()

    def factory(profile: CloudProfile) -> httpx.AsyncClient:
        return arm_client(profile, fake_arm.FakeCredential(), transport=fake.transport())

    cosmos = backends.pop("cosmos", None)
    resolved: dict[str, object] = {"gateway_arm_factory": factory, **backends}
    overrides = CompositionOverrides(
        authenticator=make_validator(clock),
        policy_repository=_policies(),
        revocation_store=InMemoryRevocationStore(),
        clock=clock,
        backends=resolved,
        cosmos_client_factory=cosmos,  # type: ignore[arg-type]
    )
    chain = (authz_builder.BUILDER, _stub_data(), gateway_builder.BUILDER)
    return compose(overrides, builders=chain, clock=clock)


def test_builder_is_registered_before_edge_and_after_mcp() -> None:
    names = [spec.name for spec in default_builders()]
    assert "gateway" in names
    assert names.index("mcp") < names.index("gateway") < names.index("edge")


def test_plane_is_installed_and_ok_with_the_memory_store(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_GATEWAY_STORE", "memory")
    composed = _compose()
    assert composed.registry.get("gateway_plane").state == "ok"
    assert isinstance(composed.app.state.gateway_plane, GatewayPlane)
    assert isinstance(composed.app.state.gateway_plane.store, InMemoryGatewayStore)


def test_routes_answer_through_the_composed_app(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_GATEWAY_STORE", "memory")
    composed = _compose()
    base = f"/api/v1/gateways/domains/{FINANCE}/gateways"
    with composed.client() as client:
        created = client.post(base, json={"arm_resource_id": RID}, headers=composed.auth(ADMIN))
        assert created.status_code == 201, created.text
        listed = client.get(base, headers=composed.auth(ADMIN))
        assert listed.status_code == 200, listed.text
        assert [g["id"] for g in listed.json()["items"]] == [created.json()["id"]]


def test_default_store_is_cosmos_on_the_shared_client() -> None:
    cosmos = FakeCosmosClient()
    composed = _compose(cosmos=lambda: cosmos)
    assert composed.registry.get("gateway_plane").state == "ok"
    plane = composed.app.state.gateway_plane
    assert type(plane.store).__name__ == "CosmosGatewayStore"
    assert cosmos.created_databases == []  # the builder opens no second client or database


def test_local_startup_creates_the_container_from_the_registry() -> None:
    from neurosphere_core.stores import container_spec

    spec = container_spec("gateways")
    assert spec.partition_key_paths == ("/customer_id", "/domain_id")
    assert spec.default_ttl is None


def test_store_kind_resolution() -> None:
    from neurosphere_api.gateway.settings import resolve_store_kind
    from neurosphere_core.cloud import Settings
    from neurosphere_core.errors import InvalidSchemaError

    local = Settings()
    assert resolve_store_kind(local, GatewaySettings()) == "cosmos"
    assert resolve_store_kind(local, GatewaySettings(store="cosmos")) == "cosmos"
    assert resolve_store_kind(local, GatewaySettings(store="memory")) == "memory"
    hosted = Settings(env="dev", cloud=CloudName.COMMERCIAL)
    assert resolve_store_kind(hosted, GatewaySettings()) == "cosmos"
    with pytest.raises(InvalidSchemaError):
        resolve_store_kind(hosted, GatewaySettings(store="memory"))


def test_cosmos_failure_is_a_named_reason_and_does_not_break_others() -> None:
    class Broken:
        def get_database_client(self, name: str) -> Any:
            raise RuntimeError("boom")

        async def close(self) -> None:
            return None

    composed = _compose(cosmos=lambda: Broken())
    status = composed.registry.get("gateway_plane")
    assert status.state == "failed"
    assert status.code == "gateway_build_error"
    assert composed.registry.get("authz").state == "ok"
    assert composed.registry.get("audit").state == "ok"
    with composed.client() as client:
        denied = client.get(
            f"/api/v1/gateways/domains/{FINANCE}/gateways", headers=composed.auth(ADMIN)
        )
    assert denied.status_code == 503
    assert denied.json()["reason"] == "gateway_plane_unconfigured"


def test_missing_audit_repository_is_reported_by_reason() -> None:
    composed = compose(
        CompositionOverrides(backends={}),
        builders=(gateway_builder.BUILDER,),
    )
    assert composed.registry.get("gateway_plane").code == "audit_repository_unavailable"


def test_invalid_settings_fail_by_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_GATEWAY_STORE", "bogus")
    composed = _compose()
    assert composed.registry.get("gateway_plane").code == "gateway_settings_invalid"
