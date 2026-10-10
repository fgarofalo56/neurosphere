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


class ModelVersion(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(max_length=128, min_length=1)] = None


class ContextWindowTokens(RootModel[StrictInt]):
    root: Annotated[StrictInt, Field(ge=0)] = None
    """
    Maximum context window; null when unknown.
    """


class MaxOutputTokens(RootModel[StrictInt]):
    root: Annotated[StrictInt, Field(ge=0)] = None
    """
    Maximum output tokens; null when unknown.
    """


class Sku(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(max_length=128, min_length=1)] = None


class PriceReference(BaseModel):
    """
    Price sheet reference used for estimates; null when unpriced.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    price_version: Annotated[StrictStr, Field(max_length=128, min_length=1)]
    price_effective_date: common.Date


class ModelDeployment(BaseModel):
    """
    Deployed model endpoint with version, modality, context, tool capability and price reference. Unknown capabilities are null, never 0. Python validators: validate_canonical_id_fullmatch (Python re.search lets '$' match before a trailing newline; the suite re-checks every canonical ID with re.fullmatch), validate_customer_segment_matches (customer segment of every canonical ID equals customer_id), validate_timestamp_order (created_at <= updated_at).
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schema_version: common.SchemaVersion
    id: Annotated[
        StrictStr,
        Field(
            max_length=512,
            pattern="^(commercial|government):[a-z0-9._-]+:[a-z0-9._-]+:model_deployment:[a-z0-9._/=-]+$",
        ),
    ]
    """
    Stable canonical ID of this entity. Canonical ID (canonical_id.schema.json) whose type segment is 'model_deployment'.
    """
    entity_type: Literal["model_deployment"]
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
    provider: common.Token
    """
    Model provider token.
    """
    model_name: Annotated[StrictStr, Field(max_length=256, min_length=1)]
    model_version: ModelVersion | None = None
    deployment_name: Annotated[StrictStr, Field(max_length=256, min_length=1)]
    modalities: list[Literal["text", "image", "audio", "video", "embedding", "unknown"]] | None = []
    context_window_tokens: ContextWindowTokens | None = None
    """
    Maximum context window; null when unknown.
    """
    max_output_tokens: MaxOutputTokens | None = None
    """
    Maximum output tokens; null when unknown.
    """
    supports_tool_calling: StrictBool | None = None
    """
    null when unknown.
    """
    region: common.Token | None = None
    sku: Sku | None = None
    price_reference: PriceReference | None = None
    """
    Price sheet reference used for estimates; null when unpriced.
    """
