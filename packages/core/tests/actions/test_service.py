"""ActionService: confirmation binding, maker rule, rechecks, approval, execution, expiry, audit."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import pytest
from neurosphere_core.actions import (
    ActionCaller,
    ActionService,
    AuditRepositoryActionAuditor,
    ExecutionRecord,
    IntentKey,
    IntentNotFoundError,
    InvalidTransitionError,
    StoredIntent,
    action_audit_chain_id,
)
from neurosphere_core.audit import AuditRepository, InMemoryAuditStore
from neurosphere_core.errors import (
    CapabilityUnavailableError,
    DependencyTransientError,
    ForbiddenError,
    InvalidSchemaError,
    StaleVersionError,
)

from .action_helpers import (
    CHECKER,
    CHECKER_ID,
    CUSTOMER,
    DOMAIN,
    MAKER,
    MAKER_ID,
    OUTSIDER,
    TARGET_VERSION,
    Harness,
    passed,
    request,
)

DIGEST = "sha256:" + "c" * 64


# -- happy path ---------------------------------------------------------------------------------


async def test_happy_path_without_approval_is_audited_before_and_after() -> None:
    h = Harness()
    executing = await h.executing()
    assert executing.state == "executing"
    assert executing.execution == ExecutionRecord(updated_at=h.clock.now)
    assert executing.requires_approval is False
    assert h.transitions() == [
        (None, "drafted"),
        ("drafted", "validated"),
        ("validated", "awaiting_confirmation"),
        ("awaiting_confirmation", "executing"),
    ]
    kinds = [e.kind for e in h.auditor.events]
    assert kinds == ["before", "after"] * 4
    assert ("commercial:contoso:entra:person:psn_maker0000000001", CUSTOMER, DOMAIN) == (
        h.rechecker.calls[-1][0],
        h.rechecker.calls[-1][1],
        h.rechecker.calls[-1][2],
    )
    assert h.rechecker.calls[-1][3] == "action.execute"


async def test_presented_confirmation_has_default_ttl_and_whole_seconds() -> None:
    h = Harness()
    presented = await h.awaiting_confirmation()
    expires = presented.intent.confirmation_expires_at
    assert expires is not None
    assert expires.root == "2026-10-20T12:15:01Z"  # 12:00:00.25 + 15 min, rounded up
    assert presented.due_at is not None
    assert presented.due_at.isoformat() == "2026-10-20T12:15:01+00:00"


async def test_unknown_intent_raises_not_found() -> None:
    h = Harness()
    with pytest.raises(IntentNotFoundError):
        await h.service.get(IntentKey(CUSTOMER, DOMAIN, "00000000-0000-4000-8000-999999999999"))


# -- confirmation refusals ---------------------------------------------------------------------


async def test_expired_confirmation_is_rejected_and_the_intent_expires() -> None:
    h = Harness()
    presented = await h.awaiting_confirmation()
    h.clock.advance(timedelta(minutes=16))
    with pytest.raises(StaleVersionError) as caught:
        await h.confirm(presented)
    assert caught.value.reason == "confirmation_expired"
    current = await h.current(presented.key)
    assert current.state == "expired"
    assert current.intent.status_reason == "confirmation_expired"


async def test_changed_target_version_fails_with_stale_version() -> None:
    h = Harness()
    presented = await h.awaiting_confirmation()
    with pytest.raises(StaleVersionError) as caught:
        await h.confirm(presented, version="etag-0xchanged")
    assert caught.value.reason == "target_version_changed"
    current = await h.current(presented.key)
    assert current.state == "failed"
    assert current.intent.status_reason == "target_version_changed"
    assert ("action.confirm", "target_version_changed") in h.denials()


async def test_target_version_change_before_presentation_fails_the_intent() -> None:
    h = Harness()
    validated = await h.validated()
    with pytest.raises(StaleVersionError) as caught:
        await h.service.present_confirmation(
            validated.key, MAKER, current_target_version="etag-0xchanged"
        )
    assert caught.value.reason == "target_version_changed"
    assert (await h.current(validated.key)).state == "failed"


async def test_hash_mismatch_is_refused_without_state_change() -> None:
    h = Harness()
    presented = await h.awaiting_confirmation()
    with pytest.raises(InvalidSchemaError) as caught:
        await h.confirm(presented, confirmation_hash=DIGEST)
    assert caught.value.reason == "confirmation_hash_mismatch"
    assert (await h.current(presented.key)).state == "awaiting_confirmation"
    assert h.denials() == [("action.confirm", "confirmation_hash_mismatch")]


async def test_tampered_stored_binding_is_refused() -> None:
    h = Harness()
    presented = await h.awaiting_confirmation()
    tampered = presented.model_copy(
        update={"intent": presented.intent.model_copy(update={"target_version": "etag-0xother"})}
    )
    await h.store.replace(tampered, if_match=presented.etag or "")
    with pytest.raises(InvalidSchemaError) as caught:
        await h.confirm(presented)
    assert caught.value.reason == "confirmation_hash_mismatch"


@pytest.mark.parametrize("stored_flag", [False, True])
async def test_advisory_intent_cannot_be_confirmed(stored_flag: bool) -> None:
    h = Harness()
    drafted = await h.drafted()
    await h.service.record_validation(drafted.key, MAKER, [passed()], advisory=stored_flag)
    presented = await h.service.present_confirmation(drafted.key, MAKER)
    writes = h.store.replace_calls
    with pytest.raises(CapabilityUnavailableError) as caught:
        await h.confirm(presented, advisory=not stored_flag)
    assert caught.value.reason == "advisory_connector"
    assert h.store.replace_calls == writes
    assert (await h.current(presented.key)).state == "awaiting_confirmation"


async def test_only_the_maker_may_confirm() -> None:
    h = Harness()
    presented = await h.awaiting_confirmation()
    with pytest.raises(ForbiddenError) as caught:
        await h.confirm(presented, CHECKER)
    assert caught.value.reason == "not_maker"
    assert (await h.current(presented.key)).state == "awaiting_confirmation"
    assert h.denials() == [("action.confirm", "not_maker")]


async def test_only_the_maker_may_present_or_decline() -> None:
    h = Harness()
    validated = await h.validated()
    with pytest.raises(ForbiddenError):
        await h.service.present_confirmation(validated.key, OUTSIDER)
    presented = await h.service.present_confirmation(validated.key, MAKER)
    with pytest.raises(ForbiddenError):
        await h.service.decline(presented.key, OUTSIDER)


async def test_revoked_permission_at_confirm_is_blocked_and_audited() -> None:
    h = Harness()
    presented = await h.awaiting_confirmation()
    h.rechecker.revoke(MAKER_ID, CUSTOMER, DOMAIN, "action.execute")
    with pytest.raises(ForbiddenError) as caught:
        await h.confirm(presented)
    assert caught.value.reason == "permission_revoked"
    assert (await h.current(presented.key)).state == "awaiting_confirmation"
    denied = [e for e in h.auditor.events if e.kind == "denied"]
    assert len(denied) == 1
    assert denied[0].denial_code == "forbidden"
    assert denied[0].actor == MAKER.actor


async def test_policy_store_outage_fails_closed() -> None:
    h = Harness()
    presented = await h.awaiting_confirmation()
    h.rechecker.fail_with(RuntimeError("policy store down"))
    with pytest.raises(DependencyTransientError) as caught:
        await h.confirm(presented)
    assert caught.value.reason == "policy_store_unavailable"
    assert caught.value.status == 503
    assert (await h.current(presented.key)).state == "awaiting_confirmation"
    assert h.denials() == [("action.confirm", "policy_store_unavailable")]


async def test_emergency_disable_blocks_confirm_into_executing() -> None:
    h = Harness()
    presented = await h.awaiting_confirmation()
    await h.control.set(
        CUSTOMER, disabled=True, reason="incident", changed_by="p-admin01", now=h.clock.now
    )
    with pytest.raises(CapabilityUnavailableError) as caught:
        await h.confirm(presented)
    assert caught.value.reason == "emergency_disabled"
    assert (await h.current(presented.key)).state == "awaiting_confirmation"
    # Routing to approval is still allowed; execution stays blocked at approval time.
    waiting = await h.confirm(presented, requires_approval=True)
    assert waiting.state == "awaiting_approval"


async def test_audit_failure_aborts_the_transition() -> None:
    h = Harness()
    presented = await h.awaiting_confirmation()
    h.auditor.fail_with(DependencyTransientError("audit down", reason="audit_write_failed"))
    with pytest.raises(DependencyTransientError):
        await h.confirm(presented)
    h.auditor.fail_with(None)
    assert (await h.current(presented.key)).state == "awaiting_confirmation"


async def test_confirm_cannot_skip_approval() -> None:
    h = Harness()
    waiting = await h.awaiting_approval()
    with pytest.raises(InvalidTransitionError):
        await h.confirm(waiting)
    assert (await h.current(waiting.key)).state == "awaiting_approval"


# -- validation ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "reason"), [("failed", "prerequisite_failed"), ("unknown", "prerequisite_unknown")]
)
async def test_failed_or_unknown_prerequisite_fails_validation(status: str, reason: str) -> None:
    h = Harness()
    drafted = await h.drafted()
    result = await h.service.record_validation(
        drafted.key, MAKER, [passed(), passed("target_health", status)]
    )
    assert result.state == "failed"
    assert result.intent.status_reason == reason
    assert [r.status for r in result.intent.prerequisite_results] == ["passed", status]


async def test_warning_prerequisite_still_validates() -> None:
    h = Harness()
    drafted = await h.drafted()
    result = await h.service.record_validation(
        drafted.key, MAKER, [passed("budget", "warning"), passed("x", "not_applicable")]
    )
    assert result.state == "validated"


async def test_draft_refuses_targets_outside_the_customer_or_cloud() -> None:
    h = Harness()
    other_customer = "commercial:fabrikam:foundry:model_deployment:eastus2/chat-prod"
    gov = "government:contoso:foundry:model_deployment:usgovvirginia/chat-prod"
    for target in (other_customer, gov):
        with pytest.raises(ForbiddenError) as caught:
            await h.drafted(request(target_id=target))
        assert caught.value.reason == "target_out_of_scope"
    assert h.denials() == [("action.draft", "target_out_of_scope")] * 2


async def test_draft_refuses_an_invalid_diff() -> None:
    h = Harness()
    bad = request().model_copy(
        update={
            "proposed_diff": request().proposed_diff.model_validate(
                {"format": "json_patch", "operations": [{"op": "replace", "path": "/a"}]}
            )
        }
    )
    with pytest.raises(InvalidSchemaError) as caught:
        await h.drafted(bad)
    assert caught.value.reason == "invalid_diff"


# -- approval -------------------------------------------------------------------------------------


async def _approve(
    h: Harness,
    who: ActionCaller = CHECKER,
    *,
    waiting: StoredIntent | None = None,
    **kwargs: Any,
) -> tuple[StoredIntent, StoredIntent]:
    waiting = waiting or await h.awaiting_approval()
    bound = waiting.intent.confirmation_hash
    assert bound is not None
    params: dict[str, Any] = {
        "approved": True,
        "approved_confirmation_hash": bound.root,
        "current_target_version": TARGET_VERSION,
    }
    params.update(kwargs)
    return waiting, await h.service.apply_approval(waiting.key, who, **params)


async def test_checker_approval_moves_to_executing() -> None:
    h = Harness()
    waiting, approved = await _approve(h)
    assert waiting.requires_approval is True
    assert approved.state == "executing"
    assert approved.execution is not None
    approve_checks = [c for c in h.rechecker.calls if c[3] == "action.approve"]
    assert approve_checks == [(CHECKER_ID, CUSTOMER, DOMAIN, "action.approve")]


async def test_self_approval_is_refused_on_the_real_principal() -> None:
    h = Harness()
    waiting = await h.awaiting_approval()
    with pytest.raises(ForbiddenError) as caught:
        await _approve(h, MAKER, waiting=waiting)
    assert caught.value.reason == "self_approval_prohibited"
    assert (await h.current(waiting.key)).state == "awaiting_approval"
    assert ("action.approve", "self_approval_prohibited") in h.denials()


async def test_self_approval_allowed_when_policy_permits() -> None:
    h = Harness()
    _, approved = await _approve(h, MAKER, self_approval_forbidden=False)
    assert approved.state == "executing"


async def test_approver_without_permission_cannot_change_state() -> None:
    h = Harness()
    waiting = await h.awaiting_approval()
    with pytest.raises(ForbiddenError) as caught:
        await _approve(h, OUTSIDER, waiting=waiting)
    assert caught.value.reason == "permission_revoked"
    assert (await h.current(waiting.key)).state == "awaiting_approval"


async def test_rejection_fails_the_intent() -> None:
    h = Harness()
    _, rejected = await _approve(h, approved=False)
    assert rejected.state == "failed"
    assert rejected.intent.status_reason == "approval_rejected"


async def test_maker_revoked_between_confirm_and_approval_fails_the_intent() -> None:
    h = Harness()
    waiting = await h.awaiting_approval()
    h.rechecker.revoke(MAKER_ID, CUSTOMER, DOMAIN, "action.execute")
    with pytest.raises(ForbiddenError) as caught:
        await _approve(h, waiting=waiting)
    assert caught.value.reason == "permission_revoked"
    current = await h.current(waiting.key)
    assert current.state == "failed"
    assert current.intent.status_reason == "permission_revoked"


async def test_approval_after_expiry_expires_the_intent() -> None:
    h = Harness()
    waiting = await h.awaiting_approval()
    h.clock.advance(timedelta(hours=1))
    with pytest.raises(StaleVersionError) as caught:
        await _approve(h, waiting=waiting)
    assert caught.value.reason == "confirmation_expired"
    assert (await h.current(waiting.key)).state == "expired"


async def test_approval_with_wrong_hash_or_stale_target() -> None:
    h = Harness()
    waiting = await h.awaiting_approval()
    with pytest.raises(InvalidSchemaError):
        await _approve(h, waiting=waiting, approved_confirmation_hash=DIGEST)
    assert (await h.current(waiting.key)).state == "awaiting_approval"
    with pytest.raises(StaleVersionError) as caught:
        await _approve(h, waiting=waiting, current_target_version="etag-0xnew")
    assert caught.value.reason == "target_version_changed"
    assert (await h.current(waiting.key)).state == "failed"


async def test_approval_needs_awaiting_approval() -> None:
    h = Harness()
    presented = await h.awaiting_confirmation()
    with pytest.raises(InvalidTransitionError):
        await _approve(h, waiting=presented)


async def test_emergency_disable_blocks_approval_into_executing() -> None:
    h = Harness()
    waiting = await h.awaiting_approval()
    await h.control.set(
        CUSTOMER, disabled=True, reason="incident", changed_by="p-admin01", now=h.clock.now
    )
    with pytest.raises(CapabilityUnavailableError):
        await _approve(h, waiting=waiting)
    assert (await h.current(waiting.key)).state == "awaiting_approval"


async def test_link_review_item() -> None:
    h = Harness()
    waiting = await h.awaiting_approval()
    linked = await h.service.link_review_item(waiting.key, "review-0001")
    assert linked.review_item_id == "review-0001"
    assert linked.state == "awaiting_approval"


# -- execution bookkeeping (item 2 codes against this) ----------------------------------------


async def test_execution_lifecycle_to_succeeded() -> None:
    h = Harness()
    executing = await h.executing()
    claimed = await h.service.begin_execution(executing.key, worker_id="worker-a")
    checked = await h.service.recheck_execution(claimed, current_target_version=TARGET_VERSION)
    record = checked.execution
    assert record is not None
    assert record.phase == "rechecked"
    applying = await h.service.record_execution(
        checked,
        record.model_copy(update={"phase": "applying", "apply_started_at": h.clock.now}),
        audit="before",
        target_state_digest=DIGEST,
    )
    assert applying.execution is not None
    assert applying.execution.apply_may_have_happened()
    applied = await h.service.record_execution(
        applying,
        applying.execution.model_copy(
            update={"phase": "applied", "apply_result": {"status": "applied"}}
        ),
        audit="after",
        target_state_digest=DIGEST,
        result="succeeded",
    )
    assert applied.execution is not None
    with pytest.raises(InvalidSchemaError) as caught:
        await h.service.finish_execution(applied, outcome="succeeded")
    assert caught.value.reason == "unverified_outcome"
    verified = applied.execution.model_copy(
        update={"verify_matched": True, "canary": "verify_only"}
    )
    done = await h.service.finish_execution(applied, outcome="succeeded", execution=verified)
    assert done.state == "succeeded"
    assert done.execution is not None
    assert done.execution.phase == "done"
    assert done.execution.lease_owner is None
    final = h.auditor.events[-1]
    assert (final.kind, final.result, final.verified) == ("after", "succeeded", True)
    phases = [e.phase for e in h.auditor.events if e.phase is not None]
    assert phases == ["applying", "applied"]


async def test_rolled_back_requires_a_recorded_rollback() -> None:
    h = Harness()
    executing = await h.executing()
    with pytest.raises(InvalidSchemaError) as caught:
        await h.service.finish_execution(executing, outcome="rolled_back")
    assert caught.value.reason == "rollback_not_recorded"
    record = ExecutionRecord(phase="rolling_back", rolled_back=True, verify_matched=False)
    rolled = await h.service.finish_execution(executing, outcome="rolled_back", execution=record)
    assert rolled.state == "rolled_back"
    assert rolled.intent.status_reason == "verification_failed"


async def test_rollback_failure_finishes_failed() -> None:
    h = Harness()
    executing = await h.executing()
    failed = await h.service.finish_execution(executing, outcome="failed", reason="rollback_failed")
    assert failed.state == "failed"
    assert failed.intent.status_reason == "rollback_failed"
    assert failed.execution is not None
    assert failed.execution.last_error == "rollback_failed"


async def test_permission_revoked_before_execution_fails_and_is_audited() -> None:
    h = Harness()
    executing = await h.executing()
    claimed = await h.service.begin_execution(executing.key, worker_id="worker-a")
    h.rechecker.revoke(MAKER_ID, CUSTOMER, DOMAIN, "action.execute")
    with pytest.raises(ForbiddenError) as caught:
        await h.service.recheck_execution(claimed, current_target_version=TARGET_VERSION)
    assert caught.value.reason == "permission_revoked"
    current = await h.current(executing.key)
    assert current.state == "failed"
    denied = [e for e in h.auditor.events if e.kind == "denied"]
    assert [(e.operation, e.channel, e.reason) for e in denied] == [
        ("action.execute", "worker", "permission_revoked")
    ]


async def test_recheck_refused_after_apply_may_have_happened() -> None:
    h = Harness()
    executing = await h.executing()
    claimed = await h.service.begin_execution(executing.key, worker_id="worker-a")
    assert claimed.execution is not None
    applying = await h.service.record_execution(
        claimed, claimed.execution.model_copy(update={"phase": "applying"})
    )
    with pytest.raises(InvalidSchemaError) as caught:
        await h.service.recheck_execution(applying, current_target_version=TARGET_VERSION)
    assert caught.value.reason == "recheck_after_apply"


async def test_dry_run_intent_can_succeed_without_apply() -> None:
    h = Harness()
    executing = await h.executing(request(dry_run=True))
    done = await h.service.finish_execution(executing, outcome="succeeded")
    assert done.state == "succeeded"


# -- expiry -------------------------------------------------------------------------------------


async def test_expire_due_sweeps_lapsed_intents_only() -> None:
    h = Harness()
    presented = await h.awaiting_confirmation()
    drafted = await h.drafted(request("idem-2026-10-20-chat-prod-0009"))
    executing = await h.executing(request("idem-2026-10-20-chat-prod-0010"))
    h.clock.advance(timedelta(minutes=20))
    expired = await h.service.expire_due()
    assert [s.intent_id for s in expired] == [presented.intent_id]
    assert expired[0].intent.status_reason == "confirmation_expired"
    h.clock.advance(timedelta(days=1))
    later = await h.service.expire_due()
    assert [s.intent_id for s in later] == [drafted.intent_id]
    assert later[0].intent.status_reason == "draft_abandoned"
    assert (await h.current(executing.key)).state == "executing"


# -- audit store integration ----------------------------------------------------------------


async def test_default_auditor_writes_a_verifiable_metadata_only_chain() -> None:
    h = Harness()
    repository = AuditRepository(InMemoryAuditStore())
    h.service = ActionService(
        h.store,
        auditor=AuditRepositoryActionAuditor(repository),
        rechecker=h.rechecker,
        execution_control=h.control,
        clock=h.clock,
    )
    presented = await h.awaiting_confirmation()
    with pytest.raises(ForbiddenError):
        await h.confirm(presented, CHECKER)
    await h.confirm(presented)
    chain = action_audit_chain_id(CUSTOMER, DOMAIN)
    assert chain == "contoso.retail"
    verification = await repository.verify(chain)
    assert verification.ok
    assert verification.records_checked == 9
    records = await repository.read_range(chain, limit=100)
    dumped = json.dumps([r.model_dump(mode="json") for r in records])
    assert MAKER_ID not in dumped
    assert CHECKER_ID not in dumped
    assert "2026-06-15" not in dumped  # the diff body never reaches the audit log
    assert [r.kind for r in records].count("denied") == 1
    details = [r.outcome.detail for r in records if r.outcome is not None]
    assert "transition=awaiting_confirmation:executing" in details


def test_caller_repr_hides_the_principal_id() -> None:
    assert MAKER_ID not in repr(MAKER)
    assert MAKER_ID not in str(MAKER)


async def test_list_pages_newest_first_with_a_cursor() -> None:
    h = Harness()
    ids = []
    for index in range(5):
        h.clock.advance(timedelta(seconds=1))
        ids.append((await h.drafted(request(f"idem-2026-10-20-page-{index:06d}"))).intent_id)
    first = await h.store.list(CUSTOMER, DOMAIN, limit=2)
    assert [s.intent_id for s in first.items] == ids[::-1][:2]
    assert first.next_cursor is not None
    second = await h.store.list(CUSTOMER, DOMAIN, limit=2, cursor=first.next_cursor)
    third = await h.store.list(CUSTOMER, DOMAIN, limit=2, cursor=second.next_cursor)
    assert [s.intent_id for s in second.items + third.items] == ids[::-1][2:]
    assert third.next_cursor is None
    assert (await h.store.list(CUSTOMER, DOMAIN, state="validated")).items == ()
    with pytest.raises(InvalidSchemaError):
        await h.store.list(CUSTOMER, DOMAIN, cursor="not-a-cursor")
    with pytest.raises(InvalidSchemaError):
        await h.store.list(CUSTOMER, DOMAIN, limit=0)


async def test_store_outage_is_dependency_transient() -> None:
    h = Harness()
    stored = await h.drafted()
    h.store.fail_with(DependencyTransientError("down", reason="intent_store_unavailable"))
    with pytest.raises(DependencyTransientError):
        await h.service.get(stored.key)
