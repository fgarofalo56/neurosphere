"""Harness for the PRP-31 item 2 adapter tests: the default app (every registered router, so the
adapters sit beside the real PRP-29 routes), the PRP-06 dev-issuer authz harness, the in-memory
catalog repository and graph, an in-memory audit store and a review queue. No network, no
compose, no cloud; synthetic ``contoso`` ids only."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from authz.authz_helpers import (  # pyright: ignore[reportMissingImports]
    ALICE,
    BOB,
    CAROL,
    CUSTOMER,
    FINANCE,
    HR,
    NOBODY,
    OPERATIONS,
    TENANT,
    Harness,
    harness,
    policy,
    pseudonymizer,
    role,
)
from neurosphere_api.catalog.curation import get_clock, get_repository, get_review_queue
from neurosphere_contracts.catalog.v1.invokes import InvokesRelation
from neurosphere_core.audit import AuditRepository, InMemoryAuditStore
from neurosphere_core.auth.scope import (
    PrincipalPolicy,
    Role,
    principal_document_id,
)
from neurosphere_core.catalog import CatalogEdge, CatalogEntity, EntityFilter, InMemoryReviewQueue
from neurosphere_core.catalog.graph import RepositoryGraphQuery
from neurosphere_core.catalog.repo import InMemoryCatalogRepository
from neurosphere_core.catalog.repo.documents import dump, parse_entity
from neurosphere_core.cloud import CloudName
from neurosphere_core.paging import PageRequest
from neurosphere_core.scope import IdentityScope
from neurosphere_core.search.fixture import FixtureSearchIndex, documents_from_catalog

NS = "commercial:contoso"
_EXAMPLES = Path(__file__).resolve().parents[4] / "packages/contracts/schemas/catalog/v1/examples"

#: Steward of FINANCE (catalog.curate, data.read, data.export).
STEWARD = ALICE
#: Viewer of FINANCE (data.read only).
VIEWER = BOB
#: Security auditor of FINANCE only (audit.read, evidence.read; NO data.read).
AUDITOR = CAROL
#: Steward of FINANCE and OPERATIONS (used to seed data).
STEWARD_BOTH = NOBODY
#: Security auditor of FINANCE and OPERATIONS.
AUDITOR_BOTH = "c27d8e9f-a0b1-4c23-94e5-f6a7b8c9d0e1"
#: Service principal (``idtyp: app``) holding domain_steward on FINANCE.
APP_STEWARD = "d38e9fa0-b1c2-4d34-a5f6-a7b8c9d0e1f2"
#: Auditor whose role names another customer's domain and an aliasing domain only.
AUDITOR_FOREIGN = "e49fa0b1-c2d3-4e45-b6a7-b8c9d0e1f2a3"
#: Security auditor AND viewer of FINANCE (may read the catalog's domain names).
AUDITOR_READER = "f5a0b1c2-d3e4-4f56-87b8-c9d0e1f2a3b4"

OTHER_CUSTOMER_FINANCE = "commercial:fabrikam:catalog:domain:finance"
#: Same last segment as FINANCE but another source: its chain would alias FINANCE's chain.
ALIASING_FINANCE = "commercial:contoso:billing:domain:finance"


def example(name: str) -> dict[str, Any]:
    return json.loads((_EXAMPLES / "valid" / name).read_text(encoding="utf-8"))


def agent_id(name: str) -> str:
    return f"{NS}:foundry:agent:{name}"


def agent_doc(name: str, domain: str = FINANCE, **patch: Any) -> dict[str, Any]:
    raw = example("agent.minimal-and-typical.json")
    raw.update(
        id=agent_id(name),
        domain_id=domain,
        current_version_id=None,
        external_agent_id=None,
        display_name=f"Agent {name}",
        attributes=None,
    )
    raw.update(patch)
    return raw


def domain_doc(domain: str, display_name: str) -> dict[str, Any]:
    raw = example("domain.minimal-and-typical.json")
    raw.update(id=domain, display_name=display_name)
    return raw


def make_edge(name: str, source: str, target: str, domain: str = FINANCE) -> InvokesRelation:
    raw = example("invokes.inferred.json")
    raw.update(
        id=f"{NS}:neurosphere:invokes:{name}",
        source_id=agent_id(source),
        target_id=agent_id(target),
        domain_id=domain,
        version=1,
        etag="caller-etag",
    )
    return InvokesRelation.model_validate(raw)


def _app_policy(object_id: str) -> PrincipalPolicy:
    pid = pseudonymizer().principal_id(
        cloud=CloudName.COMMERCIAL,
        customer_id=CUSTOMER,
        tenant_id=TENANT,
        object_id=object_id,
        kind="service_principal",
    )
    return PrincipalPolicy(
        id=principal_document_id(pid),
        customer_id=CUSTOMER,
        principal_id=pid,
        domain_memberships=(FINANCE, OPERATIONS, HR),
        role_assignments=(role(Role.DOMAIN_STEWARD, FINANCE),),
        grants=(),
    )


@dataclass
class World:
    h: Harness
    repo: InMemoryCatalogRepository
    audit: AuditRepository
    queue: InMemoryReviewQueue

    def now(self) -> datetime:
        return datetime.fromtimestamp(self.h.clock.now, UTC)

    def headers(self, who: str | None, **extra: Any) -> dict[str, str]:
        return self.h.auth(who, **extra) if who else {}

    def get(self, who: str | None, path: str, **kw: Any) -> Any:
        return self.h.client.get(path, headers=self.headers(who), **kw)

    def post(self, who: str | None, path: str, body: Any, **kw: Any) -> Any:
        headers = {**self.headers(who), **kw.pop("headers", {})}
        return self.h.client.post(path, json=body, headers=headers, **kw)

    async def scope_of(self, who: str) -> IdentityScope:
        claims = await self.h.validator.authenticate(self.h.auth(who)["Authorization"])
        return (await self.h.deriver.derive(claims)).scope

    def seed(self, *docs: dict[str, Any]) -> list[CatalogEntity]:
        async def run() -> list[CatalogEntity]:
            scope = await self.scope_of(STEWARD_BOTH)
            return [await self.repo.create_entity(scope, parse_entity(d)) for d in docs]

        made = asyncio.run(run())
        self.reindex()
        return made

    def seed_edges(self, *edges: CatalogEdge) -> list[CatalogEdge]:
        async def run() -> list[CatalogEdge]:
            scope = await self.scope_of(STEWARD_BOTH)
            stored: list[CatalogEdge] = []
            for edge in edges:
                await self.repo.put_edge(scope, edge, None)
                found = await self.repo.get_edge(scope, edge.id)
                assert found is not None
                stored.append(found)
            return stored

        return asyncio.run(run())

    def reindex(self) -> None:
        async def run() -> list[dict[str, Any]]:
            scope = await self.scope_of(STEWARD_BOTH)
            page = await self.repo.list_entities(scope, EntityFilter(), PageRequest(page_size=500))
            return [dump(e) for e in page.items]

        docs = asyncio.run(run())
        self.h.app.state.catalog_graph = RepositoryGraphQuery(
            self.repo, FixtureSearchIndex(documents_from_catalog(docs))
        )

    def records(self, chain: str = "contoso.finance") -> list[Any]:
        return list(asyncio.run(self.audit.read_range(chain, start=0, limit=500)))


def make_world() -> World:
    h = harness(
        policy(STEWARD, role(Role.DOMAIN_STEWARD, FINANCE)),
        policy(VIEWER, role(Role.VIEWER, FINANCE)),
        policy(AUDITOR, role(Role.SECURITY_AUDITOR, FINANCE)),
        policy(STEWARD_BOTH, role(Role.DOMAIN_STEWARD, FINANCE, OPERATIONS)),
        policy(AUDITOR_BOTH, role(Role.SECURITY_AUDITOR, FINANCE, OPERATIONS)),
        policy(
            AUDITOR_FOREIGN,
            role(Role.SECURITY_AUDITOR, OTHER_CUSTOMER_FINANCE, ALIASING_FINANCE),
            memberships=(OTHER_CUSTOMER_FINANCE, ALIASING_FINANCE),
        ),
        policy(
            AUDITOR_READER,
            role(Role.SECURITY_AUDITOR, FINANCE),
            role(Role.VIEWER, FINANCE),
        ),
        _app_policy(APP_STEWARD),
        routers={},
    )
    repo = InMemoryCatalogRepository()
    audit = AuditRepository(InMemoryAuditStore())
    queue = InMemoryReviewQueue()
    world = World(h=h, repo=repo, audit=audit, queue=queue)
    h.app.state.audit_repository = audit
    h.app.dependency_overrides[get_repository] = lambda: repo
    h.app.dependency_overrides[get_review_queue] = lambda: queue
    h.app.dependency_overrides[get_clock] = lambda: world.now
    world.reindex()
    return world
