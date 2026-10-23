"""MCP registration-admin service: registry operations, each wrapped in an audit record.

Permission (``config.manage``) is enforced by the router before any method here runs. Every
change writes a ``before`` record, runs, then writes an ``after`` record through the PRP-06
hash-chained store (a failed audit write aborts the change), exactly like the PRP-17 emergency
disable. Records carry the actor pseudonym, the server id, the tool name (lower-cased in the
canonical id), the tool hash (``target_version``) and the time (``recorded_at``); no manifest
text, URL credential or upstream body is ever recorded.

Audit chain: ``<customer>.mcp-admin``. Subjects: ``<cloud>:<customer>:mcp:server:<server id>``
(entity ``mcp_server``) and ``<cloud>:<customer>:mcp:tool:<server id>/<tool>`` (``mcp_tool``).
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Final

from neurosphere_contracts.audit.v1.audit_record import Subject
from neurosphere_core.audit import (
    AuditContext,
    AuditDraft,
    AuditRepository,
    build_after,
    build_before,
    make_subject,
    run_audited_mutation,
)
from neurosphere_core.mcp import (
    RegisteredServer,
    ServerStatus,
    SyncResult,
    normalize_server_url,
    server_id_for,
)
from neurosphere_core.mcp.errors import SERVER_MODIFIED, TOOL_NOT_FOUND, invalid, stale
from neurosphere_core.mcp.service import McpRegistry
from neurosphere_core.scope import IdentityScope
from pydantic import BaseModel

from neurosphere_api.mcp.client import ExternalMcpClient

__all__ = ["CHAIN_SUFFIX", "McpAdminPlane", "McpAdminService", "audit_chain_id"]

CHAIN_SUFFIX: Final = "mcp-admin"
_DETAIL_OK: Final = re.compile(r"^[a-z][a-z0-9_.:=-]{0,127}$")
_CODE_FALLBACK: Final = "error"


def audit_chain_id(customer_id: str) -> str:
    return f"{customer_id}.{CHAIN_SUFFIX}"


@dataclass(frozen=True)
class McpAdminPlane:
    """What the admin routes need; installed on ``app.state`` by ``configure_mcp_admin``."""

    registry: McpRegistry
    client: ExternalMcpClient
    audit: AuditRepository


def _error_code(exc: BaseException) -> str:
    reason = getattr(exc, "reason", None)
    return reason if isinstance(reason, str) and _DETAIL_OK.fullmatch(reason) else _CODE_FALLBACK


class _Target(BaseModel):
    """Audit target of one operation."""

    operation: str
    server_id: str
    tool: str | None = None
    tool_hash: str | None = None


class McpAdminService:
    def __init__(self, plane: McpAdminPlane) -> None:
        self._plane = plane

    # -- audit ----------------------------------------------------------------------------

    def _subject(
        self, scope: IdentityScope, target: _Target, *, extra: str | None = None
    ) -> Subject:
        base = f"{scope.cloud}:{scope.customer_id}:mcp"
        if target.tool is None:
            canonical, entity = f"{base}:server:{target.server_id}", "mcp_server"
        else:
            canonical = f"{base}:tool:{target.server_id}/{target.tool.lower()}"
            entity = "mcp_tool"
        state = {
            "operation": target.operation,
            "server_id": target.server_id,
            "tool": target.tool,
            "tool_hash": target.tool_hash,
            "extra": extra,
        }
        return make_subject(canonical, entity, target_version=target.tool_hash, state=state)

    async def _audited[T](
        self,
        scope: IdentityScope,
        correlation_id: str,
        target: _Target,
        mutate: Callable[[], Awaitable[T]],
        *,
        success_detail: str,
        result_hash: Callable[[T], str | None],
    ) -> T:
        ctx = AuditContext.from_scope(
            scope, correlation_id=correlation_id, operation=target.operation, channel="rest"
        )

        def after(result: T) -> AuditDraft:
            done = target.model_copy(update={"tool_hash": result_hash(result)})
            return build_after(
                ctx,
                self._subject(scope, done, extra="after"),
                result="succeeded",
                verified=True,
                detail=success_detail,
            )

        def failed(exc: BaseException) -> AuditDraft:
            return build_after(
                ctx,
                self._subject(scope, target, extra="failed"),
                result="failed",
                verified=False,
                detail=_error_code(exc),
            )

        return await run_audited_mutation(
            self._plane.audit,
            audit_chain_id(scope.customer_id),
            before=build_before(ctx, self._subject(scope, target, extra="before")),
            mutate=mutate,
            after=after,
            on_error=failed,
        )

    @staticmethod
    def _actor(scope: IdentityScope) -> str:
        return scope.to_contract().principal.principal_id.root

    # -- reads ----------------------------------------------------------------------------

    async def list_servers(
        self, *, after: str | None, limit: int
    ) -> tuple[list[RegisteredServer], str | None]:
        servers = await self._plane.registry.list(limit=500)
        start = 0
        if after is not None:
            ids = [s.id for s in servers]
            if after not in ids:
                raise invalid("invalid_cursor", "the cursor does not name a registered server")
            start = ids.index(after) + 1
        page = servers[start : start + limit]
        more = start + limit < len(servers)
        return page, (page[-1].id if more and page else None)

    async def get(self, server_id: str) -> RegisteredServer:
        return await self._plane.registry.require(server_id)

    async def _match_etag(self, server_id: str, header: str) -> str:
        """Header value mapped to the stored form (quoted or not); a different version passes
        through unchanged so the store refuses it with ``stale_version``."""
        current = await self._plane.registry.require(server_id)
        value = header.strip().removeprefix("W/")
        stored = current.etag
        if stored is None:
            raise stale(SERVER_MODIFIED, "the server record has no version")
        for candidate in (value, f'"{value}"', value.strip('"')):
            if candidate == stored:
                return stored
        return value

    # -- changes --------------------------------------------------------------------------

    async def register(
        self, scope: IdentityScope, correlation_id: str, *, url: str, display_name: str
    ) -> RegisteredServer:
        # An unparseable URL is refused (invalid_schema / forbidden) before anything is recorded.
        server_id = server_id_for(normalize_server_url(url))
        actor = self._actor(scope)
        return await self._audited(
            scope,
            correlation_id,
            _Target(operation="mcp.server.register", server_id=server_id),
            lambda: self._plane.registry.register(url, display_name=display_name, actor=actor),
            success_detail="registered",
            result_hash=lambda _result: None,
        )

    async def update(
        self,
        scope: IdentityScope,
        correlation_id: str,
        server_id: str,
        *,
        if_match: str,
        display_name: str | None,
        status: ServerStatus | None,
    ) -> RegisteredServer:
        etag = await self._match_etag(server_id, if_match)
        return await self._audited(
            scope,
            correlation_id,
            _Target(operation="mcp.server.update", server_id=server_id),
            lambda: self._plane.registry.update(
                server_id, if_match=etag, display_name=display_name, status=status
            ),
            success_detail="updated" if status is None else f"updated_status_{status}",
            result_hash=lambda _result: None,
        )

    async def sync(
        self, scope: IdentityScope, correlation_id: str, server_id: str, *, if_match: str | None
    ) -> tuple[RegisteredServer, SyncResult]:
        etag = None if if_match is None else await self._match_etag(server_id, if_match)

        async def run() -> SyncResult:
            return await self._plane.client.sync_tools(server_id, if_match=etag)

        result = await self._audited(
            scope,
            correlation_id,
            _Target(operation="mcp.server.sync", server_id=server_id),
            run,
            success_detail="synced",
            result_hash=lambda r: r.manifest_hash,
        )
        return await self._plane.registry.require(server_id), result

    async def approve(
        self,
        scope: IdentityScope,
        correlation_id: str,
        server_id: str,
        tool_name: str,
        *,
        expected_hash: str,
        if_match: str,
    ) -> RegisteredServer:
        etag = await self._match_etag(server_id, if_match)
        return await self._audited(
            scope,
            correlation_id,
            _Target(
                operation="mcp.tool.approve",
                server_id=server_id,
                tool=tool_name,
                tool_hash=expected_hash,
            ),
            lambda: self._plane.registry.approve(
                server_id,
                tool_name,
                expected_hash=expected_hash,
                actor=self._actor(scope),
                if_match=etag,
            ),
            success_detail="approved",
            result_hash=lambda _result: expected_hash,
        )

    async def revoke(
        self,
        scope: IdentityScope,
        correlation_id: str,
        server_id: str,
        tool_name: str,
        *,
        reason: str,
        if_match: str,
    ) -> RegisteredServer:
        current = await self._plane.registry.require(server_id)
        record = current.tool(tool_name)
        if record is None:
            raise invalid(TOOL_NOT_FOUND, "the server has not advertised that tool")
        etag = await self._match_etag(server_id, if_match)
        current_hash = record.entry.tool_hash
        return await self._audited(
            scope,
            correlation_id,
            _Target(
                operation="mcp.tool.revoke",
                server_id=server_id,
                tool=tool_name,
                tool_hash=current_hash,
            ),
            lambda: self._plane.registry.revoke(
                server_id,
                tool_name,
                actor=self._actor(scope),
                reason=reason,
                if_match=etag,
            ),
            success_detail="revoked",
            result_hash=lambda _result: current_hash,
        )
