"""``graph_query``: scope re-filtering, refusals and truncation (PRP-78 item 1)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, get_args

import pytest
from neurosphere_contracts.catalog.v1.agent import Agent
from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope
from neurosphere_core.catalog.graph import RepositoryGraphQuery
from neurosphere_core.catalog.protocol import (
    CatalogEdge,
    GraphResult,
    ImpactRequest,
    NeighborsRequest,
    RelationTypeName,
)
from neurosphere_core.catalog.repo import InMemoryCatalogRepository
from neurosphere_core.copilot.tools import (
    ArgumentNotAllowedError,
    ScopeArgumentRefusedError,
    ToolRegistry,
    ToolResult,
)
from neurosphere_core.copilot.tools.errors import ToolBudgetError
from neurosphere_core.copilot.tools.graph import (
    COPILOT_RELATIONS,
    MAX_GRAPH_DEPTH,
    MAX_GRAPH_EDGES,
    MAX_GRAPH_NODES,
    MAX_START_IDS,
    TOOL_NAME,
    graph_query_spec,
)
from neurosphere_core.errors import InvalidSchemaError
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
            "scope_hash": "sha256:" + hashlib.sha256(b"graph-scope").hexdigest(),
        }
    )
    return IdentityScope._from_verified_contract(contract)  # pyright: ignore[reportPrivateUsage]


SEED = _scope([("viewer", [DOM_A, DOM_B])], [DOM_A, DOM_B])
# Policy lets the repository see domain B, but data.read is held on A only: the tool must filter.
STEWARD_A_WIDE = _scope([("domain_steward", [DOM_A])], [DOM_A, DOM_B])
STEWARD_A = _scope([("domain_steward", [DOM_A])], [DOM_A])


def _aid(name: str) -> str:
    return f"commercial:{NS}:foundry:agent:{name}"


def _agent(name: str, domain: str) -> Agent:
    raw = _example("agent.minimal-and-typical.json")
    raw.update(
        id=_aid(name),
        customer_id=NS,
        domain_id=domain,
        current_version_id=None,
        external_agent_id=None,
        version=1,
        etag="caller-etag",
        display_name=f"Agent {name}",
    )
    return Agent.model_validate(raw)


def _invokes(name: str, src: str, dst: str, domain: str) -> CatalogEdge:
    raw = _example("invokes.inferred.json")
    raw.update(
        id=f"commercial:{NS}:neurosphere:invokes:{name}",
        source_id=_aid(src),
        target_id=_aid(dst),
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
class LeakyGraph:
    """A misbehaving port: ignores the caller's scope and reads with the seeding scope."""

    inner: RepositoryGraphQuery

    async def neighbors(self, scope: IdentityScope, request: NeighborsRequest) -> GraphResult:
        return await self.inner.neighbors(SEED, request)

    async def impact_paths(self, scope: IdentityScope, request: ImpactRequest) -> GraphResult:
        return await self.inner.impact_paths(SEED, request)


@dataclass
class Rig:
    repo: InMemoryCatalogRepository
    graph: RepositoryGraphQuery

    def registry(self, *, leaky: bool = False) -> ToolRegistry:
        return ToolRegistry(
            [
                graph_query_spec(
                    graph=LeakyGraph(self.graph) if leaky else self.graph,
                    access=None,
                    catalog=self.repo,
                    clock=lambda: NOW,
                )
            ]
        )


async def _rig() -> Rig:
    """a1 -> d (both domain A); a1 -> m (B) -> c (A); a1 -> d2 (A)."""
    repo = InMemoryCatalogRepository()
    for name, domain in (("a1", DOM_A), ("d", DOM_A), ("d2", DOM_A), ("m", DOM_B), ("c", DOM_A)):
        await repo.create_entity(SEED, _agent(name, domain))
    for name, src, dst, domain in (
        ("a1-d", "a1", "d", DOM_A),
        ("a1-m", "a1", "m", DOM_A),
        ("m-c", "m", "c", DOM_B),
        ("a1-d2", "a1", "d2", DOM_A),
    ):
        await repo.put_edge(SEED, _invokes(name, src, dst, domain), None)
    return Rig(repo, RepositoryGraphQuery(repo, _NoSearch(), now=lambda: NOW))


