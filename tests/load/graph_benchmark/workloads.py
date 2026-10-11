"""Deterministic adjacency data sets for the three G03 workloads.

(a) skewed     - one hot domain holds ``skew_factor`` of all nodes.
(b) high_degree - one hub node with ``hub_degree`` outgoing edges.
(c) cross_domain - every edge crosses a domain (and often a tenant) boundary.

Documents: ``doc_type`` is ``node`` or ``edge``. An edge lives in the partition of its
source node; ``dst_*`` fields carry the destination partition values so a traversal can
address the next hop as a single-partition query.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

WORKLOADS = ("skewed", "high_degree", "cross_domain")
_TENANTS = ("tenant-a", "tenant-b")
_SHARDS = 4


@dataclass
class Dataset:
    workload: str
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    roots: list[str]
    params: dict[str, Any] = field(default_factory=dict)

    def adjacency(self) -> dict[str, list[str]]:
        adj: dict[str, list[str]] = {}
        for e in self.edges:
            adj.setdefault(e["src"], []).append(e["dst"])
        return adj


def _node(i: int, domain_idx: int) -> dict[str, Any]:
    return {
        "id": f"n-{i}",
        "doc_type": "node",
        "name": f"node-{i}",
        "tenant": _TENANTS[domain_idx % len(_TENANTS)],
        "domain": f"domain-{domain_idx}",
        "shard": f"s{i % _SHARDS}",
    }


def _edge(src: dict[str, Any], dst: dict[str, Any], seq: int) -> dict[str, Any]:
    return {
        "id": f"e-{src['id']}-{dst['id']}",
        "doc_type": "edge",
        "rel": "depends_on",
        "seq": seq,
        "src": src["id"],
        "dst": dst["id"],
        "tenant": src["tenant"],
        "domain": src["domain"],
        "shard": src["shard"],
        "dst_tenant": dst["tenant"],
        "dst_domain": dst["domain"],
        "dst_shard": dst["shard"],
    }


def _wire(
    nodes: list[dict[str, Any]],
    pick: Any,
    edges_per_node: int,
    extra: list[tuple[int, int]] | None = None,
) -> list[dict[str, Any]]:
    seen: set[tuple[int, int]] = set()
    edges: list[dict[str, Any]] = []
    for s, d in extra or []:
        seen.add((s, d))
        edges.append(_edge(nodes[s], nodes[d], len(edges)))
    for s in range(len(nodes)):
        for _ in range(edges_per_node):
            d = pick(s)
            if d == s or (s, d) in seen:
                continue
            seen.add((s, d))
            edges.append(_edge(nodes[s], nodes[d], len(edges)))
    return edges


def generate(
    workload: str,
    *,
    nodes: int = 300,
    edges_per_node: int = 3,
    domains: int = 8,
    skew_factor: float = 0.8,
    hub_degree: int = 200,
    seed: int = 42,
    roots: int = 10,
) -> Dataset:
    if workload not in WORKLOADS:
        raise ValueError(f"unknown workload {workload!r}; expected one of {WORKLOADS}")
    if nodes < 4 or domains < 2 or not 0.0 < skew_factor < 1.0:
        raise ValueError("need nodes>=4, domains>=2, 0<skew_factor<1")
    rng = random.Random(f"{workload}:{seed}")
    params: dict[str, Any] = {
        "nodes": nodes,
        "edges_per_node": edges_per_node,
        "domains": domains,
        "seed": seed,
    }
    if workload == "skewed":
        hot = max(1, int(nodes * skew_factor))
        dom = [0 if i < hot else 1 + rng.randrange(domains - 1) for i in range(nodes)]
        docs = [_node(i, dom[i]) for i in range(nodes)]
        by_dom: dict[int, list[int]] = {}
        for i, d in enumerate(dom):
            by_dom.setdefault(d, []).append(i)

        def pick(s: int) -> int:
            if rng.random() < 0.9:
                return rng.choice(by_dom[dom[s]])
            return rng.randrange(nodes)

        edges = _wire(docs, pick, edges_per_node)
        root_ids = [docs[i]["id"] for i in rng.sample(range(hot), min(roots, hot))]
        params |= {"skew_factor": skew_factor, "hot_domain_nodes": hot}
    elif workload == "high_degree":
        dom = [i % domains for i in range(nodes)]
        docs = [_node(i, dom[i]) for i in range(nodes)]
        degree = min(hub_degree, nodes - 1)
        hub_edges = [(0, d) for d in range(1, degree + 1)]
        edges = _wire(docs, lambda _s: rng.randrange(nodes), edges_per_node, extra=hub_edges)
        root_ids = [docs[0]["id"]]
        params |= {"hub_degree": degree, "hub": docs[0]["id"]}
    else:  # cross_domain
        dom = [i % domains for i in range(nodes)]
        docs = [_node(i, dom[i]) for i in range(nodes)]

        def pick(s: int) -> int:
            while True:
                d = rng.randrange(nodes)
                if dom[d] != dom[s]:
                    return d

        edges = _wire(docs, pick, edges_per_node)
        root_ids = [docs[i]["id"] for i in rng.sample(range(nodes), min(roots, nodes))]
        params["cross_domain_edge_ratio"] = 1.0
    return Dataset(workload, docs, edges, root_ids, params)
