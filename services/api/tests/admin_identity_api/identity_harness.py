"""Shared harness for the identity admin API tests (PRP-39).

Composes the REAL authz builder, a stub data builder (in-memory audit) and the REAL admin
builder over in-memory policy and revocation stores, then drives the routes with dev-issuer
tokens. Principals (object ids are test fixtures, never in any response or log):

* ``DOMAIN_ADMIN``: time-bound ``admin`` on FINANCE only (manages FINANCE).
* ``CUSTOMER_ADMIN``: time-bound ``admin`` on FINANCE, OPERATIONS and the customer-control
  domain (customer-wide ``policy.manage``).
* ``TARGET``: analyst in FINANCE (member of FINANCE and OPERATIONS).
* ``HR_ONLY``: analyst in HR, which neither admin manages.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from authz.authz_helpers import (  # pyright: ignore[reportMissingImports]
    CUSTOMER,
    FINANCE,
    HR,
    OPERATIONS,
    POLICY_VERSION,
    FakeClock,
    make_validator,
    role,
)
from neurosphere_api.runtime import CompositionOverrides
from neurosphere_api.runtime.builders import AUDIT_REPOSITORY, BuildContext, BuilderSpec
from neurosphere_api.runtime.builders import admin as admin_builder
from neurosphere_api.runtime.builders import authz as authz_builder
from neurosphere_core.audit import AuditRepository, InMemoryAuditStore
from neurosphere_core.auth.revocation import InMemoryRevocationStore
from neurosphere_core.auth.scope import (
    InMemoryPolicyRepository,
    PolicyHead,
    PolicyRoleAssignment,
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
    "AGENT",
    "BASE",
    "CONTROL",
    "CUSTOMER",
    "CUSTOMER_ADMIN",
    "DOMAIN_ADMIN",
    "FINANCE",
    "HR",
    "HR_AGENT",
    "HR_ONLY",
    "OPERATIONS",
    "TARGET",
    "FakeResourceDomains",
    "IdentityWorld",
    "configure_env",
    "pid",
]

DOMAIN_ADMIN = "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"
CUSTOMER_ADMIN = "2b3c4d5e-6f7a-4b8c-9d0e-1f2a3b4c5d6e"
TARGET = "3c4d5e6f-7a8b-4c9d-8e1f-2a3b4c5d6e7f"
HR_ONLY = "4d5e6f7a-8b9c-4d0e-9f2a-3b4c5d6e7f80"
CONTROL = customer_control_domain_id("commercial", CUSTOMER)
AGENT = "commercial:contoso:foundry:agent:support-bot"
HR_AGENT = "commercial:contoso:foundry:agent:hr-bot"
BASE = "/api/v1/admin/identity"


def pid(object_id: str) -> str:
    return str(runtime_helpers.composed_principal_id(object_id))


def configure_env(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime_helpers.configure_auth_env(monkeypatch)


def _doc(
    object_id: str, memberships: tuple[str, ...], *roles: PolicyRoleAssignment
) -> PrincipalPolicy:
    principal = pid(object_id)
    return PrincipalPolicy(
        id=principal_document_id(principal),
        customer_id=CUSTOMER,
        principal_id=principal,
        domain_memberships=memberships,
        role_assignments=roles,
    )


def seeded_policies() -> InMemoryPolicyRepository:
    repo = InMemoryPolicyRepository()
    repo.put_head(PolicyHead(customer_id=CUSTOMER, policy_version=POLICY_VERSION))
    repo.put_principal(_doc(DOMAIN_ADMIN, (FINANCE,), role(Role.ADMIN, FINANCE)))
    customer_admin = role(Role.ADMIN, FINANCE, OPERATIONS, CONTROL)
    repo.put_principal(_doc(CUSTOMER_ADMIN, (FINANCE, OPERATIONS, CONTROL), customer_admin))
    repo.put_principal(_doc(TARGET, (FINANCE, OPERATIONS), role(Role.ANALYST, FINANCE)))
    repo.put_principal(_doc(HR_ONLY, (HR,), role(Role.ANALYST, HR)))
    return repo


class FakeResourceDomains:
    """``ResourceDomainResolver`` fake: a fixed resource -> domain map, optional outage."""

    def __init__(self, owners: dict[str, str] | None = None) -> None:
        self.owners = owners if owners is not None else {AGENT: FINANCE, HR_AGENT: HR}
        self.error: Exception | None = None

    async def domain_of(self, scope: Any, resource_id: str) -> str | None:
        if self.error is not None:
            raise self.error
        return self.owners.get(resource_id)


@dataclass
class IdentityWorld:
    composed: Composed
    policies: InMemoryPolicyRepository
    revocations: InMemoryRevocationStore
    audit_store: InMemoryAuditStore
    resources: FakeResourceDomains

    @property
    def clock(self) -> FakeClock:
        return self.composed.clock

    def auth(self, object_id: str, **headers: str) -> dict[str, str]:
        return {**self.composed.auth(object_id), **headers}

    def chain(self, chain_id: str) -> list[dict[str, Any]]:
        docs = self.audit_store.raw_documents(chain_id)
        return sorted(docs, key=lambda d: d["sequence"])

    def all_records(self) -> list[dict[str, Any]]:
        chains = {chain for (chain, _doc) in self.audit_store._docs}  # pyright: ignore[reportPrivateUsage]
        out: list[dict[str, Any]] = []
        for chain in sorted(chains):
            out.extend(self.chain(chain))
        return out

    def stored(self, object_id: str) -> PrincipalPolicy | None:
        return self.policies._principals.get((CUSTOMER, pid(object_id)))  # pyright: ignore[reportPrivateUsage]

    def head(self) -> str:
        head = self.policies._heads[CUSTOMER]  # pyright: ignore[reportPrivateUsage]
        return head.policy_version

    @classmethod
    def build(
        cls, *, extra_builders: tuple[BuilderSpec, ...] = (), **backends: object
    ) -> IdentityWorld:
        clock = FakeClock()
        policies = seeded_policies()
        revocations = InMemoryRevocationStore(clock=clock)
        store = InMemoryAuditStore()
        audit = AuditRepository(store)
        resources = FakeResourceDomains()

        def build_data(ctx: BuildContext) -> None:
            ctx.publish(AUDIT_REPOSITORY, audit)
            ctx.ok("audit")

        overrides = CompositionOverrides(
            authenticator=make_validator(clock),
            policy_repository=policies,
            revocation_store=revocations,
            clock=clock,
            backends={"resource_domains": resources, **backends},
        )
        chain = (
            authz_builder.BUILDER,
            BuilderSpec("stub-data", ("audit",), build_data),
            *extra_builders,
            admin_builder.BUILDER,
        )
        composed = compose(overrides, builders=chain, clock=clock)
        return cls(composed, policies, revocations, store, resources)
