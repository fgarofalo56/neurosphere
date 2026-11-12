"""Government sovereign profile manifest checks (PRP-20 item 2). Offline except helm lint."""

from __future__ import annotations

import ipaddress
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, NoReturn
from urllib.parse import urlsplit

import pytest
import yaml
from neurosphere_core.capabilities.loader import load_matrix
from neurosphere_core.cloud import CloudName, profile_for
from neurosphere_core.search.azure.client import _GOV_AUDIENCE

ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / "infra" / "bicep" / "params" / "government" / "sovereign-profile.yaml"
VALUES = ROOT / "infra" / "helm" / "values-government.yaml"
CHART = ROOT / "infra" / "helm"
NETWORK_BICEP = ROOT / "infra" / "bicep" / "modules" / "network" / "main.bicep"
MAIN_BICEP = ROOT / "infra" / "bicep" / "modules" / "main.bicep"
BICEPPARAM = ROOT / "infra" / "bicep" / "params" / "government" / "main.bicepparam"

# A host is Government only when it ends in a known Government suffix (dot-delimited). The set is
# the Government cloud profile's own suffixes plus the manifest's documented ones, never a bare
# "azure.us", so a typo such as foo.azure.us or documents.azure.us.evil.com fails.
_GOV_PROFILE = profile_for(CloudName.GOVERNMENT)
KNOWN_GOV_SUFFIXES: frozenset[str] = frozenset(
    {
        _GOV_PROFILE.cosmos_suffix.lstrip("."),
        _GOV_PROFILE.eventhubs_suffix.lstrip("."),
        _GOV_PROFILE.search_suffix.lstrip("."),
        _GOV_PROFILE.apim_gateway_suffix.lstrip("."),
        _GOV_PROFILE.login_host.split(".", 1)[1],
        _GOV_PROFILE.management_host.split(".", 1)[1],
        # Documented in sovereign-profile.yaml (endpoints, privateDnsZones, egressHosts).
        "portal.azure.us",
        "graph.microsoft.us",
        "monitor.azure.us",
        "openai.azure.us",
        "cognitiveservices.azure.us",
        "opinsights.azure.us",
        "databricks.azure.us",
        "azure-automation.us",
        "azurewebsites.us",
        "azurecr.us",
        "loganalytics.us",
    }
)
GOV_SUFFIX = re.compile(
    r"(?:^|\.)(?:" + "|".join(re.escape(x) for x in sorted(KNOWN_GOV_SUFFIXES)) + r")$"
)
COMMERCIAL_HOST = re.compile(
    r"(?:microsoftonline\.com|windows\.net|azure\.com|azure\.net|azure-api\.net"
    r"|azurewebsites\.net|azurecr\.io|loganalytics\.io|graph\.microsoft\.com)(?![\w-])"
)


def _load(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


@pytest.fixture(scope="module")
def manifest() -> dict[str, Any]:
    return _load(MANIFEST)


@pytest.fixture(scope="module")
def values() -> dict[str, Any]:
    return _load(VALUES)


def _is_gov(host: str) -> bool:
    return GOV_SUFFIX.search(host.lstrip("*").lstrip(".")) is not None


def test_cloud_identity(manifest: dict[str, Any]) -> None:
    assert manifest["cloud"] == "government"
    assert manifest["azureEnvironment"] == "AzureUSGovernment"


def test_endpoints_equal_cloud_resolver(manifest: dict[str, Any]) -> None:
    prof = profile_for(CloudName.GOVERNMENT)
    ep = manifest["endpoints"]
    assert ep["login"] == prof.login_host
    assert ep["resourceManager"] == prof.management_host
    assert ep["cosmosSuffix"] == prof.cosmos_suffix
    assert ep["eventHubsSuffix"] == prof.eventhubs_suffix
    assert ep["searchSuffix"] == prof.search_suffix


def test_every_endpoint_is_government(manifest: dict[str, Any]) -> None:
    for name, host in manifest["endpoints"].items():
        assert _is_gov(host), f"{name}: {host}"


def test_helm_sovereign_profile_equals_manifest(
    manifest: dict[str, Any], values: dict[str, Any]
) -> None:
    mirrored = values["sovereignProfile"]
    assert mirrored["endpoints"] == manifest["endpoints"]
    assert mirrored["privateDnsZones"] == manifest["privateDnsZones"]
    assert mirrored["egressHosts"] == manifest["egressHosts"]


def test_helm_cloud_env_and_workload_identity(values: dict[str, Any]) -> None:
    assert values["env"]["NS_CLOUD"] == "government"
    registry = values["image"]["registry"]
    assert _is_gov(registry)
    assert re.search(r"\.azurecr\.us$", registry)
    assert values["serviceAccount"]["workloadIdentity"]["clientId"]
    entries = values["networkPolicy"]["egressAllowlist"]
    assert entries
    for entry in entries:
        assert re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}/\d{1,2}", entry["cidr"])


