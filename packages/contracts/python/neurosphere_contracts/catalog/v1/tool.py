# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, StrictStr

from . import common


class McpServerRef(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(max_length=512, min_length=1)] = None


class Tool(BaseModel):
    """
    Callable tool exposed to agents (function, API, MCP tool, search, code interpreter). Python validators: validate_canonical_id_fullmatch (Python re.search lets '$' match before a trailing newline; the suite re-checks every canonical ID with re.fullmatch), validate_customer_segment_matches (customer segment of every canonical ID equals customer_id), validate_timestamp_order (created_at <= updated_at).
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schema_version: common.SchemaVersion
    id: Annotated[
        StrictStr,
        Field(
            max_length=512,
            pattern="^(commercial|government):[a-z0-9._-]+:[a-z0-9._-]+:tool:[a-z0-9._/=-]+$",
        ),
    ]
    """
    Stable canonical ID of this entity. Canonical ID (canonical_id.schema.json) whose type segment is 'tool'.
    """
    entity_type: Literal["tool"]
    version: common.EntityVersion
    etag: common.Etag
    lifecycle_status: common.LifecycleStatus
    created_at: common.Timestamp
    updated_at: common.Timestamp
    cloud: common.Cloud
    customer_id: common.CustomerId
    domain_id: common.DomainId
    classification: Annotated[common.Classification | None, Field(validate_default=True)] = (
        "unknown"
    )
    residency_region: common.Token | None = None
    """
    Azure region holding the authoritative copy; null when unknown.
    """
    attributes: common.Attributes | None = None
    display_name: common.DisplayName
    tool_kind: (
        Literal[
            "function",
            "api",
            "mcp_tool",
            "search",
            "code_interpreter",
            "other",
            "unknown",
        ]
        | None
    ) = "unknown"
    side_effects: Literal["read_only", "writes", "unknown"] | None = "unknown"
    source_id: common.Token
    mcp_server_ref: McpServerRef | None = None
