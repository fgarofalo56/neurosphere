"""PRP-139 item 1: ``dataMode`` and ``customerId`` in the hosted templates (compiled ARM).

``az bicep build`` emits expressions, so the assertions read the compiled variables and module
parameters. Skipped when ``az`` is not on PATH; the CI bicep job is the backstop.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
DEMO = ROOT / "infra" / "demo"
AZ = shutil.which("az")

pytestmark = pytest.mark.skipif(
    AZ is None, reason="az CLI not on PATH; the CI bicep job is the backstop for these builds"
)

LOG_ANALYTICS_DATA_READER = "3b03c2da-16b3-4a49-8834-0f8130efdd3b"
APIM_SERVICE_READER = "71522526-b88f-4d52-b57f-d31fc3546d0d"
FOUNDRY_USER = "53ca6127-db72-4b80-b1b0-d745d6d5456d"
STORAGE_BLOB_DATA_READER = "2a2b9908-6ea1-4ae2-8e65-a410df84e7d1"
CONNECTOR_ROLES = ("foundry_discovery", "gateway_poll", "billing_export")


def _build(path: Path) -> dict[str, Any]:
    assert AZ is not None
    proc = subprocess.run(
        [AZ, "bicep", "build", "--file", str(path), "--stdout"],
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )
    assert proc.returncode == 0, f"az bicep build {path.name} failed:\n{proc.stderr}"
    return json.loads(proc.stdout)


@pytest.fixture(scope="module")
def main_arm() -> dict[str, Any]:
    return _build(DEMO / "main.bicep")


@pytest.fixture(scope="module")
def twin_arm() -> dict[str, Any]:
    return _build(ROOT / "infra" / "appservice" / "main.bicep")


@pytest.fixture(scope="module")
def rbac_arm() -> dict[str, Any]:
    return _build(DEMO / "modules" / "connector-rbac.bicep")


def _resources(template: dict[str, Any]) -> list[dict[str, Any]]:
    resources = template.get("resources", [])
    return list(resources.values()) if isinstance(resources, dict) else list(resources)


def _walk(template: dict[str, Any]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for res in _resources(template):
        found.append(res)
        props = res.get("properties")
        inner = props.get("template") if isinstance(props, dict) else None
        if isinstance(inner, dict):
            found.extend(_walk(inner))
    return found


def test_parameters_and_defaults(main_arm: dict[str, Any]) -> None:
    params = main_arm["parameters"]
    assert params["dataMode"]["defaultValue"] == "demo"
    assert params["dataMode"]["allowedValues"] == ["demo", "real-tenant"]
    assert params["customerId"]["defaultValue"] == "synthco"
    assert params["logAnalyticsWorkspaceIds"]["defaultValue"] == []
    assert params["apimServiceIds"]["defaultValue"] == []
    assert "customerId" not in main_arm["variables"]


def test_customer_id_parameter_feeds_the_auth_setting(main_arm: dict[str, Any]) -> None:
    common = main_arm["variables"]["commonSettings"]
    assert "'NS_AUTH_CUSTOMER_ID', parameters('customerId')" in common


def test_real_tenant_adds_the_three_connector_roles(main_arm: dict[str, Any]) -> None:
    variables = main_arm["variables"]
    effective = variables["effectiveConnectorRoles"]
    assert "equals(parameters('dataMode'), 'real-tenant')" in effective
    assert "union(parameters('connectorRoles')" in effective
    for role in CONNECTOR_ROLES:
        assert f"'{role}'" in effective
    # The demo branch is the unchanged parameter.
    assert effective.endswith(", parameters('connectorRoles'))]")
    assert "variables('effectiveConnectorRoles')" in variables["workerRoles"]
    # NS_API_BASE_URL on the workers follows the effective roles, so real-tenant always sets it.
    assert "variables('effectiveConnectorRoles')" in variables["connectorSettings"]
    assert "NS_API_BASE_URL" in variables["connectorSettings"]


def test_data_mode_reaches_both_site_passes_and_the_twin_sets_the_setting(
    main_arm: dict[str, Any], twin_arm: dict[str, Any]
) -> None:
    passes = [
        r
        for r in _walk(main_arm)
        if r["type"] == "Microsoft.Resources/deployments"
        and "dataMode" in r["properties"].get("parameters", {})
    ]
    assert len(passes) == 2  # bootstrap and final site passes
    for deployment in passes:
        assert deployment["properties"]["parameters"]["dataMode"]["value"] == (
            "[parameters('dataMode')]"
        )
        # The customer id still travels in commonAppSettings; the twin's own id stays empty.
        assert "customerId" not in deployment["properties"]["parameters"]
    twin_vars = twin_arm["variables"]
    assert "'NS_HOSTED_DATA_MODE'" in twin_vars["dataModeSettings"]
    assert "parameters('dataMode')" in twin_vars["dataModeSettings"]
    sites = [r for r in _resources(twin_arm) if r["type"] == "Microsoft.Web/sites"]
    api = next(s for s in sites if "-api" in s["name"])
    workers = next(s for s in sites if "-workers" in s["name"])
    for site in (api, workers):
        assert "variables('dataModeSettings')" in str(
            site["properties"]["siteConfig"]["appSettings"]
        )
    assert twin_arm["parameters"]["dataMode"]["defaultValue"] == "demo"
    assert twin_arm["parameters"]["customerId"]["defaultValue"] == ""
    # Real-tenant on the twin adds the connector roles only on top of an explicit role list.
    effective = twin_vars["effectiveWorkerRoles"]
    assert "variables('connectorWorkerRoles')" in effective
    for role in CONNECTOR_ROLES:
        assert f"'{role}'" in str(twin_vars["connectorWorkerRoles"])


def test_role_ids_are_written_not_names(rbac_arm: dict[str, Any]) -> None:
    variables = rbac_arm["variables"]
    assert variables["logAnalyticsDataReader"] == LOG_ANALYTICS_DATA_READER
    assert variables["apimServiceReader"] == APIM_SERVICE_READER
    assert variables["foundryUser"] == FOUNDRY_USER
    assert variables["storageBlobDataReader"] == STORAGE_BLOB_DATA_READER


def test_every_role_assignment_is_at_single_resource_scope(
    main_arm: dict[str, Any], rbac_arm: dict[str, Any]
) -> None:
    """No role assignment at resource-group or subscription scope, in any compiled template."""
    seen = 0
    for template in (rbac_arm, main_arm):
        for res in _walk(template):
            if res["type"] != "Microsoft.Authorization/roleAssignments":
                continue
            seen += 1
            scope = str(res.get("scope", ""))
            assert scope, f"role assignment {res['name']} has no scope (defaults to the group)"
            assert "resourceGroup()" not in scope
            assert "subscription()" not in scope
            assert "subscriptionResourceId('Microsoft.Resources/resourceGroups'" not in scope
            assert (
                re.search(r"resourceId\('Microsoft\.[A-Za-z]+/", scope)
                or "format('Microsoft." in scope
            ), scope
    assert seen >= 4


def test_new_assignments_use_the_right_identity(rbac_arm: dict[str, Any]) -> None:
    by_name = {
        res["name"]: res
        for res in _resources(rbac_arm)
        if res["type"] == "Microsoft.Authorization/roleAssignments"
    }
    workspace = next(r for n, r in by_name.items() if "logAnalyticsWorkspace" in n)
    apim = next(r for n, r in by_name.items() if "apimService" in n)
    assert workspace["properties"]["principalId"] == "[parameters('workersPrincipalId')]"
    assert apim["properties"]["principalId"] == "[parameters('apiPrincipalId')]"
    assert "variables('logAnalyticsDataReader')" in workspace["properties"]["roleDefinitionId"]
    assert "variables('apimServiceReader')" in apim["properties"]["roleDefinitionId"]


def test_main_declares_one_module_per_id_at_that_resources_scope(main_arm: dict[str, Any]) -> None:
    modules = {
        r["name"]: r for r in _resources(main_arm) if r["type"] == "Microsoft.Resources/deployments"
    }
    for fragment, id_param in (
        ("workspace-rbac", "logAnalyticsWorkspaceIds"),
        ("apim-rbac", "apimServiceIds"),
    ):
        copies = [m for n, m in modules.items() if fragment in n]
        assert len(copies) == 1
        loop = copies[0]["copy"]
        assert id_param in loop["count"]
        assert "subscriptionId" in str(copies[0]) or "resourceGroup" in str(copies[0])


def test_no_secret_in_the_new_parameters_outputs_or_settings(
    main_arm: dict[str, Any], twin_arm: dict[str, Any], rbac_arm: dict[str, Any]
) -> None:
    banned = re.compile(r"secret|password|connectionstring|accountkey|listkeys", re.IGNORECASE)
    new_names = {"dataMode", "customerId", "logAnalyticsWorkspaceIds", "apimServiceIds"}
    new_names |= {"apiPrincipalId", "logAnalyticsWorkspaceName", "apimServiceName"}
    for template in (main_arm, twin_arm, rbac_arm):
        for name in (*template["parameters"], *template.get("outputs", {})):
            if name in new_names:
                assert not banned.search(name), name
    for template in (main_arm, twin_arm, rbac_arm):
        assert not any(
            banned.search(k) for k in template.get("outputs", {}) if k != "pseudonymSecretName"
        )
    for name in ("dataMode", "customerId", "logAnalyticsWorkspaceIds", "apimServiceIds"):
        assert not banned.search(json.dumps(main_arm["parameters"][name].get("defaultValue", "")))
