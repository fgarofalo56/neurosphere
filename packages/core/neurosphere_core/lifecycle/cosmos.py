"""Cosmos NoSQL lifecycle stores: pseudonym mapping store, legal-hold registry, request queue.

Three containers, each partition key ``/customer_id`` (Hash; the wire contract):
``lifecycle_mappings``, ``lifecycle_holds``, ``lifecycle_requests``.

The lifecycle protocols (:mod:`neurosphere_core.lifecycle.targets`) carry no customer, so each
store is bound to one ``customer_id`` at construction (a deployment is customer-hosted) and
every read, write and query is a single-partition operation on that customer. A different
customer needs a different store instance; nothing here can reach another customer's rows.

Document ids are SHA-256 hex digests of the natural key (subject id, hold id, request dedupe key),
because those keys may contain characters Cosmos forbids in ids (``/``, ``\\``, ``?``, ``#``) and
the mapping store must not leak a person identifier into an id or an access log. The mapping
store holds the subject id as data (it IS the mapping).

* Mapping: ``register`` (create/overwrite), ``exists`` (point read), ``destroy`` (point delete; a
  missing mapping is not an error, like the in-memory store).
* Holds: ``place`` is an upsert (re-placing a hold id overwrites), ``release`` a delete whose 404
  is ``False``, ``active`` a single-partition query.
* Requests: ``enqueue`` is create-only on the dedupe-key digest (409 -> ``False``, so an equal
  queued request is never duplicated); ``remove`` finds the row by ``request_id`` inside the
  partition and deletes it, after which the same request can be queued again.
"""

from __future__ import annotations

import builtins
import hashlib
from collections.abc import Mapping
from datetime import UTC
from typing import Any, Final, NoReturn

from azure.cosmos import PartitionKey
from azure.cosmos.aio import ContainerProxy, CosmosClient, DatabaseProxy
from azure.cosmos.exceptions import (
    CosmosHttpResponseError,
    CosmosResourceExistsError,
    CosmosResourceNotFoundError,
)
from pydantic import ValidationError

from neurosphere_core.errors import DependencyTransientError, NeuroSphereError, RateLimitedError
from neurosphere_core.lifecycle.models import LegalHold
from neurosphere_core.lifecycle.targets import QueuedRequest

__all__ = [
    "DEFAULT_HOLD_CONTAINER",
    "DEFAULT_MAPPING_CONTAINER",
    "DEFAULT_REQUEST_CONTAINER",
    "LIFECYCLE_PARTITION_KEY_PATH",
    "CosmosHoldRegistry",
    "CosmosMappingStore",
    "CosmosRequestQueue",
    "create_hold_container",
    "create_mapping_container",
    "create_request_container",
]

DEFAULT_MAPPING_CONTAINER: Final = "lifecycle_mappings"
DEFAULT_HOLD_CONTAINER: Final = "lifecycle_holds"
DEFAULT_REQUEST_CONTAINER: Final = "lifecycle_requests"
LIFECYCLE_PARTITION_KEY_PATH: Final = "/customer_id"
_OURS: Final = frozenset({"id", "customer_id", "request_id", "queued_key"})


async def _create(database: DatabaseProxy, container_id: str) -> ContainerProxy:
    return await database.create_container_if_not_exists(
        id=container_id, partition_key=PartitionKey(path=LIFECYCLE_PARTITION_KEY_PATH)
    )


async def create_mapping_container(
    database: DatabaseProxy, container_id: str = DEFAULT_MAPPING_CONTAINER
) -> ContainerProxy:
    return await _create(database, container_id)


async def create_hold_container(
    database: DatabaseProxy, container_id: str = DEFAULT_HOLD_CONTAINER
) -> ContainerProxy:
    return await _create(database, container_id)


async def create_request_container(
    database: DatabaseProxy, container_id: str = DEFAULT_REQUEST_CONTAINER
) -> ContainerProxy:
    return await _create(database, container_id)


def _digest(natural_key: str) -> str:
    return hashlib.sha256(natural_key.encode("utf-8")).hexdigest()


def _raise_mapped(exc: Exception) -> NoReturn:
    if isinstance(exc, NeuroSphereError):
        raise exc
    if isinstance(exc, CosmosHttpResponseError) and exc.status_code == 429:
        raise RateLimitedError(1, "lifecycle store throttled the request") from exc
    raise DependencyTransientError(
        "lifecycle store unavailable", reason="lifecycle_store_unavailable"
    ) from exc


def _invalid(exc: ValidationError) -> DependencyTransientError:
    error = DependencyTransientError(
        "stored lifecycle document failed validation",
        reason="lifecycle_record_invalid",
        upstream_invalid=True,
    )
    error.__cause__ = exc
    return error


