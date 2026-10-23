"""Shared harness for the MCP server tests (PRP-22 item 1). Offline: no network, no emulator.

Not a ``conftest.py`` (item 2 tests share this folder): test modules import it by name. It makes
the PRP-06 authz harness (``services/api/tests/authz``), the PRP-17 action-plane harness and the
PRP-19 copilot port fakes importable, then builds:

* the REAL REST stack from ``action_plane_harness.make_api`` (dev-issuer tokens for the REST
  audience, scope derivation over an in-memory policy store, the real action plane), with the
  PRP-19 recording ports bound under their ``app.state`` keys;
* the MCP server from ``create_mcp_server`` with its OWN validator (MCP audience only), mounted
  at ``/mcp`` on the same app, driven in-process through ``httpx.ASGITransport`` with
  2026-07-28 single-exchange JSON-RPC requests.

Tokens are minted at runtime by the in-memory dev issuer; no token literal exists in the tests.
MCP tokens get a long lifetime because the SDK also compares ``exp`` with the wall clock while the
validator uses the harness's fixed clock.
"""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

_HERE = Path(__file__).resolve().parent
_API_TESTS = _HERE.parent
for _path in (_API_TESTS / "copilot_api", _API_TESTS / "actions_api", _API_TESTS, _HERE):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import authz.authz_helpers as helpers  # noqa: E402  # pyright: ignore[reportMissingImports]
import httpx  # noqa: E402
from action_plane_harness import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    ALICE,
    BOB,
    CAROL,
    CUSTOMER,
    ERIN,
    FINANCE,
    KIND,
    OPERATIONS,
    TARGET_VERSION,
    Api,
    make_api,
)
from copilot_api_harness import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    World,
    agent,
    make_world,
    recommendation,
)
from mcp_types import (  # noqa: E402
    CLIENT_CAPABILITIES_META_KEY,
    CLIENT_INFO_META_KEY,
    PROTOCOL_VERSION_META_KEY,
)
from neurosphere_api.authz import configure_authz  # noqa: E402
from neurosphere_api.mcp.server import (  # noqa: E402
    McpServerMount,
    McpServerSettings,
    create_mcp_server,
)
from neurosphere_core.auth.jwt import (  # noqa: E402
    JwksCache,
    JwtConfig,
    JwtValidator,
    entra_jwks_uri,
)
from neurosphere_core.auth.scope import RevocationChecker  # noqa: E402
from neurosphere_core.cloud import CloudName  # noqa: E402

__all__ = [
    "ALICE",
    "BOB",
    "CAROL",
    "CUSTOMER",
    "ERIN",
    "FINANCE",
    "KIND",
    "MCP_AUDIENCE",
    "MCP_RESOURCE",
    "OPERATIONS",
    "OPS_TARGET",
    "PROTOCOL",
    "REST_AUDIENCE",
    "TARGET",
    "TARGET_VERSION",
    "McpHarness",
    "helpers",
    "make_harness",
    "make_mcp_validator",
    "mcp_session",
]

PROTOCOL: Final = "2026-07-28"
MCP_HOST: Final = "mcp.neurosphere.test"
MCP_RESOURCE: Final = f"https://{MCP_HOST}/mcp"
MCP_AUDIENCE: Final = "api://neurosphere-test-mcp"
REST_AUDIENCE: str = helpers.AUDIENCE
REQUIRED_SCOPE: Final = "mcp.invoke"
LONG_LIFETIME: Final = 20 * 365 * 86_400

TARGET: Final = "commercial:contoso:foundry:agent:chat-prod"
OPS_TARGET: Final = "commercial:contoso:foundry:agent:ops-prod"


def make_mcp_validator(clock: Any, audiences: Sequence[str] = (MCP_AUDIENCE,)) -> JwtValidator:
    """Same dev issuer and tenant as REST, but the MCP audience(s) only."""
    config = JwtConfig(
        env="local",
        cloud=CloudName.COMMERCIAL,
        tenant_id=helpers.TENANT,
        audiences=tuple(audiences),
        dev_issuer=helpers.dev_issuer().trust(),
    )
    fetcher = helpers.StandInJwksFetcher(entra_jwks_uri(CloudName.COMMERCIAL, helpers.TENANT))
    jwks = JwksCache(fetcher, clock=clock, ttl_seconds=3600, min_refresh_interval_seconds=300)
    return JwtValidator(config, jwks, clock=clock)


def mcp_settings(**overrides: Any) -> McpServerSettings:
    values: dict[str, Any] = {"resource_server_url": MCP_RESOURCE, "audiences": (MCP_AUDIENCE,)}
    values.update(overrides)
    return McpServerSettings(**values)


@dataclass
class McpHarness:
    api: Api
    world: World
    mount: McpServerMount
    validator: JwtValidator

    @property
    def app(self) -> Any:
        return self.api.h.app

    @property
    def clock(self) -> Any:
        return self.api.h.clock

    def token(
        self,
        who: str,
        *,
        audience: str = MCP_AUDIENCE,
        scopes: Sequence[str] = (REQUIRED_SCOPE,),
        lifetime: int = LONG_LIFETIME,
        **extra: Any,
    ) -> str:
        return helpers.dev_issuer().mint(
            audience=audience,
            object_id=who,
            now=self.clock.now,
            lifetime_seconds=lifetime,
            scopes=scopes,
            extra=extra or None,
        )

    def rest_token(self, who: str) -> str:
        return self.api.h.token(who)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app), base_url=f"https://{MCP_HOST}"
        )


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": "Bear" + "er " + token}


