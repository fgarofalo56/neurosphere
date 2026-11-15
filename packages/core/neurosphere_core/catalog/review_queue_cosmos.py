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
import hashlib
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
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
from neurosphere_core.catalog.rules import format_timestamp, parse_timestamp
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
MARKER_KIND: Final = "open_marker"
_MARKER_STALE: Final = timedelta(seconds=60)
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


def _marker_id(item: ReviewItem) -> str:
    key = "|".join((item.edge_id, item.reason, item.governing_override_id or ""))
    return "open-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:48]


def _marker_body(item: ReviewItem, now: datetime) -> dict[str, Any]:
    """Deterministic open-conflict marker: same partition as the item, never listed."""
    return {
        "id": _marker_id(item),
        "kind": MARKER_KIND,
        "status": "marker",  # never matches the open-item queries
        "item_id": item.id,
        "edge_id": item.edge_id,
        "cloud": item.cloud,
        "customer_id": item.customer_id,
        "domain_id": item.domain_id,
        "created_at": format_timestamp(now),
    }


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

    def __init__(
        self,
        container: ContainerProxy,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._container = container
        self._now = now

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
        if await self._open_duplicate(scope, item):
            return False  # also covers items stored before open markers existed
        if not await self._claim_marker(item):
            return False
        try:
            await self._container.create_item(body=_body(item))
        except CosmosResourceExistsError:
            return False
        except Exception as exc:
            _raise_mapped(exc)
        return True

    async def _claim_marker(self, item: ReviewItem) -> bool:
        """Create the deterministic open marker; False when the conflict is already open.

        Two concurrent enqueues of the same conflict race on this create (a unique id inside one
        partition), so exactly one proceeds. A marker whose item never landed (a crash between
        the two writes) is taken over once it is older than ``_MARKER_STALE``.
        """
        marker = _marker_body(item, self._now())
        try:
            await self._container.create_item(body=marker)
        except CosmosResourceExistsError:
            return await self._take_over(item, marker)
        except Exception as exc:
            _raise_mapped(exc)
        return True

    async def _take_over(self, item: ReviewItem, marker: dict[str, Any]) -> bool:
        try:
            held = await self._container.read_item(
                item=marker["id"], partition_key=[item.customer_id, item.domain_id]
            )
        except CosmosResourceNotFoundError:
            return await self._claim_marker(item)  # removed meanwhile: claim again
        except Exception as exc:
            _raise_mapped(exc)
        placed = await self._item_exists(held)
        age = self._now() - parse_timestamp(str(held.get("created_at", marker["created_at"])))
        if placed or age < _MARKER_STALE:
            return False
        try:
            await self._container.replace_item(
                item=marker["id"],
                body=marker,
                etag=str(held.get("_etag", "")),
                match_condition=MatchConditions.IfNotModified,
            )
        except (CosmosAccessConditionFailedError, CosmosResourceNotFoundError):
            return False
        except Exception as exc:
            _raise_mapped(exc)
        return True

    async def _item_exists(self, marker: Mapping[str, Any]) -> bool:
        try:
            await self._container.read_item(
                item=str(marker.get("item_id", "")),
                partition_key=[marker["customer_id"], marker["domain_id"]],
            )
        except CosmosResourceNotFoundError:
            return False
        except Exception as exc:
            _raise_mapped(exc)
        return True

    async def _drop_marker(self, item: ReviewItem) -> None:
        try:
            await self._container.delete_item(
                item=_marker_id(item), partition_key=[item.customer_id, item.domain_id]
            )
        except CosmosResourceNotFoundError:
            return
        except Exception as exc:
            _raise_mapped(exc)

    async def _open_duplicate(self, scope: IdentityScope, item: ReviewItem) -> bool:
        """A still-open item for the same edge, reason and governing decision exists."""
        sql = (
            "SELECT TOP 1 c.id FROM c WHERE c.status = @status AND c.edge_id = @edge AND "  # noqa: S608
            "c.reason = @reason AND c.domain_id = @domain AND "
            "c.governing_override_id = @governing AND " + _SCOPE_CLAUSES
        )
        rows = await self._query(
            sql,
            [
                {"name": "@status", "value": "open"},
                {"name": "@edge", "value": item.edge_id},
                {"name": "@reason", "value": item.reason},
                {"name": "@domain", "value": item.domain_id},
                {"name": "@governing", "value": item.governing_override_id},
            ],
            scope,
        )
        return bool(rows)

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
            result = _from_row(stored)
            await self._drop_marker(result)
            return result
        raise StaleVersionError("review item changed while resolving", reason="etag_mismatch")

    async def _get_row(self, scope: IdentityScope, item_id: str) -> Mapping[str, Any] | None:
        row = await self._find_row(scope, item_id)
        return None if row is None or row.get("kind") == MARKER_KIND else row

    async def _find_row(self, scope: IdentityScope, item_id: str) -> Mapping[str, Any] | None:
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
