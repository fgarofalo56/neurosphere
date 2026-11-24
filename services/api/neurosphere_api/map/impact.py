"""Impact of a failing node on the live map (PRP-74 item 3): "what is affected if this fails".

One adapter turns the PRP-73 ``AccessEngine.dependents`` answer (``impact_paths`` with
``direction="upstream"``: the entities that RELY ON the node) into :class:`ImpactResponse` levels:

* rows are grouped by depth; a node reachable at several depths is listed once, at its shallowest;
* every dependent is re-read through ``repository.get_entity(scope, id)`` and kept only when it
  is in scope, in the path domain and of a map entity type, so a misbehaving store cannot leak
  another domain or customer into the response;
* health is the measured subject point (the viewport's path); a service, tool or MCP server with
  no point gets the viewport's dependents fallback from its direct dependents in this result,
  marked ``health_inferred`` and never ``ok``;
* a person appears only as the pseudonym (id and label); ``accessor_name`` is never used;
* the budget can only lower the engine ceilings; the truncation reason is mapped from the
  engine's (a ``max_depth`` cut is the requested depth, not a truncation).

The engine returns an empty, untruncated result for a node the scope cannot read, which is
indistinguishable from a node nobody depends on, so :func:`build_impact` reads the node itself
FIRST and returns ``None`` (the route's one 404) when it is missing, unreadable, in another domain
or not a map entity.

No ``from __future__ import annotations``: this package's models are inspected by FastAPI.
"""

import asyncio
from typing import Final

from neurosphere_core.aggregates import AggregateReader
from neurosphere_core.auth.scope import PrincipalPseudonymizer
from neurosphere_core.catalog import CatalogEntity, CatalogRepository, GraphQuery
from neurosphere_core.catalog.graph.access import (
    MAX_ACCESSORS,
    MAX_TIMEOUT_MS,
    AccessBudget,
    AccessEngine,
    AccessResult,
    AccessRow,
)
from neurosphere_core.scope import IdentityScope

from neurosphere_api.map.dependencies import Clock, ViewportLimits
from neurosphere_api.map.facets import DERIVED_RELATIONS, DERIVED_SUBJECT_TYPES, derive_health
from neurosphere_api.map.models import (
    Health,
    ImpactBudget,
    ImpactLevel,
    ImpactNode,
    ImpactResponse,
    TruncationReason,
)
from neurosphere_api.map.service import (
    KIND_OF,
    VIEWPORT_ENTITY_TYPES,
    _Builder,  # pyright: ignore[reportPrivateUsage]
)
from neurosphere_api.map.settings import MapSettings

__all__ = ["build_impact", "to_access_budget", "truncation_of"]

_FETCH_CHUNK: Final = 50
_REASON: Final[dict[str, TruncationReason]] = {
    "max_accessors": "node_budget",
    "max_assets": "scan_limit",
    "timeout_ms": "timeout_ms",
}


def to_access_budget(budget: ImpactBudget | None) -> AccessBudget | None:
    """Clamp a request budget to the server ceilings (never raises them)."""
    if budget is None:
        return None
    return AccessBudget(
        max_accessors=None
        if budget.max_accessors is None
        else min(budget.max_accessors, MAX_ACCESSORS),
        timeout_ms=None if budget.timeout_ms is None else min(budget.timeout_ms, MAX_TIMEOUT_MS),
    )


def truncation_of(result: AccessResult) -> TruncationReason | None:
    """The map reason for an engine truncation; a ``max_depth`` cut is not a truncation here."""
    if not result.truncated or result.truncated_reason in (None, "max_depth"):
        return None
    return _REASON.get(result.truncated_reason or "", "traversal_incomplete")


async def _entities(
    repository: CatalogRepository, scope: IdentityScope, ids: list[str]
) -> dict[str, CatalogEntity]:
    found: dict[str, CatalogEntity] = {}
    for start in range(0, len(ids), _FETCH_CHUNK):
        chunk = ids[start : start + _FETCH_CHUNK]
        got = await asyncio.gather(*(repository.get_entity(scope, i) for i in chunk))
        for entity_id, entity in zip(chunk, got, strict=True):
            if entity is not None:
                found[entity_id] = entity
    return found


