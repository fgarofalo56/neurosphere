"""Network baseline checks on real ``az bicep build`` output (PRP-12 item 3).

There is no recorded what-if fixture and none is fabricated: the live what-if stays OPEN until an
operator runs it with ``NS_LIVE_APPROVED=1``. These tests assert on the compiled ARM instead.
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
MODULES = ROOT / "infra" / "bicep" / "modules"
MAIN = MODULES / "main.bicep"
NETWORK = MODULES / "network" / "main.bicep"

AZ = shutil.which("az")

# environment() values per cloud (Bicep environment() function reference).
ENVIRONMENTS: dict[str, dict[str, Any]] = {
    "commercial": {
        "name": "AzureCloud",
        "portal": "https://portal.azure.com",
        "suffixes": {"storage": "core.windows.net", "keyvaultDns": ".vault.azure.net"},
    },
    "government": {
        "name": "AzureUSGovernment",
        "portal": "https://portal.azure.us",
        "suffixes": {
            "storage": "core.usgovcloudapi.net",
            "keyvaultDns": ".vault.usgovcloudapi.net",
        },
    },
}
# Verified against Learn "Azure Private Endpoint private DNS zone values" (2026-10-18).
EXPECTED_ZONES: dict[str, dict[str, str]] = {
    "commercial": {
        "cosmos": "privatelink.documents.azure.com",
        "eventhubs": "privatelink.servicebus.windows.net",
        "storage": "privatelink.blob.core.windows.net",
        "keyvault": "privatelink.vaultcore.azure.net",
        "search": "privatelink.search.windows.net",
    },
    "government": {
        "cosmos": "privatelink.documents.azure.us",
        "eventhubs": "privatelink.servicebus.usgovcloudapi.net",
        "storage": "privatelink.blob.core.usgovcloudapi.net",
        "keyvault": "privatelink.vaultcore.usgovcloudapi.net",
        "search": "privatelink.search.azure.us",
    },
}
PRIVATE_ENDPOINT_GROUPS = {"Sql", "namespace", "blob", "vault", "searchService"}


def _build(path: Path) -> dict[str, Any]:
    if AZ is None:
        pytest.skip("az CLI not on PATH; the CI bicep job is the backstop")
    # Absolute executable from shutil.which plus a fixed argv; no shell.
    proc = subprocess.run(
        [AZ, "bicep", "build", "--file", str(path), "--stdout"],
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


@pytest.fixture(scope="module")
def main_arm() -> dict[str, Any]:
    return _build(MAIN)


@pytest.fixture(scope="module")
def network_arm() -> dict[str, Any]:
    return _build(NETWORK)


def _resources(template: dict[str, Any]) -> list[dict[str, Any]]:
    res = template["resources"]
    return list(res.values()) if isinstance(res, dict) else list(res)


def _deployments(main_arm: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        r["name"]: r["properties"]
        for r in _resources(main_arm)
        if r["type"] == "Microsoft.Resources/deployments"
    }


# --- minimal ARM template-expression evaluator (only the functions the zone vars use) --------


class _Parser:
    def __init__(self, text: str, env: dict[str, Any], variables: dict[str, Any]) -> None:
        self.text, self.pos, self.env, self.variables = text, 0, env, variables

    def _ws(self) -> None:
        while self.text[self.pos] == " ":
            self.pos += 1

    def parse(self) -> Any:
        self._ws()
        if self.text[self.pos] == "'":
            return self._string()
        start = self.pos
        while self.text[self.pos].isalnum():
            self.pos += 1
        name = self.text[start : self.pos]
        assert self.text[self.pos] == "(", f"unsupported expression at {self.pos}: {self.text}"
        self.pos += 1
        args: list[Any] = []
        self._ws()
        while self.text[self.pos] != ")":
            args.append(self.parse())
            self._ws()
            if self.text[self.pos] == ",":
                self.pos += 1
            self._ws()
        self.pos += 1
        value = self._call(name, args)
        while self.pos < len(self.text) and self.text[self.pos] == ".":
            self.pos += 1
            start = self.pos
            while self.pos < len(self.text) and self.text[self.pos].isalnum():
                self.pos += 1
            value = value[self.text[start : self.pos]]
        return value

    def _string(self) -> str:
        self.pos += 1
        out = ""
        while True:
            ch = self.text[self.pos]
            if ch == "'":
                if self.text[self.pos + 1] == "'":
                    out += "'"
                    self.pos += 2
                    continue
                self.pos += 1
                return out
            out += ch
            self.pos += 1

    def _call(self, name: str, args: list[Any]) -> Any:
        if name == "environment":
            return self.env
        if name == "variables":
            return evaluate(self.variables[args[0]], self.env, self.variables)
        if name == "replace":
            return str(args[0]).replace(args[1], args[2])
        if name == "format":
            return re.sub(r"\{(\d+)\}", lambda m: str(args[int(m.group(1)) + 1]), args[0])
        if name == "equals":
            return args[0] == args[1]
        if name == "if":
            return args[1] if args[0] else args[2]
        raise AssertionError(f"unsupported ARM function {name}")


def evaluate(expr: Any, env: dict[str, Any], variables: dict[str, Any]) -> Any:
    if not (isinstance(expr, str) and expr.startswith("[") and expr.endswith("]")):
        return expr
    return _Parser(expr[1:-1], env, variables).parse()


@pytest.mark.parametrize("cloud", sorted(ENVIRONMENTS))
def test_private_dns_zone_derivation(network_arm: dict[str, Any], cloud: str) -> None:
    zones = network_arm["outputs"]["zoneNames"]["value"]
    derived = {
        key: evaluate(expr, ENVIRONMENTS[cloud], network_arm["variables"])
        for key, expr in zones.items()
    }
    assert derived == EXPECTED_ZONES[cloud]


def test_evaluator_handles_escaped_quotes() -> None:
    assert evaluate("[format('it''s {0}', 'ok')]", {}, {}) == "it's ok"


# --- network module shape -----------------------------------------------------------------


def test_private_endpoints_cover_the_five_services(
    network_arm: dict[str, Any], main_arm: dict[str, Any]
) -> None:
    endpoints = network_arm["variables"]["endpoints"]
    assert {e["groupId"] for e in endpoints} == PRIVATE_ENDPOINT_GROUPS
    types = {r["type"] for r in _resources(network_arm)}
    assert {
        "Microsoft.Network/privateEndpoints",
        "Microsoft.Network/privateEndpoints/privateDnsZoneGroups",
        "Microsoft.Network/privateDnsZones",
        "Microsoft.Network/privateDnsZones/virtualNetworkLinks",
    } <= types
    # The root template wires every data-plane module output into the network module.
    params = _deployments(main_arm)["ns-network"]["parameters"]
    for module, param in (
        ("cosmos", "cosmosId"),
        ("eventHubs", "eventHubsId"),
        ("storage", "storageId"),
        ("keyVault", "keyVaultId"),
        ("search", "searchId"),
    ):
        assert f"ns-{module.lower()}" in params[param]["value"].lower(), param


def test_nsg_outbound_denies_internet_with_service_tag_allowlist(
    network_arm: dict[str, Any],
) -> None:
    nsgs = [
        r for r in _resources(network_arm) if r["type"] == "Microsoft.Network/networkSecurityGroups"
    ]
    assert len(nsgs) == 2
    rules = network_arm["variables"]["securityRules"]
    outbound = [r["properties"] for r in rules if r["properties"]["direction"] == "Outbound"]
    deny = [r for r in outbound if r["access"] == "Deny"]
    assert [d["destinationAddressPrefix"] for d in deny] == ["Internet"]
    allowed = {r["destinationAddressPrefix"] for r in outbound if r["access"] == "Allow"}
    assert allowed == {"VirtualNetwork", "AzureActiveDirectory", "AzureMonitor"}
    deny_priority = deny[0]["priority"]
    assert all(r["priority"] < deny_priority for r in outbound if r["access"] == "Allow")
    # Inbound is VNet-only with a final deny.
    inbound = [r["properties"] for r in rules if r["properties"]["direction"] == "Inbound"]
    assert {r["sourceAddressPrefix"] for r in inbound if r["access"] == "Allow"} == {
        "VirtualNetwork"
    }
    assert any(
        r["access"] == "Deny" and r["sourceAddressPrefix"] == "*" and r["priority"] == 4096
        for r in inbound
    )


def test_no_public_ip_or_public_dns_in_network_module(network_arm: dict[str, Any]) -> None:
    assert not [r for r in _resources(network_arm) if "publicIPAddresses" in r["type"]]
    assert "Internet" not in json.dumps(
        [
            r
            for r in network_arm["variables"]["securityRules"]
            if r["properties"]["access"] == "Allow"
        ]
    )


# --- no public ingress except APIM --------------------------------------------------------


def _public_access_values(node: Any, path: str = "") -> list[tuple[str, Any]]:
    found: list[tuple[str, Any]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            sub = f"{path}.{key}"
            if key.lower().startswith("publicnetworkaccess"):
                found.append((sub, value))
            found.extend(_public_access_values(value, sub))
    elif isinstance(node, list):
        for i, value in enumerate(node):
            found.extend(_public_access_values(value, f"{path}[{i}]"))
    return found


def test_only_apim_can_have_public_ingress(main_arm: dict[str, Any]) -> None:
    # The single root switch defaults to Disabled and only allows Enabled/Disabled values.
    assert main_arm["parameters"]["publicNetworkAccess"]["defaultValue"] == "Disabled"
    deployments = _deployments(main_arm)
    checked = 0
    for name, dep in deployments.items():
        template = dep["template"]
        if name in ("ns-apim", "ns-network"):
            continue
        # Data-plane modules take the root switch and default their own to Disabled.
        if "publicNetworkAccess" in template["parameters"]:
            assert template["parameters"]["publicNetworkAccess"]["defaultValue"] == "Disabled", name
            assert dep["parameters"]["publicNetworkAccess"]["value"] == (
                "[parameters('publicNetworkAccess')]"
            ), name
            checked += 1
        # Every per-type property must derive from that parameter, never a literal 'Enabled'.
        for path, value in _public_access_values(_resources(template)):
            assert isinstance(value, str), (name, path)
            assert value.startswith("[") and "parameters('publicNetworkAccess')" in value, (
                name,
                path,
                value,
            )
    assert checked == 6  # cosmos, eventhubs, storage, keyvault, search, loganalytics


def test_apim_is_the_only_module_without_the_switch(main_arm: dict[str, Any]) -> None:
    without = {
        name
        for name, dep in _deployments(main_arm).items()
        if "publicNetworkAccess" not in dep["template"]["parameters"]
    }
    assert without == {"ns-apim", "ns-network"}


def test_reuse_default_leaves_no_public_literal_in_source() -> None:
    for path in MODULES.rglob("*.bicep"):
        if path.name == "apim.bicep":
            continue
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"publicNetworkAccess\w*\s*:\s*'(?i:enabled)'", text), path
