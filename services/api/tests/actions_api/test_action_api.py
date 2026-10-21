"""Action API (PRP-17 item 4): lifecycle, idempotency, binding, maker-checker, fail closed."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from action_plane_harness import (  # pyright: ignore[reportMissingImports]
    ALICE,
    BOB,
    CAROL,
    CUSTOMER,
    DAVE,
    OPERATIONS,
    TARGET_VERSION,
    Api,
    draft_body,
    make_api,
    principal,
    problem,
)
from neurosphere_api.actions import ActionApiSettings, ActionKindPolicy
from neurosphere_api.authz import route_inventory, undeclared_routes
from neurosphere_core.actions import compute_confirmation_hash
from neurosphere_core.actions.models import parse_timestamp
from neurosphere_core.errors import DependencyTransientError

OTHER_HASH = "sha256:" + "0" * 64


def _hash(view: dict[str, Any]) -> str:
    value = view["intent"]["confirmation_hash"]
    assert isinstance(value, str)
    return value


def _id(view: dict[str, Any]) -> str:
    return view["intent"]["intent_id"]


def _approve(api: Api, view: dict[str, Any], who: str = BOB, decision: str = "approved") -> Any:
    return api.step(
        who,
        _id(view),
        "decisions",
        {"decision": decision, "reason": "checked the diff", "confirmation_hash": _hash(view)},
    )


def _no_principal_ids(api: Api) -> None:
    for who in (ALICE, BOB, CAROL, DAVE):
        real = principal(who)
        for text in api.all_text():
            assert real not in text
            assert who not in text


# -- lifecycle ----------------------------------------------------------------------------------


def test_full_lifecycle_reaches_executing_through_maker_checker() -> None:
    api = make_api()
    drafted = api.drafted()
    assert drafted["intent"]["state"] == "drafted"
    assert drafted["intent"]["channel"] == "rest"
    assert drafted["advisory"] is False and drafted["requires_approval"] is True
    assert drafted["self_approval_forbidden"] is True and drafted["execution"] is None

    validated = api.step(ALICE, _id(drafted), "validate").json()
    assert validated["intent"]["state"] == "validated"
    checks = {c["check_id"]: c["status"] for c in validated["intent"]["prerequisite_results"]}
    assert checks == {
        "actor_permission": "passed",
        "approval_policy": "passed",
        "diff_well_formed": "passed",
        "write_connector_supported": "passed",
        "target_dry_run": "passed",
    }

    presented = api.step(ALICE, _id(drafted), "confirmation").json()
    intent = presented["intent"]
    assert intent["state"] == "awaiting_confirmation"
    assert _hash(presented) == compute_confirmation_hash(intent)
    created = parse_timestamp(intent["created_at"])
    lifetime = parse_timestamp(intent["confirmation_expires_at"]) - created
    assert 23 * 3600 < lifetime.total_seconds() <= 24 * 3600 + 1  # approval TTL, not 15 min

    confirmed = api.step(
        ALICE, _id(drafted), "confirm", {"confirmation_hash": _hash(presented)}
    ).json()
    assert confirmed["intent"]["state"] == "awaiting_approval"
    item_id = confirmed["review_item_id"]
    assert isinstance(item_id, str)

    decided = _approve(api, presented)
    assert decided.status_code == 200, decided.text
    assert decided.json()["intent"]["state"] == "executing"
    assert decided.json()["execution"]["phase"] == "pending"
    item = asyncio.run(api.hitl.get(item_id))
    assert item is not None and item.state_name == "approved"
    status = api.get_intent(_id(drafted), who=CAROL).json()
    assert status["intent"]["state"] == "executing"
    # The API probed with dry_run only; the executor worker applies, never the API.
    assert api.connector.dry_runs and api.connector.forbidden_calls == []
    _no_principal_ids(api)


def test_no_approval_kind_goes_straight_to_executing() -> None:
    settings = ActionApiSettings(
        action_kinds={"model_deployment_swap": ActionKindPolicy(requires_approval=False)}
    )
    api = make_api(settings=settings)
    view = api.presented()
    lifetime = parse_timestamp(view["intent"]["confirmation_expires_at"]) - parse_timestamp(
        view["intent"]["created_at"]
    )
    assert lifetime.total_seconds() <= 15 * 60 + 1
    done = api.step(ALICE, _id(view), "confirm", {"confirmation_hash": _hash(view)}).json()
    assert done["intent"]["state"] == "executing"
    assert done["requires_approval"] is False and done["review_item_id"] is None


def test_rejection_fails_the_intent_and_closes_the_item() -> None:
    api = make_api()
    view = api.awaiting_approval()
    rejected = _approve(api, view, decision="rejected")
    assert rejected.status_code == 200, rejected.text
    body = rejected.json()
    assert body["intent"]["state"] == "failed"
    assert body["intent"]["status_reason"] == "approval_rejected"
    item = asyncio.run(api.hitl.get(view["review_item_id"]))
    assert item is not None and item.state_name == "rejected"


def test_list_intents_by_state() -> None:
    api = make_api()
    first = api.validated()
    api.drafted(key="idem-2026-10-20-chat-prod-0002", new_version="2026-07-01")
    listed = api.call("GET", CAROL, api.intents_path(), params={"state": "validated"}).json()
    assert [v["intent"]["intent_id"] for v in listed["items"]] == [_id(first)]
    assert listed["next_cursor"] is None


# -- idempotency --------------------------------------------------------------------------------


def test_replay_returns_the_original_intent_with_200() -> None:
    api = make_api()
    first = api.draft()
    assert first.status_code == 201
    again = api.draft()
    assert again.status_code == 200
    assert again.json()["intent"] == first.json()["intent"]
    # Channel is metadata only: the same change retried from a button is the same request.
    button = api.draft(channel="button")
    assert button.status_code == 200
    assert button.json()["intent"]["intent_id"] == _id(first.json())


def test_idempotency_key_reuse_with_another_payload_is_invalid_schema() -> None:
    api = make_api()
    api.drafted()
    reused = api.draft(new_version="2027-01-01")
    assert reused.status_code == 422
    body = problem(reused)
    assert body["code"] == "invalid_schema" and body["reason"] == "idempotency_key_reused"


def test_body_cannot_carry_identity_or_scope() -> None:
    api = make_api()
    body = draft_body()
    body["actor"] = {"principal_pseudonym": "p-x", "principal_kind": "user", "on_behalf_of": None}
    assert api.draft(body=body).status_code == 422
    body = draft_body()
    body["customer_id"] = "fabrikam"
    assert api.draft(body=body).status_code == 422


# -- confirmation binding -----------------------------------------------------------------------


def test_expired_confirmation_is_stale_version() -> None:
    api = make_api()
    view = api.presented()
    api.h.clock.advance(25 * 3600)
    late = api.step(ALICE, _id(view), "confirm", {"confirmation_hash": _hash(view)})
    assert late.status_code == 409
    body = problem(late)
    assert body["code"] == "stale_version" and body["reason"] == "confirmation_expired"
    assert api.get_intent(_id(view)).json()["intent"]["state"] == "expired"


def test_changed_target_version_fails_the_intent() -> None:
    api = make_api()
    view = api.presented()
    api.connector.current_version = "etag-moved-on"
    stale = api.step(ALICE, _id(view), "confirm", {"confirmation_hash": _hash(view)})
    assert stale.status_code == 409
    body = problem(stale)
    assert body["code"] == "stale_version" and body["reason"] == "target_version_changed"
    current = api.get_intent(_id(view)).json()["intent"]
    assert current["state"] == "failed" and current["status_reason"] == "target_version_changed"


def test_changed_target_at_validation_fails_the_check() -> None:
    api = make_api()
    drafted = api.drafted()
    api.connector.current_version = "etag-moved-on"
    view = api.step(ALICE, _id(drafted), "validate").json()
    assert view["intent"]["state"] == "failed"
    checks = {c["check_id"]: c for c in view["intent"]["prerequisite_results"]}
    assert checks["target_dry_run"]["status"] == "failed"
    assert checks["target_dry_run"]["detail"] == "target_version_changed"


def test_hash_mismatch_refuses_without_state_change() -> None:
    api = make_api()
    view = api.presented()
    bad = api.step(ALICE, _id(view), "confirm", {"confirmation_hash": OTHER_HASH})
    assert bad.status_code == 422
    body = problem(bad)
    assert body["code"] == "invalid_schema" and body["reason"] == "confirmation_hash_mismatch"
    assert api.get_intent(_id(view)).json()["intent"]["state"] == "awaiting_confirmation"


def test_non_maker_cannot_confirm_and_triggers_no_probe() -> None:
    api = make_api()
    view = api.presented()
    probes = len(api.connector.dry_runs)
    other = api.step(BOB, _id(view), "confirm", {"confirmation_hash": _hash(view)})
    assert other.status_code == 403
    assert problem(other)["reason"] == "not_maker"
    assert len(api.connector.dry_runs) == probes
    assert api.get_intent(_id(view)).json()["intent"]["state"] == "awaiting_confirmation"


def test_non_maker_cannot_validate_or_present() -> None:
    api = make_api()
    drafted = api.drafted()
    assert problem(api.step(BOB, _id(drafted), "validate"))["reason"] == "not_maker"
    api.step(ALICE, _id(drafted), "validate")
    assert problem(api.step(BOB, _id(drafted), "confirmation"))["reason"] == "not_maker"


# -- advisory -----------------------------------------------------------------------------------


def test_advisory_intent_is_reviewable_but_never_confirms_or_approves() -> None:
    api = make_api(with_connector=False)
    validated = api.validated()
    assert validated["intent"]["state"] == "validated" and validated["advisory"] is True
    checks = {c["check_id"]: c["status"] for c in validated["intent"]["prerequisite_results"]}
    assert checks["write_connector_supported"] == "warning"
    assert checks["target_dry_run"] == "not_applicable"
    view = api.step(ALICE, _id(validated), "confirmation").json()
    replaces = api.intents.replace_calls

    confirm = api.step(ALICE, _id(view), "confirm", {"confirmation_hash": _hash(view)})
    assert confirm.status_code == 409
    body = problem(confirm)
    assert body["code"] == "capability_unavailable" and body["reason"] == "advisory_connector"
    approve = _approve(api, view)
    assert approve.status_code == 409
    assert problem(approve)["reason"] == "advisory_connector"
    # Nothing changed anywhere: no intent write, no review item, no connector call.
    assert api.intents.replace_calls == replaces
    assert api.get_intent(_id(view)).json()["intent"]["state"] == "awaiting_confirmation"
    assert asyncio.run(api.hitl_store.due(parse_timestamp("2099-01-01T00:00:00Z"))) == []
    assert api.connector.dry_runs == [] and api.connector.forbidden_calls == []


def test_unknown_action_kind_is_advisory() -> None:
    api = make_api()
    view = api.validated(kind="budget_cap_change")
    assert view["advisory"] is True and view["requires_approval"] is True


# -- maker-checker ------------------------------------------------------------------------------


def test_maker_cannot_approve_their_own_change() -> None:
    api = make_api()
    view = api.awaiting_approval()
    own = _approve(api, view, who=ALICE)
    assert own.status_code == 403
    assert problem(own)["reason"] == "self_approval_forbidden"
    assert api.get_intent(_id(view)).json()["intent"]["state"] == "awaiting_approval"


def test_viewer_approve_is_403_problem_json() -> None:
    api = make_api()
    view = api.awaiting_approval()
    viewer = _approve(api, view, who=CAROL)
    assert viewer.status_code == 403
    body = problem(viewer)
    assert body["code"] == "forbidden"
    assert api.get_intent(_id(view)).json()["intent"]["state"] == "awaiting_approval"


def test_approval_rechecks_the_current_target_version() -> None:
    api = make_api()
    view = api.awaiting_approval()
    api.connector.current_version = "etag-moved-on"
    late = _approve(api, view)
    assert late.status_code == 409
    assert problem(late)["reason"] == "target_version_changed"
    assert api.get_intent(_id(view)).json()["intent"]["state"] == "failed"
    item = asyncio.run(api.hitl.get(view["review_item_id"]))
    assert item is not None and item.state_name == "failed"


def test_approval_with_wrong_hash_is_refused() -> None:
    api = make_api()
    view = api.awaiting_approval()
    wrong = api.step(
        BOB,
        _id(view),
        "decisions",
        {"decision": "approved", "reason": "ok", "confirmation_hash": OTHER_HASH},
    )
    assert wrong.status_code == 422
    assert problem(wrong)["reason"] == "confirmation_hash_mismatch"


def test_outage_after_decision_resumes_on_resend() -> None:
    api = make_api()
    view = api.awaiting_approval()
    api.connector.error = DependencyTransientError("arm down", reason="arm_unavailable")
    failed = _approve(api, view)
    assert failed.status_code == 503
    assert api.get_intent(_id(view)).json()["intent"]["state"] == "awaiting_approval"
    api.connector.error = None
    # Another reviewer cannot ride on Bob's recorded approval.
    steal = api.step(
        CAROL,
        _id(view),
        "decisions",
        {"decision": "approved", "reason": "x", "confirmation_hash": _hash(view)},
    )
    assert steal.status_code == 403
    resumed = _approve(api, view)
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["intent"]["state"] == "executing"
    decisions = asyncio.run(api.hitl.decisions(view["review_item_id"]))
    assert len(decisions) == 1


# -- fail closed --------------------------------------------------------------------------------


def test_policy_store_outage_at_recheck_is_503() -> None:
    api = make_api()
    view = api.presented()
    api.rechecker.fail_with(RuntimeError("policy store down"))
    down = api.step(ALICE, _id(view), "confirm", {"confirmation_hash": _hash(view)})
    assert down.status_code == 503
    body = problem(down)
    assert body["code"] == "dependency_transient" and body["reason"] == "policy_store_unavailable"
    api.rechecker.fail_with(None)
    assert api.get_intent(_id(view)).json()["intent"]["state"] == "awaiting_confirmation"


def test_policy_store_outage_at_validation_leaves_intent_drafted() -> None:
    api = make_api()
    drafted = api.drafted()
    api.rechecker.fail_with(RuntimeError("policy store down"))
    assert api.step(ALICE, _id(drafted), "validate").status_code == 503
    api.rechecker.fail_with(None)
    assert api.get_intent(_id(drafted)).json()["intent"]["state"] == "drafted"


def test_scope_policy_store_outage_is_503() -> None:
    api = make_api()
    api.h.repo.fail_with(RuntimeError("cosmos down"))
    down = api.draft()
    assert down.status_code == 503
    assert problem(down)["code"] == "dependency_transient"


def test_out_of_scope_domain_is_403() -> None:
    api = make_api()
    response = api.draft(domain=OPERATIONS)
    assert response.status_code == 403
    assert problem(response)["code"] == "forbidden"
    assert api.call("GET", ALICE, api.intents_path(OPERATIONS)).status_code == 403


def test_viewer_cannot_draft_and_unknown_intent_is_404() -> None:
    api = make_api()
    assert api.draft(who=CAROL).status_code == 403
    missing = api.get_intent("00000000-0000-4000-8000-999999999999")
    assert missing.status_code == 404


def test_every_action_and_review_route_declares_a_permission() -> None:
    api = make_api()
    entries = [
        e
        for e in route_inventory(api.h.app)
        if e.path.startswith(("/api/v1/actions", "/api/v1/review"))
    ]
    assert len(entries) == 13
    assert undeclared_routes(api.h.app) == ()
    declared = {(e.path, e.methods): e.permissions for e in entries}
    intent = "/api/v1/actions/domains/{domain}/intents/{intent_id}"
    assert declared[(f"{intent}/confirm", ("POST",))] == ("action.execute",)
    assert declared[(f"{intent}/decisions", ("POST",))] == ("action.approve",)
    assert declared[("/api/v1/actions/emergency-disable", ("PUT",))] == ("config.manage",)


def test_unconfigured_action_plane_is_503() -> None:
    api = make_api(wire=False)
    response = api.draft()
    assert response.status_code == 503
    assert problem(response)["reason"] == "action_plane_unconfigured"


# -- emergency disable --------------------------------------------------------------------------


def test_emergency_disable_read_and_change() -> None:
    api = make_api()
    assert api.call("GET", CAROL, "/emergency-disable").json()["disabled"] is False
    body = {"disabled": True, "reason": "incident_inc_42"}
    assert api.call("PUT", CAROL, "/emergency-disable", json=body).status_code == 403
    changed = api.call("PUT", DAVE, "/emergency-disable", json=body)
    assert changed.status_code == 200, changed.text
    state = changed.json()
    assert state["disabled"] is True and state["reason"] == "incident_inc_42"
    assert state["changed_by"] and state["changed_by"] != principal(DAVE)
    records = asyncio.run(api.audit.read_range(f"{CUSTOMER}.execution-control", start=0))
    assert [r.kind for r in records] == ["before", "after"]
    assert api.call("PUT", DAVE, "/emergency-disable", json={"disabled": True}).status_code == 422
    _no_principal_ids(api)


def test_emergency_disable_blocks_execution_and_records_no_decision() -> None:
    settings = ActionApiSettings(
        action_kinds={"model_deployment_swap": ActionKindPolicy(requires_approval=False)}
    )
    api = make_api(settings=settings)
    view = api.presented()
    api.call("PUT", DAVE, "/emergency-disable", json={"disabled": True, "reason": "drill"})
    blocked = api.step(ALICE, _id(view), "confirm", {"confirmation_hash": _hash(view)})
    assert blocked.status_code == 409
    assert problem(blocked)["reason"] == "emergency_disabled"

    approval = make_api()
    pending = approval.awaiting_approval()
    approval.call("PUT", DAVE, "/emergency-disable", json={"disabled": True, "reason": "drill"})
    refused = _approve(approval, pending)
    assert refused.status_code == 409 and problem(refused)["reason"] == "emergency_disabled"
    assert asyncio.run(approval.hitl.decisions(pending["review_item_id"])) == []


def test_control_store_outage_is_503() -> None:
    api = make_api()
    api.control.fail_with(RuntimeError("control store down"))
    down = api.call("GET", CAROL, "/emergency-disable")
    assert down.status_code == 503
    assert problem(down)["reason"] == "execution_control_unavailable"


@pytest.mark.parametrize("who", [ALICE, BOB])
def test_responses_never_carry_real_principal_ids(who: str) -> None:
    api = make_api()
    view = api.awaiting_approval()
    api.call("GET", who, api.intents_path())
    api.get_intent(_id(view), who=who)
    _approve(api, view)
    assert TARGET_VERSION in next(api.all_text())
    _no_principal_ids(api)
