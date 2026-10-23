"""Confused-deputy suite for the MCP server and client (PRP-22 item 4). Every case is denied.

The deputy is NeuroSphere: it holds data and an action plane, and must never let a caller borrow
more than the caller's own server-derived scope. Covered, end to end against the real stacks:

1. Token for another resource: the REST audience (and a third audience, and the bare resource
   URL) against ``/mcp`` is 401 with the RFC 9728 challenge; an MCP token against REST is 401;
   ``validate_token_resource=True`` is set on the SDK resource server. Also through item 2's
   real client: a NeuroSphere registration whose platform credential is a REST token gets
   nothing.
2. Token minted for the MCP client app with no user: app-only (client-credentials) tokens carry
   ``roles``, never ``scp``, so the delegated ``mcp.invoke`` scope is missing (403). A token
   that does carry the scope but is app-only (``idtyp=app``) derives a SERVICE PRINCIPAL id
   (``...:entra:principal:p-...``), never the user's, so even an app token naming a user's
   ``oid`` holds no grant and every tool is refused.
3. Model-supplied ``domain_id`` / ``customer_id`` in any spelling, on every tool: refused before
   any port or the action plane is reached; scope-shaped values inside the payload never widen.
4. A token replayed after its principal was revoked (past the revocation TTL): denied on MCP and
   on REST; a replayed draft creates nothing.
5. No confirm/approve/execute over MCP (D5): no such tool, no argument smuggles a confirmation,
   an MCP token cannot drive the REST confirm route; a human with a REST token can.
6. No outbound request made while serving a call carries the inbound bearer, even when a port
   federates to an external MCP server through item 2's client during the call.
"""

from __future__ import annotations

import asyncio
import json
import re
import socket
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import httpx
import httpx2
import pytest
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.mcpserver import MCPServer
from neurosphere_api.mcp.server import MCP_TOOL_NAMES, PROTECTED_RESOURCE_METADATA_PATH
from neurosphere_core.auth.revocation import (
    CachedRevocationChecker,
    InMemoryRevocationStore,
    RevocationEntry,
)
from neurosphere_core.errors import NeuroSphereError
from neurosphere_core.scope import IdentityScope

from .mcp_security_harness import (
    ADMIN,
    PUBLIC_V4,
    AppRouter,
    PlatformCredential,
    authorization_value,
    cf,
    cs,
    derive_scope,
    make_client,
)

METADATA_URL: Final = f"https://{cs.MCP_HOST}{PROTECTED_RESOURCE_METADATA_PATH}"
INTENT_ID: Final = "00000000-0000-4000-8000-000000000001"
FABRIKAM_AGENT: Final = "commercial:fabrikam:foundry:agent:fab-1"
FABRIKAM: Final = "commercial:fabrikam:catalog:domain:finance"


def _challenge(response: httpx.Response) -> dict[str, str]:
    """``WWW-Authenticate: Bearer k="v", ...`` as a dict (compared by equality, not substring)."""
    header = response.headers["www-authenticate"]
    scheme, _, params = header.partition(" ")
    assert scheme == "Bearer", header
    return dict(re.findall(r'([a-z_]+)="([^"]*)"', params))


def _assert_401(response: httpx.Response) -> None:
    assert response.status_code == 401, response.text
    challenge = _challenge(response)
    assert challenge["resource_metadata"] == METADATA_URL
    assert challenge["error"] == "invalid_token"


def _assert_403_scope(response: httpx.Response) -> None:
    assert response.status_code == 403, response.text
    challenge = _challenge(response)
    assert challenge["error"] == "insufficient_scope"
    assert challenge["resource_metadata"] == METADATA_URL


async def _intent_count(harness: Any) -> int:
    total = 0
    for domain in (cs.FINANCE, cs.OPERATIONS):
        page = await harness.api.intents.list(cs.CUSTOMER, domain)
        total += len(page.items)
    return total


def _valid_args() -> dict[str, dict[str, Any]]:
    """Minimal valid arguments for every MCP tool."""
    intent = {"intent_id": INTENT_ID}
    return {
        "search_catalog": cs.query_args("agent"),
        "get_cost_summary": cs.cost_args(),
        "list_recommendations": cs.query_args("recommendation"),
        "draft_action": cs.draft_args(),
        "validate_action": dict(intent),
        "present_action_confirmation": dict(intent),
        "get_action_status": dict(intent),
    }


