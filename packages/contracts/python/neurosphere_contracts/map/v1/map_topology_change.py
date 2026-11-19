# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool

from ...catalog.v1 import common


class MapTopologyChange(BaseModel):
    """
    Notice that the live map topology of a domain changed (PRP-70 item 4). A fragment schema without schema_version, like actions/v1/target-ref. It names what changed so a client can refetch; it carries no node or edge bodies. When truncated is true the entity_ids list is partial and the client must refetch.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    domain_id: common.DomainId
    changed_at: common.Timestamp
    change_kinds: Annotated[
        list[
            Literal[
                "node_added",
                "node_removed",
                "node_updated",
                "edge_added",
                "edge_removed",
                "edge_updated",
            ]
        ],
        Field(min_length=1),
    ]
    entity_ids: Annotated[list[common.CanonicalId], Field(max_length=50)]
    """
    Canonical ids of the entities touched; at most 50.
    """
    refetch: StrictBool
    truncated: StrictBool
