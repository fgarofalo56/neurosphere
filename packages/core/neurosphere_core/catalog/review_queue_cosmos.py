"""Cosmos NoSQL catalog review queue (azure-cosmos aio).

Container ``catalog_review_queue``, hierarchical partition key ``/customer_id``,
``/domain_id`` (MultiHash; matches ``neurosphere_core.stores.containers``). Each document is
:class:`ReviewItem` plus ``sort_key`` (``<created_at>|<id>``).
``id`` is the item's deterministic id, so ``enqueue`` is a
create-only ``create_item`` and a 409 is "already queued" (``False``).

``list_open`` takes only the caller's scope, so it is a bounded query over exactly the scope's
allowed domains (``ARRAY_CONTAINS(@domains, c.domain_id)``) plus the cloud and customer. ``get``
is a single-partition point read when the scope allows exactly one domain, otherwise the same
bounded query (``TOP 1``); an item outside the scope is indistinguishable from a missing one.
``resolve`` reads the row, then replaces it ``IfNotModified`` on ``_etag`` (retried,
so two stewards cannot lose a write).
"""

from __future__ import annotations

import builtins
from collections.abc import Mapping
from typing import Any, Final, NoReturn

from azure.core import MatchConditions
from azure.cosmos import PartitionKey
from azure.cosmos.aio import ContainerProxy, CosmosClient, DatabaseProxy
from azure.cosmos.exceptions import (
    CosmosAccessConditionFailedError,
    CosmosHttpResponseError,
    CosmosResourceExistsError,
    CosmosResourceNotFoundError,
)
from pydantic import ValidationError

from neurosphere_core.catalog.review_queue import ReviewItem, ReviewResolution
from neurosphere_core.errors import (
    DependencyTransientError,
    ForbiddenError,
    NeuroSphereError,
    RateLimitedError,
    StaleVersionError,
)
from neurosphere_core.scope import IdentityScope

__all__ = [
    "DEFAULT_REVIEW_QUEUE_CONTAINER",
    "REVIEW_QUEUE_PARTITION_KEY_PATHS",
    "CosmosReviewQueue",
    "create_review_queue_container",
]

DEFAULT_REVIEW_QUEUE_CONTAINER: Final = "catalog_review_queue"
REVIEW_QUEUE_PARTITION_KEY_PATHS: Final = ("/customer_id", "/domain_id")
_QUERY_FIELDS: Final = frozenset({"sort_key"})
_RESOLVE_ATTEMPTS: Final = 3
_SCOPE_CLAUSES: Final = (
    "c.cloud = @cloud AND c.customer_id = @customer AND ARRAY_CONTAINS(@domains, c.domain_id)"
)


async def create_review_queue_container(
    database: DatabaseProxy, container_id: str = DEFAULT_REVIEW_QUEUE_CONTAINER
) -> ContainerProxy:
    """Create (or open) the review-queue container (MultiHash on customer, domain)."""
    return await database.create_container_if_not_exists(
        id=container_id,
        partition_key=PartitionKey(path=list(REVIEW_QUEUE_PARTITION_KEY_PATHS), kind="MultiHash"),
    )


def _visible(scope: IdentityScope, item: ReviewItem) -> bool:
    return (
        item.cloud == scope.cloud
        and item.customer_id == scope.customer_id
        and item.domain_id in scope.allowed_domains
    )


def _raise_mapped(exc: Exception) -> NoReturn:
    if isinstance(exc, NeuroSphereError):
        raise exc
    if isinstance(exc, CosmosHttpResponseError) and exc.status_code == 429:
        raise RateLimitedError(1, "review queue throttled the request") from exc
    raise DependencyTransientError(
        "review queue unavailable", reason="review_queue_unavailable"
    ) from exc


def _body(item: ReviewItem) -> dict[str, Any]:
    body = item.model_dump(mode="json")
    body["sort_key"] = f"{item.created_at}|{item.id}"
    return body


def _from_row(row: Mapping[str, Any]) -> ReviewItem:
    document = {k: v for k, v in row.items() if not k.startswith("_") and k not in _QUERY_FIELDS}
    try:
        return ReviewItem.model_validate(document)
    except ValidationError as exc:
        raise DependencyTransientError(
            "stored review item failed validation",
            reason="review_queue_record_invalid",
            upstream_invalid=True,
        ) from exc


