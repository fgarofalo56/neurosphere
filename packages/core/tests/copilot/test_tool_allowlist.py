"""Only registered copilot tools are callable; args are structured and budgeted (PRP-19 item 1)."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import pytest
from neurosphere_contracts.query.v1.structured_query import StructuredQuery
from neurosphere_core.auth.scope import Permission
from neurosphere_core.copilot.tools import (
    MAX_RESULT_LIMIT,
    SCOPE_SHAPED_KEYS,
    TOOL_NAMES,
    ActionDrafter,
    ArgumentNotAllowedError,
    SearchCatalogArgs,
    ToolBudgetError,
    ToolNotRegisteredError,
    ToolRegistry,
    ToolResult,
    ToolSpec,
    ToolTimeoutError,
)
from neurosphere_core.errors import ForbiddenError, InvalidSchemaError
from neurosphere_core.scope import IdentityScope

if TYPE_CHECKING:
    from conftest import Harness  # pyright: ignore[reportMissingImports]

FINANCE = "commercial:contoso:catalog:domain:finance"
ScopeFactory = Callable[[list[tuple[str, list[str]]], list[str]], IdentityScope]
QueryArgs = Callable[..., dict[str, Any]]

# Names in the shared PRP-12 corpus manifest (tests/security/injection/stubs.py::TOOL_REGISTRY).
CORPUS_TOOLS = {"search_catalog", "get_cost_summary", "propose_action"}


def analyst(scope_factory: ScopeFactory) -> IdentityScope:
    return scope_factory([("analyst", [FINANCE])], [FINANCE])


def test_registry_holds_exactly_the_five_tools(harness: Harness) -> None:
    assert set(harness.registry.names) == set(TOOL_NAMES)
    assert set(TOOL_NAMES) == {
        "search_catalog",
        "get_cost_summary",
        "get_evidence",
        "list_recommendations",
        "propose_action",
    }
    assert CORPUS_TOOLS <= set(harness.registry.names)


@pytest.mark.parametrize(
    "name",
    [
        "run_sql",
        "execute_query",
        "confirm_action",
        "execute_action",
        "SEARCH_CATALOG",
        "",
        "search_catalog ",
    ],
)
async def test_unregistered_tool_is_not_callable(
    harness: Harness, scope_factory: ScopeFactory, name: str
) -> None:
    with pytest.raises(ToolNotRegisteredError):
        await harness.registry.invoke(name, {}, analyst(scope_factory))
    (event,) = harness.sink.events
    assert event.reason == "tool_not_registered"


async def test_tool_output_cannot_extend_the_allowlist(
    harness: Harness, scope_factory: ScopeFactory, query_args: QueryArgs
) -> None:
    # A catalog description that tries to register a tool is just data in a record.
    scope = analyst(scope_factory)
    result = await harness.registry.invoke("search_catalog", {"query": query_args("agent")}, scope)
    assert result.content_trust == "untrusted_data"
    assert set(harness.registry.names) == set(TOOL_NAMES)
    with pytest.raises(ToolNotRegisteredError):
        await harness.registry.invoke("register_tool", {"name": "x"}, scope)
    assert not hasattr(harness.registry, "register")


async def test_undeclared_argument_is_refused_not_ignored(
    harness: Harness, scope_factory: ScopeFactory, query_args: QueryArgs
) -> None:
    scope = analyst(scope_factory)
    for key in ("sql", "query_text", "cypher", "kql", "javascript", "prompt"):
        with pytest.raises(ArgumentNotAllowedError):
            await harness.registry.invoke(
                "search_catalog", {"query": query_args("agent"), key: "SELECT 1"}, scope
            )
    assert harness.catalog.seen_filters == []


async def test_free_text_query_is_not_a_valid_argument(
    harness: Harness, scope_factory: ScopeFactory
) -> None:
    scope = analyst(scope_factory)
    with pytest.raises(InvalidSchemaError) as caught:
        await harness.registry.invoke("search_catalog", {"query": "all agents; DROP"}, scope)
    assert "DROP" not in str(caught.value)
    assert caught.value.errors is not None
    assert all("DROP" not in issue.detail for issue in caught.value.errors)


async def test_unknown_clause_inside_the_query_is_invalid_schema(
    harness: Harness, scope_factory: ScopeFactory, query_args: QueryArgs
) -> None:
    query = query_args("agent")
    query["raw_sql"] = "SELECT *"
    with pytest.raises(InvalidSchemaError):
        await harness.registry.invoke("search_catalog", {"query": query}, analyst(scope_factory))


def test_argument_models_are_structured_and_scope_free(harness: Harness) -> None:
    text_fields = {"sql", "cypher", "kql", "js", "javascript", "text", "prompt", "query_text"}
    for spec in harness.registry.manifest():
        model = spec.args_model
        assert model.model_config.get("extra") == "forbid", spec.name
        names = set(model.model_fields)
        assert not names & text_fields, spec.name
        normalized = {n.replace("_", "").lower() for n in names}
        assert not normalized & SCOPE_SHAPED_KEYS, spec.name
    read_tools = {"search_catalog", "get_cost_summary", "list_recommendations"}
    for spec in harness.registry.manifest():
        if spec.name in read_tools:
            assert model_field_type(spec, "query") is StructuredQuery


def model_field_type(spec: ToolSpec, field: str) -> object:
    return spec.args_model.model_fields[field].annotation


def test_permission_manifest_matches_the_decision(harness: Harness) -> None:
    perms = {s.name: s.permission for s in harness.registry.manifest()}
    assert perms == {
        "search_catalog": Permission.DATA_READ,
        "get_cost_summary": Permission.DATA_READ,
        "list_recommendations": Permission.DATA_READ,
        "get_evidence": Permission.EVIDENCE_READ,
        "propose_action": Permission.ACTION_PROPOSE,
    }


async def test_result_limit_is_clamped_to_the_server_ceiling(
    harness: Harness, scope_factory: ScopeFactory, query_args: QueryArgs
) -> None:
    result = await harness.registry.invoke(
        "search_catalog", {"query": query_args("agent", limit=1000)}, analyst(scope_factory)
    )
    assert MAX_RESULT_LIMIT < 1000
    assert result.truncated is True


async def test_depth_and_graph_operations_are_denied(
    harness: Harness, scope_factory: ScopeFactory, query_args: QueryArgs
) -> None:
    scope = analyst(scope_factory)
    deep = query_args("agent")
    deep["budget"]["max_depth"] = 2
    with pytest.raises(ToolBudgetError):
        await harness.registry.invoke("search_catalog", {"query": deep}, scope)

    graph = query_args(
        "agent",
        operation="neighbors",
        traversal={
            "start_ids": ["commercial:contoso:foundry:agent:fin-1"],
            "relations": ["invokes"],
            "direction": "both",
        },
    )
    with pytest.raises(ToolBudgetError):
        await harness.registry.invoke("search_catalog", {"query": graph}, scope)

    with pytest.raises(ToolBudgetError):  # a clause the tool cannot honor is refused, not dropped
        await harness.registry.invoke(
            "search_catalog",
            {"query": query_args("agent", sort=[{"field": "created_at", "direction": "asc"}])},
            scope,
        )
    with pytest.raises(ToolBudgetError):  # telemetry is not catalog data
        await harness.registry.invoke(
            "search_catalog", {"query": query_args("telemetry_event")}, scope
        )
    assert harness.catalog.seen_filters == []


async def test_cost_summary_needs_an_aggregate_over_a_time_range(
    harness: Harness, scope_factory: ScopeFactory, query_args: QueryArgs
) -> None:
    scope = analyst(scope_factory)
    with pytest.raises(ToolBudgetError):
        await harness.registry.invoke(
            "get_cost_summary", {"query": query_args("cost_record", operation="aggregate")}, scope
        )
    with pytest.raises(ToolBudgetError):
        await harness.registry.invoke(
            "get_cost_summary", {"query": query_args("cost_record")}, scope
        )
    assert harness.metrics.domains_queried == []


async def test_wall_clock_budget_is_enforced(
    scope_factory: ScopeFactory, query_args: QueryArgs
) -> None:
    async def slow(scope: IdentityScope, args: SearchCatalogArgs) -> ToolResult:
        await asyncio.sleep(5)
        raise AssertionError("budget did not stop the tool")

    registry = ToolRegistry(
        [ToolSpec("slow", "test", SearchCatalogArgs, Permission.DATA_READ, slow)]
    )
    query = query_args("agent")
    query["budget"]["timeout_ms"] = 20
    with pytest.raises(ToolTimeoutError):
        await registry.invoke("slow", {"query": query}, analyst(scope_factory))


def test_duplicate_tool_names_are_rejected() -> None:
    async def noop(scope: IdentityScope, args: SearchCatalogArgs) -> ToolResult:
        raise AssertionError

    spec = ToolSpec("dup", "test", SearchCatalogArgs, Permission.DATA_READ, noop)
    with pytest.raises(ValueError, match="duplicate"):
        ToolRegistry([spec, spec])


# -- propose_action cannot confirm or execute ------------------------------------------------------


def test_action_drafter_exposes_only_draft() -> None:
    public = {
        name
        for name, member in inspect.getmembers(ActionDrafter, callable)
        if not name.startswith("_")
    }
    assert public == {"draft"}


def test_no_confirm_or_execute_surface_in_the_registry(harness: Harness) -> None:
    banned = ("confirm", "execute", "approve", "apply", "decline")
    for spec in harness.registry.manifest():
        assert not any(b in spec.name for b in banned), spec.name
        assert not any(b in f for f in spec.args_model.model_fields for b in banned), spec.name


async def test_propose_action_only_drafts(harness: Harness, scope_factory: ScopeFactory) -> None:
    raw = {
        "action_kind": "rename_agent",
        "target": {
            "canonical_id": "commercial:contoso:foundry:agent:fin-1",
            "entity_type": "agent",
        },
        "target_version": "caller-etag",
        "proposed_diff": {
            "format": "json_patch",
            "operations": [{"op": "replace", "path": "/display_name", "value": "Renamed"}],
        },
    }
    scope = analyst(scope_factory)
    first = await harness.registry.invoke("propose_action", raw, scope)
    second = await harness.registry.invoke("propose_action", raw, scope)

    (req, _) = harness.drafter.requests
    assert req.channel == "chat"
    assert req.dry_run is False
    # Same change, same server-derived idempotency key: a retry cannot create a second intent.
    assert (
        harness.drafter.requests[0].idempotency_key == harness.drafter.requests[1].idempotency_key
    )
    record = first.records[0]
    assert record.kind == "action_intent"
    assert record.data["state"] == "drafted"
    assert record.data["next_step"] == "confirm_in_ui"
    assert "confirmation_hash" not in record.data
    assert first.citations[0].record_id == second.citations[0].record_id

    # The model cannot choose the idempotency key, channel or dry-run flag.
    for key in ("idempotency_key", "channel", "dry_run", "state", "confirmation_hash"):
        with pytest.raises(ArgumentNotAllowedError):
            await harness.registry.invoke("propose_action", {**raw, key: "x"}, scope)
    assert len(harness.drafter.requests) == 2


async def test_propose_action_for_missing_target_is_forbidden(
    harness: Harness, scope_factory: ScopeFactory
) -> None:
    raw = {
        "action_kind": "rename_agent",
        "target": {"canonical_id": "commercial:contoso:foundry:agent:nope", "entity_type": "agent"},
        "target_version": "caller-etag",
        "proposed_diff": {
            "format": "json_patch",
            "operations": [{"op": "replace", "path": "/display_name", "value": "X"}],
        },
    }
    with pytest.raises(ForbiddenError):
        await harness.registry.invoke("propose_action", raw, analyst(scope_factory))
    assert harness.drafter.requests == []
