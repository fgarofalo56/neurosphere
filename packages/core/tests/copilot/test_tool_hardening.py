"""PRP-19 round 2 item 14: evidence refs, empty ``in`` lists and real catalog scope hiding."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import pytest
from neurosphere_contracts.catalog.v1.agent import Agent
from neurosphere_core.catalog.repo import InMemoryCatalogRepository
from neurosphere_core.copilot.tools import (
    ToolBudgetError,
    ToolDependencies,
    build_default_registry,
)
from neurosphere_core.errors import ForbiddenError, InvalidSchemaError
from neurosphere_core.scope import IdentityScope

if TYPE_CHECKING:
    from conftest import Harness  # pyright: ignore[reportMissingImports]

FINANCE = "commercial:contoso:catalog:domain:finance"
OPERATIONS = "commercial:contoso:catalog:domain:operations"
ScopeFactory = Callable[[list[tuple[str, list[str]]], list[str]], IdentityScope]
QueryArgs = Callable[..., dict[str, Any]]


def propose(agent: str, *evidence: tuple[str, str]) -> dict[str, Any]:
    return {
        "action_kind": "rename_agent",
        "target": {
            "canonical_id": f"commercial:contoso:foundry:agent:{agent}",
            "entity_type": "agent",
        },
        "target_version": "caller-etag",
        "proposed_diff": {
            "format": "json_patch",
            "operations": [{"op": "replace", "path": "/display_name", "value": "Renamed"}],
        },
        "evidence": [
            {"evidence_id": eid, "kind": "document", "ref": ref, "observed_at": None}
            for eid, ref in evidence
        ],
    }


async def test_unresolvable_evidence_ref_is_refused_with_no_draft(
    harness: Harness, scope_factory: ScopeFactory, caplog: pytest.LogCaptureFixture
) -> None:
    scope = scope_factory([("analyst", [FINANCE])], [FINANCE, OPERATIONS])
    caplog.set_level(logging.WARNING, logger="neurosphere.copilot.tools")
    with pytest.raises(ForbiddenError) as err:
        await harness.registry.invoke(
            "propose_action", propose("fin-1", ("ev-fin", "doc-1"), ("ev-invented", "x")), scope
        )
    assert err.value.reason == "evidence_ref_unresolved"
    assert harness.drafter.requests == []
    assert "ev-invented" not in caplog.text


async def test_evidence_from_another_domain_does_not_resolve(
    harness: Harness, scope_factory: ScopeFactory
) -> None:
    scope = scope_factory([("analyst", [FINANCE, OPERATIONS])], [FINANCE, OPERATIONS])
    with pytest.raises(ForbiddenError):
        await harness.registry.invoke(
            "propose_action", propose("fin-1", ("ev-ops", "doc-2")), scope
        )
    assert harness.drafter.requests == []


async def test_resolving_evidence_refs_draft_as_before(
    harness: Harness, scope_factory: ScopeFactory
) -> None:
    scope = scope_factory([("analyst", [FINANCE])], [FINANCE])
    result = await harness.registry.invoke(
        "propose_action", propose("fin-1", ("ev-fin", "doc-1")), scope
    )
    assert result.records[0].data["state"] == "drafted"
    assert len(harness.drafter.requests) == 1
    assert harness.evidence.domains_seen == [(FINANCE,)]


@pytest.mark.parametrize(
    ("tool", "entity", "field"),
    [
        ("search_catalog", "agent", "lifecycle_status"),
        ("search_catalog", "agent", "domain_id"),
        ("list_recommendations", "recommendation", "kind"),
    ],
)
@pytest.mark.parametrize("shape", ["empty_list", "no_values"])
async def test_empty_in_list_is_refused_not_treated_as_no_filter(
    harness: Harness,
    scope_factory: ScopeFactory,
    query_args: QueryArgs,
    tool: str,
    entity: str,
    field: str,
    shape: str,
) -> None:
    scope = scope_factory([("viewer", [FINANCE])], [FINANCE])
    flt: dict[str, Any] = {"field": field, "op": "in"}
    if shape == "empty_list":
        flt["values"] = []
    query = query_args(entity, filters=[flt])
    # An explicit empty list is refused by the contract (InvalidSchemaError); an ``in`` filter
    # with no values at all passes the contract and is refused by the tool layer.
    with pytest.raises(InvalidSchemaError) as err:
        await harness.registry.invoke(tool, {"query": query}, scope)
    if shape == "no_values":
        assert isinstance(err.value, ToolBudgetError)
        assert err.value.reason == "empty_filter_values"
    assert harness.catalog.seen_filters == []
    assert harness.recs.domains_queried == []


async def test_real_catalog_hides_unreadable_entity_from_the_tools(
    harness: Harness, scope_factory: ScopeFactory, query_args: QueryArgs
) -> None:
    from conftest import _agent  # pyright: ignore[reportMissingImports,reportPrivateUsage]

    repo = InMemoryCatalogRepository()
    admin = scope_factory([("admin", [FINANCE, OPERATIONS])], [FINANCE, OPERATIONS])
    hidden: Agent = _agent("ops-1", OPERATIONS)
    await repo.create_entity(admin, hidden)

    finance_only = scope_factory([("analyst", [FINANCE])], [FINANCE])
    assert await repo.get_entity(finance_only, hidden.id) is None
    assert await repo.get_entity(admin, hidden.id) is not None

    deps = ToolDependencies(
        catalog=repo,
        metrics=harness.metrics,
        recommendations=harness.recs,
        evidence=harness.evidence,
        drafter=harness.drafter,
    )
    registry = build_default_registry(deps)
    with pytest.raises(ForbiddenError) as err:
        await registry.invoke("propose_action", propose("ops-1"), finance_only)
    assert err.value.reason == "target_out_of_scope"
    assert harness.drafter.requests == []

    found = await registry.invoke("search_catalog", {"query": query_args("agent")}, finance_only)
    assert hidden.id not in {r.record_id for r in found.records}
