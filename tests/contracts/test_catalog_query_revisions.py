"""PRP-37 item 3 revisions to the query and catalog contracts.

* StructuredQuery accepts the ``grant`` and ``mcp_server`` entities and the
  ``grants_access_to`` relation, and ``FIELD_APPLICABILITY`` has rows for them (#148 item 1).
* Every catalog relation schema requires ``provenance`` through
  ``common.schema.json#/$defs/provenance`` (#195 provenance bullet, contract half; populating
  it in PresentedEdge is PRP-43).
"""

from __future__ import annotations

import copy
from typing import Any

import pytest
import validators as v
from contract_support import (
    SCHEMA_ROOT,
    load_json,
    load_schema,
    model_for,
    schema_errors,
    schema_files,
)

QUERY = "query/v1/structured-query.schema.json"
EXAMPLES = SCHEMA_ROOT / "query" / "v1" / "examples" / "valid"


def _list_agents() -> dict[str, Any]:
    return load_json(EXAMPLES / "structured-query.list-agents.json")


@pytest.mark.parametrize("entity", ["grant", "mcp_server"])
def test_grant_and_mcp_server_are_queryable(entity: str) -> None:
    query = {**_list_agents(), "entity": entity}
    assert schema_errors(QUERY, query) == []
    model_for(QUERY).model_validate(query)
    assert v.check_structured_query_field_applicability(query) == []
    assert entity in v.FIELD_APPLICABILITY


def test_unknown_entity_still_rejected() -> None:
    assert schema_errors(QUERY, {**_list_agents(), "entity": "secret_store"})


def _traversal_query() -> dict[str, Any]:
    for path in sorted(EXAMPLES.glob("structured-query.*.json")):
        query = load_json(path)
        if isinstance(query.get("traversal"), dict):
            return query
    raise AssertionError("no traversal example")


def test_grants_access_to_relation_is_traversable() -> None:
    query = copy.deepcopy(_traversal_query())
    query["traversal"]["relations"] = ["grants_access_to"]
    assert schema_errors(QUERY, query) == []
    model_for(QUERY).model_validate(query)


def test_every_catalog_relation_can_be_traversed_at_once() -> None:
    enum = load_schema(QUERY)["$defs"]["traversal"]["properties"]["relations"]["items"]["enum"]
    relations = {load_schema(r)["properties"]["relation_type"]["const"] for r in _relations()}
    assert set(enum) == relations
    query = copy.deepcopy(_traversal_query())
    query["traversal"]["relations"] = sorted(relations)
    assert schema_errors(QUERY, query) == []


def test_catalog_entity_enum_covers_queryable_catalog_entities() -> None:
    enum = set(load_schema(QUERY)["$defs"]["catalog_entity"]["enum"])
    assert {"grant", "mcp_server"} <= enum


def _relations() -> list[str]:
    out = []
    for rel in schema_files():
        if not rel.startswith("catalog/v1/"):
            continue
        schema = load_schema(rel)
        relation_type = schema.get("properties", {}).get("relation_type", {})
        if "const" in relation_type:
            out.append(rel)
    return out


def test_relation_discovery_finds_every_relation() -> None:
    assert len(_relations()) >= 10
    assert "catalog/v1/grants_access_to.schema.json" in _relations()


@pytest.mark.parametrize("rel", _relations())
def test_relation_requires_provenance(rel: str) -> None:
    schema = load_schema(rel)
    assert "provenance" in schema["required"], rel
    assert schema["properties"]["provenance"] == {"$ref": "common.schema.json#/$defs/provenance"}
