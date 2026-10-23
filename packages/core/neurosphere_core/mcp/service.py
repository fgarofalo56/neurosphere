"""Registry service: the entry point item 3 (admin API) and the API client call.

:class:`McpRegistry` binds a store, the deployment :class:`McpClientPolicy` and a clock. It adds
the registration rules (exact URL, hostname and IP-literal SSRF refusals, Government boundary)
and the "registered or refused" lookup the connector uses; everything else is the store port.
Permission checks (``config.manage`` for administration) and audit records belong to the caller.
"""

from __future__ import annotations

import builtins
from collections.abc import Callable
from datetime import UTC, datetime

from neurosphere_core.mcp.errors import MCP_SERVER_NOT_REGISTERED, forbidden
from neurosphere_core.mcp.manifest import ValidatedManifest
from neurosphere_core.mcp.models import (
    McpClientPolicy,
    RegisteredServer,
    ServerStatus,
    SyncResult,
)
from neurosphere_core.mcp.registry import new_registration
from neurosphere_core.mcp.store import DEFAULT_LIST_LIMIT, McpServerStore
from neurosphere_core.mcp.urls import normalize_server_url, server_id_for

__all__ = ["Clock", "McpRegistry", "utc_now"]

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(UTC)


class McpRegistry:
    def __init__(
        self, store: McpServerStore, policy: McpClientPolicy, *, clock: Clock = utc_now
    ) -> None:
        self._store = store
        self._policy = policy
        self._clock = clock

    @property
    def policy(self) -> McpClientPolicy:
        return self._policy

    def now(self) -> datetime:
        return self._clock()

    async def register(self, url: str, *, display_name: str, actor: str) -> RegisteredServer:
        server = new_registration(
            url, display_name=display_name, actor=actor, policy=self._policy, now=self._clock()
        )
        return await self._store.register(server)

    async def get(self, server_id: str) -> RegisteredServer | None:
        return await self._store.get(server_id)

    async def require(self, server_id: str) -> RegisteredServer:
        """The registered server, or ``forbidden`` ``mcp_server_not_registered``."""
        server = await self._store.get(server_id)
        if server is None:
            raise forbidden(MCP_SERVER_NOT_REGISTERED, "the MCP server is not registered")
        return server

    async def resolve_url(self, url: str) -> RegisteredServer:
        """Map a URL to its registration. Unregistered (or malformed) URLs are refused.

        There is no discovery: the URL must normalise to exactly a registered URL.
        """
        normalised = normalize_server_url(url)
        server = await self._store.get(server_id_for(normalised))
        if server is None or server.url != normalised.url:
            raise forbidden(MCP_SERVER_NOT_REGISTERED, "the MCP server is not registered")
        return server

    async def list(self, *, limit: int = DEFAULT_LIST_LIMIT) -> builtins.list[RegisteredServer]:
        return await self._store.list(limit=limit)

    async def update(
        self,
        server_id: str,
        *,
        if_match: str,
        display_name: str | None = None,
        status: ServerStatus | None = None,
    ) -> RegisteredServer:
        return await self._store.update(
            server_id, if_match=if_match, display_name=display_name, status=status
        )

    async def record_sync(
        self, server_id: str, manifest: ValidatedManifest, *, if_match: str | None = None
    ) -> tuple[RegisteredServer, SyncResult]:
        return await self._store.record_sync(
            server_id, manifest, now=self._clock(), if_match=if_match
        )

    async def approve(
        self,
        server_id: str,
        tool_name: str,
        *,
        expected_hash: str,
        actor: str,
        if_match: str | None = None,
    ) -> RegisteredServer:
        return await self._store.approve(
            server_id,
            tool_name,
            expected_hash=expected_hash,
            actor=actor,
            now=self._clock(),
            if_match=if_match,
        )

    async def revoke(
        self,
        server_id: str,
        tool_name: str,
        *,
        actor: str,
        reason: str,
        if_match: str | None = None,
    ) -> RegisteredServer:
        return await self._store.revoke(
            server_id, tool_name, actor=actor, reason=reason, now=self._clock(), if_match=if_match
        )
