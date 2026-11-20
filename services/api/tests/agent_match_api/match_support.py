"""Harness for the agent match API tests: the PRP-06 authz harness (dev-issuer tokens, in-memory
policy store) with the real match router, the real ``AgentMatcher`` over in-memory twins (catalog,
fixture search index, feedback store, subject aggregates) and an in-memory audit chain. No network.

Domains and the customer are the authz harness's (``contoso``); catalog entities are built with the
matcher suite's helpers (``packages/core/tests/agent_match``) for that customer.
"""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import authz.authz_helpers as helpers  # pyright: ignore[reportMissingImports]
from agent_match.match_helpers import (  # pyright: ignore[reportMissingImports]
    CountingGraph,
    CountingSearch,
    FakeSubjects,
    agent_id,
    dom,
    make_agent,
    make_edge,
    make_point,
    make_scope,
    make_tool,
)
from neurosphere_api.recommendations.match import PREFIX, build_router
from neurosphere_contracts.catalog.v1.invokes import InvokesRelation
from neurosphere_core.audit import AuditRepository, InMemoryAuditStore
from neurosphere_core.auth.scope import Role
from neurosphere_core.catalog.protocol import CatalogEntity
from neurosphere_core.catalog.repo import InMemoryCatalogRepository
from neurosphere_core.recommendations.matching import (
    AgentMatcher,
    InMemoryFeedbackStore,
    MatchSettings,
)
from neurosphere_core.search.fixture.index import FixtureSearchIndex, documents_from_catalog

__all__ = [
    "ALICE",
    "BOB",
    "CAROL",
    "CUSTOMER",
    "FIN",
    "NOBODY",
    "OPS",
    "ApiWorld",
    "agent_id",
    "make_agent",
    "make_edge",
    "make_point",
    "make_tool",
]

CUSTOMER: str = helpers.CUSTOMER
ALICE: str = helpers.ALICE  # viewer on finance and operations
BOB: str = helpers.BOB  # viewer on finance only
CAROL: str = helpers.CAROL  # viewer on finance and operations (a third principal)
NOBODY: str = helpers.NOBODY  # no role at all
FIN: str = dom("finance", CUSTOMER)
OPS: str = dom("operations", CUSTOMER)
HR: str = dom("hr", CUSTOMER)


def url(domain: str, suffix: str = "") -> str:
    return PREFIX.replace("{domain}", domain) + suffix


@dataclass
class ApiWorld:
    h: Any
    matcher: AgentMatcher
    store: InMemoryFeedbackStore
    search: CountingSearch
    graph: CountingGraph
    subjects: FakeSubjects
    audit: AuditRepository
    denials: Any

    def post(self, who: str | None, domain: str, body: Any, suffix: str = "") -> Any:
        headers = self.h.auth(who) if who else {}
        return self.h.client.post(url(domain, suffix), json=body, headers=headers)

    def get(self, who: str | None, domain: str, suffix: str = "", **params: Any) -> Any:
        headers = self.h.auth(who) if who else {}
        return self.h.client.get(url(domain, suffix), params=params or None, headers=headers)

    def match(self, who: str, domain: str = FIN, task: str = "summarize support ticket", **p: Any):
        body = {"schema_version": "1.0.0", "task_text": task, **p}
        return self.post(who, domain, body)

    def feedback(self, who: str, match_id: str, entity_id: str, decision: str, domain: str = FIN):
        body = {
            "schema_version": "1.0.0",
            "match_id": match_id,
            "entity_id": entity_id,
            "decision": decision,
        }
        return self.post(who, domain, body, "/feedback")


def make_world(
    entities: Sequence[CatalogEntity],
    *,
    edges: Sequence[InvokesRelation] = (),
    points: Sequence[Any] = (),
    settings: MatchSettings | None = None,
    configured: bool = True,
) -> ApiWorld:
    repo = InMemoryCatalogRepository()
    docs = documents_from_catalog([e.model_dump(mode="json") for e in entities])
    search = CountingSearch(FixtureSearchIndex(docs))
    graph = CountingGraph(repo, search)
    store = InMemoryFeedbackStore()
    subjects = FakeSubjects(points)
    matcher = AgentMatcher(
        search, graph, store, subjects=subjects, settings=settings or MatchSettings()
    )

    async def seed() -> None:
        writer = make_scope(["finance", "operations", "hr"], pseudonym="p-writer", ns=CUSTOMER)
        for entity in entities:
            await repo.create_entity(writer, entity)
        for edge in edges:
            await repo.put_edge(writer, edge, None)

    asyncio.run(seed())
    denials = helpers.RecordingDenials()
    members = (FIN, OPS, HR)
    h = helpers.harness(
        helpers.policy(ALICE, helpers.role(Role.VIEWER, FIN, OPS), memberships=members),
        helpers.policy(BOB, helpers.role(Role.VIEWER, FIN), memberships=members),
        helpers.policy(CAROL, helpers.role(Role.VIEWER, FIN, OPS), memberships=members),
        helpers.policy(NOBODY, memberships=members),
        routers={PREFIX: build_router()},
        denials=denials,
    )
    audit = AuditRepository(InMemoryAuditStore())
    if configured:
        h.app.state.agent_matcher = matcher
        h.app.state.audit_repository = audit
    return ApiWorld(
        h=h,
        matcher=matcher,
        store=store,
        search=search,
        graph=graph,
        subjects=subjects,
        audit=audit,
        denials=denials,
    )