def envelope(method: str, params: dict[str, Any] | None = None, rid: int = 1) -> dict[str, Any]:
    body: dict[str, Any] = dict(params or {})
    body["_meta"] = {
        PROTOCOL_VERSION_META_KEY: PROTOCOL,
        CLIENT_CAPABILITIES_META_KEY: {},
        CLIENT_INFO_META_KEY: {"name": "ns-mcp-tests", "version": "0.0.1"},
    }
    return {"jsonrpc": "2.0", "id": rid, "method": method, "params": body}


def rpc_headers(method: str, name: str | None = None) -> dict[str, str]:
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "MCP-Protocol-Version": PROTOCOL,
        "Mcp-Method": method,
    }
    if name is not None:
        headers["Mcp-Name"] = name
    return headers


async def rpc(
    client: httpx.AsyncClient,
    method: str,
    params: dict[str, Any] | None = None,
    *,
    token: str | None,
    name: str | None = None,
    extra_headers: dict[str, str] | None = None,
) -> httpx.Response:
    if name is None and params is not None:
        key = {"tools/call": "name", "resources/read": "uri"}.get(method)
        value = params.get(key) if key else None
        name = value if isinstance(value, str) else None
    headers = rpc_headers(method, name)
    if token is not None:
        headers.update(bearer(token))
    headers.update(extra_headers or {})
    return await client.post("/mcp", json=envelope(method, params), headers=headers)


async def call_tool(
    client: httpx.AsyncClient, token: str, tool: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    """``tools/call`` that must reach the tool; returns the CallToolResult object."""
    response = await rpc(
        client, "tools/call", {"name": tool, "arguments": arguments}, token=token, name=tool
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "result" in body, body
    return body["result"]


def tool_error(result: dict[str, Any]) -> dict[str, Any]:
    assert result["isError"] is True, result
    return result["structuredContent"]["error"]


def records(result: dict[str, Any]) -> list[dict[str, Any]]:
    assert result["isError"] is False, result
    return result["structuredContent"]["records"]


def query_args(entity: str, *, domain: str | None = None, **extra: Any) -> dict[str, Any]:
    query: dict[str, Any] = {
        "schema_version": "1.0.0",
        "operation": "list",
        "entity": entity,
        "budget": {"timeout_ms": 2000, "limit": 20, "max_depth": 0},
        **extra,
    }
    if domain is not None:
        query["filters"] = [{"field": "domain_id", "op": "eq", "value": domain}]
    return {"query": query}


def cost_args(*, domain: str | None = None) -> dict[str, Any]:
    args = query_args(
        "cost_record",
        domain=domain,
        operation="aggregate",
        time_range={"start": "2026-10-01T00:00:00Z", "end": "2026-10-10T00:00:00Z"},
        time_bucket="day",
    )
    return args


def draft_args(target: str = TARGET, new_version: str = "2026-06-15") -> dict[str, Any]:
    return {
        "action_kind": KIND,
        "target": {"canonical_id": target, "entity_type": "agent"},
        "target_version": TARGET_VERSION,
        "proposed_diff": {
            "format": "json_patch",
            "operations": [
                {"op": "test", "path": "/model/version", "value": "2024-08-06"},
                {"op": "replace", "path": "/model/version", "value": new_version},
            ],
        },
    }


def default_world() -> World:
    return make_world(
        [
            agent(TARGET, FINANCE),
            agent(OPS_TARGET, OPERATIONS),
            agent("commercial:contoso:foundry:agent:fin-1", FINANCE),
        ],
        recs=[recommendation(1, FINANCE), recommendation(2, OPERATIONS)],
    )


def make_harness(
    *,
    world: World | None = None,
    revocation_checker: RevocationChecker | None = None,
    settings: McpServerSettings | None = None,
    validator: JwtValidator | None = None,
    bind_ports: bool = True,
    action_plane: bool = True,
) -> McpHarness:
    api = make_api(wire=action_plane)
    h = api.h
    if revocation_checker is not None:
        deriver = helpers.make_deriver(h.repo, h.clock, revocation_checker=revocation_checker)
        h.deriver = deriver
        configure_authz(h.app, authenticator=h.validator, scope_source=deriver, clock=h.clock)
    resolved = world if world is not None else default_world()
    if bind_ports:
        h.app.state.catalog_repository = resolved.catalog
        h.app.state.aggregate_reader = resolved.metrics
        h.app.state.recommendation_store = resolved.recs
    mcp_validator = validator or make_mcp_validator(h.clock)
    mount = create_mcp_server(
        h.app,
        settings or mcp_settings(),
        validator=mcp_validator,
        clock=lambda: datetime.fromtimestamp(h.clock(), UTC),
    )
    h.app.router.routes.append(mount.route())
    return McpHarness(api=api, world=resolved, mount=mount, validator=mcp_validator)


@asynccontextmanager
async def mcp_session(harness: McpHarness) -> AsyncIterator[httpx.AsyncClient]:
    """Run the SDK session manager (the API lifespan does this in production) plus a client."""
    async with harness.mount.session_manager.run(), harness.client() as client:
        yield client
