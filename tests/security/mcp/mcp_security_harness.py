"""Shared offline setup for the PRP-22 item 4 security suite (``tests/security/mcp``).

Reuses, without editing, the item 1 server harness (``services/api/tests/mcp_api/
conftest_server.py``: the real REST stack, the real action plane and the real MCP server mounted
at ``/mcp`` with its own MCP-audience validator) and the item 2 client fixtures
(``client_fixtures.py``: stub DNS, a public test IP, an SDK ``MCPServer`` "external" server).

What this module adds is the wiring between them:

* :class:`AppRouter` is a ``TransportFactory`` for item 2's :class:`ExternalMcpClient`. It is
  called with the ``VettedTarget`` that ``vet_target`` produced from the stub resolver (so the
  SSRF check and IP pinning stay in the path), and returns an ``httpx2`` transport that serves
  a SWITCHABLE in-process ASGI app and records every request that passed item 2's guard.
* :class:`PlatformCredential` is the outbound credential port: the platform's OWN token for
  one registered server (never a caller's inbound token).
* :func:`make_client` builds the registry + client around those.

Tokens are minted at runtime by the in-memory dev issuer; no token literal exists here.
"""

from __future__ import annotations

import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

_REPO = Path(__file__).resolve().parents[3]
_MCP_API = _REPO / "services" / "api" / "tests" / "mcp_api"
if str(_MCP_API) not in sys.path:
    sys.path.insert(0, str(_MCP_API))

import client_fixtures as cf  # noqa: E402  # pyright: ignore[reportMissingImports]
import conftest_server as cs  # noqa: E402  # pyright: ignore[reportMissingImports]
import httpx2  # noqa: E402
from neurosphere_api.mcp.client import ExternalMcpClient  # noqa: E402
from neurosphere_core.cloud import CloudName  # noqa: E402
from neurosphere_core.mcp import (  # noqa: E402
    InMemoryMcpServerStore,
    McpClientPolicy,
    McpRegistry,
    OutboundCredentialProvider,
    RegisteredServer,
    TransportLimits,
    VettedTarget,
)
from neurosphere_core.scope import IdentityScope  # noqa: E402

__all__ = [
    "ADMIN",
    "PUBLIC_V4",
    "AppRouter",
    "PlatformCredential",
    "Sent",
    "StubResolver",
    "authorization_value",
    "cf",
    "cs",
    "derive_scope",
    "make_client",
]

ADMIN: Final[str] = cf.ADMIN
PUBLIC_V4: Final[str] = cf.PUBLIC_V4
StubResolver = cf.StubResolver


def authorization_value(token: str) -> str:
    """``Bearer <token>`` (split literal: no credential-shaped string in the source)."""
    return "Bear" + "er " + token


@dataclass(frozen=True)
class Sent:
    method: str
    url: str
    headers: dict[str, str]


@dataclass
class AppRouter:
    """``TransportFactory`` that serves whichever ASGI app is current, recording each request."""

    app: Any
    sent: list[Sent] = field(default_factory=list[Sent])
    targets: list[VettedTarget] = field(default_factory=list[VettedTarget])

    def factory(self, target: VettedTarget, limits: TransportLimits) -> httpx2.AsyncBaseTransport:
        self.targets.append(target)
        return _RoutedTransport(self)


class _RoutedTransport(httpx2.AsyncBaseTransport):
    def __init__(self, router: AppRouter) -> None:
        self._router = router

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        self._router.sent.append(
            Sent(
                request.method, str(request.url), {k.lower(): v for k, v in request.headers.items()}
            )
        )
        return await httpx2.ASGITransport(app=self._router.app).handle_async_request(request)


class PlatformCredential:
    """The platform's own credential for ONE registered server (``OutboundCredentialProvider``)."""

    def __init__(self, token: str | None) -> None:
        self.token = token
        self.seen: list[str] = []

    async def headers_for(self, server: RegisteredServer) -> Mapping[str, str]:
        self.seen.append(server.id)
        if self.token is None:
            return {}
        return {"authorization": authorization_value(self.token)}


def make_client(
    router: AppRouter,
    *,
    answers: dict[str, Sequence[Sequence[str]]] | None = None,
    credentials: OutboundCredentialProvider | None = None,
    cloud: CloudName = CloudName.COMMERCIAL,
) -> tuple[ExternalMcpClient, McpRegistry, Any]:
    """Item 2's client and registry over an in-memory store, with stub DNS and ``router``."""
    registry = McpRegistry(InMemoryMcpServerStore(), McpClientPolicy(cloud=cloud))
    resolver = StubResolver(answers if answers is not None else {cs.MCP_HOST: [[PUBLIC_V4]]})
    client = ExternalMcpClient(
        registry,
        resolver=resolver,
        credentials=credentials,
        transport_factory=router.factory,
    )
    return client, registry, resolver


async def derive_scope(harness: Any, who: str) -> IdentityScope:
    """The caller's server-derived scope (REST validator + REST ScopeSource), as REST derives it."""
    claims = await harness.api.h.validator.validate(harness.rest_token(who))
    return await harness.api.h.deriver.from_verified_claims(claims)
