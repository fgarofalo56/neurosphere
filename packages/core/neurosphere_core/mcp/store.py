"""MCP server registry store port, the shared transition logic and the in-memory store.

Contract for every implementation (``CosmosMcpServerStore`` in
:mod:`neurosphere_core.mcp.cosmos_store` is the durable one):

* ``register`` is create-only; a second registration of the same exact URL (same derived id)
  raises ``invalid_schema`` reason ``server_already_registered``.
* ``get`` returns ``None`` only for "not registered"; every mutating call on an unknown id
  raises ``forbidden`` ``mcp_server_not_registered``.
* ``update``, ``record_sync``, ``approve`` and ``revoke`` are read-transform-replace under the
  document ETag. An ``if_match`` that is not the current ETag, or a concurrent writer, raises
  ``stale_version`` reason ``server_modified``; nothing is retried silently.
* Outages raise ``dependency_transient`` (``mcp_registry_unavailable``); a stored document that
  fails validation raises ``dependency_transient`` with ``upstream_invalid``. A failure is never
  reported as "not registered".

The transitions themselves live in :mod:`neurosphere_core.mcp.registry`, so the in-memory and
Cosmos stores cannot drift.
"""

from __future__ import annotations

import builtins
import itertools
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Final, Protocol, runtime_checkable

from pydantic import ValidationError

from neurosphere_core.errors import DependencyTransientError, InvalidSchemaError
from neurosphere_core.mcp.errors import (
    INVALID_REGISTRATION,
    MCP_REGISTRY_UNAVAILABLE,
    MCP_SERVER_NOT_REGISTERED,
    SERVER_ALREADY_REGISTERED,
    SERVER_MODIFIED,
    forbidden,
    invalid,
    stale,
    unavailable,
)
from neurosphere_core.mcp.manifest import ValidatedManifest
from neurosphere_core.mcp.models import RegisteredServer, ServerStatus, SyncResult
from neurosphere_core.mcp.registry import apply_approval, apply_revocation, apply_sync

__all__ = [
    "DEFAULT_LIST_LIMIT",
    "MAX_LIST_LIMIT",
    "InMemoryMcpServerStore",
    "McpServerStore",
    "RegistryStoreBase",
    "already_registered",
    "not_registered",
    "record_invalid",
    "registry_unavailable",
    "server_modified",
]

DEFAULT_LIST_LIMIT: Final = 100
MAX_LIST_LIMIT: Final = 500
_MAX_REVOKE_REASON: Final = 200


@runtime_checkable
class McpServerStore(Protocol):
    async def register(self, server: RegisteredServer) -> RegisteredServer:
        """Create-only; returns the stored record with its ETag."""
        ...

    async def get(self, server_id: str) -> RegisteredServer | None: ...

    async def list(self, *, limit: int = DEFAULT_LIST_LIMIT) -> builtins.list[RegisteredServer]:
        """Registered servers ordered by ``registered_at`` then id (at most ``limit``)."""
        ...

    async def update(
        self,
        server_id: str,
        *,
        if_match: str,
        display_name: str | None = None,
        status: ServerStatus | None = None,
    ) -> RegisteredServer:
        """Change the mutable registration fields only (URL, cloud and tools are immutable)."""
        ...

    async def record_sync(
        self,
        server_id: str,
        manifest: ValidatedManifest,
        *,
        now: datetime,
        if_match: str | None = None,
    ) -> tuple[RegisteredServer, SyncResult]: ...

    async def approve(
        self,
        server_id: str,
        tool_name: str,
        *,
        expected_hash: str,
        actor: str,
        now: datetime,
        if_match: str | None = None,
    ) -> RegisteredServer: ...

    async def revoke(
        self,
        server_id: str,
        tool_name: str,
        *,
        actor: str,
        reason: str,
        now: datetime,
        if_match: str | None = None,
    ) -> RegisteredServer: ...


def registry_unavailable() -> DependencyTransientError:
    return unavailable(MCP_REGISTRY_UNAVAILABLE, "MCP server registry is unavailable")


def record_invalid() -> DependencyTransientError:
    return unavailable(
        MCP_REGISTRY_UNAVAILABLE,
        "stored MCP server record failed validation",
        upstream_invalid=True,
    )


def server_modified() -> Exception:
    return stale(SERVER_MODIFIED, "the MCP server record was modified concurrently")


def not_registered() -> Exception:
    return forbidden(MCP_SERVER_NOT_REGISTERED, "the MCP server is not registered")


def already_registered() -> InvalidSchemaError:
    return invalid(SERVER_ALREADY_REGISTERED, "that exact server URL is already registered")


def _check_limit(limit: int) -> int:
    if not 1 <= limit <= MAX_LIST_LIMIT:
        raise invalid(INVALID_REGISTRATION, f"limit must be 1..{MAX_LIST_LIMIT}")
    return limit