def _document(row: Mapping[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in row.items() if not k.startswith("_") and k not in _OURS}


async def _select(
    container: ContainerProxy, sql: str, parameters: builtins.list[dict[str, Any]], customer: str
) -> builtins.list[Mapping[str, Any]]:
    try:
        return [
            row
            async for row in container.query_items(
                sql, parameters=parameters, partition_key=customer
            )
        ]
    except Exception as exc:
        _raise_mapped(exc)


class CosmosMappingStore:
    """:class:`PseudonymMappingStore` for one customer, plus ``register`` to create mappings."""

    def __init__(self, container: ContainerProxy, *, customer_id: str) -> None:
        self._container = container
        self._customer = customer_id

    @classmethod
    def from_client(
        cls,
        client: CosmosClient,
        *,
        database: str,
        customer_id: str,
        container: str = DEFAULT_MAPPING_CONTAINER,
    ) -> CosmosMappingStore:
        return cls(
            client.get_database_client(database).get_container_client(container),
            customer_id=customer_id,
        )

    async def register(self, subject_id: str) -> None:
        """Record that a mapping exists for ``subject_id`` (idempotent)."""
        try:
            await self._container.upsert_item(
                body={
                    "id": _digest(subject_id),
                    "customer_id": self._customer,
                    "subject_id": subject_id,
                }
            )
        except Exception as exc:
            _raise_mapped(exc)

    async def exists(self, subject_id: str) -> bool:
        try:
            await self._container.read_item(item=_digest(subject_id), partition_key=self._customer)
        except CosmosResourceNotFoundError:
            return False
        except Exception as exc:
            _raise_mapped(exc)
        return True

    async def destroy(self, subject_id: str) -> None:
        try:
            await self._container.delete_item(
                item=_digest(subject_id), partition_key=self._customer
            )
        except CosmosResourceNotFoundError:
            return
        except Exception as exc:
            _raise_mapped(exc)


class CosmosHoldRegistry:
    """:class:`HoldRegistry` for one customer."""

    def __init__(self, container: ContainerProxy, *, customer_id: str) -> None:
        self._container = container
        self._customer = customer_id

    @classmethod
    def from_client(
        cls,
        client: CosmosClient,
        *,
        database: str,
        customer_id: str,
        container: str = DEFAULT_HOLD_CONTAINER,
    ) -> CosmosHoldRegistry:
        return cls(
            client.get_database_client(database).get_container_client(container),
            customer_id=customer_id,
        )

    async def place(self, hold: LegalHold) -> None:
        body = {
            **hold.model_dump(mode="json"),
            "id": _digest(hold.hold_id),
            "customer_id": self._customer,
        }
        try:
            await self._container.upsert_item(body=body)
        except Exception as exc:
            _raise_mapped(exc)

    async def release(self, hold_id: str) -> bool:
        try:
            await self._container.delete_item(item=_digest(hold_id), partition_key=self._customer)
        except CosmosResourceNotFoundError:
            return False
        except Exception as exc:
            _raise_mapped(exc)
        return True

    async def active(self) -> builtins.list[LegalHold]:
        rows = await _select(
            self._container,
            "SELECT * FROM c WHERE c.customer_id = @customer",
            [{"name": "@customer", "value": self._customer}],
            self._customer,
        )
        try:
            return [LegalHold.model_validate(_document(row)) for row in rows]
        except ValidationError as exc:
            raise _invalid(exc) from exc


class CosmosRequestQueue:
    """:class:`RequestQueue` for one customer."""

    def __init__(self, container: ContainerProxy, *, customer_id: str) -> None:
        self._container = container
        self._customer = customer_id

    @classmethod
    def from_client(
        cls,
        client: CosmosClient,
        *,
        database: str,
        customer_id: str,
        container: str = DEFAULT_REQUEST_CONTAINER,
    ) -> CosmosRequestQueue:
        return cls(
            client.get_database_client(database).get_container_client(container),
            customer_id=customer_id,
        )

    async def enqueue(self, item: QueuedRequest) -> bool:
        body = {
            **item.model_dump(mode="json"),
            "id": _digest(item.request.dedupe_key),
            "customer_id": self._customer,
            "request_id": item.request.request_id,
            "queued_key": (
                f"{item.queued_at.astimezone(UTC).strftime('%Y-%m-%dT%H:%M:%S.%f')}"
                f"|{item.request.request_id}"
            ),
        }
        try:
            await self._container.create_item(body=body)
        except CosmosResourceExistsError:
            return False
        except Exception as exc:
            _raise_mapped(exc)
        return True

    async def pending(self) -> builtins.list[QueuedRequest]:
        rows = await _select(
            self._container,
            "SELECT * FROM c WHERE c.customer_id = @customer ORDER BY c.queued_key ASC",
            [{"name": "@customer", "value": self._customer}],
            self._customer,
        )
        try:
            return [QueuedRequest.model_validate(_document(row)) for row in rows]
        except ValidationError as exc:
            raise _invalid(exc) from exc

    async def remove(self, request_id: str) -> None:
        rows = await _select(
            self._container,
            "SELECT c.id FROM c WHERE c.request_id = @request",
            [{"name": "@request", "value": request_id}],
            self._customer,
        )
        for row in rows:
            try:
                await self._container.delete_item(item=row["id"], partition_key=self._customer)
            except CosmosResourceNotFoundError:
                continue
            except Exception as exc:
                _raise_mapped(exc)
