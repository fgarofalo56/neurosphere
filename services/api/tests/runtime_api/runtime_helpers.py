"""Test-only composition helpers: stub builders, fake Cosmos client, configured overrides.

The token validator here trusts the PRP-06 test issuer (``authz_helpers``) and is handed to
``compose_app`` ONLY through ``CompositionOverrides``; production code never sees it.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

import pytest
from authz.authz_helpers import (  # pyright: ignore[reportMissingImports]
    AUDIENCE,
    CUSTOMER,
    FINANCE,
    OPERATIONS,
    POLICY_VERSION,
    TENANT,
    FakeClock,
    dev_issuer,
    make_validator,
    role,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient
from neurosphere_api.app import create_app
from neurosphere_api.runtime import ComponentRegistry, CompositionOverrides, compose_app
from neurosphere_api.runtime.builders import BuildContext, BuilderSpec, default_builders
from neurosphere_api.runtime.builders import authz as authz_builder
from neurosphere_api.runtime.pseudonym import local_dev_pseudonym_key
from neurosphere_core.auth.revocation import InMemoryRevocationStore
from neurosphere_core.auth.scope import (
    InMemoryPolicyRepository,
    PolicyHead,
    PrincipalPolicy,
    PrincipalPseudonymizer,
    Role,
    principal_document_id,
)
from neurosphere_core.cloud import CloudName, Settings

__all__ = [
    "ALICE",
    "AUDIENCE",
    "CUSTOMER",
    "FINANCE",
    "TENANT",
    "Composed",
    "FakeCosmosClient",
    "authz_only",
    "builders_with_stubs",
    "compose",
    "composed_principal_id",
    "configure_auth_env",
    "configured_overrides",
    "stub_builder",
]

ALICE = "6c1d2e3f-4a5b-4c6d-8e7f-90a1b2c3d4e5"


def configure_auth_env(monkeypatch: pytest.MonkeyPatch, **values: str) -> None:
    """The ``NS_AUTH_*`` settings of the PRP-06 test tenant (overridable per test)."""
    env = {"TENANT_ID": TENANT, "AUDIENCES": AUDIENCE, "CUSTOMER_ID": CUSTOMER, **values}
    for name, value in env.items():
        monkeypatch.setenv(f"NS_AUTH_{name}", value)


def stub_builder(name: str, components: Iterable[str]) -> BuilderSpec:
    """Reports ``ok`` for components whose real builder is a placeholder (tests only)."""
    owned = tuple(components)

    def build(ctx: BuildContext) -> None:
        for component in owned:
            ctx.ok(component)

    return BuilderSpec(name, owned, build)


def builders_with_stubs() -> tuple[BuilderSpec, ...]:
    """The default order with every placeholder REQUIRED component stubbed ``ok``."""
    out: list[BuilderSpec] = []
    for spec in default_builders():
        if spec.name in ("data", "planes"):
            out.append(stub_builder(f"stub-{spec.name}", spec.components))
        else:
            out.append(spec)
    return tuple(out)


def composed_principal_id(object_id: str) -> str:
    """Principal id under the composed (local dev) pseudonym key."""
    return PrincipalPseudonymizer(local_dev_pseudonym_key()).principal_id(
        cloud=CloudName.COMMERCIAL,
        customer_id=CUSTOMER,
        tenant_id=TENANT,
        object_id=object_id,
        kind="user",
    )


def analyst_policy(object_id: str) -> PrincipalPolicy:
    pid = composed_principal_id(object_id)
    return PrincipalPolicy(
        id=principal_document_id(pid),
        customer_id=CUSTOMER,
        principal_id=pid,
        domain_memberships=(FINANCE, OPERATIONS),
        role_assignments=(role(Role.ANALYST, FINANCE),),
    )


@dataclass
class Composed:
    app: FastAPI
    registry: ComponentRegistry
    clock: FakeClock

    def client(self) -> TestClient:
        return TestClient(self.app, raise_server_exceptions=False)

    def auth(self, object_id: str = ALICE) -> dict[str, str]:
        token = dev_issuer().mint(audience=AUDIENCE, object_id=object_id, now=self.clock.now)
        return {"Authorization": f"Bearer {token}"}


def configured_overrides(clock: FakeClock, **extra: Any) -> CompositionOverrides:
    """Test issuer validator, in-memory policy (ALICE = finance analyst) and revocation store."""
    repo = InMemoryPolicyRepository()
    repo.put_head(PolicyHead(customer_id=CUSTOMER, policy_version=POLICY_VERSION))
    repo.put_principal(analyst_policy(ALICE))
    values: dict[str, Any] = {
        "authenticator": make_validator(clock),
        "policy_repository": repo,
        "revocation_store": InMemoryRevocationStore(),
        "clock": clock,
        **extra,
    }
    return CompositionOverrides(**values)


def compose(
    overrides: CompositionOverrides | None = None,
    *,
    builders: Iterable[BuilderSpec] | None = None,
    clock: FakeClock | None = None,
    settings: Settings | None = None,
) -> Composed:
    """A bare ``create_app`` composed with no environment probes (CI has no emulators)."""
    clock = clock or FakeClock()
    settings = settings or Settings()
    app = create_app(settings)
    registry = compose_app(
        app,
        settings,
        overrides,
        builders=None if builders is None else tuple(builders),
        env_probes=(),
    )
    return Composed(app=app, registry=registry, clock=clock)


@dataclass
class FakeDatabase:
    id: str
    containers: dict[str, dict[str, Any]] = field(default_factory=dict)
    missing: set[str] = field(default_factory=set)

    async def create_container_if_not_exists(self, id: str, partition_key: Any, **kw: Any) -> Any:
        self.containers[id] = {"partition_key": partition_key, **kw}
        return self

    def get_container_client(self, name: str) -> FakeContainer:
        return FakeContainer(name, self)


@dataclass
class FakeContainer:
    name: str
    database: FakeDatabase

    async def read(self) -> dict[str, Any]:
        from azure.cosmos.exceptions import CosmosResourceNotFoundError

        if self.name in self.database.missing or self.name not in self.database.containers:
            raise CosmosResourceNotFoundError(message="not found")
        return {"id": self.name}


@dataclass
class FakeCosmosClient:
    """The Cosmos client slice composition uses; records every call. Never touches a network."""

    databases: dict[str, FakeDatabase] = field(default_factory=dict)
    created_databases: list[str] = field(default_factory=list)
    closed: bool = False

    async def create_database_if_not_exists(self, id: str, **kw: Any) -> FakeDatabase:
        self.created_databases.append(id)
        return self.databases.setdefault(id, FakeDatabase(id))

    def get_database_client(self, name: str) -> FakeDatabase:
        return self.databases.setdefault(name, FakeDatabase(name))

    async def close(self) -> None:
        self.closed = True


def authz_only() -> tuple[BuilderSpec, ...]:
    return (authz_builder.BUILDER,)
