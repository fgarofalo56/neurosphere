"""``graph_query``: neighbours with provenance, and the two-step data-access list (PRP-78 item 1).

Runs the real in-memory catalog repository, graph query and PRP-73 access engine behind the tool
ports, with spies where a test needs to see what reached a port.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from neurosphere_contracts.catalog.v1.agent import Agent
from neurosphere_contracts.catalog.v1.grounding_source import GroundingSource
from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope
from neurosphere_core.auth.scope import Permission
from neurosphere_core.catalog.graph import RepositoryGraphQuery
from neurosphere_core.catalog.graph.access import AccessEngine, AccessQuery, AccessResult
from neurosphere_core.catalog.protocol import CatalogEdge
from neurosphere_core.catalog.repo import InMemoryCatalogRepository
from neurosphere_core.copilot.tools import ToolRegistry, ToolResult
from neurosphere_core.copilot.tools.errors import ToolBudgetError
from neurosphere_core.copilot.tools.graph import (
    MAX_START_IDS,
    TOOL_NAME,
    graph_query_spec,
)
from neurosphere_core.scope import IdentityScope
from neurosphere_core.search.protocol import SearchRequest, SearchResult
from pydantic import TypeAdapter

SCHEMAS = Path(__file__).resolve().parents[4] / "packages" / "contracts" / "schemas"
VALID = SCHEMAS / "catalog" / "v1" / "examples" / "valid"
NS = "acme"
NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
DOM_A = f"commercial:{NS}:neurosphere:domain:a"
DOM_B = f"commercial:{NS}:neurosphere:domain:b"
EDGES = TypeAdapter(CatalogEdge)


def _example(name: str) -> dict[str, Any]:
    return json.loads((VALID / name).read_text(encoding="utf-8"))


def _scope(roles: list[tuple[str, list[str]]], allowed: list[str]) -> IdentityScope:
    contract = ContractScope.model_validate(
        {
            "schema_version": "1.0.0",
            "cloud": "commercial",
            "customer_id": NS,
            "principal": {
                "principal_id": f"commercial:{NS}:idp:person:p1",
                "principal_pseudonym": "p-0001",
                "principal_kind": "user",
            },
            "roles": [{"role": r, "domain_ids": d} for r, d in roles],
            "allowed_domains": allowed,
            "allowed_resources": [],
            "policy_version": "v1",
            "derived_at": "2026-01-01T00:00:00Z",
            "scope_hash": "sha256:" + hashlib.sha256(b"graph-tool").hexdigest(),
        }
    )
    return IdentityScope._from_verified_contract(contract)  # pyright: ignore[reportPrivateUsage]


SEED = _scope([("viewer", [DOM_A, DOM_B])], [DOM_A, DOM_B])
STEWARD_A = _scope([("domain_steward", [DOM_A])], [DOM_A])


def _agent_id(name: str) -> str:
    return f"commercial:{NS}:foundry:agent:{name}"


def _source_id(name: str) -> str:
    return f"commercial:{NS}:foundry:grounding_source:{name}"


def _agent(name: str, domain: str) -> Agent:
    raw = _example("agent.minimal-and-typical.json")
    raw.update(
        id=_agent_id(name),
        customer_id=NS,
        domain_id=domain,
        current_version_id=None,
        external_agent_id=None,
        version=1,
        etag="caller-etag",
        display_name=f"Agent {name}",
    )
    return Agent.model_validate(raw)


def _source(name: str, domain: str, **patch: Any) -> GroundingSource:
    raw = _example("grounding_source.sensitivity-residency.json")
    raw.update(
        id=_source_id(name),
        customer_id=NS,
        domain_id=domain,
        version=1,
        etag="caller-etag",
        display_name=f"Source {name}",
        tags=[],
        environment="unknown",
    )
    raw.update(patch)
    return GroundingSource.model_validate(raw)


def _edge(relation: str, name: str, who: str, what: str, domain: str) -> CatalogEdge:
    raw = _example(f"{relation}.inferred.json")
    raw.update(
        id=f"commercial:{NS}:neurosphere:{relation}:{name}",
        source_id=_agent_id(who),
        target_id=_source_id(what),
        customer_id=NS,
        domain_id=domain,
        version=1,
        etag="caller-etag",
    )
    return EDGES.validate_python(raw)


class _NoSearch:
    async def search(self, scope: object, request: SearchRequest) -> SearchResult:
        return SearchResult(hits=[], matched=0, partial=False)


@dataclass
class SpyAccess:
    """Records every ``AccessQuery`` that reaches the real engine."""

    inner: AccessEngine
    queries: list[AccessQuery] = field(default_factory=list[AccessQuery])

    async def who_accesses(self, scope: IdentityScope, query: AccessQuery) -> AccessResult:
        self.queries.append(query)
        return await self.inner.who_accesses(scope, query)


@dataclass
class World:
    repo: InMemoryCatalogRepository
    graph: RepositoryGraphQuery
    access: SpyAccess

    def registry(self, *, with_access: bool = True) -> ToolRegistry:
        return ToolRegistry(
            [
                graph_query_spec(
                    graph=self.graph,
                    access=self.access if with_access else None,
                    catalog=self.repo,
                    clock=lambda: NOW,
                )
            ]
        )


async def _world() -> World:
    repo = InMemoryCatalogRepository()
    graph = RepositoryGraphQuery(repo, _NoSearch(), now=lambda: NOW)
    return World(repo, graph, SpyAccess(AccessEngine(repo, graph, now=lambda: NOW)))


async def _seed(world: World) -> None:
    for name in ("x", "y"):
        await world.repo.create_entity(SEED, _agent(name, DOM_A))
    await world.repo.create_entity(
        SEED,
        _source(
            "eu-claims",
            DOM_A,
            sensitivity_categories=["pii"],
            contains_personal_data=True,
            residency_region="westeurope",
            residency_geography="eu_eea",
        ),
    )
    await world.repo.create_entity(
        SEED,
        _source(
            "us-logs",
            DOM_A,
            sensitivity_categories=["pii"],
            contains_personal_data=True,
            residency_region="eastus",
            residency_geography="united_states",
        ),
    )
    await world.repo.put_edge(SEED, _edge("writes", "x-eu", "x", "eu-claims", DOM_A), None)
    await world.repo.put_edge(SEED, _edge("reads", "y-us", "y", "us-logs", DOM_A), None)


def _query(entity: str, operation: str = "list", depth: int = 0, **extra: Any) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "operation": operation,
        "entity": entity,
        "budget": {"timeout_ms": 5000, "limit": 50, "max_depth": depth},
        **extra,
    }


def _filter(field_name: str, value: Any) -> dict[str, Any]:
    return {"field": field_name, "op": "eq", "value": value}


def _ids(result: ToolResult) -> set[str]:
    return {r.record_id for r in result.records}


def _assert_cited(result: ToolResult) -> None:
    assert [(c.record_id, c.kind) for c in result.citations] == [
        (r.record_id, r.kind) for r in result.records
    ]


async def test_neighbors_returns_writer_with_edge_provenance_and_evidence() -> None:
    world = await _world()
    await _seed(world)
    args = {
        "query": _query(
            "grounding_source",
            "neighbors",
            1,
            traversal={
                "start_ids": [_source_id("eu-claims")],
                "relations": ["writes"],
                "direction": "incoming",
            },
        )
    }
    result = await world.registry().invoke(TOOL_NAME, args, STEWARD_A)

    edge_id = f"commercial:{NS}:neurosphere:writes:x-eu"
    assert _ids(result) == {_agent_id("x"), _source_id("eu-claims"), edge_id}
    (edge,) = (r for r in result.records if r.kind == "graph_edge")
    assert edge.data["source_id"] == _agent_id("x")
    assert edge.data["target_id"] == _source_id("eu-claims")
    expected_evidence = _example("writes.inferred.json")["evidence_ids"]
    assert expected_evidence
    assert edge.data["evidence_ids"] == expected_evidence
    provenance: dict[str, Any] = edge.data["provenance"]  # type: ignore[assignment]
    assert provenance["method"]
    assert not result.truncated
    _assert_cited(result)


async def test_neighbors_relation_filter_excludes_other_relations() -> None:
    world = await _world()
    await _seed(world)
    await world.repo.put_edge(SEED, _edge("reads", "y-eu", "y", "eu-claims", DOM_A), None)
    args = {
        "query": _query(
            "grounding_source",
            "neighbors",
            1,
            traversal={
                "start_ids": [_source_id("eu-claims")],
                "relations": ["writes"],
                "direction": "incoming",
            },
        )
    }
    result = await world.registry().invoke(TOOL_NAME, args, STEWARD_A)
    assert _agent_id("y") not in _ids(result)


async def test_access_list_by_geography_is_two_step_and_cited_per_agent_and_asset() -> None:
    world = await _world()
    await _seed(world)
    args = {
        "query": _query(
            "grounding_source",
            filters=[_filter("residency_geography", "eu_eea")],
        ),
        "access_mode": "any",
    }
    result = await world.registry().invoke(TOOL_NAME, args, STEWARD_A)

    (spied,) = world.access.queries
    assert spied.asset_ids == [_source_id("eu-claims")]  # step 1 resolved the geography
    assert spied.domain_ids == [DOM_A]
    assert spied.modes == ["read", "write"]
    assert _ids(result) == {_agent_id("x"), _source_id("eu-claims")}
    (accessor,) = (r for r in result.records if r.record_id == _agent_id("x"))
    (access,) = accessor.data["accesses"]  # type: ignore[misc]
    assert access["asset_id"] == _source_id("eu-claims")  # type: ignore[index]
    assert access["mode"] == "write"  # type: ignore[index]
    assert access["evidence_ids"]  # type: ignore[index]
    _assert_cited(result)


async def test_access_list_by_sensitivity_skips_step_one() -> None:
    world = await _world()
    await _seed(world)
    args = {
        "query": _query("grounding_source", filters=[_filter("sensitivity_category", "pii")]),
        "access_mode": "any",
    }
    result = await world.registry().invoke(TOOL_NAME, args, STEWARD_A)

    (spied,) = world.access.queries
    assert spied.asset_ids == []
    assert spied.sensitivity_categories == ["pii"]
    assert {_agent_id("x"), _agent_id("y")} <= _ids(result)
    assert {_source_id("eu-claims"), _source_id("us-logs")} <= _ids(result)
    _assert_cited(result)


async def test_access_mode_read_only_lists_readers() -> None:
    world = await _world()
    await _seed(world)
    args = {
        "query": _query("grounding_source", filters=[_filter("sensitivity_category", "pii")]),
        "access_mode": "read",
    }
    result = await world.registry().invoke(TOOL_NAME, args, STEWARD_A)
    assert world.access.queries[0].modes == ["read"]
    assert _agent_id("y") in _ids(result)
    assert _agent_id("x") not in _ids(result)


async def test_geography_without_a_match_never_calls_the_access_engine() -> None:
    world = await _world()
    await _seed(world)
    args = {
        "query": _query("grounding_source", filters=[_filter("residency_geography", "uk")]),
        "access_mode": "any",
    }
    result = await world.registry().invoke(TOOL_NAME, args, STEWARD_A)
    assert result.records == ()
    assert world.access.queries == []  # no ids must never mean "scan everything"


async def test_asset_ids_are_capped_at_fifty_and_flagged() -> None:
    world = await _world()
    for i in range(MAX_START_IDS + 2):
        await world.repo.create_entity(
            SEED,
            _source(
                f"eu-{i:02d}",
                DOM_A,
                residency_geography="eu_eea",
                sensitivity_categories=["pii"],
                contains_personal_data=True,
                residency_region="westeurope",
            ),
        )
    args = {
        "query": _query("grounding_source", filters=[_filter("residency_geography", "eu_eea")]),
        "access_mode": "any",
    }
    result = await world.registry().invoke(TOOL_NAME, args, STEWARD_A)
    (spied,) = world.access.queries
    assert len(spied.asset_ids) == MAX_START_IDS
    assert result.truncated


async def test_domain_filter_can_only_narrow() -> None:
    world = await _world()
    await _seed(world)
    args = {
        "query": _query(
            "grounding_source",
            filters=[{"field": "domain_id", "op": "eq", "value": DOM_B}],
        ),
        "access_mode": "any",
    }
    result = await world.registry().invoke(TOOL_NAME, args, STEWARD_A)
    assert result.records == ()
    assert world.access.queries == []


@pytest.mark.parametrize(
    ("args", "reason"),
    [
        ({"query": _query("agent")}, "unsupported_entity"),
        ({"query": _query("grounding_source")}, "access_mode_required"),
        ({"query": _query("agent"), "access_mode": "any"}, "unsupported_entity"),
        (
            {
                "query": _query(
                    "grounding_source",
                    filters=[{"field": "lifecycle_status", "op": "eq", "value": "active"}],
                ),
                "access_mode": "any",
            },
            "unsupported_filter",
        ),
        (
            {
                "query": _query(
                    "grounding_source",
                    filters=[{"field": "sensitivity_category", "op": "eq", "value": "not-a-kind"}],
                ),
                "access_mode": "any",
            },
            "unsupported_filter",
        ),
        (
            {
                "query": _query(
                    "grounding_source",
                    filters=[
                        _filter("residency_geography", "uk"),
                        _filter("residency_geography", "canada"),
                    ],
                ),
                "access_mode": "any",
            },
            "unsupported_filter",
        ),
        (
            {
                "query": _query("grounding_source", sort=[{"field": "id", "direction": "asc"}]),
                "access_mode": "any",
            },
            "unsupported_query",
        ),
    ],
)
async def test_list_refusals_carry_a_fixed_reason(args: dict[str, Any], reason: str) -> None:
    world = await _world()
    await _seed(world)
    with pytest.raises(ToolBudgetError) as info:
        await world.registry().invoke(TOOL_NAME, args, STEWARD_A)
    assert info.value.reason == reason
    assert world.access.queries == []


async def test_access_mode_with_a_graph_operation_is_refused() -> None:
    world = await _world()
    args = {
        "query": _query(
            "grounding_source",
            "neighbors",
            1,
            traversal={
                "start_ids": [_source_id("eu-claims")],
                "relations": ["writes"],
                "direction": "incoming",
            },
        ),
        "access_mode": "any",
    }
    with pytest.raises(ToolBudgetError):
        await world.registry().invoke(TOOL_NAME, args, STEWARD_A)


async def test_list_is_refused_when_no_access_reader_is_bound() -> None:
    world = await _world()
    args = {
        "query": _query("grounding_source", filters=[_filter("sensitivity_category", "pii")]),
        "access_mode": "any",
    }
    with pytest.raises(ToolBudgetError) as info:
        await world.registry(with_access=False).invoke(TOOL_NAME, args, STEWARD_A)
    assert info.value.reason == "access_unavailable"


async def test_caller_without_data_read_is_refused() -> None:
    world = await _world()
    auditor = _scope([("security_auditor", [DOM_A])], [DOM_A])
    args = {"query": _query("grounding_source"), "access_mode": "any"}
    with pytest.raises(Exception) as info:
        await world.registry().invoke(TOOL_NAME, args, auditor)
    assert Permission.DATA_READ.value in str(info.value)
