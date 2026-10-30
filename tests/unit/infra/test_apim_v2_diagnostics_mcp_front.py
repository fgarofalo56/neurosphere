"""PRP-34 item 7: APIM v2 SKUs, created-only diagnostics, optional MCP front, Helm resource URL."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
MODULES = ROOT / "infra" / "bicep" / "modules"
POLICIES = MODULES / "policies"
CHART = ROOT / "infra" / "helm"
CI_VALUES = CHART / "ci" / "values-ci.yaml"

_COMMERCIAL_HOST = re.compile(
    r"[A-Za-z0-9.-]+\.(?:windows\.net|azure\.com|microsoftonline\.com|azure\.net|azure-api\.net)",
    re.IGNORECASE,
)


def find_commercial_hosts(text: str) -> list[str]:
    return _COMMERCIAL_HOST.findall(text)


AZ = shutil.which("az")
HELM = shutil.which("helm")
requires_az = pytest.mark.skipif(AZ is None, reason="az CLI not on PATH; CI bicep job covers it")


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_apim_allows_classic_and_v2_skus() -> None:
    text = _text(MODULES / "apim.bicep")
    allowed = re.search(r"@allowed\(\[([^\]]*)\]\)\s*param skuName", text)
    assert allowed
    names = set(re.findall(r"'(\w+)'", allowed.group(1)))
    assert names == {"Developer", "Standard", "Premium", "BasicV2", "StandardV2", "PremiumV2"}
    assert re.search(r"Microsoft\.ApiManagement/service@(\d{4}-\d{2}-\d{2})", text)
    version = re.search(r"service@(\d{4}-\d{2}-\d{2})", text)
    assert version
    assert version.group(1) >= "2024-05-01"  # v2 tiers need 2024-05-01 or later
    assert "capacity: effectiveCapacity" in text


def test_diagnostics_module_categories() -> None:
    text = _text(MODULES / "apim-diagnostics.bicep")
    for category in ("GatewayLogs", "GatewayLlmLogs", "GatewayMCPLogs"):
        assert f"category: '{category}'" in text


def test_main_wires_modules_only_for_created_instance() -> None:
    text = _text(MODULES / "main.bicep")
    diag = re.search(r"module apimDiagnostics .*?= if \((.*)\) \{", text)
    front = re.search(r"module apimMcpFront .*?= if \((.*)\) \{", text)
    assert diag and front
    assert "empty(reuseApim)" in diag.group(1)
    assert "empty(reuseApim)" in front.group(1)
    assert re.search(r"param enableApimMcpFront bool = false", text)


def test_government_params_use_classic_apim_tier() -> None:
    gov = _text(ROOT / "infra" / "bicep" / "params" / "government" / "main.bicepparam")
    sku = re.search(r"^param apimSkuName = '(\w+)'", gov, re.MULTILINE)
    assert sku
    assert not sku.group(1).endswith("V2")
    assert "enableApimMcpFront = false" in gov
    assert "unverified" in gov.lower()


def test_policies_parse_and_hold_enforcement_rules() -> None:
    enforcement = POLICIES / "apim-mcp-enforcement.xml"
    ET.fromstring(_text(enforcement))
    ET.fromstring(_text(POLICIES / "apim-mcp-prm.xml"))
    text = _text(enforcement)
    for header in ("Ocp-Apim-Subscription-Key", "api-key", "subscription-key"):
        assert f'<set-header name="{header}" exists-action="delete" />' in text
    assert "validate-jwt" in text
    assert "rate-limit-by-key" in text
    assert 'buffer-request-body="false"' in text
    # Never reads bodies.
    assert "context.Request.Body" not in text
    assert "context.Response.Body" not in text
    # Only named values, no literal hosts.
    assert not find_commercial_hosts(text)
    assert not find_commercial_hosts(_text(POLICIES / "apim-mcp-prm.xml"))


def test_mcp_front_declares_prm_operation_and_loads_policies() -> None:
    text = _text(MODULES / "apim-mcp-front.bicep")
    assert "urlTemplate: '/.well-known/oauth-protected-resource/mcp'" in text
    assert "loadTextContent('policies/apim-mcp-enforcement.xml')" in text
    assert "loadTextContent('policies/apim-mcp-prm.xml')" in text
    assert "environment().authentication.loginEndpoint" in text


def test_own_server_policy_retains_authorization_and_never_reads_bodies() -> None:
    text = _text(POLICIES / "apim-mcp-enforcement.xml")
    assert 'set-header name="Authorization"' not in text
    for header in ("Ocp-Apim-Subscription-Key", "api-key", "subscription-key"):
        assert f'<set-header name="{header}" exists-action="delete" />' in text
    assert "context.Request.Body" not in text
    assert "context.Response.Body" not in text


@requires_az
def test_main_arm_gates_diagnostics_and_front_on_created() -> None:
    assert AZ is not None
    proc = subprocess.run(
        [AZ, "bicep", "build", "--file", str(MODULES / "main.bicep"), "--stdout"],
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )
    assert proc.returncode == 0, proc.stderr
    arm: dict[str, Any] = json.loads(proc.stdout)
    resources = arm["resources"]
    items = resources.values() if isinstance(resources, dict) else resources
    by_name = {r["name"]: r for r in items if r["type"] == "Microsoft.Resources/deployments"}
    for name in ("ns-apim-diagnostics", "ns-apim-mcp-front"):
        assert "empty(parameters('reuseApim'))" in by_name[name]["condition"], name
    assert arm["parameters"]["enableApimMcpFront"]["defaultValue"] is False


def _helm_docs(*extra: str) -> list[dict[str, Any]]:
    if HELM is None:
        pytest.skip("helm is not installed; the dedicated Helm 4 CI job runs this test")
    proc = subprocess.run(
        [HELM, "template", "neurosphere", str(CHART), "-f", str(CI_VALUES), *extra],
        capture_output=True,
        text=True,
        check=False,
        cwd=ROOT,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    return [d for d in yaml.safe_load_all(proc.stdout) if d]


def _api_env(docs: list[dict[str, Any]]) -> dict[str, str]:
    api = next(
        d
        for d in docs
        if d["kind"] == "Deployment"
        and d["metadata"]["labels"]["app.kubernetes.io/component"] == "api"
    )
    return {
        e["name"]: e["value"]
        for e in api["spec"]["template"]["spec"]["containers"][0].get("env", [])
    }


def test_helm_values_default_off() -> None:
    for name in ("values.yaml", "values-government.yaml"):
        values = yaml.safe_load(_text(CHART / name))
        assert values["mcp"]["apimFront"]["enabled"] is False, name
        assert values["mcp"]["apimFront"]["gatewayHost"] == "", name


def test_helm_renders_resource_url_from_gateway_host_only_when_enabled() -> None:
    assert "NS_MCP_RESOURCE_SERVER_URL" not in _api_env(_helm_docs())
    docs = _helm_docs(
        "--set",
        "mcp.apimFront.enabled=true",
        "--set",
        "mcp.apimFront.gatewayHost=gw.example.invalid",
    )
    assert _api_env(docs)["NS_MCP_RESOURCE_SERVER_URL"] == "https://gw.example.invalid/mcp"
    other = next(
        d
        for d in docs
        if d["kind"] == "Deployment"
        and d["metadata"]["labels"]["app.kubernetes.io/component"] == "workers"
    )
    assert "env" not in other["spec"]["template"]["spec"]["containers"][0]


def test_helm_requires_gateway_host_when_enabled() -> None:
    if HELM is None:
        pytest.skip("helm is not installed")
    proc = subprocess.run(
        [
            HELM,
            "template",
            "n",
            str(CHART),
            "-f",
            str(CI_VALUES),
            "--set",
            "mcp.apimFront.enabled=true",
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=ROOT,
        timeout=120,
    )
    assert proc.returncode != 0
    assert "mcp.apimFront.gatewayHost is required" in proc.stderr
