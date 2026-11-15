"""Harness for the connector admin API tests (PRP-42).

Composes the REAL authz builder, a stub data builder (in-memory audit) and the REAL
``admin_connectors`` builder over an in-memory ``admin_config`` store. Principals:

* ``CUSTOMER_ADMIN``: ``admin`` on FINANCE and the customer-control domain (customer-level
  ``config.manage``).
* ``DOMAIN_ADMIN``: ``admin`` on FINANCE only (config.manage in a domain, not customer-wide).
* ``ANALYST``: analyst in FINANCE (no ``config.manage``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from authz.authz_helpers import (  # pyright: ignore[reportMissingImports]
    CUSTOMER,
    FINANCE,
    POLICY_VERSION,
    FakeClock,
    make_validator,
    role,
)
from neurosphere_api.runtime import CompositionOverrides
from neurosphere_api.runtime.builders import AUDIT_REPOSITORY, BuildContext, BuilderSpec
from neurosphere_api.runtime.builders import admin_connectors as builder
from neurosphere_api.runtime.builders import authz as authz_builder
from neurosphere_core.admin import InMemoryAdminConfigRepository
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

__all__ = [
    "ANALYST",
    "BASE",
    "CUSTOMER",
    "CUSTOMER_ADMIN",
    "DOMAIN",
    "DOMAIN_ADMIN",
    "VAULT_URI",
    "ConnectorsWorld",
    "configure_env",
    "gateway_body",
]

CUSTOMER_ADMIN = "2b3c4d5e-6f7a-4b8c-9d0e-1f2a3b4c5d6e"
DOMAIN_ADMIN = "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"
ANALYST = "3c4d5e6f-7a8b-4c9d-8e1f-2a3b4c5d6e7f"
BASE = "/api/v1/admin/sources/connectors"
DOMAIN = "commercial:contoso:neurosphere:domain:finance"
CONTROL = customer_control_domain_id("commercial", CUSTOMER)
VAULT_URI = "https://ns-kv.vault.azure.net/secrets/producer-key"


def configure_env(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime_helpers.configure_auth_env(monkeypatch)


def pid(object_id: str) -> str:
    return str(runtime_helpers.composed_principal_id(object_id))


def gateway_body(**over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "schema_version": "1.0.0",
        "connector_id": "gateway-main",
        "connector_kind": "gateway_poll",
        "domain_ids": [DOMAIN],
        "settings": {"api_base_url": "https://api.example.test", "interval_seconds": 600},
        "credential": {"kind": "key_vault_secret", "secret_uri": VAULT_URI},
        "enabled": True,
    }
    body.update(over)
    return body


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
    repo.put_principal(_doc(CUSTOMER_ADMIN, (FINANCE, CONTROL), FINANCE, CONTROL, who=Role.ADMIN))
    repo.put_principal(_doc(DOMAIN_ADMIN, (FINANCE,), FINANCE, who=Role.ADMIN))
    repo.put_principal(_doc(ANALYST, (FINANCE,), FINANCE, who=Role.ANALYST))
    return repo


@dataclass
class ConnectorsWorld:
    composed: Composed
    repository: InMemoryAdminConfigRepository
    audit_store: InMemoryAuditStore

    def auth(self, object_id: str) -> dict[str, str]:
        return self.composed.auth(object_id)

    def records(self) -> list[dict[str, Any]]:
        chains = {chain for (chain, _doc) in self.audit_store._docs}  # pyright: ignore[reportPrivateUsage]
        out: list[dict[str, Any]] = []
        for chain in sorted(chains):
            out.extend(sorted(self.audit_store.raw_documents(chain), key=lambda d: d["sequence"]))
        return out

    @classmethod
    def build(cls, **backends: object) -> ConnectorsWorld:
        clock = FakeClock()
        repository = InMemoryAdminConfigRepository(cloud="commercial")
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
            backends={"admin_config_repository": repository, **backends},
        )
        chain = (
            authz_builder.BUILDER,
            BuilderSpec("stub-data", ("audit",), build_data),
            builder.BUILDER,
        )
        composed = compose(overrides, builders=chain, clock=clock)
        return cls(composed, repository, store)