class RegistryStoreBase(ABC):
    """Shared port behaviour over four storage primitives."""

    @abstractmethod
    async def _read(self, server_id: str) -> RegisteredServer | None: ...

    @abstractmethod
    async def _insert(self, server: RegisteredServer) -> RegisteredServer: ...

    @abstractmethod
    async def _replace(self, server: RegisteredServer, *, if_match: str) -> RegisteredServer: ...

    @abstractmethod
    async def _scan(self, limit: int) -> builtins.list[RegisteredServer]: ...

    async def register(self, server: RegisteredServer) -> RegisteredServer:
        return await self._insert(server)

    async def get(self, server_id: str) -> RegisteredServer | None:
        return await self._read(server_id)

    async def list(self, *, limit: int = DEFAULT_LIST_LIMIT) -> builtins.list[RegisteredServer]:
        return await self._scan(_check_limit(limit))

    async def _current(self, server_id: str, if_match: str | None) -> RegisteredServer:
        current = await self._read(server_id)
        if current is None:
            raise not_registered()
        if current.etag is None or (if_match is not None and current.etag != if_match):
            raise server_modified()
        return current

    async def _commit(
        self, current: RegisteredServer, updated: RegisteredServer
    ) -> RegisteredServer:
        etag = current.etag
        if etag is None:  # _current guarantees an etag; kept for the type checker
            raise server_modified()
        return await self._replace(updated, if_match=etag)

    async def update(
        self,
        server_id: str,
        *,
        if_match: str,
        display_name: str | None = None,
        status: ServerStatus | None = None,
    ) -> RegisteredServer:
        current = await self._current(server_id, if_match)
        changes: dict[str, Any] = {}
        if display_name is not None:
            changes["display_name"] = display_name.strip()
        if status is not None:
            changes["status"] = status
        try:
            updated = RegisteredServer.model_validate({**current.model_dump(), **changes})
        except ValidationError:
            raise invalid(INVALID_REGISTRATION, "registration update is not valid") from None
        return await self._commit(current, updated)

    async def record_sync(
        self,
        server_id: str,
        manifest: ValidatedManifest,
        *,
        now: datetime,
        if_match: str | None = None,
    ) -> tuple[RegisteredServer, SyncResult]:
        current = await self._current(server_id, if_match)
        updated, result = apply_sync(current, manifest, now=now)
        return await self._commit(current, updated), result

    async def approve(
        self,
        server_id: str,
        tool_name: str,
        *,
        expected_hash: str,
        actor: str,
        now: datetime,
        if_match: str | None = None,
    ) -> RegisteredServer:
        current = await self._current(server_id, if_match)
        updated = apply_approval(
            current, tool_name, expected_hash=expected_hash, actor=actor, now=now
        )
        return await self._commit(current, updated)

    async def revoke(
        self,
        server_id: str,
        tool_name: str,
        *,
        actor: str,
        reason: str,
        now: datetime,
        if_match: str | None = None,
    ) -> RegisteredServer:
        reason = reason.strip()
        if not reason or len(reason) > _MAX_REVOKE_REASON:
            raise invalid(INVALID_REGISTRATION, f"reason must be 1..{_MAX_REVOKE_REASON} chars")
        current = await self._current(server_id, if_match)
        updated = apply_revocation(current, tool_name, actor=actor, reason=reason, now=now)
        return await self._commit(current, updated)


class InMemoryMcpServerStore(RegistryStoreBase):
    """Per-process store for tests and the local sandbox (no durability).

    Documents are kept serialized and re-validated on every read, so the round trip a durable
    store performs is exercised. ``fail_with`` makes every call raise (outage simulation).
    """

    def __init__(self) -> None:
        self._docs: dict[str, tuple[dict[str, Any], str]] = {}
        self._etags = itertools.count(1)
        self.error: Exception | None = None

    def fail_with(self, error: Exception | None) -> None:
        self.error = error

    def _check(self) -> None:
        if self.error is not None:
            raise self.error

    def _load(self, server_id: str) -> RegisteredServer | None:
        found = self._docs.get(server_id)
        if found is None:
            return None
        try:
            return RegisteredServer.from_document(dict(found[0]), etag=found[1])
        except ValidationError:
            raise record_invalid() from None

    def _put(self, server: RegisteredServer) -> RegisteredServer:
        self._docs[server.id] = (server.to_document(), f'"{next(self._etags)}"')
        loaded = self._load(server.id)
        assert loaded is not None
        return loaded

    async def _read(self, server_id: str) -> RegisteredServer | None:
        self._check()
        return self._load(server_id)

    async def _insert(self, server: RegisteredServer) -> RegisteredServer:
        self._check()
        if server.id in self._docs:
            raise already_registered()
        return self._put(server)

    async def _replace(self, server: RegisteredServer, *, if_match: str) -> RegisteredServer:
        self._check()
        found = self._docs.get(server.id)
        if found is None or found[1] != if_match:
            raise server_modified()
        return self._put(server)

    async def _scan(self, limit: int) -> builtins.list[RegisteredServer]:
        self._check()
        rows = [s for key in builtins.list(self._docs) if (s := self._load(key)) is not None]
        rows.sort(key=lambda s: (s.registered_at, s.id))
        return rows[:limit]
