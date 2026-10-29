"""The core catalog protocol duplicates the contract enumerations; keep them in step.

``protocol.py`` re-declares ``EntityType`` and ``RelationType`` as literals and caps the filter
list lengths at their size. A contract enum change (PRP-33 item 5 added ``grant``,
``mcp_server`` and ``grants_access_to``) that skips the core copy would silently reject the new
values in every filter, so the copies and caps are compared with the generated contract here.
"""

from __future__ import annotations

from typing import get_args

import pytest
from neurosphere_contracts.catalog.v1 import common
from neurosphere_core.catalog.protocol import (
    EdgeFilter,
    EntityFilter,
    EntityTypeName,
    RelationTypeName,
)
from pydantic import ValidationError

CONTRACT_ENTITY_TYPES = get_args(common.EntityType.model_fields["root"].annotation)
CONTRACT_RELATION_TYPES = get_args(common.RelationType.model_fields["root"].annotation)


def _max_length(model: type, field: str) -> int:
    for meta in model.model_fields[field].metadata:  # type: ignore[attr-defined]
        if hasattr(meta, "max_length"):
            return int(meta.max_length)
    raise AssertionError(f"{model.__name__}.{field} has no max_length")


def test_entity_type_literal_equals_the_contract_enum() -> None:
    assert get_args(EntityTypeName) == CONTRACT_ENTITY_TYPES
    assert len(CONTRACT_ENTITY_TYPES) == 14
    assert {"grant", "mcp_server"} <= set(CONTRACT_ENTITY_TYPES)


def test_relation_type_literal_equals_the_contract_enum() -> None:
    assert get_args(RelationTypeName) == CONTRACT_RELATION_TYPES
    assert len(CONTRACT_RELATION_TYPES) == 10
    assert "grants_access_to" in CONTRACT_RELATION_TYPES


def test_filter_caps_track_the_enums() -> None:
    # Each cap equals the number of values, so a filter naming every type is accepted.
    assert _max_length(EntityFilter, "entity_types") == len(CONTRACT_ENTITY_TYPES)
    assert _max_length(EdgeFilter, "relation_types") == len(CONTRACT_RELATION_TYPES)
    EntityFilter(entity_types=list(CONTRACT_ENTITY_TYPES))
    EdgeFilter(relation_types=list(CONTRACT_RELATION_TYPES))


def test_filters_accept_the_new_values() -> None:
    assert EntityFilter(entity_types=["grant", "mcp_server"]).entity_types == [
        "grant",
        "mcp_server",
    ]
    assert EdgeFilter(relation_types=["grants_access_to"]).relation_types == ["grants_access_to"]


def test_filters_reject_unknown_values() -> None:
    with pytest.raises(ValidationError):
        EntityFilter(entity_types=["model_api"])  # type: ignore[list-item]
    with pytest.raises(ValidationError):
        EdgeFilter(relation_types=["grants"])  # type: ignore[list-item]
