"""Loader and measurement for the agent match latency profile (PRP-72 item 5).

MEASURED, never asserted: nothing here compares a latency to a threshold. The catalog is the
sandbox generator's ``custom`` profile with 10,000 agents, loaded into the in-memory repository
(through the catalog-latency harness helpers) after giving every agent tags, capabilities and
descriptive text (the generator's agents carry none, and without text the lexical signal is empty).
The matcher runs over the fixture BM25 search provider, so the numbers say nothing about Azure AI
Search, Cosmos NoSQL or live telemetry.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from neurosphere_contracts.recommendations.v1.agent_match_request import AgentMatchRequest
from neurosphere_core.catalog import CatalogRepository
from neurosphere_core.catalog.graph import RepositoryGraphQuery
from neurosphere_core.catalog.repo import InMemoryCatalogRepository
from neurosphere_core.catalog.repo.documents import parse_edge, parse_entity
from neurosphere_core.errors import InvalidSchemaError
from neurosphere_core.recommendations.matching import (
    AgentMatcher,
    InMemoryFeedbackStore,
    MatchSettings,
)
from neurosphere_core.scope import IdentityScope
from neurosphere_core.search.fixture import FixtureSearchIndex, documents_from_catalog

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:  # `tests` and `sandbox` are top-level, not workspace members
    sys.path.insert(0, str(_ROOT))

from sandbox import catalog as sandbox_catalog  # noqa: E402
from sandbox.config import PROFILES, GenerateConfig, with_overrides  # noqa: E402
from sandbox.world import World  # noqa: E402
from tests.load.catalog_latency.harness import (  # noqa: E402
    ROOT,
    _percentile,  # pyright: ignore[reportPrivateUsage]
    make_scope,
)

AGENTS = 10_000
DOMAINS = 8
QUERY_DOMAINS = 3
CANDIDATE_CAP = MatchSettings().candidate_cap
WARMUP = 3
ROUNDS = int(os.environ.get("NS_AGENT_MATCH_ROUNDS", "1"))  # runs per task; all are sampled
EDGE_CAP = 1500  # the in-memory repository scans per edge write (quadratic); bound the load
LABEL = "in-memory repository + fixture BM25, bounded feasibility, not a live claim"
RESULT_PATH = ROOT / "temp" / "agent_match" / "p95.json"

_VERBS = ("reconcile", "summarize", "classify", "route", "extract", "translate", "audit", "triage")
_OBJECTS = ("invoices", "tickets", "contracts", "incidents", "emails", "claims", "logs", "orders")
_TAGS = ("finance", "support", "legal", "ops", "security", "hr", "sales", "data")

_GENERATED = [
    f"{verb} the {obj} for the {tag} team"
    for verb in _VERBS[:5]
    for obj, tag in zip(_OBJECTS[:3], _TAGS[:3], strict=True)
]
TASKS: tuple[str, ...] = (
    *_GENERATED,
    "route support tickets to the right queue",
    "summarize long legal contracts",
    "extract line items from invoices",
    "classify incoming emails by urgency",
    "triage security incidents",
)


def make_world() -> tuple[World, list[str]]:
    profile = with_overrides(PROFILES["custom"], domains=DOMAINS, agents=AGENTS)
    world = World(GenerateConfig(seed=11, profile=profile, cloud="commercial"))
    return world, [world.domain_id(i) for i in range(len(world.domains))]


def describe(doc: dict[str, Any], index: int) -> dict[str, Any]:
    """Tags, capabilities and text for one agent doc; deterministic in ``index``."""
    verb, obj, tag = _VERBS[index % 8], _OBJECTS[(index // 8) % 8], _TAGS[(index // 64) % 8]
    doc["tags"] = [tag, _TAGS[(index // 7) % 8]]
    doc["capabilities"] = [f"{verb}.{obj}"]
    doc["description"] = f"agent that can {verb} {obj} for the {tag} team"
    return doc


async def load_catalog(
    repo: CatalogRepository, scope: IdentityScope, world: World
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    entities: list[dict[str, Any]] = []
    counts = {"entities": 0, "agents": 0, "edges": 0, "skipped": 0}
    steps = (
        (sandbox_catalog.iter_domains, False),
        (sandbox_catalog.iter_owners, False),
        (sandbox_catalog.iter_models, False),
        (sandbox_catalog.iter_sources, False),
        (sandbox_catalog.iter_tools, False),
        (sandbox_catalog.iter_agents, True),
    )
    for fn, is_agent in steps:
        for number, doc in enumerate(fn(world)):
            if is_agent:
                doc = describe(doc, number)
            try:
                await repo.create_entity(scope, parse_entity(doc))
            except InvalidSchemaError:
                counts["skipped"] += 1
                continue
            entities.append(doc)
            counts["entities"] += 1
            counts["agents"] += 1 if is_agent else 0
    for doc in sandbox_catalog.iter_relations(world):
        if counts["edges"] >= EDGE_CAP:
            break
        try:
            await repo.put_edge(scope, parse_edge(doc), None)
        except InvalidSchemaError:
            continue
        counts["edges"] += 1
    return entities, counts


async def measure() -> dict[str, Any]:
    world, all_domains = make_world()
    repo = InMemoryCatalogRepository()
    entities, loaded = await load_catalog(repo, make_scope(world, all_domains), world)
    allowed = all_domains[:QUERY_DOMAINS]
    scope = make_scope(world, allowed)
    search = FixtureSearchIndex(documents_from_catalog(entities))
    graph = RepositoryGraphQuery(repo, search)
    matcher = AgentMatcher(search, graph, InMemoryFeedbackStore(), settings=MatchSettings())
    domain_of = {e["id"]: e.get("domain_id") for e in entities}
    in_scope_agents = {i for i, d in domain_of.items() if d in allowed and ":agent:" in i}
    assert in_scope_agents, "the scoped caller must see some agents"

    violations: list[str] = []
    ranked: list[int] = []
    samples: list[float] = []
    runs = [(task, False) for task in TASKS[:WARMUP]] + [
        (task, True) for _ in range(ROUNDS) for task in TASKS
    ]
    for task, counted in runs:
        request = AgentMatchRequest.model_validate({"schema_version": "1.0.0", "task_text": task})
        started = time.perf_counter()
        result = await matcher.match_detailed(scope, allowed[0], request)
        elapsed = (time.perf_counter() - started) * 1000.0
        if not counted:
            continue
        samples.append(elapsed)
        candidates = [_plain(c.entity_id) for c in result.response.candidates]
        ranked.append(len(candidates))
        violations.extend(c for c in candidates if domain_of.get(c) not in allowed)
    ordered = sorted(samples)
    return {
        "label": LABEL,
        "disclaimer": (
            "Measured against the in-memory catalog repository and the fixture BM25 search "
            "provider (no network, no index service, no live telemetry). This is not a live "
            "claim and says nothing about Azure AI Search or Cosmos NoSQL."
        ),
        "backend": "in-memory repository + fixture BM25",
        "agent_count": AGENTS,
        "candidate_cap": CANDIDATE_CAP,
        "query_domains": QUERY_DOMAINS,
        "tasks": len(TASKS),
        "rounds": ROUNDS,
        "warmup_runs_excluded": WARMUP,
        "samples": len(ordered),
        "p50_ms": round(_percentile(ordered, 50), 3),
        "p95_ms": round(_percentile(ordered, 95), 3),
        "max_ms": round(ordered[-1], 3),
        "dataset": {
            "generator": "sandbox",
            "profile": "custom",
            "domains": DOMAINS,
            "edge_cap": EDGE_CAP,
            **loaded,
        },
        "in_scope_agents": len(in_scope_agents),
        "empty_rankings": sum(1 for n in ranked if n == 0),
        "scope_violations": violations,
    }


def _plain(value: Any) -> str:
    while hasattr(value, "root"):
        value = value.root
    return str(value)


def check_and_record(result: dict[str, Any], path: Path = RESULT_PATH) -> None:
    """Correctness asserts (scope, non-empty ranking, labelled), then write. No latency assert."""
    assert result["scope_violations"] == []
    assert result["agent_count"] == AGENTS == result["dataset"]["agents"]
    assert result["tasks"] >= 20
    assert result["empty_rankings"] == 0, "every task must rank something"
    assert result["label"] == LABEL and "not a live claim" in result["disclaimer"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"\nagent match latency ({LABEL}); no latency threshold is asserted")
    print(
        f"  agents={result['agent_count']} cap={result['candidate_cap']} "
        f"samples={result['samples']}  p50={result['p50_ms']:.3f} ms  "
        f"p95={result['p95_ms']:.3f} ms  max={result['max_ms']:.3f} ms"
    )
    print(f"  recorded: {path}")
