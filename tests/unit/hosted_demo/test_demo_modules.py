"""Hosted-demo Bicep modules: they build, stay in their lane, keep least-privilege RBAC."""

from __future__ import annotations

import json
import re
from typing import Any

import pytest

from .conftest import (
    CORE_MODULES,
    DEMO_MODULES,
    GOLDEN,
    compile_bicep,
    requires_az,
    resource_list,
    walk_resources,
)

EXPECTED_MODULES = {
    "budget",
    "cosmos-data",
    "cosmos-rbac",
    "hub-private-endpoint",
    "keyvault-rbac",
    "messaging-data",
}
SECRET_MARKERS = re.compile(
    r"listkeys|listsecrets|listconnectionstrings|connectionstring|primarykey|secondarykey|"
    r"accountkey|sharedaccesskey|password|secret|token",
    re.IGNORECASE,
)
BUILTIN_COSMOS_DATA_CONTRIBUTOR = "00000000-0000-0000-0000-" + "000000000002"
WRITE_VERBS = ("items/replace", "items/upsert", "items/delete", "items/patch")
AUDIT_RECORDS = "audit"
AUDIT_TAIL = "audit_tail"
PREFIX = "variables('dataActionPrefix')"


def test_expected_modules_present() -> None:
    assert {p.stem for p in DEMO_MODULES.glob("*.bicep")} == EXPECTED_MODULES


@pytest.mark.parametrize("name", sorted(EXPECTED_MODULES))
def test_source_has_no_literal_hosts_or_keys(name: str) -> None:
    text = (DEMO_MODULES / f"{name}.bicep").read_text(encoding="utf-8")
    assert not re.search(r"https?://", text)
    assert not re.search(r"\.(windows|azure)\.(net|com|us)\b", text)
    assert "listKeys" not in text
    assert "@description" in text


@requires_az
@pytest.mark.parametrize("name", sorted(EXPECTED_MODULES))
def test_module_builds_with_safe_outputs(name: str) -> None:
    arm = compile_bicep(DEMO_MODULES / f"{name}.bicep")
    assert "listkeys" not in json.dumps(arm).lower()
    for out_name, out in arm.get("outputs", {}).items():
        assert not SECRET_MARKERS.search(out_name), out_name
        assert out.get("metadata", {}).get("description"), f"{out_name} lacks @description"
    for param_name, param in arm.get("parameters", {}).items():
        assert param.get("metadata", {}).get("description"), f"{param_name} lacks @description"


@requires_az
def test_no_throughput_anywhere(demo_arm: dict[str, dict[str, Any]]) -> None:
    for name, arm in demo_arm.items():
        assert "throughput" not in json.dumps(arm).lower(), name


@requires_az
def test_hub_private_endpoint_declares_no_network_foundations(
    demo_arm: dict[str, dict[str, Any]],
) -> None:
    arm = demo_arm["hub-private-endpoint"]
    types = {r["type"] for r in resource_list(arm)}
    assert types == {
        "Microsoft.Network/privateEndpoints",
        "Microsoft.Network/privateEndpoints/privateDnsZoneGroups",
    }
    for forbidden in ("privateDnsZones", "virtualNetworks", "subnets"):
        assert forbidden not in json.dumps(arm)
    assert set(arm["parameters"]) >= {
        "name",
        "location",
        "privateLinkServiceId",
        "groupId",
        "subnetId",
        "privateDnsZoneId",
        "tags",
    }


def _role_actions(arm: dict[str, Any]) -> dict[str, list[str]]:
    roles = {}
    for res in resource_list(arm):
        if res["type"].endswith("/sqlRoleDefinitions"):
            actions = [a for p in res["properties"]["permissions"] for a in p["dataActions"]]
            roles[res["properties"]["roleName"]] = actions
    return roles