def _world_with_other_customer() -> Any:
    world = cs.default_world()
    world.catalog.entities.append(cs.agent(FABRIKAM_AGENT, FABRIKAM, customer="fabrikam"))
    return world


# -- 1. token for another resource / audience ----------------------------------------------------


async def test_tokens_for_another_resource_are_401_on_every_mcp_method() -> None:
    harness = cs.make_harness()
    assert harness.mount.auth_settings.validate_token_resource is True
    others = {
        "rest_audience": harness.rest_token(cs.ALICE),
        "third_audience": harness.token(cs.ALICE, audience="api://another-resource"),
        "resource_url_not_an_audience": harness.token(cs.ALICE, audience=cs.MCP_RESOURCE),
    }
    async with cs.mcp_session(harness) as client:
        for token in others.values():
            for method, params in (
                ("tools/list", None),
                ("tools/call", {"name": "search_catalog", "arguments": cs.query_args("agent")}),
                ("tools/call", {"name": "draft_action", "arguments": cs.draft_args()}),
                ("resources/read", {"uri": "neurosphere://scope/current"}),
            ):
                _assert_401(await cs.rpc(client, method, params, token=token))
        ok = await cs.rpc(client, "tools/list", token=harness.token(cs.ALICE))
        assert ok.status_code == 200, ok.text
    assert harness.world.domains_asked() == set()
    intents = await _intent_count(harness)
    assert intents == 0


def test_an_mcp_token_is_401_on_every_rest_action_route() -> None:
    harness = cs.make_harness()
    mcp_auth = cs.bearer(harness.token(cs.ALICE))
    rest = harness.api.h.client
    base = f"/api/v1/actions/domains/{cs.FINANCE}/intents"
    body = {**cs.draft_args(), "idempotency_key": "idem-deputy-rest-0001"}
    for method, path, payload in (
        ("GET", base, None),
        ("POST", base, body),
        ("POST", f"{base}/{INTENT_ID}/confirm", {"confirmation_hash": "sha256:" + "0" * 64}),
        ("POST", f"{base}/{INTENT_ID}/decisions", None),
    ):
        response = rest.request(method, path, json=payload, headers=mcp_auth)
        assert response.status_code == 401, (method, path, response.text)
    created = rest.post(base, json=body, headers=cs.bearer(harness.rest_token(cs.ALICE)))
    assert created.status_code == 201, created.text  # the right token for the right resource


async def test_the_real_client_with_a_rest_token_as_platform_credential_gets_nothing() -> None:
    harness = cs.make_harness()
    router = AppRouter(harness.app)
    client, registry, _ = make_client(
        router, credentials=PlatformCredential(harness.rest_token(cs.ALICE))
    )
    async with harness.mount.session_manager.run():
        server = await registry.register(cs.MCP_RESOURCE, display_name="NS", actor=ADMIN)
        with pytest.raises(NeuroSphereError) as refused:
            await client.sync_tools(server.id)
    # The resource server's 401 surfaces from item 2's client as a transient "unavailable".
    assert (refused.value.code, refused.value.reason) == (
        "dependency_transient",
        "mcp_server_unavailable",
    )
    stored = await registry.require(server.id)
    assert stored.tools == ()  # no manifest was obtained, nothing to approve
    assert router.sent  # the request was made and answered 401 by the resource server
    assert harness.world.domains_asked() == set()


# -- 2. token minted for the MCP client app, with no user ----------------------------------------


async def test_app_only_client_credentials_tokens_lack_the_delegated_scope() -> None:
    harness = cs.make_harness()
    client_app = str(uuid.uuid4())
    service_principal = str(uuid.uuid4())
    shapes = {
        # Entra app-only shape: application roles, no ``scp``; with and without ``idtyp``.
        "idtyp_app": {"idtyp": "app", "azp": client_app, "roles": ["mcp.invoke"]},
        "no_idtyp": {"azp": client_app, "roles": ["mcp.invoke"]},
    }
    async with cs.mcp_session(harness) as client:
        for extra in shapes.values():
            token = harness.token(service_principal, scopes=(), **extra)
            _assert_403_scope(await cs.rpc(client, "tools/list", token=token))
            _assert_403_scope(
                await cs.rpc(
                    client,
                    "tools/call",
                    {"name": "search_catalog", "arguments": cs.query_args("agent")},
                    token=token,
                )
            )
    assert harness.world.domains_asked() == set()


