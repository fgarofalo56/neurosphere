# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, StrictFloat, StrictInt

from ...catalog.v1 import common


class ErrorRate(RootModel[StrictFloat]):
    root: Annotated[StrictFloat, Field(ge=0.0, le=1.0)] = None
    """
    Share of failed requests in the window, 0 to 1; null when unknown (never 0 for unknown).
    """


class ErrorCount(RootModel[StrictInt]):
    root: Annotated[StrictInt, Field(ge=0)] = None
    """
    Failed requests in the window; null when unknown (never 0 for unknown).
    """


class RequestCount(RootModel[StrictInt]):
    root: Annotated[StrictInt, Field(ge=0)] = None
    """
    Requests in the window; null when unknown (never 0 for unknown).
    """


class MapNodeFacets(BaseModel):
    """
    Filterable facets and health of one live-map node (PRP-70 item 4). A fragment schema without schema_version, like actions/v1/target-ref, so the API and the frontend share one shape. Every member is nullable or defaulted, so none is required. Unknown numeric values (error_rate, error_count, request_count) are null, never 0: a zero means a measured zero.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    entity_type: common.EntityType | None = None
    """
    Catalog entity type of the node; null for cluster nodes.
    """
    environment: Annotated[common.Environment | None, Field(validate_default=True)] = "unknown"
    cloud: common.Cloud | None = None
    """
    Cloud boundary of the node; null when unknown.
    """
    tags: common.Tags | None = None
    lifecycle_status: common.LifecycleStatus | None = None
    """
    Lifecycle state of the node's entity; null when unknown.
    """
    discovery: Literal["declared", "telemetry", "import", "unknown"] | None = "unknown"
    """
    How the node came to be known: declared in the catalog, seen in telemetry, imported, or unknown.
    """
    health: Literal["ok", "degraded", "failing", "unknown"] | None = "unknown"
    """
    Observed health of the node. unknown when there is no telemetry window to judge.
    """
    error_rate: ErrorRate | None = None
    """
    Share of failed requests in the window, 0 to 1; null when unknown (never 0 for unknown).
    """
    error_count: ErrorCount | None = None
    """
    Failed requests in the window; null when unknown (never 0 for unknown).
    """
    request_count: RequestCount | None = None
    """
    Requests in the window; null when unknown (never 0 for unknown).
    """
    last_error_at: common.Timestamp | None = None
    """
    Time of the most recent error; null when none is known.
    """
    sensitivity_categories: common.SensitivityCategories | None = None
    residency_geography: common.ResidencyGeography | None = None
    """
    Coarse geography of the node's data; null when not declared.
    """
