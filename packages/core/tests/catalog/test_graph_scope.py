"""Graph query scope rules, presented lineage (locks, overrides) and Auditor-only raw view."""

from __future__ import annotations

import pytest
from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope
from neurosphere_core.catalog import EntityFilter, GraphSearchRequest, ImpactRequest
from neurosphere_core.catalog.repo import InMemoryCatalogRepository
from neurosphere_core.errors.taxonomy import ForbiddenError

from .graph_helpers import (
    NS,
    StubSearch,
    agent,
    budget,
    dom,
    edge,
    make_query,
    make_scope,
    neighbors_request,
    nid,
    override_for,
    seed_chain,
)

SCOPE_A = make_scope(NS, [dom(NS, "a")])
SCOPE_AB = make_scope(NS, [dom(NS, "a"), dom(NS, "b")])
SCOPE_B = make_scope(NS, [dom(NS, "b")])


async def test_out_of_scope_intermediate_cuts_the_path() -> None:
    repo = InMemoryCatalogRepository()
    await repo.create_entity(SCOPE_A, agent(NS, "a1", "a"))
    await repo.create_entity(SCOPE_B, agent(NS, "x", "b"))
    await repo.create_entity(SCOPE_A, agent(NS, "b1", "a"))
    await repo.put_edge(SCOPE_AB, edge(NS, "a1-x", "a1", "x", "a"), None)
    await repo.put_edge(SCOPE_AB, edge(NS, "x-b1", "x", "b1", "a"), None)
    query = make_query(repo)

    narrow = await query.impact_paths(SCOPE_A, ImpactRequest(node_id=nid("a1"), budget=budget()))
    assert [n.id for n in narrow.nodes] == [nid("a1")]
    assert narrow.edges == []
    assert narrow.paths == []

    wide = await query.impact_paths(SCOPE_AB, ImpactRequest(node_id=nid("a1"), budget=budget()))
    assert [p.node_ids for p in wide.paths][-1] == [nid("a1"), nid("x"), nid("b1")]

    # an out-of-scope root yields nothing at all
    assert (await query.get(SCOPE_B, nid("a1"))) is None
    empty = await query.neighbors(SCOPE_B, neighbors_request("a1"))
    assert empty.nodes == [] and empty.edges == [] and empty.truncated is False


async def test_presented_lineage_applies_rejects_and_locks() -> None:
    repo = InMemoryCatalogRepository()
    edges = await seed_chain(repo, SCOPE_A, ["p0", "p1", "p2", "p3", "p4"])
    rejected, locked, expired, plain = edges
    await repo.put_override(SCOPE_A, override_for(rejected, "rej", "reject"))
    await repo.put_override(SCOPE_A, override_for(locked, "lck", "lock", set_confidence=1.0))
    await repo.put_override(
        SCOPE_A,
        override_for(expired, "old", "lock", set_confidence=1.0, expiry="2026-10-10T00:00:00Z"),
    )
    query = make_query(repo)
    result = await query.neighbors(SCOPE_A, neighbors_request("p0", direction="out"))
    # p0 -> p1 is rejected: hidden and not traversed, so nothing beyond it is reached
    assert result.edges == []
    assert [n.id for n in result.nodes] == [nid("p0")]

    mid = await query.neighbors(SCOPE_A, neighbors_request("p1", direction="out"))
    by_id = {e.edge_id: e for e in mid.edges}
    pinned = by_id[locked.id]
    assert pinned.pinned is True
    assert pinned.lock.locked is True
    assert pinned.confidence == 1.0
    assert pinned.status == "curated"
    lapsed = by_id[expired.id]
    assert lapsed.pinned is False
    assert lapsed.lock.locked is False
    assert lapsed.confidence == pytest.approx(0.82)  # observed value again
    assert by_id[plain.id].override_ids == []


async def test_raw_view_shows_observed_edges_to_auditors_only() -> None:
    repo = InMemoryCatalogRepository()
    edges = await seed_chain(repo, SCOPE_A, ["r0", "r1", "r2"])
    await repo.put_override(SCOPE_A, override_for(edges[0], "rej", "reject"))
    query = make_query(repo)
    auditor = make_scope(NS, [dom(NS, "a")], auditor_for=[dom(NS, "a")])

    raw = await query.neighbors(auditor, neighbors_request("r0", direction="out", view="raw"))
    assert [e.edge_id for e in raw.edges] == [e.id for e in edges]  # reject not applied
    assert all(e.hidden is False and e.curation is None for e in raw.edges)

    presented = await query.neighbors(auditor, neighbors_request("r0", direction="out"))
    assert presented.edges == []

    with pytest.raises(ForbiddenError):
        await query.neighbors(SCOPE_A, neighbors_request("r0", view="raw"))
    with pytest.raises(ForbiddenError):  # an isolated node must not turn into a silent empty
        await query.neighbors(SCOPE_A, neighbors_request("r2", direction="out", view="raw"))
    with pytest.raises(ForbiddenError):
        await query.impact_paths(
            SCOPE_A, ImpactRequest(node_id=nid("r0"), view="raw", budget=budget())
        )
    other = make_scope(NS, [dom(NS, "a")], auditor_for=[dom(NS, "b")])
    with pytest.raises(ForbiddenError):  # auditor for a different domain
        await query.neighbors(other, neighbors_request("r0", direction="out", view="raw"))