@pytest.mark.parametrize("object_id", ["own_service_principal", "a_users_oid"])
async def test_an_app_token_with_the_scope_holds_no_user_grant(object_id: str) -> None:
    """``idtyp=app`` derives ``principal_kind=service_principal``: a different principal id from
    any user, so it inherits nothing, even when its ``oid`` equals ALICE's object id."""
    harness = cs.make_harness()
    oid = cs.ALICE if object_id == "a_users_oid" else str(uuid.uuid4())
    token = harness.token(oid, idtyp="app", azp=str(uuid.uuid4()))
    claims = await harness.validator.validate(token)
    assert claims.identity_type == "app"
    derived = await harness.api.h.deriver.from_verified_claims(claims)
    alice = await derive_scope(harness, cs.ALICE)
    contract = derived.to_contract()
    assert contract.principal.principal_kind == "service_principal"
    principal_id = contract.principal.principal_id.root
    assert ":entra:principal:" in principal_id
    assert principal_id != alice.to_contract().principal.principal_id.root
    assert list(derived.allowed_domains) == [] and contract.roles == []

    errors: dict[str, dict[str, Any]] = {}
    async with cs.mcp_session(harness) as client:
        for tool, args in _valid_args().items():
            errors[tool] = cs.tool_error(await cs.call_tool(client, token, tool, args))
        scope_view = await cs.rpc(
            client, "resources/read", {"uri": "neurosphere://scope/current"}, token=token
        )
    for tool, error in errors.items():
        assert error["code"] in {"forbidden", "not_found"}, (tool, error)
    assert errors["draft_action"]["reason"] == "target_out_of_scope"
    assert scope_view.status_code == 200, scope_view.text
    summary = json.loads(scope_view.json()["result"]["contents"][0]["text"])
    assert summary["readable_domains"] == [] and summary["proposable_domains"] == []
    assert harness.world.metrics.domains_asked == [] and harness.world.recs.domains_asked == []
    # Only the by-id lookup of the draft target (which returned nothing for this scope).
    assert set(harness.world.catalog.domains_asked) <= {cs.FINANCE}
    intents = await _intent_count(harness)
    assert intents == 0


# -- 3. model-supplied domain / customer arguments -----------------------------------------------

SCOPE_SPELLINGS: Final = (
    "domain_id",
    "domainId",
    "Domain-ID",
    "DOMAIN_ID",
    "domain id",
    "domains",
    "customer_id",
    "customerId",
    "Customer-Id",
    "tenant_id",
    "allowed_domains",
    "scope",
)
#: Not on the scope-shaped list, but every tool's arguments are a closed set: still refused.
LOOKALIKE_SPELLINGS: Final = ("domain.id", "domain\u200bid", "cust0mer_id", "x_domain_id")


@pytest.mark.parametrize("key", [*SCOPE_SPELLINGS, *LOOKALIKE_SPELLINGS])
async def test_a_model_supplied_scope_argument_is_refused_on_every_tool(key: str) -> None:
    harness = cs.make_harness()
    values = (cs.OPERATIONS, "fabrikam", [cs.OPERATIONS], {"domain_id": cs.OPERATIONS})
    async with cs.mcp_session(harness) as client:
        token = harness.token(cs.ALICE)
        for tool, args in _valid_args().items():
            for value in values:
                result = await cs.call_tool(client, token, tool, {**args, key: value})
                error = cs.tool_error(result)
                expected = (
                    {"scope_argument_refused"}
                    if key in SCOPE_SPELLINGS
                    else {"argument_not_allowed", "scope_argument_refused"}
                )
                assert (error["code"], error["status"]) == ("forbidden", 403), (tool, key)
                assert error["reason"] in expected, (tool, key, error)
    assert harness.world.domains_asked() == set()  # no read port reached
    intents = await _intent_count(harness)
    assert intents == 0
    assert harness.api.connector.dry_runs == []