def test_private_dns_zones_are_government(manifest: dict[str, Any]) -> None:
    zones = manifest["privateDnsZones"]
    for key in ("cosmosSql", "eventHubs", "search", "keyVault", "storageBlob", "apimGateway"):
        assert key in zones
    assert any(z.startswith("privatelink.") and "monitor" in z for z in zones.values())
    for name, zone in zones.items():
        assert zone.startswith("privatelink."), name
        assert _is_gov(zone), f"{name}: {zone}"
        assert COMMERCIAL_HOST.search(zone) is None, f"{name}: {zone}"


def test_bicep_network_zone_derivation_agrees(manifest: dict[str, Any]) -> None:
    # Reproduce modules/network/main.bicep zone derivation under AzureUSGovernment.
    storage = "core.usgovcloudapi.net"
    platform = storage.replace("core.", "")
    portal = "azure.us"
    keyvault_dns = "vault.usgovcloudapi.net"
    derived = {
        "storageBlob": f"privatelink.blob.{storage}",
        "eventHubs": f"privatelink.servicebus.{platform}",
        "keyVault": "privatelink." + keyvault_dns.replace("vault.", "vaultcore.", 1),
        "cosmosSql": f"privatelink.documents.{portal}",
        "search": f"privatelink.search.{portal}",
    }
    zones = manifest["privateDnsZones"]
    for key, zone in derived.items():
        assert zones[key] == zone, key


def test_egress_hosts_are_government(manifest: dict[str, Any]) -> None:
    hosts = manifest["egressHosts"]
    assert hosts
    for host in hosts:
        assert _is_gov(host), host
        assert COMMERCIAL_HOST.search(host) is None, host


def test_allowed_regions(manifest: dict[str, Any]) -> None:
    regions = {r["name"]: r for r in manifest["allowedRegions"]}
    assert set(regions) == {"usgovvirginia", "usgovarizona", "usgovtexas"}
    assert regions["usgovtexas"]["fabricOnly"] is True
    assert regions["usgovvirginia"]["fabricOnly"] is False
    assert regions["usgovarizona"]["fabricOnly"] is False
    assert [r["name"] for r in manifest["allowedRegions"] if r["default"]] == ["usgovvirginia"]


def test_disabled_options_have_reason_and_source(manifest: dict[str, Any]) -> None:
    options = manifest["disabledOptions"]
    ids = [o["id"] for o in options]
    assert len(ids) == len(set(ids))
    for needed in (
        "fabric-outside-virginia-texas",
        "fabric-gcc-and-dod",
        "event-hubs-data-geo-replication",
        "foundry-hosted-agents",
        "foundry-web-search",
        "foundry-bing-grounding",
        "foundry-fabric-tool",
        "foundry-agent-to-agent",
        "app-service-managed-certificate",
        "azure-ad-b2c",
    ):
        assert needed in ids
    for option in options:
        assert str(option["reason"]).strip(), option["id"]
        assert re.match(r"https://learn\.microsoft\.com/", str(option["source"])), option["id"]


def test_capability_rows_referenced_exist(manifest: dict[str, Any]) -> None:
    matrix = load_matrix()
    for option in manifest["disabledOptions"]:
        refs = option.get("capabilityRow", [])
        for ref in [refs] if isinstance(refs, str) else refs:
            assert matrix.by_id(ref) is not None, f"{option['id']}: {ref}"
    for region in manifest["allowedRegions"]:
        if "capabilityRow" in region:
            assert matrix.by_id(region["capabilityRow"]) is not None


