"""Catalog search indexer (PRP-35 item 3): keeps a search index in step with the catalog.

Three parts, none of which widens authorization:

* :class:`FixtureSearchStore` is an in-process ``AuthorizedSearch`` that is also an
  :class:`IndexSink`; ``upsert`` replaces documents by canonical id and rebuilds the BM25 fixture
  index only when something changed. Its scope filter is the ordinary ``FixtureSearchIndex`` one.
* :class:`AzureIndexSink` upserts the same documents into an Azure AI Search index with
  ``merge_or_upload_documents`` (the client is Entra / managed-identity only; no key path).
* :class:`CatalogIndexer` reads entities through ``CatalogRepository.list_entities`` **with the
  caller's own scope** (there is no unscoped enumeration, so an indexer can never index more than
  the principal it is acting for may read) and upserts only documents that changed since the last
  upsert, so repeated runs are idempotent.

Logging: counts only. Document bodies, ids and entity text are never logged.
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any, Final, Protocol

from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope
from pydantic import BaseModel

from neurosphere_core.catalog.protocol import CatalogRepository, EntityFilter
from neurosphere_core.errors import DependencyTransientError
from neurosphere_core.paging import PageRequest
from neurosphere_core.scope import IdentityScope
from neurosphere_core.search.fixture.index import (
    FixtureSearchIndex,
    SearchDocument,
    documents_from_catalog,
)
from neurosphere_core.search.protocol import SearchRequest, SearchResult

__all__ = [
    "AzureIndexSink",
    "CatalogIndexer",
    "CompositeIndexSink",
    "FixtureSearchStore",
    "IndexSink",
    "UploadBackend",
]

_log = logging.getLogger("neurosphere_core.search.indexer")

#: Azure accepts up to 1000 documents per indexing request.
UPLOAD_BATCH: Final = 500
DEFAULT_PAGE_SIZE: Final = 200
#: Hard ceiling on pages walked per refresh (bounded work per request).
DEFAULT_MAX_PAGES: Final = 200


class IndexSink(Protocol):
    async def upsert(self, documents: Sequence[SearchDocument]) -> None:
        """Insert or replace documents by id. Must be idempotent."""
        ...


class UploadBackend(Protocol):
    """The slice of ``azure.search.documents.aio.SearchClient`` used for indexing."""

    async def merge_or_upload_documents(
        self, documents: list[dict[str, Any]], **kwargs: Any
    ) -> Any:
        """Return a list of indexing results with ``succeeded`` flags."""
        ...


class FixtureSearchStore:
    """Mutable in-process index: an ``AuthorizedSearch`` that is also an ``IndexSink``."""

    def __init__(
        self,
        documents: Iterable[SearchDocument] = (),
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._clock = clock
        self._docs: dict[str, SearchDocument] = {d.id: d for d in documents}
        self._index = FixtureSearchIndex(self._docs.values(), clock=clock)

    def __len__(self) -> int:
        return len(self._docs)

    async def upsert(self, documents: Sequence[SearchDocument]) -> None:
        changed = False
        for doc in documents:
            if self._docs.get(doc.id) != doc:
                self._docs[doc.id] = doc
                changed = True
        if changed:  # synchronous swap: a concurrent search sees the old or the new index
            self._index = FixtureSearchIndex(self._docs.values(), clock=self._clock)

    async def search(self, scope: ContractScope, request: SearchRequest) -> SearchResult:
        return await self._index.search(scope, request)


class AzureIndexSink:
    """Upserts documents into an Azure AI Search index (RBAC / managed identity only)."""

    def __init__(self, backend: UploadBackend) -> None:
        self._backend = backend

    async def upsert(self, documents: Sequence[SearchDocument]) -> None:
        for start in range(0, len(documents), UPLOAD_BATCH):
            batch = [d.model_dump() for d in documents[start : start + UPLOAD_BATCH]]
            results = await self._backend.merge_or_upload_documents(documents=batch)
            failed = sum(1 for r in results or () if not getattr(r, "succeeded", True))
            if failed:
                _log.warning("search index upload: %d of %d documents failed", failed, len(batch))
                raise DependencyTransientError(
                    "search index upload failed", reason="search_index_upload_failed"
                )


class CompositeIndexSink:
    """Fans one upsert out to several sinks, in order."""

    def __init__(self, *sinks: IndexSink) -> None:
        self._sinks = sinks

    async def upsert(self, documents: Sequence[SearchDocument]) -> None:
        for sink in self._sinks:
            await sink.upsert(documents)


def _digest(doc: SearchDocument) -> str:
    return hashlib.sha256(doc.model_dump_json().encode("utf-8")).hexdigest()


def _as_mapping(entity: Mapping[str, Any] | BaseModel) -> Mapping[str, Any]:
    if isinstance(entity, BaseModel):
        return entity.model_dump(mode="json")
    return entity


class CatalogIndexer:
    """Turns catalog entities into search documents and upserts the ones that changed."""

    def __init__(
        self,
        repository: CatalogRepository,
        sink: IndexSink,
        *,
        page_size: int = DEFAULT_PAGE_SIZE,
        max_pages: int = DEFAULT_MAX_PAGES,
    ) -> None:
        self._repo = repository
        self._sink = sink
        self._page_size = page_size
        self._max_pages = max_pages
        self._seen: dict[str, str] = {}

    async def index_entities(self, entities: Iterable[Mapping[str, Any] | BaseModel]) -> int:
        """Upsert the entities that are new or changed; return how many were sent."""
        docs = documents_from_catalog([_as_mapping(e) for e in entities])
        pending = [(d, _digest(d)) for d in docs]
        pending = [(d, h) for d, h in pending if self._seen.get(d.id) != h]
        if not pending:
            return 0
        await self._sink.upsert([d for d, _ in pending])
        for doc, digest in pending:  # remembered only after the sink accepted the batch
            self._seen[doc.id] = digest
        return len(pending)

    async def refresh(self, scope: IdentityScope) -> int:
        """Index every entity ``scope`` may read (bounded pages); return how many were sent."""
        sent = 0
        cursor = None
        for _ in range(self._max_pages):
            page = await self._repo.list_entities(
                scope,
                EntityFilter(),
                PageRequest(page_size=self._page_size, cursor=cursor),
            )
            sent += await self.index_entities(page.items)
            cursor = page.next_cursor
            if cursor is None:
                break
        _log.info("catalog indexer refresh: %d documents upserted", sent)
        return sent
