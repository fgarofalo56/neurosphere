"""PRP-58 item 2: the App Service profile exposes the data path switches, all off by default."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
BICEP = ROOT / "infra" / "appservice" / "main.bicep"
AZ = shutil.which("az")

pytestmark = pytest.mark.skipif(AZ is None, reason="az CLI not on PATH; CI bicep job backstops")

PARAMS = {
    "ingestProducerStore": False,
    "workerRoles": [],
    "workerConnectorConfigSource": "",
    "workerApiBaseUrl": "",
    "recommendationsSource": "",
}


@pytest.fixture(scope="module")
def arm() -> dict[str, Any]:
    assert AZ is not None
    proc = subprocess.run(
        [AZ, "bicep", "build", "--file", str(BICEP), "--stdout"],
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)  # type: ignore[no-any-return]


def _site_text(arm: dict[str, Any], suffix: str) -> str:
    resources = arm["resources"]
    rows = list(resources.values()) if isinstance(resources, dict) else list(resources)
    (site,) = [
        r
        for r in rows
        if r["type"] == "Microsoft.Web/sites" and f"-{suffix}'" in json.dumps(r["name"])
    ]
    return json.dumps(site["properties"]["siteConfig"]["appSettings"])


def test_parameters_default_to_off(arm: dict[str, Any]) -> None:
    for name, default in PARAMS.items():
        spec = arm["parameters"][name]
        assert spec["defaultValue"] == default
        assert spec["metadata"]["description"]


def test_settings_are_conditional_and_target_the_right_site(arm: dict[str, Any]) -> None:
    variables = arm["variables"]
    data_path = str(variables["workerDataPathSettings"])
    assert "empty(parameters('workerRoles'))" in data_path
    for key in (
        "NS_WORKER_ROLES",
        "NS_WORKER_CONNECTOR_CONFIG_SOURCE",
        "NS_API_BASE_URL",
        "NS_WORKER_REC_SOURCE",
    ):
        assert key in data_path
    assert "NS_INGEST_PRODUCER_STORE" in str(variables["ingestStoreSettings"])
    api = _site_text(arm, "api")
    workers = _site_text(arm, "workers")
    assert "ingestStoreSettings" in api and "ingestStoreSettings" not in workers
    assert "workerDataPathSettings" in workers and "workerDataPathSettings" not in api