async def test_scope_shaped_values_inside_the_payload_never_widen() -> None:
    """Nested filters and target ids naming another domain or customer narrow or are refused."""
    harness = cs.make_harness(world=_world_with_other_customer())
    async with cs.mcp_session(harness) as client:
        token = harness.token(cs.ALICE)
        attempts: list[tuple[str, dict[str, Any]]] = [
            ("search_catalog", cs.query_args("agent", domain=cs.OPERATIONS)),
            ("search_catalog", cs.query_args("agent", domain="*")),
            ("search_catalog", cs.query_args("agent", filters=[cf_filter("customer_id")])),
            ("search_catalog", cs.query_args("agent", filters=[cf_filter("cloud")])),
            ("get_cost_summary", cs.cost_args(domain=cs.OPERATIONS)),
            ("list_recommendations", cs.query_args("recommendation", domain=cs.OPERATIONS)),
            ("draft_action", cs.draft_args(cs.OPS_TARGET)),
            ("draft_action", cs.draft_args(FABRIKAM_AGENT)),
        ]
        for tool, args in attempts:
            result = await cs.call_tool(client, token, tool, args)
            if result["isError"]:
                assert cs.tool_error(result)["code"] in {"forbidden", "invalid_schema"}, tool
                continue
            rows = cs.records(result)
            assert {r["data"]["domain_id"] for r in rows} <= {cs.FINANCE}, (tool, args)
    # Metrics and recommendation ports were only ever asked for FINANCE. The catalog fake also
    # notes the domain of an entity looked up BY ID (the two draft targets) before it filters by
    # scope; that lookup returned nothing (target_out_of_scope), so it is not a retrieval.
    assert set(harness.world.metrics.domains_asked) <= {cs.FINANCE}
    assert set(harness.world.recs.domains_asked) <= {cs.FINANCE}
    assert set(harness.world.catalog.domains_asked) <= {cs.FINANCE, cs.OPERATIONS, FABRIKAM}
    intents = await _intent_count(harness)
    assert intents == 0


def cf_filter(field: str) -> dict[str, Any]:
    return {"field": field, "op": "eq", "value": "fabrikam"}


# -- 4. token replayed after revocation ----------------------------------------------------------


async def test_a_token_replayed_after_revocation_is_denied_on_mcp_and_rest() -> None:
    clock_holder: dict[str, Callable[[], float]] = {}

    def clock() -> float:
        return clock_holder["clock"]()

    store = InMemoryRevocationStore(clock=clock)
    checker = CachedRevocationChecker(store, ttl_seconds=60, clock=clock)
    harness = cs.make_harness(revocation_checker=checker)
    clock_holder["clock"] = harness.clock
    mcp_token = harness.token(cs.ALICE)
    rest_token = harness.rest_token(cs.ALICE)
    path = harness.api.intents_path(cs.FINANCE)
    async with cs.mcp_session(harness) as client:
        before = await cs.call_tool(client, mcp_token, "search_catalog", cs.query_args("agent"))
        assert cs.records(before)
        rest_before = harness.api.h.client.get(
            f"/api/v1/actions{path}", headers=cs.bearer(rest_token)
        )
        assert rest_before.status_code == 200, rest_before.text

        await store.put(
            RevocationEntry(
                principal_id=cs.helpers.principal_id_for(cs.ALICE),
                revoked_at=datetime.fromtimestamp(harness.clock.now, UTC) + timedelta(seconds=1),
                reason="account_compromised",
                revoked_by=cs.helpers.principal_id_for(cs.BOB),
            )
        )
        harness.clock.advance(61)  # past the revocation TTL of the cached "not revoked" answer
        replays = {
            tool: await cs.call_tool(client, mcp_token, tool, args)
            for tool, args in _valid_args().items()
        }
        scope_read = await cs.rpc(
            client, "resources/read", {"uri": "neurosphere://scope/current"}, token=mcp_token
        )
    for tool, result in replays.items():
        error = cs.tool_error(result)
        assert (error["code"], error["reason"], error["status"]) == (
            "forbidden",
            "principal_revoked",
            403,
        ), tool
    assert scope_read.json()["error"]["data"]["reason"] == "principal_revoked"
    rest_after = harness.api.h.client.get(f"/api/v1/actions{path}", headers=cs.bearer(rest_token))
    assert rest_after.status_code == 403, rest_after.text
    intents = await _intent_count(harness)
    assert intents == 0  # the replayed draft created nothing