class CosmosReviewQueue:
    """:class:`neurosphere_core.catalog.review_queue.ReviewQueue` on one Cosmos container."""

    def __init__(self, container: ContainerProxy) -> None:
        self._container = container

    @classmethod
    def from_client(
        cls,
        client: CosmosClient,
        *,
        database: str,
        container: str = DEFAULT_REVIEW_QUEUE_CONTAINER,
    ) -> CosmosReviewQueue:
        return cls(client.get_database_client(database).get_container_client(container))

    async def enqueue(self, scope: IdentityScope, item: ReviewItem) -> bool:
        if not _visible(scope, item):
            raise ForbiddenError("review item is outside the caller's scope")
        try:
            await self._container.create_item(body=_body(item))
        except CosmosResourceExistsError:
            return False
        except Exception as exc:
            _raise_mapped(exc)
        return True

    async def get(self, scope: IdentityScope, item_id: str) -> ReviewItem | None:
        found = await self._get_row(scope, item_id)
        return None if found is None else _from_row(found)

    async def list_open(self, scope: IdentityScope, limit: int = 100) -> tuple[ReviewItem, ...]:
        bounded = max(1, min(limit, 500))
        if not scope.allowed_domains:
            return ()
        sql = (
            "SELECT TOP @limit * FROM c WHERE c.status = @status AND "  # noqa: S608
            + _SCOPE_CLAUSES
            + " ORDER BY c.sort_key ASC"
        )
        rows = await self._query(
            sql, [{"name": "@limit", "value": bounded}, {"name": "@status", "value": "open"}], scope
        )
        return tuple(_from_row(row) for row in rows)

    async def resolve(
        self,
        scope: IdentityScope,
        item_id: str,
        *,
        resolved_by: str,
        resolution: ReviewResolution,
        resolved_at: str,
    ) -> ReviewItem:
        for _ in range(_RESOLVE_ATTEMPTS):
            row = await self._get_row(scope, item_id)
            if row is None:
                raise ForbiddenError("review item not found in the caller's scope")
            updated = _from_row(row).model_copy(
                update={
                    "status": "resolved",
                    "resolved_by": resolved_by,
                    "resolution": resolution,
                    "resolved_at": resolved_at,
                }
            )
            try:
                stored = await self._container.replace_item(
                    item=item_id,
                    body=_body(updated),
                    etag=str(row.get("_etag", "")),
                    match_condition=MatchConditions.IfNotModified,
                )
            except (CosmosAccessConditionFailedError, CosmosResourceNotFoundError):
                continue  # lost a race; re-read and retry
            except Exception as exc:
                _raise_mapped(exc)
            return _from_row(stored)
        raise StaleVersionError("review item changed while resolving", reason="etag_mismatch")

    async def _get_row(self, scope: IdentityScope, item_id: str) -> Mapping[str, Any] | None:
        if not scope.allowed_domains:
            return None
        if len(scope.allowed_domains) == 1:
            return await self._point_read(scope, item_id)
        sql = "SELECT TOP 1 * FROM c WHERE c.id = @id AND " + _SCOPE_CLAUSES  # noqa: S608
        rows = await self._query(sql, [{"name": "@id", "value": item_id}], scope)
        return rows[0] if rows else None

    async def _point_read(self, scope: IdentityScope, item_id: str) -> Mapping[str, Any] | None:
        try:
            row = await self._container.read_item(
                item=item_id, partition_key=[scope.customer_id, scope.allowed_domains[0]]
            )
        except CosmosResourceNotFoundError:
            return None
        except Exception as exc:
            _raise_mapped(exc)
        return row if row.get("cloud") == scope.cloud else None

    async def _query(
        self, sql: str, parameters: builtins.list[dict[str, Any]], scope: IdentityScope
    ) -> builtins.list[Mapping[str, Any]]:
        params = [
            *parameters,
            {"name": "@cloud", "value": scope.cloud},
            {"name": "@customer", "value": scope.customer_id},
            {"name": "@domains", "value": builtins.list(scope.allowed_domains)},
        ]
        try:
            return [row async for row in self._container.query_items(sql, parameters=params)]
        except Exception as exc:
            _raise_mapped(exc)
