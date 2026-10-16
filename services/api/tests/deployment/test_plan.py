"""Reuse/create/skip planner: consent, residency, matrix-disabled options, cost, manifest, authz."""

from __future__ import annotations

import importlib
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from authz.authz_helpers import Harness  # pyright: ignore[reportMissingImports]
from neurosphere_api.deploy.plan import (
    CREATED_BY_TAG,
    CREATED_BY_VALUE,
    DeploymentPlan,
    OwnerConsentRecord,
    PlanItem,
    PlanRequest,
    PriceEntry,
    PriceTable,
    ServiceChoice,
    build_plan,
    build_router,
    to_manifest,
)
from neurosphere_api.deploy.scan import (
    DiscoveredResource,
    ScanResponse,
    SubscriptionScan,
)
from neurosphere_contracts.deployment.v1.capability_matrix_entry import CapabilityMatrixEntry
from neurosphere_core.capabilities import (
    CapabilityMatrix,
    DeploymentProfile,
    FeatureRequest,
    matrix_from_rows,
)
from pydantic import ValidationError

from .conftest import ADMIN, VIEWER

_CONTRACTS = Path(__file__).resolve().parents[4] / "tests" / "contracts"
sys.path.insert(0, str(_CONTRACTS))
schema_errors: Callable[[str, Any], list[Any]] = importlib.import_module(
    "contract_support"
).schema_errors
check_deployment_manifest: Callable[[Any], list[str]] = importlib.import_module(
    "validators"
).check_deployment_manifest

SCHEMA = "deployment/v1/deployment-manifest.schema.json"
SUB = "aaaaaaaa-0000-4000-8000-000000000001"
NOW = datetime(2026, 10, 16, 12, 0, 0, tzinfo=UTC)
OWNER = "owner:platform-team"

COMMERCIAL = DeploymentProfile(
    cloud="commercial", regions=("eastus2",), hosting="aks", analytics="synapse"
)
GOVERNMENT = DeploymentProfile(
    cloud="government", regions=("usgovvirginia",), hosting="aks", analytics="synapse"
)


def _id(rtype: str, name: str) -> str:
    return f"/subscriptions/{SUB}/resourceGroups/rg/providers/{rtype}/{name}"


def _res(
    category: str,
    rtype: str,
    name: str,
    location: str = "eastus2",
    tags: dict[str, str] | None = None,
) -> DiscoveredResource:
    return DiscoveredResource.model_validate(
        {
            "category": category,
            "type": rtype,
            "id": _id(rtype, name),
            "name": name,
            "location": location,
            "sku": "Standard",
            "subscription_id": SUB,
            "tags": tags or {},
        }
    )


def _scan(*resources: DiscoveredResource) -> ScanResponse:
    return ScanResponse(
        consent_id="scan-consent-1",
        scanned_at=NOW,
        subscriptions=[
            SubscriptionScan(subscription_id=SUB, status="visible", resources=list(resources))
        ],
    )


def _consent(
    *resource_ids: str, granted: bool = True, principal: str | None = OWNER
) -> OwnerConsentRecord:
    return OwnerConsentRecord(
        consent_id="consent-1",
        granted=granted,
        owner_principal=principal,
        resource_ids=list(resource_ids),
        recorded_at=NOW,
    )


KV = _res("key_vault", "Microsoft.KeyVault/vaults", "kv-shared")


def _plan(request: PlanRequest, matrix: CapabilityMatrix | None = None) -> DeploymentPlan:
    return build_plan(
        request,
        matrix=matrix,
        now=NOW,
        plan_id="plan-test",
    )


def _item(plan: DeploymentPlan, service: str) -> PlanItem:
    return next(i for i in plan.items if i.service == service)


def _assert_valid_manifest(plan: DeploymentPlan) -> dict[str, Any]:
    doc = to_manifest(plan).model_dump(mode="json", exclude_none=False)
    # The contract schema forbids absent-vs-null drift: validate exactly what we emit.
    assert [e.message for e in schema_errors(SCHEMA, doc)] == []
    assert check_deployment_manifest(doc) == []
    return doc


