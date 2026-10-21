"""PRP-17 item 7a: the in-process action-plane vertical slice (REST -> HITL -> executor -> ARM).

Unmarked, runs in CI. Everything is in memory; the connector is the real Foundry swap connector
over a scripted ARM (``httpx.MockTransport``). What this proves: the registered routes, the
maker-checker flow, the single executor path, execution-time rechecks, verify/rollback, the kill
switch, advisory refusal and Government gating work TOGETHER. What it cannot prove (G05 stays
OPEN): that real ARM accepts the documented PUT shape and that a real credential can write.
"""

from __future__ import annotations

from typing import Any

import pytest
from neurosphere_core.actions import IntentKey

from .support import (
    ALICE,
    BOB,
    CAROL,
    CHAIN,
    CUSTOMER,
    DAVE,
    FAKES,
    FINANCE,
    GOV_TARGET_ID,
    KIND,
    MismatchingArm,
    Slice,
    make_slice,
    principal,
    problem,
    run,
    swap_body,
)


def _intent_id(view: dict[str, Any]) -> str:
    return view["intent"]["intent_id"]


def _model(slice_: Slice) -> tuple[str, str]:
    model = slice_.arm.state["properties"]["model"]
    return model["name"], model["version"]


def test_the_default_app_serves_the_action_and_review_routes() -> None:
    s = make_slice()
    paths = set(s.h.app.openapi()["paths"])
    assert "/api/v1/actions/domains/{domain}/intents" in paths
    assert "/api/v1/actions/emergency-disable" in paths
    assert "/api/v1/review/domains/{domain}/items" in paths


def test_happy_path_maker_drafts_checker_approves_executor_swaps_and_verifies() -> None:
    s = make_slice()
    assert _model(s) == ("gpt-4o", "2024-08-06")
    view = s.awaiting_approval()
    assert view["intent"]["state"] == "awaiting_approval"
    assert view["requires_approval"] is True and view["advisory"] is False
    assert view["review_item_id"] is not None
    assert s.review_state(view) == "pending"
    # Validation only ever READ the target: no PUT before the executor runs.
    assert s.arm.puts == []

    approved = s.approve(view)
    assert approved.status_code == 200, approved.text
    assert approved.json()["intent"]["state"] == "executing"
    assert s.arm.puts == []  # approval is not execution
    assert s.review_state(view) == "approved"

    report = s.execute(view)
    assert (report.outcome, report.state) == ("succeeded", "succeeded")

    # Verified by read-back from the (fake) target, not by anything we wrote ourselves.
    assert _model(s) == ("gpt-4.1", "2025-04-14")
    assert len(s.arm.puts) == 1
    status = s.intent(_intent_id(view))
    assert status["intent"]["state"] == "succeeded"
    assert status["execution"] == {
        "phase": "done",
        "canary": "verify_only",
        "verify_matched": True,
        "rolled_back": False,
    }
    assert s.review_state(view) == "executed"

    # The audit chain verifies and brackets the apply with before/after records.
    verification = run(s.audit.verify(CHAIN))
    assert verification.ok, verification
    records = s.audit_records()
    exec_records = [r for r in records if r.operation == "action.execute"]
    kinds = [r.kind for r in exec_records]
    assert "before" in kinds and "after" in kinds
    assert kinds.index("before") < len(kinds) - 1 - kinds[::-1].index("after")
    assert any(
        r.kind == "after" and r.outcome is not None and r.outcome.verified for r in exec_records
    )
    assert all(r.subject is not None and r.subject.state_digest for r in exec_records)
    dumped = " ".join(r.model_dump_json() for r in records)
    assert "gpt-4.1" not in dumped and "2025-04-14" not in dumped  # diff body never audited
    # The review item's completion went through the HITL audit too.
    assert any(r.operation == "hitl.review.executed" for r in records)


def test_a_second_run_over_the_finished_intent_changes_nothing() -> None:
    s = make_slice()
    view = s.executing()
    assert s.execute(view).outcome == "succeeded"
    puts = len(s.arm.puts)
    again = s.execute(view)
    assert again.outcome == "skipped"
    assert len(s.arm.puts) == puts