def _query(operation: str, depth: int, start: list[str], **extra: Any) -> dict[str, Any]:
    traversal = {
        "start_ids": [_aid(s) if not s.startswith("commercial:") else s for s in start],
        "relations": ["invokes"],
        "direction": "outgoing",
    }
    return {
        "schema_version": "1.0.0",
        "operation": operation,
        "entity": "agent",
        "budget": {"timeout_ms": 5000, "limit": 50, "max_depth": depth, **extra.pop("budget", {})},
        "traversal": {**traversal, **extra.pop("traversal", {})},
        **extra,
    }


def _ids(result: ToolResult) -> set[str]:
    return {r.record_id for r in result.records}


@pytest.mark.parametrize("scope", [STEWARD_A_WIDE, STEWARD_A])
@pytest.mark.parametrize("leaky", [False, True])
@pytest.mark.parametrize("operation", ["neighbors", "impact_paths"])
async def test_unreadable_domain_never_appears_even_as_an_intermediate(
    scope: IdentityScope, leaky: bool, operation: str
) -> None:
    rig = await _rig()
    result = await rig.registry(leaky=leaky).invoke(
        TOOL_NAME, {"query": _query(operation, 3, ["a1"])}, scope
    )
    ids = _ids(result)
    assert _aid("m") not in ids
    assert _aid("c") not in ids  # only reachable through m
    assert not any("a1-m" in i or "m-c" in i for i in ids)
    assert ids == {_aid("a1"), _aid("d"), _aid("d2")} | {
        f"commercial:{NS}:neurosphere:invokes:a1-d",
        f"commercial:{NS}:neurosphere:invokes:a1-d2",
    }
    for rec in result.records:
        assert rec.data.get("domain_id", DOM_A) == DOM_A
    assert [c.record_id for c in result.citations] == [r.record_id for r in result.records]


async def test_unreadable_start_node_returns_nothing() -> None:
    rig = await _rig()
    result = await rig.registry(leaky=True).invoke(
        TOOL_NAME, {"query": _query("neighbors", 2, ["m"])}, STEWARD_A
    )
    assert result.records == ()


async def test_impact_nodes_carry_their_path() -> None:
    rig = await _rig()
    result = await rig.registry().invoke(
        TOOL_NAME, {"query": _query("impact_paths", 2, ["a1"])}, STEWARD_A
    )
    (node,) = (r for r in result.records if r.record_id == _aid("d"))
    assert node.data["path_node_ids"] == [_aid("a1"), _aid("d")]


def test_relation_allowlist_is_the_contract_enum_minus_grants_access_to() -> None:
    assert COPILOT_RELATIONS == set(get_args(RelationTypeName)) - {"grants_access_to"}
    assert "grants_access_to" not in COPILOT_RELATIONS


@pytest.mark.parametrize("relation", ["grants_access_to"])
async def test_disallowed_relation_is_refused_before_any_read(relation: str) -> None:
    rig = await _rig()
    with pytest.raises(ToolBudgetError) as info:
        await rig.registry().invoke(
            TOOL_NAME,
            {
                "query": _query(
                    "neighbors", 1, ["a1"], traversal={"relations": ["invokes", relation]}
                )
            },
            STEWARD_A,
        )
    assert info.value.reason == "relation_denied"


@pytest.mark.parametrize("depth", [MAX_GRAPH_DEPTH + 1, 5, 0])
async def test_depth_outside_the_copilot_cap_is_refused(depth: int) -> None:
    rig = await _rig()
    with pytest.raises(ToolBudgetError) as info:
        await rig.registry().invoke(
            TOOL_NAME, {"query": _query("neighbors", depth, ["a1"])}, STEWARD_A
        )
    assert info.value.reason == "depth_denied"


