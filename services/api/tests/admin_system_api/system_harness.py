"""Harness for the system admin API tests (PRP-45).

Composes the REAL authz builder, a stub data builder (in-memory audit), any extra builders a test
names and the REAL ``admin_system`` builder over an in-memory ``admin_config`` store. Principals:

* ``DEPLOYMENT_ADMIN``: ``admin`` on FINANCE and the customer-control domain.
* ``DOMAIN_ADMIN``: ``admin`` (so ``config.manage``) on FINANCE only.
* ``ANALYST``: analyst in FINANCE.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import pytest
from authz.authz_helpers import (  # pyright: ignore[reportMissingImports]
    CUSTOMER,
    POLICY_VERSION,
    FakeClock,
    make_validator,
    role,
)
from neurosphere_api.runtime import CompositionOverrides
from neurosphere_api.runtime.builders import AUDIT_REPOSITORY, BuildContext, BuilderSpec
from neurosphere_api.runtime.builders import admin_system as builder
from neurosphere_api.runtime.builders import authz as authz_builder
from neurosphere_core.admin import InMemoryAdminConfigRepository
from neurosphere_core.admin.runtime import SYSTEM_SETTING_KIND, document_id
from neurosphere_core.audit import AuditRepository, InMemoryAuditStore
from neurosphere_core.auth.revocation import InMemoryRevocationStore
from neurosphere_core.auth.scope import (
    InMemoryPolicyRepository,
    PolicyHead,
    PrincipalPolicy,
    Role,
    customer_control_domain_id,
    principal_document_id,
)
from runtime_api import runtime_helpers  # pyright: ignore[reportMissingImports]
from runtime_api.runtime_helpers import (  # pyright: ignore[reportMissingImports]
    Composed,
    compose,
)

DEPLOYMENT_ADMIN = "2b3c4d5e-6f7a-4b8c-9d0e-1f2a3b4c5d6e"
DOMAIN_ADMIN = "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"
ANALYST = "3c4d5e6f-7a8b-4c9d-8e1f-2a3b4c5d6e7f"
BASE = "/api/v1/admin/system"
FINANCE = "commercial:contoso:neurosphere:domain:finance"
CONTROL = customer_control_domain_id("commercial", CUSTOMER)
ACTOR = "commercial:contoso:entra:person:p-" + "0c" * 32
MI = {
    "kind": "managed_identity",
    "managed_identity_client_id": "0b5d0c6e-1f2a-4b3c-8d4e-5f6a7b8c9d0e",
}
RESOURCE = (
    "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-ns"
    "/providers/Microsoft.CognitiveServices/accounts/acct"
)


def configure_env(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime_helpers.configure_auth_env(monkeypatch)


def pid(object_id: str) -> str:
    return str(runtime_helpers.composed_principal_id(object_id))


def model_body(
    key: str = "copilot", endpoint: str = "https://acct.openai.azure.com", **over: Any
) -> dict[str, Any]:
    member: dict[str, Any] = {
        "endpoint": endpoint,
        "deployment": "gpt-4o",
        "api_version": "2024-10-21",
        "resource_id": RESOURCE,
        "credential": MI,
    }
    member.update(over)
    return {"schema_version": "1.0.0", "setting_key": key, "enabled": True, key: member}


def search_body(endpoint: str = "https://ns-search.search.windows.net") -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "setting_key": "search",
        "enabled": True,
        "search": {
            "endpoint": endpoint,
            "index_name": "stored-index",
            "resource_id": None,
            "credential": MI,
        },
    }


def scan_body(enabled: bool = True) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "setting_key": "scan",
        "enabled": enabled,
        "scan": {
            "interval_seconds": 3600,
            "scopes": ["/subscriptions/00000000-0000-0000-0000-000000000001"],
            "credential": MI,
        },
    }


def mcp_body(endpoint: str = "https://ns.example.com/mcp", enabled: bool = True) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "setting_key": "mcp_server",
        "enabled": enabled,
        "mcp_server": {"endpoint": endpoint, "resource_id": None, "credential": None},
    }


def write_target_body(kind: str = "foundry") -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "setting_key": "write_target",
        "enabled": True,
        "write_target": {"target_kind": kind, "resource_id": RESOURCE, "credential": MI},
    }


def _doc(object_id: str, memberships: tuple[str, ...], *domains: str, who: Role) -> PrincipalPolicy:
    principal = pid(object_id)
    return PrincipalPolicy(
        id=principal_document_id(principal),
        customer_id=CUSTOMER,
        principal_id=principal,
        domain_memberships=memberships,
        role_assignments=(role(who, *domains),),
    )


def seeded_policies() -> InMemoryPolicyRepository:
    repo = InMemoryPolicyRepository()
    repo.put_head(PolicyHead(customer_id=CUSTOMER, policy_version=POLICY_VERSION))
    both = (FINANCE, CONTROL)
    repo.put_principal(_doc(DEPLOYMENT_ADMIN, both, *both, who=Role.ADMIN))
    repo.put_principal(_doc(DOMAIN_ADMIN, (FINANCE,), FINANCE, who=Role.ADMIN))
    repo.put_principal(_doc(ANALYST, (FINANCE,), FINANCE, who=Role.ANALYST))
    return repo


def seed(repository: InMemoryAdminConfigRepository, key: str, body: dict[str, Any]) -> Any:
    """Store ``body`` directly (what a previous PUT left behind before this start)."""
    kind = body["write_target"]["target_kind"] if key == "write_targets" else None
    doc_id = document_id(key, kind)  # type: ignore[arg-type]
    return asyncio.run(
        repository.create(CUSTOMER, SYSTEM_SETTING_KIND, doc_id, body, updated_by=ACTOR)
    )


@dataclass
class SystemWorld:
    composed: Composed
    repository: InMemoryAdminConfigRepository
    audit_store: InMemoryAuditStore

    def auth(self, object_id: str = DEPLOYMENT_ADMIN) -> dict[str, str]:
        return self.composed.auth(object_id)

    def get(self, path: str, who: str = DEPLOYMENT_ADMIN) -> Any:
        return self.composed.client().get(f"{BASE}{path}", headers=self.auth(who))

    def put(self, key: str, body: Any, if_match: str | None, who: str = DEPLOYMENT_ADMIN) -> Any:
        headers = self.auth(who)
        if if_match is not None:
            headers["If-Match"] = if_match
        return self.composed.client().put(f"{BASE}/settings/{key}", json=body, headers=headers)

    def records(self) -> list[dict[str, Any]]:
        chains = {chain for (chain, _doc) in self.audit_store._docs}  # pyright: ignore[reportPrivateUsage]
        out: list[dict[str, Any]] = []
        for chain in sorted(chains):
            out.extend(sorted(self.audit_store.raw_documents(chain), key=lambda d: d["sequence"]))
        return out

    @classmethod
    def build(
        cls,
        *,
        repository: InMemoryAdminConfigRepository | None = None,
        extra: Sequence[BuilderSpec] = (),
        **backends: object,
    ) -> SystemWorld:
        clock = FakeClock()
        repo = repository or InMemoryAdminConfigRepository(cloud="commercial")
        store = InMemoryAuditStore()
        audit = AuditRepository(store)

        def build_data(ctx: BuildContext) -> None:
            ctx.publish(AUDIT_REPOSITORY, audit)
            ctx.ok("audit")

        overrides = CompositionOverrides(
            authenticator=make_validator(clock),
            policy_repository=seeded_policies(),
            revocation_store=InMemoryRevocationStore(clock=clock),
            clock=clock,
            backends={"admin_config_repository": repo, **backends},
        )
        chain = (
            authz_builder.BUILDER,
            BuilderSpec("stub-data", ("audit",), build_data),
            *extra,
            builder.BUILDER,
        )
        composed = compose(overrides, builders=chain, clock=clock)
        return cls(composed, repo, store)