async def build_impact(
    *,
    scope: IdentityScope,
    domain_id: str,
    node_id: str,
    max_depth: int,
    budget: ImpactBudget | None,
    engine: AccessEngine,
    repository: CatalogRepository,
    graph: GraphQuery,
    reader: AggregateReader,
    pseudonymizer: PrincipalPseudonymizer,
    clock: Clock,
    limits: ViewportLimits,
    settings: MapSettings | None = None,
) -> ImpactResponse | None:
    """Dependents of ``node_id`` by depth; ``None`` when the node is missing or not readable."""
    b = _Builder(
        scope, domain_id, repository, graph, reader, pseudonymizer, clock, limits, settings
    )
    center = await repository.get_entity(scope, node_id)
    if center is None or center.entity_type not in VIEWPORT_ENTITY_TYPES or not b.in_domain(center):
        return None
    result = await engine.dependents(scope, node_id, max_depth, to_access_budget(budget))

    rows = sorted(result.rows, key=lambda r: (r.depth, r.accessor_id, r.edge_id))
    fetched = await _entities(repository, scope, sorted({r.accessor_id for r in rows}))
    allowed = {
        entity_id: e
        for entity_id, e in fetched.items()
        if e.entity_type in VIEWPORT_ENTITY_TYPES and b.in_domain(e) and entity_id != center.id
    }
    kept = [r for r in rows if r.accessor_id in allowed]
    await b.load_subjects(list(allowed.values()))
    derived = _derived(b, kept, allowed)

    placed: dict[str, int] = {}
    nodes_at: dict[int, list[ImpactNode]] = {}
    edges_at: dict[int, set[str]] = {}
    for row in kept:
        if placed.setdefault(row.accessor_id, row.depth) != row.depth:
            continue  # already listed at a shallower depth
        edges_at.setdefault(row.depth, set()).add(row.edge_id)
        level = nodes_at.setdefault(row.depth, [])
        entity = allowed[row.accessor_id]
        if all(n.id != b.public_id(entity) for n in level):
            level.append(_node(b, entity, derived.get(entity.id)))
    levels = [
        ImpactLevel(
            depth=depth,
            nodes=sorted(nodes_at[depth], key=lambda n: (n.label.lower(), n.id)),
            edge_ids=sorted(edges_at[depth]),
        )
        for depth in sorted(nodes_at)
    ]
    reason = truncation_of(result)
    coverage = await b.coverage(incomplete=reason is not None or b.subjects_failed)
    return ImpactResponse(
        domain_id=domain_id,
        node_id=b.public_id(center),
        levels=levels,
        truncated=reason is not None,
        truncation_reason=reason,
        coverage=coverage,
    )


def _derived(
    b: _Builder,  # pyright: ignore[reportPrivateUsage]
    rows: list[AccessRow],
    entities: dict[str, CatalogEntity],
) -> dict[str, Health]:
    """Fallback health of service, tool and MCP-server dependents with no subject point, from the
    measured health of their direct dependents that are in this result."""
    dependents: dict[str, set[str]] = {}
    for row in rows:
        path = row.path_node_ids
        if len(path) >= 2 and row.relation_path and row.relation_path[0] in DERIVED_RELATIONS:
            dependents.setdefault(path[1], set()).add(row.accessor_id)
    out: dict[str, Health] = {}
    for entity_id, entity in entities.items():
        if entity.entity_type not in DERIVED_SUBJECT_TYPES or entity_id in b.subjects:
            continue
        health = derive_health(
            [b.measured_health(s) for s in sorted(dependents.get(entity_id, set()))],
            failing_ratio=b.settings.derived_failing_ratio,
            degraded_ratio=b.settings.derived_degraded_ratio,
        )
        if health != "unknown":
            out[entity_id] = health
    return out


def _node(
    b: _Builder,  # pyright: ignore[reportPrivateUsage]
    entity: CatalogEntity,
    derived: Health | None,
) -> ImpactNode:
    point_known = entity.id in b.subjects
    health: Health = b.measured_health(entity.id)
    inferred = False
    if not point_known and derived is not None:
        health, inferred = derived, True
    return ImpactNode(
        id=b.public_id(entity),
        kind=KIND_OF[entity.entity_type],
        label=b.label_of(entity),
        domain_id=b.domain_id,
        health=health,
        health_inferred=inferred,
    )
