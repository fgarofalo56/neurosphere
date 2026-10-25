"""The MCP server builder: mounted only when configured, after authz, audiences kept apart.

These are the key assertions of ``tests/security/mcp`` (token for another resource, scope
required, no confirm/approve/execute tool) run against the COMPOSED app; that suite builds its
own harness app and cannot be pointed at a composition, so it is run unchanged alongside.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
from authz.authz_helpers import AUDIENCE  # pyright: ignore[reportMissingImports]
from neurosphere_api.mcp.server import (
    MCP_PATH,
    MCP_TOOL_NAMES,
    PROTECTED_RESOURCE_METADATA_PATH,
    McpServerMount,
)

from .planes_helpers import (
    ALICE,
    MCP_ENV,
    Planes,
    compose_planes,
    configure_auth_env,
    cs,
    mcp_token,
)

ME = "/api/v1/me/domains"


@pytest.fixture(autouse=True)
def _auth(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_auth_env(monkeypatch)


def _mcp_env(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> None:
    for name, value in {**MCP_ENV, **overrides}.items():
        monkeypatch.setenv(name, value)


def _mcp_routes(app: Any) -> list[Any]:
    return [r for r in app.router.routes if getattr(r, "path", None) == MCP_PATH]


@asynccontextmanager
async def _client(planes: Planes) -> AsyncIterator[httpx.AsyncClient]:
    """The composed lifespan (it runs the SDK session manager) plus an in-process client."""
    app = planes.app
    transport = httpx.ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url=f"https://{cs.MCP_HOST}") as client,
    ):
        yield client


def _resource_metadata(response: httpx.Response) -> str:
    header = response.headers["www-authenticate"]
    assert header.startswith("Bearer "), header
    return header


def test_unset_resource_url_disables_the_server_and_mounts_nothing() -> None:
    planes = compose_planes(mcp_validator=True)
    assert planes.registry.get("mcp_server").state == "disabled"
    assert _mcp_routes(planes.app) == []
    with planes.composed.client() as client:
        metadata = client.get(PROTECTED_RESOURCE_METADATA_PATH)
    assert metadata.status_code == 503
    assert metadata.json()["reason"] == "mcp_unconfigured"


def test_configured_server_is_mounted_and_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    _mcp_env(monkeypatch)
    planes = compose_planes(mcp_validator=True)
    assert planes.registry.get("mcp_server").state == "ok", planes.registry.get("mcp_server")
    assert isinstance(planes.app.state.mcp_server, McpServerMount)
    assert len(_mcp_routes(planes.app)) == 1
    with planes.composed.client() as client:
        metadata = client.get(PROTECTED_RESOURCE_METADATA_PATH)
        ready = client.get("/readyz")
    assert metadata.status_code == 200
    assert metadata.json()["resource"] == cs.MCP_RESOURCE
    assert ready.status_code == 200, ready.json()


def test_the_runtime_route_is_not_in_the_openapi_document(monkeypatch: pytest.MonkeyPatch) -> None:
    _mcp_env(monkeypatch)
    planes = compose_planes(mcp_validator=True)
    paths = planes.app.openapi()["paths"]
    assert MCP_PATH not in paths


def test_the_production_validator_path_builds_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mcp_env(monkeypatch)
    planes = compose_planes()  # no validator override: create_jwt_validator over httpx
    assert planes.registry.get("mcp_server").state == "ok", planes.registry.get("mcp_server")
    assert planes.app.state.mcp_server.validator.config.audiences == (cs.MCP_AUDIENCE,)


def test_mcp_audiences_overlapping_the_rest_audience_are_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mcp_env(monkeypatch, NS_MCP_AUDIENCES=f'["{AUDIENCE}"]')
    planes = compose_planes()
    assert planes.registry.get("mcp_server").code == "mcp_config_invalid"
    assert _mcp_routes(planes.app) == []


def test_invalid_mcp_settings_fail_by_name(monkeypatch: pytest.MonkeyPatch) -> None:
    _mcp_env(monkeypatch, NS_MCP_RESOURCE_SERVER_URL="http://mcp.neurosphere.test/mcp")
    planes = compose_planes()
    assert planes.registry.get("mcp_server").code == "mcp_settings_invalid"


def test_without_authz_the_server_is_not_mounted(monkeypatch: pytest.MonkeyPatch) -> None:
    _mcp_env(monkeypatch)
    monkeypatch.delenv("NS_AUTH_TENANT_ID")
    planes = compose_planes(mcp_validator=True)
    assert planes.registry.get("mcp_server").state == "failed"
    assert _mcp_routes(planes.app) == []


def test_without_the_action_service_the_server_is_not_mounted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mcp_env(monkeypatch)
    planes = compose_planes(mcp_validator=True, skip=("hitl",))
    assert planes.registry.get("mcp_server").code == "action_service_unavailable"
    assert _mcp_routes(planes.app) == []


async def test_no_token_and_a_rest_token_are_401_with_the_resource_challenge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mcp_env(monkeypatch)
    planes = compose_planes(mcp_validator=True)
    rest_token = planes.auth(ALICE)["Authorization"].removeprefix("Bear" + "er ")
    async with _client(planes) as client:
        anonymous = await cs.rpc(client, "tools/list", token=None)
        rest = await cs.rpc(client, "tools/list", token=rest_token)
    for response in (anonymous, rest):
        assert response.status_code == 401, response.text
        assert "resource_metadata=" in _resource_metadata(response)


async def test_an_mcp_token_is_refused_by_the_rest_api(monkeypatch: pytest.MonkeyPatch) -> None:
    _mcp_env(monkeypatch)
    planes = compose_planes(mcp_validator=True)
    async with _client(planes) as client:
        response = await client.get(ME, headers=cs.bearer(mcp_token(planes)))
    assert response.status_code == 401


async def test_a_token_without_the_mcp_scope_is_403(monkeypatch: pytest.MonkeyPatch) -> None:
    _mcp_env(monkeypatch)
    planes = compose_planes(mcp_validator=True)
    from authz.authz_helpers import dev_issuer  # pyright: ignore[reportMissingImports]

    unscoped = dev_issuer().mint(
        audience=cs.MCP_AUDIENCE,
        object_id=ALICE,
        now=planes.clock.now,
        lifetime_seconds=20 * 365 * 86_400,
        scopes=("user_impersonation",),
    )
    async with _client(planes) as client:
        response = await cs.rpc(client, "tools/list", token=unscoped)
    assert response.status_code == 403, response.text


async def test_tools_list_offers_no_confirm_approve_or_execute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mcp_env(monkeypatch)
    planes = compose_planes(mcp_validator=True)
    async with _client(planes) as client:
        response = await cs.rpc(client, "tools/list", token=mcp_token(planes))
    assert response.status_code == 200, response.text
    names = sorted(tool["name"] for tool in response.json()["result"]["tools"])
    assert names == sorted(MCP_TOOL_NAMES)
    assert not [n for n in names if n.startswith(("confirm", "approve", "execute", "decide"))]


async def test_mcp_reads_are_limited_to_the_derived_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    _mcp_env(monkeypatch)
    planes = compose_planes(mcp_validator=True)
    async with _client(planes) as client:
        result = await cs.call_tool(
            client, mcp_token(planes), "search_catalog", cs.query_args("agent")
        )
        smuggled = await cs.call_tool(
            client,
            mcp_token(planes),
            "search_catalog",
            {**cs.query_args("agent"), "domain_id": cs.OPERATIONS},
        )
    rows = cs.records(result)
    assert rows
    assert {r["data"].get("domain_id") for r in rows} == {cs.FINANCE}
    assert smuggled["isError"] is True