def test_self_approval_by_the_maker_is_403() -> None:
    s = make_slice()
    view = s.awaiting_approval()
    own = s.approve(view, who=ALICE)
    assert own.status_code == 403
    assert problem(own)["reason"] == "self_approval_forbidden"
    assert s.intent(_intent_id(view))["intent"]["state"] == "awaiting_approval"
    assert s.arm.puts == []


def test_viewer_approve_is_403_problem_json() -> None:
    s = make_slice()
    view = s.awaiting_approval()
    viewer = s.approve(view, who=CAROL)
    assert viewer.status_code == 403
    assert problem(viewer)["code"] == "forbidden"
    assert s.intent(_intent_id(view))["intent"]["state"] == "awaiting_approval"
    assert s.review_state(view) == "pending"


@pytest.mark.parametrize("how", ["role_removed", "principal_revoked"])
def test_permission_revoked_between_approval_and_execution_blocks_the_executor(how: str) -> None:
    s = make_slice()
    view = s.executing()
    before = len(s.arm.requests)
    if how == "role_removed":
        s.revoke_maker()
    else:
        s.revocation.revoked.add(principal(ALICE))
    report = s.execute(view)
    assert (report.outcome, report.reason, report.state) == (
        "failed",
        "permission_revoked",
        "failed",
    )
    assert s.arm.puts == [] and len(s.arm.requests) == before  # not even a read
    assert _model(s) == ("gpt-4o", "2024-08-06")
    status = s.intent(_intent_id(view), who=BOB)
    assert status["intent"]["state"] == "failed"
    assert status["intent"]["status_reason"] == "permission_revoked"
    assert s.review_state(view) == "failed"
    denied = [r for r in s.audit_records() if r.kind == "denied"]
    assert any(r.operation == "action.execute" for r in denied)
    assert run(s.audit.verify(CHAIN)).ok


def test_verify_mismatch_rolls_the_target_back() -> None:
    arm = MismatchingArm(put_state="Succeeded")
    arm.mismatch_after_first_put = True
    s = make_slice(arm=arm)
    view = s.executing()
    report = s.execute(view)
    assert (report.outcome, report.state) == ("rolled_back", "rolled_back")
    assert len(s.arm.puts) == 2  # the swap, then the restore
    assert _model(s) == ("gpt-4o", "2024-08-06")
    status = s.intent(_intent_id(view))
    assert status["intent"]["state"] == "rolled_back"
    assert status["execution"]["rolled_back"] is True
    assert status["execution"]["verify_matched"] is False
    assert s.review_state(view) == "failed"
    assert run(s.audit.verify(CHAIN)).ok


def test_emergency_disable_stops_the_executor_and_resumes_cleanly() -> None:
    s = make_slice()
    view = s.executing()
    before = len(s.arm.requests)

    on = s.call(
        "PUT", DAVE, "/emergency-disable", json={"disabled": True, "reason": "incident_response"}
    )
    assert on.status_code == 200, on.text
    assert s.call("GET", CAROL, "/emergency-disable").json()["disabled"] is True

    report = s.execute(view)
    assert (report.outcome, report.reason, report.state) == (
        "deferred",
        "emergency_disabled",
        "executing",
    )
    assert len(s.arm.requests) == before  # zero connector calls
    assert s.intent(_intent_id(view))["intent"]["state"] == "executing"
    assert s.review_state(view) == "approved"  # not completed while deferred

    off = s.call("PUT", DAVE, "/emergency-disable", json={"disabled": False, "reason": None})
    assert off.status_code == 200, off.text
    assert s.execute(view).outcome == "succeeded"
    assert _model(s) == ("gpt-4.1", "2025-04-14")
    assert len(s.arm.puts) == 1