async def test_more_than_fifty_start_ids_is_refused() -> None:
    rig = await _rig()
    starts = [f"commercial:{NS}:foundry:agent:s{i}" for i in range(MAX_START_IDS + 1)]
    with pytest.raises(InvalidSchemaError):
        await rig.registry().invoke(TOOL_NAME, {"query": _query("neighbors", 1, starts)}, STEWARD_A)


@pytest.mark.parametrize("operation", ["neighbors", "impact_paths"])
async def test_graph_operation_without_traversal_is_refused(operation: str) -> None:
    rig = await _rig()
    query = _query(operation, 1, ["a1"])
    del query["traversal"]
    with pytest.raises(ToolBudgetError) as info:
        await rig.registry().invoke(TOOL_NAME, {"query": query}, STEWARD_A)
    assert info.value.reason == "traversal_required"


async def test_impact_paths_needs_a_single_direction() -> None:
    rig = await _rig()
    with pytest.raises(ToolBudgetError):
        await rig.registry().invoke(
            TOOL_NAME,
            {"query": _query("impact_paths", 1, ["a1"], traversal={"direction": "both"})},
            STEWARD_A,
        )


@pytest.mark.parametrize(
    "extra",
    [
        {"filters": [{"field": "lifecycle_status", "op": "eq", "value": "active"}]},
        {"sort": [{"field": "id", "direction": "asc"}]},
        {"cursor": "abc"},
    ],
)
async def test_unsupported_clauses_are_refused_not_dropped(extra: dict[str, Any]) -> None:
    rig = await _rig()
    with pytest.raises((ToolBudgetError, InvalidSchemaError)):
        await rig.registry().invoke(
            TOOL_NAME, {"query": _query("neighbors", 1, ["a1"], **extra)}, STEWARD_A
        )


async def test_unknown_keys_are_refused() -> None:
    rig = await _rig()
    registry = rig.registry()
    good = _query("neighbors", 1, ["a1"])
    with pytest.raises(ArgumentNotAllowedError):
        await registry.invoke(TOOL_NAME, {"query": good, "cypher": "MATCH (n) RETURN n"}, STEWARD_A)
    with pytest.raises(InvalidSchemaError):
        await registry.invoke(TOOL_NAME, {"query": {**good, "cypher": "MATCH (n)"}}, STEWARD_A)
    with pytest.raises(InvalidSchemaError):
        await registry.invoke(TOOL_NAME, {"query": good, "access_mode": "everything"}, STEWARD_A)


@pytest.mark.parametrize("key", ["domain_id", "customer_id", "allowed_domains", "scope"])
async def test_scope_shaped_keys_are_refused(key: str) -> None:
    rig = await _rig()
    with pytest.raises(ScopeArgumentRefusedError):
        await rig.registry().invoke(
            TOOL_NAME, {"query": _query("neighbors", 1, ["a1"]), key: DOM_B}, STEWARD_A
        )


async def test_over_budget_walk_is_flagged_truncated() -> None:
    rig = await _rig()
    result = await rig.registry().invoke(
        TOOL_NAME,
        {"query": _query("neighbors", 1, ["a1"], budget={"max_nodes": 2})},
        STEWARD_A,
    )
    assert result.truncated
    assert len(result.records) <= 2 + MAX_GRAPH_EDGES
    nodes = [r for r in result.records if r.kind != "graph_edge"]
    assert len(nodes) <= 2


async def test_server_caps_are_below_the_contract_ceiling() -> None:
    assert (MAX_GRAPH_DEPTH, MAX_GRAPH_NODES, MAX_GRAPH_EDGES, MAX_START_IDS) == (3, 100, 300, 50)
    rig = await _rig()
    result = await rig.registry().invoke(
        TOOL_NAME,
        {"query": _query("neighbors", 3, ["a1"], budget={"max_nodes": 5000, "max_edges": 20000})},
        STEWARD_A,
    )
    assert not result.truncated
