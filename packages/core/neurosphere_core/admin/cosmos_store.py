"""Cosmos NoSQL ``admin_config`` store (azure-cosmos aio).

Container ``admin_config``, partition key ``/customer_id``. One row per ``(kind, id)``:

    {"id": "<kind>:<config id>", "doc_type": "admin_config", "customer_id", "kind", "status",
     "document": <AdminConfigDocument without etag>}

The Cosmos ``id`` is composite because the contract ``id`` is unique per customer AND kind, while
Cosmos ids are unique per partition. The Cosmos ``_etag`` is the contract ``etag``; replace is
``IfNotModified`` (412/404 -> ``stale_version`` ``admin_config_modified``), create is create-only
(409 -> ``stale_version`` ``admin_config_exists``). Queries are parameterized over fixed fields and
pinned to the customer's partition. Outages -> ``dependency_transient``
(``admin_config_unavailable``); 429 -> ``rate_limited``; a row that fails validation ->
``dependency_transient`` with ``upstream_invalid``. Messages never echo SDK text or documents.
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
from neurosphere_contracts.admin.v1.admin_config_document import AdminConfigDocument
from pydantic import ValidationError

from neurosphere_core.admin.models import (
    ADMIN_CONFIG_CONTAINER,
    ADMIN_CONFIG_PARTITION_KEY_PATH,
    CloudName,
)
from neurosphere_core.admin.store import (
    AdminConfigStoreBase,
    Clock,
    admin_config_exists,
    admin_config_modified,
    admin_config_unavailable,
)
from neurosphere_core.errors import DependencyTransientError, NeuroSphereError, RateLimitedError

__all__ = [
    "ADMIN_CONFIG_DOC_TYPE",
    "CosmosAdminConfigRepository",
    "cosmos_item_id",
    "create_admin_config_container",
]

ADMIN_CONFIG_DOC_TYPE: Final = "admin_config"


def cosmos_item_id(kind: str, config_id: str) -> str:
    """Composite Cosmos id of one configuration document (``<kind>:<config id>``)."""
    return f"{kind}:{config_id}"


async def create_admin_config_container(
    database: DatabaseProxy, container_id: str = ADMIN_CONFIG_CONTAINER
) -> ContainerProxy:
    """Create (or open) the container (partition ``/customer_id``). Local emulator only."""
    return await database.create_container_if_not_exists(
        id=container_id, partition_key=PartitionKey(path=ADMIN_CONFIG_PARTITION_KEY_PATH)
    )


def _raise_mapped(exc: Exception) -> NoReturn:
    if isinstance(exc, NeuroSphereError):
        raise exc
    if isinstance(exc, CosmosHttpResponseError) and exc.status_code == 429:
        raise RateLimitedError(1, "admin configuration store throttled the request") from exc
    raise admin_config_unavailable() from exc


def _invalid_row() -> DependencyTransientError:
    return DependencyTransientError(
        "admin configuration document failed validation",
        reason="admin_config_document_invalid",
        upstream_invalid=True,
    )


def _from_row(row: Mapping[str, Any], customer_id: str) -> AdminConfigDocument:
    document = row.get("document")
    etag = str(row.get("_etag", ""))
    if not isinstance(document, Mapping) or not etag:
        raise _invalid_row()
    try:
        parsed = AdminConfigDocument.model_validate({**document, "etag": etag})
    except ValidationError as exc:
        raise _invalid_row() from exc
    if (
        parsed.customer_id.root != customer_id
        or row.get("customer_id") != customer_id
        or row.get("id") != cosmos_item_id(parsed.kind.root, parsed.id.root)
    ):
        raise _invalid_row()
    return parsed


def _to_row(document: AdminConfigDocument) -> dict[str, Any]:
    body = document.model_dump(mode="json", exclude_none=True, exclude={"etag"})
    return {
        "id": cosmos_item_id(document.kind.root, document.id.root),
        "doc_type": ADMIN_CONFIG_DOC_TYPE,
        "customer_id": document.customer_id.root,
        "kind": document.kind.root,
        "status": document.status,
        "document": body,
    }


class CosmosAdminConfigRepository(AdminConfigStoreBase):
    """:class:`~neurosphere_core.admin.store.AdminConfigRepository` on one Cosmos container."""

    def __init__(
        self,
        container: ContainerProxy,
        *,
        cloud: CloudName | None = None,
        clock: Clock | None = None,
    ) -> None:
        super().__init__(cloud=cloud, clock=clock)
        self._container = container

    @classmethod
    def from_client(
        cls,
        client: CosmosClient,
        *,
        database: str,
        container: str = ADMIN_CONFIG_CONTAINER,
        cloud: CloudName | None = None,
        clock: Clock | None = None,
    ) -> CosmosAdminConfigRepository:
        proxy = client.get_database_client(database).get_container_client(container)
        return cls(proxy, cloud=cloud, clock=clock)

    async def _read(
        self, customer_id: str, kind: str, config_id: str
    ) -> AdminConfigDocument | None:
        try:
            row = await self._container.read_item(
                item=cosmos_item_id(kind, config_id), partition_key=customer_id
            )
        except CosmosResourceNotFoundError:
            return None
        except Exception as exc:
            _raise_mapped(exc)
        if row.get("doc_type") != ADMIN_CONFIG_DOC_TYPE:
            return None
        return _from_row(row, customer_id)

    async def _insert(self, document: AdminConfigDocument) -> AdminConfigDocument:
        try:
            row = await self._container.create_item(body=_to_row(document))
        except CosmosResourceExistsError:
            raise admin_config_exists() from None
        except Exception as exc:
            _raise_mapped(exc)
        return _from_row(row, document.customer_id.root)

    async def _replace(
        self, document: AdminConfigDocument, *, if_match: str
    ) -> AdminConfigDocument:
        row_body = _to_row(document)
        try:
            row = await self._container.replace_item(
                item=row_body["id"],
                body=row_body,
                etag=if_match,
                match_condition=MatchConditions.IfNotModified,
            )
        except (CosmosAccessConditionFailedError, CosmosResourceNotFoundError) as exc:
            raise admin_config_modified() from exc
        except Exception as exc:
            _raise_mapped(exc)
        return _from_row(row, document.customer_id.root)

    async def _scan(
        self, customer_id: str, kind: str, *, include_retired: bool, limit: int
    ) -> builtins.list[AdminConfigDocument]:
        sql = "SELECT TOP @limit * FROM c WHERE c.doc_type = @doc_type AND c.kind = @kind"
        params: builtins.list[dict[str, Any]] = [
            {"name": "@limit", "value": limit},
            {"name": "@doc_type", "value": ADMIN_CONFIG_DOC_TYPE},
            {"name": "@kind", "value": kind},
        ]
        if not include_retired:
            sql += " AND c.status = @status"
            params.append({"name": "@status", "value": "active"})
        sql += " ORDER BY c.id ASC"
        try:
            rows = [
                row
                async for row in self._container.query_items(
                    sql, parameters=params, partition_key=customer_id
                )
            ]
        except Exception as exc:
            _raise_mapped(exc)
        docs = [_from_row(row, customer_id) for row in rows]
        docs.sort(key=lambda d: d.id.root)
        return docs