@requires_az
def test_cosmos_roles_keep_prp06_posture(demo_arm: dict[str, dict[str, Any]]) -> None:
    arm = demo_arm["cosmos-rbac"]
    roles = _role_actions(arm)
    assert set(roles) == {
        "ns-app-read-create-query",
        "ns-app-replace-upsert",
        "ns-app-replace-only",
    }
    base = " ".join(roles["ns-app-read-create-query"])
    assert not any(v in base for v in WRITE_VERBS)
    assert "items/create" in base
    assert "executeQuery" in base
    assert any("items/delete" in a for acts in roles.values() for a in acts) is False
    # The replace-only role (audit tail) must not carry upsert or delete.
    tail = " ".join(roles["ns-app-replace-only"])
    assert "items/replace" in tail
    assert "upsert" not in tail
    assert "delete" not in tail

    # The audit records container is excluded from every container-scoped write grant: the skip
    # list defaults to it, and the write-pair list is built by filtering the registry with it.
    params = arm["parameters"]
    assert params["appendOnlyContainers"]["defaultValue"] == [AUDIT_RECORDS]
    assert params["replaceOnlyContainers"]["defaultValue"] == [AUDIT_TAIL]
    variables = arm["variables"]
    assert variables["skipWrite"] == (
        "[concat(parameters('appendOnlyContainers'), parameters('replaceOnlyContainers'))]"
    )
    assert "variables('skipWrite')" in variables["writeContainers"]
    assert variables["writePairs"].count("variables('writeContainers')") == 1
    assert "variables('principals')" in variables["writePairs"]

    # Mirror the filter on the real registry: neither audit container gets replace/upsert.
    registry = next(v for k, v in variables.items() if k.startswith("$fxv#"))
    skip = set(params["appendOnlyContainers"]["defaultValue"]) | set(
        params["replaceOnlyContainers"]["defaultValue"]
    )
    write_targets = {c["name"] for c in registry["containers"]} - skip
    assert AUDIT_RECORDS not in write_targets
    assert AUDIT_TAIL not in write_targets
    assert len(write_targets) == len(registry["containers"]) - 2

    # Each assignment family reads only its own pair list, and the upsert role is never given
    # database scope.
    assignments = {
        r["copy"]["name"]: r["properties"]
        for r in resource_list(arm)
        if r["type"].endswith("/sqlRoleAssignments")
    }
    assert set(assignments) == {"baseAssignments", "writeAssignments", "tailAssignments"}
    assert assignments["baseAssignments"]["scope"] == "[variables('dbScope')]"
    assert "writePairs" in assignments["writeAssignments"]["scope"]
    assert "ns-app-write" in assignments["writeAssignments"]["roleDefinitionId"]
    assert "tailPairs" in assignments["tailAssignments"]["scope"]
    assert "ns-app-replace-only" in assignments["tailAssignments"]["roleDefinitionId"]


@requires_az
def test_no_builtin_data_contributor_for_app_principals(
    demo_arm: dict[str, dict[str, Any]],
) -> None:
    for name, arm in demo_arm.items():
        assert BUILTIN_COSMOS_DATA_CONTRIBUTOR not in json.dumps(arm), name
    # No seeder parameter: operator grants are made by the seed-access script, not Bicep.
    assert not any("seeder" in p.lower() for p in demo_arm["cosmos-rbac"]["parameters"])


@requires_az
def test_messaging_defaults_match_worker_settings(demo_arm: dict[str, dict[str, Any]]) -> None:
    params = demo_arm["messaging-data"]["parameters"]
    assert params["eventHubName"]["defaultValue"] == "telemetry"
    assert params["consumerGroupName"]["defaultValue"] == "normalizer"
    assert params["checkpointContainerName"]["defaultValue"] == "ns-ingestion-checkpoints"
    assert params["archiveContainerName"]["defaultValue"] == "ns-archive"
    assert params["quarantineContainerName"]["defaultValue"] == "ns-quarantine"


