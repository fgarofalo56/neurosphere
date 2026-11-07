"""Deploy apply / uninstall-preview adapter (PRP-08 item 12) through the real action executor.

No live or paid call: Fabric is a scripted ``RecordingFabricHttp`` and ARM a stub. The properties
under test are the fail-closed ones: no approved plan or a changed plan hash means zero HTTP
calls, the permission is rechecked at execution, an unavailable Fabric combination is
``capability_unavailable`` with zero calls, and uninstall has no delete path.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from neurosphere_connector.write import DryRunResult, WriteRequest
from neurosphere_contracts.deployment.v1.deploy_action_plan import DeployActionPlan, ResourceSpec
from neurosphere_core.actions import DraftRequest, IntentKey
from neurosphere_core.cloud import CloudName
from neurosphere_core.deploy.fabric import (
    FabricProvisioner,
    FabricResponse,
    RecordingFabricHttp,
    fabric_endpoints_for,
)
from neurosphere_core.deploy.register import (
    InMemoryRegisterStore,
    Ownership,
    ResourceRow,
    assert_removable,
    remove,
)
from neurosphere_core.errors import (
    CapabilityUnavailableError,
    ForbiddenError,
    StaleVersionError,
)
from neurosphere_workers.actions import DEPLOY_ACTION_CONNECTORS
from neurosphere_workers.actions.deploy import (
    APPLY_KIND,
    DEPLOY_CONNECTOR,
    UNINSTALL_KIND,
    ApprovedPlan,
    DeployConnector,
    FabricHttpObserver,
    ProvisionedResource,
    apply_diff,
    deployment_target,
    plan_target,
    register_digest,
    resources_digest,
    uninstall_diff,
)

from .executor_support import CUSTOMER, DOMAIN, MAKER_ID, Harness

SUB = "aaaaaaaa-0000-4000-8000-000000000001"
WS_ID = "11111111-1111-1111-1111-111111111111"
PLAN_ID = "plan-0123456789abcdef0123456789abcdef"
DEPLOYMENT = "demo-eastus2"
PLAN_HASH = "sha256:" + "a" * 64
GOV_SCOPE = "https://configured.example.us/.default"
NOW = datetime(2026, 11, 7, 12, 0, 0, tzinfo=UTC)
KEY = "idem-deploy-apply-0001"
TABLE = dict(DEPLOY_ACTION_CONNECTORS)


def _spec(kind: str, name: str, **extra: Any) -> ResourceSpec:
    base: dict[str, Any] = {
        "service": "analytics_workspace",
        "kind": kind,
        "disposition": "create",
        "name": name,
        "region": "eastus2",
        "sku": "F2" if kind == "fabric_capacity" else None,
        "resource_id": None,
        "subscription_id": SUB,
        "resource_group": "rg-neurosphere",
        "consent_reference": None,
    }
    base.update(extra)
    return ResourceSpec.model_validate(base)


def _plan(resources: list[ResourceSpec], *, cloud: str = "commercial") -> DeployActionPlan:
    return DeployActionPlan(
        schema_version="1.0.0",
        plan_id=PLAN_ID,
        plan_hash=PLAN_HASH,
        deployment_id=DEPLOYMENT,
        cloud=cloud,  # type: ignore[arg-type]
        resources=resources,
    )


FABRIC_PLAN = _plan(
    [_spec("fabric_capacity", "nsfdemoeastus2"), _spec("fabric_workspace", "neurosphere-demo")]
)


class Approvals:
    def __init__(self) -> None:
        self.items: dict[tuple[str, str], ApprovedPlan] = {}

    def approve(self, plan: DeployActionPlan, *, plan_hash: str | None = None) -> None:
        self.items[(CUSTOMER, plan.plan_id)] = ApprovedPlan(
            customer_id=CUSTOMER,
            plan_id=plan.plan_id,
            plan_hash=plan_hash or plan.plan_hash,
            resources_digest=resources_digest(plan.resources),
            deployment_id=plan.deployment_id,
        )

    async def get(self, customer_id: str, plan_id: str) -> ApprovedPlan | None:
        return self.items.get((customer_id, plan_id))


class Arm:
    def __init__(self, *, created: bool = True) -> None:
        self.created = created
        self.ensured: list[str] = []
        self.present: set[str] = set()

    async def ensure(self, spec: ResourceSpec) -> ProvisionedResource:
        self.ensured.append(spec.name)
        if self.created:
            self.present.add(spec.name)
        return ProvisionedResource(
            resource_id=f"/subscriptions/{SUB}/resourceGroups/rg/providers/Microsoft.Foo/bars/{spec.name}",
            created=self.created,
        )

    async def exists(self, spec: ResourceSpec) -> bool:
        return spec.name in self.present


class Setup:
    def __init__(
        self,
        cloud: CloudName = CloudName.COMMERCIAL,
        *,
        with_arm: Arm | None = None,
        with_fabric: bool = True,
    ) -> None:
        self.http = RecordingFabricHttp()
        self.approvals = Approvals()
        self.register = InMemoryRegisterStore()
        endpoints = fabric_endpoints_for(
            cloud, token_scope=GOV_SCOPE if cloud is CloudName.GOVERNMENT else None
        )
        self.connector = DeployConnector(
            cloud=cloud,
            approvals=self.approvals,
            register=self.register,
            fabric=FabricProvisioner(self.http, endpoints) if with_fabric else None,
            observer=FabricHttpObserver(self.http, endpoints) if with_fabric else None,
            arm=with_arm,
        )

    def script_fabric_apply_and_verify(self) -> None:
        ok = FabricResponse
        self.http.enqueue(
            ok(404),  # apply: capacity GET (absent)
            ok(201, {}),  # apply: capacity PUT
            ok(200, {"value": []}),  # apply: workspace lookup
            ok(201, {"id": WS_ID}),  # apply: workspace POST
            ok(200, {}),  # verify (canary): capacity GET
            ok(200, {"value": [{"displayName": "neurosphere-demo", "id": WS_ID}]}),
            ok(200, {}),  # verify (read-back): capacity GET
            ok(200, {"value": [{"displayName": "neurosphere-demo", "id": WS_ID}]}),
        )


def _draft(
    plan: DeployActionPlan,
    *,
    kind: str = APPLY_KIND,
    version: str | None = None,
    cloud: str = "commercial",
) -> DraftRequest:
    diff = apply_diff(plan)
    return DraftRequest.model_validate(
        {
            "action_kind": kind,
            "target": plan_target(cloud, CUSTOMER, plan.plan_id).model_dump(mode="json"),
            "target_version": version or plan.plan_hash,
            "proposed_diff": diff.model_dump(mode="json", by_alias=True, exclude_none=True),
            "evidence": [],
            "idempotency_key": KEY,
            "channel": "rest",
            "dry_run": False,
        }
    )


def _harness(setup: Setup) -> Harness:
    return Harness(connector=setup.connector)  # type: ignore[arg-type]


async def _run(h: Harness, request: DraftRequest) -> Any:
    key: IntentKey = await h.executing(request)
    return await h.executor(table=TABLE).execute(key)


def _write(plan: DeployActionPlan, version: str | None = None) -> WriteRequest:
    return WriteRequest(
        target=plan_target(plan.cloud, CUSTOMER, plan.plan_id),
        target_version=version or plan.plan_hash,
        proposed_diff=apply_diff(plan),
    )


# -- registration ----------------------------------------------------------------------------------


def test_the_connector_is_a_registrable_write_target_for_both_kinds() -> None:
    h = _harness(Setup())
    assert h.registry.supports(DEPLOY_CONNECTOR, APPLY_KIND)
    assert h.registry.supports(DEPLOY_CONNECTOR, UNINSTALL_KIND)
    assert TABLE == {APPLY_KIND: DEPLOY_CONNECTOR, UNINSTALL_KIND: DEPLOY_CONNECTOR}


# -- apply through the executor ---


async def test_approved_plan_is_applied_verified_and_recorded() -> None:
    setup = Setup()
    setup.approvals.approve(FABRIC_PLAN)
    setup.script_fabric_apply_and_verify()
    h = _harness(setup)
    report = await _run(h, _draft(FABRIC_PLAN))
    assert (report.outcome, report.state, report.reason) == ("succeeded", "succeeded", None)
    stored = await h.current(IntentKey(CUSTOMER, DOMAIN, report.intent_id))
    assert stored.execution is not None and stored.execution.verify_matched is True
    methods = [c.method for c in setup.http.calls]
    assert methods == ["GET", "PUT", "GET", "POST", "GET", "GET", "GET", "GET"]
    rows = await setup.register.list_rows(DEPLOYMENT)
    assert [(r.service, r.ownership, r.created_by) for r in rows] == [
        ("analytics_workspace", Ownership.CREATED, "neurosphere")
    ]
    assert rows[0].creating_plan_id == PLAN_ID


async def test_unapproved_plan_is_refused_with_zero_calls() -> None:
    setup = Setup()
    h = _harness(setup)
    report = await _run(h, _draft(FABRIC_PLAN))
    assert (report.outcome, report.reason) == ("failed", "plan_not_approved")
    assert setup.http.calls == []
    assert await setup.register.list_rows(DEPLOYMENT) == []


async def test_changed_plan_hash_is_refused_with_zero_calls() -> None:
    setup = Setup()
    setup.approvals.approve(FABRIC_PLAN, plan_hash="sha256:" + "b" * 64)  # approved another plan
    h = _harness(setup)
    report = await _run(h, _draft(FABRIC_PLAN))
    assert (report.outcome, report.reason) == ("failed", "plan_hash_mismatch")
    assert setup.http.calls == []


async def test_target_version_that_is_not_the_plan_hash_is_refused() -> None:
    setup = Setup()
    setup.approvals.approve(FABRIC_PLAN)
    h = _harness(setup)
    report = await _run(h, _draft(FABRIC_PLAN, version="sha256:" + "c" * 64))
    assert (report.outcome, report.reason) == ("failed", "plan_hash_mismatch")
    assert setup.http.calls == []


async def test_resources_that_differ_from_the_approved_ones_are_refused() -> None:
    setup = Setup()
    setup.approvals.approve(FABRIC_PLAN)
    tampered = _plan(
        [_spec("fabric_capacity", "nsfdemoeastus2", sku="F2048"), FABRIC_PLAN.resources[1]]
    )
    h = _harness(setup)
    report = await _run(h, _draft(tampered))
    assert (report.outcome, report.reason) == ("failed", "resources_not_approved")
    assert setup.http.calls == []


async def test_permission_is_rechecked_at_execution() -> None:
    setup = Setup()
    setup.approvals.approve(FABRIC_PLAN)
    setup.script_fabric_apply_and_verify()
    h = _harness(setup)
    key = await h.executing(_draft(FABRIC_PLAN))
    h.rechecker.revoke(MAKER_ID, CUSTOMER, DOMAIN, "action.execute")
    report = await h.executor(table=TABLE).execute(key)
    assert (report.outcome, report.reason) == ("failed", "permission_revoked")
    assert setup.http.calls == []
    assert ("action.execute", "permission_revoked") in h.denials()


async def test_fabric_unavailable_is_capability_unavailable_with_zero_calls() -> None:
    gov_plan = _plan(
        [
            _spec("fabric_capacity", "nsfdemoarizona", region="usgovarizona"),
            _spec("fabric_workspace", "neurosphere-gov", region="usgovarizona"),
        ],
        cloud="government",
    )
    setup = Setup(CloudName.GOVERNMENT)
    setup.approvals.approve(gov_plan)
    with pytest.raises(CapabilityUnavailableError):
        await setup.connector.dry_run(_write(gov_plan))
    with pytest.raises(CapabilityUnavailableError):
        await setup.connector.apply(_write(gov_plan))
    assert setup.http.calls == []

    # Through the executor (Commercial region the shipped matrix does not list).
    commercial = _plan([_spec("fabric_workspace", "neurosphere-demo", region="swedensouth")])
    live = Setup()
    live.approvals.approve(commercial)
    report = await _run(_harness(live), _draft(commercial))
    assert (report.outcome, report.reason) == ("failed", "capability_unavailable")
    assert live.http.calls == []


async def test_commercial_region_missing_from_the_matrix_makes_no_calls() -> None:
    plan = _plan([_spec("fabric_workspace", "neurosphere-demo", region="swedensouth")])
    setup = Setup()
    setup.approvals.approve(plan)
    with pytest.raises(CapabilityUnavailableError) as raised:
        await setup.connector.dry_run(_write(plan))
    assert raised.value.reason == "capability_unavailable"
    assert setup.http.calls == []


async def test_other_cloud_plan_is_never_bridged() -> None:
    gov_plan = _plan([_spec("fabric_workspace", "w", region="usgovvirginia")], cloud="government")
    setup = Setup(CloudName.COMMERCIAL)
    setup.approvals.approve(gov_plan)
    with pytest.raises(ForbiddenError) as raised:
        await setup.connector.dry_run(_write(gov_plan))
    assert raised.value.reason == "cloud_mismatch"
    assert setup.http.calls == []


async def test_arm_item_without_a_provisioner_is_capability_unavailable() -> None:
    plan = _plan([_spec("arm_resource", "kv-demo", service="key_vault")])
    setup = Setup()
    setup.approvals.approve(plan)
    with pytest.raises(CapabilityUnavailableError):
        await setup.connector.dry_run(_write(plan))


async def test_existing_resources_are_never_claimed_as_created() -> None:
    setup = Setup()
    setup.approvals.approve(FABRIC_PLAN)
    setup.http.enqueue(FabricResponse(200, {}))  # capacity GET: it already exists
    with pytest.raises(ForbiddenError) as raised:
        await setup.connector.apply(_write(FABRIC_PLAN))
    assert raised.value.reason == "resource_exists_not_owned"
    assert [c.method for c in setup.http.calls] == ["GET"]  # no PUT
    assert await setup.register.list_rows(DEPLOYMENT) == []


async def test_arm_resource_is_created_through_the_injected_provisioner_and_registered() -> None:
    arm = Arm()
    plan = _plan([_spec("arm_resource", "kv-demo", service="key_vault")])
    setup = Setup(with_arm=arm, with_fabric=False)
    setup.approvals.approve(plan)
    h = _harness(setup)
    report = await _run(h, _draft(plan))
    assert (report.outcome, report.state) == ("succeeded", "succeeded")
    assert arm.ensured == ["kv-demo"]
    [row] = await setup.register.list_rows(DEPLOYMENT)
    assert row.ownership is Ownership.CREATED


async def test_pretend_apply_is_caught_by_verify() -> None:
    arm = Arm(created=True)
    plan = _plan([_spec("arm_resource", "kv-demo", service="key_vault")])
    setup = Setup(with_arm=arm, with_fabric=False)
    setup.approvals.approve(plan)
    await setup.connector.apply(_write(plan))
    arm.present.clear()  # the resource is not really there
    verified = await setup.connector.verify(_write(plan))
    assert verified.matched is False
    assert verified.mismatched_paths == ("/resources/key_vault.arm_resource",)


async def test_reused_resource_is_recorded_as_reused_and_never_touched() -> None:
    rid = f"/subscriptions/{SUB}/resourceGroups/rg-shared/providers/Microsoft.KeyVault/vaults/kv"
    plan = _plan(
        [
            _spec(
                "arm_resource",
                "kv",
                service="key_vault",
                disposition="reuse",
                resource_id=rid,
                consent_reference="consent-owner-0001",
                subscription_id=None,
                resource_group=None,
            )
        ]
    )
    setup = Setup(with_fabric=False)
    setup.approvals.approve(plan)
    await setup.connector.apply(_write(plan))
    [row] = await setup.register.list_rows(DEPLOYMENT)
    assert (row.ownership, row.created_by, row.consent_reference) == (
        Ownership.REUSED,
        None,
        "consent-owner-0001",
    )
    assert (await setup.connector.verify(_write(plan))).matched is True
    assert setup.http.calls == []


async def test_no_automatic_rollback() -> None:
    setup = Setup()
    applied = type("A", (), {})()
    with pytest.raises(CapabilityUnavailableError) as raised:
        await setup.connector.rollback(applied)  # type: ignore[arg-type]
    assert raised.value.reason == "rollback_not_supported"


# -- uninstall: dry run only, R1 guard ---


def _row(rid: str, ownership: Ownership, **extra: Any) -> ResourceRow:
    created = ownership is Ownership.CREATED
    base: dict[str, Any] = {
        "deployment_id": DEPLOYMENT,
        "resource_id": rid,
        "service": "storage",
        "ownership": ownership,
        "created_by": "neurosphere" if created else None,
        "owner": "svc.neurosphere-actions",
        "consent_reference": None if created else "consent-owner-0001",
        "creating_plan_id": PLAN_ID,
        "recorded_at": NOW,
    }
    base.update(extra)
    return ResourceRow.model_validate(base)


RG = f"/subscriptions/{SUB}/resourceGroups/rg-ns"
OWN = f"{RG}/providers/Microsoft.Storage/storageAccounts/own"
REUSED = f"/subscriptions/{SUB}/resourceGroups/rg-shared/providers/Microsoft.KeyVault/vaults/kv"
SHARED = (
    f"/subscriptions/{SUB}/resourceGroups/rg-shared/providers/Microsoft.Search/searchServices/s"
)


async def _seed(setup: Setup, *, with_group: bool = False) -> list[ResourceRow]:
    rows = [
        _row(OWN, Ownership.CREATED),
        _row(REUSED, Ownership.REUSED),
        _row(SHARED, Ownership.SHARED),
    ]
    if with_group:
        rows.append(_row(RG, Ownership.CREATED))
    for row in rows:
        await setup.register.put_row(row)
    return rows


def _uninstall_request(rows: list[ResourceRow], *, version: str | None = None) -> WriteRequest:
    digest = register_digest(rows)
    return WriteRequest(
        target=deployment_target("commercial", CUSTOMER, DEPLOYMENT),
        target_version=version or digest,
        proposed_diff=uninstall_diff(digest, []),
    )


async def test_uninstall_preview_lists_reused_and_shared_as_untouched() -> None:
    setup = Setup()
    rows = await _seed(setup)
    planned = await setup.connector.dry_run(_uninstall_request(rows))
    assert isinstance(planned, DryRunResult) and planned.would_change is False
    removable = [op.path for op in planned.planned_diff.operations if op.op == "remove"]
    assert removable == [f"/resources/{OWN.replace('/', '~1')}"]
    assert REUSED.replace("/", "~1") not in " ".join(removable)
    assert SHARED.replace("/", "~1") not in " ".join(removable)


async def test_uninstall_apply_is_refused_and_no_delete_path_exists() -> None:
    setup = Setup()
    rows = await _seed(setup)
    with pytest.raises(ForbiddenError) as raised:
        await setup.connector.apply(_uninstall_request(rows))
    assert raised.value.reason == "uninstall_dry_run_only"
    assert not any("delet" in name.lower() for name in dir(setup.connector))
    assert setup.http.calls == []


async def test_the_guard_refuses_reused_and_shared_rows() -> None:
    setup = Setup()
    rows = await _seed(setup)
    for row in rows[1:]:
        with pytest.raises(ForbiddenError):
            assert_removable(row, rows)
    deleted: list[str] = []

    class Deleter:
        async def delete(self, resource_id: str) -> None:
            deleted.append(resource_id)

    await remove(DEPLOYMENT, [r for r in rows if r.ownership is not Ownership.CREATED], Deleter())
    assert deleted == []


async def test_resource_group_needs_the_live_inventory_check() -> None:
    setup = Setup()
    rows = await _seed(setup, with_group=True)
    unverified = await setup.connector.dry_run(_uninstall_request(rows))
    assert unverified.would_change is False

    class Foreign:
        async def list_resource_group(self, rg_id: str) -> list[str]:
            return [OWN, f"{RG}/providers/Microsoft.Web/sites/someone-elses"]

    class Broken:
        async def list_resource_group(self, rg_id: str) -> list[str]:
            raise RuntimeError("ARM down")

    for inventory in (Foreign(), Broken()):
        guarded = DeployConnector(
            cloud=CloudName.COMMERCIAL,
            approvals=setup.approvals,
            register=setup.register,
            inventory=inventory,
        )
        planned = await guarded.dry_run(_uninstall_request(rows))
        paths = [op.path for op in planned.planned_diff.operations]
        assert f"/resources/{RG.replace('/', '~1')}" not in paths

    class Clean:
        async def list_resource_group(self, rg_id: str) -> list[str]:
            return [OWN]

    verified = DeployConnector(
        cloud=CloudName.COMMERCIAL,
        approvals=setup.approvals,
        register=setup.register,
        inventory=Clean(),
    )
    planned = await verified.dry_run(_uninstall_request(rows))
    assert f"/resources/{RG.replace('/', '~1')}" in [
        op.path for op in planned.planned_diff.operations
    ]


async def test_uninstall_against_a_changed_register_is_stale() -> None:
    setup = Setup()
    rows = await _seed(setup)
    with pytest.raises(StaleVersionError):
        await setup.connector.dry_run(_uninstall_request(rows, version="sha256:" + "d" * 64))


async def test_uninstall_intent_runs_as_a_dry_run_through_the_executor() -> None:
    setup = Setup()
    rows = await _seed(setup)
    digest = register_digest(rows)
    request = DraftRequest.model_validate(
        {
            "action_kind": UNINSTALL_KIND,
            "target": deployment_target("commercial", CUSTOMER, DEPLOYMENT).model_dump(mode="json"),
            "target_version": digest,
            "proposed_diff": uninstall_diff(digest, [OWN]).model_dump(
                mode="json", by_alias=True, exclude_none=True
            ),
            "evidence": [],
            "idempotency_key": "idem-deploy-uninstall-01",
            "channel": "rest",
            "dry_run": True,
        }
    )
    h = _harness(setup)
    report = await _run(h, request)
    assert (report.outcome, report.state) == ("succeeded", "succeeded")
    assert setup.http.calls == []
    assert len(await setup.register.list_rows(DEPLOYMENT)) == 3  # nothing removed


async def test_uninstall_intent_that_is_not_a_dry_run_cannot_delete() -> None:
    setup = Setup()
    rows = await _seed(setup)
    digest = register_digest(rows)
    request = DraftRequest.model_validate(
        {
            "action_kind": UNINSTALL_KIND,
            "target": deployment_target("commercial", CUSTOMER, DEPLOYMENT).model_dump(mode="json"),
            "target_version": digest,
            "proposed_diff": uninstall_diff(digest, [OWN]).model_dump(
                mode="json", by_alias=True, exclude_none=True
            ),
            "evidence": [],
            "idempotency_key": "idem-deploy-uninstall-02",
            "channel": "rest",
            "dry_run": False,
        }
    )
    h = _harness(setup)
    report = await _run(h, request)
    assert report.outcome == "failed"
    assert len(await setup.register.list_rows(DEPLOYMENT)) == 3
    assert setup.http.calls == []