def test_audiences(manifest: dict[str, Any]) -> None:
    audiences = manifest["audiences"]
    # AI Search: verified, and equal to the value the search client actually uses.
    assert audiences["aiSearch"]["verified"] is True
    assert audiences["aiSearch"]["value"] == _GOV_AUDIENCE
    assert audiences["aiSearch"]["source"]
    # Event Hubs: one audience for every cloud, accepted only because it is flagged cross-cloud.
    assert audiences["eventHubs"]["verified"] is True
    assert audiences["eventHubs"]["crossCloud"] is True
    assert audiences["eventHubs"]["value"] == "https://eventhubs.azure.net/"
    assert audiences["eventHubs"]["source"]
    # Cosmos DB: still unverified; the pages checked and the date are recorded.
    cosmos = audiences["cosmosDb"]
    assert cosmos["verified"] is False
    assert cosmos["value"] is None
    assert cosmos["checked"]
    assert cosmos["checked_on"] == "2026-11-12"
    for name, aud in audiences.items():
        assert isinstance(aud["verified"], bool), name
        if aud["verified"]:
            assert aud["value"], name
            assert aud["source"], name
        value = aud["value"]
        if value is None or aud.get("crossCloud") is True:
            continue
        assert COMMERCIAL_HOST.search(value) is None, f"{name}: {value}"
        host = urlsplit(value).hostname
        assert host is not None, f"{name}: {value}"
        assert _is_gov(host), f"{name}: {value}"


def test_event_hubs_audience_is_not_an_egress_host(
    manifest: dict[str, Any], values: dict[str, Any]
) -> None:
    for hosts in (manifest["egressHosts"], values["sovereignProfile"]["egressHosts"]):
        assert not any("eventhubs.azure.net" in h for h in hosts)


def test_helm_audiences_mirror_manifest(manifest: dict[str, Any], values: dict[str, Any]) -> None:
    mirrored = values["sovereignProfile"]["audiences"]
    assert set(mirrored) == {"cosmosDb", "aiSearch", "eventHubs"}
    for name, aud in mirrored.items():
        source = manifest["audiences"][name]
        assert aud["value"] == source["value"], name
        assert aud["verified"] == source["verified"], name
        assert aud.get("crossCloud") == source.get("crossCloud"), name


@pytest.mark.parametrize(
    "host",
    [
        "foo.azure.us",
        "documents.azure.us.evil.com",
        "evildocuments.azure.us",
        "azure.us",
        "x.microsoft.us",
        "login.microsoftonline.com",
    ],
)
def test_gov_suffix_rejects_typos(host: str) -> None:
    assert not _is_gov(host)


@pytest.mark.parametrize(
    "host",
    [
        "myacct.documents.azure.us",
        "*.search.azure.us",
        "ns.servicebus.usgovcloudapi.net",
        "login.microsoftonline.us",
        "graph.microsoft.us",
        "privatelink.adx.monitor.azure.us",
        "reg.azurecr.us",
    ],
)
def test_gov_suffix_accepts_known_hosts(host: str) -> None:
    assert _is_gov(host)


def test_egress_cidr_matches_private_endpoint_subnet(values: dict[str, Any]) -> None:
    # Neither the root template nor the Government param file overrides the subnet prefix, so the
    # network module default is what is deployed. If an override is added, this must follow it.
    for path in (MAIN_BICEP, BICEPPARAM):
        assert "privateEndpointSubnetPrefix" not in path.read_text(encoding="utf-8"), path.name
    text = NETWORK_BICEP.read_text(encoding="utf-8")
    match = re.search(
        r"^param\s+privateEndpointSubnetPrefix\s+string\s*=\s*'([^']+)'", text, re.MULTILINE
    )
    assert match is not None, "privateEndpointSubnetPrefix default not found"
    deployed = ipaddress.ip_network(match.group(1))
    entries = {e["name"]: e for e in values["networkPolicy"]["egressAllowlist"]}
    assert ipaddress.ip_network(entries["private-endpoints"]["cidr"]) == deployed


def _skip_or_fail(reason: str) -> NoReturn:
    """Skip locally; fail when CI is set so a missing tool cannot hide a skipped scan (#100)."""
    if os.environ.get("CI", "").strip().lower() not in ("", "0", "false", "no"):
        pytest.fail(f"{reason} (CI is set: a missing tool must not skip the check)")
    pytest.skip(reason)


def test_helm_lint_with_government_values() -> None:
    helm = shutil.which("helm")
    if helm is None:
        _skip_or_fail("helm is not installed; the dedicated Helm CI job runs this test")
    # Absolute executable from shutil.which plus a fixed argv list; no shell.
    proc = subprocess.run(
        [helm, "lint", str(CHART), "-f", str(VALUES)],
        capture_output=True,
        text=True,
        check=False,
        cwd=ROOT,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
