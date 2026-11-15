"""Shared harness for the producer admin API tests (PRP-41).

Composes the REAL authz builder, a stub data builder (in-memory audit) and the REAL edge builder
over an in-memory ``admin_config`` repository, with the ingest service built on the layered
registry (store first, file fallback) and an in-memory publisher. Principals (object ids are test
fixtures, never in any response or log):

* ``CUSTOMER_ADMIN``: ``admin`` on FINANCE and the customer-control domain (customer-wide).
* ``DOMAIN_ADMIN``: ``admin`` on FINANCE only (``config.manage`` in an ordinary domain).
* ``ANALYST``: analyst in FINANCE.
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
from neurosphere_api.ingest import (
    IngestSettings,
    InMemoryPublisher,
    build_service,
    configure_ingest,
)
from neurosphere_api.ingest.auth import StaticProducerRegistry
from neurosphere_api.ingest.producer_store import LayeredProducerRegistry, StoreProducerRegistry
from neurosphere_api.runtime import CompositionOverrides
from neurosphere_api.runtime.builders import AUDIT_REPOSITORY, BuildContext, BuilderSpec
from neurosphere_api.runtime.builders import authz as authz_builder
from neurosphere_api.runtime.builders import edge as edge_builder
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
from neurosphere_core.cloud import Settings
from runtime_api import runtime_helpers  # pyright: ignore[reportMissingImports]
from runtime_api.runtime_helpers import Composed, compose  # pyright: ignore[reportMissingImports]

__all__ = [
    "ANALYST",
    "BASE",
    "CUSTOMER",
    "CUSTOMER_ADMIN",
    "DOMAIN_ADMIN",
    "EVENTS",
    "ProducerWorld",
    "configure_env",
    "telemetry_event",
]

CUSTOMER_ADMIN = "2b3c4d5e-6f7a-4b8c-9d0e-1f2a3b4c5d6e"
DOMAIN_ADMIN = "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"
ANALYST = "3c4d5e6f-7a8b-4c9d-8e1f-2a3b4c5d6e7f"
CONTROL = customer_control_domain_id("commercial", CUSTOMER)
BASE = "/api/v1/admin/sources/producers"
EVENTS = "/api/v1/ingest/events"


def configure_env(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime_helpers.configure_auth_env(monkeypatch)


def _doc(object_id: str, memberships: tuple[str, ...], *roles: Any) -> PrincipalPolicy:
    principal = str(runtime_helpers.composed_principal_id(object_id))
    return PrincipalPolicy(
        id=principal_document_id(principal),
        customer_id=CUSTOMER,
        principal_id=principal,
        domain_memberships=memberships,
        role_assignments=tuple(roles),
    )


def seeded_policies() -> InMemoryPolicyRepository:
    repo = InMemoryPolicyRepository()
    repo.put_head(PolicyHead(customer_id=CUSTOMER, policy_version=POLICY_VERSION))
    repo.put_principal(_doc(CUSTOMER_ADMIN, (FINANCE, CONTROL), role(Role.ADMIN, FINANCE, CONTROL)))
    repo.put_principal(_doc(DOMAIN_ADMIN, (FINANCE,), role(Role.ADMIN, FINANCE)))
    repo.put_principal(_doc(ANALYST, (FINANCE,), role(Role.ANALYST, FINANCE)))
    return repo


def telemetry_event(source_id: str, event_id: str = "ev-1") -> dict[str, Any]:
    return {
        "specversion": "1.0",
        "id": "ce-1",
        "source": "synthetic/producer",
        "type": "com.neurosphere.telemetry.v1",
        "datacontenttype": "application/json",
        "data": {
            "schema_version": "1.0.0",
            "event_id": event_id,
            "event_time": "2026-01-01T00:00:00Z",
            "cloud": "commercial",
            "customer_id": CUSTOMER,
            "source_id": source_id,
            "request_id": "req-9",
        },
    }


@dataclass
class ProducerWorld:
    composed: Composed
    repository: InMemoryAdminConfigRepository
    audit_store: InMemoryAuditStore
    store: StoreProducerRegistry
    publisher: InMemoryPublisher

    def auth(self, object_id: str) -> dict[str, str]:
        return self.composed.auth(object_id)

    def records(self) -> list[dict[str, Any]]:
        chains = {chain for (chain, _doc) in self.audit_store._docs}  # pyright: ignore[reportPrivateUsage]
        out: list[dict[str, Any]] = []
        for chain in sorted(chains):
            docs = self.audit_store.raw_documents(chain)
            out.extend(sorted(docs, key=lambda d: d["sequence"]))
        return out

    @classmethod
    def build(
        cls,
        *,
        fallback: StaticProducerRegistry | None = None,
        repository: InMemoryAdminConfigRepository | None = None,
        with_store: bool = True,
    ) -> ProducerWorld:
        clock = FakeClock()
        repo = repository or InMemoryAdminConfigRepository(cloud="commercial")
        audit_store = InMemoryAuditStore()
        audit = AuditRepository(audit_store)
        store = StoreProducerRegistry()
        publisher = InMemoryPublisher()
        settings = Settings(env="local")
        registry = LayeredProducerRegistry(store, fallback or StaticProducerRegistry([]))

        def build_data(ctx: BuildContext) -> None:
            ctx.publish(AUDIT_REPOSITORY, audit)
            ctx.ok("audit")

        def build_ingest(ctx: BuildContext) -> None:
            if with_store:
                ctx.app.state.ingest_producer_store = store
            service = build_service(settings, IngestSettings(), publisher, registry=registry)
            configure_ingest(ctx.app, service)

        overrides = CompositionOverrides(
            authenticator=make_validator(clock),
            policy_repository=seeded_policies(),
            revocation_store=InMemoryRevocationStore(clock=clock),
            clock=clock,
            backends={"admin_config_repository": repo},
        )
        chain = (
            authz_builder.BUILDER,
            BuilderSpec("stub-data", ("audit",), build_data),
            BuilderSpec("stub-ingest", (), build_ingest),
            edge_builder.BUILDER,
        )
        composed = compose(overrides, builders=chain, clock=clock, settings=settings)
        return cls(composed, repo, audit_store, store, publisher)
