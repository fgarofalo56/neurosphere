"""Verify-by-change, register rows and the customer binding (PRP-55 item 5, criteria 6 and 7).

The connector runs with the real ``HttpArmProvisioner`` over a fake ARM (``httpx.MockTransport``)
and the durable approvals adapter over the in-memory repository. No network, nothing paid.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from action_executor.executor_support import CUSTOMER, DOMAIN, Harness  # pyright: ignore[reportMissingImports]
from neurosphere_connector.write import WriteRequest
from neurosphere_contracts.deployment.v1.deploy_action_plan import DeployActionPlan, ResourceSpec
from neurosphere_core.actions import DraftRequest, IntentKey
from neurosphere_core.cloud import CloudName, profile_for
from neurosphere_core.deploy.approvals import InMemoryPlanApprovalRepository, PlanApprovalRecord
from neurosphere_core.deploy.arm import (
    CREATED_BY_TAG,
    DEPLOYMENT_TAG,
    PLAN_TAG,
    arm_resource_name,
)
from neurosphere_core.deploy.register import (
    CustomerScopedRegister,
    InMemoryRegisterStore,
    Ownership,
)
from neurosphere_core.errors import CapabilityUnavailableError, ForbiddenError
from neurosphere_workers.actions import DEPLOY_ACTION_CONNECTORS
from neurosphere_workers.actions.deploy import (
    APPLY_KIND,
    DeployConnector,
    apply_diff,
    deployment_target,
    plan_target,
    resources_digest,
)
from neurosphere_workers.actions.deploy_approvals import RepositoryPlanApprovals
from neurosphere_workers.actions.deploy_arm import HttpArmProvisioner
from neurosphere_workers.actions.deploy_http import BearerDeployHttp, deploy_scopes

from .fake_arm import RG, SUB, FakeArm, FakeCredential, no_sleep

PLAN_ID = "plan-0123456789abcdef0123456789abcdef"
PLAN_HASH = "sha256:" + "a" * 64
DEPLOYMENT = "demo-eastus2"
KEY = "idem-deploy-apply-0055"
REUSED = f"/subscriptions/{SUB}/resourceGroups/rg-shared/providers/Microsoft.KeyVault/vaults/kv"
NOW = datetime(2026, 11, 16, 12, 0, 0, tzinfo=UTC)


def _arm_spec(service: str) -> ResourceSpec:
    return ResourceSpec.model_validate(
        {
            "service": service,
            "kind": "arm_resource",
            "disposition": "create",
            "name": arm_resource_name(service, DEPLOYMENT),
            "region": "eastus2",
            "sku": None,
            "resource_id": None,
            "subscription_id": SUB,
            "resource_group": RG,
            "consent_reference": None,
        }
    )


def _reuse_spec() -> ResourceSpec:
    return ResourceSpec.model_validate(
        {
            "service": "key_vault",
            "kind": "arm_resource",
            "disposition": "reuse",
            "name": "kv",
            "region": "eastus2",
            "sku": None,
            "resource_id": REUSED,
            "subscription_id": None,
            "resource_group": None,
            "consent_reference": "consent-0001",
        }
    )


def _plan(resources: list[ResourceSpec]) -> DeployActionPlan:
    return DeployActionPlan(
        schema_version="1.0.0",
        plan_id=PLAN_ID,
        plan_hash=PLAN_HASH,
        deployment_id=DEPLOYMENT,
        cloud="commercial",
        resources=resources,
    )


class Setup:
    def __init__(self, arm: FakeArm | None = None, *, bound: str | None = CUSTOMER) -> None:
        self.arm = arm or FakeArm()
        self.repo = InMemoryPlanApprovalRepository(lambda: NOW)
        self.register = InMemoryRegisterStore()
        profile = profile_for(CloudName.COMMERCIAL)
        http = BearerDeployHttp(self.arm.client(), FakeCredential, deploy_scopes(profile))  # type: ignore[arg-type]
        self.connector = DeployConnector(
            cloud=CloudName.COMMERCIAL,
            customer_id=bound,
            approvals=RepositoryPlanApprovals(self.repo),
            register=CustomerScopedRegister(self.register, CUSTOMER),
            arm=HttpArmProvisioner(http, profile, sleep=no_sleep),
        )

    async def approve(self, plan: DeployActionPlan, customer: str = CUSTOMER) -> None:
        await self.repo.create(
            PlanApprovalRecord(
                customer_id=customer,
                plan_id=plan.plan_id,
                plan_hash=plan.plan_hash,
                resources_digest=resources_digest(plan.resources),
                deployment_id=plan.deployment_id,
                cloud=plan.cloud,
                resources=tuple(plan.resources),
                approver="pp-approver",
                approved_at=NOW,
                expires_at=NOW + timedelta(hours=1),
            )
        )


def _write(plan: DeployActionPlan, customer: str = CUSTOMER) -> WriteRequest:
    return WriteRequest(
        target=plan_target("commercial", customer, plan.plan_id),
        target_version=plan.plan_hash,
        proposed_diff=apply_diff(plan),
    )


def _draft(plan: DeployActionPlan) -> DraftRequest:
    return DraftRequest.model_validate(
        {
            "action_kind": APPLY_KIND,
            "target": plan_target("commercial", CUSTOMER, plan.plan_id).model_dump(mode="json"),
            "target_version": plan.plan_hash,
            "proposed_diff": apply_diff(plan).model_dump(
                mode="json", by_alias=True, exclude_none=True
            ),
            "evidence": [],
            "idempotency_key": KEY,
            "channel": "rest",
            "dry_run": False,
        }
    )


async def test_created_and_reused_rows_are_registered_and_verify_reads_back() -> None:
    setup = Setup()
    plan = _plan([_arm_spec("storage"), _arm_spec("event_hubs"), _reuse_spec()])
    await setup.approve(plan)
    await setup.connector.apply(_write(plan))
    rows = {r.service: r for r in await setup.register.list_rows(DEPLOYMENT)}
    assert rows["storage"].ownership is Ownership.CREATED
    assert rows["storage"].created_by == "neurosphere"
    assert rows["event_hubs"].ownership is Ownership.CREATED
    assert rows["key_vault"].ownership is Ownership.REUSED
    assert rows["key_vault"].consent_reference == "consent-0001"
    assert rows["key_vault"].resource_id == REUSED
    assert {r.customer_id for r in rows.values()} == {CUSTOMER}
    assert {r.creating_plan_id for r in rows.values()} == {PLAN_ID}
    tags = [p["tags"] for p in setup.arm.payloads]
    assert all(t[CREATED_BY_TAG] == "neurosphere" for t in tags)
    assert all(t[DEPLOYMENT_TAG] == DEPLOYMENT and t[PLAN_TAG] == PLAN_ID for t in tags)
    verified = await setup.connector.verify(_write(plan))
    assert verified.matched is True
    # The reused resource is never written to ARM.
    assert all("KeyVault" not in path for _, path in setup.arm.calls)


async def test_a_missing_resource_after_apply_is_a_failed_verify() -> None:
    setup = Setup(FakeArm(drop_after_create=True))
    plan = _plan([_arm_spec("storage")])
    await setup.approve(plan)
    await setup.connector.apply(_write(plan))
    verified = await setup.connector.verify(_write(plan))
    assert verified.matched is False
    assert verified.mismatched_paths == ("/resources/storage.arm_resource",)


async def test_a_failed_verify_runs_the_executor_rollback_path() -> None:
    setup = Setup(FakeArm(drop_after_create=True))
    plan = _plan([_arm_spec("monitoring")])
    await setup.approve(plan)
    h = Harness(connector=setup.connector)  # type: ignore[arg-type]
    key: IntentKey = await h.executing(_draft(plan))
    report = await h.executor(table=dict(DEPLOY_ACTION_CONNECTORS)).execute(key)
    # verify mismatched -> rollback attempted -> the deploy connector never deletes, so the
    # intent ends failed for operator attention (nothing is pretended to have succeeded).
    assert report.outcome == "failed"
    stored = await h.current(IntentKey(CUSTOMER, DOMAIN, report.intent_id))
    assert stored.execution is not None
    assert stored.execution.verify_matched is False
    phases = [phase for _, phase, _ in h.exec_events()]
    assert "rolling_back" in phases
    assert [m for m, _ in setup.arm.calls].count("PUT") == 1


async def test_a_target_of_another_customer_is_refused_before_any_call() -> None:
    setup = Setup()
    plan = _plan([_arm_spec("storage")])
    await setup.approve(plan, customer="fabrikam")  # approved for fabrikam, connector is contoso
    for phase in (setup.connector.dry_run, setup.connector.apply, setup.connector.verify):
        with pytest.raises(ForbiddenError) as raised:
            await phase(_write(plan, customer="fabrikam"))
        assert raised.value.reason == "customer_mismatch"
    with pytest.raises(ForbiddenError) as raised:
        await setup.connector.dry_run(
            WriteRequest(
                target=deployment_target("commercial", "fabrikam", DEPLOYMENT),
                target_version="sha256:" + "0" * 64,
                proposed_diff=apply_diff(plan),
            )
        )
    assert raised.value.reason == "customer_mismatch"
    assert setup.arm.calls == []
    assert await setup.register.list_rows(DEPLOYMENT) == []


async def test_an_unbound_connector_keeps_the_previous_behaviour() -> None:
    setup = Setup(bound=None)
    plan = _plan([_arm_spec("storage")])
    await setup.approve(plan)
    await setup.connector.apply(_write(plan))
    assert len(await setup.register.list_rows(DEPLOYMENT)) == 1


async def test_a_service_outside_the_allowlist_is_refused_before_any_call() -> None:
    setup = Setup()
    kv: dict[str, Any] = {**_arm_spec("storage").model_dump(), "service": "key_vault"}
    plan = _plan([_arm_spec("storage"), ResourceSpec.model_validate(kv)])
    await setup.approve(plan)
    with pytest.raises(CapabilityUnavailableError) as raised:
        await setup.connector.apply(_write(plan))
    assert raised.value.reason == "capability_unavailable"
    assert setup.arm.calls == []  # storage was not created either: refused as a whole


async def test_an_unapproved_or_expired_plan_is_refused_with_zero_calls() -> None:
    setup = Setup()
    plan = _plan([_arm_spec("storage")])
    with pytest.raises(ForbiddenError) as raised:
        await setup.connector.apply(_write(plan))
    assert raised.value.reason == "plan_not_approved"
    await setup.approve(plan)
    late = Setup()
    late.repo = InMemoryPlanApprovalRepository(lambda: NOW + timedelta(hours=2))
    await late.repo.create(
        (await setup.repo.get(CUSTOMER, PLAN_ID)).model_copy()  # type: ignore[union-attr]
    )
    assert await RepositoryPlanApprovals(late.repo).get(CUSTOMER, PLAN_ID) is None
    assert setup.arm.calls == []
