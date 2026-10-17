"""In-memory catalog repository: the engine over a dict backend (unit tests, items 2-5).

The evaluator mirrors the Cosmos SQL produced by ``cosmos.build_sql`` clause for clause, and
partition-scoped uniqueness mirrors Cosmos (an ID collides only inside one partition), so the
shared conformance suite exercises the same engine rules against both.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any

from neurosphere_core.catalog.partitioning import (
    DEFAULT_SHARD_COUNT,
    PartitionKeyShape,
    partition_key_paths,
)
from neurosphere_core.catalog.repo.backend import (
    DocConflictError,
    DocPreconditionFailedError,
    Query,
)
from neurosphere_core.catalog.repo.engine import CatalogEngine, _utcnow


def _matches(doc: dict[str, Any], q: Query) -> bool:
    scope = q.scope
    if (
        doc.get("doc_type") != q.doc_type
        or doc.get("cloud") != scope.cloud
        or doc.get("customer_id") != scope.customer_id
    ):
        return False
    if scope.domains is not None and doc.get("domain_id") not in scope.domains:
        return False
    if any(doc.get(field) != value for field, value in q.eq):
        return False
    if any(doc.get(field) not in values for field, values in q.any_of):
        return False
    if q.either and not any(doc.get(field) == value for field, value in q.either):
        return False
    if q.order is not None:
        current = doc.get(q.order)
        if current is None:
            return False
        if q.after is not None and not (current < q.after if q.descending else current > q.after):
            return False
    return True


class InMemoryBackend:
    """Dict-backed ``DocBackend``. Documents are deep-copied on the way in and out."""

    def __init__(self, shape: PartitionKeyShape) -> None:
        self._partition_names = tuple(p.lstrip("/") for p in partition_key_paths(shape))
        self._docs: dict[tuple[tuple[str, ...], str], dict[str, Any]] = {}
        self._counter = 0

    def _key(self, doc: dict[str, Any]) -> tuple[tuple[str, ...], str]:
        return tuple(str(doc[name]) for name in self._partition_names), str(doc["id"])

    def _stamp(self, doc: dict[str, Any]) -> dict[str, Any]:
        self._counter += 1
        stored = copy.deepcopy(doc)
        stored["_etag"] = f"mem-{self._counter}"
        return stored

    async def query(self, query: Query) -> Sequence[dict[str, Any]]:
        rows = [d for d in self._docs.values() if _matches(d, query)]
        if query.order is not None:
            order = query.order
            rows.sort(key=lambda d: str(d[order]), reverse=query.descending)
        return [copy.deepcopy(d) for d in rows[: query.limit]]

    async def insert(self, doc: dict[str, Any]) -> dict[str, Any]:
        key = self._key(doc)
        if key in self._docs:
            raise DocConflictError
        self._docs[key] = self._stamp(doc)
        return copy.deepcopy(self._docs[key])

    async def replace(self, doc: dict[str, Any], if_match: str) -> dict[str, Any]:
        key = self._key(doc)
        current = self._docs.get(key)
        if current is None or current["_etag"] != if_match:
            raise DocPreconditionFailedError
        self._docs[key] = self._stamp(doc)
        return copy.deepcopy(self._docs[key])


class InMemoryCatalogRepository(CatalogEngine):
    """``CatalogRepository`` with the same semantics as the Cosmos implementation."""

    def __init__(
        self,
        shape: PartitionKeyShape = PartitionKeyShape.FLAT_DOMAIN,
        *,
        shard_count: int = DEFAULT_SHARD_COUNT,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        super().__init__(InMemoryBackend(shape), shape, shard_count=shard_count, clock=clock)
