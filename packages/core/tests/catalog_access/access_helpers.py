"""Builders for the access engine tests: a two-domain world on the in-memory repository."""

from __future__ import annotations

from typing import Any

from catalog.graph_helpers import (  # pyright: ignore[reportMissingImports]
    NOW,
    NS,
    StubSearch,
    agent,
    dom,
    example,
    make_scope,
)
from neurosphere_contracts.catalog.v1.edge_override import EdgeOverride
from neurosphere_contracts.catalog.v1.grounding_source import GroundingSource
from neurosphere_contracts.catalog.v1.reads import ReadsRelation
from neurosphere_contracts.catalog.v1.writes import WritesRelation
from neurosphere_core.catalog.graph import RepositoryGraphQuery
from neurosphere_core.catalog.graph.access import AccessEngine
from neurosphere_core.catalog.protocol import CatalogEdge
from neurosphere_core.catalog.repo import InMemoryCatalogRepository
from neurosphere_core.scope import IdentityScope

__all__ = [
    "NOW",
    "NS",
    "SCOPE_A",
    "SCOPE_AB",
    "SCOPE_B",
    "World",
    "access_edge",
    "asset",
    "asset_id",
    "build_world",
    "make_engine",
    "make_scope",
    "reject",
    "scope_of",
]

SCOPE_A = make_scope(NS, [dom(NS, "a")])
SCOPE_B = make_scope(NS, [dom(NS, "b")])
SCOPE_AB = make_scope(NS, [dom(NS, "a"), dom(NS, "b")])


def asset(name: str, domain: str, **patch: Any) -> GroundingSource:
    raw = example("grounding_source.sensitivity-residency.json")
    raw.update(
        id=f"commercial:{NS}:foundry:grounding_source:{name}",
        customer_id=NS,
        domain_id=dom(NS, domain),
        version=1,
        etag="caller-etag",
        display_name=f"Asset {name}",
        tags=[],
        environment="unknown",
    )
    raw.update(patch)
    return GroundingSource.model_validate(raw)


def asset_id(name: str) -> str:
    return f"commercial:{NS}:foundry:grounding_source:{name}"


def access_edge(
    name: str, relation: str, who: str, what: str, domain: str, **patch: Any
) -> CatalogEdge:
    """A ``reads`` or ``writes`` edge from agent ``who`` to asset ``what`` stored in ``domain``."""
    raw = example(f"{relation}.inferred.json")
    raw.update(
        id=f"commercial:{NS}:neurosphere:{relation}:{name}",
        source_id=f"commercial:{NS}:foundry:agent:{who}",
        target_id=asset_id(what),
        customer_id=NS,
        domain_id=dom(NS, domain),
        version=1,
        etag="caller-etag",
    )
    raw.update(patch)
    return (ReadsRelation if relation == "reads" else WritesRelation).model_validate(raw)


def reject(edge: CatalogEdge, name: str) -> EdgeOverride:
    """A steward reject decision for ``edge``."""
    raw = example("edge_override.lock.json")
    raw.update(
        id=f"commercial:{NS}:neurosphere:edge_override:{name}",
        edge_id=edge.id,
        relation_type=edge.relation_type,
        expected_edge_version=int(edge.version.root),
        expected_edge_etag=edge.etag.root,
        customer_id=NS,
        domain_id=edge.domain_id.root,
        decision="reject",
        decided_at="2026-10-09T17:30:00Z",
        set_confidence=None,
        add_evidence_ids=[],
        lock=None,
    )
    return EdgeOverride.model_validate(raw)


class World:
    """Repository plus the ids of the seeded documents."""

    def __init__(self, repo: InMemoryCatalogRepository) -> None:
        self.repo = repo
        self.edges: dict[str, CatalogEdge] = {}


async def build_world() -> World:
    """Two domains, agents and assets with different sensitivity and residency.

    Domain ``a``: agents a1, a2; assets ``customers`` (pii, westeurope), ``claims`` (phi,
    eastus), ``mystery`` (every sensitivity field null), ``public`` (personal data false, no
    categories, eastus). Domain ``b``: agent b1 and asset ``ledger`` (pii and financial,
    northeurope). Edges (stored in domain a unless noted): a1 writes customers, a2 reads
    customers, b1 reads customers (the accessor lives in domain b), a1 reads claims,
    a2 writes mystery, b2 writes ledger (domain b).
    """
    repo = InMemoryCatalogRepository()
    world = World(repo)
    for name, domain in (("a1", "a"), ("a2", "a"), ("b1", "b"), ("b2", "b")):
        await repo.create_entity(SCOPE_AB, agent(NS, name, domain))
    await repo.create_entity(
        SCOPE_AB,
        asset(
            "customers",
            "a",
            contains_personal_data=True,
            sensitivity_categories=["pii"],
            residency_region="westeurope",
            classification="restricted",
        ),
    )
    await repo.create_entity(
        SCOPE_AB,
        asset(
            "claims",
            "a",
            contains_personal_data=True,
            sensitivity_categories=["phi"],
            residency_region="eastus",
            classification="confidential",
        ),
    )
    await repo.create_entity(
        SCOPE_AB,
        asset(
            "mystery",
            "a",
            contains_personal_data=None,
            sensitivity_categories=None,
            residency_region=None,
            classification="unknown",
        ),
    )
    await repo.create_entity(
        SCOPE_AB,
        asset(
            "public",
            "a",
            contains_personal_data=False,
            sensitivity_categories=[],
            residency_region="eastus",
            classification="public",
        ),
    )
    await repo.create_entity(
        SCOPE_AB,
        asset(
            "ledger",
            "b",
            contains_personal_data=True,
            sensitivity_categories=["pii", "financial"],
            residency_region="northeurope",
            classification="restricted",
        ),
    )
    for name, relation, who, what, domain in (
        ("w-a1-customers", "writes", "a1", "customers", "a"),
        ("r-a2-customers", "reads", "a2", "customers", "a"),
        ("r-b1-customers", "reads", "b1", "customers", "a"),
        ("r-a1-claims", "reads", "a1", "claims", "a"),
        ("w-a2-mystery", "writes", "a2", "mystery", "a"),
        ("w-b2-ledger", "writes", "b2", "ledger", "b"),
    ):
        stored = await repo.put_edge(SCOPE_AB, access_edge(name, relation, who, what, domain), None)
        world.edges[name] = stored
    return world


def make_engine(
    repo: InMemoryCatalogRepository, *, clock: Any = None, **kwargs: Any
) -> AccessEngine:
    graph = RepositoryGraphQuery(repo, StubSearch([]), now=lambda: NOW)
    if clock is not None:
        kwargs["clock"] = clock
    return AccessEngine(repo, graph, now=lambda: NOW, **kwargs)


def scope_of(*domains: str) -> IdentityScope:
    return make_scope(NS, [dom(NS, d) for d in domains])
