"""PRP-58 item 1: the hosted data path in ``infra/demo/main.bicep`` and its parameter plumbing.

Assertions run over the compiled ARM (``az bicep build``); skipped when ``az`` is not on PATH,
the CI bicep job being the backstop. The script tests need no ``az``.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
MAIN = ROOT / "infra" / "demo" / "main.bicep"
MODULE = ROOT / "infra" / "demo" / "modules" / "connector-rbac.bicep"
GATES = ROOT / "scripts" / "gates"
AZ = shutil.which("az")
requires_az = pytest.mark.skipif(AZ is None, reason="az CLI not on PATH; CI bicep job backstops")

NEW_PARAMS = (
    "connectorRoles",
    "recommendationsEnabled",
    "foundryAccountIds",
    "billingExportStorageAccountId",
)
PILOT_PARAMS = ("evaluationPilotDomainId", "evaluationPilotSubjectId", "evaluationPilotDatasetIds")
FOUNDRY_USER = "53ca6127-db72-4b80-b1b0-d745d6d5456d"
BLOB_READER = "2a2b9908-6ea1-4ae2-8e65-a410df84e7d1"
FOUNDRY_ACCOUNT = (
    "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-x/providers/"
    "Microsoft.CognitiveServices/accounts/acct-x"
)


def _build(path: Path) -> dict[str, Any]:
    assert AZ is not None
    proc = subprocess.run(
        [AZ, "bicep", "build", "--file", str(path), "--stdout"],
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)  # type: ignore[no-any-return]


def _resources(arm: dict[str, Any]) -> list[dict[str, Any]]:
    res = arm["resources"]
    return list(res.values()) if isinstance(res, dict) else list(res)


@pytest.fixture(scope="module")
def main_arm() -> dict[str, Any]:
    if AZ is None:
        pytest.skip("az CLI not on PATH")
    return _build(MAIN)


@pytest.fixture(scope="module")
def rbac_arm() -> dict[str, Any]:
    if AZ is None:
        pytest.skip("az CLI not on PATH")
    return _build(MODULE)


@requires_az
def test_new_parameters_default_to_the_current_deployment(main_arm: dict[str, Any]) -> None:
    params = main_arm["parameters"]
    assert params["connectorRoles"]["defaultValue"] == []
    assert params["recommendationsEnabled"]["defaultValue"] is False
    assert params["foundryAccountIds"]["defaultValue"] == []
    assert params["billingExportStorageAccountId"]["defaultValue"] == ""
    for name in NEW_PARAMS:
        assert params[name]["metadata"]["description"]


@requires_az
def test_store_switches_and_opt_in_settings(main_arm: dict[str, Any]) -> None:
    variables = main_arm["variables"]
    assert variables["apiSettings"]["NS_INGEST_PRODUCER_STORE"] == "true"
    workers = str(variables["workersBaseSettings"])
    assert "'NS_WORKER_CONNECTOR_CONFIG_SOURCE', 'auto'" in workers
    # Opt-in settings are conditional on their parameters, so defaults add nothing.
    assert "recommendationsEnabled" in str(variables["recommendationsSettings"])
    assert "NS_WORKER_REC_SOURCE" in str(variables["recommendationsSettings"])
    assert "archive" in str(variables["recommendationsSettings"])
    connector = str(variables["connectorSettings"])
    assert "empty(variables('effectiveConnectorRoles'))" in connector
    assert "NS_API_BASE_URL" in connector and "apiUpstream" in connector
    roles = str(variables["workerRoles"])
    assert "variables('effectiveConnectorRoles')" in roles
    assert "'recommendations'" in roles


@requires_az
def test_no_connector_role_in_the_default_role_list(main_arm: dict[str, Any]) -> None:
    text = json.dumps(main_arm["variables"]["workerRoles"])
    for role in ("gateway_poll", "foundry_discovery", "billing_export"):
        assert role not in text


@requires_az
def test_connector_rbac_assigns_only_at_resource_scope(rbac_arm: dict[str, Any]) -> None:
    assignments = [
        r for r in _resources(rbac_arm) if r["type"] == "Microsoft.Authorization/roleAssignments"
    ]
    assert len(assignments) == 4
    scopes = {r["scope"] for r in assignments}
    assert any("Microsoft.OperationalInsights/workspaces" in s for s in scopes)
    assert any("Microsoft.ApiManagement/service" in s for s in scopes)
    assert any("Microsoft.CognitiveServices/accounts" in s for s in scopes)
    assert any("Microsoft.Storage/storageAccounts" in s for s in scopes)
    for res in assignments:
        scope = res["scope"]
        # Scope is a resourceId() of one named resource, never a group or subscription id.
        assert scope.startswith("[resourceId('Microsoft.")
        assert "resourceGroup()" not in scope and "subscription()" not in scope
        assert res["properties"]["principalType"] == "ServicePrincipal"
    variables = rbac_arm["variables"]
    assert variables["foundryUser"] == FOUNDRY_USER
    assert variables["storageBlobDataReader"] == BLOB_READER
    assert set(rbac_arm["parameters"]) == {
        "workersPrincipalId",
        "foundryAccountName",
        "exportStorageAccountName",
        "apiPrincipalId",
        "logAnalyticsWorkspaceName",
        "apimServiceName",
    }


@requires_az
def test_main_creates_no_wide_role_assignment_for_the_connectors(main_arm: dict[str, Any]) -> None:
    resources = _resources(main_arm)
    assert [r for r in resources if r["type"] == "Microsoft.Authorization/roleAssignments"] == []
    by_name = {str(r["name"]): r for r in resources}
    foundry = next(r for n, r in by_name.items() if "foundry-rbac" in n)
    billing = next(r for n, r in by_name.items() if "billing-export-rbac" in n)
    # Each deployment runs at the target resource's own group (it may be another subscription).
    assert foundry["copy"]["count"] == "[length(parameters('foundryAccountIds'))]"
    assert "split(parameters('foundryAccountIds')[copyIndex()]" in foundry["subscriptionId"]
    assert billing["condition"] == "[not(empty(parameters('billingExportStorageAccountId')))]"
    assert billing["subscriptionId"] == "[variables('billingExportSubscriptionId')]"
    assert set(foundry["properties"]["parameters"]) == {"workersPrincipalId", "foundryAccountName"}
    assert set(billing["properties"]["parameters"]) == {
        "workersPrincipalId",
        "exportStorageAccountName",
    }


def test_generated_params_cover_the_new_and_pilot_parameters() -> None:
    cm = _hosted_demo().cm
    for name in (*NEW_PARAMS, *PILOT_PARAMS):
        assert name in cm.GENERATED_PARAMS
    text = MAIN.read_text(encoding="utf-8")
    for name in (*NEW_PARAMS, *PILOT_PARAMS):
        assert f"\nparam {name} " in text


def _hosted_demo() -> Any:
    spec = importlib.util.spec_from_file_location("hosted_demo_p58", GATES / "hosted_demo.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # dataclasses resolves annotations through sys.modules
    sys.path.insert(0, str(GATES))
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.path.remove(str(GATES))
    return mod


def _args(mod: Any, *extra: str) -> SimpleNamespace:
    base = [
        "plan",
        "--subscription",
        "00000000-0000-0000-0000-000000000000",
        "--operator",
        "tester",
        "--image-tag",
        "0.0.0",
        "--integration-subnet-id",
        "/subscriptions/s/resourceGroups/r/providers/Microsoft.Network/virtualNetworks/v/subnets/a",
        "--private-endpoint-subnet-id",
        "/subscriptions/s/resourceGroups/r/providers/Microsoft.Network/virtualNetworks/v/subnets/b",
        "--cosmos-zone-id",
        "/subscriptions/s/resourceGroups/r/providers/Microsoft.Network/privateDnsZones/c",
        "--eventhubs-zone-id",
        "/subscriptions/s/resourceGroups/r/providers/Microsoft.Network/privateDnsZones/e",
        "--blob-zone-id",
        "/subscriptions/s/resourceGroups/r/providers/Microsoft.Network/privateDnsZones/b",
        "--webapps-zone-id",
        "/subscriptions/s/resourceGroups/r/providers/Microsoft.Network/privateDnsZones/w",
        "--entra-tenant-id",
        "00000000-0000-0000-0000-000000000001",
        "--entra-client-id",
        "00000000-0000-0000-0000-000000000002",
        "--copilot-endpoint",
        "https://example.invalid",
        "--budget-contact-emails",
        "ops@example.invalid",
        "--tag-owner",
        "tester",
        *extra,
    ]
    return mod.build_parser().parse_args(base)


def test_plan_flags_reach_the_template_parameters() -> None:
    mod = _hosted_demo()
    ns = _args(
        mod,
        "--connector-roles",
        "gateway_poll, billing_export",
        "--foundry-account-ids",
        FOUNDRY_ACCOUNT,
        "--billing-export-storage-account-id",
        FOUNDRY_ACCOUNT.replace("CognitiveServices/accounts", "Storage/storageAccounts"),
        "--recommendations",
        "--evaluation-pilot-domain-id",
        "dom-1",
        "--evaluation-pilot-subject-id",
        "sub-1",
    )
    values = mod.infra_values(SimpleNamespace(args=ns, deployment_id="dep"))
    assert values["connectorRoles"] == ["gateway_poll", "billing_export"]
    assert values["foundryAccountIds"] == [FOUNDRY_ACCOUNT]
    assert values["recommendationsEnabled"] is True
    assert values["evaluationPilotDomainId"] == "dom-1"
    assert values["evaluationPilotDatasetIds"] == "sbx-groundedness-pilot"
    assert set(values) == set(mod.cm.GENERATED_PARAMS)


def test_defaults_enable_nothing() -> None:
    mod = _hosted_demo()
    values = mod.infra_values(SimpleNamespace(args=_args(mod), deployment_id="dep"))
    assert values["connectorRoles"] == []
    assert values["recommendationsEnabled"] is False
    assert values["foundryAccountIds"] == []
    assert values["billingExportStorageAccountId"] == ""


def test_unknown_connector_role_is_refused() -> None:
    mod = _hosted_demo()
    ns = _args(mod, "--connector-roles", "gateway_poll,evaluation")
    with pytest.raises(mod.RefusedError, match="unknown role"):
        mod.infra_values(SimpleNamespace(args=ns, deployment_id="dep"))


def test_foundry_ids_must_be_arm_ids() -> None:
    mod = _hosted_demo()
    ns = _args(mod, "--foundry-account-ids", "not-an-id")
    with pytest.raises(mod.RefusedError, match="resource ids"):
        mod.infra_values(SimpleNamespace(args=ns, deployment_id="dep"))
