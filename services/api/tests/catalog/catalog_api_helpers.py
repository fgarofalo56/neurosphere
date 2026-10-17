"""Harness for catalog API tests: the real in-memory ``CatalogRepository`` and ``GraphQuery`` over
the fixture search index, entity builders and an app wired with the PRP-06 authz harness. No
network, no Cosmos. ``services/api/tests/catalog`` has no ``__init__.py``: import by module name."""

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
    FINANCE,
    NOBODY,
    OPERATIONS,
    Harness,
    harness,
    policy,
    role,
)
from fastapi import APIRouter
from neurosphere_api.catalog import build_router, get_clock, get_repository
from neurosphere_api.catalog.curation import build_router as build_curation_router
from neurosphere_api.catalog.curation import get_review_queue
from neurosphere_contracts.catalog.v1.invokes import InvokesRelation
from neurosphere_core.audit import AuditRepository, InMemoryAuditStore
from neurosphere_core.auth.scope import Role
from neurosphere_core.catalog import CatalogEntity, InMemoryReviewQueue
from neurosphere_core.catalog.graph import RepositoryGraphQuery
from neurosphere_core.catalog.repo import InMemoryCatalogRepository
from neurosphere_core.catalog.repo.documents import dump, parse_entity
from neurosphere_core.scope import IdentityScope
from neurosphere_core.search.fixture import FixtureSearchIndex, documents_from_catalog

PREFIX = "/catalog"
DAVE = "a05b6c7d-8e9f-4a01-b2c3-d4e5f6a7b8c9"
EVE = "b16c7d8e-9fa0-4b12-83d4-e5f6a7b8c9d0"
STEWARD_FINANCE = ALICE
VIEWER = BOB
STEWARD_BOTH = NOBODY
ANALYST_MIXED = DAVE  # analyst of FINANCE, viewer of OPERATIONS
STEWARD_MIXED = EVE  # steward of FINANCE, viewer of OPERATIONS
_EXAMPLES = Path(__file__).resolve().parents[4] / "packages/contracts/schemas/catalog/v1/examples"
NS = "commercial:contoso"
PERSON = "commercial:contoso:entra:person:psn_0123456789abcdef"


def example(name: str) -> dict[str, Any]:
    return json.loads((_EXAMPLES / "valid" / name).read_text(encoding="utf-8"))


def agent_id(name: str) -> str:
    return f"{NS}:foundry:agent:{name}"


def owner_id(name: str) -> str:
    return f"{NS}:foundry:owner:{name}"


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


def owner_doc(name: str, domain: str = FINANCE, **patch: Any) -> dict[str, Any]:
    raw = example("owner.minimal-and-typical.json")
    raw.update(id=owner_id(name), domain_id=domain, display_name=f"Owner {name}")
    raw.update(patch)
    return raw


def make_edge(name: str, source: str, target: str, domain: str, **patch: Any) -> InvokesRelation:
    raw = example("invokes.inferred.json")
    raw.update(
        id=f"{NS}:neurosphere:invokes:{name}",
        source_id=agent_id(source),
        target_id=agent_id(target),
        domain_id=domain,
        version=1,
        etag="caller-etag",
    )
    raw.update(patch)
    return InvokesRelation.model_validate(raw)


