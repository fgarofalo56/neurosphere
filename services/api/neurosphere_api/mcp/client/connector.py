"""MCP client for administrator-approved external servers (PRP-22 item 2).

:class:`ExternalMcpClient` is the only way the platform talks to an external MCP server:

1. The server must be registered (exact URL, no discovery) and active; its cloud must be the
   deployment cloud and, in Government, its host inside the approved boundary. Otherwise
   ``forbidden``.
2. Every connection re-runs the SSRF policy (:func:`neurosphere_core.mcp.vet_target`) and pins
   the socket to the vetted addresses (:class:`PinnedTransport`); the URL is never re-resolved.
3. The SDK's ``httpx2`` client is built here with ``trust_env=False`` (no proxy or netrc
   credentials from the environment), no redirects, bounded timeouts and the
   :class:`GuardedTransport` (exact URL only, response-size cap, no inbound credentials).
4. Tool manifests are validated, bounded and hashed in core; a tool is callable only when it is
   approved and its LIVE hash in this session equals the approved hash. Drift is recorded
   (approval revoked) and the call refused.
5. Results come back as :class:`~neurosphere_core.mcp.ExternalToolResult`: bounded, untrusted
   data with provenance. This module does not import the action plane, so no code path turns a
   result into an action draft or confirmation.

No token passthrough: no method accepts a request, header or token. Outbound credentials, if
any, come from the injected :class:`~neurosphere_core.mcp.OutboundCredentialProvider`. The SDK
receives no sampling, elicitation or roots callbacks, so an external server cannot borrow the
platform's model or ask a user for input.
"""

from __future__ import annotations

import builtins
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Literal

import anyio
import httpx2
from mcp.client import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import MCPError
from mcp_types import Implementation
from neurosphere_core.auth.scope.permissions import Permission, domains_with_permission
from neurosphere_core.errors import ForbiddenError, NeuroSphereError, StaleVersionError
from neurosphere_core.mcp import (
    ExternalToolProvenance,
    ExternalToolResult,
    ManifestLimits,
    McpRegistry,
    NoOutboundCredentials,
    OutboundCredentialProvider,
    RegisteredServer,
    Resolver,
    ResultLimits,
    SyncResult,
    SystemResolver,
    ToolManifestEntry,
    ToolRecord,
    TransportLimits,
    ValidatedManifest,
    VettedTarget,
    build_external_result,
    check_boundary,
    check_callable,
    normalize_server_url,
    validate_manifest,
    vet_target,
)
from neurosphere_core.mcp.errors import (
    CLOUD_BOUNDARY_MISMATCH,
    INVALID_MANIFEST,
    INVALID_TOOL_ARGUMENTS,
    INVALID_TOOL_RESULT,
    MANIFEST_TOO_LARGE,
    MCP_SERVER_DISABLED,
    MCP_SERVER_UNAVAILABLE,
    MISSING_DATA_READ,
    TOOL_HASH_MISMATCH,
    forbidden,
    invalid,
    unavailable,
)
from neurosphere_core.mcp.manifest import json_size, measure_json
from neurosphere_core.scope import IdentityScope
from pydantic import ValidationError

from neurosphere_api.mcp.client.transport import GuardedTransport, pinned_transport

__all__ = [
    "MAX_ARGUMENT_BYTES",
    "MCP_EGRESS_REFUSED",
    "MCP_RESPONSE_TOO_LARGE",
    "ExternalMcpClient",
    "TransportFactory",
]

MCP_EGRESS_REFUSED: Final = "mcp_egress_refused"
MCP_RESPONSE_TOO_LARGE: Final = "mcp_response_too_large"
MCP_SERVER_ERROR: Final = "mcp_server_error"
MAX_ARGUMENT_BYTES: Final = 65536
_MAX_ARGUMENT_DEPTH: Final = 16
_RESERVED_HEADERS: Final = frozenset(
    {"host", "content-length", "transfer-encoding", "connection", "cookie", "proxy-authorization"}
)

#: Builds the INNER transport for a vetted target. Production uses :func:`pinned_transport`;
#: tests inject an in-process ASGI transport. The guard always wraps whatever is returned.
TransportFactory = Callable[[VettedTarget, TransportLimits], httpx2.AsyncBaseTransport]

Phase = Literal["manifest", "call"]


@dataclass(frozen=True, slots=True)
class _Session:
    client: Client
    guard: GuardedTransport


def _find_ns_error(exc: BaseException) -> NeuroSphereError | None:
    if isinstance(exc, NeuroSphereError):
        return exc
    if isinstance(exc, BaseExceptionGroup):
        for inner in exc.exceptions:  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]
            found = _find_ns_error(inner)  # pyright: ignore[reportUnknownArgumentType]
            if found is not None:
                return found
    cause = exc.__cause__ or exc.__context__
    if cause is not None and cause is not exc and isinstance(cause, NeuroSphereError):
        return cause
    return None