# -- 5. an action tool cannot confirm, approve or execute ----------------------------------------


async def test_mcp_cannot_confirm_approve_or_execute_and_a_human_can() -> None:
    harness = cs.make_harness()
    async with cs.mcp_session(harness) as client:
        token = harness.token(cs.ALICE)
        listed = await cs.rpc(client, "tools/list", token=token)
        names = {t["name"] for t in listed.json()["result"]["tools"]}
        assert names == set(MCP_TOOL_NAMES)
        assert not {n for n in names if any(v in n for v in ("confirm", "approv", "execut"))} - {
            "present_action_confirmation"
        }

        [draft] = cs.records(await cs.call_tool(client, token, "draft_action", cs.draft_args()))
        intent_id = draft["data"]["intent_id"]
        cs.records(await cs.call_tool(client, token, "validate_action", {"intent_id": intent_id}))
        [bound] = cs.records(
            await cs.call_tool(
                client, token, "present_action_confirmation", {"intent_id": intent_id}
            )
        )
        confirmation = bound["data"]["confirmation_hash"]
        assert confirmation.startswith("sha256:")

        for tool in (
            "confirm_action",
            "confirm_intent",
            "execute_action",
            "approve_action",
            "decide_action",
            "confirm",
            "Confirm_Action",
        ):
            refused = cs.tool_error(
                await cs.call_tool(
                    client, token, tool, {"intent_id": intent_id, "confirmation_hash": confirmation}
                )
            )
            assert refused["reason"] == "tool_not_registered", tool
        for tool in ACTION_STEPS:
            for extra in (
                {"confirmation_hash": confirmation},
                {"decision": "approved"},
                {"execute": True},
                {"state": "executing"},
            ):
                smuggled = cs.tool_error(
                    await cs.call_tool(client, token, tool, {"intent_id": intent_id, **extra})
                )
                assert smuggled["reason"] == "argument_not_allowed", (tool, extra)
        status = cs.records(
            await cs.call_tool(client, token, "get_action_status", {"intent_id": intent_id})
        )

    assert status[0]["data"]["state"] == "awaiting_confirmation"
    assert harness.api.connector.forbidden_calls == []
    # An MCP token cannot drive the REST confirm route either (wrong resource: 401).
    confirm_path = f"/api/v1/actions{harness.api.intents_path()}/{intent_id}/confirm"
    body = {"confirmation_hash": confirmation}
    by_mcp_token = harness.api.h.client.post(confirm_path, json=body, headers=cs.bearer(token))
    assert by_mcp_token.status_code == 401, by_mcp_token.text
    assert harness.api.get_intent(intent_id).json()["intent"]["state"] == "awaiting_confirmation"
    # The human, through REST with a REST token and the bound hash, can.
    confirmed = harness.api.step(cs.ALICE, intent_id, "confirm", body)
    assert confirmed.status_code == 200, confirmed.text


ACTION_STEPS: Final = ("validate_action", "present_action_confirmation", "get_action_status")


# -- 6. no outbound request carries the inbound bearer -------------------------------------------


class _Outbound:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def blocked(self, label: str) -> Callable[..., Any]:
        def refuse(*args: Any, **kwargs: Any) -> Any:
            self.calls.append(label)
            raise AssertionError(f"real outbound {label} attempted")

        return refuse


def _block_real_network(monkeypatch: pytest.MonkeyPatch) -> _Outbound:
    outbound = _Outbound()
    for owner, name in (
        (httpx.AsyncHTTPTransport, "handle_async_request"),
        (httpx2.AsyncHTTPTransport, "handle_async_request"),
        (socket.socket, "connect"),
        (socket.socket, "connect_ex"),
        (asyncio.BaseEventLoop, "create_connection"),
    ):
        monkeypatch.setattr(owner, name, outbound.blocked(f"{owner.__name__}.{name}"))
    monkeypatch.setattr(socket, "create_connection", outbound.blocked("socket.create_connection"))
    return outbound


