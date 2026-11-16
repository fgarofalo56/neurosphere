"""PRP-54 item 4: compose, Helm and hosted Bicep carry an explicit, default-off opt-in."""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any, NoReturn

import yaml

ROOT = Path(__file__).resolve().parents[3]
CHART = ROOT / "infra" / "helm"
CI_VALUES = CHART / "ci" / "values-ci.yaml"
DEMO_MAIN = ROOT / "infra" / "demo" / "main.bicep"
COMPOSE = ROOT / "docker-compose.yml"

NEW_NAMES = (
    "NS_WRITE_TARGETS_FROM_STORE",
    "NS_FOUNDRY_ENABLED",
    "NS_FOUNDRY_SUBSCRIPTION_ID",
    "NS_FOUNDRY_RESOURCE_GROUP",
    "NS_FOUNDRY_ACCOUNT",
    "NS_FOUNDRY_LOCATION",
    "NS_APIM_ENABLED",
    "NS_APIM_GATEWAY_ID",
    "NS_APIM_DOMAIN_ID",
)
SECRET_SHAPED = re.compile(r"(SECRET|PASSW|TOKEN|_KEY$|CREDENTIAL|CONNECTION)")


def _load_skip_or_fail() -> Callable[[str], NoReturn]:
    path = Path(__file__).resolve().parents[2] / "security" / "egress" / "ci_gate.py"
    spec = importlib.util.spec_from_file_location("_ns_ci_gate_wt", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.skip_or_fail  # type: ignore[no-any-return]


_skip_or_fail = _load_skip_or_fail()


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, check=False, cwd=ROOT, timeout=180)


def _render(*extra: str) -> dict[str, dict[str, str]]:
    helm = shutil.which("helm")
    if helm is None:
        _skip_or_fail("helm is not installed; the dedicated Helm CI job runs this test")
    proc = _run([helm, "template", "neurosphere", str(CHART), "-f", str(CI_VALUES), *extra])
    assert proc.returncode == 0, proc.stderr
    env: dict[str, dict[str, str]] = {}
    for doc in yaml.safe_load_all(proc.stdout):
        if not doc or doc.get("kind") != "Deployment":
            continue
        container = doc["spec"]["template"]["spec"]["containers"][0]
        env[doc["metadata"]["labels"]["app.kubernetes.io/component"]] = {
            e["name"]: e.get("value", "") for e in container.get("env", [])
        }
    return env


def test_helm_defaults_render_no_write_target_env() -> None:
    for workload, env in _render().items():
        assert not [n for n in NEW_NAMES if n in env], workload


def test_helm_from_store_reaches_api_and_workers_only() -> None:
    env = _render("--set", "writeTargets.fromStore=true")
    assert env["api"]["NS_WRITE_TARGETS_FROM_STORE"] == "true"
    assert env["workers"]["NS_WRITE_TARGETS_FROM_STORE"] == "true"
    assert "NS_WRITE_TARGETS_FROM_STORE" not in env["frontend"]
    assert "NS_FOUNDRY_ENABLED" not in env["api"]


def test_helm_env_fallback_values_render_when_enabled() -> None:
    env = _render(
        "--set",
        "writeTargets.apim.enabled=true",
        "--set",
        "writeTargets.apim.gatewayId=gw-abc",
        "--set",
        "writeTargets.apim.domainId=commercial:acme:catalog:domain:fin",
        "--set",
        "writeTargets.foundry.enabled=true",
        "--set",
        "writeTargets.foundry.account=acct1",
    )
    for workload in ("api", "workers"):
        assert env[workload]["NS_APIM_ENABLED"] == "true"
        assert env[workload]["NS_APIM_GATEWAY_ID"] == "gw-abc"
        assert env[workload]["NS_FOUNDRY_ACCOUNT"] == "acct1"
    assert "NS_APIM_ENABLED" not in env["frontend"]


def test_helm_values_default_off() -> None:
    values = yaml.safe_load((CHART / "values.yaml").read_text(encoding="utf-8"))
    targets = values["writeTargets"]
    assert targets["fromStore"] is False
    assert targets["foundry"]["enabled"] is False
    assert targets["apim"]["enabled"] is False


def test_compose_passes_the_names_default_off_to_api_and_workers() -> None:
    compose = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    for service in ("api", "workers"):
        env = compose["services"][service]["environment"]
        for name in NEW_NAMES:
            assert name in env, (service, name)
        assert env["NS_WRITE_TARGETS_FROM_STORE"] == "${NS_WRITE_TARGETS_FROM_STORE:-false}"
        assert env["NS_FOUNDRY_ENABLED"] == "${NS_FOUNDRY_ENABLED:-false}"
        assert env["NS_APIM_ENABLED"] == "${NS_APIM_ENABLED:-false}"


def test_no_new_name_looks_like_a_secret() -> None:
    assert not [n for n in NEW_NAMES if SECRET_SHAPED.search(n)]


def test_demo_bicep_param_defaults_false_and_reaches_api_and_workers() -> None:
    az = shutil.which("az")
    if az is None:
        _skip_or_fail("az CLI is not installed; the CI bicep job runs this test")
    proc = _run([az, "bicep", "build", "--file", str(DEMO_MAIN), "--stdout"])
    assert proc.returncode == 0, proc.stderr
    template: dict[str, Any] = json.loads(proc.stdout)
    param = template["parameters"]["writeTargetsFromStore"]
    assert param["type"] == "bool"
    assert param["defaultValue"] is False
    variables = template["variables"]
    assert "NS_WRITE_TARGETS_FROM_STORE" in json.dumps(variables["writeTargetSettings"])
    text = DEMO_MAIN.read_text(encoding="utf-8")
    assert "union(apiSettings, writeTargetSettings)" in text
    assert "evaluationPilotSettings,\n  writeTargetSettings" in text
