"""PRP-70 item 4: map/v1 fragment schemas (MapNodeFacets, MapTopologyChange).

JSON Schema is the source of truth; the Pydantic assertions cover what the shape projection keeps
(extra="forbid", numeric bounds, enums, array bounds, defaults).
"""

from __future__ import annotations

import copy
from typing import Any

import pydantic
import pytest
from contract_support import SCHEMA_ROOT, load_json, model_for, schema_errors

VALID = SCHEMA_ROOT / "map" / "v1" / "examples" / "valid"
FACETS = "map/v1/map-node-facets.schema.json"
CHANGE = "map/v1/map-topology-change.schema.json"
ID_PREFIX = "commercial:contoso:foundry:agent:"


def _facets() -> dict[str, Any]:
    return copy.deepcopy(load_json(VALID / "map-node-facets.degraded-agent.json"))


def _change() -> dict[str, Any]:
    return copy.deepcopy(load_json(VALID / "map-topology-change.node-and-edge.json"))


def _both_reject(rel: str, doc: dict[str, Any]) -> None:
    assert schema_errors(rel, doc), "JSON Schema must reject"
    with pytest.raises(pydantic.ValidationError):
        model_for(rel).model_validate(doc)


def _both_accept(rel: str, doc: dict[str, Any]) -> None:
    assert schema_errors(rel, doc) == []
    model_for(rel).model_validate(doc)


@pytest.mark.parametrize("bad", [1.5, -0.1])
def test_error_rate_outside_unit_interval_is_rejected(bad: float) -> None:
    doc = _facets()
    doc["error_rate"] = bad
    _both_reject(FACETS, doc)


def test_unknown_health_is_rejected() -> None:
    doc = _facets()
    doc["health"] = "broken"
    _both_reject(FACETS, doc)


def test_unknown_key_is_rejected() -> None:
    doc = _facets()
    doc["extra"] = 1
    _both_reject(FACETS, doc)


def test_negative_counts_are_rejected() -> None:
    for key in ("error_count", "request_count"):
        doc = _facets()
        doc[key] = -1
        _both_reject(FACETS, doc)


def test_null_numerics_are_accepted_and_zero_is_a_real_zero() -> None:
    doc = _facets()
    doc.update(error_rate=None, error_count=None, request_count=None, last_error_at=None)
    _both_accept(FACETS, doc)
    model = model_for(FACETS).model_validate(doc)
    assert model.error_rate is None
    assert model.error_count is None
    assert model.request_count is None
    doc.update(error_rate=0, error_count=0, request_count=0)
    _both_accept(FACETS, doc)


def test_empty_facets_validate_and_default_to_unknown() -> None:
    _both_accept(FACETS, {})
    model = model_for(FACETS).model_validate({})
    assert model.discovery == "unknown"
    assert model.health == "unknown"
    assert model.error_rate is None
    assert model.entity_type is None


def test_facets_schema_has_no_schema_version_and_nothing_required() -> None:
    schema = load_json(SCHEMA_ROOT / FACETS)
    assert "schema_version" not in schema["properties"]
    assert schema.get("required", []) == []
    assert schema["properties"]["discovery"]["default"] == "unknown"
    assert schema["properties"]["health"]["default"] == "unknown"


def test_topology_change_rejects_empty_change_kinds() -> None:
    doc = _change()
    doc["change_kinds"] = []
    _both_reject(CHANGE, doc)


def test_topology_change_rejects_more_than_fifty_entity_ids() -> None:
    doc = _change()
    doc["entity_ids"] = [f"{ID_PREFIX}a{i}" for i in range(51)]
    _both_reject(CHANGE, doc)
    doc["entity_ids"] = [f"{ID_PREFIX}a{i}" for i in range(50)]
    _both_accept(CHANGE, doc)


def test_topology_change_rejects_unknown_kind_and_duplicates() -> None:
    doc = _change()
    doc["change_kinds"] = ["node_moved"]
    _both_reject(CHANGE, doc)
    doc["change_kinds"] = ["node_added", "node_added"]
    assert schema_errors(CHANGE, doc)


def test_topology_change_rejects_unknown_key() -> None:
    doc = _change()
    doc["extra"] = True
    _both_reject(CHANGE, doc)