@requires_az
def test_messaging_roles_are_scoped(demo_arm: dict[str, dict[str, Any]]) -> None:
    arm = demo_arm["messaging-data"]
    assignments = [
        r for r in resource_list(arm) if r["type"] == "Microsoft.Authorization/roleAssignments"
    ]
    # Nothing is assigned at account or subscription scope: every scope is a hub or a container.
    for res in assignments:
        scope = res["scope"]
        assert "eventhubs'" in scope or "blobServices/containers" in scope, scope
    by_role: dict[str, list[str]] = {}
    for res in assignments:
        role = res["properties"]["roleDefinitionId"]
        by_role.setdefault(role, []).append(res["properties"]["principalId"])
    sender = [p for r, p in by_role.items() if "eventHubsDataSender" in r]
    receiver = [p for r, p in by_role.items() if "eventHubsDataReceiver" in r]
    assert sender == [["[parameters('apiPrincipalId')]"]]
    assert receiver == [["[parameters('workersPrincipalId')]"]]
    # The API only ever reads the archive: reader, never contributor.
    api_roles = {r for r, p in by_role.items() if "[parameters('apiPrincipalId')]" in p}
    assert not any("storageBlobDataContributor" in r for r in api_roles)


@requires_az
def test_keyvault_rbac_is_secrets_user_at_vault_scope(demo_arm: dict[str, dict[str, Any]]) -> None:
    arm = demo_arm["keyvault-rbac"]
    (res,) = resource_list(arm)
    assert res["type"] == "Microsoft.Authorization/roleAssignments"
    assert "Microsoft.KeyVault/vaults" in res["scope"]
    assert "keyVaultSecretsUser" in res["properties"]["roleDefinitionId"]
    assert arm["variables"]["keyVaultSecretsUser"] == "4633458b-17de-408a-b874-0445c86b69e6"


@requires_az
def test_budget_has_four_notifications(demo_arm: dict[str, dict[str, Any]]) -> None:
    (res,) = resource_list(demo_arm["budget"])
    assert res["type"] == "Microsoft.Consumption/budgets"
    notes = res["properties"]["notifications"]
    seen = {(n["threshold"], n["thresholdType"]) for n in notes.values()}
    assert seen == {(50, "Actual"), (80, "Actual"), (100, "Actual"), (100, "Forecasted")}
    assert len(notes) == 4
    assert all(n["enabled"] for n in notes.values())
    assert res["properties"]["timeGrain"] == "Monthly"


# ---- Core modules: additive params only; defaults leave the deployed resources unchanged ----


def _rows(arm: dict[str, Any]) -> list[list[str]]:
    return sorted({(r["type"], r["apiVersion"], r["name"]) for r in walk_resources(arm)})  # type: ignore[misc]


@requires_az
def test_core_main_resource_set_unchanged_and_defaults_inert() -> None:
    arm = compile_bicep(CORE_MODULES / "main.bicep")
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert [list(r) for r in _rows(arm)] == golden

    # main.bicep does not pass the new parameters, so every deployment keeps the defaults.
    source = (CORE_MODULES / "main.bicep").read_text(encoding="utf-8")
    assert "capacityMode" not in source
    assert "dailyQuotaGb" not in source

    nested = {
        r["name"]: r["properties"]["template"]
        for r in resource_list(arm)
        if r["type"] == "Microsoft.Resources/deployments"
    }
    cosmos = nested["ns-cosmos"]
    assert cosmos["parameters"]["capacityMode"]["defaultValue"] == "Provisioned"
    (account,) = [r for r in resource_list(cosmos) if r["type"].endswith("/databaseAccounts")]
    # The guard yields an empty object for the default, so no capacityMode is emitted.
    assert (
        "if(equals(parameters('capacityMode'), 'Serverless'), "
        "createObject('capacityMode', 'Serverless'), createObject())"
        in json.dumps(account["properties"])
    )

    law = nested["ns-loganalytics"]
    assert law["parameters"]["dailyQuotaGb"]["defaultValue"] == -1
    (workspace,) = [r for r in resource_list(law) if r["type"].endswith("/workspaces")]
    assert (
        "if(equals(parameters('dailyQuotaGb'), -1), createObject(), createObject('workspaceCapping'"
        in json.dumps(workspace["properties"])
    )


@requires_az
def test_core_cosmos_serverless_emits_capacity_mode() -> None:
    arm = compile_bicep(CORE_MODULES / "cosmos.bicep")
    allowed = arm["parameters"]["capacityMode"]["allowedValues"]
    assert allowed == ["Provisioned", "Serverless"]
