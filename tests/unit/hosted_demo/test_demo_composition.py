"""PRP-32 item 3: ``infra/demo/main.bicep`` composes the demo and stays inside its guard rails.

Assertions run over the compiled ARM (``az bicep build``); the template's parameter and output
names are the D9 contract the deploy script codes against. Skipped when ``az`` is not on PATH;
the CI bicep job (build, build-params, lint) is the backstop.
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest

from .conftest import ROOT, compile_bicep, requires_az, walk_resources

DEMO = ROOT / "infra" / "demo"
MAIN = DEMO / "main.bicep"
PARAMS = DEMO / "main.bicepparam"

PARAMETERS = [
    "prefix",
    "location",
    "imageRegistry",
    "imageTag",
    "appServiceSkuName",
    "deployKeyVault",
    "integrationSubnetId",
    "privateEndpointSubnetId",
    "cosmosDnsZoneId",
    "eventHubsDnsZoneId",
    "blobDnsZoneId",
    "webAppsDnsZoneId",
    "keyVaultDnsZoneId",
    "entraTenantId",
    "entraClientId",
    "copilotEndpoint",
    "copilotDeployment",
    "copilotMode",
    "budgetAmount",
    "budgetStartDate",
    "budgetContactEmails",
    "tagOwner",
    "tagDeleteAfter",
    "deploymentId",
    "createdBy",
]
NO_DEFAULT = {
    "imageTag",
    "integrationSubnetId",
    "privateEndpointSubnetId",
    "cosmosDnsZoneId",
    "eventHubsDnsZoneId",
    "blobDnsZoneId",
    "webAppsDnsZoneId",
    "keyVaultDnsZoneId",
    "entraTenantId",
    "entraClientId",
    "copilotEndpoint",
    "budgetStartDate",
    "budgetContactEmails",
    "tagOwner",
    "tagDeleteAfter",
    "deploymentId",
    "createdBy",
}
OUTPUTS = [
    "apiSiteName",
    "workersSiteName",
    "frontendSiteName",
    "frontendHostName",
    "apiHostName",
    "apiPrincipalId",
    "workersPrincipalId",
    "cosmosAccountName",
    "cosmosEndpoint",
    "cosmosDatabaseName",
    "eventHubsNamespaceName",
    "eventHubsFqdn",
    "eventHubName",
    "storageAccountName",
    "archiveContainerName",
    "keyVaultName",
    "pseudonymSecretName",
    "privateEndpointIds",
]
FORBIDDEN_NAMESPACES = ("microsoft.apimanagement", "microsoft.search")
FORBIDDEN_TYPES = {
    "microsoft.network/virtualnetworks",
    "microsoft.network/virtualnetworks/subnets",
    "microsoft.network/privatednszones",
    "microsoft.network/privatednszones/virtualnetworklinks",
    "microsoft.network/privatednszones/a",
}
# Resource types that accept ``tags`` and are created by this composition.
TAGGABLE = {
    "Microsoft.DocumentDB/databaseAccounts",
    "Microsoft.EventHub/namespaces",
    "Microsoft.Storage/storageAccounts",
    "Microsoft.OperationalInsights/workspaces",
    "Microsoft.KeyVault/vaults",
    "Microsoft.Web/serverfarms",
    "Microsoft.Web/sites",
    "Microsoft.Network/privateEndpoints",
}
DATA_SERVICES = {
    "Microsoft.DocumentDB/databaseAccounts",
    "Microsoft.EventHub/namespaces",
    "Microsoft.Storage/storageAccounts",
    "Microsoft.KeyVault/vaults",
}
REQUIRED_TAGS = {
    "owner",
    "project",
    "env",
    "delete-after",
    "neurosphere:created-by",
    "neurosphere:deployment-id",
}
KEY_VAULT_CONDITION = "[parameters('deployKeyVault')]"
# Names only; the one output named after a secret carries the secret's NAME, never a value.
SECRET_MARKERS = re.compile(
    r"listkeys|listsecrets|listconnectionstrings|connectionstring|primarykey|secondarykey|"
    r"accountkey|sharedaccesskey|password|token|secret",
    re.IGNORECASE,
)
SECRET_NAME_ALLOWED = {"pseudonymSecretName"}
GUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

pytestmark = requires_az


@pytest.fixture(scope="module")
def arm() -> dict[str, Any]:
    return compile_bicep(MAIN)


def _deployments(arm: dict[str, Any]) -> list[dict[str, Any]]:
    """Top-level module deployments of the root template."""
    return [r for r in arm["resources"] if r["type"] == "Microsoft.Resources/deployments"]


def _nested_types(deployment: dict[str, Any]) -> set[str]:
    inner = deployment["properties"]["template"]
    return {r["type"] for r in walk_resources(inner)}


def _param(deployment: dict[str, Any], name: str) -> Any:
    return deployment["properties"]["parameters"][name]["value"]


def _by_type(arm: dict[str, Any], resource_type: str) -> list[dict[str, Any]]:
    return [d for d in _deployments(arm) if resource_type in _nested_types(d)]


def _is_bootstrap(deployment: dict[str, Any]) -> bool:
    return "bootstrap" in deployment["name"]


def test_parameters_and_outputs_are_the_d9_contract(arm: dict[str, Any]) -> None:
    assert list(arm["parameters"]) == PARAMETERS
    assert list(arm["outputs"]) == OUTPUTS
    assert {n for n, p in arm["parameters"].items() if "defaultValue" not in p} == NO_DEFAULT
    assert arm["parameters"]["prefix"]["defaultValue"] == "nsdemo"
    assert arm["parameters"]["appServiceSkuName"]["defaultValue"] == "B2"
    assert arm["parameters"]["deployKeyVault"]["defaultValue"] is True
    assert arm["parameters"]["copilotDeployment"]["defaultValue"] == "mini"
    assert arm["parameters"]["copilotMode"]["defaultValue"] == "disabled"
    assert arm["parameters"]["copilotMode"]["allowedValues"] == [
        "disabled",
        "approved_endpoint",
        "foundry_agent",
    ]
    assert arm["parameters"]["budgetAmount"]["defaultValue"] == 200
    assert arm["parameters"]["imageRegistry"]["defaultValue"] == "ghcr.io/fgarofalo56/neurosphere"
    for name, spec in {**arm["parameters"], **arm["outputs"]}.items():
        assert spec.get("metadata", {}).get("description"), f"{name} lacks @description"


def test_outputs_reference_only_module_deployments(arm: dict[str, Any]) -> None:
    """PRP-32 item 10: an out-of-template reference() fails the whole deploy (ResourceNotFound).

    The Cosmos account and the Event Hubs namespace are created inside nested modules, so the
    root outputs must read them through the module outputs, never through ``existing`` resources.
    """
    for name, spec in arm["outputs"].items():
        value = str(spec["value"])
        targets = re.findall(r"reference\(resourceId\('([^']+)'", value)
        assert value.count("reference(") == len(targets), f"{name}: reference() not on a resourceId"
        assert set(targets) <= {"Microsoft.Resources/deployments"}, name
    top_types = {r["type"] for r in arm["resources"]}
    assert "Microsoft.DocumentDB/databaseAccounts" not in top_types
    assert "Microsoft.EventHub/namespaces" not in top_types


@pytest.mark.parametrize(
    ("module", "output", "created"),
    [
        ("cosmos.bicep", "documentEndpoint", "Microsoft.DocumentDB/databaseAccounts"),
        ("eventhubs.bicep", "serviceBusEndpoint", "Microsoft.EventHub/namespaces"),
    ],
)
def test_module_endpoint_outputs_guard_the_reuse_branch(
    module: str, output: str, created: str
) -> None:
    """The reused branch is only evaluated when ``reuse`` is set; the created one is in-template."""
    arm = compile_bicep(ROOT / "infra" / "bicep" / "modules" / module)
    value = str(arm["outputs"][output]["value"])
    assert value.startswith("[if(empty(parameters('reuse')), reference(resourceId('" + created)
    assert value.count("reference(") == 2


def test_no_forbidden_resource_types_anywhere(arm: dict[str, Any]) -> None:
    types = {r["type"].lower() for r in walk_resources(arm)}
    for resource_type in types:
        assert not resource_type.startswith(FORBIDDEN_NAMESPACES), resource_type
        assert resource_type not in FORBIDDEN_TYPES, resource_type
    assert {"microsoft.web/sites", "microsoft.documentdb/databaseaccounts"} <= types


def test_key_vault_exists_only_when_flagged(arm: dict[str, Any]) -> None:
    gated = [d for d in _deployments(arm) if d.get("condition") == KEY_VAULT_CONDITION]
    gated_types = set().union(*(_nested_types(d) for d in gated))
    assert "Microsoft.KeyVault/vaults" in gated_types
    assert "Microsoft.Network/privateEndpoints" in gated_types
    assert "Microsoft.Authorization/roleAssignments" in gated_types
    assert len(gated) == 3
    ungated_types = set().union(*(_nested_types(d) for d in _deployments(arm) if d not in gated))
    assert "Microsoft.KeyVault/vaults" not in ungated_types
    # The Key Vault references and the output follow the same flag.
    variables = arm["variables"]
    assert "parameters('deployKeyVault')" in variables["keyVaultReferences"]
    assert "parameters('deployKeyVault')" in variables["keyVaultPlainSettings"]
    assert "parameters('deployKeyVault')" in arm["outputs"]["keyVaultName"]["value"]
    assert arm["parameters"]["deployKeyVault"]["defaultValue"] is True


def test_data_services_have_no_public_access(arm: dict[str, Any]) -> None:
    seen: set[str] = set()
    for deployment in _deployments(arm):
        hit = _nested_types(deployment) & DATA_SERVICES
        if not hit or "publicNetworkAccess" not in deployment["properties"]["parameters"]:
            continue
        assert _param(deployment, "publicNetworkAccess") == "Disabled", deployment["name"]
        seen |= hit
    assert seen == DATA_SERVICES
    cosmos = _by_type(arm, "Microsoft.DocumentDB/databaseAccounts")[0]
    assert _param(cosmos, "capacityMode") == "Serverless"
    assert _param(_by_type(arm, "Microsoft.EventHub/namespaces")[0], "skuName") == "Standard"
    workspace = _by_type(arm, "Microsoft.OperationalInsights/workspaces")[0]
    assert _param(workspace, "retentionInDays") == 30


def test_only_the_frontend_is_public_and_all_sites_use_route_all(arm: dict[str, Any]) -> None:
    passes = _by_type(arm, "Microsoft.Web/sites")
    assert len(passes) == 2  # bootstrap + final, the same three sites
    for deployment in passes:
        assert _param(deployment, "apiPublicNetworkAccess") == "Disabled"
        assert _param(deployment, "workersPublicNetworkAccess") == "Disabled"
        assert _param(deployment, "frontendPublicNetworkAccess") == "Enabled"
        assert _param(deployment, "vnetRouteAllEnabled") is True
        assert _param(deployment, "registryAuth") == "anonymous"
        assert _param(deployment, "frontendRepository") == "frontend"
        assert _param(deployment, "capacity") == 1
        assert _param(deployment, "virtualNetworkSubnetId") == "[parameters('integrationSubnetId')]"
        assert _param(deployment, "skuName") == "[parameters('appServiceSkuName')]"
        assert _param(deployment, "namePrefix") == "[parameters('prefix')]"
        # System-assigned identities: no user-assigned id is passed.
        assert "userAssignedIdentityId" not in deployment["properties"]["parameters"]


def test_every_created_resource_carries_the_required_tags(arm: dict[str, Any]) -> None:
    assert set(arm["variables"]["tags"]) == REQUIRED_TAGS
    assert arm["variables"]["tags"]["project"] == "neurosphere"
    assert arm["variables"]["tags"]["env"] == "demo"
    checked: set[str] = set()
    for deployment in _deployments(arm):
        inner = deployment["properties"]["template"]
        for resource in walk_resources(inner):
            if resource["type"] not in TAGGABLE:
                continue
            assert "tags" in resource, f"{deployment['name']}: {resource['type']} has no tags"
            assert _param(deployment, "tags") == "[variables('tags')]", deployment["name"]
            checked.add(resource["type"])
    assert checked == TAGGABLE


def test_app_settings_follow_the_wire_contract(arm: dict[str, Any]) -> None:
    variables = arm["variables"]
    api = set(variables["apiSettings"])
    assert {
        "NS_AUTH_AUDIENCES",
        "NS_INGEST_EVENTHUBS_NAMESPACE",
        "NS_INGEST_EVENTHUB_NAME",
        "NS_COPILOT_MODE",
        "NS_COPILOT_ENDPOINT",
        "NS_COPILOT_DEPLOYMENT",
        "NS_COPILOT_API_VERSION",
    } <= api
    assert variables["apiSettings"]["NS_COPILOT_MODE"] == "[parameters('copilotMode')]"
    assert variables["apiSettings"]["NS_AUTH_AUDIENCES"] == "[parameters('entraClientId')]"
    common = variables["commonSettings"]
    assert "'NS_ENV', 'prod'" in common
    assert "'NS_STORE_COSMOS_ACCOUNT'" in common
    assert "variables('customerId')" in common
    assert variables["customerId"] == "synthco"
    assert variables["keyVaultPlainSettings"].count("NS_AUTH_PSEUDONYM_KEY_REFERENCE") == 1
    assert set(re.findall(r"NS_[A-Z_]+", variables["keyVaultReferences"])) == {
        "NS_AUTH_PSEUDONYM_KEY",
        "NS_ARCHIVE_PSEUDONYM_KEY",
    }
    assert "keyvaultDns" in variables["pseudonymSecretUri"]
    # No CORS: the API is reached through the frontend's same-origin proxy.
    assert not any("CORS" in key for key in api | set(variables["workersBaseSettings"]))
    # The only secret-valued settings are Key Vault references (the pass-through goes via
    # keyVaultSecretUris, which the profile renders as @Microsoft.KeyVault(SecretUri=...)).
    for deployment in _by_type(arm, "Microsoft.Web/sites"):
        refs = _param(deployment, "keyVaultSecretUris")
        assert refs == "[variables('keyVaultReferences')]"


def test_workers_get_their_identity_in_a_second_pass(arm: dict[str, Any]) -> None:
    bootstrap, final = sorted(_by_type(arm, "Microsoft.Web/sites"), key=_is_bootstrap, reverse=True)
    assert _is_bootstrap(bootstrap) and not _is_bootstrap(final)
    base = arm["variables"]["workersBaseSettings"]
    # recommendations/evaluation need compose-mounted data dirs the hosted image lacks.
    assert (
        base["NS_WORKER_ROLES"] == "ingestion,projections,aggregates,actions,hitl_timers,lifecycle"
    )
    assert base["NS_WORKER_TENANT_ID"] == "[parameters('entraTenantId')]"
    assert "NS_WORKER_OBJECT_ID" not in base
    assert _param(bootstrap, "workersAppSettings") == "[variables('workersBaseSettings')]"
    final_settings = _param(final, "workersAppSettings")
    assert "NS_WORKER_OBJECT_ID" in final_settings
    assert "workersPrincipalId" in final_settings
    assert "-appservice-bootstrap" in final_settings
    # The consumer group and hub names match the messaging module defaults.
    assert arm["variables"]["eventHubName"] == "telemetry"
    assert arm["variables"]["consumerGroupName"] == "normalizer"


def test_frontend_proxies_to_the_api_site_and_never_exposes_health(arm: dict[str, Any]) -> None:
    frontend = arm["variables"]["frontendSettings"]
    assert set(frontend) == {
        "NS_UI_CLOUD",
        "NS_UI_TENANT_ID",
        "NS_UI_CLIENT_ID",
        "NS_UI_API_SCOPE",
        "NS_UI_API_UPSTREAM",
    }
    assert frontend["NS_UI_API_UPSTREAM"] == "[variables('apiUpstream')]"
    upstream = arm["variables"]["apiUpstream"]
    assert upstream.startswith("[format('https://{0}-api.{1}', parameters('prefix')")
    assert "privatelink." in arm["variables"]["webAppsSuffix"]
    assert arm["variables"]["apiScope"].startswith("[format('api://{0}/access_as_user'")
    assert "NS_UI_PROXY_HEALTH" not in json.dumps(arm)
    for deployment in _by_type(arm, "Microsoft.Web/sites"):
        assert _param(deployment, "frontendAppSettings") == "[variables('frontendSettings')]"


def test_private_endpoints_target_the_hub_subnet_and_zones(arm: dict[str, Any]) -> None:
    endpoints = _by_type(arm, "Microsoft.Network/privateEndpoints")
    by_group = {_param(d, "groupId"): d for d in endpoints}
    assert set(by_group) == {"Sql", "namespace", "blob", "sites", "vault"}
    zones = {
        "Sql": "cosmosDnsZoneId",
        "namespace": "eventHubsDnsZoneId",
        "blob": "blobDnsZoneId",
        "sites": "webAppsDnsZoneId",
        "vault": "keyVaultDnsZoneId",
    }
    for group, zone in zones.items():
        deployment = by_group[group]
        assert _param(deployment, "privateDnsZoneId") == f"[parameters('{zone}')]"
        assert _param(deployment, "subnetId") == "[parameters('privateEndpointSubnetId')]"
    assert by_group["vault"].get("condition") == KEY_VAULT_CONDITION
    assert "parameters('deployKeyVault')" in arm["outputs"]["privateEndpointIds"]["value"]


def test_diagnostics_cover_the_three_sites(arm: dict[str, Any]) -> None:
    diagnostics = [
        r for r in arm["resources"] if r["type"] == "Microsoft.Insights/diagnosticSettings"
    ]
    assert len(diagnostics) == 3
    scopes = " ".join(d["scope"] for d in diagnostics)
    for site in ("-api", "-workers", "-web"):
        assert site in scopes
    for d in diagnostics:
        assert "workspaceId" in d["properties"]


def test_no_secret_markers_in_names_or_values(arm: dict[str, Any]) -> None:
    dumped = json.dumps(arm).lower()
    for banned in ("listkeys", "listsecrets", "listconnectionstrings", "listaccountsas"):
        assert banned not in dumped
    for name in [*arm["parameters"], *arm["outputs"]]:
        if name not in SECRET_NAME_ALLOWED:
            assert not SECRET_MARKERS.search(name), name
    source = MAIN.read_text(encoding="utf-8")
    assert "listKeys" not in source
    assert not re.search(
        r"\.(windows\.net|azure\.com|azurewebsites\.net|azure\.net|usgovcloudapi\.net)", source
    )
    assert source.count("@description") >= len(PARAMETERS) + len(OUTPUTS)
    assert "targetScope = 'resourceGroup'" in source


def test_param_file_is_placeholders_only() -> None:
    text = PARAMS.read_text(encoding="utf-8")
    assert not GUID.search(text)
    assert not EMAIL.search(text)
    assert "/subscriptions/" not in text.lower()
    assert "using './main.bicep'" in text
    assert "param prefix = 'nsdemo'" in text
    assert "param location = 'centralus'" in text
    assert "param budgetContactEmails = []" in text


def test_param_file_names_are_template_parameters() -> None:
    declared = set(re.findall(r"^param (\w+) =", PARAMS.read_text(encoding="utf-8"), re.MULTILINE))
    assert declared <= set(PARAMETERS)
    assert NO_DEFAULT <= declared  # every required parameter has a placeholder
