"""PRP-18 round 2 item 1: bulk ``edges_among`` parity, scope, budgets and the raw-view refusal."""

from __future__ import annotations

import pytest
from neurosphere_core.catalog.graph import EdgesAmongQuery, RepositoryGraphQuery
from neurosphere_core.catalog.repo import InMemoryCatalogRepository
from neurosphere_core.errors.taxonomy import ForbiddenError

from .graph_helpers import (
    NS,
    FakeClock,
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


def _bulk(query: object) -> RepositoryGraphQuery:
    assert isinstance(query, EdgesAmongQuery)
    assert isinstance(query, RepositoryGraphQuery)
    return query


async def _seed() -> tuple[InMemoryCatalogRepository, list[str]]:
    repo = InMemoryCatalogRepository()
    names = ["n0", "n1", "n2", "n3", "n4", "n5"]
    edges = await seed_chain(repo, SCOPE_A, names)
    await repo.put_override(SCOPE_A, override_for(edges[0], "rej", "reject"))
    await repo.put_override(SCOPE_A, override_for(edges[1], "lck", "lock", set_confidence=1.0))
    # out-of-scope node reachable from n2 and into n3
    await repo.create_entity(make_scope(NS, [dom(NS, "b")]), agent(NS, "x", "b"))
    await repo.put_edge(SCOPE_AB, edge(NS, "n2-x", "n2", "x", "a"), None)
    await repo.put_edge(SCOPE_AB, edge(NS, "x-n3", "x", "n3", "a"), None)
    return repo, names


async def test_parity_with_per_node_walk() -> None:
    repo, names = await _seed()
    query = make_query(repo)
    ids = [nid(n) for n in names]
    bulk = await _bulk(query).edges_among(SCOPE_A, ids, budget(max_nodes=100))
    walked = {}
    for name in names:
        res = await query.neighbors(
            SCOPE_A, neighbors_request(name, direction="out", budget=budget(max_depth=1))
        )
        for e in res.edges:
            if e.source_id in ids and e.target_id in ids:
                walked[e.edge_id] = e
    assert {e.edge_id: e for e in bulk.edges} == walked
    assert bulk.truncated is False
    # n0->n1 rejected (hidden), n1->n2 locked (pinned), x is out of scope; 4 remain
    got = {e.edge_id: e for e in bulk.edges}
    assert len(got) == 4
    assert any(e.pinned for e in got.values())
    assert all(nid("x") not in (e.source_id, e.target_id) for e in bulk.edges)


async def test_wider_scope_includes_the_other_domain_edges() -> None:
    repo, names = await _seed()
    ids = [nid(n) for n in names] + [nid("x")]
    wide = await _bulk(make_query(repo)).edges_among(SCOPE_AB, ids, budget(max_nodes=100))
    pairs = {(e.source_id, e.target_id) for e in wide.edges}
    assert (nid("n2"), nid("x")) in pairs and (nid("x"), nid("n3")) in pairs


async def test_unknown_ids_are_dropped() -> None:
    repo, _names = await _seed()
    res = await _bulk(make_query(repo)).edges_among(
        SCOPE_A, [nid("n2"), nid("n3"), nid("ghost")], budget()
    )
    assert [n.id for n in res.nodes] == [nid("n2"), nid("n3")]
    assert len(res.edges) == 1


async def test_edge_budget_truncates() -> None:
    repo, names = await _seed()
    res = await _bulk(make_query(repo)).edges_among(
        SCOPE_A, [nid(n) for n in names], budget(max_edges=2)
    )
    assert len(res.edges) == 2
    assert res.truncated is True and res.truncated_reason == "max_edges"


async def test_node_budget_truncates() -> None:
    repo, names = await _seed()
    res = await _bulk(make_query(repo)).edges_among(
        SCOPE_A, [nid(n) for n in names], budget(max_nodes=2)
    )
    assert len(res.nodes) == 2
    assert res.truncated_reason == "max_nodes"


async def test_time_budget_truncates() -> None:
    repo, names = await _seed()
    query = make_query(repo, clock=FakeClock(step=1.0))
    res = await _bulk(query).edges_among(SCOPE_A, [nid(n) for n in names], budget(timeout_ms=1500))
    assert res.truncated is True and res.truncated_reason == "timeout_ms"


async def test_raw_view_refused_for_non_auditor() -> None:
    repo, names = await _seed()
    with pytest.raises(ForbiddenError):
        await _bulk(make_query(repo)).edges_among(
            SCOPE_A, [nid(n) for n in names], budget(), view="raw"
        )
