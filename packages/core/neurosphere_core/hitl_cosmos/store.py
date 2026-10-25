"""Cosmos NoSQL HITL review-item store and append-only decision store (azure-cosmos aio).

``hitl_items`` uses the hierarchical partition key ``/customer_id``, ``/domain_id``
(``MultiHash``, delta D7); ``hitl_decisions`` uses ``/review_item_id`` (Hash), because an
``ApprovalDecision`` carries no customer or domain. Both match
``neurosphere_core.stores.containers``.

``hitl_items`` (``id = <item_id>``): :meth:`ReviewItem.model_dump` plus query fields
``state_name``, ``sort_key`` (``<created_at>|<item_id>``, fixed width) and, while the item still
has an active deadline, ``due_ts`` (the earliest deadline) and ``due_key`` (``<due_ts>|<item_id>``).
Final items carry neither due field, so the expiry scan never reads them. The Cosmos ``_etag`` is
the store ETag; ``replace`` is ``IfNotModified`` and a 404/412 is ``stale_version``.

Query shapes (all parameterized, field names fixed):

* ``list`` is a single-partition query (``[customer_id, domain_id]``) ordered by ``sort_key``,
  ``TOP limit + 1``, continued by a ``sort_key > @after`` cursor.
* ``due`` is the expiry scan. The protocol carries no customer, so it is the one cross-partition
  query; it is bounded (``TOP @limit``, ``limit <= 500``) and touches only items with an active
  deadline (``IS_DEFINED(c.due_key)``), ordered by ``due_key``.
* ``get`` is unscoped by protocol (the caller authorizes the item's domain), so it is a
  cross-partition ``id`` lookup bounded to one row.

``hitl_decisions`` (``id = <decision_id>``): the decision document plus ``recorded_ns``
(insertion order); the partition value is the document's own ``review_item_id``.
The decision store is append-only: it only ever calls
``create_item``, ``read_item`` and ``query_items``; there is no update path.

Every backing-store failure is ``dependency_transient`` (``hitl_store_unavailable``) except 429,
which is ``rate_limited``; messages never echo SDK text or documents.
"""

from __future__ import annotations

import builtins
import time
from collections.abc import Callable, Mapping
from datetime import datetime
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

from neurosphere_core.errors import (
    DependencyTransientError,
    InvalidSchemaError,
    NeuroSphereError,
    RateLimitedError,
    StaleVersionError,
)
from neurosphere_core.hitl.models import ReviewItem, format_timestamp
from neurosphere_core.hitl.store import decode_cursor, encode_cursor
from neurosphere_core.paging import Page
from neurosphere_core.paging.models import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from neurosphere_core.scope import IdentityScope

__all__ = [
    "DECISION_PARTITION_KEY_PATHS",
    "DEFAULT_DECISION_CONTAINER",
    "DEFAULT_ITEM_CONTAINER",
    "ITEM_PARTITION_KEY_PATHS",
    "CosmosDecisionStore",
    "CosmosHitlStore",
    "create_decision_container",
    "create_item_container",
]

DEFAULT_ITEM_CONTAINER: Final = "hitl_items"
DEFAULT_DECISION_CONTAINER: Final = "hitl_decisions"
ITEM_PARTITION_KEY_PATHS: Final = ("/customer_id", "/domain_id")
DECISION_PARTITION_KEY_PATHS: Final = ("/review_item_id",)
_ITEM_QUERY_FIELDS: Final = frozenset({"id", "state_name", "sort_key", "due_ts", "due_key"})
_DECISION_FIELDS: Final = frozenset({"id", "recorded_ns"})
_MAX_DECISIONS_PER_ITEM: Final = 500


async def create_item_container(
    database: DatabaseProxy, container_id: str = DEFAULT_ITEM_CONTAINER
) -> ContainerProxy:
    """Create (or open) the review-item container with the hierarchical key."""
    return await database.create_container_if_not_exists(
        id=container_id,
        partition_key=PartitionKey(path=list(ITEM_PARTITION_KEY_PATHS), kind="MultiHash"),
    )


async def create_decision_container(
    database: DatabaseProxy, container_id: str = DEFAULT_DECISION_CONTAINER
) -> ContainerProxy:
    """Create (or open) the decision container with the hierarchical key."""
    return await database.create_container_if_not_exists(
        id=container_id,
        partition_key=PartitionKey(path=DECISION_PARTITION_KEY_PATHS[0]),
    )