def _row(
    service: str, feature: str, cloud: str, region: str, availability: str
) -> CapabilityMatrixEntry:
    return CapabilityMatrixEntry.model_validate(
        {
            "schema_version": "1.1.0",
            "id": f"{service}.{feature}.{cloud}.{'any' if region == '*' else region}.any",
            "service": service,
            "feature": feature,
            "cloud": cloud,
            "region": region,
            "sku": None,
            "availability": availability,
            "ga_status": "ga" if availability == "available" else "not_applicable",
            "authorization_scope": "none_claimed",
            "source_url": "https://example.invalid/doc",
            "observed_on": "2026-10-01",
            "notes": None,
        }
    )


def _matrix(*, synapse: str = "available", aks: str = "available") -> CapabilityMatrix:
    return matrix_from_rows(
        [
            _row("aks", "base", "commercial", "eastus2", aks),
            _row("synapse", "base", "commercial", "eastus2", synapse),
            _row("aks", "base", "government", "usgovvirginia", aks),
            _row("synapse", "base", "government", "usgovvirginia", synapse),
        ]
    )


# --------------------------------------------------------------------------- consent (rule 1)


def test_shared_resource_without_consent_is_needs_consent_not_reuse() -> None:
    plan = _plan(PlanRequest(profile=COMMERCIAL, scan=_scan(KV)), _matrix())
    item = _item(plan, "key_vault")
    assert item.status == "needs_consent"
    assert item.shared is True
    assert item.existing_resource_id == KV.id
    assert not any(i.status == "reuse" for i in plan.items)
    assert plan.consents == []


def test_granted_consent_covering_resource_enables_reuse() -> None:
    consent = _consent(KV.id.upper().replace("/SUBSCRIPTIONS/", "/subscriptions/"))
    plan = _plan(PlanRequest(profile=COMMERCIAL, scan=_scan(KV), consents=[consent]), _matrix())
    item = _item(plan, "key_vault")
    assert item.status == "reuse"
    assert item.shared is True
    assert item.owner_consent is not None
    assert [c.consent_id for c in plan.consents] == ["consent-1"]


@pytest.mark.parametrize(
    "consent",
    [
        _consent(_id("Microsoft.KeyVault/vaults", "other")),  # covers a different resource
        _consent(KV.id, granted=False, principal=None),  # not granted
    ],
)
def test_consent_that_does_not_apply_never_enables_reuse(consent: OwnerConsentRecord) -> None:
    plan = _plan(PlanRequest(profile=COMMERCIAL, scan=_scan(KV), consents=[consent]), _matrix())
    assert _item(plan, "key_vault").status == "needs_consent"


def test_granted_consent_must_name_a_pseudonymous_principal() -> None:
    with pytest.raises(ValidationError):
        _consent(KV.id, principal=None)
    with pytest.raises(ValidationError):
        _consent(KV.id, principal="someone@example.com")


def test_neurosphere_created_resource_is_not_shared() -> None:
    mine = _res(
        "storage",
        "Microsoft.Storage/storageAccounts",
        "stns",
        tags={CREATED_BY_TAG: CREATED_BY_VALUE},
    )
    plan = _plan(PlanRequest(profile=COMMERCIAL, scan=_scan(mine)), _matrix())
    item = _item(plan, "storage")
    assert (item.status, item.shared, item.neurosphere_created) == ("reuse", False, True)
    _assert_valid_manifest(plan)


def test_unknown_checks_are_never_pass() -> None:
    plan = _plan(PlanRequest(profile=COMMERCIAL, scan=_scan(KV)), _matrix())
    checks = {c.name: c.outcome for c in _item(plan, "key_vault").checks}
    assert checks["residency"] == "pass"
    for name in ("sku", "network_reachability", "quota", "permission", "lifecycle"):
        assert checks[name] == "unknown"


# --------------------------------------------------------------------------- residency (rule 2)


def test_government_profile_does_not_reuse_commercial_region_resource() -> None:
    commercial_kv = _res("key_vault", "Microsoft.KeyVault/vaults", "kv-com", location="eastus2")
    request = PlanRequest(
        profile=GOVERNMENT, scan=_scan(commercial_kv), consents=[_consent(commercial_kv.id)]
    )
    item = _item(_plan(request, _matrix()), "key_vault")
    assert item.status == "create"
    assert item.existing_resource_id is None
    assert any("outside the profile regions" in n for n in item.notes)
    residency = next(c for c in item.checks if c.name == "residency")
    assert residency.outcome == "fail"  # records why the discovered resource was rejected


