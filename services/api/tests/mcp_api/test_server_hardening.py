"""MCP server hardening (PRP-22 follow-up #111).

* ``tools/list`` and ``resources/list`` are derived from the caller's server-side scope, like
  ``tools/call``: two principals see different tool lists, list parameters cannot widen the
  scope, and a policy-store outage or an unknown principal is an error, never an unfiltered list.
* ``OPTIONS`` on the RFC 9728 metadata route answers a CORS preflight (it returned 405).
* The derived draft idempotency key carries a time window: the same change drafted again in a
  later window is a new intent, while the intent hash stays equal (surface independent).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import conftest_server as cs  # pyright: ignore[reportMissingImports]
import pytest
from action_plane_harness import principal  # pyright: ignore[reportMissingImports]
from neurosphere_api.authz import configure_authz
from neurosphere_api.mcp.server import MCP_TOOL_NAMES, PROTECTED_RESOURCE_METADATA_PATH
from neurosphere_api.mcp.server.router import build_router
from neurosphere_api.mcp.server.tools import (
    DERIVED_KEY_WINDOW_SECONDS,
    DraftActionArgs,
    _derived_idempotency_key,  # pyright: ignore[reportPrivateUsage]
)
from neurosphere_core.auth.jwt import VerifiedClaims
from neurosphere_core.auth.scope import ScopeDerivation
from neurosphere_core.errors import ForbiddenError

READ_ONLY_TOOLS = (
    "get_action_status",
    "get_cost_summary",
    "list_recommendations",
    "search_catalog",
)
ALL_RESOURCES = {
    "neurosphere://mcp/about",
    "neurosphere://scope/current",
    "neurosphere://recommendations/recent",
}
NO_POLICY_PRINCIPAL = "0f1e2d3c-4b5a-4968-8776-655443322110"


class CountingScopeSource:
    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.claims: list[VerifiedClaims] = []

    async def derive(self, claims: VerifiedClaims) -> ScopeDerivation:
        self.claims.append(claims)
        return await self.inner.derive(claims)


async def _list(client: Any, method: str, token: str, params: dict[str, Any] | None = None) -> Any:
    response = await cs.rpc(client, method, params, token=token)
    assert response.status_code == 200, response.text
    return response.json()


def _tool_names(body: dict[str, Any]) -> tuple[str, ...]:
    return tuple(sorted(t["name"] for t in body["result"]["tools"]))


def _resource_uris(body: dict[str, Any]) -> set[str]:
    return {r["uri"] for r in body["result"]["resources"]}


# -- tools/list and resources/list are scope-derived ---------------------------------------------


async def test_tools_list_differs_by_the_callers_derived_permissions() -> None:
    harness = cs.make_harness()
    async with cs.mcp_session(harness) as client:
        steward = await _list(client, "tools/list", harness.token(cs.ALICE))
        viewer = await _list(client, "tools/list", harness.token(cs.CAROL))
    # ALICE (steward on FINANCE) holds data.read and action.propose: the whole allowlist.
    assert _tool_names(steward) == MCP_TOOL_NAMES
    # CAROL (viewer on FINANCE) holds data.read only: no drafting tools are offered.
    assert _tool_names(viewer) == READ_ONLY_TOOLS
    assert steward["result"]["cacheScope"] == viewer["result"]["cacheScope"] == "private"


async def test_resources_list_follows_the_derived_scope_and_is_private() -> None:
    harness = cs.make_harness()
    async with cs.mcp_session(harness) as client:
        alice = await _list(client, "resources/list", harness.token(cs.ALICE))
        carol = await _list(client, "resources/list", harness.token(cs.CAROL))
        stranger = await _list(client, "resources/list", harness.token(NO_POLICY_PRINCIPAL))
    assert _resource_uris(alice) == _resource_uris(carol) == ALL_RESOURCES
    assert alice["result"]["cacheScope"] == "private"
    # No grant anywhere: no data resource, only the static description and the (empty) scope.
    assert _resource_uris(stranger) == {"neurosphere://mcp/about", "neurosphere://scope/current"}


async def test_a_principal_without_policy_is_offered_no_tools() -> None:
    harness = cs.make_harness()
    async with cs.mcp_session(harness) as client:
        body = await _list(client, "tools/list", harness.token(NO_POLICY_PRINCIPAL))
    assert body["result"]["tools"] == []


@pytest.mark.parametrize("method", ["tools/list", "resources/list"])
async def test_a_policy_store_outage_fails_listing_closed_with_503(method: str) -> None:
    harness = cs.make_harness()
    harness.api.h.repo.fail_with(RuntimeError("cosmos down"))
    async with cs.mcp_session(harness) as client:
        body = await _list(client, method, harness.token(cs.ALICE))
    assert "result" not in body
    data = body["error"]["data"]
    assert (data["code"], data["status"]) == ("dependency_transient", 503)
    assert "cosmos down" not in str(body)


class DenyingScopeSource:
    async def derive(self, claims: VerifiedClaims) -> ScopeDerivation:
        raise ForbiddenError("principal revoked", reason="principal_revoked")


@pytest.mark.parametrize("method", ["tools/list", "resources/list"])
async def test_a_denied_derivation_is_a_403_error_not_a_list(method: str) -> None:
    harness = cs.make_harness()
    configure_authz(
        harness.app,
        authenticator=harness.api.h.validator,
        scope_source=DenyingScopeSource(),
        clock=harness.clock,
    )
    async with cs.mcp_session(harness) as client:
        body = await _list(client, method, harness.token(cs.ALICE))
    assert "result" not in body
    data = body["error"]["data"]
    assert (data["code"], data["status"], data["reason"]) == (
        "forbidden",
        403,
        "principal_revoked",
    )


@pytest.mark.parametrize("method", ["tools/list", "resources/list"])
async def test_unconfigured_authz_fails_listing_closed(method: str) -> None:
    harness = cs.make_harness()
    delattr(harness.app.state, "authz")
    async with cs.mcp_session(harness) as client:
        body = await _list(client, method, harness.token(cs.ALICE))
    assert "result" not in body
    assert body["error"]["data"]["reason"] == "authz_unconfigured"


@pytest.mark.parametrize(
    "params",
    [
        {"domain_id": cs.OPERATIONS},
        {"domainId": cs.OPERATIONS, "customer_id": "fabrikam", "scope": {"domains": ["*"]}},
    ],
)
async def test_model_supplied_scope_parameters_on_a_list_never_widen_it(
    params: dict[str, Any],
) -> None:
    harness = cs.make_harness()
    counting = CountingScopeSource(harness.api.h.deriver)
    configure_authz(
        harness.app,
        authenticator=harness.api.h.validator,
        scope_source=counting,
        clock=harness.clock,
    )
    async with cs.mcp_session(harness) as client:
        token = harness.token(cs.CAROL)
        plain = await _list(client, "tools/list", token)
        supplied = await _list(client, "tools/list", token, params)
        resources = await _list(client, "resources/list", token, params)
    assert _tool_names(supplied) == _tool_names(plain) == READ_ONLY_TOOLS
    assert _resource_uris(resources) == ALL_RESOURCES
    # The scope still came from the token and the policy store only.
    assert {c.object_id for c in counting.claims} == {cs.CAROL}
    assert len(counting.claims) == 3


async def test_listing_rederives_the_scope_and_a_call_derives_it_exactly_once() -> None:
    harness = cs.make_harness()
    counting = CountingScopeSource(harness.api.h.deriver)
    configure_authz(
        harness.app,
        authenticator=harness.api.h.validator,
        scope_source=counting,
        clock=harness.clock,
    )
    async with cs.mcp_session(harness) as client:
        token = harness.token(cs.ALICE)
        await _list(client, "tools/list", token)
        await _list(client, "resources/list", token)
        assert len(counting.claims) == 2
        await cs.call_tool(client, token, "search_catalog", cs.query_args("agent"))
    assert len(counting.claims) == 3


async def test_a_revoked_policy_drops_tools_from_the_next_listing() -> None:
    harness = cs.make_harness()
    async with cs.mcp_session(harness) as client:
        token = harness.token(cs.ALICE)
        before = await _list(client, "tools/list", token)
        assert _tool_names(before) == MCP_TOOL_NAMES
        harness.api.h.repo.remove_principal(cs.CUSTOMER, principal(cs.ALICE))
        harness.clock.advance(31)  # policy cache TTL is 30 s
        after = await _list(client, "tools/list", token)
        resources = await _list(client, "resources/list", token)
    assert after["result"]["tools"] == []
    assert "neurosphere://recommendations/recent" not in _resource_uris(resources)


async def test_an_unlisted_tool_is_still_rechecked_and_denied_on_call() -> None:
    harness = cs.make_harness()
    async with cs.mcp_session(harness) as client:
        token = harness.token(cs.CAROL)
        listed = await _list(client, "tools/list", token)
        assert "draft_action" not in _tool_names(listed)
        result = await cs.call_tool(client, token, "draft_action", cs.draft_args())
    assert cs.tool_error(result)["reason"] == "permission_denied"


# -- RFC 9728 metadata: CORS preflight -----------------------------------------------------------


def test_metadata_route_answers_a_cors_preflight() -> None:
    harness = cs.make_harness()
    harness.app.include_router(build_router(), prefix=PROTECTED_RESOURCE_METADATA_PATH)
    response = harness.api.h.client.options(
        PROTECTED_RESOURCE_METADATA_PATH,
        headers={
            "Origin": "https://client.example",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "mcp-protocol-version",
        },
    )
    assert response.status_code == 204, response.text
    assert response.headers["access-control-allow-origin"] == "*"
    assert response.headers["access-control-allow-methods"] == "GET, OPTIONS"
    assert response.headers["access-control-allow-headers"] == "MCP-Protocol-Version"
    assert response.headers["access-control-max-age"] == "600"
    assert "access-control-allow-credentials" not in response.headers
    assert response.content == b""
    # The GET it precedes is unchanged.
    get = harness.api.h.client.get(PROTECTED_RESOURCE_METADATA_PATH)
    assert get.status_code == 200
    assert get.headers["access-control-allow-origin"] == "*"


def test_metadata_preflight_fails_closed_until_the_server_is_built() -> None:
    api_harness = cs.make_api()
    api_harness.h.app.include_router(build_router(), prefix=PROTECTED_RESOURCE_METADATA_PATH)
    response = api_harness.h.client.options(
        PROTECTED_RESOURCE_METADATA_PATH,
        headers={"Origin": "https://client.example", "Access-Control-Request-Method": "GET"},
    )
    assert response.status_code == 503
    assert response.json()["reason"] == "mcp_unconfigured"


def test_metadata_route_still_refuses_writes() -> None:
    harness = cs.make_harness()
    harness.app.include_router(build_router(), prefix=PROTECTED_RESOURCE_METADATA_PATH)
    response = harness.api.h.client.post(PROTECTED_RESOURCE_METADATA_PATH, json={})
    assert response.status_code == 405


# -- derived idempotency key: time window, intent hash unchanged ---------------------------------


def _args() -> DraftActionArgs:
    return DraftActionArgs.model_validate(cs.draft_args())


def test_derived_key_is_stable_within_a_window_and_changes_across_windows() -> None:
    start = datetime(2026, 11, 5, 10, 0, tzinfo=UTC)
    window = timedelta(seconds=DERIVED_KEY_WINDOW_SECONDS)
    first = _derived_idempotency_key(_args(), start)
    assert _derived_idempotency_key(_args(), start + window - timedelta(seconds=1)) == first
    assert _derived_idempotency_key(_args(), start + window) != first
    assert _derived_idempotency_key(_args(), start + timedelta(days=1)) != first
    assert first.startswith("mcp-") and len(first) == 4 + 32
    # A naive clock reading is treated as UTC, never as local time.
    assert _derived_idempotency_key(_args(), start.replace(tzinfo=None)) == first


async def test_redrafting_later_is_a_new_intent_with_the_same_intent_hash() -> None:
    harness = cs.make_harness()
    async with cs.mcp_session(harness) as client:
        token = harness.token(cs.ALICE)
        [first] = cs.records(await cs.call_tool(client, token, "draft_action", cs.draft_args()))
        [retry] = cs.records(await cs.call_tool(client, token, "draft_action", cs.draft_args()))
        harness.clock.advance(DERIVED_KEY_WINDOW_SECONDS + 1)
        [later] = cs.records(await cs.call_tool(client, token, "draft_action", cs.draft_args()))
    # A retry inside the window collapses into the first draft (idempotent).
    assert first["data"]["created"] is True
    assert retry["data"]["created"] is False
    assert retry["data"]["intent_id"] == first["data"]["intent_id"]
    # The same change drafted in a later window is a new intent ...
    assert later["data"]["created"] is True
    assert later["data"]["intent_id"] != first["data"]["intent_id"]
    first_key = first["data"]["action"]["intent"]["idempotency_key"]
    later_key = later["data"]["action"]["intent"]["idempotency_key"]
    assert first_key != later_key
    # ... whose intent hash (surface independent, excludes the idempotency key) is unchanged.
    assert later["data"]["intent_hash"] == first["data"]["intent_hash"]


async def test_a_caller_supplied_key_is_used_verbatim_without_a_time_window() -> None:
    harness = cs.make_harness()
    args = {**cs.draft_args(), "idempotency_key": "caller-key-0000000001"}
    async with cs.mcp_session(harness) as client:
        token = harness.token(cs.ALICE)
        [first] = cs.records(await cs.call_tool(client, token, "draft_action", args))
        harness.clock.advance(DERIVED_KEY_WINDOW_SECONDS + 1)
        [later] = cs.records(await cs.call_tool(client, token, "draft_action", args))
    assert first["data"]["action"]["intent"]["idempotency_key"] == "caller-key-0000000001"
    assert later["data"]["created"] is False
    assert later["data"]["intent_id"] == first["data"]["intent_id"]
