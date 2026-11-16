"""Deploy apply on the Cosmos emulator (PRP-55 item 6, the ``integration`` twin of the in-memory
end-to-end test in ``services/workers/tests/deploy_apply_worker/test_end_to_end.py``).

The API approves into the real ``deploy_plan_approvals`` container; a separately built worker
connector (its own repository and register instances on the same database) dry-runs, applies and
verifies through a fake ARM (``httpx.MockTransport``) and writes the real ``deploy_register``
container. Without an approval or with a changed hash nothing is provisioned. Needs the compose
emulators; CI's python job skips it (``-m "not integration"``). Nothing live or paid.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from azure.core.credentials import AccessToken
from azure.cosmos.aio import CosmosClient, DatabaseProxy
from neurosphere_api.deploy.apply import PlanApprovalStore
from neurosphere_api.deploy.apply.models import ApplyTarget
from neurosphere_api.deploy.plan import DeploymentPlan, PlanCheck, PlanCost, PlanItem
from neurosphere_connector.write import WriteRequest
from neurosphere_contracts.deployment.v1.deploy_action_plan import DeployActionPlan
from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope
from neurosphere_core.capabilities import DeploymentProfile
from neurosphere_core.cloud import CloudName, profile_for
from neurosphere_core.deploy.approvals.cosmos_store import CosmosPlanApprovalRepository
from neurosphere_core.deploy.register import CustomerScopedRegister, Ownership
from neurosphere_core.deploy.register.cosmos_store import CosmosRegisterStore
from neurosphere_core.errors import ForbiddenError
from neurosphere_core.scope import IdentityScope
from neurosphere_workers.actions.deploy import DeployConnector, apply_diff, plan_target
from neurosphere_workers.actions.deploy_approvals import RepositoryPlanApprovals
from neurosphere_workers.actions.deploy_arm import HttpArmProvisioner
from neurosphere_workers.actions.deploy_http import BearerDeployHttp, deploy_scopes

pytestmark = pytest.mark.integration

CUSTOMER = "contoso"
SUB = "aaaaaaaa-0000-4000-8000-000000000001"
RG = "rg-neurosphere"
PLAN_ID = "plan-0123456789abcdef0123456789abcdef"
DEPLOYMENT = "demo-eastus2"
NOW = datetime.now(UTC)
_SCOPE = (
    Path(__file__).resolve().parents[3]
    / "packages/contracts/schemas/scope/v1/examples/valid/identity-scope.viewer.json"
)


class _Credential:
    async def get_token(self, *scopes: str, **_: Any) -> AccessToken:
        return AccessToken("fake-token-not-a-secret", 4102444800)


class _Arm:
    """Fake ARM: the resource group exists; a PUT creates synchronously (200 Succeeded)."""

    def __init__(self) -> None:
        self.resources: dict[str, dict[str, Any]] = {}
        self.calls: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.lower()
        self.calls.append(request.method)
        if "/providers/" not in path:
            return httpx.Response(200, json={})
        if request.method == "GET":
            found = self.resources.get(path)
            return httpx.Response(200, json=found) if found else httpx.Response(404, json={})
        body = {**json.loads(request.content), "properties": {"provisioningState": "Succeeded"}}
        self.resources[path] = body
        return httpx.Response(200, json=body)


def _scope() -> IdentityScope:
    payload = json.loads(_SCOPE.read_text(encoding="utf-8"))
    return IdentityScope._from_verified_contract(  # pyright: ignore[reportPrivateUsage]
        ContractScope.model_validate(payload)
    )


def _plan() -> DeploymentPlan:
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
            for service in ("storage", "monitoring")
        ],
        created_at=NOW,
    )


def _worker(client: CosmosClient, database: str, arm: _Arm) -> tuple[DeployConnector, Any]:
    profile = profile_for(CloudName.COMMERCIAL)
    http = BearerDeployHttp(
        httpx.AsyncClient(transport=httpx.MockTransport(arm.handler)),
        _Credential,  # type: ignore[arg-type]
        deploy_scopes(profile),
    )
    register = CosmosRegisterStore.from_client(
        client, database=database, container="deploy_register"
    )
    connector = DeployConnector(
        cloud=CloudName.COMMERCIAL,
        customer_id=CUSTOMER,
        approvals=RepositoryPlanApprovals(
            CosmosPlanApprovalRepository.from_client(client, database=database)
        ),
        register=CustomerScopedRegister(register, CUSTOMER),
        arm=HttpArmProvisioner(http, profile),
    )
    return connector, register


def _write(plan: DeployActionPlan) -> WriteRequest:
    return WriteRequest(
        target=plan_target("commercial", CUSTOMER, plan.plan_id),
        target_version=plan.plan_hash,
        proposed_diff=apply_diff(plan),
    )


async def test_api_approval_is_executed_verified_and_registered_by_the_worker(
    emulator: tuple[CosmosClient, DatabaseProxy],
) -> None:
    client, db = emulator
    api = PlanApprovalStore(CosmosPlanApprovalRepository.from_client(client, database=db.id))
    record = await api.approve(
        _scope(), _plan(), ApplyTarget(subscription_id=SUB, resource_group=RG, region="eastus2")
    )
    plan = (await api.record(_scope(), PLAN_ID)).action_plan()
    assert plan.plan_hash == record.approved.plan_hash

    arm = _Arm()
    connector, register = _worker(client, db.id, arm)
    request = _write(plan)
    assert (await connector.dry_run(request)).would_change is True
    await connector.apply(request)
    assert (await connector.verify(request)).matched is True
    rows = await register.list_rows(DEPLOYMENT)
    assert sorted(r.service for r in rows) == ["monitoring", "storage"]
    assert all(r.ownership is Ownership.CREATED and r.customer_id == CUSTOMER for r in rows)


async def test_no_approval_or_a_changed_hash_provisions_nothing(
    emulator: tuple[CosmosClient, DatabaseProxy],
) -> None:
    client, db = emulator
    api = PlanApprovalStore(CosmosPlanApprovalRepository.from_client(client, database=db.id))
    target = ApplyTarget(subscription_id=SUB, resource_group=RG, region="eastus2")
    unapproved = (
        await PlanApprovalStore().approve(_scope(), _plan(), target)  # another process' memory
    ).action_plan()
    arm = _Arm()
    connector, register = _worker(client, db.id, arm)
    with pytest.raises(ForbiddenError) as raised:
        await connector.apply(_write(unapproved))
    assert raised.value.reason == "plan_not_approved"

    approved = (await api.approve(_scope(), _plan(), target)).action_plan()
    tampered = approved.model_copy(update={"plan_hash": "sha256:" + "f" * 64})
    with pytest.raises(ForbiddenError) as raised:
        await connector.apply(_write(tampered))
    assert raised.value.reason == "plan_hash_mismatch"
    assert arm.calls == []
    assert await register.list_rows(DEPLOYMENT) == []
