"""Shared loader and measurement for the catalog latency runs (PRP-10 items 5 and 13).

MEASURED, never asserted: nothing here compares a latency to a threshold. The same scoped
workloads run over any ``CatalogRepository`` (in-memory, Cosmos vNext emulator, or a live
account); each backend's test supplies the repository and the label.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sys
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from neurosphere_contracts.query.v1.budget import Budget
from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope
from neurosphere_core.audit import AuditRepository, InMemoryAuditStore
from neurosphere_core.catalog import (
    CatalogRepository,
    EdgeFilter,
    EntityFilter,
    GraphSearchRequest,
    ImpactRequest,
    NeighborsRequest,
)
from neurosphere_core.catalog.graph import RepositoryGraphQuery
from neurosphere_core.catalog.repo.documents import parse_edge, parse_entity
from neurosphere_core.errors import InvalidSchemaError
from neurosphere_core.paging import PageRequest
from neurosphere_core.scope import IdentityScope
from neurosphere_core.search.fixture import FixtureSearchIndex, documents_from_catalog

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:  # the generator is a top-level package, not a workspace member
    sys.path.insert(0, str(ROOT))

from neurosphere_api.catalog.service import CatalogService  # noqa: E402

from sandbox import catalog as sandbox_catalog  # noqa: E402
from sandbox.config import PROFILES, GenerateConfig, with_overrides  # noqa: E402
from sandbox.world import World  # noqa: E402

TARGET_MS = 500.0  # PRP-10 target, recorded for context only; never asserted
ITERATIONS = int(os.environ.get("NS_CATALOG_LATENCY_ITERATIONS", "60"))
RESULT_DIR = ROOT / "temp" / "catalog_latency"
QUERY_DOMAINS = 3
SEARCH_TERMS = ("review", "router", "classifier", "planner", "operations")
WORKLOAD_NAMES = (
    "get_entity",
    "list_entities_scoped",
    "export_page_scoped",
    "search",
    "neighbors_depth3",
    "impact_paths_depth3",
)


def make_world() -> tuple[World, list[str], int]:
    profile = with_overrides(PROFILES["custom"], domains=8, agents=200)
    world = World(GenerateConfig(seed=7, profile=profile, cloud="commercial"))
    return world, [world.domain_id(i) for i in range(len(world.domains))], profile.agents


def make_scope(world: World, domains: list[str]) -> IdentityScope:
    """Analyst over ``domains`` (holds ``data.export``, so the export path is reachable)."""
    payload: dict[str, Any] = {
        "schema_version": "1.0.0",
        "cloud": world.cloud,
        "customer_id": world.customer,
        "principal": {
            "principal_id": f"{world.cloud}:{world.customer}:idp:person:p1",
            "principal_pseudonym": "p-0001",
            "principal_kind": "user",
        },
        "roles": [{"role": "analyst", "domain_ids": domains}],
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


async def load_catalog(
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


async def measure(
    repo: CatalogRepository,
    world: World,
    all_domains: list[str],
    agents: int,
    *,
    label: str,
    disclaimer: str,
) -> dict[str, Any]:
    """Load the sandbox profile into ``repo`` and time every scoped workload."""
    entities, loaded = await load_catalog(repo, make_scope(world, all_domains), world)

    allowed = all_domains[:QUERY_DOMAINS]
    scope = make_scope(world, allowed)
    graph = RepositoryGraphQuery(repo, FixtureSearchIndex(documents_from_catalog(entities)))
    # The API's export path (GET /catalog/export) is CatalogService.export_page.
    service = CatalogService(repo, AuditRepository(InMemoryAuditStore()), lambda: datetime.now(UTC))
    visible = [
        e["id"] for e in entities if e["entity_type"] == "agent" and e["domain_id"] in allowed
    ]
    assert visible, "the scoped caller must see some agents"
    budget = Budget(timeout_ms=5000, limit=50, max_depth=3)
    violations: list[str] = []
    search_nodes: list[int] = []
    exported: list[int] = []

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

    async def export_page(i: int) -> None:
        flt = EntityFilter(entity_types=["agent"], domain_ids=[allowed[i % QUERY_DOMAINS]])
        page = await service.export_page(scope, flt, PageRequest(page_size=100))
        exported.append(len(page.items))
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
        "export_page_scoped": export_page,
        "search": search,
        "neighbors_depth3": neighbors,
        "impact_paths_depth3": impact,
    }
    measured: dict[str, dict[str, float]] = {}
    for name, fn in workloads.items():
        await _time(name, [lambda i=i, fn=fn: fn(i) for i in range(max(1, len(visible)))], measured)
    return {
        "label": label,
        "target_ms_for_context_only": TARGET_MS,
        "disclaimer": disclaimer,
        "dataset": {
            "generator": "sandbox",
            "profile": "custom",
            "domains": len(all_domains),
            "agents": agents,
            "query_domains": QUERY_DOMAINS,
            **loaded,
        },
        "iterations_per_workload": ITERATIONS,
        "p95_ms_by_workload": {k: v["p95_ms"] for k, v in measured.items()},
        "workloads": measured,
        "search_nodes_returned_total": sum(search_nodes),
        "export_items_returned_total": sum(exported),
        "scope_violations": violations,
    }


def check_and_record(result: dict[str, Any], label: str, path: Path) -> None:
    """Correctness asserts (scope, non-empty, labelled), then write the JSON. No latency assert."""
    assert result["scope_violations"] == []
    assert result["search_nodes_returned_total"] > 0, "search must return something to time"
    assert result["export_items_returned_total"] > 0, "export must return something to time"
    assert result["label"] == label
    assert set(result["p95_ms_by_workload"]) == set(WORKLOAD_NAMES)
    assert all(v > 0 for v in result["p95_ms_by_workload"].values())

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"\ncatalog latency ({label}); target {TARGET_MS} ms is NOT asserted")
    for name, stats in result["workloads"].items():
        print(
            f"  {name:24s} p50={stats['p50_ms']:9.3f} ms  p95={stats['p95_ms']:9.3f} ms  "
            f"max={stats['max_ms']:9.3f} ms  n={int(stats['samples'])}"
        )
    print(f"  recorded: {path}")
    assert path.is_file()
