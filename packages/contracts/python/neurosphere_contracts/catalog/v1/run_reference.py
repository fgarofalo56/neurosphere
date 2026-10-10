# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, StrictInt, StrictStr

from . import common


class AgentVersionId(RootModel[StrictStr]):
    root: Annotated[
        StrictStr,
        Field(
            max_length=512,
            pattern="^(commercial|government):[a-z0-9._-]+:[a-z0-9._-]+:agent_version:[a-z0-9._/=-]+$",
        ),
    ] = None
    """
    Version, when resolved. Canonical ID (canonical_id.schema.json) whose type segment is 'agent_version'.
    """


class TraceId(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(pattern="^[a-f0-9]{32}$")] = None
    """
    W3C trace ID.
    """


class RequestId(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(max_length=256, min_length=1)] = None


class SpanCount(RootModel[StrictInt]):
    root: Annotated[StrictInt, Field(ge=0)] = None
    """
    Number of spans; null when unknown.
    """


class RunReference(BaseModel):
    """
    Pointer to a run held in the telemetry store. Runs and spans are referenced, never replicated into the graph; no prompt or response body appears here. Python validators: validate_canonical_id_fullmatch (Python re.search lets '$' match before a trailing newline; the suite re-checks every canonical ID with re.fullmatch), validate_customer_segment_matches (customer segment of every canonical ID equals customer_id), validate_timestamp_order (created_at <= updated_at).
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schema_version: common.SchemaVersion
    id: Annotated[
        StrictStr,
        Field(
            max_length=512,
            pattern="^(commercial|government):[a-z0-9._-]+:[a-z0-9._-]+:run_reference:[a-z0-9._/=-]+$",
        ),
    ]
    """
    Stable canonical ID of this entity. Canonical ID (canonical_id.schema.json) whose type segment is 'run_reference'.
    """
    entity_type: Literal["run_reference"]
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
    agent_id: Annotated[
        StrictStr,
        Field(
            max_length=512,
            pattern="^(commercial|government):[a-z0-9._-]+:[a-z0-9._-]+:agent:[a-z0-9._/=-]+$",
        ),
    ]
    """
    Agent that executed the run. Canonical ID (canonical_id.schema.json) whose type segment is 'agent'.
    """
    agent_version_id: AgentVersionId | None = None
    source_run_id: Annotated[StrictStr, Field(max_length=256, min_length=1)]
    trace_id: TraceId | None = None
    """
    W3C trace ID.
    """
    request_id: RequestId | None = None
    started_at: common.Timestamp
    ended_at: common.Timestamp | None = None
    outcome: Literal["success", "error", "cancelled", "timeout", "unknown"] | None = "unknown"
    span_count: SpanCount | None = None
    """
    Number of spans; null when unknown.
    """
