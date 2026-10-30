"""Gateway mode switch API (PRP-34 item 2): drafts an audited action intent, never flips itself.

Covers: draft shape and replay, authorization (two permissions on the gateway's domain), audit
before/after on the gateway chain, refusals (unchanged, Government, busy), the preflight result
surfacing at validate (pass and denied write), the observe-mode refusal of APIM plans in the
action plane's connector resolution, and that a mode request never reaches ARM.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from gateway_mode_harness import (  # pyright: ignore[reportMissingImports]
    ACTIONS,
    ADMIN,
    CUSTOMER,
    FINANCE,
    GATEWAY_ID,
    GATEWAYS,
    OPERATIONS,
    OPERATOR,
    OUTSIDER,
    STEWARD,
    VIEWER,
    make_mode_env,
    manage_fields,
    problem,
    registration,
)
from neurosphere_core.paging import Page

READER: list[dict[str, Any]] = [{"actions": ["*/read"], "notActions": []}]


def _checks(view: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {c["check_id"]: c for c in view["intent"]["prerequisite_results"]}


# -- draft --------------------------------------------------------------------------------------


def test_operator_drafts_a_gateway_mode_change_intent() -> None:
    env = make_mode_env()
    response = env.mode(OPERATOR, "manage")
    assert response.status_code == 201, response.text
    intent = response.json()["intent"]
    assert intent["action_kind"] == "gateway_mode_change"
    assert intent["state"] == "drafted"
    assert intent["target"] == {
        "canonical_id": f"commercial:contoso:apim:apim_gateway_mode:{GATEWAY_ID}",
        "entity_type": "apim_gateway_mode",
    }
    assert intent["target_version"] == "mode-r0-observe"
    ops = intent["proposed_diff"]["operations"]
    assert ops[0] == {"op": "replace", "path": "/mode", "value": "manage"}
    assert ops[1]["path"] == "/mode_changed_by"
    assert ops[1]["value"] == intent["actor"]["principal_pseudonym"]
    assert response.json()["advisory"] is False
    # Drafting changes nothing: the registration is still observe and ARM was never called.
    assert env.current().mode == "observe"
    assert env.apim.calls == []
    # Same intent through the action API (the one plane).
    listed = env.call("GET", OPERATOR, f"{ACTIONS}/domains/{FINANCE}/intents")
    assert [i["intent"]["intent_id"] for i in listed.json()["items"]] == [intent["intent_id"]]


def test_replay_returns_the_original_intent() -> None:
    env = make_mode_env()
    first = env.mode(OPERATOR, "manage")
    again = env.mode(OPERATOR, "manage")
    assert first.status_code == 201
    assert again.status_code == 200
    assert again.json()["intent"]["intent_id"] == first.json()["intent"]["intent_id"]


def test_mode_request_is_audited_before_and_after() -> None:
    env = make_mode_env()
    assert env.mode(OPERATOR, "manage").status_code == 201
    records = env.audit_records()
    assert [r.kind for r in records] == ["before", "after"]
    assert {r.operation for r in records} == {"gateway.mode_change"}
    assert records[1].outcome is not None
    assert records[1].outcome.result == "succeeded"
    assert records[1].outcome.detail == "drafted:mode=manage"
    dumped = json.dumps([r.model_dump(mode="json") for r in records])
    assert GATEWAY_ID in dumped
    assert "/subscriptions/" not in dumped


def test_refusals_are_audited_as_failed() -> None:
    env = make_mode_env()
    refused = env.mode(OPERATOR, "observe")
    assert refused.status_code == 422
    assert problem(refused)["reason"] == "gateway_mode_unchanged"
    records = env.audit_records()
    assert [r.kind for r in records] == ["before", "after"]
    assert records[1].outcome.result == "failed"
    assert records[1].outcome.detail == "gateway_mode_unchanged"


# -- authorization ------------------------------------------------------------------------------


def test_steward_holding_action_propose_can_draft() -> None:
    env = make_mode_env()
    drafted = env.mode(STEWARD, "manage")
    assert drafted.status_code == 201, drafted.text
    assert drafted.json()["intent"]["action_kind"] == "gateway_mode_change"


def test_viewer_admin_alone_and_other_domains_cannot_draft() -> None:
    env = make_mode_env()
    for who in (VIEWER, ADMIN):
        denied = env.mode(who, "manage")
        assert denied.status_code == 403, (who, denied.text)
    # Right permissions, wrong domain scope: the gateway's domain is the authorization target.
    outside = env.mode(OUTSIDER, "manage")
    assert outside.status_code == 403
    assert env.mode(None, "manage").status_code == 401
    # Path domain the caller DOES hold, but the gateway is registered elsewhere: not found.
    misplaced = env.mode(OUTSIDER, "manage", domain=OPERATIONS)
    assert misplaced.status_code == 404
    assert env.audit_records() == []
    listed = env.call("GET", OPERATOR, f"{ACTIONS}/domains/{FINANCE}/intents")
    assert listed.json()["items"] == []


def test_body_cannot_smuggle_identity_or_target() -> None:
    env = make_mode_env()
    for extra in ({"customer_id": "fabrikam"}, {"target_version": "x"}, {"actor": {}}):
        assert env.mode(OPERATOR, "manage", **extra).status_code == 422
    assert env.mode(OPERATOR, "admin").status_code == 422
    bad = env.mode(OPERATOR, "manage", gateway_id="gw-nope")
    assert bad.status_code == 422


def test_unknown_gateway_is_404() -> None:
    env = make_mode_env()
    assert env.mode(OPERATOR, "manage", gateway_id="gw-" + "f" * 32).status_code == 404


# -- refusals -----------------------------------------------------------------------------------


def test_government_profile_refuses_manage_with_a_reason() -> None:
    env = make_mode_env(seed=registration(cloud="government"))
    refused = env.mode(OPERATOR, "manage")
    assert refused.status_code == 409
    body = problem(refused)
    assert body["code"] == "capability_unavailable"
    assert body["reason"] == "gateway_manage_unavailable"
    assert body["detail"]
    assert env.current().mode == "observe"


def test_mode_change_is_refused_while_an_apim_action_is_executing() -> None:
    env = make_mode_env()
    executing = SimpleNamespace(
        intent=SimpleNamespace(
            action_kind="grant_unpublish",
            target=SimpleNamespace(entity_type="grant"),
        )
    )
    seen: list[str | None] = []

    async def listing(customer_id: str, domain_id: str, **kw: Any) -> Page[Any]:
        seen.append(kw.get("state"))
        return Page[Any](items=(executing,), next_cursor=None)

    env.intents.list = listing  # type: ignore[method-assign]
    refused = env.mode(OPERATOR, "manage")
    assert refused.status_code == 409
    assert problem(refused)["reason"] == "gateway_applying"
    assert seen == ["executing"]


def test_executing_non_apim_actions_do_not_block() -> None:
    env = make_mode_env()
    foundry = SimpleNamespace(
        intent=SimpleNamespace(
            action_kind="model_deployment_swap",
            target=SimpleNamespace(entity_type="model_deployment"),
        )
    )

    async def listing(customer_id: str, domain_id: str, **kw: Any) -> Page[Any]:
        return Page[Any](items=(foundry,), next_cursor=None)

    env.intents.list = listing  # type: ignore[method-assign]
    assert env.mode(OPERATOR, "manage").status_code == 201


# -- validate: the preflight through the one executor path ----------------------------------------


def test_validate_runs_the_preflight_and_passes() -> None:
    env = make_mode_env()
    intent_id = env.mode(OPERATOR, "manage").json()["intent"]["intent_id"]
    validated = env.step(OPERATOR, intent_id, "validate")
    assert validated.status_code == 200, validated.text
    view = validated.json()
    assert view["intent"]["state"] == "validated"
    assert _checks(view)["target_dry_run"]["status"] == "passed"
    assert _checks(view)["write_connector_supported"]["status"] == "passed"
    assert [c.path for c in env.apim.calls] == ["providers/Microsoft.Authorization/permissions"]
    assert env.apim.writes() == []
    assert env.current().mode == "observe"  # only the executor flips it


def test_validate_with_a_denied_write_fails_the_preflight() -> None:
    env = make_mode_env(permissions=READER)
    intent_id = env.mode(OPERATOR, "manage").json()["intent"]["intent_id"]
    view = env.step(OPERATOR, intent_id, "validate").json()
    assert view["intent"]["state"] == "failed"
    check = _checks(view)["target_dry_run"]
    assert check["status"] == "failed"
    assert check["detail"] == "gateway_preflight_failed"
    assert env.current().mode == "observe"


def test_switching_back_to_observe_drafts_without_touching_the_gateway() -> None:
    env = make_mode_env(seed=registration(**manage_fields()))
    response = env.mode(OPERATOR, "observe")
    assert response.status_code == 201, response.text
    assert response.json()["intent"]["target_version"] == "mode-r1-manage"
    intent_id = response.json()["intent"]["intent_id"]
    view = env.step(OPERATOR, intent_id, "validate").json()
    assert _checks(view)["target_dry_run"]["status"] == "passed"
    assert env.apim.calls == []  # no preflight needed to go back; nothing written


# -- observe-mode refusal in the action plane's connector resolution ----------------------------


def _resource_intent(kind: str = "grant_publish") -> dict[str, Any]:
    return {
        "action_kind": kind,
        "target": {
            "canonical_id": f"commercial:{CUSTOMER}:apim:apim_gateway:{GATEWAY_ID}",
            "entity_type": "apim_gateway",
        },
        "target_version": '"svc-1"',
        "proposed_diff": {
            "format": "json_patch",
            "operations": [
                {
                    "op": "add",
                    "path": "/resources/products~1ns-grant-g1",
                    "value": {"displayName": "Grant g1", "subscriptionRequired": True},
                }
            ],
        },
        "idempotency_key": f"idem-{kind}-0000000001",
        "channel": "rest",
    }


def test_apim_plans_are_refused_while_the_gateway_is_in_observe_mode() -> None:
    env = make_mode_env()
    drafted = env.draft_intent(_resource_intent())
    assert drafted.status_code == 201, drafted.text
    view = env.step(OPERATOR, drafted.json()["intent"]["intent_id"], "validate").json()
    check = _checks(view)["target_dry_run"]
    assert check["status"] == "failed"
    assert check["detail"] == "gateway_observe_mode"
    assert env.apim.calls == []


def test_apim_plans_run_once_the_gateway_is_in_manage_mode() -> None:
    env = make_mode_env(seed=registration(**manage_fields()))
    drafted = env.draft_intent(_resource_intent())
    view = env.step(OPERATOR, drafted.json()["intent"]["intent_id"], "validate").json()
    assert _checks(view)["target_dry_run"]["status"] == "passed", view
    assert env.apim.writes() == []  # dry_run plans, never writes


def test_apim_plans_fail_closed_without_the_gateway_registry() -> None:
    env = make_mode_env(gateway_plane=False)
    drafted = env.draft_intent(_resource_intent())
    refused = env.step(OPERATOR, drafted.json()["intent"]["intent_id"], "validate")
    assert refused.status_code == 503
    assert problem(refused)["reason"] == "gateway_plane_unconfigured"
    assert env.apim.calls == []


def test_mode_route_fails_closed_without_the_gateway_registry() -> None:
    env = make_mode_env(gateway_plane=False)
    response = env.mode(OPERATOR, "manage")
    assert response.status_code == 503
    assert problem(response)["reason"] == "gateway_plane_unconfigured"


def test_registered_gateways_start_in_observe_mode_and_register_cannot_ask_for_manage() -> None:
    env = make_mode_env()
    detail = env.call("GET", OPERATOR, f"{GATEWAYS}/domains/{FINANCE}/gateways/{GATEWAY_ID}")
    body = detail.json()
    assert body["mode"] == "observe"
    assert body["mode_revision"] == 0
    assert body["preflight"] is None
    smuggled = env.call(
        "POST",
        OPERATOR,
        f"{GATEWAYS}/domains/{FINANCE}/gateways",
        json={"arm_resource_id": registration().arm_resource_id, "mode": "manage"},
    )
    assert smuggled.status_code == 422
