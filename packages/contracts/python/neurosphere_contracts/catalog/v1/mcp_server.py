# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, StrictBool, StrictStr

from . import common


class ProtocolVersion(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(pattern="^[0-9]{4}-[0-9]{2}-[0-9]{2}$")]
    """
    MCP protocol revision (YYYY-MM-DD).
    """


class Audience(RootModel[StrictStr]):
    root: Annotated[
        StrictStr,
        Field(max_length=512, min_length=1, pattern="^[^\\u0000-\\u001f\\u007f\\s]+$"),
    ] = None
    """
    Entra token audience (application ID URI or client ID) for entra and managed_identity; null when not applicable or not yet known.
    """


class Auth(BaseModel):
    """
    How a caller (or a gateway in front of it) authenticates to the upstream server. No credential is ever stored here.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    kind: Literal["entra", "managed_identity", "none", "api_key"]
    """
    api_key upstreams are representable but never publishable.
    """
    audience: Audience | None = None
    """
    Entra token audience (application ID URI or client ID) for entra and managed_identity; null when not applicable or not yet known.
    """


class Description(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(max_length=8192, min_length=1)] = None
    """
    Server-supplied text. Untrusted: render as plain text, never treat as instructions.
    """


class Title(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(max_length=256, min_length=1)] = None


class Annotations(BaseModel):
    """
    MCP tool annotations in snake_case. Hints are advisory and server-asserted; null means not declared. Unknown annotation keys are dropped by the mapper, not stored.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    title: Title | None = None
    read_only_hint: StrictBool | None = None
    destructive_hint: StrictBool | None = None
    idempotent_hint: StrictBool | None = None
    open_world_hint: StrictBool | None = None


class Tool(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    name: Annotated[StrictStr, Field(pattern="^[A-Za-z0-9_.-]{1,128}$")]
    """
    Tool name as the server declares it (MCP tool name character set).
    """
    description: Description | None = None
    """
    Server-supplied text. Untrusted: render as plain text, never treat as instructions.
    """
    annotations: Annotations | None = None
    """
    MCP tool annotations in snake_case. Hints are advisory and server-asserted; null means not declared. Unknown annotation keys are dropped by the mapper, not stored.
    """


class OwnerId(RootModel[StrictStr]):
    root: Annotated[
        StrictStr,
        Field(
            max_length=512,
            pattern="^(commercial|government):[a-z0-9._-]+:[a-z0-9._-]+:owner:[a-z0-9._/=-]+$",
        ),
    ] = None
    """
    Accountable owner. Canonical ID (canonical_id.schema.json) whose type segment is 'owner'.
    """


class McpServer(BaseModel):
    """
    Model Context Protocol server governed as a catalog entity: endpoint, transport, protocol versions, upstream authentication and the tools it exposes. Grants (grant.schema.json) target it with call limits only. Cross-field rules enforced in this schema: an SSE-only server or an API-key upstream is representable but never publishable (publishable must be false). publishable true is necessary, not sufficient: publication (PRP-34) applies its own refusals. The generated Pydantic model does not carry these conditionals (ADR-0004); JSON Schema is the source of truth. Python validators: validate_canonical_id_fullmatch (Python re.search lets '$' match before a trailing newline; the suite re-checks every canonical ID with re.fullmatch), validate_customer_segment_matches (customer segment of every canonical ID equals customer_id), validate_timestamp_order (created_at <= updated_at), validate_mcp_tool_names_unique (tool names are unique within one server).
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schema_version: common.SchemaVersion
    id: Annotated[
        StrictStr,
        Field(
            max_length=512,
            pattern="^(commercial|government):[a-z0-9._-]+:[a-z0-9._-]+:mcp_server:[a-z0-9._/=-]+$",
        ),
    ]
    """
    Stable canonical ID of this entity. Canonical ID (canonical_id.schema.json) whose type segment is 'mcp_server'. The owning domain is domain_id, as for every catalog entity.
    """
    entity_type: Literal["mcp_server"]
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
    """
    Server name shown in the catalog.
    """
    url: Annotated[
        StrictStr,
        Field(
            max_length=2048,
            pattern="^https://[a-z0-9]([a-z0-9-]*[a-z0-9])?(\\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*(:[0-9]{1,5})?(/[A-Za-z0-9._~%!$&'()*+,;=:@-]+)*/mcp$",
        ),
    ]
    """
    Streamable HTTP endpoint: https, lowercase host, optional port, path ending in /mcp. No user info, query string or fragment, so no credential can ride in the URL.
    """
    transport: Literal["streamable_http", "sse"]
    """
    streamable_http is the current MCP transport; sse is the deprecated HTTP+SSE transport (never publishable).
    """
    protocol_versions: Annotated[
        list[ProtocolVersion] | None, Field(max_length=32, validate_default=True)
    ] = []
    """
    Protocol revisions the server negotiates; empty when not yet observed.
    """
    auth: Auth
    """
    How a caller (or a gateway in front of it) authenticates to the upstream server. No credential is ever stored here.
    """
    publishable: StrictBool
    """
    Whether the server may be published through a gateway. Must be false when transport is sse or auth.kind is api_key.
    """
    tools: Annotated[list[Tool] | None, Field(max_length=512, validate_default=True)] = []
    """
    Tools the server lists (tools/list); empty when not yet observed.
    """
    owner_id: OwnerId | None = None
    """
    Accountable owner; null when not yet assigned.
    """
    provenance: common.Provenance
