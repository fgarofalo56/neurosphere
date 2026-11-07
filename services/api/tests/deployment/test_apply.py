"""Plan approval, apply and uninstall preview through the action plane (PRP-08 item 12).

Real authz stack and real ``ActionService`` over in-memory stores (the PRP-17 harness); the deploy
write connector is registered under the core action table. Fabric is a recording stub that must
see ZERO calls: the API only drafts, and the executor worker applies. Nothing live or paid.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any

import neurosphere_core.actions.targets as core_targets
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "actions_api"))

from action_plane_harness import (  # pyright: ignore[reportMissingImports]
    ALICE,
    CAROL,
    CUSTOMER,
    DAVE,
    FINANCE,
    Api,
    make_api,
    principal,
)
from neurosphere_api.authz import route_inventory, undeclared_routes
from neurosphere_api.deploy.apply import (
    ROUTE_PREFIX,
    PlanApprovalStore,
    build_router,
    configure_apply,
    plan_hash,
)
from neurosphere_api.deploy.plan import DeploymentPlan, PlanCheck, PlanCost, PlanItem
from neurosphere_api.deploy.scan.audit import audit_chain
from neurosphere_core.capabilities import DeploymentProfile
from neurosphere_core.cloud import CloudName
from neurosphere_core.deploy.fabric import (
    FabricProvisioner,
    RecordingFabricHttp,
    fabric_endpoints_for,
)
from neurosphere_core.deploy.register import (
    CustomerScopedRegister,
    InMemoryRegisterStore,
    Ownership,
    ResourceRow,
    assert_removable,
)
from neurosphere_core.errors import ForbiddenError
from neurosphere_workers.actions.deploy import (
    DeployConnector,
    FabricHttpObserver,
)

SUB = "aaaaaaaa-0000-4000-8000-000000000001"
PLAN_ID = "plan-0123456789abcdef0123456789abcdef"
DEPLOYMENT = "demo-eastus2"
NOW = datetime(2026, 11, 7, 12, 0, 0, tzinfo=UTC)
BASE = f"{ROUTE_PREFIX}/domains/{FINANCE}"
KEY = "idem-deploy-apply-0001"
RG = f"/subscriptions/{SUB}/resourceGroups/rg-ns"
OWN = f"{RG}/providers/Microsoft.Storage/storageAccounts/own"
REUSED = f"/subscriptions/{SUB}/resourceGroups/rg-shared/providers/Microsoft.KeyVault/vaults/kv"
SHARED = (
    f"/subscriptions/{SUB}/resourceGroups/rg-shared/providers/Microsoft.Search/searchServices/s"
)
TARGET = {
    "subscription_id": SUB,
    "resource_group": "rg-neurosphere",
    "region": "eastus2",
    "capacity_sku": "F2",
}


def _plan(
    *, region: str = "eastus2", plan_id: str = PLAN_ID, status: str = "create"
) -> DeploymentPlan:
    return DeploymentPlan(
        plan_id=plan_id,
        deployment_id=DEPLOYMENT,
        profile=DeploymentProfile(
            cloud="commercial", regions=(region,), hosting="aks", analytics="fabric"
        ),
        items=[
            PlanItem(
                service="analytics_workspace",
                status=status,  # type: ignore[arg-type]
                cost_implication=PlanCost(basis="unknown"),
                checks=[PlanCheck(name="sku", outcome="pass", reason="ok")],
            )
        ],
        created_at=NOW,
    )


def _approve_body(plan: DeploymentPlan, target: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"plan": plan.model_dump(mode="json"), "target": target or TARGET}


class Setup:
    def __init__(self, api: Api) -> None:
        self.api = api
        self.http = RecordingFabricHttp()
        self.approvals = PlanApprovalStore(clock=lambda: NOW)
        self.register = InMemoryRegisterStore()
        endpoints = fabric_endpoints_for(CloudName.COMMERCIAL)
        connector = DeployConnector(
            cloud=CloudName.COMMERCIAL,
            approvals=self.approvals,
            register=CustomerScopedRegister(self.register, CUSTOMER),
            fabric=FabricProvisioner(self.http, endpoints),
            observer=FabricHttpObserver(self.http, endpoints),
        )
        api.registry.register(connector)
        app = api.h.app
        app.include_router(build_router(), prefix=ROUTE_PREFIX)
        configure_apply(app, approvals=self.approvals, register=self.register)
        for permission in ("action.propose", "action.execute", "action.approve"):
            api.rechecker.grant(principal(DAVE), CUSTOMER, FINANCE, permission)

    def post(self, path: str, body: Any, who: str | None = DAVE) -> Any:
        return self.api._send("POST", who, f"{BASE}{path}", json=body)  # pyright: ignore[reportPrivateUsage]

    def approve(self, plan: DeploymentPlan | None = None, **kw: Any) -> Any:
        return self.post("/plans/approve", _approve_body(plan or _plan(), **kw))

    def apply(self, plan_hash_value: str, plan_id: str = PLAN_ID, key: str = KEY) -> Any:
        return self.post(
            "/plans/apply",
            {"plan_id": plan_id, "plan_hash": plan_hash_value, "idempotency_key": key},
        )

    async def seed_register(
        self, *, with_group: bool = False, customer: str | None = CUSTOMER
    ) -> None:
        rows = [
            _row(OWN, Ownership.CREATED, customer),
            _row(REUSED, Ownership.REUSED, customer),
            _row(SHARED, Ownership.SHARED, customer),
        ]
        if with_group:
            rows.append(_row(RG, Ownership.CREATED, customer))
        for row in rows:
            await self.register.put_row(row)


def _apply_package_source() -> str:
    package = Path(__file__).resolve().parents[2] / "neurosphere_api" / "deploy" / "apply"
    return "\n".join(p.read_text(encoding="utf-8") for p in package.glob("*.py"))


def _row(rid: str, ownership: Ownership, customer: str | None = CUSTOMER) -> ResourceRow:
    created = ownership is Ownership.CREATED
    return ResourceRow.model_validate(
        {
            "deployment_id": DEPLOYMENT,
            "customer_id": customer,
            "resource_id": rid,
            "service": "storage",
            "ownership": ownership,
            "created_by": "neurosphere" if created else None,
            "owner": "svc.neurosphere-actions",
            "consent_reference": None if created else "consent-owner-0001",
            "creating_plan_id": PLAN_ID,
            "recorded_at": NOW,
        }
    )


@pytest.fixture
def setup() -> Iterator[Setup]:
    # The deploy kinds resolve through the real core action table (PRP-08 item 14): no patching.
    yield Setup(make_api())


async def _events(setup: Setup) -> list[Any]:
    return await setup.api.audit.read_range(audit_chain(CUSTOMER))


# -- approve ---


def test_approve_records_the_hash_and_the_exact_resources(setup: Setup) -> None:
    plan = _plan()
    response = setup.approve(plan)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["plan_hash"] == plan_hash(plan)
    assert [(r["kind"], r["disposition"]) for r in body["resources"]] == [
        ("fabric_capacity", "create"),
        ("fabric_workspace", "create"),
    ]
    assert body["resources"][0]["sku"] == "F2"
    assert setup.http.calls == []


async def test_approve_is_audited_without_resource_ids(setup: Setup) -> None:
    assert setup.approve().status_code == 201
    events = await _events(setup)
    approved = [e for e in events if e.operation == "deploy.apply.approve"]
    assert len(approved) == 1 and approved[0].outcome.detail == "plan_approved"
    assert SUB not in approved[0].model_dump_json()


def test_approve_refuses_unresolved_or_foreign_input(setup: Setup) -> None:
    needs = setup.approve(_plan(status="needs_consent"))
    assert needs.status_code == 422
    assert needs.json()["reason"] == "plan_has_unresolved_items"
    wrong_region = setup.approve(_plan(), target={**TARGET, "region": "westus2"})
    assert wrong_region.json()["reason"] == "region_not_in_plan"
    smuggled = setup.post("/plans/approve", {**_approve_body(_plan()), "customer_id": "fabrikam"})
    assert smuggled.status_code == 422


def test_a_different_plan_under_the_same_id_is_refused(setup: Setup) -> None:
    assert setup.approve(_plan()).status_code == 201
    changed = _plan(status="skip").model_copy(update={"deployment_id": "other-deployment"})
    conflict = setup.approve(changed)
    assert conflict.status_code == 422 and conflict.json()["reason"] == "plan_id_conflict"


# -- apply ---


def test_apply_without_an_approved_plan_is_refused_and_drafts_nothing(setup: Setup) -> None:
    response = setup.apply(plan_hash(_plan()))
    assert response.status_code == 403
    assert response.json()["reason"] == "plan_not_approved"
    assert setup.api.get_intent("00000000-0000-4000-8000-000000000001").status_code == 404
    assert setup.http.calls == []


def test_apply_with_a_changed_plan_hash_is_refused(setup: Setup) -> None:
    assert setup.approve().status_code == 201
    response = setup.apply("sha256:" + "0" * 64)
    assert response.status_code == 422
    assert response.json()["reason"] == "plan_hash_mismatch"


def test_apply_drafts_the_exact_intent_and_stays_inside_the_action_plane(setup: Setup) -> None:
    plan = _plan()
    digest = setup.approve(plan).json()["plan_hash"]
    response = setup.apply(digest)
    assert response.status_code == 201, response.text
    view = response.json()["action"]
    intent = view["intent"]
    assert intent["action_kind"] == "deploy_plan_apply"
    assert intent["state"] == "drafted" and intent["dry_run"] is False
    assert intent["target_version"] == digest
    assert (
        intent["target"]["canonical_id"]
        == f"commercial:{CUSTOMER}:deploy:deployment_plan:{PLAN_ID}"
    )
    ops = {op["path"]: op for op in intent["proposed_diff"]["operations"]}
    assert ops["/plan_hash"]["value"] == digest
    assert "/resources/analytics_workspace.fabric_capacity" in ops
    assert view["advisory"] is False
    # The intent lives in the shared action plane (validation, confirmation, approval and the
    # executor worker take it from here), not in a deploy-specific store.
    fetched = setup.api.get_intent(intent["intent_id"], who=DAVE)
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["intent"]["confirmation_hash"] is None
    assert setup.http.calls == []  # the API never calls Fabric


def test_apply_is_idempotent_per_key(setup: Setup) -> None:
    digest = setup.approve().json()["plan_hash"]
    first = setup.apply(digest)
    second = setup.apply(digest)
    assert (
        first.json()["action"]["intent"]["intent_id"]
        == second.json()["action"]["intent"]["intent_id"]
    )


def test_fabric_unavailable_is_capability_unavailable_with_zero_calls(setup: Setup) -> None:
    plan = _plan(region="swedensouth")
    digest = setup.approve(plan, target={**TARGET, "region": "swedensouth"}).json()["plan_hash"]
    response = setup.apply(digest)
    assert response.status_code == 409
    assert response.json()["code"] == "capability_unavailable"
    assert setup.http.calls == []


async def test_apply_requests_and_refusals_are_audited(setup: Setup) -> None:
    digest = setup.approve().json()["plan_hash"]
    assert setup.apply(digest).status_code == 201
    assert setup.apply("sha256:" + "1" * 64, key="idem-deploy-apply-0002").status_code == 422
    events = await _events(setup)
    kinds = [(e.kind, e.operation) for e in events if e.operation.startswith("deploy.apply")]
    assert ("after", "deploy.apply.request") in kinds
    assert ("denied", "deploy.apply.request") in kinds


# -- uninstall preview ---


async def test_uninstall_preview_lists_reused_and_shared_as_untouched(setup: Setup) -> None:
    await setup.seed_register()
    response = setup.post(
        "/uninstall/preview",
        {"deployment_id": DEPLOYMENT, "idempotency_key": "idem-deploy-uninstall-01"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["dry_run"] is True
    assert [e["resource_id"] for e in body["removable"]] == [OWN]
    untouched = {e["resource_id"]: e for e in body["untouched"]}
    assert set(untouched) == {REUSED, SHARED}
    assert all("never removed" in (e["reason"] or "") for e in untouched.values())
    intent = body["action"]["intent"]
    assert intent["action_kind"] == "deploy_uninstall" and intent["dry_run"] is True
    assert intent["target_version"] == body["register_digest"]
    assert setup.http.calls == []


async def test_uninstall_has_no_reachable_delete_path(setup: Setup) -> None:
    await setup.seed_register()
    rows = await setup.register.list_rows(DEPLOYMENT)
    for row in rows:
        if row.ownership is not Ownership.CREATED:
            with pytest.raises(ForbiddenError):
                assert_removable(row, rows)
    # The body cannot clear dry_run, and the module imports no deleter or remove().
    forced = setup.post(
        "/uninstall/preview",
        {
            "deployment_id": DEPLOYMENT,
            "idempotency_key": "idem-deploy-uninstall-02",
            "dry_run": False,
        },
    )
    assert forced.status_code == 422
    source = _apply_package_source()
    assert "ResourceDeleter" not in source and "import remove" not in source
    assert ".delete(" not in source and "ArmDeleter" not in source


async def test_uninstall_of_an_unknown_deployment_is_refused(setup: Setup) -> None:
    response = setup.post(
        "/uninstall/preview",
        {"deployment_id": "nope-nope", "idempotency_key": "idem-deploy-uninstall-03"},
    )
    assert response.status_code == 422 and response.json()["reason"] == "deployment_not_found"


async def test_uninstall_live_verification_needs_the_inventory(setup: Setup) -> None:
    await setup.seed_register(with_group=True)
    body = {
        "deployment_id": DEPLOYMENT,
        "idempotency_key": "idem-deploy-uninstall-04",
        "verify_live": True,
    }
    missing = setup.post("/uninstall/preview", body)
    assert missing.status_code == 409
    assert missing.json()["reason"] == "live_inventory_not_configured"

    class Foreign:
        async def list_resource_group(self, rg_id: str) -> list[str]:
            return [OWN, f"{RG}/providers/Microsoft.Web/sites/someone-elses"]

    setup.api.h.app.state.deploy_live_inventory = Foreign()
    guarded = setup.post("/uninstall/preview", body)
    assert guarded.status_code == 201, guarded.text
    data = guarded.json()
    assert RG not in [e["resource_id"] for e in data["removable"]]
    assert any(e["resource_id"] == RG for e in data["untouched"])


# -- authorization, wiring, inventory ---


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/plans/approve", None),
        (
            "/plans/apply",
            {"plan_id": PLAN_ID, "plan_hash": "sha256:" + "0" * 64, "idempotency_key": KEY},
        ),
        ("/uninstall/preview", {"deployment_id": DEPLOYMENT, "idempotency_key": KEY}),
    ],
)
def test_config_manage_is_required_on_every_route(
    setup: Setup, path: str, body: dict[str, Any] | None
) -> None:
    payload = body if body is not None else _approve_body(_plan())
    for who in (CAROL, ALICE):  # viewer; steward without config.manage
        assert setup.post(path, payload, who=who).status_code == 403
    assert setup.post(path, payload, who=None).status_code == 401
    assert setup.http.calls == []


def test_unconfigured_apply_fails_closed() -> None:
    api = make_api()
    api.h.app.include_router(build_router(), prefix=ROUTE_PREFIX)
    response = api._send(  # pyright: ignore[reportPrivateUsage]
        "POST", DAVE, f"{BASE}/plans/approve", json=_approve_body(_plan())
    )
    assert response.status_code == 503 and response.json()["reason"] == "apply_not_configured"


def test_routes_are_declared_in_the_authz_inventory(setup: Setup) -> None:
    app = setup.api.h.app
    assert undeclared_routes(app) == ()
    mine = [e for e in route_inventory(app) if e.path.startswith(ROUTE_PREFIX)]
    assert {e.path for e in mine} == {
        f"{ROUTE_PREFIX}/domains/{{domain}}/plans/approve",
        f"{ROUTE_PREFIX}/domains/{{domain}}/plans/apply",
        f"{ROUTE_PREFIX}/domains/{{domain}}/uninstall/preview",
    }
    assert all(e.permissions == ("config.manage",) and not e.public for e in mine)


def test_the_router_is_registered_by_default() -> None:
    from neurosphere_api.routers import RouterRegistry, register_default_routers

    registry = RouterRegistry()
    register_default_routers(registry)
    assert ROUTE_PREFIX in registry.prefixes


# -- production wiring (PRP-08 item 14) ---


def test_deploy_kinds_resolve_through_the_real_action_table(setup: Setup) -> None:
    assert core_targets.connector_name_for("deploy_plan_apply") == "deploy-orchestrator"
    assert core_targets.connector_name_for("deploy_uninstall") == "deploy-orchestrator"
    digest = setup.approve().json()["plan_hash"]
    applied = setup.apply(digest)
    assert applied.status_code == 201, applied.text
    assert applied.json()["action"]["advisory"] is False  # a connector resolved


def test_configure_apply_without_connector_rows_is_unsupported_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """configure_apply alone is not enough: without ACTION_CONNECTORS rows no connector resolves,
    and apply refuses with ``write_connector_unsupported_target`` (never a pretend draft)."""
    without = MappingProxyType(
        {k: v for k, v in core_targets.ACTION_CONNECTORS.items() if not k.startswith("deploy_")}
    )
    monkeypatch.setattr(core_targets, "ACTION_CONNECTORS", without)
    bare = Setup(make_api())
    digest = bare.approve().json()["plan_hash"]
    applied = bare.apply(digest)
    assert applied.status_code == 409, applied.text
    assert "write_connector_unsupported_target" in applied.text


async def test_uninstall_preview_is_customer_scoped_and_leaks_no_existence(setup: Setup) -> None:
    await setup.seed_register(customer="fabrikam")  # another customer's deployment, same id
    body = {"deployment_id": DEPLOYMENT, "idempotency_key": "idem-deploy-uninstall-05"}
    foreign = setup.post("/uninstall/preview", body)
    unknown = setup.post(
        "/uninstall/preview",
        {"deployment_id": "nope-nope", "idempotency_key": "idem-deploy-uninstall-06"},
    )
    assert foreign.status_code == unknown.status_code == 422
    assert foreign.json()["reason"] == unknown.json()["reason"] == "deployment_not_found"
    assert foreign.json()["detail"] == unknown.json()["detail"]
    assert OWN not in foreign.text and REUSED not in foreign.text


async def test_rows_without_a_customer_are_visible_to_no_one(setup: Setup) -> None:
    await setup.seed_register(customer=None)  # written before the field existed
    response = setup.post(
        "/uninstall/preview",
        {"deployment_id": DEPLOYMENT, "idempotency_key": "idem-deploy-uninstall-07"},
    )
    assert response.status_code == 422 and response.json()["reason"] == "deployment_not_found"


async def test_preview_sees_only_the_callers_rows_of_a_shared_deployment_id(setup: Setup) -> None:
    await setup.seed_register()
    theirs = f"{RG}/providers/Microsoft.Storage/storageAccounts/theirs"
    await setup.register.put_row(_row(theirs, Ownership.CREATED, "fabrikam"))
    response = setup.post(
        "/uninstall/preview",
        {"deployment_id": DEPLOYMENT, "idempotency_key": "idem-deploy-uninstall-08"},
    )
    assert response.status_code == 201, response.text
    assert "theirs" not in response.text


def test_approval_store_logs_eviction_without_secrets(
    setup: Setup, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from neurosphere_api.deploy.apply import approvals as approvals_module

    monkeypatch.setattr(approvals_module, "_MAX_ENTRIES", 1)
    first, second = "plan-0123456789abcdef0123456789abcde1", "plan-0123456789abcdef0123456789abcde2"
    with caplog.at_level(logging.WARNING, logger="neurosphere_api.deploy.apply"):
        assert setup.approve(_plan(plan_id=first)).status_code == 201
        assert setup.approve(_plan(plan_id=second)).status_code == 201
    evictions = [r for r in caplog.records if getattr(r, "event", "") == "deploy.approval_evicted"]
    assert len(evictions) == 1
    assert evictions[0].plan_id == first  # type: ignore[attr-defined]  # pyright: ignore
    assert SUB not in caplog.text and CUSTOMER not in caplog.text
