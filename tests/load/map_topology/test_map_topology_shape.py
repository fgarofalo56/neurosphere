"""Live-map shape check over an in-memory 50k-entity world (PRP-74 item 5). CI-safe.

Asserts response shapes, bounds and truncation labels. It asserts NO time target: wall times of
the in-memory backend say nothing about Cosmos and are only printed. The local emulator timings
live in ``run_emulator.py`` and ``docs/evidence/G07/map/server-timings.json``.
"""

import time
from typing import Any

from neurosphere_api.map.settings import MapSettings
from neurosphere_api.map.topology import TopologySource
from neurosphere_core.catalog.repo import InMemoryCatalogRepository

from .world import (
    IMPACT_AGENTS,
    PERF_DOMAIN,
    ROOT_SERVICE,
    background_docs,
    background_edges,
    build_api,
    impact_docs,
    impact_edges,
    load_world,
)

ENTITIES = 50_000
NODE_CEILING = 2000
EDGE_CEILING = 5000
REASONS = {"node_budget", "edge_budget", "scan_limit", "traversal_incomplete", "timeout_ms"}


def _label_consistent(body: dict[str, Any]) -> None:
    """A truncated response names a reason; a complete one does not."""
    if body["truncated"]:
        assert body["truncation_reason"] in REASONS, body["truncation_reason"]
    else:
        assert body["truncation_reason"] is None


async def test_shapes_bounds_and_truncation_labels_over_a_50k_world() -> None:
    repo = InMemoryCatalogRepository()
    perf = await build_api(repo)
    background = ENTITIES - IMPACT_AGENTS - 1
    docs = background_docs(background) + impact_docs()
    edges = background_edges(background) + impact_edges()
    assert len(docs) == ENTITIES
    await load_world(perf, docs, edges)
    timings: dict[str, float] = {}

    # Viewport, unclustered entry: too many nodes, so clusters come back (never 50k nodes).
    start = time.perf_counter()
    response = await perf.get("viewport", node_budget=10_000_000, edge_budget=10_000_000)
    timings["viewport_clusters"] = time.perf_counter() - start
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["nodes"]) <= NODE_CEILING
    assert len(body["edges"]) <= EDGE_CEILING
    assert {n["kind"] for n in body["nodes"]} == {"cluster"}
    assert all(n["member_count"] and n["member_count"] > 0 for n in body["nodes"])
    assert body["truncated"] is True
    assert body["truncation_reason"] in {"node_budget", "scan_limit"}
    _label_consistent(body)

    # Viewport, one 2000-node page of a cluster: bounded, edges only among returned nodes.
    start = time.perf_counter()
    response = await perf.get(
        "viewport", cluster_id="kind:agent", node_budget=NODE_CEILING, edge_budget=EDGE_CEILING
    )
    timings["viewport_2000_nodes"] = time.perf_counter() - start
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["nodes"]) == NODE_CEILING
    assert len(body["edges"]) <= EDGE_CEILING
    ids = {n["id"] for n in body["nodes"]}
    assert len(ids) == len(body["nodes"]), "duplicate node ids on one page"
    assert all(e["source"] in ids and e["target"] in ids for e in body["edges"])
    assert body["next_cursor"] is not None
    assert body["truncated"] is True
    assert body["truncation_reason"] == "node_budget"
    assert body["coverage"]["state"]

    # Search: at most `limit` matches, counts sum to one total, truncation is labelled.
    start = time.perf_counter()
    response = await perf.get("search", q="w0", limit=50)
    timings["search"] = time.perf_counter() - start
    assert response.status_code == 200, response.text
    body = response.json()
    assert 0 < len(body["matches"]) <= 50
    counts = body["counts"]
    total = sum(counts["by_kind"].values())
    assert total >= len(body["matches"])
    assert sum(counts["by_health"].values()) == total
    assert sum(counts["by_environment"].values()) == total
    assert all(m["node"]["label"] for m in body["matches"])
    _label_consistent(body)

    # Impact at depth 5: levels ascend from 1, stay within the depth, no node repeats.
    start = time.perf_counter()
    response = await perf.post_impact(ROOT_SERVICE, 5)
    timings["impact_depth_5"] = time.perf_counter() - start
    assert response.status_code == 200, response.text
    body = response.json()
    depths = [lv["depth"] for lv in body["levels"]]
    assert depths == sorted(set(depths))
    assert all(1 <= d <= 5 for d in depths)
    listed = [n["id"] for lv in body["levels"] for n in lv["nodes"]]
    assert len(listed) == len(set(listed)), "a dependent was listed twice"
    assert len(listed) <= IMPACT_AGENTS
    assert body["node_id"] == ROOT_SERVICE
    _label_consistent(body)
    if len(listed) < IMPACT_AGENTS:
        assert body["truncated"] is True, "fewer dependents than the tree has, but not labelled"

    # One topology poll: a scoped snapshot, bounded by the scan pages, with a fingerprint.
    source = TopologySource(repo, MapSettings(), clock=time.monotonic)
    start = time.perf_counter()
    snapshot = await source.snapshot(perf.reader, PERF_DOMAIN)
    timings["topology_poll"] = time.perf_counter() - start
    assert 0 < snapshot.node_count <= ENTITIES
    assert snapshot.edge_count <= len(edges)
    assert snapshot.fingerprint
    assert source.cache_size == 1

    await perf.client.aclose()
    print("in-memory wall seconds (not asserted):", {k: round(v, 2) for k, v in timings.items()})