def _validated_headers(headers: Mapping[str, str]) -> dict[str, str]:
    checked: dict[str, str] = {}
    for name, value in headers.items():
        lowered = name.strip().lower()
        if not lowered or lowered in _RESERVED_HEADERS or any(c in value for c in "\r\n\0"):
            raise forbidden(MCP_EGRESS_REFUSED, "outbound credential headers are not allowed")
        checked[lowered] = value
    return checked


class ExternalMcpClient:
    """Connector for registered external MCP servers (see module docstring)."""

    def __init__(
        self,
        registry: McpRegistry,
        *,
        resolver: Resolver | None = None,
        credentials: OutboundCredentialProvider | None = None,
        manifest_limits: ManifestLimits | None = None,
        result_limits: ResultLimits | None = None,
        transport_limits: TransportLimits | None = None,
        transport_factory: TransportFactory | None = None,
        client_name: str = "neurosphere",
        client_version: str = "0.0.0",
    ) -> None:
        self._registry = registry
        self._resolver: Resolver = resolver or SystemResolver()
        self._credentials: OutboundCredentialProvider = credentials or NoOutboundCredentials()
        self._manifest_limits = manifest_limits or ManifestLimits()
        self._result_limits = result_limits or ResultLimits()
        self._limits = transport_limits or TransportLimits()
        self._factory: TransportFactory = transport_factory or pinned_transport
        self._client_info = Implementation(name=client_name, version=client_version)

    # -- policy -------------------------------------------------------------------------------

    def _check_server(self, server: RegisteredServer) -> None:
        policy = self._registry.policy
        if server.status != "active":
            raise forbidden(MCP_SERVER_DISABLED, "the server is disabled")
        if server.cloud is not policy.cloud:
            raise forbidden(CLOUD_BOUNDARY_MISMATCH, "the server is registered for another cloud")
        check_boundary(normalize_server_url(server.url), policy)

    def _check_scope(self, scope: IdentityScope, now: datetime) -> None:
        if not isinstance(scope, IdentityScope):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise TypeError("calling an external tool requires a server-derived IdentityScope")
        if scope.cloud != self._registry.policy.cloud.value:
            raise forbidden(CLOUD_BOUNDARY_MISMATCH, "the caller's scope is in another cloud")
        if not domains_with_permission(scope, Permission.DATA_READ, now=now):
            raise forbidden(MISSING_DATA_READ, "calling an external tool requires data.read")

    # -- session ------------------------------------------------------------------------------

    @asynccontextmanager
    async def _session(self, server: RegisteredServer) -> AsyncIterator[_Session]:
        self._check_server(server)
        url = normalize_server_url(server.url)
        target = await vet_target(
            url, self._resolver, dns_timeout_seconds=self._limits.dns_timeout_seconds
        )
        headers = _validated_headers(await self._credentials.headers_for(server))
        guard = GuardedTransport(
            self._factory(target, self._limits),
            server_url=url,
            credential_headers=headers,
            max_response_bytes=self._limits.max_response_bytes,
        )
        timeout = httpx2.Timeout(
            connect=self._limits.connect_timeout_seconds,
            read=self._limits.read_timeout_seconds,
            write=self._limits.write_timeout_seconds,
            pool=self._limits.connect_timeout_seconds,
        )
        async with httpx2.AsyncClient(
            transport=guard,
            timeout=timeout,
            trust_env=False,
            follow_redirects=False,
            max_redirects=0,
        ) as http:
            transport = streamable_http_client(
                url.url,
                http_client=http,
                terminate_on_close=True,
                max_sse_event_size=self._limits.max_response_bytes,
            )
            async with Client(
                transport,
                cache=None,
                client_info=self._client_info,
                read_timeout_seconds=self._limits.read_timeout_seconds,
                input_required_max_rounds=0,
            ) as client:
                yield _Session(client=client, guard=guard)

    def _translate(
        self, exc: BaseException, guard: GuardedTransport | None, phase: Phase
    ) -> Exception:
        found = _find_ns_error(exc)
        if found is not None:
            return found
        if guard is not None and guard.violations:
            kind = guard.violations[0].kind
            if kind == "egress_refused":
                return forbidden(MCP_EGRESS_REFUSED, "the server attempted a request off its URL")
            return invalid(MCP_RESPONSE_TOO_LARGE, "the server response exceeded the size bound")
        if isinstance(exc, ValidationError):
            reason = INVALID_MANIFEST if phase == "manifest" else INVALID_TOOL_RESULT
            return invalid(reason, "the server returned a malformed MCP message")
        if isinstance(exc, MCPError):
            return unavailable(
                MCP_SERVER_ERROR, "the MCP server returned an error", upstream_invalid=True
            )
        if isinstance(exc, TimeoutError):
            return unavailable(MCP_SERVER_UNAVAILABLE, "the MCP server timed out")
        return unavailable(MCP_SERVER_UNAVAILABLE, "the MCP server is unavailable")

    async def _list_raw_tools(self, client: Client) -> builtins.list[dict[str, Any]]:
        raw: builtins.list[dict[str, Any]] = []
        cursor: str | None = None
        for _ in range(self._manifest_limits.max_list_pages):
            page = await client.list_tools(cursor=cursor)
            raw.extend(
                tool.model_dump(mode="json", by_alias=True, exclude_none=True)
                for tool in page.tools
            )
            if len(raw) > self._manifest_limits.max_tools:
                raise invalid(MANIFEST_TOO_LARGE, "tool manifest exceeds a size limit")
            cursor = page.next_cursor
            if cursor is None:
                return raw
        raise invalid(MANIFEST_TOO_LARGE, "tool manifest has too many pages")

    async def _manifest(self, session: _Session) -> ValidatedManifest:
        return validate_manifest(await self._list_raw_tools(session.client), self._manifest_limits)

    # -- public API ---------------------------------------------------------------------------

    async def fetch_manifest(self, server_id: str) -> ValidatedManifest:
        """Connect and return the server's validated live manifest (nothing is stored)."""
        server = await self._registry.require(server_id)
        guard: GuardedTransport | None = None
        try:
            with anyio.fail_after(self._limits.operation_timeout_seconds):
                async with self._session(server) as session:
                    guard = session.guard
                    return await self._manifest(session)
        except Exception as exc:
            raise self._translate(exc, guard, "manifest") from None

    async def sync_tools(self, server_id: str, *, if_match: str | None = None) -> SyncResult:
        """Fetch the live manifest and apply it (new tools pending, changed hashes revoked).

        The caller (item 3 admin API) authorizes ``config.manage`` and audits the result.
        """
        manifest = await self.fetch_manifest(server_id)
        _, result = await self._registry.record_sync(server_id, manifest, if_match=if_match)
        return result

    async def call_tool(
        self,
        scope: IdentityScope,
        server_id: str,
        tool_name: str,
        arguments: Mapping[str, Any] | None = None,
    ) -> ExternalToolResult:
        """Call an approved tool; the result is untrusted data with provenance.

        Requires a server-derived ``IdentityScope`` with ``data.read`` in at least one domain,
        in the deployment cloud. Refused (``forbidden``) unless the server is registered and
        active and the tool is approved with a live hash equal to the approved hash.
        """
        now = self._registry.now()
        self._check_scope(scope, now)
        payload = self._arguments(arguments)
        server = await self._registry.require(server_id)
        stored = server.tool(tool_name)
        check_callable(
            server,
            tool_name,
            live_hash=stored.entry.tool_hash if stored else None,
            policy=self._registry.policy,
        )
        guard: GuardedTransport | None = None
        phase: Phase = "manifest"
        try:
            with anyio.fail_after(self._limits.operation_timeout_seconds):
                async with self._session(server) as session:
                    guard = session.guard
                    manifest = await self._manifest(session)
                    live = manifest.by_name().get(tool_name)
                    record = await self._check_live(server, tool_name, live, manifest)
                    phase = "call"
                    result = await session.client.call_tool(tool_name, payload)
                    dumped = result.model_dump(mode="json", by_alias=True)
        except Exception as exc:
            raise self._translate(exc, guard, phase) from None
        provenance = ExternalToolProvenance(
            server_id=server.id,
            server_url=server.url,
            cloud=server.cloud,
            tool_name=tool_name,
            tool_hash=record.entry.tool_hash,
            retrieved_at=self._registry.now(),
        )
        return build_external_result(
            provenance=provenance,
            raw_content=dumped.get("content") or [],
            structured_content=dumped.get("structuredContent"),
            is_error=bool(dumped.get("isError", False)),
            limits=self._result_limits,
        )

    async def _check_live(
        self,
        server: RegisteredServer,
        tool_name: str,
        live: ToolManifestEntry | None,
        manifest: ValidatedManifest,
    ) -> ToolRecord:
        live_hash = live.tool_hash if live is not None else None
        try:
            return check_callable(
                server, tool_name, live_hash=live_hash, policy=self._registry.policy
            )
        except ForbiddenError as exc:
            if exc.reason == TOOL_HASH_MISMATCH:
                await self._record_drift(server, manifest)
            raise

    async def _record_drift(self, server: RegisteredServer, manifest: ValidatedManifest) -> None:
        """Persist the drift so the approval is revoked for everyone, not just this call."""
        try:
            await self._registry.record_sync(server.id, manifest, if_match=server.etag)
        except StaleVersionError:
            return  # a concurrent writer already moved the record on; the call is refused anyway

    @staticmethod
    def _arguments(arguments: Mapping[str, Any] | None) -> dict[str, Any]:
        if arguments is None:
            return {}
        if not isinstance(arguments, Mapping):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise invalid(INVALID_TOOL_ARGUMENTS, "tool arguments must be a JSON object")
        try:
            measure_json(arguments, max_depth=_MAX_ARGUMENT_DEPTH, max_nodes=MAX_ARGUMENT_BYTES)
            size = json_size(arguments)
        except (OverflowError, ValueError, TypeError, UnicodeEncodeError):
            raise invalid(INVALID_TOOL_ARGUMENTS, "tool arguments are not bounded JSON") from None
        if size > MAX_ARGUMENT_BYTES:
            raise invalid(
                INVALID_TOOL_ARGUMENTS, f"tool arguments exceed {MAX_ARGUMENT_BYTES} bytes"
            )
        return dict(arguments)
