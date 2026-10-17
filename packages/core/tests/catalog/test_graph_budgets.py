"""Graph traversal budgets: every dimension truncates, a hub never causes an unbounded walk."""

from __future__ import annotations

from neurosphere_core.catalog import GraphQuery, ImpactRequest
from neurosphere_core.catalog.repo import InMemoryCatalogRepository

from .graph_helpers import (
    NS,
    CountingRepo,
    FakeClock,
    agent,
    budget,
    dom,
    edge,
    make_query,
    make_scope,
    neighbors_request,
    nid,
    seed_chain,
)

NAMES = ["n0", "n1", "n2", "n3", "n4", "n5"]


async def _chain() -> tuple[InMemoryCatalogRepository, GraphQuery, object]:
    repo = InMemoryCatalogRepository()
    scope = make_scope(NS, [dom(NS, "a")])
    await seed_chain(repo, scope, NAMES)
    return repo, make_query(repo), scope


async def test_untruncated_walk_is_complete() -> None:
    _, query, scope = await _chain()
    result = await query.neighbors(scope, neighbors_request("n0", direction="out"))  # type: ignore[arg-type]
    assert [n.id for n in result.nodes] == [nid(n) for n in NAMES]
    assert len(result.edges) == 5
    assert result.truncated is False
    assert result.truncated_reason is None


async def test_depth_budget_truncates() -> None:
    _, query, scope = await _chain()
    request = neighbors_request("n0", direction="out", budget=budget(max_depth=2))
    result = await query.neighbors(scope, request)  # type: ignore[arg-type]
    assert [n.id for n in result.nodes] == [nid(n) for n in NAMES[:3]]
    assert result.truncated is True
    assert result.truncated_reason == "max_depth"


async def test_node_budget_truncates() -> None:
    _, query, scope = await _chain()
    request = neighbors_request("n0", direction="out", budget=budget(max_nodes=3))
    result = await query.neighbors(scope, request)  # type: ignore[arg-type]
    assert len(result.nodes) == 3
    assert result.truncated is True
    assert result.truncated_reason == "max_nodes"
    # no dangling edges: every edge connects two returned nodes
    ids = {n.id for n in result.nodes}
    assert all(e.source_id in ids and e.target_id in ids for e in result.edges)


async def test_edge_budget_truncates() -> None:
    _, query, scope = await _chain()
    request = neighbors_request("n0", direction="out", budget=budget(max_edges=2))
    result = await query.neighbors(scope, request)  # type: ignore[arg-type]
    assert len(result.edges) == 2
    assert result.truncated is True
    assert result.truncated_reason == "max_edges"


async def test_time_budget_truncates() -> None:
    repo = InMemoryCatalogRepository()
    scope = make_scope(NS, [dom(NS, "a")])
    await seed_chain(repo, scope, NAMES)
    query = make_query(repo, clock=FakeClock(step=1.0))  # every clock read costs one second
    request = neighbors_request("n0", direction="out", budget=budget(timeout_ms=2500))
    result = await query.neighbors(scope, request)
    assert result.truncated is True
    assert result.truncated_reason == "timeout_ms"
    assert len(result.nodes) < len(NAMES)


async def test_hub_fanout_is_capped_per_node() -> None:
    inner = InMemoryCatalogRepository()
    scope = make_scope(NS, [dom(NS, "a")])
    spokes = [f"s{i:02d}" for i in range(40)]
    await inner.create_entity(scope, agent(NS, "hub", "a"))
    for s in spokes:
        await inner.create_entity(scope, agent(NS, s, "a"))
        await inner.put_edge(scope, edge(NS, f"hub-{s}", "hub", s, "a"), None)
        # each spoke has its own tail, which must not be reached past the cap
        await inner.create_entity(scope, agent(NS, f"{s}x", "a"))
        await inner.put_edge(scope, edge(NS, f"{s}-{s}x", s, f"{s}x", "a"), None)
    repo = CountingRepo(inner)
    query = make_query(repo)  # type: ignore[arg-type]
    request = neighbors_request("hub", direction="out", budget=budget(limit=5, max_depth=2))
    result = await query.neighbors(scope, request)
    assert result.truncated is True
    assert result.truncated_reason == "max_edges"
    hub_edges = [e for e in result.edges if e.source_id == nid("hub")]
    assert len(hub_edges) == 5
    # 1 hub page + 5 spoke pages + 5 depth probes; every page asks for at most limit + 1 rows
    assert len(repo.edge_pages) == 11
    assert max(repo.edge_pages) == 6
    assert len(result.nodes) <= 1 + 5 + 5


async def test_deterministic_ordering() -> None:
    inner = InMemoryCatalogRepository()
    scope = make_scope(NS, [dom(NS, "a")])
    await inner.create_entity(scope, agent(NS, "root", "a"))
    for s in ("zeta", "alpha", "mid"):
        await inner.create_entity(scope, agent(NS, s, "a"))
        await inner.put_edge(scope, edge(NS, f"root-{s}", "root", s, "a"), None)
    query = make_query(inner)
    first = await query.impact_paths(
        scope,
        ImpactRequest(node_id=nid("root"), budget=budget()),
    )
    second = await query.impact_paths(
        scope,
        ImpactRequest(node_id=nid("root"), budget=budget()),
    )
    assert first.model_dump() == second.model_dump()
    assert [n.id for n in first.nodes][1:] == [nid(n) for n in ("alpha", "mid", "zeta")]


async def test_impact_paths_are_root_to_node_and_bounded() -> None:
    _, query, scope = await _chain()
    result = await query.impact_paths(
        scope,  # type: ignore[arg-type]
        ImpactRequest(node_id=nid("n0"), budget=budget(max_depth=3)),
    )
    assert [p.node_ids[-1] for p in result.paths] == [nid(n) for n in NAMES[1:4]]
    deepest = result.paths[-1]
    assert deepest.node_ids == [nid(n) for n in NAMES[:4]]
    assert len(deepest.edge_ids) == 3
    assert result.truncated_reason == "max_depth"
    upstream = await query.impact_paths(
        scope,  # type: ignore[arg-type]
        ImpactRequest(node_id=nid("n5"), direction="upstream", budget=budget()),
    )
    assert [p.node_ids[-1] for p in upstream.paths] == [nid(n) for n in reversed(NAMES[:5])]
