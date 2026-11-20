"""Request and response models of the catalog access routes (PRP-73 item 3).

API-local on purpose (not contracts): PRP-70 owns ``packages/contracts`` and the copilot tool
builds on the core engine, not on a schema. Class names are prefixed ``Access`` and stay stable
because FastAPI publishes them as ``openapi.json`` components.

Requests forbid extra fields, like every other catalog request model (lineage included). There is
deliberately NO customer, cloud or domain-scope field: the scope comes only from the server
identity, and ``filters.domain_ids`` narrows within that scope, it never widens it.
"""

from __future__ import annotations

from typing import Annotated, Literal

from neurosphere_contracts.catalog.v1.common import SensitivityCategory
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, field_validator

__all__ = [
    "MAX_REQUEST_ASSET_IDS",
    "AccessAssetView",
    "AccessBoundView",
    "AccessBudgetIn",
    "AccessDependentsRequest",
    "AccessDependentsResponse",
    "AccessDepthGroup",
    "AccessFiltersIn",
    "AccessQueryRequest",
    "AccessQueryResponse",
    "AccessRowView",
    "RegionGroupView",
    "RegionGroupsResponse",
]

#: A transport guard well above the engine's ``MAX_ASSET_IDS`` (50), so that 51 to this many ids
#: still reach the engine and answer with the ``too_many_assets`` reason code.
MAX_REQUEST_ASSET_IDS = 500
_MAX_TOKEN = 512

AccessModeName = Literal["read", "write"]
AccessTruncatedReason = Literal["max_assets", "max_accessors", "max_depth", "timeout_ms"]


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Response(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- requests


class AccessBudgetIn(_Request):
    """Optional budget. Every value can only LOWER the fixed server ceiling, never raise it."""

    timeout_ms: Annotated[StrictInt | None, Field(ge=1, le=30000)] = None
    max_assets: Annotated[StrictInt | None, Field(ge=1, le=5000)] = None
    max_accessors: Annotated[StrictInt | None, Field(ge=1, le=1000)] = None


class AccessFiltersIn(_Request):
    """Asset predicates, combined with AND. ``domain_ids`` narrows inside the caller's scope."""

    classifications: list[Annotated[StrictStr, Field(max_length=64)]] | None = Field(
        default=None, max_length=50
    )
    sensitivity_categories: list[StrictStr] | None = Field(default=None, max_length=20)
    contains_personal_data: StrictBool | None = None
    residency_regions: list[Annotated[StrictStr, Field(max_length=128)]] | None = Field(
        default=None, max_length=100
    )
    region_group: Annotated[StrictStr | None, Field(max_length=64)] = None
    domain_ids: list[Annotated[StrictStr, Field(max_length=_MAX_TOKEN)]] | None = Field(
        default=None, max_length=100
    )

    @field_validator("sensitivity_categories")
    @classmethod
    def _known_categories(cls, value: list[str] | None) -> list[str] | None:
        """Names outside the contract vocabulary fail schema validation (422)."""
        if value is None:
            return None
        return [SensitivityCategory.model_validate(v).root for v in value]


class AccessQueryRequest(_Request):
    """Who read or wrote the selected in-scope data assets (observed edges)."""

    asset_ids: list[Annotated[StrictStr, Field(max_length=_MAX_TOKEN)]] = Field(
        default_factory=list, max_length=MAX_REQUEST_ASSET_IDS
    )
    filters: AccessFiltersIn = Field(default_factory=AccessFiltersIn)
    modes: list[AccessModeName] = Field(default_factory=lambda: ["read", "write"], max_length=2)
    include_unassessed: StrictBool = False
    budget: AccessBudgetIn | None = None


class AccessDependentsRequest(_Request):
    """Entities that depend on a failing node, to ``max_depth`` (1 to 5; others answer 422)."""

    node_id: Annotated[StrictStr, Field(min_length=1, max_length=_MAX_TOKEN)]
    max_depth: StrictInt = 3
    budget: AccessBudgetIn | None = None


# --------------------------------------------------------------------------- responses


class AccessBoundView(_Response):
    """The bounds this answer ran under (after any lowering by the request)."""

    max_assets: int
    max_accessors: int
    timeout_ms: int
    max_depth: int | None = None


class AccessAssetView(_Response):
    """An in-scope asset and the values the question looked at; null means not assessed."""

    id: str
    display_name: str
    domain_id: str | None
    classification: str | None
    residency_region: str | None
    contains_personal_data: bool | None
    sensitivity_categories: list[str] | None


class AccessRowView(_Response):
    """One accessor (query) or one dependent (dependents), with its edge evidence.

    ``mode`` is null for dependents. ``relation_path`` and ``path_node_ids`` run from the
    dependent toward the node (``path_node_ids`` ends at ``asset_id``).
    """

    asset_id: str
    accessor_id: str
    accessor_type: str
    accessor_name: str
    accessor_domain_id: str | None
    mode: AccessModeName | None
    relation: str
    edge_id: str
    status: Literal["asserted", "inferred", "curated"]
    confidence: float
    provenance_method: str
    provenance_source_id: str
    evidence_ids: list[str]
    last_observed: str
    depth: int
    relation_path: list[str]
    path_node_ids: list[str]


class AccessQueryResponse(_Response):
    """A bounded answer. ``truncated`` true means partial: a bound stopped the scan."""

    rows: list[AccessRowView]
    assets: list[AccessAssetView]
    unassessed_assets: list[AccessAssetView] | None
    unassessed_count: int | None
    truncated: bool
    truncated_reason: AccessTruncatedReason | None
    assets_scanned: int
    bound: AccessBoundView


class AccessDepthGroup(_Response):
    """Dependents at one distance from the failing node."""

    depth: int
    rows: list[AccessRowView]


class AccessDependentsResponse(_Response):
    """Dependents grouped by depth, shallowest first. A truncated answer is partial."""

    groups: list[AccessDepthGroup]
    total: int
    truncated: bool
    truncated_reason: AccessTruncatedReason | None
    assets_scanned: int
    bound: AccessBoundView


class RegionGroupView(_Response):
    """A named region group and its member region names."""

    name: str
    regions: list[str]


class RegionGroupsResponse(_Response):
    """Groups available for the caller's cloud (empty member lists for Government)."""

    groups: list[RegionGroupView]