def test_read_only_credential_is_advisory_and_changes_nothing() -> None:
    s = make_slice(permissions=FAKES.READ_PERMS)
    assert s.advisory is True
    assert not s.registry.supports("foundry-model-swap", KIND)  # the registry refused it
    drafted = s.draft()
    assert drafted.status_code == 201, drafted.text
    intent_id = _intent_id(drafted.json())
    assert drafted.json()["advisory"] is True
    validated = s.step(ALICE, intent_id, "validate")
    assert validated.status_code == 200, validated.text
    presented = s.step(ALICE, intent_id, "confirmation").json()
    snapshot = run(s.service.get(_key(intent_id)))
    confirm = s.step(
        ALICE, intent_id, "confirm", {"confirmation_hash": presented["intent"]["confirmation_hash"]}
    )
    assert confirm.status_code == 409
    body = problem(confirm)
    assert body["code"] == "capability_unavailable" and body["reason"] == "advisory_connector"
    approve = s.approve(presented)
    assert approve.status_code == 409
    assert problem(approve)["reason"] == "advisory_connector"

    # Zero writes anywhere: the only ARM traffic was the one permissions read at connector build.
    assert s.arm.puts == []
    assert {r.method for r in s.arm.requests} == {"GET"}
    assert _model(s) == ("gpt-4o", "2024-08-06")
    # The intent stays exactly where it was, no review item exists, nothing was executed.
    after = run(s.service.get(_key(intent_id)))
    assert after.state == snapshot.state == "awaiting_confirmation"
    assert after.review_item_id is None
    assert s.execute(presented).outcome == "skipped"
    assert s.arm.puts == []


def test_government_target_is_never_routed_to_commercial() -> None:
    s = make_slice()
    before = len(s.arm.requests)  # the one permissions read made when the connector was built
    refused = s.draft(body=swap_body(target_id=GOV_TARGET_ID))
    # The Commercial deployment's scope does not cover a Government target: refused at the
    # door, so nothing is stored and the Commercial connector is never asked.
    assert refused.status_code == 403, refused.text
    assert problem(refused)["reason"] == "target_out_of_scope"
    assert len(s.arm.requests) == before and s.arm.puts == []
    assert _model(s) == ("gpt-4o", "2024-08-06")
    listed = s.call("GET", ALICE, f"/domains/{FINANCE}/intents")
    assert listed.status_code == 200 and listed.json()["items"] == []


def test_government_account_is_advisory_with_no_arm_traffic() -> None:
    from neurosphere_connector_foundry_actions import AccountRef
    from neurosphere_core.cloud import CloudName

    gov = AccountRef(
        cloud=CloudName.GOVERNMENT,
        subscription_id=FAKES.SUB,
        resource_group="rg-ai",
        account="acct1",
        location="usgovvirginia",
    )
    s = make_slice(account=gov)
    assert s.advisory is True
    assert s.arm.requests == []  # a Government account is refused before any request
    view = s.presented()
    assert view["advisory"] is True
    confirm = s.step(
        ALICE,
        _intent_id(view),
        "confirm",
        {"confirmation_hash": view["intent"]["confirmation_hash"]},
    )
    assert confirm.status_code == 409
    assert problem(confirm)["reason"] == "advisory_connector"
    assert s.arm.requests == []


def test_policy_store_outage_is_503_and_the_executor_defers() -> None:
    s = make_slice()
    view = s.executing()
    before = len(s.arm.requests)
    s.h.repo.fail_with(RuntimeError("cosmos down"))
    # DAVE has no cached scope yet, so derivation must read the (down) policy store.
    down = s.draft(DAVE, body=swap_body("idem-2026-10-20-dep1-swap-0002"))
    assert down.status_code == 503
    body = problem(down)
    assert body["code"] == "dependency_transient"
    report = s.execute(view)
    assert report.outcome == "deferred"  # fail closed, never a stale allow
    assert len(s.arm.requests) == before
    s.h.repo.fail_with(None)
    assert s.execute(view).outcome == "succeeded"


def test_buttons_and_rest_produce_the_same_confirmation_hash() -> None:
    """Same actor, same logical change, different channel: one hash (PRP-17 D1)."""
    s = make_slice()
    rest = s.presented(swap_body("idem-2026-10-20-dep1-swap-0003", channel="rest"))
    button = s.presented(swap_body("idem-2026-10-20-dep1-swap-0004", channel="button"))
    assert rest["intent"]["channel"] == "rest" and button["intent"]["channel"] == "button"
    assert rest["intent"]["confirmation_expires_at"] == button["intent"]["confirmation_expires_at"]
    assert rest["intent"]["confirmation_hash"] == button["intent"]["confirmation_hash"]
    assert rest["intent"]["intent_id"] != button["intent"]["intent_id"]


def _key(intent_id: str) -> IntentKey:
    return IntentKey(CUSTOMER, FINANCE, intent_id)
