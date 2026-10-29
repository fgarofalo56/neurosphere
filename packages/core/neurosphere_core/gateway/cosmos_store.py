"""Cosmos NoSQL gateway store (azure-cosmos aio).

Container ``gateways``, hierarchical partition key ``/customer_id``, ``/domain_id``. Two document
types per partition: ``doc_type = gateway`` (``id`` = gateway id; Cosmos ``_etag`` is the store
ETag) and ``doc_type = gateway_inventory`` (``id`` = ``inv-<gateway id>``, replaced wholesale with
``upsert_item``). Replace is ``IfNotModified`` on ``_etag``. Messages never echo SDK text.
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

from neurosphere_core.errors import DependencyTransientError, NeuroSphereError, RateLimitedError
from neurosphere_core.gateway.models import GatewayInventory, GatewayRegistration
from neurosphere_core.gateway.store import (
    already_registered,
    check_limit,
    decode_cursor,
    encode_cursor,
    modified,
    store_unavailable,
)
from neurosphere_core.paging import Page
from neurosphere_core.paging.models import DEFAULT_PAGE_SIZE

__all__ = [
    "DEFAULT_GATEWAY_CONTAINER",
    "GATEWAY_PARTITION_KEY_PATHS",
    "CosmosGatewayStore",
    "create_gateway_container",
]

DEFAULT_GATEWAY_CONTAINER: Final = "gateways"
GATEWAY_PARTITION_KEY_PATHS: Final = ("/customer_id", "/domain_id")
GATEWAY_DOC_TYPE: Final = "gateway"
INVENTORY_DOC_TYPE: Final = "gateway_inventory"
_QUERY_FIELDS: Final = frozenset({"doc_type", "sort_key"})


async def create_gateway_container(
    database: DatabaseProxy, container_id: str = DEFAULT_GATEWAY_CONTAINER
) -> ContainerProxy:
    return await database.create_container_if_not_exists(
        id=container_id,
        partition_key=PartitionKey(path=list(GATEWAY_PARTITION_KEY_PATHS), kind="MultiHash"),
    )


def _raise_mapped(exc: Exception) -> NoReturn:
    if isinstance(exc, NeuroSphereError):
        raise exc
    if isinstance(exc, CosmosHttpResponseError) and exc.status_code == 429:
        raise RateLimitedError(1, "gateway store throttled the request") from exc
    raise store_unavailable() from exc


def _invalid() -> DependencyTransientError:
    return DependencyTransientError(
        "stored gateway failed validation", reason="gateway_record_invalid", upstream_invalid=True
    )


def _strip(document: Mapping[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in document.items() if not k.startswith("_") and k not in _QUERY_FIELDS}


def _registration(row: Mapping[str, Any]) -> GatewayRegistration:
    try:
        return GatewayRegistration.model_validate(
            {**_strip(row), "etag": str(row.get("_etag", "")) or None}
        )
    except ValidationError as exc:
        raise _invalid() from exc


def _inventory_id(gateway_id: str) -> str:
    return f"inv-{gateway_id}"


class CosmosGatewayStore:
    """:class:`neurosphere_core.gateway.store.GatewayStore` on one Cosmos container."""

    def __init__(self, container: ContainerProxy) -> None:
        self._container = container

    @classmethod
    def from_client(
        cls, client: CosmosClient, *, database: str, container: str = DEFAULT_GATEWAY_CONTAINER
    ) -> CosmosGatewayStore:
        return cls(client.get_database_client(database).get_container_client(container))

    @staticmethod
    def _body(registration: GatewayRegistration) -> dict[str, Any]:
        body = registration.model_dump(mode="json", exclude={"etag"})
        body["doc_type"] = GATEWAY_DOC_TYPE
        body["sort_key"] = registration.sort_key()
        return body

    async def create(self, registration: GatewayRegistration) -> GatewayRegistration:
        try:
            row = await self._container.create_item(body=self._body(registration))
        except CosmosResourceExistsError as exc:
            raise already_registered() from exc
        except Exception as exc:
            _raise_mapped(exc)
        return _registration(row)

    async def get(
        self, customer_id: str, domain_id: str, gateway_id: str
    ) -> GatewayRegistration | None:
        try:
            row = await self._container.read_item(
                item=gateway_id, partition_key=[customer_id, domain_id]
            )
        except CosmosResourceNotFoundError:
            return None
        except Exception as exc:
            _raise_mapped(exc)
        if row.get("doc_type") != GATEWAY_DOC_TYPE:
            return None
        return _registration(row)

    async def find(self, customer_id: str, gateway_id: str) -> GatewayRegistration | None:
        """Cross-partition point query by customer and gateway id (ids are unique per customer)."""
        sql = (
            "SELECT TOP 1 * FROM c WHERE c.doc_type = @doc_type"
            " AND c.customer_id = @customer AND c.id = @id"
        )
        params: builtins.list[dict[str, Any]] = [
            {"name": "@doc_type", "value": GATEWAY_DOC_TYPE},
            {"name": "@customer", "value": customer_id},
            {"name": "@id", "value": gateway_id},
        ]
        try:
            rows = [row async for row in self._container.query_items(sql, parameters=params)]
        except Exception as exc:
            _raise_mapped(exc)
        return _registration(rows[0]) if rows else None

    async def list(
        self,
        customer_id: str,
        domain_id: str,
        *,
        cursor: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> Page[GatewayRegistration]:
        check_limit(limit)
        clauses = ["c.doc_type = @doc_type"]
        params: builtins.list[dict[str, Any]] = [
            {"name": "@doc_type", "value": GATEWAY_DOC_TYPE},
            {"name": "@limit", "value": limit + 1},
        ]
        if cursor is not None:
            clauses.append("c.sort_key < @after")
            params.append({"name": "@after", "value": decode_cursor(cursor)})
        # Only fixed clause text and parameter placeholders are interpolated.
        sql = (
            "SELECT TOP @limit * FROM c WHERE "  # noqa: S608
            + " AND ".join(clauses)
            + " ORDER BY c.sort_key DESC"
        )
        try:
            rows = [
                row
                async for row in self._container.query_items(
                    sql, parameters=params, partition_key=[customer_id, domain_id]
                )
            ]
        except Exception as exc:
            _raise_mapped(exc)
        found = [_registration(row) for row in rows]
        page = found[:limit]
        next_cursor = encode_cursor(page[-1].sort_key()) if len(found) > limit else None
        return Page[GatewayRegistration](items=tuple(page), next_cursor=next_cursor)

    async def replace(
        self, registration: GatewayRegistration, *, if_match: str
    ) -> GatewayRegistration:
        body = self._body(registration)
        try:
            row = await self._container.replace_item(
                item=registration.id,
                body=body,
                etag=if_match,
                match_condition=MatchConditions.IfNotModified,
            )
        except (CosmosAccessConditionFailedError, CosmosResourceNotFoundError) as exc:
            raise modified() from exc
        except Exception as exc:
            _raise_mapped(exc)
        return _registration(row)

    async def put_inventory(
        self, customer_id: str, domain_id: str, inventory: GatewayInventory
    ) -> None:
        body = inventory.model_dump(mode="json")
        body.update(
            id=_inventory_id(inventory.gateway_id),
            doc_type=INVENTORY_DOC_TYPE,
            customer_id=customer_id,
            domain_id=domain_id,
        )
        try:
            await self._container.upsert_item(body=body)
        except Exception as exc:
            _raise_mapped(exc)

    async def get_inventory(
        self, customer_id: str, domain_id: str, gateway_id: str
    ) -> GatewayInventory | None:
        try:
            row = await self._container.read_item(
                item=_inventory_id(gateway_id), partition_key=[customer_id, domain_id]
            )
        except CosmosResourceNotFoundError:
            return None
        except Exception as exc:
            _raise_mapped(exc)
        if row.get("doc_type") != INVENTORY_DOC_TYPE:
            return None
        try:
            fields = {
                k: v
                for k, v in row.items()
                if not k.startswith("_") and k not in {"id", "doc_type", "customer_id", "domain_id"}
            }
            return GatewayInventory.model_validate(fields)
        except ValidationError as exc:
            raise _invalid() from exc
