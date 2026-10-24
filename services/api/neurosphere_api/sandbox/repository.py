"""Sandbox repository: a fixed database/container allowlist enforced before any client call.

Fail closed (PRP-24 clarification 8): the allowlist is the set of names below, not a prefix rule.
A look-alike such as ``sandbox-catalog`` and a real name such as ``entities`` are both refused
with ``InvalidSchemaError(reason="sandbox_allowlist")`` before the store is touched.

Local-only: the Cosmos store uses the emulator path of ``neurosphere_core.clients`` (NS_ENV=local,
emulator key from the environment); no credential type and no egress beyond that.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, Final, Protocol

from azure.core.exceptions import AzureError
from azure.cosmos.aio import CosmosClient
from neurosphere_core.errors import (
    DependencyTransientError,
    InvalidSchemaError,
    ValidationIssue,
)

from neurosphere_api.sandbox.models import SandboxKind

__all__ = [
    "ALLOWED_CONTAINERS",
    "ALLOWED_DATABASE",
    "ENTITIES_CONTAINER",
    "RELATIONS_CONTAINER",
    "CosmosSandboxStore",
    "SandboxRepository",
    "SandboxStore",
]

ALLOWED_DATABASE: Final = "sandbox-neurosphere"
ENTITIES_CONTAINER: Final = "sandbox-entities"
RELATIONS_CONTAINER: Final = "sandbox-relations"
ALLOWED_CONTAINERS: Final = frozenset({ENTITIES_CONTAINER, RELATIONS_CONTAINER})

MAX_PAGE_SIZE: Final = 100


def _refuse(kind: str) -> InvalidSchemaError:
    detail = f"{kind} is not in the sandbox allowlist"
    return InvalidSchemaError(
        detail, errors=[ValidationIssue(f"/{kind}", detail)], reason="sandbox_allowlist"
    )


def require_database(name: str) -> str:
    if name != ALLOWED_DATABASE:
        raise _refuse("database")
    return name


def require_container(name: str) -> str:
    if name not in ALLOWED_CONTAINERS:
        raise _refuse("container")
    return name


class SandboxStore(Protocol):
    """The only client surface the repository uses; every call names database and container."""

    async def count(self, database: str, container: str, kind: str | None) -> int: ...

    async def list_items(
        self, database: str, container: str, kind: str, limit: int, offset: int
    ) -> list[dict[str, Any]]: ...

    async def clear(self, database: str, container: str) -> int: ...


class SandboxRepository:
    """Reads and writes only allowlisted sandbox containers."""

    def __init__(
        self,
        store: SandboxStore,
        *,
        database: str = ALLOWED_DATABASE,
        containers: tuple[str, ...] = (ENTITIES_CONTAINER, RELATIONS_CONTAINER),
    ) -> None:
        self._database = require_database(database)
        self._containers = tuple(require_container(c) for c in containers)
        self._store = store

    @property
    def database(self) -> str:
        return self._database

    async def counts_by_kind(self) -> Mapping[str, int]:
        require_container(ENTITIES_CONTAINER)
        result = {
            k.value: await self._store.count(self._database, ENTITIES_CONTAINER, k.value)
            for k in SandboxKind
        }
        return MappingProxyType(result)

    async def count_container(self, container: str) -> int:
        require_container(container)
        return await self._store.count(self._database, container, None)

    async def list_entities(
        self, kind: SandboxKind, limit: int, offset: int
    ) -> list[dict[str, Any]]:
        bounded = max(1, min(limit, MAX_PAGE_SIZE))
        return await self._store.list_items(
            self._database,
            require_container(ENTITIES_CONTAINER),
            kind.value,
            bounded,
            max(offset, 0),
        )

    async def reset(self) -> dict[str, int]:
        deleted: dict[str, int] = {}
        for container in self._containers:
            deleted[container] = await self._store.clear(
                self._database, require_container(container)
            )
        return deleted


class CosmosSandboxStore:
    """Async Cosmos implementation; re-checks the allowlist so it is safe even if used directly."""

    def __init__(self, client: CosmosClient) -> None:
        self._client = client

    def _container(self, database: str, container: str) -> Any:
        db_name = require_database(database)
        container_name = require_container(container)  # both checked before any client call
        return self._client.get_database_client(db_name).get_container_client(container_name)

    async def count(self, database: str, container: str, kind: str | None) -> int:
        handle = self._container(database, container)
        query = "SELECT VALUE COUNT(1) FROM c"
        params: list[dict[str, Any]] = []
        if kind is not None:
            query += " WHERE c.entity_type = @kind"
            params = [{"name": "@kind", "value": kind}]
        try:
            async for value in handle.query_items(query=query, parameters=params):
                return int(value)
        except AzureError as exc:
            raise _unavailable() from exc
        return 0

    async def list_items(
        self, database: str, container: str, kind: str, limit: int, offset: int
    ) -> list[dict[str, Any]]:
        handle = self._container(database, container)
        query = "SELECT * FROM c WHERE c.entity_type = @kind ORDER BY c.id OFFSET @o LIMIT @l"
        params: list[dict[str, Any]] = [
            {"name": "@kind", "value": kind},
            {"name": "@o", "value": offset},
            {"name": "@l", "value": limit},
        ]
        try:
            return [
                {k: v for k, v in item.items() if not k.startswith("_")}
                async for item in handle.query_items(query=query, parameters=params)
            ]
        except AzureError as exc:
            raise _unavailable() from exc

    async def clear(self, database: str, container: str) -> int:
        handle = self._container(database, container)
        deleted = 0
        try:
            ids = [i async for i in handle.query_items(query="SELECT VALUE c.id FROM c")]
            for item_id in ids:
                await handle.delete_item(item=item_id, partition_key=item_id)
                deleted += 1
        except AzureError as exc:
            raise _unavailable() from exc
        return deleted


def _unavailable() -> DependencyTransientError:
    return DependencyTransientError(
        "sandbox store is unavailable", reason="sandbox_store_unavailable"
    )
