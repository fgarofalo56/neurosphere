"""Harness for the agent identity API tests (PRP-137 item 5).

Composes the REAL authz builder, a stub data builder (in-memory audit and catalog) and the REAL
``agent_identity`` builder. Principals (object ids), all in customer ``contoso``:

* ``STEWARD``: steward in FINANCE (``catalog.curate`` there).
* ``BOTH_STEWARD``: steward in FINANCE and OPS.
* ``OPS_STEWARD``: steward in OPS only (another domain's steward).
* ``VIEWER``: viewer in FINANCE; ``AUDITOR``: security auditor in FINANCE.
* ``EXPIRING``: steward in FINANCE whose role lapses 10 seconds after ``T0``.

Agents: ``fin-one`` and ``fin-two`` in FINANCE, ``ops-one`` in OPS.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from authz.authz_helpers import (  # pyright: ignore[reportMissingImports]
    CUSTOMER,
    FINANCE,
    POLICY_VERSION,
    FakeClock,
    make_validator,
    role,
)
from connectors_harness import configure_env  # pyright: ignore[reportMissingImports]
from neurosphere_api.runtime import CompositionOverrides
from neurosphere_api.runtime.builders import (
    AUDIT_REPOSITORY,
    CATALOG_REPOSITORY,
    BuildContext,
    BuilderSpec,
)
from neurosphere_api.runtime.builders import agent_identity as builder
from neurosphere_api.runtime.builders import authz as authz_builder
from neurosphere_contracts.catalog.v1.agent import Agent
from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope
from neurosphere_core.audit import AuditRepository, InMemoryAuditStore
from neurosphere_core.auth.revocation import InMemoryRevocationStore
from neurosphere_core.auth.scope import (
    InMemoryPolicyRepository,
    PolicyHead,
    PrincipalPolicy,
    Role,
    principal_document_id,
)
from neurosphere_core.catalog.repo import InMemoryCatalogRepository
from neurosphere_core.scope import IdentityScope
from runtime_api import runtime_helpers  # pyright: ignore[reportMissingImports]
from runtime_api.runtime_helpers import (  # pyright: ignore[reportMissingImports]
    Composed,
    compose,
)

__all__ = [
    "AUDITOR",
    "BOTH_STEWARD",
    "EXPIRING",
    "FINANCE",
    "OPS",
    "OPS_STEWARD",
    "STEWARD",
    "VIEWER",
    "AliasWorld",
    "agent_id",
    "body",
    "build",
    "configure_env",
]

STEWARD = "4d5e6f7a-8b9c-4d0e-9f2a-3b4c5d6e7f80"
BOTH_STEWARD = "5e6f7a8b-9c0d-4e1f-8a3b-4c5d6e7f8091"
OPS_STEWARD = "6f7a8b9c-0d1e-4f2a-9b4c-5d6e7f8091a2"
VIEWER = "7a8b9c0d-1e2f-4a3b-8c5d-6e7f8091a2b3"
AUDITOR = "8b9c0d1e-2f3a-4b4c-9d6e-7f8091a2b3c4"
EXPIRING = "9c0d1e2f-3a4b-4c5d-8e7f-8091a2b3c4d5"
OPS = "commercial:contoso:catalog:domain:ops"
BASE = "/api/v1/agent-identity/domains"
_VALID = (
    Path(__file__).resolve().parents[4] / "packages/contracts/schemas/catalog/v1/examples/valid"
)


def agent_id(name: str) -> str:
    return f"commercial:{CUSTOMER}:foundry:agent:{name}"


def _doc(
    object_id: str, who: Role, *domains: str, expires_in: float | None = None
) -> PrincipalPolicy:
    principal = runtime_helpers.composed_principal_id(object_id)
    return PrincipalPolicy(
        id=principal_document_id(str(principal)),
        customer_id=CUSTOMER,
        principal_id=str(principal),
        domain_memberships=domains,
        role_assignments=(role(who, *domains, expires_in=expires_in),),
    )


def _policies() -> InMemoryPolicyRepository:
    repo = InMemoryPolicyRepository()
    repo.put_head(PolicyHead(customer_id=CUSTOMER, policy_version=POLICY_VERSION))
    repo.put_principal(_doc(STEWARD, Role.DOMAIN_STEWARD, FINANCE))
    repo.put_principal(_doc(BOTH_STEWARD, Role.DOMAIN_STEWARD, FINANCE, OPS))
    repo.put_principal(_doc(OPS_STEWARD, Role.DOMAIN_STEWARD, OPS))
    repo.put_principal(_doc(VIEWER, Role.VIEWER, FINANCE))
    repo.put_principal(_doc(AUDITOR, Role.SECURITY_AUDITOR, FINANCE))
    repo.put_principal(_doc(EXPIRING, Role.DOMAIN_STEWARD, FINANCE, expires_in=10))
    return repo


def _seed_scope() -> IdentityScope:
    payload: dict[str, Any] = {
        "schema_version": "1.0.0",
        "cloud": "commercial",
        "customer_id": CUSTOMER,
        "principal": {
            "principal_id": f"commercial:{CUSTOMER}:idp:person:seed",
            "principal_pseudonym": "p-0001",
            "principal_kind": "user",
        },
        "roles": [{"role": "viewer", "domain_ids": [FINANCE, OPS]}],
        "allowed_domains": [FINANCE, OPS],
        "allowed_resources": [],
        "policy_version": "v1",
        "derived_at": "2026-01-01T00:00:00Z",
        "scope_hash": "sha256:" + hashlib.sha256(b"seed").hexdigest(),
    }
    return IdentityScope._from_verified_contract(  # pyright: ignore[reportPrivateUsage]
        ContractScope.model_validate(payload)
    )


def _agent(name: str, domain: str) -> Agent:
    raw = json.loads((_VALID / "agent.minimal-and-typical.json").read_text(encoding="utf-8"))
    raw.update(
        id=agent_id(name),
        customer_id=CUSTOMER,
        domain_id=domain,
        current_version_id=None,
        external_agent_id=None,
        version=1,
        etag="caller-etag",
        display_name=f"Agent {name}",
    )
    return Agent.model_validate(raw)


@dataclass
class AliasWorld:
    composed: Composed
    catalog: InMemoryCatalogRepository
    audit_store: InMemoryAuditStore
    audit: AuditRepository
    clock: FakeClock

    def put(self, domain: str, who: str, body: dict[str, Any]) -> Any:
        return self.composed.client().put(
            f"{BASE}/{domain}/aliases", json=body, headers=self.composed.auth(who)
        )

    def get(self, domain: str, who: str, **params: str) -> Any:
        return self.composed.client().get(
            f"{BASE}/{domain}/aliases", params=params, headers=self.composed.auth(who)
        )

    def audit_docs(self) -> list[dict[str, Any]]:
        docs = self.audit_store._docs  # pyright: ignore[reportPrivateUsage]
        return [json.loads(raw) for (_c, k), raw in sorted(docs.items(), key=str) if k != "tail"]

    def audit_count(self) -> int:
        return len(self.audit_docs())


def seed_scope() -> IdentityScope:
    return _seed_scope()


def body(external: str = "asst-1", target: str | None = None, **over: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "source_id": "foundry",
        "external_agent_id": external,
        "target_agent_id": target or agent_id("fin-one"),
    }
    out.update(over)
    return out


def build(**backends: object) -> AliasWorld:
    clock = FakeClock()
    catalog = InMemoryCatalogRepository()
    scope = _seed_scope()
    for name, domain in (("fin-one", FINANCE), ("fin-two", FINANCE), ("ops-one", OPS)):
        asyncio.run(catalog.create_entity(scope, _agent(name, domain)))
    audit_store = InMemoryAuditStore()
    audit = AuditRepository(audit_store)
    overrides = CompositionOverrides(
        authenticator=make_validator(clock),
        policy_repository=_policies(),
        revocation_store=InMemoryRevocationStore(clock=clock),
        clock=clock,
        backends=dict(backends),
    )

    def build_data(ctx: BuildContext) -> None:
        ctx.publish(AUDIT_REPOSITORY, audit)
        ctx.publish(CATALOG_REPOSITORY, catalog)
        ctx.app.state.audit_repository = audit
        ctx.app.state.catalog_repository = catalog
        ctx.ok("audit")

    chain = (
        authz_builder.BUILDER,
        BuilderSpec("stub-data", ("audit",), build_data),
        builder.BUILDER,
    )
    composed = compose(overrides, builders=chain, clock=clock)
    return AliasWorld(composed, catalog, audit_store, audit, clock)
