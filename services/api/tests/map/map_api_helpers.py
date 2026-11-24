"""Harness for viewport API tests: the PRP-06 authz harness (dev-issuer tokens, in-memory policy
store) with the real router, the in-memory catalog repository and graph query, an
``InMemoryAggregateStore`` and a fixed clock. No network, no Cosmos.

``services/api/tests/map`` has no ``__init__.py``: import this module by name."""

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from authz.authz_helpers import (  # pyright: ignore[reportMissingImports]
    ALICE,
    BOB,
    CUSTOMER,
    FINANCE,
    NOBODY,
    OPERATIONS,
    Harness,
    harness,
    policy,
    pseudonymizer,
    role,
)
from neurosphere_api.map import ViewportLimits, build_router, get_clock
from neurosphere_contracts.catalog.v1.delegates_to import DelegatesToRelation
from neurosphere_contracts.catalog.v1.depends_on import DependsOnRelation
from neurosphere_contracts.catalog.v1.invokes import InvokesRelation
from neurosphere_core.aggregates import (
    AggregateStatus,
    InMemoryAggregateStore,
    SubjectPoint,
    aggregate_doc_id,
    bucket_start,
    format_bucket,
)
from neurosphere_core.auth.scope import Role
from neurosphere_core.catalog.graph import RepositoryGraphQuery
from neurosphere_core.catalog.repo import InMemoryCatalogRepository
from neurosphere_core.catalog.repo.documents import dump, parse_entity
from neurosphere_core.scope import IdentityScope
from neurosphere_core.search.fixture import FixtureSearchIndex, documents_from_catalog

__all__ = [
    "ALICE",
    "BOB",
    "FINANCE",
    "NOW",
    "OPERATIONS",
    "PREFIX",
    "Api",
    "agent_doc",
    "agent_id",
    "make_api",
    "make_edge",
    "mcp_doc",
    "model_doc",
    "person_doc",
    "put_points",
    "service_doc",
    "service_id",
    "subject_point",
    "tool_doc",
    "tool_id",
]

PREFIX = "/api/v1/map"
NS = "commercial:contoso"
NOW = datetime(2027, 1, 15, 8, 30, tzinfo=UTC)
STEWARD_BOTH = NOBODY
_EXAMPLES = Path(__file__).resolve().parents[4] / "packages/contracts/schemas/catalog/v1/examples"


def example(name: str) -> dict[str, Any]:
    return json.loads((_EXAMPLES / "valid" / name).read_text(encoding="utf-8"))


def agent_id(name: str) -> str:
    return f"{NS}:foundry:agent:{name}"


def agent_doc(name: str, domain: str = FINANCE) -> dict[str, Any]:
    raw = example("agent.minimal-and-typical.json")
    raw.update(
        id=agent_id(name),
        domain_id=domain,
        current_version_id=None,
        external_agent_id=None,
        display_name=f"Agent {name}",
        attributes=None,
    )
    return raw


def person_doc(name: str, domain: str = FINANCE) -> dict[str, Any]:
    raw = example("person.minimal-and-typical.json")
    raw.update(
        id=f"{NS}:entra:person:psn_{name}", principal_pseudonym=f"psn_{name}", domain_id=domain
    )
    return raw


def model_doc(name: str, domain: str = FINANCE) -> dict[str, Any]:
    raw = example("model_deployment.minimal-and-typical.json")
    raw.update(id=f"{NS}:foundry:model_deployment:{name}", domain_id=domain, deployment_name=name)
    return raw


def service_id(name: str) -> str:
    return f"{NS}:foundry:service:{name}"


def tool_id(name: str) -> str:
    return f"{NS}:foundry:tool:{name}"


def service_doc(name: str, domain: str = FINANCE, **patch: Any) -> dict[str, Any]:
    raw = example("service.minimal-and-typical.json")
    raw.update(id=service_id(name), domain_id=domain, display_name=f"Service {name}")
    raw.update(patch)
    return raw


def tool_doc(name: str, domain: str = FINANCE, **patch: Any) -> dict[str, Any]:
    raw = example("tool.minimal-and-typical.json")
    raw.update(id=tool_id(name), domain_id=domain, display_name=f"Tool {name}", mcp_server_ref=None)
    raw.update(patch)
    return raw


def mcp_doc(name: str, domain: str = FINANCE, **patch: Any) -> dict[str, Any]:
    raw = example("mcp_server.entra-streamable-http.json")
    raw.update(
        id=f"{NS}:neurosphere:mcp_server:{name}", domain_id=domain, display_name=f"Mcp {name}"
    )
    raw.update(patch)
    return raw