def test_residency_failure_can_fall_back_to_skip() -> None:
    commercial_kv = _res("key_vault", "Microsoft.KeyVault/vaults", "kv-com", location="eastus2")
    request = PlanRequest(
        profile=GOVERNMENT,
        scan=_scan(commercial_kv),
        choices={"key_vault": ServiceChoice(decision="reuse", fallback="skip")},
    )
    item = _item(_plan(request, _matrix()), "key_vault")
    assert item.status == "skip"
    assert any("cannot reuse" in n for n in item.notes)


def test_same_cloud_region_resource_is_reusable_with_consent() -> None:
    gov_kv = _res("key_vault", "Microsoft.KeyVault/vaults", "kv-gov", location="usgovvirginia")
    request = PlanRequest(profile=GOVERNMENT, scan=_scan(gov_kv), consents=[_consent(gov_kv.id)])
    assert _item(_plan(request, _matrix()), "key_vault").status == "reuse"


# --------------------------------------------------------------------------- matrix (rule 3)


def test_matrix_unavailable_analytics_is_disabled_with_reason() -> None:
    plan = _plan(PlanRequest(profile=COMMERCIAL), _matrix(synapse="unavailable"))
    item = _item(plan, "analytics_workspace")
    assert item.status == "disabled"
    assert item.disabled_reason and "synapse.base.commercial.eastus2.any" in item.disabled_reason
    assert item.reason_code == "not_available_in_region"
    assert item.source_url == "https://example.invalid/doc"
    assert item.cost_implication.basis == "no_incremental_cost"
    assert not any(i.status == "create" and i.service == "analytics_workspace" for i in plan.items)
    doc = _assert_valid_manifest(plan)
    row = next(s for s in doc["services"] if s["service"] == "analytics_workspace")
    assert row["decision"] == "skip"
    assert "synapse.base" in row["skip_reason"]


def test_matrix_unavailable_hosting_is_disabled() -> None:
    plan = _plan(PlanRequest(profile=COMMERCIAL), _matrix(aks="unavailable"))
    assert _item(plan, "kubernetes").status == "disabled"
    assert not any(i.service == "app_service" for i in plan.items)


def test_real_shipped_matrix_government_region_without_fabric() -> None:
    profile = DeploymentProfile(
        cloud="government", regions=("usgovarizona",), hosting="aks", analytics="fabric"
    )
    plan = _plan(PlanRequest(profile=profile), None)
    item = _item(plan, "analytics_workspace")
    assert item.status == "disabled"
    assert item.disabled_reason and "usgovarizona" in item.disabled_reason
    assert item.status != "create"
    _assert_valid_manifest(plan)


def test_real_shipped_matrix_disabled_optional_feature_is_plan_only() -> None:
    profile = DeploymentProfile(
        cloud="government",
        regions=("usgovvirginia",),
        hosting="aks",
        analytics="fabric",
        features=(FeatureRequest(service="fabric", feature="customer_managed_keys"),),
    )
    plan = _plan(PlanRequest(profile=profile), None)
    feature = _item(plan, "fabric.customer_managed_keys")
    assert (feature.kind, feature.status) == ("feature", "disabled")
    assert feature.disabled_reason
    doc = _assert_valid_manifest(plan)
    assert "fabric.customer_managed_keys" not in {s["service"] for s in doc["services"]}


def test_capability_warnings_are_carried() -> None:
    plan = _plan(PlanRequest(profile=GOVERNMENT), None)
    assert any(w.startswith("ga_unverified") for w in plan.capability_warnings)


# --------------------------------------------------------------------------- cost (rule 4)


PRICES = PriceTable(
    price_version="prices-2026-10",
    entries=[
        PriceEntry(service="key_vault", monthly_amount="3.5"),
        PriceEntry(service="storage", sku="Premium", monthly_amount="120.25"),
    ],
)


