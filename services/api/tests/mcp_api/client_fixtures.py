"""In-process fixtures for the external MCP client tests (no network, no DNS).

The "external server" is a real SDK ``MCPServer`` served over streamable HTTP through
``httpx2.ASGITransport``; the client reaches it through the same ``GuardedTransport`` it uses in
production, so every header that would leave the process is recorded by
:class:`RecordingTransport`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx2
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from neurosphere_api.mcp.client import ExternalMcpClient
from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope
from neurosphere_core.auth.scope import compute_scope_hash
from neurosphere_core.cloud import CloudName
from neurosphere_core.mcp import (
    InMemoryMcpServerStore,
    McpClientPolicy,
    McpRegistry,
    TransportLimits,
    VettedTarget,
)
from neurosphere_core.scope import IdentityScope

NOW = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)
ADMIN = "commercial:contoso:entra:person:p-00000000000000aa"
SERVER_URL = "https://mcp.example.com/mcp"
GOV_SERVER_URL = "https://tools.contoso.azure.us/mcp"
PUBLIC_V4 = "93.184.215.14"
FINANCE = "commercial:contoso:catalog:domain:finance"
GOV_FINANCE = "government:contoso:catalog:domain:finance"


def make_scope(
    *,
    cloud: str = "commercial",
    role: str = "viewer",
    domain: str = FINANCE,
) -> IdentityScope:
    doc: dict[str, Any] = {
        "schema_version": "1.0.0",
        "cloud": cloud,
        "customer_id": "contoso",
        "principal": {
            "principal_id": f"{cloud}:contoso:entra:person:p-0123456789abcdef",
            "principal_pseudonym": "p-0123456789abcdef",
            "principal_kind": "user",
        },
        "roles": [{"role": role, "domain_ids": [domain]}],
        "allowed_domains": [domain],
        "allowed_resources": [],
        "policy_version": "2026.10.01-1",
        "derived_at": "2026-10-10T00:00:00Z",
    }
    if role in ("admin", "security_auditor"):
        doc["roles"][0]["expires_at"] = "2027-01-01T00:00:00Z"
    doc["scope_hash"] = compute_scope_hash(doc)
    contract = ContractScope.model_validate(doc)
    return IdentityScope._from_verified_contract(contract)  # pyright: ignore[reportPrivateUsage]


class StubResolver:
    """DNS stub: each lookup pops the next answer for the host (the last answer repeats)."""

    def __init__(self, answers: dict[str, Sequence[Sequence[str]]] | None = None) -> None:
        self.answers = {k: [list(a) for a in v] for k, v in (answers or {}).items()}
        self.calls: list[str] = []

    async def resolve(self, host: str, port: int) -> Sequence[str]:
        self.calls.append(host)
        queue = self.answers.get(host)
        if not queue:
            raise OSError("no such host")
        return queue.pop(0) if len(queue) > 1 else queue[0]


@dataclass
class Sent:
    method: str
    url: str
    headers: dict[str, str]


@dataclass
class RecordingTransport(httpx2.AsyncBaseTransport):
    """Inner transport: records what passed the guard, then serves the ASGI app."""

    app: Any
    sent: list[Sent] = field(default_factory=list[Sent])

    def __post_init__(self) -> None:
        self._asgi = httpx2.ASGITransport(app=self.app)

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        self.sent.append(Sent(request.method, str(request.url), dict(request.headers)))
        return await self._asgi.handle_async_request(request)


@dataclass
class Harness:
    server: MCPServer
    registry: McpRegistry
    store: InMemoryMcpServerStore
    resolver: StubResolver
    client: ExternalMcpClient
    transports: list[RecordingTransport]
    targets: list[VettedTarget]

    @property
    def sent(self) -> list[Sent]:
        return [s for t in self.transports for s in t.sent]

    async def register(self, url: str = SERVER_URL) -> str:
        server = await self.registry.register(url, display_name="External", actor=ADMIN)
        return server.id

    async def approve_all(self, server_id: str) -> None:
        await self.client.sync_tools(server_id)
        stored = await self.registry.require(server_id)
        for record in stored.tools:
            if record.approval.state == "pending":
                await self.registry.approve(
                    server_id, record.name, expected_hash=record.entry.tool_hash, actor=ADMIN
                )


def external_server() -> MCPServer:
    server = MCPServer("external")

    @server.tool()
    def lookup(record_id: str) -> str:
        """Look up a record by id."""
        return f"record {record_id}"

    @server.tool()
    def stats(region: str) -> dict[str, int]:
        """Return counts for a region."""
        return {"count": len(region)}

    return server


AppFactory = Callable[[MCPServer], Any]


def default_app(server: MCPServer) -> Any:
    return server.streamable_http_app(
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )


@asynccontextmanager
async def harness(
    *,
    server: MCPServer | None = None,
    policy: McpClientPolicy | None = None,
    answers: dict[str, Sequence[Sequence[str]]] | None = None,
    app_factory: AppFactory = default_app,
    **client_kwargs: Any,
) -> AsyncIterator[Harness]:
    server = server or external_server()
    mcp_app = default_app(server)  # also creates the session manager run() below needs
    app = mcp_app if app_factory is default_app else app_factory(server)
    store = InMemoryMcpServerStore()
    registry = McpRegistry(store, policy or McpClientPolicy(cloud=CloudName.COMMERCIAL))
    resolver = StubResolver(
        answers
        if answers is not None
        else {"mcp.example.com": [[PUBLIC_V4]], "tools.contoso.azure.us": [[PUBLIC_V4]]}
    )
    transports: list[RecordingTransport] = []
    targets: list[VettedTarget] = []

    def factory(target: VettedTarget, limits: TransportLimits) -> httpx2.AsyncBaseTransport:
        targets.append(target)
        transport = RecordingTransport(app)
        transports.append(transport)
        return transport

    client_kwargs.setdefault("transport_factory", factory)
    client = ExternalMcpClient(registry, resolver=resolver, **client_kwargs)
    async with server.session_manager.run():
        yield Harness(server, registry, store, resolver, client, transports, targets)
