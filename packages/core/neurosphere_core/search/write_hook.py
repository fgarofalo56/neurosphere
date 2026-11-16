"""Write-through catalog repository (PRP-60 item 4): keeps the search index in step with writes.

``IndexingCatalogRepository`` decorates a ``CatalogRepository``. After a successful
``create_entity``, ``update_entity`` or ``deprecate_entity`` it upserts just that entity into the
index through the :class:`CatalogIndexer` (no full re-enumeration). Every other repository method
is forwarded untouched, so authorization, versioning and ETag behaviour are exactly the inner
repository's.

A search outage must never fail a catalog write: sink errors are swallowed after logging the
exception type only (never ids, text or bodies). The lazy per-scope refresh remains the safety net.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence

from neurosphere_contracts.catalog.v1.alias import Alias
from neurosphere_contracts.catalog.v1.edge_override import EdgeOverride

from neurosphere_core.catalog.protocol import (
    AliasKey,
    CatalogEdge,
    CatalogEntity,
    CatalogRepository,
    Direction,
    EdgeFilter,
    EdgeObservation,
    EntityFilter,
)
from neurosphere_core.paging import Page, PageRequest
from neurosphere_core.scope import IdentityScope
from neurosphere_core.search.indexer import CatalogIndexer

__all__ = ["IndexingCatalogRepository"]

_log = logging.getLogger("neurosphere_core.search.write_hook")


class IndexingCatalogRepository:
    """A ``CatalogRepository`` that writes changed entities through to the search index."""

    def __init__(
        self,
        inner: CatalogRepository,
        indexer: CatalogIndexer,
        *,
        on_write: Callable[[], None] | None = None,
    ) -> None:
        self._inner = inner
        self._indexer = indexer
        self._on_write = on_write

    @property
    def inner(self) -> CatalogRepository:
        return self._inner

    async def _after_write(self, entity: CatalogEntity) -> None:
        try:
            await self._indexer.index_entities([entity])
        except Exception as exc:  # never fail the catalog write; log the type only
            _log.warning("search write-through failed: %s", type(exc).__name__)
        if self._on_write is not None:
            try:
                self._on_write()
            except Exception as exc:
                _log.warning("search write hook failed: %s", type(exc).__name__)

    async def create_entity(self, scope: IdentityScope, entity: CatalogEntity) -> CatalogEntity:
        created = await self._inner.create_entity(scope, entity)
        await self._after_write(created)
        return created

    async def update_entity(
        self, scope: IdentityScope, entity: CatalogEntity, expected_etag: str
    ) -> CatalogEntity:
        updated = await self._inner.update_entity(scope, entity, expected_etag)
        await self._after_write(updated)
        return updated

    async def deprecate_entity(
        self, scope: IdentityScope, entity_id: str, expected_etag: str
    ) -> CatalogEntity:
        deprecated = await self._inner.deprecate_entity(scope, entity_id, expected_etag)
        await self._after_write(deprecated)
        return deprecated

    # Everything below is forwarded unchanged to the wrapped repository.

    async def get_entity(self, scope: IdentityScope, entity_id: str) -> CatalogEntity | None:
        return await self._inner.get_entity(scope, entity_id)

    async def list_entities(
        self, scope: IdentityScope, flt: EntityFilter, page: PageRequest
    ) -> Page[CatalogEntity]:
        return await self._inner.list_entities(scope, flt, page)

    async def put_alias(self, scope: IdentityScope, alias: Alias) -> Alias:
        return await self._inner.put_alias(scope, alias)

    async def resolve_alias(self, scope: IdentityScope, key: AliasKey) -> str | None:
        return await self._inner.resolve_alias(scope, key)

    async def get_edge(self, scope: IdentityScope, edge_id: str) -> CatalogEdge | None:
        return await self._inner.get_edge(scope, edge_id)

    async def put_edge(
        self, scope: IdentityScope, edge: CatalogEdge, expected_etag: str | None
    ) -> CatalogEdge:
        return await self._inner.put_edge(scope, edge, expected_etag)

    async def list_edges_by_node(
        self,
        scope: IdentityScope,
        node_id: str,
        direction: Direction,
        flt: EdgeFilter,
        page: PageRequest,
    ) -> Page[CatalogEdge]:
        return await self._inner.list_edges_by_node(scope, node_id, direction, flt, page)

    async def list_edges_by_domain(
        self, scope: IdentityScope, domain_id: str, flt: EdgeFilter, page: PageRequest
    ) -> Page[CatalogEdge]:
        return await self._inner.list_edges_by_domain(scope, domain_id, flt, page)

    async def record_observation(self, scope: IdentityScope, observation: EdgeObservation) -> bool:
        return await self._inner.record_observation(scope, observation)

    async def list_observations(
        self, scope: IdentityScope, edge_id: str, page: PageRequest
    ) -> Page[EdgeObservation]:
        return await self._inner.list_observations(scope, edge_id, page)

    async def put_override(self, scope: IdentityScope, override: EdgeOverride) -> EdgeOverride:
        return await self._inner.put_override(scope, override)

    async def list_overrides(self, scope: IdentityScope, edge_id: str) -> tuple[EdgeOverride, ...]:
        return await self._inner.list_overrides(scope, edge_id)

    async def list_overrides_for_edges(
        self, scope: IdentityScope, edge_ids: Sequence[str]
    ) -> dict[str, tuple[EdgeOverride, ...]]:
        return await self._inner.list_overrides_for_edges(scope, edge_ids)
