"""Whole-domain search for the live map (PRP-74 item 2, clarification 2).

An application-side scan over ``CatalogRepository.list_entities`` pages of 500, up to
``NS_MAP_SEARCH_SCAN_PAGES`` pages under an ``NS_MAP_SEARCH_TIMEOUT_MS`` deadline. When either
stops the scan the response says so (``truncated`` with ``scan_limit`` or ``timeout_ms``) and
coverage is ``partial``. Every entity is re-checked against the domain and customer.

Text matching is case-insensitive on the node's PUBLIC label and id. A person's public label and
id are the pseudonym, so a person is only ever found by pseudonym and the response never carries
a real name. Matches are ordered by node kind (the viewport's kind order), then label, then id;
counts cover every match scanned, not only the returned page.

No ``from __future__ import annotations``: FastAPI inspects the signatures that use these types.
"""

import asyncio
import time
from collections import Counter
from typing import Any, Final

from neurosphere_core.aggregates import AggregateReader
from neurosphere_core.auth.scope import PrincipalPseudonymizer
from neurosphere_core.catalog import CatalogEntity, CatalogRepository, GraphQuery
from neurosphere_core.paging import PageRequest
from neurosphere_core.scope import IdentityScope

from neurosphere_api.map.dependencies import Clock, ViewportLimits
from neurosphere_api.map.facets import facets_of
from neurosphere_api.map.models import (
    SearchCounts,
    SearchMatch,
    SearchResponse,
    TruncationReason,
)
from neurosphere_api.map.service import (
    CLUSTER_PREFIX,
    KIND_OF,
    PAGE_SIZE,
    VIEWPORT_ENTITY_TYPES,
    MapFilters,
    _Builder,  # pyright: ignore[reportPrivateUsage]
)
from neurosphere_api.map.settings import MapSettings

__all__ = ["MAX_QUERY_LENGTH", "MAX_SEARCH_LIMIT", "search_domain"]

MAX_QUERY_LENGTH: Final = 128
MAX_SEARCH_LIMIT: Final = 50
_SUBJECT_CHUNK: Final = 500
_KIND_ORDER: Final = {entity_type: i for i, entity_type in enumerate(VIEWPORT_ENTITY_TYPES)}


def _raw(value: Any) -> Any:
    return getattr(value, "root", value)


async def search_domain(
    *,
    scope: IdentityScope,
    domain_id: str,
    q: str,
    limit: int,
    filters: MapFilters,
    repository: CatalogRepository,
    graph: GraphQuery,
    reader: AggregateReader,
    pseudonymizer: PrincipalPseudonymizer,
    clock: Clock,
    limits: ViewportLimits,
    settings: MapSettings,
) -> SearchResponse:
    b = _Builder(
        scope, domain_id, repository, graph, reader, pseudonymizer, clock, limits, settings, filters
    )
    needle = q.strip().lower()
    deadline = time.monotonic() + settings.search_timeout_ms / 1000
    matched: list[tuple[CatalogEntity, str]] = []
    reason: TruncationReason | None = None
    cursor: str | None = None
    pages = 0
    while True:
        if pages >= settings.search_scan_pages:
            reason = "scan_limit"
            break
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            reason = "timeout_ms"
            break
        try:
            page = await asyncio.wait_for(
                repository.list_entities(
                    scope,
                    b._filter(list(filters.entity_types)),
                    PageRequest(page_size=PAGE_SIZE, cursor=cursor),
                ),
                remaining,
            )
        except TimeoutError:
            reason = "timeout_ms"
            break
        pages += 1
        for entity in b.static_filtered(b._in_domain(page.items)):
            label = b.label_of(entity)
            public = b.public_id(entity)
            if needle and needle not in label.lower() and needle not in public.lower():
                continue
            matched.append((entity, label))
        cursor = page.next_cursor
        if cursor is None:
            break

    # Health is measured per node: read subject points in bounded chunks for the matches.
    entities = [e for e, _ in matched]
    for start in range(0, len(entities), _SUBJECT_CHUNK):
        await b.load_subjects(entities[start : start + _SUBJECT_CHUNK])
    if filters.health:
        matched = [(e, lab) for e, lab in matched if b.measured_health(e.id) in filters.health]

    matched.sort(key=lambda m: (_KIND_ORDER[m[0].entity_type], m[1].lower(), b.public_id(m[0])))
    by_kind: Counter[str] = Counter()
    by_health: Counter[str] = Counter()
    by_env: Counter[str] = Counter()
    by_cloud: Counter[str] = Counter()
    for entity, _ in matched:
        facets = facets_of(entity, b.subjects.get(entity.id))
        by_kind[KIND_OF[entity.entity_type]] += 1
        by_health[str(_raw(facets.health) or "unknown")] += 1
        by_env[str(_raw(facets.environment) or "unknown")] += 1
        by_cloud[str(_raw(facets.cloud) or "unknown")] += 1

    page_entities = [e for e, _ in matched[:limit]]
    page_nodes = [
        SearchMatch(
            node=b.node_for(e, f"{CLUSTER_PREFIX}{e.entity_type}"),
            cluster_id=f"{CLUSTER_PREFIX}{e.entity_type}",
        )
        for e in page_entities
    ]
    coverage = await b.coverage(incomplete=reason is not None or b.subjects_failed)
    return SearchResponse(
        domain_id=domain_id,
        matches=page_nodes,
        counts=SearchCounts(
            by_kind=dict(by_kind),
            by_health=dict(by_health),
            by_environment=dict(by_env),
            by_cloud=dict(by_cloud),
        ),
        truncated=reason is not None,
        truncation_reason=reason,
        coverage=coverage,
        filters_applied=filters.echo() if filters.active else None,
    )
