"""The MCP feature against the live composed API (PRP-22 audit close-out, lane R; G08 evidence).

Runs the production composition over real HTTP on ``127.0.0.1`` (:mod:`.mcp_live_stack`: compose
emulators, ``NS_ENV=local`` with the local dev issuer as the only stand-in, ``NS_MCP_*`` set in the
process environment) and checks, against the live process:

* the MCP route exists: RFC 9728 metadata is served (resource + the active cloud's authorization
  server) and its CORS preflight answers; ``/mcp`` without a token is 401 with
  ``resource_metadata``;
* ``tools/list`` is scope-filtered (a viewer does not see the action tools an analyst sees) and a
  read tool returns only the caller's domain while other seeded domains hold data;
* token audience separation: a token for another audience and a REST-audience token are 401 at
  ``/mcp``, an MCP token is 401 at a REST route, and a missing ``mcp.invoke`` scope is 403;
* the admin API (``/api/v1/mcp/admin/servers``) enforces ``config.manage``: viewer 403, admin 200;
* registering a REAL stub MCP server listening on ``127.0.0.1`` (reachable, proven by a direct
  ``tools/list``) is refused by the admin plane's SSRF guard for every loopback spelling, and
  nothing gets registered; a public name that resolves to ``127.0.0.1`` (``localtest.me``, one
  ordinary DNS lookup through the system resolver) registers, but its sync is refused by the
  resolved address, so no tool is ever listed or approvable.

Every check appends one redacted line (status codes, error codes, tool names; never a token or a
body) to the evidence printed at the end, which ``docs/evidence/G08/`` records.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from mcp.server.mcpserver import MCPServer

from .mcp_live_stack import (
    MCP_AUDIENCE,
    MCP_RESOURCE,
    REST_AUDIENCE,
    TENANT,
    LiveStack,
    ServerThread,
    bearer,
    free_port,
    http_client,
    live_stack,
    mcp_rpc,
    record_domains,
)
from .mcp_security_harness import cf, cs

pytestmark = pytest.mark.integration

ADMIN_SERVERS = "/api/v1/mcp/admin/servers"
METADATA = "/.well-known/oauth-protected-resource/mcp"
ACTION_TOOLS = {"draft_action", "validate_action", "present_action_confirmation"}
#: A public DNS name whose A record is 127.0.0.1 (resolved by the system resolver at sync time).
LOOPBACK_NAME = "localtest.me"


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def stack() -> AsyncIterator[LiveStack]:
    async with live_stack() as running:
        yield running


def _error(response: Any) -> str:
    """``code/reason`` of an error body (never the body itself)."""
    try:
        body = response.json()
    except ValueError:
        return "-"
    if isinstance(body, dict):
        error = body.get("error", body)
        if isinstance(error, dict):
            return f"{error.get('code', '-')}/{error.get('reason', '-')}"
    return "-"


@pytest.mark.asyncio(loop_scope="module")
async def test_mcp_feature_against_the_live_composed_api(
    stack: LiveStack, capsys: pytest.CaptureFixture[str]
) -> None:
    evidence: list[str] = [
        f"composed API: http://127.0.0.1:{stack.port} (uvicorn, create_app + compose_app)",
        "process env: "
        + ", ".join(
            f"{k}={v}" for k, v in sorted(stack.environment.items()) if k.startswith("NS_")
        ),
        f"seed: {stack.seed_summary}; seeded domains={len(stack.domains)}",
        "principals: viewer(1 domain), analyst(1 domain), admin(all seeded domains)",
    ]

    async with http_client(stack) as http:
        # 1. The MCP route exists: RFC 9728 metadata, preflight, unauthenticated 401.
        meta = await http.get(METADATA)
        assert meta.status_code == 200, meta.status_code
        body = meta.json()
        assert body["resource"] == MCP_RESOURCE
        issuer = f"https://login.microsoftonline.com/{TENANT}/v2.0"
        assert issuer in body["authorization_servers"]
        evidence.append(
            f"GET {METADATA} -> {meta.status_code}; resource={body['resource']}; "
            f"authorization_servers=[login.microsoftonline.com/<tenant>/v2.0]; "
            f"scopes_supported={body.get('scopes_supported')}"
        )
        preflight = await http.options(
            METADATA,
            headers={"Origin": "https://client.example", "Access-Control-Request-Method": "GET"},
        )
        assert preflight.status_code in (200, 204), preflight.status_code
        allow_origin = preflight.headers.get("access-control-allow-origin")
        assert allow_origin == "*"
        evidence.append(
            f"OPTIONS {METADATA} (preflight) -> {preflight.status_code}; "
            f"access-control-allow-origin={allow_origin}"
        )
        anonymous = await mcp_rpc(http, "tools/list", token=None)
        assert anonymous.status_code == 401
        challenge = anonymous.headers.get("www-authenticate", "")
        assert "resource_metadata=" in challenge
        evidence.append(
            f"POST /mcp tools/list without token -> {anonymous.status_code}; "
            "WWW-Authenticate carries resource_metadata"
        )

        # 2. tools/list is scope-filtered; reads return only the caller's domain.
        lists: dict[str, set[str]] = {}
        for who in ("viewer", "analyst"):
            listed = await mcp_rpc(http, "tools/list", token=stack.token(who))
            assert listed.status_code == 200, listed.status_code
            lists[who] = {t["name"] for t in listed.json()["result"]["tools"]}
            evidence.append(
                f"POST /mcp tools/list as {who} (MCP token) -> {listed.status_code}; "
                f"tools={sorted(lists[who])}"
            )
        assert "search_catalog" in lists["viewer"]
        assert not ACTION_TOOLS & lists["viewer"]
        assert ACTION_TOOLS <= lists["analyst"]

        viewer_domains = set(stack.principals["viewer"].domains)
        search = {"name": "search_catalog", "arguments": cs.query_args("agent")}
        viewer_read = await mcp_rpc(http, "tools/call", search, token=stack.token("viewer"))
        admin_read = await mcp_rpc(http, "tools/call", search, token=stack.token("admin"))
        seen_viewer = record_domains(viewer_read)
        seen_admin = record_domains(admin_read)
        assert seen_viewer and seen_viewer <= viewer_domains
        assert len(seen_admin) > 1 and seen_admin - viewer_domains
        evidence.append(
            f"tools/call search_catalog: viewer -> {viewer_read.status_code}, rows from "
            f"{len(seen_viewer)} domain (its own); admin -> {admin_read.status_code}, rows from "
            f"{len(seen_admin)} domains"
        )
        other = sorted(seen_admin - viewer_domains)[0]
        filtered = await mcp_rpc(
            http,
            "tools/call",
            {"name": "search_catalog", "arguments": cs.query_args("agent", domain=other)},
            token=stack.token("viewer"),
        )
        assert record_domains(filtered) == set()
        smuggled = await mcp_rpc(
            http,
            "tools/call",
            {
                "name": "search_catalog",
                "arguments": {**cs.query_args("agent"), "domain_id": other},
            },
            token=stack.token("viewer"),
        )
        smuggled_error = smuggled.json()["result"]["structuredContent"]["error"]
        assert (smuggled_error["code"], smuggled_error["reason"]) == (
            "forbidden",
            "scope_argument_refused",
        )
        evidence.append(
            "tools/call search_catalog as viewer with another seeded domain as filter -> "
            f"{filtered.status_code}, 0 rows (narrowed); as a domain_id argument -> "
            f"{smuggled.status_code}, isError forbidden/scope_argument_refused"
        )

        # 3. Audience separation and the required scope.
        cases = {
            "token for another audience": stack.token("viewer", audience="api://someone-else"),
            "REST-audience token": stack.token("viewer", audience=REST_AUDIENCE, scopes=()),
        }
        for label, token in cases.items():
            refused = await mcp_rpc(http, "tools/list", token=token)
            assert refused.status_code == 401, (label, refused.status_code)
            evidence.append(f"POST /mcp tools/list with {label} -> {refused.status_code}")
        no_scope = await mcp_rpc(http, "tools/list", token=stack.token("viewer", scopes=()))
        assert no_scope.status_code == 403
        evidence.append(
            f"POST /mcp tools/list with MCP token lacking mcp.invoke -> {no_scope.status_code}"
        )
        mcp_at_rest = await http.get(
            "/api/v1/me/domains", headers=bearer(stack.token("viewer", audience=MCP_AUDIENCE))
        )
        rest_ok = await http.get("/api/v1/me/domains", headers=stack.rest_headers("viewer"))
        assert mcp_at_rest.status_code == 401
        assert rest_ok.status_code == 200
        evidence.append(
            f"GET /api/v1/me/domains with MCP-audience token -> {mcp_at_rest.status_code}; "
            f"with REST token -> {rest_ok.status_code}"
        )

        # 4. Admin API enforces config.manage.
        as_viewer = await http.get(ADMIN_SERVERS, headers=stack.rest_headers("viewer"))
        as_admin = await http.get(ADMIN_SERVERS, headers=stack.rest_headers("admin"))
        assert as_viewer.status_code == 403
        assert as_admin.status_code == 200
        assert as_admin.json()["items"] == []
        evidence.append(
            f"GET {ADMIN_SERVERS}: viewer -> {as_viewer.status_code} ({_error(as_viewer)}); "
            f"admin -> {as_admin.status_code}, items=0"
        )
        viewer_register = await http.post(
            ADMIN_SERVERS,
            json={"url": "https://mcp.example.com/mcp", "display_name": "x"},
            headers=stack.rest_headers("viewer"),
        )
        assert viewer_register.status_code == 403
        evidence.append(f"POST {ADMIN_SERVERS} as viewer -> {viewer_register.status_code}")

        # 5. A real stub MCP server on 127.0.0.1: reachable, but registration is refused.
        stub = MCPServer("loopback-stub")

        @stub.tool()
        def echo(text: str) -> str:
            """Echo the text."""
            return text

        stub_port = free_port()
        stub_thread = ServerThread(cf.default_app(stub), stub_port)
        stub_thread.start()
        try:
            direct = await http.post(
                f"http://127.0.0.1:{stub_port}/mcp",
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
                headers={
                    "Accept": "application/json, text/event-stream",
                    "Content-Type": "application/json",
                },
            )
            evidence.append(
                f"stub MCP server on 127.0.0.1:<port> answers directly: POST /mcp tools/list -> "
                f"{direct.status_code}"
            )
            assert direct.status_code == 200
            for url in (
                f"https://127.0.0.1:{stub_port}/mcp",
                f"https://localhost:{stub_port}/mcp",
                f"https://[::1]:{stub_port}/mcp",
                f"https://[::ffff:127.0.0.1]:{stub_port}/mcp",
                f"http://127.0.0.1:{stub_port}/mcp",
            ):
                register = await http.post(
                    ADMIN_SERVERS,
                    json={"url": url, "display_name": "Loopback stub"},
                    headers=stack.rest_headers("admin"),
                )
                shown = url.replace(str(stub_port), "<port>")
                evidence.append(
                    f"POST {ADMIN_SERVERS} as admin url={shown} -> {register.status_code} "
                    f"({_error(register)})"
                )
                assert register.status_code in (400, 403, 422), (shown, register.status_code)
            listed_after = await http.get(ADMIN_SERVERS, headers=stack.rest_headers("admin"))
            assert listed_after.json()["items"] == []
            evidence.append(f"GET {ADMIN_SERVERS} as admin after the attempts -> items=0")

            # A public NAME that resolves to loopback passes registration (no DNS there) and
            # must be refused at sync, by the resolved address, before any connection.
            rebind_url = f"https://{LOOPBACK_NAME}:{stub_port}/mcp"
            created = await http.post(
                ADMIN_SERVERS,
                json={"url": rebind_url, "display_name": "Resolves to loopback"},
                headers=stack.rest_headers("admin"),
            )
            outcome = _error(created) if created.status_code >= 400 else "registered"
            evidence.append(
                f"POST {ADMIN_SERVERS} as admin url=https://{LOOPBACK_NAME}:<port>/mcp -> "
                f"{created.status_code} ({outcome})"
            )
            assert created.status_code == 201, created.status_code
            server_id = created.json()["id"]
            synced = await http.post(
                f"{ADMIN_SERVERS}/{server_id}/sync", headers=stack.rest_headers("admin")
            )
            evidence.append(
                f"POST {ADMIN_SERVERS}/<id>/sync as admin -> "
                f"{synced.status_code} ({_error(synced)})"
            )
            # 403 ssrf_blocked_address when the resolver answers 127.0.0.1; a resolver that
            # sinkholes the name (DNS-rebinding protection) makes getaddrinfo fail instead, and
            # the sync fails closed with 503 mcp_dns_unavailable. Either way nothing is fetched;
            # the evidence line records which one this host produced.
            assert (synced.status_code, _error(synced)) in {
                (403, "forbidden/ssrf_blocked_address"),
                (503, "dependency_transient/mcp_dns_unavailable"),
            }, (synced.status_code, _error(synced))
            tools = await http.get(
                f"{ADMIN_SERVERS}/{server_id}/tools", headers=stack.rest_headers("admin")
            )
            assert tools.json()["items"] == []
            evidence.append(
                f"GET {ADMIN_SERVERS}/<id>/tools -> {tools.status_code}, items=0 (nothing synced, "
                "so nothing can be approved)"
            )
        finally:
            stub_thread.stop()

    with capsys.disabled():
        print("\n--- PRP-22 live MCP evidence (redacted) ---")
        for line in evidence:
            print(line)
