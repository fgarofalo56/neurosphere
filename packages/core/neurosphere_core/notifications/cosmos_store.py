"""Cosmos NoSQL outbox store (azure-cosmos aio) over the PRP-102 ``notification_outbox`` container.

Partition key ``/customer_id`` (as declared in ``stores/containers.py``). One document per row,
``id = notification_id``: the contract fields plus ``ttl`` (per-item expiry in seconds, refreshed
by every write because Cosmos restarts the clock on update). Nothing else is stored: no body, no
recipient. The Cosmos ``_etag`` is the store ETag: ``replace`` is ``IfNotModified`` and a 404 or
412 is ``stale_version`` (``etag_mismatch``), which is how two workers cannot both claim a row.

Query shapes (parameterized, field names fixed): ``due`` runs one query per live status
(``status = @status AND next_attempt_at <= @now ORDER BY next_attempt_at``), single-partition when
a customer is given, otherwise a bounded cross-partition scan; ``find_by_dedup`` is a one-row
single-partition query; ``list_deliveries`` is single-partition. A 429 is ``rate_limited``; every
other failure is ``dependency_transient`` (``notification_store_unavailable``); messages never echo
SDK text or documents.
"""

from __future__ import annotations

from collections.abc import Mapping
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
    NeuroSphereError,
    RateLimitedError,
    StaleVersionError,
)
from neurosphere_core.notifications.models import NotificationDelivery
from neurosphere_core.notifications.outbox import OutboxEntry, format_timestamp

__all__ = [
    "DEFAULT_CONTAINER",
    "DEFAULT_ROW_TTL_SECONDS",
    "PARTITION_KEY_PATH",
    "CosmosOutboxStore",
    "create_outbox_container",
]

DEFAULT_CONTAINER: Final = "notification_outbox"
PARTITION_KEY_PATH: Final = "/customer_id"
#: Rows expire 30 days after their last write.
DEFAULT_ROW_TTL_SECONDS: Final = 30 * 24 * 3600
_MAX_LIST: Final = 500
_DUE_STATUSES: Final = ("pending", "sending")
_DUE_SQL: Final = (
    "SELECT TOP @limit * FROM c WHERE c.status = @status AND c.next_attempt_at <= @now"
    " ORDER BY c.next_attempt_at ASC"
)
_DUE_CUSTOMER_SQL: Final = (
    "SELECT TOP @limit * FROM c WHERE c.customer_id = @customer_id AND c.status = @status"
    " AND c.next_attempt_at <= @now ORDER BY c.next_attempt_at ASC"
)
_DEDUP_SQL: Final = (
    "SELECT TOP 1 * FROM c WHERE c.customer_id = @customer_id AND c.dedup_key = @dedup_key"
    " AND c.created_at >= @since ORDER BY c.created_at ASC"
)
_COUNT_SQL: Final = (
    "SELECT VALUE COUNT(1) FROM c WHERE c.customer_id = @customer_id"
    " AND c.channel_id = @channel_id AND c.status = @status"
)
_LAST_ERROR_SQL: Final = (
    "SELECT TOP 1 c.last_error_code FROM c WHERE c.customer_id = @customer_id"
    " AND c.channel_id = @channel_id AND c.status = @status AND IS_DEFINED(c.last_error_code)"
    " ORDER BY c.created_at DESC"
)
_STORAGE_FIELDS: Final = frozenset({"id", "ttl"})


async def create_outbox_container(
    database: DatabaseProxy, container_id: str = DEFAULT_CONTAINER
) -> ContainerProxy:
    """Create (or open) the outbox container with per-item TTL enabled."""
    return await database.create_container_if_not_exists(
        id=container_id,
        partition_key=PartitionKey(path=PARTITION_KEY_PATH),
        default_ttl=-1,
    )


def _raise_mapped(exc: Exception) -> NoReturn:
    if isinstance(exc, NeuroSphereError):
        raise exc
    if isinstance(exc, CosmosHttpResponseError) and exc.status_code == 429:
        raise RateLimitedError(1, "notification store throttled the request") from exc
    raise DependencyTransientError(
        "notification store unavailable", reason="notification_store_unavailable"
    ) from exc


def _invalid() -> DependencyTransientError:
    return DependencyTransientError(
        "stored notification row failed validation",
        reason="notification_record_invalid",
        upstream_invalid=True,
    )


def _entry(row: Mapping[str, Any]) -> OutboxEntry:
    document = {k: v for k, v in row.items() if not k.startswith("_") and k not in _STORAGE_FIELDS}
    try:
        return OutboxEntry(NotificationDelivery.model_validate(document), str(row.get("_etag", "")))
    except ValidationError as exc:
        raise _invalid() from exc


