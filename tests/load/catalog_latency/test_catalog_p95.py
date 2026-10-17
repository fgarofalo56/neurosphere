"""Catalog read latency over the sandbox dataset (PRP-10 item 5): MEASURED, never asserted.

What this is: wall-clock p50/p95/max of scoped catalog reads (entity get, filtered list, search,
neighbors, impact paths) against the IN-MEMORY repository loaded from the ``sandbox/`` generator
(custom profile: 8 domains, 200 agents), through the same ``CatalogRepository`` and
``GraphQuery`` the API uses. The in-memory backend scans documents (no index), so the numbers
say nothing about Cosmos NoSQL or Azure AI Search.

What this is not: a performance claim. The PRP-10 target (p95 <= 500 ms on indexed scoped
queries) is only evidenced by the live gate against a real account (G03). This test records the
numbers so a regression in the query layer is visible, prints them, and writes
``temp/catalog_latency/p95.json`` (gitignored) labelled "in-memory, bounded feasibility, not a
live claim". It asserts correctness (every result is inside the caller's scope) and that the
measurement was recorded, not any latency threshold.

Size knobs for a bigger local run: ``NS_CATALOG_LATENCY_ITERATIONS`` (default 60).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import sys
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from neurosphere_contracts.query.v1.budget import Budget
from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope
from neurosphere_core.catalog import (
    CatalogRepository,
    EdgeFilter,
    EntityFilter,
    GraphSearchRequest,
    ImpactRequest,
    NeighborsRequest,
)
from neurosphere_core.catalog.graph import RepositoryGraphQuery
from neurosphere_core.catalog.repo import InMemoryCatalogRepository
from neurosphere_core.catalog.repo.documents import parse_edge, parse_entity
from neurosphere_core.errors import InvalidSchemaError
from neurosphere_core.paging import PageRequest
from neurosphere_core.scope import IdentityScope
from neurosphere_core.search.fixture import FixtureSearchIndex, documents_from_catalog

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:  # the generator is a top-level package, not a workspace member
    sys.path.insert(0, str(ROOT))

from sandbox import catalog as sandbox_catalog  # noqa: E402
from sandbox.config import PROFILES, GenerateConfig, with_overrides  # noqa: E402
from sandbox.world import World  # noqa: E402

LABEL = "in-memory, bounded feasibility, not a live claim"
TARGET_MS = 500.0  # PRP-10 target, recorded for context only; never asserted here
ITERATIONS = int(os.environ.get("NS_CATALOG_LATENCY_ITERATIONS", "60"))
RESULT_PATH = Path(__file__).resolve().parents[3] / "temp" / "catalog_latency" / "p95.json"
QUERY_DOMAINS = 3
SEARCH_TERMS = ("review", "router", "classifier", "planner", "operations")


def _scope(world: World, domains: list[str]) -> IdentityScope:
    payload: dict[str, Any] = {
        "schema_version": "1.0.0",
        "cloud": world.cloud,
        "customer_id": world.customer,
        "principal": {
            "principal_id": f"{world.cloud}:{world.customer}:idp:person:p1",
            "principal_pseudonym": "p-0001",
            "principal_kind": "user",
        },
        "roles": [{"role": "viewer", "domain_ids": domains}],
        "allowed_domains": domains,
        "allowed_resources": [],
        "policy_version": "v1",
        "derived_at": "2026-01-01T00:00:00Z",
        "scope_hash": "sha256:" + hashlib.sha256(b"catalog-latency").hexdigest(),
    }
    return IdentityScope._from_verified_contract(ContractScope.model_validate(payload))


def _percentile(sorted_ms: list[float], pct: float) -> float:
    rank = max(1, math.ceil(pct / 100.0 * len(sorted_ms)))
    return sorted_ms[rank - 1]


async def _load(
    repo: CatalogRepository, scope: IdentityScope, world: World
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Load the sandbox catalog; return the entity documents and what was loaded."""
    entities: list[dict[str, Any]] = []
    counts = {"entities": 0, "edges": 0, "skipped_without_domain": 0}
    for fn in (
        sandbox_catalog.iter_domains,
        sandbox_catalog.iter_owners,
        sandbox_catalog.iter_models,
        sandbox_catalog.iter_sources,
        sandbox_catalog.iter_tools,
        sandbox_catalog.iter_agents,
    ):
        for doc in fn(world):
            try:
                await repo.create_entity(scope, parse_entity(doc))
            except InvalidSchemaError:
                counts["skipped_without_domain"] += 1
                continue
            entities.append(doc)
            counts["entities"] += 1
    for doc in sandbox_catalog.iter_relations(world):
        try:
            await repo.put_edge(scope, parse_edge(doc), None)
        except InvalidSchemaError:
            continue
        counts["edges"] += 1
    return entities, counts