def test_cost_estimated_unknown_and_no_incremental() -> None:
    request = PlanRequest(
        profile=COMMERCIAL,
        scan=_scan(_res("event_hubs", "Microsoft.EventHub/namespaces", "eh")),
        consents=[_consent(_id("Microsoft.EventHub/namespaces", "eh"))],
        choices={
            "monitoring": ServiceChoice(decision="skip"),
            "storage": ServiceChoice(decision="create", sku="Premium"),
        },
        price_table=PRICES,
    )
    plan = _plan(request, _matrix())
    kv = _item(plan, "key_vault").cost_implication
    assert (kv.basis, kv.monthly_amount, kv.currency, kv.price_version) == (
        "estimated",
        "3.5",
        "USD",
        "prices-2026-10",
    )
    assert _item(plan, "storage").cost_implication.monthly_amount == "120.25"
    unpriced = _item(plan, "cosmos_db")
    assert unpriced.status == "create"
    assert unpriced.cost_implication.basis == "unknown"
    assert unpriced.cost_implication.monthly_amount is None
    assert _item(plan, "event_hubs").cost_implication.basis == "no_incremental_cost"
    assert _item(plan, "monitoring").cost_implication.basis == "no_incremental_cost"
    doc = _assert_valid_manifest(plan)
    cosmos = next(s for s in doc["services"] if s["service"] == "cosmos_db")["cost_implication"]
    assert cosmos["monthly_amount"] is None
    assert cosmos["price_version"] is None
    for item in plan.items:
        if item.cost_implication.basis != "estimated":
            assert item.cost_implication.monthly_amount not in ("0", "0.0", "0.00")


def test_without_price_table_every_create_is_unknown() -> None:
    plan = _plan(PlanRequest(profile=COMMERCIAL), _matrix())
    creates = [i for i in plan.items if i.status == "create"]
    assert creates
    assert all(
        i.cost_implication.basis == "unknown" and i.cost_implication.monthly_amount is None
        for i in creates
    )


# --------------------------------------------------------------------------- manifest


def test_manifest_all_create() -> None:
    plan = _plan(PlanRequest(profile=COMMERCIAL), _matrix())
    doc = _assert_valid_manifest(plan)
    assert doc["status"] == "planned"
    assert {s["decision"] for s in doc["services"]} == {"create"}


def test_manifest_mixed_reuse_needs_consent_skip_is_draft() -> None:
    eh = _res("event_hubs", "Microsoft.EventHub/namespaces", "eh")
    request = PlanRequest(
        profile=COMMERCIAL,
        scan=_scan(KV, eh),
        consents=[_consent(eh.id)],
        choices={"monitoring": ServiceChoice(decision="skip")},
    )
    plan = _plan(request, _matrix())
    doc = _assert_valid_manifest(plan)
    by_service = {s["service"]: s for s in doc["services"]}
    assert doc["status"] == "draft"
    assert by_service["event_hubs"]["decision"] == "reuse"
    assert by_service["event_hubs"]["owner_consent"]["granted"] is True
    assert by_service["event_hubs"]["owner_consent"]["owner_principal"] == OWNER
    kv = by_service["key_vault"]
    assert kv["decision"] == "skip"
    assert kv["owner_consent"]["required"] is True and kv["owner_consent"]["granted"] is False
    assert by_service["monitoring"]["decision"] == "skip"


def test_manifest_with_disabled_option_is_planned() -> None:
    plan = _plan(PlanRequest(profile=GOVERNMENT), _matrix(synapse="unavailable"))
    doc = _assert_valid_manifest(plan)
    assert doc["status"] == "planned"
    assert "reuse" not in {s["decision"] for s in doc["services"]}


# --------------------------------------------------------------------------- route


def _body() -> dict[str, Any]:
    return PlanRequest(
        profile=COMMERCIAL,
        scan=_scan(KV),
        consents=[_consent(KV.id)],
        deployment_id="dep-test-01",
    ).model_dump(mode="json")


def test_route_requires_config_manage(mount: Callable[[dict[str, Any]], Harness]) -> None:
    h = mount({"/v1/deploy/plan": build_router(_matrix())})
    denied = h.client.post("/v1/deploy/plan", json=_body(), headers=h.auth(VIEWER))
    assert denied.status_code == 403
    assert denied.json()["reason"] == "permission_missing"
    assert h.client.post("/v1/deploy/plan", json=_body()).status_code == 401


def test_route_admin_gets_plan_and_valid_manifest(
    mount: Callable[[dict[str, Any]], Harness],
) -> None:
    h = mount({"/v1/deploy/plan": build_router(_matrix())})
    ok = h.client.post("/v1/deploy/plan", json=_body(), headers=h.auth(ADMIN))
    assert ok.status_code == 200, ok.text
    data = ok.json()
    assert data["plan"]["deployment_id"] == "dep-test-01"
    assert data["manifest"]["deployment_id"] == "dep-test-01"
    assert [e.message for e in schema_errors(SCHEMA, data["manifest"])] == []
    kv = next(i for i in data["plan"]["items"] if i["service"] == "key_vault")
    assert kv["status"] == "reuse"
