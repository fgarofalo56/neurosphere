"""Item 2's MCP client against the COMPOSED API over real HTTP (PRP-22 audit close-out, lane R).

The compose-backed twin of ``test_client_server_roundtrip.py`` (which runs in-process, D4). Here
the NeuroSphere MCP server is the production composition served by uvicorn on ``127.0.0.1``
(:mod:`.mcp_live_stack`: compose emulators, Cosmos policy store, seeded sandbox catalog,
``NS_MCP_*`` from the process environment). It is registered in item 2's registry and reached
through item 2's ``ExternalMcpClient`` over a TCP socket.

What is NOT production here, and why: the client's DNS answer. The registered URL is the MCP
resource identifier ``https://mcp.neurosphere.test/mcp``; a stub resolver answers a public test
address so ``vet_target`` vets and pins it (the SSRF check stays in the path), and the transport
factory then connects that vetted request to ``127.0.0.1:<port>`` over plain HTTP with the
original ``Host`` header. A real loopback answer is refused by the SSRF guard, which
``test_mcp_real_stack_live.py`` proves live. Everything on the server side is real.

Run: ``docker compose up -d --wait`` then ``pytest -m integration tests/security/mcp``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx2
import pytest
import pytest_asyncio
from neurosphere_core.errors import ForbiddenError
from neurosphere_core.mcp import UNTRUSTED_EXTERNAL, TransportLimits, VettedTarget

from .mcp_live_stack import (
    MCP_HOST,
    MCP_RESOURCE,
    REST_AUDIENCE,
    LiveStack,
    bearer,
    http_client,
    live_stack,
    mcp_rpc,
    record_domains,
)
from .mcp_security_harness import ADMIN, PUBLIC_V4, PlatformCredential, cf, cs, make_client

pytestmark = pytest.mark.integration


@dataclass
class LoopbackFactory:
    """``TransportFactory``: the vetted target is recorded, then the socket goes to the local
    composed API (scheme http, host 127.0.0.1, the given port; ``Host`` header unchanged)."""

    port: int
    targets: list[VettedTarget] = field(default_factory=list[VettedTarget])
    sent: list[tuple[str, str, str | None]] = field(
        default_factory=list[tuple[str, str, str | None]]
    )

    def factory(self, target: VettedTarget, limits: TransportLimits) -> httpx2.AsyncBaseTransport:
        self.targets.append(target)
        return _Loopback(self)


class _Loopback(httpx2.AsyncBaseTransport):
    def __init__(self, owner: LoopbackFactory) -> None:
        self._owner = owner
        self._inner = httpx2.AsyncHTTPTransport()

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        self._owner.sent.append(
            (request.method, str(request.url), request.headers.get("authorization"))
        )
        request.url = request.url.copy_with(scheme="http", host="127.0.0.1", port=self._owner.port)
        return await self._inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self._inner.aclose()


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def stack() -> AsyncIterator[LiveStack]:
    async with live_stack() as running:
        yield running


async def _live_tool_names(stack: LiveStack, token: str) -> set[str]:
    async with http_client(stack) as http:
        response = await mcp_rpc(http, "tools/list", token=token)
    assert response.status_code == 200, response.status_code
    return {t["name"] for t in response.json()["result"]["tools"]}


async def _admin_catalog_domains(stack: LiveStack) -> set[str]:
    async with http_client(stack) as http:
        response = await mcp_rpc(
            http,
            "tools/call",
            {"name": "search_catalog", "arguments": cs.query_args("agent")},
            token=stack.token("admin"),
        )
    assert response.status_code == 200, response.status_code
    return record_domains(response)


def _domains(structured: dict[str, Any] | None) -> set[str]:
    assert structured is not None
    return {row["data"]["domain_id"] for row in structured["records"]}


@pytest.mark.asyncio(loop_scope="module")
async def test_register_sync_approve_and_call_over_real_http(stack: LiveStack) -> None:
    token = stack.token("viewer")
    loopback = LoopbackFactory(stack.port)
    client, registry, resolver = make_client(
        loopback,  # type: ignore[arg-type]  # same factory protocol as AppRouter
        answers={MCP_HOST: [[PUBLIC_V4]]},
        credentials=PlatformCredential(token),
    )
    scope = cf.make_scope()
    server = await registry.register(MCP_RESOURCE, display_name="NeuroSphere", actor=ADMIN)

    with pytest.raises(ForbiddenError) as before_sync:
        await client.call_tool(scope, server.id, "search_catalog", cs.query_args("agent"))
    assert before_sync.value.reason == "tool_not_approved"
    assert loopback.sent == []

    # tools/list over HTTP is scope-derived: the viewer's manifest is what the sync records.
    sync = await client.sync_tools(server.id)
    expected = await _live_tool_names(stack, token)
    assert set(sync.added) == expected
    assert "search_catalog" in expected and "draft_action" not in expected
    stored = await registry.require(server.id)
    assert {t.approval.state for t in stored.tools} == {"pending"}

    record = stored.tool("search_catalog")
    assert record is not None
    await registry.approve(
        server.id, "search_catalog", expected_hash=record.entry.tool_hash, actor=ADMIN
    )
    result = await client.call_tool(scope, server.id, "search_catalog", cs.query_args("agent"))
    assert result.trust == UNTRUSTED_EXTERNAL and result.is_error is False
    assert result.provenance.server_url == MCP_RESOURCE
    assert result.provenance.tool_hash == record.entry.tool_hash
    viewer_domains = set(stack.principals["viewer"].domains)
    rows = _domains(result.structured_content)
    assert rows, "the seeded catalog returned no rows for the viewer's domain"
    assert rows <= viewer_domains  # scoped by the SERVER from the token it received

    # Other seeded domains hold data too (an admin over every domain sees them), so the
    # viewer's single-domain result is the server's scope filter, not an empty catalog.
    assert len(await _admin_catalog_domains(stack)) > 1

    # SSRF vetting and pinning stayed in the path; only the platform's own token was sent.
    assert resolver.calls and set(resolver.calls) == {MCP_HOST}
    assert loopback.targets and all(t.addresses == (PUBLIC_V4,) for t in loopback.targets)
    assert {url for _, url, _ in loopback.sent} == {MCP_RESOURCE}
    assert {auth for _, _, auth in loopback.sent} == {bearer(token)["Authorization"]}


@pytest.mark.asyncio(loop_scope="module")
async def test_an_unapproved_tool_is_refused_without_a_request(stack: LiveStack) -> None:
    loopback = LoopbackFactory(stack.port)
    client, registry, _ = make_client(
        loopback,  # type: ignore[arg-type]
        answers={MCP_HOST: [[PUBLIC_V4]]},
        credentials=PlatformCredential(stack.token("viewer")),
    )
    scope = cf.make_scope()
    server = await registry.register(MCP_RESOURCE, display_name="NeuroSphere", actor=ADMIN)
    await client.sync_tools(server.id)
    sent_before = len(loopback.sent)
    for tool in ("get_cost_summary", "draft_action", "not_a_tool"):
        with pytest.raises(ForbiddenError) as refused:
            await client.call_tool(scope, server.id, tool, {})
        assert refused.value.reason == "tool_not_approved", tool
    assert len(loopback.sent) == sent_before


@pytest.mark.asyncio(loop_scope="module")
async def test_a_private_answer_for_the_registered_host_sends_nothing(stack: LiveStack) -> None:
    loopback = LoopbackFactory(stack.port)
    client, registry, _ = make_client(
        loopback,  # type: ignore[arg-type]
        answers={MCP_HOST: [["10.20.30.40"]]},
        credentials=PlatformCredential(stack.token("viewer")),
    )
    server = await registry.register(MCP_RESOURCE, display_name="NeuroSphere", actor=ADMIN)
    with pytest.raises(ForbiddenError) as blocked:
        await client.sync_tools(server.id)
    assert blocked.value.reason == "ssrf_blocked_address"
    assert loopback.targets == [] and loopback.sent == []


@pytest.mark.asyncio(loop_scope="module")
async def test_a_wrong_audience_platform_token_is_refused_by_the_live_server(
    stack: LiveStack,
) -> None:
    loopback = LoopbackFactory(stack.port)
    rest_token = stack.token("viewer", audience=REST_AUDIENCE, scopes=())
    client, registry, _ = make_client(
        loopback,  # type: ignore[arg-type]
        answers={MCP_HOST: [[PUBLIC_V4]]},
        credentials=PlatformCredential(rest_token),
    )
    server = await registry.register(MCP_RESOURCE, display_name="NeuroSphere", actor=ADMIN)
    with pytest.raises(ForbiddenError) as rejected:
        await client.sync_tools(server.id)
    assert rejected.value.reason == "mcp_auth_rejected"
