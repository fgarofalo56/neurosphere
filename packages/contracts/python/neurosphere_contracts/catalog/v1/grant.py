# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    StrictBool,
    StrictInt,
    StrictStr,
)

from . import common


class Principal(BaseModel):
    """
    The Entra principal the grant applies to. Gateways match object_id against the token 'oid' claim (user, application, agent) or the 'groups' claim (entra_group).
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    kind: Literal["user", "application", "agent", "entra_group"]
    object_id: Annotated[
        StrictStr,
        Field(pattern="^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"),
    ]
    """
    Entra object ID (GUID) of the principal, lowercase hyphenated form (claims are compared as exact strings). A pattern rather than format uuid keeps the generated models wire-exact strings.
    """
    display: common.DisplayName | None = None
    """
    Label of an application, agent or group. Must be null for a user principal: person names are never stored in the catalog.
    """


class Target(BaseModel):
    """
    What the principal may call. ref is the canonical ID of the target catalog entity; its type segment follows kind (model_api -> service, model_deployment -> model_deployment, mcp_server -> mcp_server).
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    kind: Literal["model_api", "model_deployment", "mcp_server"]
    ref: Annotated[
        StrictStr,
        Field(
            max_length=512,
            pattern="^(commercial|government):[a-z0-9._-]+:[a-z0-9._-]+:(service|model_deployment|mcp_server):[a-z0-9._/=-]+$",
        ),
    ]
    """
    Target entity. Canonical ID (canonical_id.schema.json) whose type segment is 'service' or 'model_deployment' or 'mcp_server'.
    """


class TokensPerMinute(RootModel[StrictInt]):
    root: Annotated[StrictInt, Field(ge=1)] = None
    """
    Token rate limit (model targets only).
    """


class TokenQuota(RootModel[StrictInt]):
    root: Annotated[StrictInt, Field(ge=1)] = None
    """
    Token quota per quota_period (model targets only); set together with quota_period.
    """


class RequestsPerMinute(RootModel[StrictInt]):
    root: Annotated[StrictInt, Field(ge=1)] = None
    """
    Request rate limit (model targets only).
    """


class McpCallsPerMinute(RootModel[StrictInt]):
    root: Annotated[StrictInt, Field(ge=1)] = None
    """
    MCP call rate limit (mcp_server targets only).
    """


class Limits(BaseModel):
    """
    Usage limits; null means no limit of that kind is declared. Token limits apply to model targets only; MCP grants are call-limited only.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    tokens_per_minute: TokensPerMinute | None = None
    """
    Token rate limit (model targets only).
    """
    token_quota: TokenQuota | None = None
    """
    Token quota per quota_period (model targets only); set together with quota_period.
    """
    quota_period: Literal["minute", "hour", "day", "week", "month", "year"] | None = None
    """
    Period of token_quota; set together with token_quota.
    """
    requests_per_minute: RequestsPerMinute | None = None
    """
    Request rate limit (model targets only).
    """
    mcp_calls_per_minute: McpCallsPerMinute | None = None
    """
    MCP call rate limit (mcp_server targets only).
    """


class CostCenter(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(pattern="^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")] = None
    """
    Cost center usage under this grant is attributed to; null when not assigned. Restricted to characters safe in an HTTP header and a metric dimension.
    """


class Grant(BaseModel):
    """
    Access grant of one Entra principal (user, application, agent or Entra group) to one target (a model API, a model deployment or an MCP server) with optional usage limits and a cost center. It is the unit a gateway enforces (PRP-34); this document is desired state only and records no enforcement. Cross-field rules enforced in this schema: target.ref carries the type segment of target.kind (model_api is a 'service' entity, model_deployment a 'model_deployment', mcp_server an 'mcp_server'); MCP grants are call-limited only (tokens_per_minute, token_quota, quota_period and requests_per_minute must be null) and model grants carry no mcp_calls_per_minute; token_quota and quota_period are set together; a user principal carries no display label (person names are never stored). The generated Pydantic model does not carry these conditionals (ADR-0004); JSON Schema is the source of truth. Python validators: validate_canonical_id_fullmatch (Python re.search lets '$' match before a trailing newline; the suite re-checks every canonical ID with re.fullmatch), validate_customer_segment_matches (customer segment of every canonical ID equals customer_id), validate_timestamp_order (created_at <= updated_at), validate_grant_window (valid_from < valid_until when both are set).
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schema_version: common.SchemaVersion
    id: Annotated[
        StrictStr,
        Field(
            max_length=512,
            pattern="^(commercial|government):[a-z0-9._-]+:[a-z0-9._-]+:grant:[a-z0-9._/=-]+$",
        ),
    ]
    """
    Stable canonical ID of this entity. Canonical ID (canonical_id.schema.json) whose type segment is 'grant'. The owning domain is domain_id, as for every catalog entity.
    """
    entity_type: Literal["grant"]
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
    principal: Principal
    """
    The Entra principal the grant applies to. Gateways match object_id against the token 'oid' claim (user, application, agent) or the 'groups' claim (entra_group).
    """
    target: Target
    """
    What the principal may call. ref is the canonical ID of the target catalog entity; its type segment follows kind (model_api -> service, model_deployment -> model_deployment, mcp_server -> mcp_server).
    """
    limits: Limits
    """
    Usage limits; null means no limit of that kind is declared. Token limits apply to model targets only; MCP grants are call-limited only.
    """
    cost_center: CostCenter | None = None
    """
    Cost center usage under this grant is attributed to; null when not assigned. Restricted to characters safe in an HTTP header and a metric dimension.
    """
    enabled: StrictBool
    """
    false suspends the grant without deleting it.
    """
    valid_from: common.Timestamp | None = None
    """
    Start of the grant; null means effective immediately.
    """
    valid_until: common.Timestamp | None = None
    """
    End of the grant (exclusive); null means open-ended.
    """
    provenance: common.Provenance