def _raise_mapped(exc: Exception) -> NoReturn:
    if isinstance(exc, NeuroSphereError):
        raise exc
    if isinstance(exc, CosmosHttpResponseError) and exc.status_code == 429:
        raise RateLimitedError(1, "review store throttled the request") from exc
    raise DependencyTransientError(
        "review store unavailable", reason="hitl_store_unavailable"
    ) from exc


def _invalid() -> DependencyTransientError:
    return DependencyTransientError(
        "stored review document failed validation",
        reason="hitl_record_invalid",
        upstream_invalid=True,
    )


def _check_limit(limit: int) -> None:
    if not 1 <= limit <= MAX_PAGE_SIZE:
        raise InvalidSchemaError(f"limit must be 1..{MAX_PAGE_SIZE}", reason="invalid_limit")


def _sort_key(item: ReviewItem) -> str:
    return f"{format_timestamp(item.created_at)}|{item.item_id}"


def _item_body(item: ReviewItem) -> dict[str, Any]:
    body = item.model_dump(mode="json", exclude={"etag"})
    body["id"] = item.item_id
    body["state_name"] = item.state_name
    body["sort_key"] = _sort_key(item)
    deadline = item.next_deadline()
    if deadline is not None:
        body["due_ts"] = format_timestamp(deadline)
        body["due_key"] = f"{format_timestamp(deadline)}|{item.item_id}"
    return body


def _item_from_row(row: Mapping[str, Any]) -> ReviewItem:
    document = {
        k: v for k, v in row.items() if not k.startswith("_") and k not in _ITEM_QUERY_FIELDS
    }
    document["etag"] = str(row.get("_etag", "")) or None
    try:
        return ReviewItem.model_validate(document)
    except ValidationError as exc:
        raise _invalid() from exc