def _external_server(seen: list[str]) -> MCPServer:
    server = MCPServer("external-federated")

    @server.tool()
    def lookup(record_id: str) -> str:
        """Look up a record by id."""
        seen.append(record_id)
        return f"record {record_id}"

    return server


async def test_no_outbound_request_carries_the_inbound_bearer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """While ``search_catalog`` is served for ALICE, the catalog port federates to an approved
    external MCP server through item 2's client. The inbound bearer is in the SDK's request
    context at that moment; it must not appear on any outbound request (headers or body)."""
    harness = cs.make_harness()
    inbound_token = harness.token(cs.ALICE)
    signature = inbound_token.rsplit(".", 1)[-1]

    seen: list[str] = []
    external = _external_server(seen)
    external_app = cf.default_app(external)
    router = AppRouter(external_app)
    ext_client, ext_registry, _ = make_client(
        router,
        answers={"mcp.example.com": [[PUBLIC_V4]]},
        credentials=PlatformCredential(None),  # the platform has no credential for it
    )
    server = await ext_registry.register(cf.SERVER_URL, display_name="Ext", actor=ADMIN)

    contexts: list[str] = []
    bodies: list[bytes] = []
    original_list = harness.world.catalog.list_entities

    async def federating_list(scope: IdentityScope, flt: Any, page: Any) -> Any:
        access = get_access_token()
        assert access is not None  # we are inside the inbound MCP request
        contexts.append(access.model_dump_json())
        result = await ext_client.call_tool(scope, server.id, "lookup", {"record_id": "fed-1"})
        assert result.content and result.content[0].text == "record fed-1"
        return await original_list(scope, flt, page)

    monkeypatch.setattr(harness.world.catalog, "list_entities", federating_list)

    original_handle = httpx2.ASGITransport.handle_async_request

    async def capture(self: httpx2.ASGITransport, request: httpx2.Request) -> httpx2.Response:
        bodies.append(await request.aread())
        return await original_handle(self, request)

    monkeypatch.setattr(httpx2.ASGITransport, "handle_async_request", capture)

    async with external.session_manager.run():
        await ext_client.sync_tools(server.id)
        stored = await ext_registry.require(server.id)
        record = stored.tool("lookup")
        assert record is not None
        await ext_registry.approve(
            server.id, "lookup", expected_hash=record.entry.tool_hash, actor=ADMIN
        )
        outbound = _block_real_network(monkeypatch)
        async with cs.mcp_session(harness) as client:
            result = await cs.call_tool(
                client, inbound_token, "search_catalog", cs.query_args("agent")
            )
    assert cs.records(result)
    assert seen == ["fed-1"]  # the federated call really happened during the inbound request
    assert outbound.calls == []  # and nothing used a real socket
    assert contexts and all(inbound_token not in c for c in contexts)  # SDK kept no raw token
    assert router.sent, "outbound requests were recorded"
    for sent in router.sent:
        assert "authorization" not in sent.headers
        assert "cookie" not in sent.headers
        for value in sent.headers.values():
            assert inbound_token not in value and signature not in value
    assert bodies
    for body in bodies:
        assert inbound_token.encode() not in body and signature.encode() not in body


async def test_the_recorder_does_see_a_credential_when_one_is_sent() -> None:
    """Control for the test above: the recording path is not blind to Authorization."""
    external = _external_server([])
    router = AppRouter(cf.default_app(external))
    platform_token = uuid.uuid4().hex
    ext_client, ext_registry, _ = make_client(
        router,
        answers={"mcp.example.com": [[PUBLIC_V4]]},
        credentials=PlatformCredential(platform_token),
    )
    server = await ext_registry.register(cf.SERVER_URL, display_name="Ext", actor=ADMIN)
    async with external.session_manager.run():
        await ext_client.sync_tools(server.id)
    assert router.sent
    assert {s.headers.get("authorization") for s in router.sent} == {
        authorization_value(platform_token)
    }
