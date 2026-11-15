"""PRP-18 round 2 item 4: the viewport uses one bulk edges-among call, with a per-node fallback."""

import time
from typing import Any

from map_api_helpers import (  # pyright: ignore[reportMissingImports]
    ALICE,
    FINANCE,
    Api,
    agent_doc,
    agent_id,
    make_api,
    make_edge,
)
from neurosphere_core.catalog.graph import EdgesAmongQuery

NODES = 2000
EDGES = 4000
TIME_BOUND_SECONDS = 3.0  # ASSUMPTION A-1: regression guard, not a promise (round 1: about 15 s)


class _Spy:
    """Delegates to the real graph and counts calls; has no ``edges_among``."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.bulk_calls = 0
        self.neighbor_calls = 0

    async def get(self, scope: Any, node_id: str) -> Any:
        return await self._inner.get(scope, node_id)

    async def search(self, scope: Any, request: Any) -> Any:
        return await self._inner.search(scope, request)

    async def neighbors(self, scope: Any, request: Any) -> Any:
        self.neighbor_calls += 1
        return await self._inner.neighbors(scope, request)

    async def impact_paths(self, scope: Any, request: Any) -> Any:
        return await self._inner.impact_paths(scope, request)


class _BulkSpy(_Spy):
    """Same spy, plus the bulk method."""

    async def edges_among(
        self, scope: Any, node_ids: Any, budget: Any, view: str = "presented"
    ) -> Any:
        self.bulk_calls += 1
        return await self._inner.edges_among(scope, node_ids, budget, view)


def _seed(api: Api, nodes: int, edges: int) -> None:
    api.seed(*[agent_doc(f"a{i:05d}") for i in range(nodes)])
    made = []
    for i in range(edges):
        src, dst = i % nodes, (i * 7 + 1) % nodes
        if src == dst:
            dst = (dst + 1) % nodes
        made.append(make_edge(f"e{i:05d}", agent_id(f"a{src:05d}"), agent_id(f"a{dst:05d}")))
    api.seed_edges(*made)


def _wrap(api: Api, cls: type[_Spy]) -> _Spy:
    spy = cls(api.h.app.state.catalog_graph)
    api.h.app.state.catalog_graph = spy
    return spy


def test_real_graph_satisfies_the_bulk_protocol() -> None:
    api = make_api()
    api.seed(*[agent_doc("a00000")])
    assert isinstance(api.h.app.state.catalog_graph, EdgesAmongQuery)


def test_2000_node_page_uses_one_bulk_call_and_is_fast() -> None:
    api = make_api()
    api.limits(max_nodes=NODES, max_edges=5000)
    _seed(api, NODES, EDGES)
    spy = _wrap(api, _BulkSpy)
    # The bound is on this process's CPU time, not wall time: the work is in-memory, and a
    # wall-clock bound failed on a loaded machine (3.1 to 5.6 s during a parallel build) with
    # no regression in the code. Wall time is still printed for the record.
    started = time.perf_counter()
    cpu_started = time.process_time()
    response = api.get(ALICE, FINANCE, node_budget=NODES, edge_budget=5000)
    cpu_elapsed = time.process_time() - cpu_started
    elapsed = time.perf_counter() - started
    print(f"2000-node viewport page: {elapsed:.2f} s wall, {cpu_elapsed:.2f} s CPU")  # A-1
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["nodes"]) == NODES
    assert len(body["edges"]) == EDGES
    assert body["truncated"] is False
    assert spy.bulk_calls == 1
    assert spy.neighbor_calls == 0
    assert cpu_elapsed < TIME_BOUND_SECONDS


def test_graph_without_the_bulk_method_falls_back_to_the_walk() -> None:
    api = make_api()
    _seed(api, 12, 20)
    spy = _wrap(api, _Spy)
    assert not isinstance(spy, EdgesAmongQuery)
    body = api.get(ALICE, FINANCE).json()
    assert len(body["edges"]) == 20
    assert spy.neighbor_calls == 12


def test_bulk_and_fallback_return_the_same_edge_set() -> None:
    bulk_api, walk_api = make_api(), make_api()
    for api in (bulk_api, walk_api):
        _seed(api, 15, 30)
    _wrap(walk_api, _Spy)
    first = bulk_api.get(ALICE, FINANCE)
    assert first.status_code == 200, first.text
    bulk = first.json()
    second = walk_api.get(ALICE, FINANCE)
    assert second.status_code == 200, second.text
    walked = second.json()
    assert {e["id"] for e in bulk["edges"]} == {e["id"] for e in walked["edges"]}
    assert len(bulk["edges"]) == 30


def test_edge_budget_flag_is_unchanged_on_the_bulk_path() -> None:
    api = make_api()
    _seed(api, 10, 20)
    body = api.get(ALICE, FINANCE, edge_budget=5).json()
    assert len(body["edges"]) == 5
    assert body["truncated"] is True
    assert body["truncation_reason"] == "edge_budget"
