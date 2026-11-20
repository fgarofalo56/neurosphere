"""Builders and counting fakes shared by the matcher service tests (in-memory twins only)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from neurosphere_contracts.catalog.v1.agent import Agent
from neurosphere_contracts.catalog.v1.invokes import InvokesRelation
from neurosphere_contracts.catalog.v1.tool import Tool
from neurosphere_contracts.recommendations.v1.agent_match_feedback_request import (
    AgentMatchFeedbackRequest,
)
from neurosphere_contracts.recommendations.v1.agent_match_request import AgentMatchRequest
from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope
from neurosphere_core.aggregates.models import (
    AggregateWindow,
    SubjectPoint,
    aggregate_doc_id,
    format_bucket,
)
from neurosphere_core.aggregates.subject import SubjectKind, SubjectLookup
from neurosphere_core.catalog.graph import RepositoryGraphQuery
from neurosphere_core.catalog.protocol import CatalogEntity, GraphResult, NeighborsRequest
from neurosphere_core.catalog.repo import InMemoryCatalogRepository
from neurosphere_core.recommendations.matching import (
    AgentMatcher,
    InMemoryFeedbackStore,
    MatchSettings,
)
from neurosphere_core.scope import IdentityScope
from neurosphere_core.search.fixture.index import FixtureSearchIndex, documents_from_catalog
from neurosphere_core.search.protocol import SearchRequest, SearchResult

NS = "acme"
_EXAMPLES = Path(__file__).resolve().parents[3] / "contracts/schemas/catalog/v1/examples/valid"


def u(value: Any) -> Any:
    """Unwrap contract RootModel wrappers (CanonicalId wraps twice) to the plain value."""
    while hasattr(value, "root"):
        value = value.root
    return value


def dom(name: str, ns: str = NS) -> str:
    return f"commercial:{ns}:neurosphere:domain:{name}"


def agent_id(name: str, ns: str = NS) -> str:
    return f"commercial:{ns}:foundry:agent:{name}"


def tool_id(name: str, ns: str = NS) -> str:
    return f"commercial:{ns}:foundry:tool:{name}"


def make_scope(
    domains: Sequence[str],
    *,
    pseudonym: str = "p-0001",
    ns: str = NS,
    cloud: str = "commercial",
) -> IdentityScope:
    payload: dict[str, Any] = {
        "schema_version": "1.0.0",
        "cloud": cloud,
        "customer_id": ns,
        "principal": {
            "principal_id": f"{cloud}:{ns}:idp:person:{pseudonym}",
            "principal_pseudonym": pseudonym,
            "principal_kind": "user",
        },
        "roles": [{"role": "viewer", "domain_ids": [dom(d, ns) for d in domains]}],
        "allowed_domains": [dom(d, ns) for d in domains],
        "allowed_resources": [],
        "policy_version": "v1",
        "derived_at": "2026-01-01T00:00:00Z",
        "scope_hash": "sha256:" + hashlib.sha256(pseudonym.encode()).hexdigest(),
    }
    return IdentityScope._from_verified_contract(ContractScope.model_validate(payload))


def _example(name: str) -> dict[str, Any]:
    return json.loads((_EXAMPLES / name).read_text(encoding="utf-8"))


def make_agent(
    name: str,
    domain: str,
    *,
    description: str = "",
    tags: Sequence[str] = (),
    capabilities: Sequence[str] = (),
    environment: str = "production",
    ns: str = NS,
) -> Agent:
    raw = _example("agent.minimal-and-typical.json")
    raw.update(
        id=agent_id(name, ns),
        customer_id=ns,
        domain_id=dom(domain, ns),
        current_version_id=None,
        external_agent_id=None,
        version=1,
        etag="caller-etag",
        display_name=f"Agent {name}",
        description=description or None,
        tags=list(tags),
        capabilities=list(capabilities),
        environment=environment,
    )
    return Agent.model_validate(raw)


def make_tool(
    name: str,
    domain: str,
    *,
    tags: Sequence[str] = (),
    capabilities: Sequence[str] = (),
    ns: str = NS,
) -> Tool:
    raw = _example("tool.minimal-and-typical.json")
    raw.update(
        id=tool_id(name, ns),
        customer_id=ns,
        domain_id=dom(domain, ns),
        version=1,
        etag="caller-etag",
        display_name=f"Tool {name}",
        tags=list(tags),
        capabilities=list(capabilities),
    )
    return Tool.model_validate(raw)


def make_edge(name: str, src: str, dst: str, domain: str, ns: str = NS) -> InvokesRelation:
    raw = _example("invokes.inferred.json")
    raw.update(
        id=f"commercial:{ns}:neurosphere:invokes:{name}",
        source_id=agent_id(src, ns),
        target_id=agent_id(dst, ns),
        customer_id=ns,
        domain_id=dom(domain, ns),
        version=1,
        etag="caller-etag",
    )
    return InvokesRelation.model_validate(raw)


def make_request(task: str = "summarize support ticket", **patch: Any) -> AgentMatchRequest:
    raw: dict[str, Any] = {"schema_version": "1.0.0", "task_text": task}
    raw.update(patch)
    return AgentMatchRequest.model_validate(raw)


def make_feedback(
    match_id: str, entity_id: str, decision: str, reason: str | None = None
) -> AgentMatchFeedbackRequest:
    return AgentMatchFeedbackRequest.model_validate(
        {
            "schema_version": "1.0.0",
            "match_id": match_id,
            "entity_id": entity_id,
            "decision": decision,
            "reason_code": reason,
        }
    )


def make_point(
    entity_id: str,
    domain: str,
    *,
    events: int = 500,
    p95: int | None = 200,
    error_rate: float | None = 0.02,
    ns: str = NS,
) -> SubjectPoint:
    key = f"agent:{entity_id}"
    start = format_bucket(datetime.now(UTC).replace(minute=0, second=0, microsecond=0))
    return SubjectPoint(
        id=aggregate_doc_id(ns, dom(domain, ns), "subject", "hour", start, key),
        customer_id=ns,
        domain_id=dom(domain, ns),
        grain="hour",
        bucket_start=start,
        series_key=key,
        watermark=start,
        complete=True,
        subject_kind="agent",
        subject_key=key,
        event_count=events,
        missing_duration_count=0,
        unknown_outcome_count=0,
        error_count=None if error_rate is None else 0,
        error_rate=error_rate,
        p50_ms=p95,
        p95_ms=p95,
        tokens_known_count=0,
    )


class CountingSearch:
    """Wraps the fixture index; records every request and the scope it was called with."""

    def __init__(self, inner: FixtureSearchIndex) -> None:
        self._inner = inner
        self.requests: list[SearchRequest] = []

    async def search(self, scope: ContractScope, request: SearchRequest) -> SearchResult:
        self.requests.append(request)
        return await self._inner.search(scope, request)


class CountingGraph(RepositoryGraphQuery):
    """Counts ``neighbors`` walks per node id and ``get`` calls."""

    def __init__(self, repo: InMemoryCatalogRepository, search: CountingSearch) -> None:
        super().__init__(repo, search)
        self.walks: list[str] = []
        self.gets: list[str] = []

    async def get(self, scope: IdentityScope, node_id: str) -> CatalogEntity | None:
        self.gets.append(node_id)
        return await super().get(scope, node_id)

    async def neighbors(self, scope: IdentityScope, request: NeighborsRequest) -> GraphResult:
        self.walks.append(request.node_id)
        return await super().neighbors(scope, request)


class FakeSubjects:
    """``SubjectMetricsReader`` with canned points; records every read (domain, key count)."""

    def __init__(
        self, points: Sequence[SubjectPoint] = (), *, fail: Exception | None = None
    ) -> None:
        self._points = {p.subject_key: p for p in points}
        self._fail = fail
        self.reads: list[tuple[str, int]] = []

    async def latest_subject_points(
        self,
        customer_id: str,
        domain_id: str,
        kind: SubjectKind,
        keys: Sequence[str],
        window: AggregateWindow,
    ) -> SubjectLookup:
        self.reads.append((domain_id, len(keys)))
        if self._fail is not None:
            raise self._fail
        return SubjectLookup(points={k: self._points[k] for k in keys if k in self._points})

    async def newest_subject_points(
        self, customer_id: str, domain_id: str, window: AggregateWindow, limit: int
    ) -> SubjectLookup:
        return SubjectLookup(points={})


class World:
    """A catalog, its search index, a counting graph, a feedback store and a matcher."""

    def __init__(
        self,
        entities: Sequence[CatalogEntity],
        *,
        edges: Sequence[InvokesRelation] = (),
        subjects: FakeSubjects | None = None,
        settings: MatchSettings | None = None,
    ) -> None:
        self.entities = list(entities)
        self.edges = list(edges)
        self.repo = InMemoryCatalogRepository()
        docs = documents_from_catalog([e.model_dump(mode="json") for e in self.entities])
        self.search = CountingSearch(FixtureSearchIndex(docs))
        self.graph = CountingGraph(self.repo, self.search)
        self.store = InMemoryFeedbackStore()
        self.subjects = subjects
        self.matcher = AgentMatcher(
            self.search,
            self.graph,
            self.store,
            subjects=subjects,
            settings=settings or MatchSettings(),
        )

    async def seed(self) -> World:
        """Create entities and edges through a scope that can write every domain used."""
        entities: list[Any] = list(self.entities)
        for customer in sorted({str(e.customer_id.root) for e in entities}):
            domains = sorted(
                {
                    str(e.domain_id.root).rsplit(":", 1)[-1]
                    for e in entities
                    if e.customer_id.root == customer
                }
            )
            writer = make_scope(domains, pseudonym="p-writer", ns=customer)
            for entity in entities:
                if entity.customer_id.root == customer:
                    await self.repo.create_entity(writer, entity)
        domains = sorted(
            {str(e.domain_id.root).rsplit(":", 1)[-1] for e in entities if e.customer_id.root == NS}
        )
        writer = make_scope(domains, pseudonym="p-writer")
        for edge in self.edges:
            await self.repo.put_edge(writer, edge, None)
        return self
