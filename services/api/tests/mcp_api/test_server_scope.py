"""MCP tools run under the server-derived ``IdentityScope`` (PRP-22 item 1).

* Every tool call and resource read re-derives the scope through the REST ``ScopeSource``.
* Results are filtered by that scope; a ``domain_id`` filter only narrows.
* Caller-supplied scope-shaped arguments (``domain_id``, ``customer_id``, any spelling the
  PRP-19 registry normalises) are refused and logged, never consulted (PRP-19 D6).
* Revocation is honored within the revocation TTL; a policy-store outage fails closed (503).
* Action tools draft (channel ``mcp``), validate, present confirmation and read status through
  the PRP-17 ``ActionApi``; there is no confirm, execute or approve tool (PRP-22 D5).
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import conftest_server as cs  # pyright: ignore[reportMissingImports]
import pytest
from action_plane_harness import draft_body, principal  # pyright: ignore[reportMissingImports]
from neurosphere_api.authz import configure_authz
from neurosphere_api.mcp.server import MCP_TOOL_NAMES
from neurosphere_core.actions import compute_confirmation_hash
from neurosphere_core.auth.jwt import VerifiedClaims
from neurosphere_core.auth.revocation import (
    CachedRevocationChecker,
    InMemoryRevocationStore,
    RevocationEntry,
)
from neurosphere_core.auth.scope import ScopeDerivation


def _domains(rows: list[dict[str, Any]]) -> set[str]:
    return {row["data"]["domain_id"] for row in rows}


class CountingScopeSource:
    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.claims: list[VerifiedClaims] = []

    async def derive(self, claims: VerifiedClaims) -> ScopeDerivation:
        self.claims.append(claims)
        return await self.inner.derive(claims)


# -- read tools: filtered by the derived scope ---------------------------------------------------


async def test_tools_list_is_the_mcp_allowlist_without_confirm_execute_or_approve() -> None:
    harness = cs.make_harness()
    async with cs.mcp_session(harness) as client:
        response = await cs.rpc(client, "tools/list", token=harness.token(cs.ALICE))
    assert response.status_code == 200, response.text
    tools = response.json()["result"]["tools"]
    names = sorted(t["name"] for t in tools)
    assert tuple(names) == MCP_TOOL_NAMES
    assert not [n for n in names if n.startswith(("confirm", "execute", "approve", "decide"))]
    for tool in tools:
        assert tool["inputSchema"]["type"] == "object"
        assert tool["inputSchema"].get("additionalProperties") is False
        properties = set(tool["inputSchema"].get("properties", {}))
        assert not properties & {"domain_id", "customer_id", "tenant_id", "scope"}
        text = tool["description"].lower()
        assert "discover" not in text and "complete telemetry" not in text
        assert "all telemetry" not in text


async def test_search_catalog_returns_only_domains_in_the_derived_scope() -> None:
    harness = cs.make_harness()
    async with cs.mcp_session(harness) as client:
        alice = await cs.call_tool(
            client, harness.token(cs.ALICE), "search_catalog", cs.query_args("agent")
        )
        erin = await cs.call_tool(
            client, harness.token(cs.ERIN), "search_catalog", cs.query_args("agent")
        )
    assert _domains(cs.records(alice)) == {cs.FINANCE}
    assert _domains(cs.records(erin)) == {cs.FINANCE, cs.OPERATIONS}
    assert alice["structuredContent"]["content_trust"] == "untrusted_data"


async def test_a_domain_filter_narrows_and_never_widens() -> None:
    harness = cs.make_harness()
    async with cs.mcp_session(harness) as client:
        result = await cs.call_tool(
            client,
            harness.token(cs.ALICE),
            "search_catalog",
            cs.query_args("agent", domain=cs.OPERATIONS),
        )
    assert cs.records(result) == []
    assert cs.OPERATIONS not in harness.world.domains_asked()


async def test_cost_and_recommendation_tools_are_scoped() -> None:
    harness = cs.make_harness()
    async with cs.mcp_session(harness) as client:
        token = harness.token(cs.ALICE)
        cost = await cs.call_tool(client, token, "get_cost_summary", cs.cost_args())
        recs = await cs.call_tool(
            client, token, "list_recommendations", cs.query_args("recommendation")
        )
    assert _domains(cs.records(cost)) == {cs.FINANCE}
    assert _domains(cs.records(recs)) == {cs.FINANCE}
    assert harness.world.domains_asked() == {cs.FINANCE}


async def test_every_tool_call_and_resource_read_rederives_the_scope() -> None:
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
        await cs.call_tool(client, token, "search_catalog", cs.query_args("agent"))
        await cs.call_tool(client, token, "search_catalog", cs.query_args("agent"))
        read = await cs.rpc(
            client, "resources/read", {"uri": "neurosphere://scope/current"}, token=token
        )
        assert read.status_code == 200, read.text
    assert len(counting.claims) == 3
    assert {c.audience for c in counting.claims} == {cs.MCP_AUDIENCE}


async def test_a_policy_change_applies_to_the_next_call_after_the_policy_cache_ttl() -> None:
    harness = cs.make_harness()
    async with cs.mcp_session(harness) as client:
        token = harness.token(cs.ALICE)
        first = await cs.call_tool(client, token, "search_catalog", cs.query_args("agent"))
        assert _domains(cs.records(first)) == {cs.FINANCE}
        harness.api.h.repo.remove_principal(cs.CUSTOMER, principal(cs.ALICE))
        harness.clock.advance(31)  # policy cache TTL is 30 s
        second = await cs.call_tool(client, token, "search_catalog", cs.query_args("agent"))
    error = cs.tool_error(second)
    assert (error["code"], error["status"], error["reason"]) == (
        "forbidden",
        403,
        "permission_denied",
    )


# -- caller-supplied scope arguments: refused, logged, never consulted ---------------------------


@pytest.mark.parametrize(
    "key", ["domain_id", "Domain-ID", "domainId", "customer_id", "CustomerId", "tenant", "scope"]
)
async def test_scope_shaped_arguments_are_refused_logged_and_never_consulted(
    key: str, caplog: pytest.LogCaptureFixture
) -> None:
    harness = cs.make_harness()
    arguments = {**cs.query_args("agent"), key: cs.OPERATIONS}
    with caplog.at_level(logging.INFO):
        async with cs.mcp_session(harness) as client:
            result = await cs.call_tool(
                client, harness.token(cs.ALICE), "search_catalog", arguments
            )
    error = cs.tool_error(result)
    assert (error["code"], error["reason"], error["status"]) == (
        "forbidden",
        "scope_argument_refused",
        403,
    )
    assert harness.world.domains_asked() == set()  # no port was called at all
    refused = [r for r in caplog.records if r.getMessage() == "mcp tool call refused"]
    assert refused and getattr(refused[0], "reason", None) == "scope_argument_refused"
    registry_log = [r for r in caplog.records if r.getMessage() == "copilot tool call refused"]
    assert registry_log and key in getattr(registry_log[0], "key_names", ())
    assert all(cs.OPERATIONS not in r.getMessage() for r in caplog.records)


async def test_action_tools_refuse_a_supplied_domain_too() -> None:
    harness = cs.make_harness()
    async with cs.mcp_session(harness) as client:
        result = await cs.call_tool(
            client,
            harness.token(cs.ALICE),
            "draft_action",
            {**cs.draft_args(), "domain_id": cs.OPERATIONS},
        )
    assert cs.tool_error(result)["reason"] == "scope_argument_refused"
    listed = harness.api.call("GET", cs.ALICE, harness.api.intents_path(cs.FINANCE))
    assert listed.status_code == 200 and listed.json()["items"] == []


async def test_undeclared_arguments_and_unknown_tools_are_refused() -> None:
    harness = cs.make_harness()
    async with cs.mcp_session(harness) as client:
        token = harness.token(cs.ALICE)
        extra = await cs.call_tool(
            client, token, "search_catalog", {**cs.query_args("agent"), "sql": "1"}
        )
        unknown = await cs.call_tool(client, token, "confirm_action", {"intent_id": "x"})
    assert cs.tool_error(extra)["reason"] == "argument_not_allowed"
    assert cs.tool_error(unknown)["reason"] == "tool_not_registered"


# -- revocation and outages ----------------------------------------------------------------------


async def test_a_revoked_principal_is_denied_within_the_revocation_ttl() -> None:
    clock_holder: dict[str, Any] = {}

    def clock() -> float:
        return clock_holder["clock"]()

    store = InMemoryRevocationStore(clock=clock)
    checker = CachedRevocationChecker(store, ttl_seconds=60, clock=clock)
    harness = cs.make_harness(revocation_checker=checker)
    clock_holder["clock"] = harness.clock
    async with cs.mcp_session(harness) as client:
        token = harness.token(cs.ALICE)
        before = await cs.call_tool(client, token, "search_catalog", cs.query_args("agent"))
        assert cs.records(before)
        await store.put(
            RevocationEntry(
                principal_id=principal(cs.ALICE),
                revoked_at=datetime.fromtimestamp(harness.clock.now, UTC) + timedelta(seconds=1),
                reason="account_compromised",
                revoked_by=principal(cs.BOB),
            )
        )
        harness.clock.advance(61)  # past the revocation TTL of the cached "not revoked" answer
        after = await cs.call_tool(client, token, "search_catalog", cs.query_args("agent"))
        status = await cs.rpc(
            client, "resources/read", {"uri": "neurosphere://scope/current"}, token=token
        )
    error = cs.tool_error(after)
    assert (error["code"], error["reason"], error["status"]) == (
        "forbidden",
        "principal_revoked",
        403,
    )
    assert status.json()["error"]["data"]["reason"] == "principal_revoked"


async def test_a_policy_store_outage_fails_closed_with_503() -> None:
    harness = cs.make_harness()
    harness.api.h.repo.fail_with(RuntimeError("cosmos down"))
    async with cs.mcp_session(harness) as client:
        result = await cs.call_tool(
            client, harness.token(cs.ALICE), "search_catalog", cs.query_args("agent")
        )
    error = cs.tool_error(result)
    assert (error["code"], error["status"]) == ("dependency_transient", 503)
    assert harness.world.domains_asked() == set()
    assert "cosmos down" not in json.dumps(result)


async def test_unconfigured_authz_or_ports_fail_closed() -> None:
    harness = cs.make_harness(bind_ports=False)
    async with cs.mcp_session(harness) as client:
        token = harness.token(cs.ALICE)
        unbound = await cs.call_tool(client, token, "search_catalog", cs.query_args("agent"))
        delattr(harness.app.state, "authz")
        no_authz = await cs.call_tool(client, token, "search_catalog", cs.query_args("agent"))
    assert cs.tool_error(unbound)["reason"] == "mcp_unconfigured"
    assert cs.tool_error(no_authz)["reason"] == "authz_unconfigured"


# -- action tools through the PRP-17 action API --------------------------------------------------


async def test_draft_validate_present_and_status_use_the_action_api_with_channel_mcp() -> None:
    harness = cs.make_harness()
    async with cs.mcp_session(harness) as client:
        token = harness.token(cs.ALICE)
        drafted = cs.records(await cs.call_tool(client, token, "draft_action", cs.draft_args()))
        [draft] = drafted
        data = draft["data"]
        intent_id = data["intent_id"]
        assert data["state"] == "drafted" and data["domain_id"] == cs.FINANCE
        assert data["action"]["intent"]["channel"] == "mcp"
        assert data["target_version"] == cs.TARGET_VERSION
        assert data["proposed_diff"]["format"] == "json_patch"
        assert data["intent_hash"].startswith("sha256:")
        assert data["confirmation_hash"] is None and data["next_step"] == "validate_action"
        assert data["confirmed_by"] == "human_in_ui_or_rest"

        [validated] = cs.records(
            await cs.call_tool(client, token, "validate_action", {"intent_id": intent_id})
        )
        assert validated["data"]["state"] == "validated"
        [presented] = cs.records(
            await cs.call_tool(
                client, token, "present_action_confirmation", {"intent_id": intent_id}
            )
        )
        bound = presented["data"]
        assert bound["state"] == "awaiting_confirmation"
        assert bound["confirmation_hash"].startswith("sha256:")
        assert bound["confirmation_expires_at"]
        assert bound["next_step"] == "human_confirms_in_ui_or_rest"
        assert bound["confirm_path"].endswith(f"/intents/{intent_id}/confirm")

        [status] = cs.records(
            await cs.call_tool(
                client, harness.token(cs.CAROL), "get_action_status", {"intent_id": intent_id}
            )
        )
        assert status["data"]["state"] == "awaiting_confirmation"

    # Never confirmed or executed by MCP: the API only dry-ran; a human confirms via REST.
    assert harness.api.connector.forbidden_calls == []
    rest = harness.api.get_intent(intent_id)
    assert rest.status_code == 200 and rest.json()["intent"]["state"] == "awaiting_confirmation"
    assert rest.json()["intent"]["confirmation_hash"] == bound["confirmation_hash"]
    confirmed = harness.api.step(
        cs.ALICE, intent_id, "confirm", {"confirmation_hash": bound["confirmation_hash"]}
    )
    assert confirmed.status_code == 200, confirmed.text


async def test_an_mcp_draft_hashes_like_the_rest_draft_of_the_same_change() -> None:
    harness = cs.make_harness()
    async with cs.mcp_session(harness) as client:
        [draft] = cs.records(
            await cs.call_tool(client, harness.token(cs.ALICE), "draft_action", cs.draft_args())
        )
    body = draft_body(key="idem-rest-same-change-0001", target_id=cs.TARGET)
    body["target"] = {"canonical_id": cs.TARGET, "entity_type": "agent"}
    rest = harness.api.draft(cs.ALICE, body)
    assert rest.status_code == 201, rest.text
    assert compute_confirmation_hash(rest.json()["intent"]) == draft["data"]["intent_hash"]


async def test_action_tools_recheck_permission_and_maker_rules() -> None:
    harness = cs.make_harness()
    async with cs.mcp_session(harness) as client:
        viewer = await cs.call_tool(
            client, harness.token(cs.CAROL), "draft_action", cs.draft_args()
        )
        outside = await cs.call_tool(
            client, harness.token(cs.ALICE), "draft_action", cs.draft_args(cs.OPS_TARGET)
        )
        [draft] = cs.records(
            await cs.call_tool(client, harness.token(cs.ALICE), "draft_action", cs.draft_args())
        )
        intent_id = draft["data"]["intent_id"]
        not_maker = await cs.call_tool(
            client, harness.token(cs.BOB), "validate_action", {"intent_id": intent_id}
        )
        invisible = await cs.call_tool(
            client, harness.token(cs.ERIN), "validate_action", {"intent_id": intent_id}
        )
    assert cs.tool_error(viewer)["reason"] == "permission_denied"
    assert cs.tool_error(outside)["reason"] == "target_out_of_scope"
    assert cs.tool_error(not_maker)["code"] == "forbidden"
    assert cs.tool_error(invisible)["code"] == "not_found"


async def test_draft_without_an_action_plane_fails_closed() -> None:
    harness = cs.make_harness(action_plane=False)
    async with cs.mcp_session(harness) as client:
        result = await cs.call_tool(
            client, harness.token(cs.ALICE), "draft_action", cs.draft_args()
        )
    error = cs.tool_error(result)
    assert (error["status"], error["reason"]) == (503, "action_plane_unconfigured")


# -- resources -----------------------------------------------------------------------------------


async def test_resources_are_scoped_and_make_no_discovery_or_telemetry_claims() -> None:
    harness = cs.make_harness()
    async with cs.mcp_session(harness) as client:
        token = harness.token(cs.ALICE)
        listed = await cs.rpc(client, "resources/list", token=token)
        scope = await cs.rpc(
            client, "resources/read", {"uri": "neurosphere://scope/current"}, token=token
        )
        recs = await cs.rpc(
            client, "resources/read", {"uri": "neurosphere://recommendations/recent"}, token=token
        )
        about = await cs.rpc(
            client, "resources/read", {"uri": "neurosphere://mcp/about"}, token=token
        )
        unknown = await cs.rpc(
            client, "resources/read", {"uri": "neurosphere://scope/other"}, token=token
        )
    uris = {r["uri"] for r in listed.json()["result"]["resources"]}
    assert uris == {
        "neurosphere://mcp/about",
        "neurosphere://scope/current",
        "neurosphere://recommendations/recent",
    }
    summary = json.loads(scope.json()["result"]["contents"][0]["text"])
    assert summary["readable_domains"] == [cs.FINANCE]
    assert summary["proposable_domains"] == [cs.FINANCE]
    assert summary["customer_id"] == cs.CUSTOMER
    rec_rows = json.loads(recs.json()["result"]["contents"][0]["text"])["records"]
    assert {r["data"]["domain_id"] for r in rec_rows} == {cs.FINANCE}
    text = about.json()["result"]["contents"][0]["text"]
    assert "does not discover" in text and "does not provide complete telemetry" in text
    assert "error" in unknown.json()