async def test_search_is_rescoped_through_the_repository() -> None:
    repo = InMemoryCatalogRepository()
    await repo.create_entity(SCOPE_A, agent(NS, "s1", "a"))
    await repo.create_entity(SCOPE_B, agent(NS, "hidden", "b"))
    stub = StubSearch([nid("hidden"), nid("s1"), nid("ghost")])
    query = make_query(repo, search=stub)
    result = await query.search(
        SCOPE_A, GraphSearchRequest(term="agent", filters=EntityFilter(), budget=budget())
    )
    assert [n.id for n in result.nodes] == [nid("s1")]  # out-of-scope and missing IDs dropped
    assert result.edges == []
    assert result.truncated is False
    assert isinstance(stub.scopes[0], ContractScope)
    assert stub.scopes[0].customer_id == NS


async def test_search_limits_and_partial_results_are_truncated() -> None:
    repo = InMemoryCatalogRepository()
    for name in ("s1", "s2", "s3"):
        await repo.create_entity(SCOPE_A, agent(NS, name, "a"))
    hits = [nid(n) for n in ("s1", "s2", "s3")]
    query = make_query(repo, search=StubSearch(hits))
    capped = await query.search(
        SCOPE_A, GraphSearchRequest(term="agent", budget=budget(max_nodes=2))
    )
    assert [n.id for n in capped.nodes] == hits[:2]
    assert capped.truncated_reason == "max_nodes"
    partial = make_query(repo, search=StubSearch(hits, partial=True))
    result = await partial.search(SCOPE_A, GraphSearchRequest(term="agent", budget=budget()))
    assert result.truncated is True
    assert len(result.nodes) == 3


async def _seed_visible(repo: InMemoryCatalogRepository) -> None:
    await repo.create_entity(SCOPE_A, agent(NS, "v1", "a"))
    await repo.create_entity(SCOPE_A, agent(NS, "v2", "a"))
    await repo.put_edge(SCOPE_A, edge(NS, "v1-v2", "v1", "v2", "a"), None)


async def _seed_hidden_extras(repo: InMemoryCatalogRepository) -> None:
    await repo.create_entity(SCOPE_B, agent(NS, "hx1", "b"))
    await repo.create_entity(SCOPE_B, agent(NS, "hx2", "b"))
    await repo.create_entity(SCOPE_A, agent(NS, "v3", "a"))
    for name, src, dst in (("v1-hx1", "v1", "hx1"), ("hx2-v1", "hx2", "v1")):
        await repo.put_edge(SCOPE_AB, edge(NS, name, src, dst, "a"), None)
    rejected = await repo.put_edge(SCOPE_A, edge(NS, "v1-v3", "v1", "v3", "a"), None)
    await repo.put_override(SCOPE_A, override_for(rejected, "rej-v3", "reject"))


async def test_result_counts_do_not_leak_hidden_neighbours_or_edges() -> None:
    plain = InMemoryCatalogRepository()
    extra = InMemoryCatalogRepository()
    await _seed_visible(plain)
    await _seed_visible(extra)
    await _seed_hidden_extras(extra)

    for direction in ("out", "in", "both"):
        base = await make_query(plain).neighbors(
            SCOPE_A, neighbors_request("v1", direction=direction)
        )
        more = await make_query(extra).neighbors(
            SCOPE_A, neighbors_request("v1", direction=direction)
        )
        assert more.visited_nodes == base.visited_nodes == len(base.nodes)
        assert more.visited_edges == base.visited_edges == len(base.edges)
        assert more.truncated == base.truncated
        assert more.truncated_reason == base.truncated_reason
        assert [n.id for n in more.nodes] == [n.id for n in base.nodes]
        assert [e.edge_id for e in more.edges] == [e.edge_id for e in base.edges]

    base_impact = await make_query(plain).impact_paths(
        SCOPE_A, ImpactRequest(node_id=nid("v1"), budget=budget())
    )
    more_impact = await make_query(extra).impact_paths(
        SCOPE_A, ImpactRequest(node_id=nid("v1"), budget=budget())
    )
    assert more_impact.visited_nodes == base_impact.visited_nodes == len(base_impact.nodes)
    assert more_impact.visited_edges == base_impact.visited_edges == len(base_impact.edges)
    assert more_impact.truncated == base_impact.truncated
    assert more_impact.truncated_reason == base_impact.truncated_reason
    assert [p.node_ids for p in more_impact.paths] == [p.node_ids for p in base_impact.paths]
