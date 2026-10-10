# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, StrictBool, StrictStr

from . import common


class ResourceRef(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(max_length=1024, min_length=1)] = None
    """
    Provider resource reference; a pointer, never fetched.
    """


class GroundingSource(BaseModel):
    """
    GroundingSource/DataAsset: a data asset read, written or used for grounding (index, store, table, file share, knowledge base). One schema covers both names. Python validators: validate_canonical_id_fullmatch (Python re.search lets '$' match before a trailing newline; the suite re-checks every canonical ID with re.fullmatch), validate_customer_segment_matches (customer segment of every canonical ID equals customer_id), validate_timestamp_order (created_at <= updated_at).
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schema_version: common.SchemaVersion
    id: Annotated[
        StrictStr,
        Field(
            max_length=512,
            pattern="^(commercial|government):[a-z0-9._-]+:[a-z0-9._-]+:grounding_source:[a-z0-9._/=-]+$",
        ),
    ]
    """
    Stable canonical ID of this entity. Canonical ID (canonical_id.schema.json) whose type segment is 'grounding_source'.
    """
    entity_type: Literal["grounding_source"]
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
    asset_kind: (
        Literal[
            "search_index",
            "vector_store",
            "database",
            "table",
            "file_store",
            "knowledge_base",
            "api",
            "other",
            "unknown",
        ]
        | None
    ) = "unknown"
    source_id: common.Token
    resource_ref: ResourceRef | None = None
    """
    Provider resource reference; a pointer, never fetched.
    """
    contains_personal_data: StrictBool | None = None
    """
    null when not assessed.
    """
