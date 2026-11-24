"""Facets of a live-map node (PRP-74 item 1).

``facets_of`` builds the PRP-70 ``MapNodeFacets`` from the catalog entity (environment, cloud,
tags, lifecycle, sensitivity, residency) and the newest subject point (health, error and request
numbers). Unknown stays ``None`` / ``unknown``, never 0. No field here carries a person's real
name: a person yields only the entity-type, cloud and lifecycle facts.

``derive_health`` is the fallback for a service, tool or MCP server that has NO subject point
(clarification 5): an inference from its direct dependents, labelled inferred by the caller, and
it can never say ``ok``.

No ``from __future__ import annotations`` in this package (FastAPI inspects signatures).
"""

from collections.abc import Sequence
from typing import Any

from neurosphere_contracts.map.v1.map_node_facets import MapNodeFacets
from neurosphere_core.aggregates import SubjectPoint, health_for_error_rate
from neurosphere_core.catalog import CatalogEntity

from neurosphere_api.map.models import Health

__all__ = [
    "DERIVED_MIN_DEPENDENTS",
    "DERIVED_RELATIONS",
    "DERIVED_SUBJECT_TYPES",
    "derive_health",
    "facets_of",
]

DERIVED_RELATIONS = frozenset({"depends_on", "invokes"})
"""Edge types whose SOURCE is a dependent of the target."""
DERIVED_SUBJECT_TYPES = frozenset({"service", "tool", "mcp_server"})
DERIVED_MIN_DEPENDENTS = 2
"""At least this many dependents must be failing (or degraded) before anything is inferred."""


def _raw(value: Any) -> Any:
    """Unwrap a pydantic ``RootModel`` value; plain values pass through."""
    return getattr(value, "root", value)


def facets_of(
    entity: CatalogEntity,
    point: SubjectPoint | None,
    *,
    derived_health: Health | None = None,
) -> MapNodeFacets:
    """Facets of one entity node. ``point`` is the measured subject point, if any.

    A measured point always wins; ``derived_health`` is only used when ``point`` is ``None``.
    """
    data: dict[str, Any] = {"entity_type": entity.entity_type}
    for name in (
        "environment",
        "cloud",
        "lifecycle_status",
        "sensitivity_categories",
        "residency_geography",
    ):
        value = _raw(getattr(entity, name, None))
        if value is not None:
            data[name] = value
    tags = _raw(getattr(entity, "tags", None))
    if tags is not None:
        data["tags"] = list(tags)
    if point is not None:
        data["health"] = health_for_error_rate(point.error_rate)
        data["error_rate"] = point.error_rate
        data["error_count"] = point.error_count
        data["request_count"] = point.event_count
    elif derived_health is not None:
        data["health"] = derived_health
    return MapNodeFacets.model_validate(data)


def cluster_facets() -> MapNodeFacets:
    """Facets of a cluster node: everything unknown, ``entity_type`` null."""
    return MapNodeFacets()


def derive_health(
    dependent_health: Sequence[Health],
    *,
    failing_ratio: float,
    degraded_ratio: float,
) -> Health:
    """Inferred health of a node with no subject point, from its direct dependents' health.

    ``failing`` when at least ``failing_ratio`` of the dependents, and at least
    ``DERIVED_MIN_DEPENDENTS`` of them, are failing; ``degraded`` when the same holds for
    degraded-or-worse at ``degraded_ratio``; otherwise ``unknown``. Never ``ok``.
    """
    total = len(dependent_health)
    if total < DERIVED_MIN_DEPENDENTS:
        return "unknown"
    failing = sum(1 for h in dependent_health if h == "failing")
    worse = sum(1 for h in dependent_health if h in ("failing", "degraded"))
    if failing >= DERIVED_MIN_DEPENDENTS and failing / total >= failing_ratio:
        return "failing"
    if worse >= DERIVED_MIN_DEPENDENTS and worse / total >= degraded_ratio:
        return "degraded"
    return "unknown"