@dataclass
class Api:
    h: Harness
    repo: InMemoryCatalogRepository
    audit: AuditRepository
    docs: list[dict[str, Any]]

    def now(self) -> datetime:
        return datetime.fromtimestamp(self.h.clock.now, UTC)

    def request(self, method: str, who: str | None, path: str, **kw: Any) -> Any:
        headers = dict(kw.pop("headers", {}))
        if who:
            headers.update(self.h.auth(who))
        return self.h.client.request(method, f"{PREFIX}{path}", headers=headers, **kw)

    def get(self, who: str | None, path: str, **kw: Any) -> Any:
        return self.request("GET", who, path, **kw)

    def post(self, who: str | None, path: str, body: Any = None, **kw: Any) -> Any:
        return self.request("POST", who, path, json=body, **kw)

    def put(self, who: str | None, path: str, body: Any, etag: str | None, **kw: Any) -> Any:
        headers = {"If-Match": etag} if etag is not None else {}
        return self.request("PUT", who, path, json=body, headers=headers, **kw)

    async def scope_of(self, who: str) -> IdentityScope:
        claims = await self.h.validator.authenticate(self.h.auth(who)["Authorization"])
        return (await self.h.deriver.derive(claims)).scope

    def seed(self, *docs: dict[str, Any]) -> list[CatalogEntity]:
        """Store entity documents as a steward of both domains (bypasses the API)."""

        async def run() -> list[CatalogEntity]:
            scope = await self.scope_of(STEWARD_BOTH)
            made: list[CatalogEntity] = []
            for doc in docs:
                made.append(await self.repo.create_entity(scope, parse_entity(doc)))
            return made

        made = asyncio.run(run())
        self._reindex()
        return made

    def seed_edges(self, *edges: InvokesRelation) -> None:
        async def run() -> None:
            scope = await self.scope_of(STEWARD_BOTH)
            for e in edges:
                await self.repo.put_edge(scope, e, None)

        asyncio.run(run())

    def stored(self, entity_id: str, who: str = STEWARD_BOTH) -> CatalogEntity | None:
        async def run() -> CatalogEntity | None:
            return await self.repo.get_entity(await self.scope_of(who), entity_id)

        return asyncio.run(run())

    def _reindex(self) -> None:
        async def run() -> list[dict[str, Any]]:
            from neurosphere_core.catalog import EntityFilter
            from neurosphere_core.paging import PageRequest

            scope = await self.scope_of(STEWARD_BOTH)
            page = await self.repo.list_entities(scope, EntityFilter(), PageRequest(page_size=500))
            return [dump(e) for e in page.items]

        self.docs = asyncio.run(run())
        self.h.app.state.catalog_graph = RepositoryGraphQuery(
            self.repo, FixtureSearchIndex(documents_from_catalog(self.docs))
        )

    async def audit_records(self, chain: str = "contoso.finance") -> list[Any]:
        return list(await self.audit.read_range(chain, start=0, limit=500))


def make_api(*, routers: dict[str, APIRouter] | None = None, graph: bool = True) -> Api:
    h = harness(
        policy(STEWARD_FINANCE, role(Role.DOMAIN_STEWARD, FINANCE)),
        policy(VIEWER, role(Role.VIEWER, FINANCE)),
        policy(STEWARD_BOTH, role(Role.DOMAIN_STEWARD, FINANCE, OPERATIONS)),
        policy(ANALYST_MIXED, role(Role.ANALYST, FINANCE), role(Role.VIEWER, OPERATIONS)),
        policy(STEWARD_MIXED, role(Role.DOMAIN_STEWARD, FINANCE), role(Role.VIEWER, OPERATIONS)),
        routers=routers if routers is not None else {PREFIX: build_router()},
    )
    repo = InMemoryCatalogRepository()
    audit = AuditRepository(InMemoryAuditStore())
    api = Api(h=h, repo=repo, audit=audit, docs=[])
    h.app.state.audit_repository = audit
    h.app.dependency_overrides[get_repository] = lambda: repo
    h.app.dependency_overrides[get_clock] = lambda: api.now
    if graph:
        api._reindex()
    return api


def make_both_routers_api(*, curation_first: bool) -> Api:
    """One app with the catalog and the curation routers (registration order is selectable)."""
    pair = [(PREFIX, build_router()), (f"{PREFIX}/curation", build_curation_router())]
    if curation_first:
        pair.reverse()
    api = make_api(routers=dict(pair))
    queue = InMemoryReviewQueue()
    api.h.app.dependency_overrides[get_review_queue] = lambda: queue
    return api
