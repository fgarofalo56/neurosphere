"""Request and response models of the catalog API (PRP-10 item 5).

Every model forbids extra fields. Lineage requests carry no ``view``: the API only serves the
PRESENTED lineage (raw observed edges are Auditor evidence and live under curation).
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from neurosphere_contracts.query.v1.budget import Budget
from neurosphere_core.catalog.protocol import (
    CanonicalIdStr,
    CatalogEntity,
    Direction,
    EdgeFilter,
)
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr

__all__ = [
    "MAX_IMPORT_ITEMS",
    "MAX_STALE_CANDIDATES",
    "ExportPage",
    "ImportItemResult",
    "ImportRequest",
    "ImportResult",
    "LineageImpactRequest",
    "LineageNeighborsRequest",
    "PlanRef",
    "RecertificationItem",
    "RecertificationPage",
    "RecertifyRequest",
    "StaleAgentConfirm",
    "StaleAgentOutcome",
    "StaleAgentPlan",
    "StaleAgentRequest",
    "StaleCandidate",
    "StaleItemResult",
]

MAX_IMPORT_ITEMS = 100
MAX_STALE_CANDIDATES = 500


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- lineage


class LineageNeighborsRequest(_Model):
    """Neighbors of one node in the presented lineage, bounded by ``budget``."""

    node_id: CanonicalIdStr
    direction: Direction = "both"
    filters: EdgeFilter = Field(default_factory=EdgeFilter)
    budget: Budget


class LineageImpactRequest(_Model):
    """Bounded impact paths (downstream = edges out) in the presented lineage."""

    node_id: CanonicalIdStr
    direction: Literal["downstream", "upstream"] = "downstream"
    filters: EdgeFilter = Field(default_factory=EdgeFilter)
    budget: Budget


# --------------------------------------------------------------------------- import / export


class ImportRequest(_Model):
    """A bounded batch of entity documents. ``dry_run`` validates and reports, writing nothing."""

    items: Annotated[list[dict[str, Any]], Field(min_length=1, max_length=MAX_IMPORT_ITEMS)]
    dry_run: StrictBool = False


class ImportItemResult(_Model):
    index: StrictInt
    id: StrictStr | None = None
    status: Literal["valid", "created", "rejected", "failed", "skipped"]
    code: StrictStr | None = None
    """Machine code (error code or reason) for ``rejected`` and ``failed`` items."""


class ImportResult(_Model):
    """Per-item outcome. ``committed`` is True only when every item was created.

    Validation is all-or-report: when any item is ``rejected`` nothing is written. A failure
    while writing (a race the validation could not see) marks that item ``failed`` and the rest
    ``skipped``; items already ``created`` stay created and are listed.
    """

    committed: StrictBool
    dry_run: StrictBool
    items: list[ImportItemResult]


class ExportPage(_Model):
    """One page of the scope-filtered export. Page through ``next_cursor``."""

    exported_at: StrictStr
    domains: list[StrictStr]
    """Domains the export covered: the caller's ``data.export`` domains, narrowed by the filter."""
    items: list[CatalogEntity]
    next_cursor: StrictStr | None = None


# --------------------------------------------------------------------------- recertification


class RecertifyRequest(_Model):
    """Record a recertification of an owner; it is valid for ``valid_for_days`` from now."""

    valid_for_days: Annotated[StrictInt, Field(ge=1, le=730)]


class RecertificationItem(_Model):
    owner_id: CanonicalIdStr
    domain_id: CanonicalIdStr
    owner_kind: StrictStr
    recertified_at: StrictStr | None
    recertify_by: StrictStr
    state: Literal["due", "overdue"]
    days_until_due: StrictInt
    """Negative when overdue."""


class RecertificationPage(_Model):
    items: list[RecertificationItem]
    scanned: StrictInt
    next_cursor: StrictStr | None = None


# --------------------------------------------------------------------------- stale agents


class StaleAgentRequest(_Model):
    """Dry-run: agents with no observation (edge ``last_observed``) within ``window_days``."""

    window_days: Annotated[StrictInt, Field(ge=1, le=3650)]


class StaleCandidate(_Model):
    agent_id: CanonicalIdStr
    etag: StrictStr
    domain_id: CanonicalIdStr
    last_observed: StrictStr


class PlanRef(_Model):
    agent_id: CanonicalIdStr
    etag: StrictStr


class StaleAgentPlan(_Model):
    """Dry-run result. Nothing was changed. Send ``plan_id``, ``as_of``, ``window_days`` and the
    ``candidates`` back to confirm; the server re-derives the set and refuses any difference."""

    plan_id: StrictStr
    as_of: StrictStr
    window_days: StrictInt
    candidates: list[StaleCandidate]
    truncated: StrictBool = False
    """True when the bounded scan stopped early; confirm is refused for a truncated plan."""


class StaleAgentConfirm(_Model):
    plan_id: Annotated[StrictStr, Field(max_length=128)]
    as_of: Annotated[StrictStr, Field(max_length=64)]
    window_days: Annotated[StrictInt, Field(ge=1, le=3650)]
    candidates: Annotated[list[PlanRef], Field(max_length=MAX_STALE_CANDIDATES)]


class StaleItemResult(_Model):
    agent_id: CanonicalIdStr
    status: Literal["marked", "failed"]
    code: StrictStr | None = None
    etag: StrictStr | None = None


class StaleAgentOutcome(_Model):
    plan_id: StrictStr
    items: list[StaleItemResult]