async def _time(
    name: str, calls: list[Callable[[], Awaitable[None]]], out: dict[str, dict[str, float]]
) -> None:
    samples: list[float] = []
    for index in range(ITERATIONS):
        call = calls[index % len(calls)]
        started = time.perf_counter()
        await call()
        samples.append((time.perf_counter() - started) * 1000.0)
    ordered = sorted(samples)
    out[name] = {
        "samples": float(len(ordered)),
        "p50_ms": round(_percentile(ordered, 50), 3),
        "p95_ms": round(_percentile(ordered, 95), 3),
        "max_ms": round(ordered[-1], 3),
    }


async def _measure() -> dict[str, Any]:
    profile = with_overrides(PROFILES["custom"], domains=8, agents=200)
    world = World(GenerateConfig(seed=7, profile=profile, cloud="commercial"))
    all_domains = [world.domain_id(i) for i in range(len(world.domains))]
    repo = InMemoryCatalogRepository()
    entities, loaded = await _load(repo, _scope(world, all_domains), world)

    allowed = all_domains[:QUERY_DOMAINS]
    scope = _scope(world, allowed)
    graph = RepositoryGraphQuery(repo, FixtureSearchIndex(documents_from_catalog(entities)))
    visible = [
        e["id"] for e in entities if e["entity_type"] == "agent" and e["domain_id"] in allowed
    ]
    assert visible, "the scoped caller must see some agents"
    budget = Budget(timeout_ms=5000, limit=50, max_depth=3)
    violations: list[str] = []
    search_nodes: list[int] = []

    async def get_one(i: int) -> None:
        found = await repo.get_entity(scope, visible[i % len(visible)])
        assert found is not None

    async def list_scoped(i: int) -> None:
        flt = EntityFilter(entity_types=["agent"], domain_ids=[allowed[i % QUERY_DOMAINS]])
        page = await repo.list_entities(scope, flt, PageRequest(page_size=100))
        violations.extend(
            e.id
            for e in page.items
            if getattr(e, "domain_id").root not in allowed  # noqa: B009
        )

    async def search(i: int) -> None:
        result = await graph.search(
            scope,
            GraphSearchRequest(
                term=SEARCH_TERMS[i % len(SEARCH_TERMS)], filters=EntityFilter(), budget=budget
            ),
        )
        search_nodes.append(len(result.nodes))
        violations.extend(
            n.id
            for n in result.nodes
            if getattr(n, "domain_id").root not in allowed  # noqa: B009
        )

    async def neighbors(i: int) -> None:
        result = await graph.neighbors(
            scope,
            NeighborsRequest(
                node_id=visible[i % len(visible)], filters=EdgeFilter(), budget=budget
            ),
        )
        violations.extend(e.edge_id for e in result.edges if e.domain_id not in allowed)

    async def impact(i: int) -> None:
        await graph.impact_paths(
            scope, ImpactRequest(node_id=visible[i % len(visible)], budget=budget)
        )

    workloads: dict[str, Callable[[int], Awaitable[None]]] = {
        "get_entity": get_one,
        "list_entities_scoped": list_scoped,
        "search": search,
        "neighbors_depth3": neighbors,
        "impact_paths_depth3": impact,
    }
    measured: dict[str, dict[str, float]] = {}
    for name, fn in workloads.items():
        await _time(name, [lambda i=i, fn=fn: fn(i) for i in range(max(1, len(visible)))], measured)
    return {
        "label": LABEL,
        "target_ms_for_context_only": TARGET_MS,
        "disclaimer": (
            "Measured against the in-memory repository (no index, no network). This is not "
            "evidence for the PRP-10 p95 target; the live gate G03 is still required."
        ),
        "dataset": {
            "generator": "sandbox",
            "profile": "custom",
            "domains": len(all_domains),
            "agents": profile.agents,
            "query_domains": QUERY_DOMAINS,
            **loaded,
        },
        "iterations_per_workload": ITERATIONS,
        "p95_ms_by_workload": {k: v["p95_ms"] for k, v in measured.items()},
        "workloads": measured,
        "search_nodes_returned_total": sum(search_nodes),
        "scope_violations": violations,
    }


def test_scoped_read_latency_is_measured_and_recorded() -> None:
    result = asyncio.run(_measure())

    assert result["scope_violations"] == []
    assert result["search_nodes_returned_total"] > 0, "search must return something to time"
    assert result["label"] == LABEL
    assert set(result["p95_ms_by_workload"]) == {
        "get_entity",
        "list_entities_scoped",
        "search",
        "neighbors_depth3",
        "impact_paths_depth3",
    }
    assert all(v > 0 for v in result["p95_ms_by_workload"].values())

    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"\ncatalog latency ({LABEL}); target {TARGET_MS} ms is NOT asserted")
    for name, stats in result["workloads"].items():
        print(
            f"  {name:24s} p50={stats['p50_ms']:9.3f} ms  p95={stats['p95_ms']:9.3f} ms  "
            f"max={stats['max_ms']:9.3f} ms  n={int(stats['samples'])}"
        )
    print(f"  recorded: {RESULT_PATH}")
    assert RESULT_PATH.is_file()
