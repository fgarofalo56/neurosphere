"""Cosmos NoSQL MCP server registry (azure-cosmos aio).

Container: partition key ``/id``; one document per registered server, ``id`` = the server id
derived from the exact normalised URL (so the URL is unique by construction and a duplicate
registration is a create-only 409). ``doc_type = mcp_server``. The Cosmos ``_etag`` is the store
ETag; replace is ``IfNotModified`` (412/404 -> ``stale_version`` ``server_modified``).

Queries are parameterized with fixed field names. Outages -> ``dependency_transient``
(``mcp_registry_unavailable``); 429 -> ``rate_limited``; a document that fails validation ->
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
from pydantic import ValidationError

from neurosphere_core.errors import NeuroSphereError, RateLimitedError
from neurosphere_core.mcp.models import RegisteredServer
from neurosphere_core.mcp.store import (
    RegistryStoreBase,
    already_registered,
    record_invalid,
    registry_unavailable,
    server_modified,
)

__all__ = [
    "DEFAULT_MCP_SERVER_CONTAINER",
    "PARTITION_KEY_PATH",
    "CosmosMcpServerStore",
    "create_mcp_server_container",
]

DEFAULT_MCP_SERVER_CONTAINER: Final = "mcp_servers"
PARTITION_KEY_PATH: Final = "/id"
DOC_TYPE: Final = "mcp_server"


async def create_mcp_server_container(
    database: DatabaseProxy, container_id: str = DEFAULT_MCP_SERVER_CONTAINER
) -> ContainerProxy:
    """Create (or open) the registry container (partition key ``/id``)."""
    return await database.create_container_if_not_exists(
        id=container_id, partition_key=PartitionKey(path=PARTITION_KEY_PATH)
    )


def _raise_mapped(exc: Exception) -> NoReturn:
    if isinstance(exc, NeuroSphereError):
        raise exc
    if isinstance(exc, CosmosHttpResponseError) and exc.status_code == 429:
        raise RateLimitedError(1, "MCP server registry throttled the request") from exc
    raise registry_unavailable() from exc


def _from_row(row: Mapping[str, Any]) -> RegisteredServer:
    document = {k: v for k, v in row.items() if not k.startswith("_") and k != "doc_type"}
    try:
        return RegisteredServer.from_document(document, etag=str(row.get("_etag", "")) or None)
    except ValidationError as exc:
        raise record_invalid() from exc


def _body(server: RegisteredServer) -> dict[str, Any]:
    body = server.to_document()
    body["doc_type"] = DOC_TYPE
    return body


class CosmosMcpServerStore(RegistryStoreBase):
    """:class:`neurosphere_core.mcp.store.McpServerStore` on one Cosmos container."""

    def __init__(self, container: ContainerProxy) -> None:
        self._container = container

    @classmethod
    def from_client(
        cls,
        client: CosmosClient,
        *,
        database: str,
        container: str = DEFAULT_MCP_SERVER_CONTAINER,
    ) -> CosmosMcpServerStore:
        return cls(client.get_database_client(database).get_container_client(container))

    async def _read(self, server_id: str) -> RegisteredServer | None:
        try:
            row = await self._container.read_item(item=server_id, partition_key=server_id)
        except CosmosResourceNotFoundError:
            return None
        except Exception as exc:
            _raise_mapped(exc)
        if row.get("doc_type") != DOC_TYPE:
            return None
        return _from_row(row)

    async def _insert(self, server: RegisteredServer) -> RegisteredServer:
        try:
            row = await self._container.create_item(body=_body(server))
        except CosmosResourceExistsError:
            raise already_registered() from None
        except Exception as exc:
            _raise_mapped(exc)
        return _from_row(row)

    async def _replace(self, server: RegisteredServer, *, if_match: str) -> RegisteredServer:
        try:
            row = await self._container.replace_item(
                item=server.id,
                body=_body(server),
                etag=if_match,
                match_condition=MatchConditions.IfNotModified,
            )
        except (CosmosAccessConditionFailedError, CosmosResourceNotFoundError) as exc:
            raise server_modified() from exc
        except Exception as exc:
            _raise_mapped(exc)
        return _from_row(row)

    async def _scan(self, limit: int) -> builtins.list[RegisteredServer]:
        sql = "SELECT TOP @limit * FROM c WHERE c.doc_type = @doc_type ORDER BY c.registered_at ASC"
        params: builtins.list[dict[str, Any]] = [
            {"name": "@limit", "value": limit},
            {"name": "@doc_type", "value": DOC_TYPE},
        ]
        try:
            rows = [row async for row in self._container.query_items(sql, parameters=params)]
        except Exception as exc:
            _raise_mapped(exc)
        servers = [_from_row(row) for row in rows]
        servers.sort(key=lambda s: (s.registered_at, s.id))
        return servers
