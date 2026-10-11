"""IdentityScope is output-only (PRP-01 gotcha; PRP.md section 3).

It is derived server-side from a validated identity and the policy store; a caller or a
model can never supply it. So no request schema may reach identity-scope.schema.json
through its ``$ref`` graph (file or fragment refs, transitively), and nothing in the
contract set embeds it today. A future response envelope that legitimately carries the
scope must be added to ``RESPONSES_ALLOWED_TO_EMBED_SCOPE`` with a review.
"""

from __future__ import annotations

import pytest
from contract_support import (
    load_schema,
    reachable_from,
    ref_graph,
    ref_target,
    refs_of,
    schema_files,
)

SCOPE = "scope/v1/identity-scope.schema.json"

# Bodies a client, copilot tool or MCP caller submits (directly or as an embedded part).
REQUEST_SCHEMAS = (
    "query/v1/structured-query.schema.json",
    "query/v1/budget.schema.json",
    "actions/v1/action-intent.schema.json",
    "actions/v1/approval-decision.schema.json",
    "actions/v1/actor.schema.json",
    "actions/v1/target-ref.schema.json",
    "catalog/v1/edge_override.schema.json",
    "catalog/v1/alias.schema.json",
    "chart/v1/chart-plan.schema.json",
    "deployment/v1/deployment-manifest.schema.json",
    "connectors/v1/connector-manifest.schema.json",
)
RESPONSES_ALLOWED_TO_EMBED_SCOPE: frozenset[str] = frozenset()

SCOPE_ONLY_MEMBERS = {"scope_hash", "allowed_domains", "allowed_resources", "derived_at"}


def test_request_schemas_exist() -> None:
    missing = set(REQUEST_SCHEMAS) - set(schema_files())
    assert not missing, missing


@pytest.mark.parametrize("rel", REQUEST_SCHEMAS)
def test_request_schema_cannot_reach_identity_scope(rel: str) -> None:
    reached = reachable_from(rel)
    assert SCOPE not in reached, f"{rel} reaches IdentityScope via $ref ({sorted(reached)})"


@pytest.mark.parametrize("rel", REQUEST_SCHEMAS)
def test_request_schema_has_no_scope_members(rel: str) -> None:
    """No request body declares the scope's own members (a copied shape is still input)."""
    props = set(load_schema(rel).get("properties", {}))
    assert not props & SCOPE_ONLY_MEMBERS, f"{rel} declares {props & SCOPE_ONLY_MEMBERS}"
    assert "identity_scope" not in props and "scope" not in props


@pytest.mark.parametrize("rel", [r for r in schema_files() if r != SCOPE])
def test_no_schema_references_identity_scope(rel: str) -> None:
    """Walk every schema; any $ref into identity-scope (even a fragment) is a violation."""
    if rel in RESPONSES_ALLOWED_TO_EMBED_SCOPE:
        return
    direct = [ref for _, ref in refs_of(rel) if ref_target(rel, ref)[0] == SCOPE]
    assert not direct, f"{rel} references IdentityScope: {direct}"
    assert SCOPE not in reachable_from(rel)


def test_identity_scope_is_marked_read_only() -> None:
    schema = load_schema(SCOPE)
    assert schema.get("readOnly") is True
    assert "OUTPUT-ONLY" in schema["description"]
    assert ref_graph()[SCOPE] == frozenset(), "IdentityScope must be self-contained"


def test_walker_would_catch_a_reference() -> None:
    """Prove the walker resolves relative refs: action-intent reaches actor and target-ref."""
    reached = reachable_from("actions/v1/action-intent.schema.json")
    assert {"actions/v1/actor.schema.json", "actions/v1/target-ref.schema.json"} <= reached
    assert "telemetry/v1/telemetry-event.schema.json" in reachable_from(
        "cost/v1/cost-record.schema.json"
    )