class CosmosOutboxStore:
    """:class:`~neurosphere_core.notifications.outbox.OutboxStore` on one Cosmos container."""

    def __init__(
        self, container: ContainerProxy, *, row_ttl_seconds: int = DEFAULT_ROW_TTL_SECONDS
    ) -> None:
        if row_ttl_seconds <= 0:
            raise ValueError("row_ttl_seconds must be positive")
        self._container = container
        self._ttl = row_ttl_seconds

    @classmethod
    def from_client(
        cls,
        client: CosmosClient,
        *,
        database: str,
        container: str = DEFAULT_CONTAINER,
        row_ttl_seconds: int = DEFAULT_ROW_TTL_SECONDS,
    ) -> CosmosOutboxStore:
        return cls(
            client.get_database_client(database).get_container_client(container),
            row_ttl_seconds=row_ttl_seconds,
        )

    def _body(self, delivery: NotificationDelivery) -> dict[str, Any]:
        body = delivery.model_dump(mode="json", exclude_none=True)
        body["id"] = delivery.notification_id.root
        body["ttl"] = self._ttl
        return body

    async def create_if_absent(self, delivery: NotificationDelivery) -> tuple[OutboxEntry, bool]:
        try:
            row = await self._container.create_item(body=self._body(delivery))
        except CosmosResourceExistsError:
            existing = await self.get(delivery.customer_id.root, delivery.notification_id.root)
            if existing is None:  # expired between the conflict and the read
                raise DependencyTransientError(
                    "notification store unavailable", reason="notification_store_unavailable"
                ) from None
            return existing, False
        except Exception as exc:
            _raise_mapped(exc)
        return _entry(row), True

    async def get(self, customer_id: str, notification_id: str) -> OutboxEntry | None:
        try:
            row = await self._container.read_item(item=notification_id, partition_key=customer_id)
        except CosmosResourceNotFoundError:
            return None
        except Exception as exc:
            _raise_mapped(exc)
        return _entry(row)

    async def find_by_dedup(
        self, customer_id: str, dedup_key: str, *, since: datetime
    ) -> OutboxEntry | None:
        rows = await self._query(
            _DEDUP_SQL,
            [
                {"name": "@customer_id", "value": customer_id},
                {"name": "@dedup_key", "value": dedup_key},
                {"name": "@since", "value": format_timestamp(since)},
            ],
            partition=customer_id,
        )
        return _entry(rows[0]) if rows else None

    async def due(
        self, *, now: datetime, limit: int, customer_id: str | None = None
    ) -> list[OutboxEntry]:
        limit = max(1, min(limit, _MAX_LIST))
        found: list[OutboxEntry] = []
        for status in _DUE_STATUSES:
            params: list[dict[str, Any]] = [
                {"name": "@limit", "value": limit},
                {"name": "@status", "value": status},
                {"name": "@now", "value": format_timestamp(now)},
            ]
            if customer_id is not None:
                params.append({"name": "@customer_id", "value": customer_id})
            rows = await self._query(
                _DUE_SQL if customer_id is None else _DUE_CUSTOMER_SQL,
                params,
                partition=customer_id,
            )
            found.extend(_entry(r) for r in rows)
        found.sort(
            key=lambda e: (
                e.delivery.next_attempt_at.root if e.delivery.next_attempt_at else "",
                e.delivery.notification_id.root,
            )
        )
        return found[:limit]

    async def list_deliveries(
        self,
        customer_id: str,
        *,
        status: str | None = None,
        channel_id: str | None = None,
        limit: int = 100,
        newest_first: bool = False,
    ) -> list[OutboxEntry]:
        params: list[dict[str, Any]] = [
            {"name": "@limit", "value": max(1, min(limit, _MAX_LIST))},
            {"name": "@customer_id", "value": customer_id},
        ]
        where = "c.customer_id = @customer_id"
        if status is not None:
            params.append({"name": "@status", "value": status})
            where += " AND c.status = @status"
        if channel_id is not None:
            params.append({"name": "@channel_id", "value": channel_id})
            where += " AND c.channel_id = @channel_id"
        order = "DESC" if newest_first else "ASC"
        # Only constant fragments are joined (no caller text); values travel as parameters.
        sql = f"SELECT TOP @limit * FROM c WHERE {where} ORDER BY c.created_at {order}"  # noqa: S608
        rows = await self._query(sql, params, partition=customer_id)
        return [_entry(r) for r in rows]

    async def count_deliveries(self, customer_id: str, *, channel_id: str, status: str) -> int:
        rows = await self._query(
            _COUNT_SQL,
            [
                {"name": "@customer_id", "value": customer_id},
                {"name": "@channel_id", "value": channel_id},
                {"name": "@status", "value": status},
            ],
            partition=customer_id,
        )
        return int(rows[0]) if rows else 0

    async def last_error_code(self, customer_id: str, channel_id: str) -> str | None:
        for status in ("failed", "dead_lettered"):
            rows = await self._query(
                _LAST_ERROR_SQL,
                [
                    {"name": "@customer_id", "value": customer_id},
                    {"name": "@channel_id", "value": channel_id},
                    {"name": "@status", "value": status},
                ],
                partition=customer_id,
            )
            if rows:
                value = rows[0].get("last_error_code")
                return value if isinstance(value, str) else None
        return None

    async def replace(self, entry: OutboxEntry, delivery: NotificationDelivery) -> OutboxEntry:
        try:
            row = await self._container.replace_item(
                item=delivery.notification_id.root,
                body=self._body(delivery),
                etag=entry.etag,
                match_condition=MatchConditions.IfNotModified,
            )
        except (CosmosAccessConditionFailedError, CosmosResourceNotFoundError) as exc:
            raise StaleVersionError(
                "outbox row changed since it was read", reason="etag_mismatch"
            ) from exc
        except Exception as exc:
            _raise_mapped(exc)
        return _entry(row)

    async def _query(
        self, sql: str, params: list[dict[str, Any]], *, partition: str | None
    ) -> list[Any]:
        try:
            if partition is None:
                return [r async for r in self._container.query_items(sql, parameters=params)]
            return [
                r
                async for r in self._container.query_items(
                    sql, parameters=params, partition_key=partition
                )
            ]
        except Exception as exc:
            _raise_mapped(exc)
