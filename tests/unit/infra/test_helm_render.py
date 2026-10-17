"""Static render tests for the Helm 4 chart and the App Service profile (PRP-08 item 2).

Skips (with an explicit reason) when Helm 4 or the Azure CLI is not installed; a dedicated
CI job runs Helm 4.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
CHART = ROOT / "infra" / "helm"
CI_VALUES = CHART / "ci" / "values-ci.yaml"
APPSERVICE = ROOT / "infra" / "appservice"

WORKLOADS = ("api", "workers", "frontend")
AZURE_HOST = re.compile(
    r"[\w.-]+\.(?:azure\.com|azure\.us|windows\.net|microsoftonline\.com|microsoftonline\.us"
    r"|azurecr\.io|azurecr\.us|usgovcloudapi\.net|azure-api\.net)\b",
    re.IGNORECASE,
)


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    # Callers pass an absolute executable from shutil.which plus a fixed argv list; no shell.
    return subprocess.run(args, capture_output=True, text=True, check=False, cwd=ROOT, timeout=120)


def _helm() -> str:
    exe = shutil.which("helm")
    if exe is None:
        pytest.skip("helm is not installed; the dedicated Helm 4 CI job runs this test")
    out = _run([exe, "version", "--short"]).stdout.strip()
    match = re.match(r"v?(\d+)\.", out)
    if match is None or int(match.group(1)) != 4:
        pytest.skip(f"Helm 4 required (ADR-0002), found {out!r}")
    return exe


def _az() -> str:
    exe = shutil.which("az")
    if exe is None:
        pytest.skip("az CLI is not installed; cannot compile the App Service Bicep params")
    return exe


def _render(*extra: str) -> list[dict[str, Any]]:
    helm = _helm()
    proc = _run([helm, "template", "neurosphere", str(CHART), "-f", str(CI_VALUES), *extra])
    assert proc.returncode == 0, proc.stderr
    return [d for d in yaml.safe_load_all(proc.stdout) if d]


def _containers(docs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        d["metadata"]["labels"]["app.kubernetes.io/component"]: d["spec"]["template"]["spec"][
            "containers"
        ][0]
        for d in docs
        if d["kind"] == "Deployment"
    }


def test_three_workloads_present() -> None:
    docs = _render()
    deployments = {d["metadata"]["name"] for d in docs if d["kind"] == "Deployment"}
    services = {d["metadata"]["name"] for d in docs if d["kind"] == "Service"}
    assert deployments == {f"neurosphere-{w}" for w in WORKLOADS}
    assert services == deployments
    assert not any(d["kind"] == "Ingress" for d in docs)  # disabled by default


def test_workload_identity_and_probes() -> None:
    docs = _render()
    sa = next(d for d in docs if d["kind"] == "ServiceAccount")
    assert "azure.workload.identity/client-id" in sa["metadata"]["annotations"]
    api = _containers(docs)["api"]
    assert api["readinessProbe"]["httpGet"]["path"] == "/readyz"
    assert api["livenessProbe"]["httpGet"]["path"] == "/healthz"
    for c in _containers(docs).values():
        assert c["resources"]["requests"]
        assert c["resources"]["limits"]


def test_containers_hardened() -> None:
    docs = _render()
    for d in docs:
        if d["kind"] != "Deployment":
            continue
        pod = d["spec"]["template"]["spec"]
        assert pod["securityContext"]["runAsNonRoot"] is True
        assert pod["securityContext"]["seccompProfile"]["type"] == "RuntimeDefault"
        for c in pod["containers"]:
            sc = c["securityContext"]
            assert sc["runAsNonRoot"] is True
            assert sc["readOnlyRootFilesystem"] is True
            assert sc["allowPrivilegeEscalation"] is False
            assert sc["capabilities"]["drop"] == ["ALL"]


def test_no_secret_objects_or_literals() -> None:
    gated = [
        "--set",
        "secretProviderClass.enabled=true",
        "--set",
        "secretProviderClass.keyVaultName=kv-placeholder",
        "--set",
        "secretProviderClass.tenantId=00000000-0000-0000-0000-000000000000",
        "--set",
        "ingress.enabled=true",
        "--set",
        "ingress.host=app.example.invalid",
    ]
    for docs in (_render(), _render(*gated)):
        assert not any(d["kind"] == "Secret" for d in docs)
    spc = next(d for d in _render(*gated) if d["kind"] == "SecretProviderClass")
    assert spc["spec"]["provider"] == "azure"
    values_text = (CHART / "values.yaml").read_text(encoding="utf-8")
    values = yaml.safe_load(values_text)
    assert values["env"] == {}
    assert values["image"]["registry"] == ""  # nothing cloud-specific baked in


def test_registry_is_required() -> None:
    helm = _helm()
    client = "serviceAccount.workloadIdentity.clientId=00000000-0000-0000-0000-000000000000"
    proc = _run([helm, "template", "neurosphere", str(CHART), "--set", client])
    assert proc.returncode != 0
    assert "image.registry is required" in proc.stderr


def test_images_match_app_service_profile() -> None:
    images = {n: c["image"] for n, c in _containers(_render()).items()}

    az = _az()
    proc = _run(
        [az, "bicep", "build-params", "--file", str(APPSERVICE / "main.bicepparam"), "--stdout"]
    )
    assert proc.returncode == 0, proc.stderr
    built = json.loads(proc.stdout)
    given = json.loads(built["parametersJson"])["parameters"]
    template = json.loads(built["templateJson"])["parameters"]
    resolved = {
        k: given[k]["value"] if k in given else template[k].get("defaultValue")
        for k in ("imageRegistry", "imageTag", "apiRepository", "workersRepository")
    }
    for name, repo_key in (("api", "apiRepository"), ("workers", "workersRepository")):
        expected = f"{resolved['imageRegistry']}/{resolved[repo_key]}:{resolved['imageTag']}"
        assert images[name] == expected


def test_app_service_security_posture() -> None:
    text = (APPSERVICE / "main.bicep").read_text(encoding="utf-8")
    assert text.count("httpsOnly: true") == 2
    assert text.count("minTlsVersion: '1.2'") == 2
    assert text.count("ftpsState: 'Disabled'") == 2
    assert "@Microsoft.KeyVault(SecretUri=" in text
    assert re.search(r"(?i)(password|accountkey|connectionstring)\s*[:=]\s*'", text) is None


def test_no_literal_azure_endpoints() -> None:
    files = [
        *CHART.rglob("*.yaml"),
        *CHART.rglob("*.tpl"),
        APPSERVICE / "main.bicep",
        APPSERVICE / "main.bicepparam",
    ]
    for f in files:
        assert AZURE_HOST.search(f.read_text(encoding="utf-8")) is None, f
    helm = _helm()
    rendered = _run([helm, "template", "neurosphere", str(CHART), "-f", str(CI_VALUES)]).stdout
    assert AZURE_HOST.search(rendered) is None


def test_extension_points_left_to_later_prps() -> None:
    assert not (CHART / "templates" / "networkpolicy.yaml").exists()  # PRP-12
    assert not (CHART / "values-government.yaml").exists()  # PRP-20
    values = yaml.safe_load((CHART / "values.yaml").read_text(encoding="utf-8"))
    assert values["networkPolicy"]["enabled"] is False