def subject_point(
    key: str,
    *,
    events: int = 10,
    error_count: int | None = 0,
    error_rate: float | None = 0.0,
    domain: str = FINANCE,
) -> SubjectPoint:
    """Newest-hour subject point for a series key (agent, model, tool or service)."""
    start = format_bucket(bucket_start(NOW, "hour"))
    return SubjectPoint(
        id=aggregate_doc_id(CUSTOMER, domain, "subject", "hour", start, key),
        customer_id=CUSTOMER,
        domain_id=domain,
        grain="hour",
        bucket_start=start,
        series_key=key,
        watermark=start,
        complete=True,
        subject_kind=key.partition(":")[0],  # pyright: ignore[reportArgumentType]
        subject_key=key,
        event_count=events,
        missing_duration_count=0,
        unknown_outcome_count=0,
        error_count=error_count,
        error_rate=error_rate,
        p95_ms=100,
    )


def put_points(api: "Api", *points: SubjectPoint) -> None:
    async def run() -> None:
        buckets: dict[tuple[str, str, str], list[SubjectPoint]] = {}
        for p in points:  # replace_bucket replaces the whole bucket: group first
            buckets.setdefault((p.customer_id, p.domain_id, p.bucket_start), []).append(p)
        for (cust, domain, start), docs in buckets.items():
            await api.store.replace_bucket(cust, domain, "hour", start, docs)

    asyncio.run(run())


def make_edge(
    name: str,
    source: str,
    target: str,
    domain: str = FINANCE,
    *,
    relation: str = "invokes",
    status_file: str = "inferred",
    **patch: Any,
) -> InvokesRelation | DelegatesToRelation | DependsOnRelation:
    raw = example(f"{relation}.{status_file}.json")
    raw.update(
        id=f"{NS}:neurosphere:{relation}:{name}",
        source_id=source,
        target_id=target,
        domain_id=domain,
        version=1,
        etag="caller-etag",
    )
    raw.update(patch)
    models: dict[str, Any] = {
        "invokes": InvokesRelation,
        "delegates_to": DelegatesToRelation,
        "depends_on": DependsOnRelation,
    }
    return models[relation].model_validate(raw)


@dataclass
class Api:
    h: Harness
    repo: InMemoryCatalogRepository
    store: InMemoryAggregateStore

    def get(self, who: str | None, domain: str, **params: Any) -> Any:
        headers = self.h.auth(who) if who else {}
        return self.h.client.get(
            f"{PREFIX}/domains/{domain}/viewport", headers=headers, params=params
        )

    async def scope_of(self, who: str) -> IdentityScope:
        claims = await self.h.validator.authenticate(self.h.auth(who)["Authorization"])
        return (await self.h.deriver.derive(claims)).scope

    def seed(self, *docs: dict[str, Any]) -> None:
        async def run() -> list[dict[str, Any]]:
            scope = await self.scope_of(STEWARD_BOTH)
            for doc in docs:
                await self.repo.create_entity(scope, parse_entity(doc))
            from neurosphere_core.catalog import EntityFilter
            from neurosphere_core.paging import PageRequest

            stored: list[dict[str, Any]] = []
            cursor = None
            while True:
                page = await self.repo.list_entities(
                    scope, EntityFilter(), PageRequest(page_size=500, cursor=cursor)
                )
                stored.extend(dump(e) for e in page.items)
                cursor = page.next_cursor
                if cursor is None:
                    return stored

        stored = asyncio.run(run())
        self.h.app.state.catalog_graph = RepositoryGraphQuery(
            self.repo, FixtureSearchIndex(documents_from_catalog(stored))
        )

    def seed_edges(self, *edges: InvokesRelation | DelegatesToRelation | DependsOnRelation) -> None:
        async def run() -> None:
            scope = await self.scope_of(STEWARD_BOTH)
            for edge in edges:
                await self.repo.put_edge(scope, edge, None)

        asyncio.run(run())

    def set_watermark(self, watermark: datetime | None) -> None:
        text = None if watermark is None else watermark.strftime("%Y-%m-%dT%H:%M:%SZ")
        asyncio.run(self.store.put_status(AggregateStatus(customer_id=CUSTOMER, watermark=text)))

    def limits(self, *, max_nodes: int, max_edges: int = 5000) -> None:
        self.h.app.state.map_viewport_limits = ViewportLimits(
            max_nodes=max_nodes, max_edges=max_edges
        )


def make_api() -> Api:
    h = harness(
        policy(ALICE, role(Role.VIEWER, FINANCE)),
        policy(BOB, role(Role.VIEWER, OPERATIONS)),
        policy(STEWARD_BOTH, role(Role.DOMAIN_STEWARD, FINANCE, OPERATIONS)),
        routers={PREFIX: build_router()},
    )
    repo = InMemoryCatalogRepository()
    store = InMemoryAggregateStore()
    h.app.state.catalog_repository = repo
    h.app.state.aggregate_reader = store
    h.app.state.map_pseudonymizer = pseudonymizer()
    h.app.dependency_overrides[get_clock] = lambda: lambda: NOW
    api = Api(h=h, repo=repo, store=store)
    api.seed()
    api.set_watermark(NOW)
    return api
