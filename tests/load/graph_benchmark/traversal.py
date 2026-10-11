"""Bounded BFS traversal and its correctness oracle."""

from __future__ import annotations

import time
from collections.abc import Callable

from .model import Budget, PartitionVariant, TraversalResult
from .store import ContainerHandle
from .workloads import Dataset


def bounded_traverse(
    container: ContainerHandle,
    variant: PartitionVariant,
    root: dict[str, object],
    budget: Budget,
    *,
    clock: Callable[[], float] = time.perf_counter,
) -> TraversalResult:
    """BFS from ``root`` (a node doc) honoring depth, per-node fan-out (``budget.limit``),
    node/edge caps and a wall-clock deadline checked before every query.

    Every hop is a single-partition query: the next node's partition values come from the
    edge document's ``dst_*`` fields.
    """
    start = clock()
    deadline = start + budget.timeout_ms / 1000.0
    root_id = str(root["id"])
    res = TraversalResult(root=root_id, nodes=[root_id], node_depth={root_id: 0})
    seen = {root_id}
    frontier: list[tuple[str, tuple[str, ...]]] = [(root_id, variant.values(root))]  # type: ignore[arg-type]
    charge = 0.0
    measured = container.measures_request_charge

    for depth in range(1, budget.max_depth + 1):
        nxt: list[tuple[str, tuple[str, ...]]] = []
        for node_id, pk in frontier:
            if clock() >= deadline:
                res.truncated.add("timeout")
                break
            rows = container.fetch_edges(node_id, pk, budget.limit + 1)
            res.queries += 1
            if measured:
                charge += container.last_request_charge() or 0.0
            if len(rows) > budget.limit:
                res.truncated.add("fanout")
                rows = rows[: budget.limit]
            res.max_fanout_seen = max(res.max_fanout_seen, len(rows))
            for e in rows:
                if budget.max_edges is not None and len(res.edges) >= budget.max_edges:
                    res.truncated.add("max_edges")
                    break
                res.edges.append(e["id"])
                dst = e["dst"]
                if dst in seen:
                    continue
                if budget.max_nodes is not None and len(res.nodes) >= budget.max_nodes:
                    res.truncated.add("max_nodes")
                    continue
                seen.add(dst)
                res.nodes.append(dst)
                res.node_depth[dst] = depth
                res.depth_reached = depth
                nxt.append((dst, variant.values(e, prefix="dst_")))
        if "timeout" in res.truncated:
            break
        frontier = nxt
        if not frontier:
            break
    else:
        if frontier:
            res.truncated.add("depth")
    res.elapsed_ms = (clock() - start) * 1000.0
    res.request_charge = charge if measured else None
    return res


def check_correctness(ds: Dataset, res: TraversalResult, budget: Budget) -> list[str]:
    """Bounded-result correctness. Returns violations (empty list = correct)."""
    bad: list[str] = []
    edge_by_id = {e["id"]: e for e in ds.edges}
    adj = ds.adjacency()
    if len(set(res.nodes)) != len(res.nodes):
        bad.append("duplicate nodes returned")
    if len(set(res.edges)) != len(res.edges):
        bad.append("duplicate edges returned")
    if any(d > budget.max_depth for d in res.node_depth.values()):
        bad.append("depth budget exceeded")
    if budget.max_nodes is not None and len(res.nodes) > budget.max_nodes:
        bad.append("max_nodes budget exceeded")
    if budget.max_edges is not None and len(res.edges) > budget.max_edges:
        bad.append("max_edges budget exceeded")
    if res.max_fanout_seen > budget.limit:
        bad.append("fan-out budget exceeded")
    unknown = [e for e in res.edges if e not in edge_by_id]
    if unknown:
        bad.append(f"{len(unknown)} returned edges not in data set")
    for eid in res.edges:
        e = edge_by_id.get(eid)
        if e and (e["src"] not in res.node_depth):
            bad.append("edge from a node that was never expanded")
            break
    # Reference BFS (unbounded except depth); result must be a subset, equal if untruncated.
    ref = {res.root: 0}
    queue = [res.root]
    while queue:
        cur = queue.pop(0)
        if ref[cur] >= budget.max_depth:
            continue
        for d in adj.get(cur, []):
            if d not in ref:
                ref[d] = ref[cur] + 1
                queue.append(d)
    if not set(res.nodes) <= set(ref):
        bad.append("returned nodes not reachable within depth")
    for n, d in res.node_depth.items():
        if n in ref and d < ref[n]:
            bad.append("node reached shallower than shortest path")
            break
    hard = res.truncated - {"depth"}
    if not hard and set(res.nodes) != set(ref):
        bad.append("untruncated traversal missed reachable nodes")
    return bad
