"""Harness for the MCP registration-admin API tests (PRP-22 item 3). Offline: no network.

Composes three existing harnesses without a ``conftest.py``:

* the PRP-06 authz stack (dev-issuer tokens, scope derivation over an in-memory policy store,
  the real ``create_app`` with every default router, so the admin routes under test are the ones
  ``routers.py`` registers);
* item 2's in-process "external server" (a real SDK ``MCPServer`` behind an ASGI transport, DNS
  stubbed) wired into a real ``McpRegistry`` / ``ExternalMcpClient``;
* an in-memory hash-chained audit repository.

People (customer ``contoso``): ADMIN holds ``config.manage``; STEWARD and VIEWER do not.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import client_fixtures  # pyright: ignore[reportMissingImports]
import conftest_server  # noqa: F401  # pyright: ignore[reportMissingImports, reportUnusedImport]
import httpx
from authz import authz_helpers as helpers  # pyright: ignore[reportMissingImports]
from neurosphere_api.mcp.admin import McpAdminPlane, configure_mcp_admin
from neurosphere_contracts.audit.v1.audit_record import AuditRecord
from neurosphere_core.audit import AuditRepository, InMemoryAuditStore
from neurosphere_core.auth.scope import Role

ADMIN = "9f4a5b6c-7d8e-4f90-a1b2-c3d4e5f6a7b8"
STEWARD = helpers.ALICE
VIEWER = helpers.CAROL
FINANCE = helpers.FINANCE
PREFIX = "/api/v1/mcp/admin"
SERVER_URL: str = client_fixtures.SERVER_URL
PUBLIC_V4: str = client_fixtures.PUBLIC_V4
SERVER_URL_2 = "https://other.example.com/mcp"
AUDIT_CHAIN = "contoso.mcp-admin"


def people() -> tuple[Any, ...]:
    return (
        helpers.policy(ADMIN, helpers.role(Role.ADMIN, FINANCE)),
        helpers.policy(STEWARD, helpers.role(Role.DOMAIN_STEWARD, FINANCE)),
        helpers.policy(VIEWER, helpers.role(Role.VIEWER, FINANCE)),
    )


@dataclass
class AdminEnv:
    auth: Any
    external: client_fixtures.Harness
    audit: AuditRepository
    http: httpx.AsyncClient

    def headers(self, who: str = ADMIN, **extra: str) -> dict[str, str]:
        return {**self.auth.auth(who), **extra}

    async def register(self, url: str = SERVER_URL, name: str = "External") -> dict[str, Any]:
        response = await self.http.post(
            f"{PREFIX}/servers",
            json={"url": url, "display_name": name},
            headers=self.headers(),
        )
        assert response.status_code == 201, response.text
        return response.json()

    async def server(self, server_id: str) -> httpx.Response:
        return await self.http.get(f"{PREFIX}/servers/{server_id}", headers=self.headers())

    async def sync(self, server_id: str) -> httpx.Response:
        return await self.http.post(f"{PREFIX}/servers/{server_id}/sync", headers=self.headers())

    async def tools(self, server_id: str) -> dict[str, Any]:
        response = await self.http.get(
            f"{PREFIX}/servers/{server_id}/tools", headers=self.headers()
        )
        assert response.status_code == 200, response.text
        return response.json()

    async def approve(
        self, server_id: str, tool: str, expected_hash: str, *, if_match: str | None = None
    ) -> httpx.Response:
        etag: str = (await self.tools(server_id))["etag"] if if_match is None else if_match
        return await self.http.post(
            f"{PREFIX}/servers/{server_id}/tools/{tool}/approval",
            json={"expected_hash": expected_hash},
            headers=self.headers(**{"If-Match": etag}),
        )

    async def revoke(
        self, server_id: str, tool: str, *, reason: str | None = None
    ) -> httpx.Response:
        etag = (await self.tools(server_id))["etag"]
        return await self.http.delete(
            f"{PREFIX}/servers/{server_id}/tools/{tool}/approval",
            params={} if reason is None else {"reason": reason},
            headers=self.headers(**{"If-Match": etag}),
        )

    async def audit_records(self) -> Sequence[AuditRecord]:
        return await self.audit.read_range(AUDIT_CHAIN, limit=200)


@asynccontextmanager
async def admin_env(
    *, answers: dict[str, Sequence[Sequence[str]]] | None = None, configure: bool = True
) -> AsyncIterator[AdminEnv]:
    resolved = (
        answers
        if answers is not None
        else {"mcp.example.com": [[PUBLIC_V4]], "other.example.com": [[PUBLIC_V4]]}
    )
    auth = helpers.harness(*people(), routers={})
    audit = AuditRepository(InMemoryAuditStore())
    async with client_fixtures.harness(answers=resolved) as external:
        if configure:
            configure_mcp_admin(
                auth.app,
                McpAdminPlane(registry=external.registry, client=external.client, audit=audit),
            )
        transport = httpx.ASGITransport(app=auth.app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
            yield AdminEnv(auth=auth, external=external, audit=audit, http=http)