class CosmosHitlStore:
    """:class:`neurosphere_core.hitl.store.HitlStore` on one Cosmos container."""

    def __init__(self, container: ContainerProxy) -> None:
        self._container = container

    @classmethod
    def from_client(
        cls,
        client: CosmosClient,
        *,
        database: str,
        container: str = DEFAULT_ITEM_CONTAINER,
    ) -> CosmosHitlStore:
        return cls(client.get_database_client(database).get_container_client(container))

    async def create(self, item: ReviewItem) -> ReviewItem:
        try:
            row = await self._container.create_item(body=_item_body(item))
        except CosmosResourceExistsError as exc:
            raise StaleVersionError(
                "review item already exists", reason="review_item_exists"
            ) from exc
        except Exception as exc:
            _raise_mapped(exc)
        return _item_from_row(row)

    async def get(self, item_id: str) -> ReviewItem | None:
        rows = await self._query(
            "SELECT TOP 1 * FROM c WHERE c.id = @id",
            [{"name": "@id", "value": item_id}],
            partition_key=None,
        )
        return _item_from_row(rows[0]) if rows else None

    async def replace(self, item: ReviewItem, *, if_match: str) -> ReviewItem:
        body = _item_body(item)
        try:
            row = await self._container.replace_item(
                item=item.item_id,
                body=body,
                etag=if_match,
                match_condition=MatchConditions.IfNotModified,
            )
        except (CosmosAccessConditionFailedError, CosmosResourceNotFoundError) as exc:
            raise StaleVersionError(
                "review item changed since it was read", reason="etag_mismatch"
            ) from exc
        except Exception as exc:
            _raise_mapped(exc)
        return _item_from_row(row)

    async def list(
        self,
        scope: IdentityScope,
        domain: str,
        *,
        kind: str | None = None,
        state: str | None = None,
        cursor: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> Page[ReviewItem]:
        _check_limit(limit)
        after = decode_cursor(cursor) if cursor else None
        if domain not in scope.allowed_domains:
            return Page[ReviewItem](items=(), next_cursor=None)
        clauses = ["c.cloud = @cloud"]
        params: builtins.list[dict[str, Any]] = [
            {"name": "@cloud", "value": scope.cloud},
            {"name": "@limit", "value": limit + 1},
        ]
        if kind is not None:
            clauses.append("c.kind = @kind")
            params.append({"name": "@kind", "value": kind})
        if state is not None:
            clauses.append("c.state_name = @state")
            params.append({"name": "@state", "value": state})
        if after is not None:
            clauses.append("c.sort_key > @after")
            params.append({"name": "@after", "value": f"{after[0]}|{after[1]}"})
        # Only fixed clause text and parameter placeholders are interpolated.
        sql = (
            "SELECT TOP @limit * FROM c WHERE "  # noqa: S608
            + " AND ".join(clauses)
            + " ORDER BY c.sort_key ASC"
        )
        rows = await self._query(sql, params, partition_key=[scope.customer_id, domain])
        items = [_item_from_row(row) for row in rows]
        page = items[:limit]
        next_cursor = encode_cursor(page[-1]) if len(items) > limit else None
        return Page[ReviewItem](items=tuple(page), next_cursor=next_cursor)

    async def due(self, now: datetime, limit: int = 100) -> builtins.list[ReviewItem]:
        _check_limit(limit)
        rows = await self._query(
            "SELECT TOP @limit * FROM c WHERE IS_DEFINED(c.due_key) AND c.due_ts <= @now "
            "ORDER BY c.due_key ASC",
            [
                {"name": "@limit", "value": limit},
                {"name": "@now", "value": format_timestamp(now)},
            ],
            partition_key=None,
        )
        return [_item_from_row(row) for row in rows]

    async def _query(
        self,
        sql: str,
        parameters: builtins.list[dict[str, Any]],
        *,
        partition_key: builtins.list[str] | None,
    ) -> builtins.list[Mapping[str, Any]]:
        try:
            if partition_key is None:
                return [
                    row async for row in self._container.query_items(sql, parameters=parameters)
                ]
            return [
                row
                async for row in self._container.query_items(
                    sql, parameters=parameters, partition_key=partition_key
                )
            ]
        except Exception as exc:
            _raise_mapped(exc)


class CosmosDecisionStore:
    """:class:`neurosphere_core.hitl.decisions.DecisionStore` on Cosmos. Append-only.

    Partitioned by ``review_item_id`` (taken from the document), so ``list_for_item`` is a
    single-partition query. Like the in-memory store, it does not check the review item exists.
    """

    def __init__(
        self,
        container: ContainerProxy,
        *,
        clock_ns: Callable[[], int] = time.time_ns,
    ) -> None:
        self._container = container
        self._clock_ns = clock_ns
        self._last_ns = 0

    @classmethod
    def from_client(
        cls,
        client: CosmosClient,
        *,
        database: str,
        container: str = DEFAULT_DECISION_CONTAINER,
    ) -> CosmosDecisionStore:
        return cls(client.get_database_client(database).get_container_client(container))

    def _next_ns(self) -> int:
        self._last_ns = max(self._clock_ns(), self._last_ns + 1)
        return self._last_ns

    async def create(self, decision_id: str, document: Mapping[str, Any]) -> None:
        review_item_id = document.get("review_item_id")
        if not isinstance(review_item_id, str) or not review_item_id:
            raise InvalidSchemaError(
                "decision carries no review item id", reason="decision_item_missing"
            )
        body = {**dict(document), "id": decision_id, "recorded_ns": self._next_ns()}
        try:
            await self._container.create_item(body=body)
        except CosmosResourceExistsError as exc:
            raise StaleVersionError("decision already recorded", reason="decision_exists") from exc
        except Exception as exc:
            _raise_mapped(exc)

    async def get(self, decision_id: str) -> dict[str, Any] | None:
        rows = await self._query(
            "SELECT TOP 1 * FROM c WHERE c.id = @id",
            [{"name": "@id", "value": decision_id}],
            partition_key=None,
        )
        return _decision_document(rows[0]) if rows else None

    async def list_for_item(self, review_item_id: str) -> builtins.list[dict[str, Any]]:
        rows = await self._query(
            "SELECT TOP @limit * FROM c WHERE c.review_item_id = @item ORDER BY c.recorded_ns ASC",
            [
                {"name": "@limit", "value": _MAX_DECISIONS_PER_ITEM},
                {"name": "@item", "value": review_item_id},
            ],
            partition_key=[review_item_id],
        )
        return [_decision_document(row) for row in rows]

    async def _query(
        self,
        sql: str,
        parameters: builtins.list[dict[str, Any]],
        *,
        partition_key: builtins.list[str] | None,
    ) -> builtins.list[Mapping[str, Any]]:
        try:
            if partition_key is None:
                return [
                    row async for row in self._container.query_items(sql, parameters=parameters)
                ]
            return [
                row
                async for row in self._container.query_items(
                    sql, parameters=parameters, partition_key=partition_key
                )
            ]
        except Exception as exc:
            _raise_mapped(exc)


def _decision_document(row: Mapping[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in row.items() if not k.startswith("_") and k not in _DECISION_FIELDS}
