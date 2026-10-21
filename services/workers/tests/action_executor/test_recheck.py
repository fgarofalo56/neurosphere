"""Execution-time recheck: revoked permission, stale target version, policy outage (fail closed)."""

from __future__ import annotations

from neurosphere_core.actions import ActionService
from neurosphere_core.actions.recheck import PolicyPermissionRechecker
from neurosphere_core.auth.scope import (
    InMemoryPolicyRepository,
    NoRevocationCheck,
    PolicyHead,
    PolicyRoleAssignment,
    PrincipalPolicy,
    Role,
    principal_document_id,
)
from neurosphere_core.cloud import CloudName
from neurosphere_core.errors import (
    CapabilityUnavailableError,
    DependencyTransientError,
    InvalidSchemaError,
    RateLimitedError,
)

from .executor_support import CUSTOMER, DOMAIN, MAKER_ID, Harness


async def test_permission_revoked_after_approval_blocks_execution_and_is_audited() -> None:
    h = Harness()
    key = await h.executing()
    h.rechecker.revoke(MAKER_ID, CUSTOMER, DOMAIN, "action.execute")
    report = await h.executor().execute(key)
    assert (report.outcome, report.reason, report.state) == (
        "failed",
        "permission_revoked",
        "failed",
    )
    assert h.connector.calls == []  # not even a dry run
    assert ("action.execute", "permission_revoked") in h.denials()
    denied = [e for e in h.auditor.events if e.kind == "denied"][-1]
    assert denied.denial_code == "forbidden"
    assert denied.channel == "worker"
    assert h.final_transition() == ("executing", "failed", "permission_revoked")


async def test_revocation_through_the_policy_store_rechecker_blocks() -> None:
    """Same flow with the real PolicyPermissionRechecker: the maker loses the steward role."""
    repo = InMemoryPolicyRepository()
    repo.put_head(PolicyHead(customer_id=CUSTOMER, policy_version="v1"))
    maker_policy = PrincipalPolicy(
        id=principal_document_id(MAKER_ID),
        customer_id=CUSTOMER,
        principal_id=MAKER_ID,
        domain_memberships=(DOMAIN,),
        role_assignments=(
            PolicyRoleAssignment(
                assignment_id="ra-1", role=Role.DOMAIN_STEWARD, domain_ids=(DOMAIN,)
            ),
        ),
    )
    repo.put_principal(maker_policy)
    h = Harness()
    h.service = ActionService(
        h.store,
        auditor=h.auditor,
        rechecker=PolicyPermissionRechecker(
            cloud=CloudName.COMMERCIAL,
            policy_repository=repo,
            revocation_checker=NoRevocationCheck(),
            clock=h.clock,
        ),
        execution_control=h.control,
        clock=h.clock,
    )
    key = await h.executing()
    repo.put_principal(maker_policy.model_copy(update={"role_assignments": ()}))
    report = await h.executor().execute(key)
    assert (report.outcome, report.reason) == ("failed", "permission_revoked")
    assert h.connector.calls == []


async def test_stale_target_version_blocks_apply() -> None:
    h = Harness()
    key = await h.executing()
    h.connector.state["etag"] = "etag-changed-elsewhere"
    report = await h.executor().execute(key)
    assert (report.outcome, report.reason) == ("failed", "target_version_changed")
    assert h.connector.calls == ["dry_run"]
    assert h.connector.count("apply") == 0
    assert h.final_transition() == ("executing", "failed", "target_version_changed")


async def test_policy_outage_fails_closed_and_keeps_the_intent() -> None:
    h = Harness()
    key = await h.executing()
    h.rechecker.fail_with(RuntimeError("policy store down"))
    report = await h.executor().execute(key)
    assert (report.outcome, report.reason) == ("deferred", "policy_store_unavailable")
    assert h.connector.calls == []
    stored = await h.current(key)
    assert stored.state == "executing"
    assert stored.execution is not None
    assert stored.execution.lease_owner is None
    assert stored.execution.phase == "pending"
    # Recovery: the outage clears, the next pass executes normally.
    h.rechecker.fail_with(None)
    again = await h.executor().execute(key)
    assert again.outcome == "succeeded"
    assert h.connector.count("apply") == 1


async def test_policy_store_transient_error_is_not_converted_to_allow() -> None:
    h = Harness()
    key = await h.executing()
    h.rechecker.fail_with(DependencyTransientError(reason="policy_store_unavailable"))
    report = await h.executor().execute(key)
    assert report.outcome == "deferred"
    assert h.connector.count("apply") == 0


async def test_retryable_dry_run_error_defers_non_retryable_fails() -> None:
    h = Harness()
    key = await h.executing()
    h.connector.dry_run_error = RateLimitedError(5, reason="arm_throttled")
    assert (await h.executor().execute(key)).outcome == "deferred"
    assert (await h.current(key)).state == "executing"
    h.connector.dry_run_error = InvalidSchemaError(reason="compatibility_failed")
    report = await h.executor().execute(key)
    assert (report.outcome, report.reason) == ("failed", "compatibility_failed")
    assert h.connector.count("apply") == 0


async def test_connector_capability_refusal_at_dry_run_fails() -> None:
    h = Harness()
    key = await h.executing()
    h.connector.dry_run_error = CapabilityUnavailableError("deployment_write_unavailable")
    report = await h.executor().execute(key)
    assert (report.outcome, report.reason) == ("failed", "deployment_write_unavailable")
    assert h.connector.count("apply") == 0
