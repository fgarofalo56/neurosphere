"""PRP-58 item 2: the Helm chart renders the hosted data path switches, all off by default."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
CHART = ROOT / "infra" / "helm"
CI_VALUES = CHART / "ci" / "values-ci.yaml"

DATA_PATH_ENV = (
    "NS_INGEST_PRODUCER_STORE",
    "NS_WORKER_CONNECTOR_CONFIG_SOURCE",
    "NS_API_BASE_URL",
    "NS_WORKER_REC_SOURCE",
)


def _render(*extra: str) -> dict[str, dict[str, str]]:
    """Env of each Deployment's first container, by component."""
    helm = shutil.which("helm")
    if helm is None:
        pytest.skip("helm is not installed; the dedicated Helm 4 CI job runs the chart tests")
    proc = subprocess.run(
        [helm, "template", "neurosphere", str(CHART), "-f", str(CI_VALUES), *extra],
        capture_output=True,
        text=True,
        check=False,
        cwd=ROOT,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    out: dict[str, dict[str, str]] = {}
    for doc in yaml.safe_load_all(proc.stdout):
        if not doc or doc.get("kind") != "Deployment":
            continue
        component = doc["metadata"]["labels"]["app.kubernetes.io/component"]
        container: dict[str, Any] = doc["spec"]["template"]["spec"]["containers"][0]
        out[component] = {e["name"]: e.get("value", "") for e in container.get("env", [])}
    return out


def test_defaults_render_none_of_the_data_path_env() -> None:
    envs = _render()
    for env in envs.values():
        assert not set(DATA_PATH_ENV) & set(env)
    assert "NS_WORKER_ROLES" not in envs["workers"]


def test_switches_land_on_the_right_workload() -> None:
    envs = _render(
        "--set",
        "ingest.producerStore=true",
        "--set",
        "workers.roles={ingestion,gateway_poll}",
        "--set",
        "workers.connectorConfigSource=auto",
        "--set",
        "workers.apiBaseUrl=http://neurosphere-api:8000",
        "--set",
        "workers.recommendations.source=archive",
    )
    assert envs["api"]["NS_INGEST_PRODUCER_STORE"] == "true"
    assert "NS_INGEST_PRODUCER_STORE" not in envs["workers"]
    workers = envs["workers"]
    assert workers["NS_WORKER_ROLES"] == "ingestion,gateway_poll"
    assert workers["NS_WORKER_CONNECTOR_CONFIG_SOURCE"] == "auto"
    assert workers["NS_API_BASE_URL"] == "http://neurosphere-api:8000"
    assert workers["NS_WORKER_REC_SOURCE"] == "archive"
    assert not set(DATA_PATH_ENV) & set(envs["frontend"])


def test_roles_accept_the_historical_string_form() -> None:
    envs = _render("--set", "workers.roles=ingestion\\,projections")
    assert envs["workers"]["NS_WORKER_ROLES"] == "ingestion,projections"


def test_no_connector_role_is_on_in_the_shipped_values() -> None:
    for path in (CHART / "values.yaml", CI_VALUES):
        values = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        roles = (values.get("workers") or {}).get("roles", "")
        text = ",".join(roles) if isinstance(roles, list) else str(roles)
        for role in ("gateway_poll", "foundry_discovery", "billing_export"):
            assert role not in text
