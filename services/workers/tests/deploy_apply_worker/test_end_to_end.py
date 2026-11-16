"""End to end, in memory (PRP-55 item 6, criteria 1 and 8; unmarked: runs in CI).

The "API process" approves a plan through ``PlanApprovalStore`` (the store behind
``POST .../plans/approve``) and derives the apply intent exactly as ``POST .../plans/apply`` does
(``ApprovalRecord.action_plan`` -> ``apply_diff``). The "worker process" is a separate set of
objects: its own repository instance on the SAME backing container (a fake Cosmos container),
the real action executor, the real ``DeployConnector`` with ``RepositoryPlanApprovals`` and the
real ``HttpArmProvisioner`` over a fake ARM (``httpx.MockTransport``). Approve, confirm, execute,
verify and register; with no approval or a changed hash nothing is provisioned. No network.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from action_executor.executor_support import CUSTOMER, DOMAIN, Harness  # pyright: ignore[reportMissingImports]
from azure.core import MatchConditions
from azure.cosmos.exceptions import (
    CosmosAccessConditionFailedError,
    CosmosResourceExistsError,
    CosmosResourceNotFoundError,
)
from neurosphere_api.deploy.apply import PlanApprovalStore
from neurosphere_api.deploy.apply.models import ApplyTarget
from neurosphere_api.deploy.plan import DeploymentPlan, PlanCheck, PlanCost, PlanItem
from neurosphere_contracts.deployment.v1.deploy_action_plan import DeployActionPlan
from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope
from neurosphere_core.actions import DraftRequest, IntentKey
from neurosphere_core.capabilities import DeploymentProfile
from neurosphere_core.cloud import CloudName, profile_for
from neurosphere_core.deploy.approvals.cosmos_store import CosmosPlanApprovalRepository
from neurosphere_core.deploy.register import (
    CustomerScopedRegister,
    InMemoryRegisterStore,
    Ownership,
)
from neurosphere_core.scope import IdentityScope
from neurosphere_workers.actions import DEPLOY_ACTION_CONNECTORS
from neurosphere_workers.actions.deploy import APPLY_KIND, DeployConnector, apply_diff, plan_target
from neurosphere_workers.actions.deploy_approvals import RepositoryPlanApprovals
from neurosphere_workers.actions.deploy_arm import HttpArmProvisioner
from neurosphere_workers.actions.deploy_http import BearerDeployHttp, deploy_scopes

from .fake_arm import RG, SUB, FakeArm, FakeCredential, no_sleep

NOW = datetime(2026, 11, 16, 12, 0, 0, tzinfo=UTC)
PLAN_ID = "plan-0123456789abcdef0123456789abcdef"
DEPLOYMENT = "demo-eastus2"
KEY = "idem-deploy-apply-e2e-0001"
_SCOPE_EXAMPLE = (
    Path(__file__).resolve().parents[4]
    / "packages/contracts/schemas/scope/v1/examples/valid/identity-scope.viewer.json"
)


class SharedContainer:
    """One Cosmos container both processes talk to (point reads, create, ETag'd replace)."""

    def __init__(self) -> None:
        self.docs: dict[tuple[str, str], dict[str, Any]] = {}
        self._n = 0

    async def read_item(self, item: str, partition_key: str) -> dict[str, Any]:
        found = self.docs.get((partition_key, item))
        if found is None:
            raise CosmosResourceNotFoundError(status_code=404, message="not found")
        return json.loads(json.dumps(found))  # a fresh copy, as from the wire

    async def create_item(self, body: dict[str, Any]) -> dict[str, Any]:
        key = (body["customer_id"], body["id"])
        if key in self.docs:
            raise CosmosResourceExistsError(status_code=409, message="conflict")
        self._n += 1
        self.docs[key] = {**body, "_etag": str(self._n)}
        return body

    async def replace_item(
        self, item: str, body: dict[str, Any], etag: str, match_condition: MatchConditions
    ) -> dict[str, Any]:
        key = (body["customer_id"], item)
        if self.docs[key]["_etag"] != etag:
            raise CosmosAccessConditionFailedError(status_code=412, message="precondition")
        self._n += 1
        self.docs[key] = {**body, "_etag": str(self._n)}
        return body


def _scope() -> IdentityScope:
    payload = json.loads(_SCOPE_EXAMPLE.read_text(encoding="utf-8"))
    assert payload["customer_id"] == CUSTOMER
    return IdentityScope._from_verified_contract(  # pyright: ignore[reportPrivateUsage]
        ContractScope.model_validate(payload)
    )


def _plan(*services: str) -> DeploymentPlan:
    return DeploymentPlan(
        plan_id=PLAN_ID,
        deployment_id=DEPLOYMENT,
        profile=DeploymentProfile(
            cloud="commercial", regions=("eastus2",), hosting="aks", analytics="fabric"
        ),
        items=[
            PlanItem(
                service=service,  # type: ignore[arg-type]
                status="create",
                cost_implication=PlanCost(basis="unknown"),
                checks=[PlanCheck(name="quota", outcome="pass", reason="ok")],
            )
            for service in services
        ],
        created_at=NOW,
    )


TARGET = ApplyTarget(subscription_id=SUB, resource_group=RG, region="eastus2")


class Worker:
    """The executor worker: separate objects, the same backing container."""

    def __init__(self, container: SharedContainer, arm: FakeArm) -> None:
        self.arm = arm
        self.register = InMemoryRegisterStore()
        profile = profile_for(CloudName.COMMERCIAL)
        http = BearerDeployHttp(arm.client(), FakeCredential, deploy_scopes(profile))  # type: ignore[arg-type]
        repository = CosmosPlanApprovalRepository(container, clock=lambda: NOW)  # type: ignore[arg-type]
        self.connector = DeployConnector(
            cloud=CloudName.COMMERCIAL,
            customer_id=CUSTOMER,
            approvals=RepositoryPlanApprovals(repository),
            register=CustomerScopedRegister(self.register, CUSTOMER),
            arm=HttpArmProvisioner(http, profile, sleep=no_sleep),
        )
        self.harness = Harness(connector=self.connector)  # type: ignore[arg-type]

    async def run(self, plan: DeployActionPlan, *, version: str | None = None) -> Any:
        draft = DraftRequest.model_validate(
            {
                "action_kind": APPLY_KIND,
                "target": plan_target("commercial", CUSTOMER, plan.plan_id).model_dump(mode="json"),
                "target_version": version or plan.plan_hash,
                "proposed_diff": apply_diff(plan).model_dump(
                    mode="json", by_alias=True, exclude_none=True
                ),
                "evidence": [],
                "idempotency_key": KEY,
                "channel": "rest",
                "dry_run": False,
            }
        )
        key: IntentKey = await self.harness.executing(draft)  # validate + confirm
        return await self.harness.executor(table=dict(DEPLOY_ACTION_CONNECTORS)).execute(key)


def _api(container: SharedContainer) -> PlanApprovalStore:
    repository = CosmosPlanApprovalRepository(container, clock=lambda: NOW)  # type: ignore[arg-type]
    return PlanApprovalStore(repository, clock=lambda: NOW)


async def test_approve_confirm_execute_verify_and_register_across_processes() -> None:
    container = SharedContainer()
    api = _api(container)
    record = await api.approve(_scope(), _plan("storage", "event_hubs", "monitoring"), TARGET)
    action_plan = (await api.record(_scope(), PLAN_ID)).action_plan()
    assert action_plan.plan_hash == record.approved.plan_hash

    worker = Worker(container, FakeArm())
    report = await worker.run(action_plan)
    assert (report.outcome, report.state, report.reason) == ("succeeded", "succeeded", None)
    stored = await worker.harness.current(IntentKey(CUSTOMER, DOMAIN, report.intent_id))
    assert stored.execution is not None and stored.execution.verify_matched is True

    rows = await worker.register.list_rows(DEPLOYMENT)
    assert sorted(r.service for r in rows) == ["event_hubs", "monitoring", "storage"]
    assert all(r.ownership is Ownership.CREATED and r.customer_id == CUSTOMER for r in rows)
    assert {r.creating_plan_id for r in rows} == {PLAN_ID}
    assert len(worker.arm.payloads) == 3
    assert all(p["tags"]["neurosphere:created-by"] == "neurosphere" for p in worker.arm.payloads)


async def test_without_an_approval_nothing_is_provisioned() -> None:
    container = SharedContainer()
    api = _api(container)
    record = await api.approve(_scope(), _plan("storage"), TARGET)
    action_plan = record.action_plan()
    container.docs.clear()  # the approval is gone (e.g. never written in this container)
    worker = Worker(container, FakeArm())
    report = await worker.run(action_plan)
    assert (report.outcome, report.reason) == ("failed", "plan_not_approved")
    assert worker.arm.calls == []
    assert await worker.register.list_rows(DEPLOYMENT) == []


async def test_a_changed_plan_hash_is_refused_and_nothing_is_provisioned() -> None:
    container = SharedContainer()
    api = _api(container)
    record = await api.approve(_scope(), _plan("storage"), TARGET)
    tampered = record.action_plan().model_copy(update={"plan_hash": "sha256:" + "f" * 64})
    worker = Worker(container, FakeArm())
    report = await worker.run(tampered)
    assert (report.outcome, report.reason) == ("failed", "plan_hash_mismatch")
    assert worker.arm.calls == []
    assert await worker.register.list_rows(DEPLOYMENT) == []


async def test_the_shared_document_holds_no_secret_and_no_email() -> None:
    container = SharedContainer()
    await _api(container).approve(_scope(), _plan("storage"), TARGET)
    (doc,) = container.docs.values()
    text = json.dumps(doc).lower()
    assert "@" not in text and "token" not in text and "password" not in text
    assert doc["approver"] == "p-7f3a"
