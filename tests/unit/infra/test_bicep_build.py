"""Compile every Bicep module and param file with the Azure CLI and check reuse semantics.

Skipped (with a reason) when ``az`` is not on PATH; the CI ``bicep`` job is the backstop.
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
BICEP_ROOT = ROOT / "infra" / "bicep"
MODULES = BICEP_ROOT / "modules"
PARAMS = BICEP_ROOT / "params"
MAIN = MODULES / "main.bicep"

AZ = shutil.which("az")
requires_az = pytest.mark.skipif(
    AZ is None, reason="az CLI not on PATH; the CI bicep job is the backstop for these builds"
)

# Every module except main.bicep is one reuse-or-create service family.
SERVICE_MODULES = {
    "cosmos": "Microsoft.DocumentDB/databaseAccounts",
    "eventhubs": "Microsoft.EventHub/namespaces",
    "storage": "Microsoft.Storage/storageAccounts",
    "keyvault": "Microsoft.KeyVault/vaults",
    "search": "Microsoft.Search/searchServices",
    "loganalytics": "Microsoft.OperationalInsights/workspaces",
    "apim": "Microsoft.ApiManagement/service",
}
SECRET_MARKERS = re.compile(
    r"listkeys|listsecrets|listconnectionstrings|connectionstring|primarykey|secondarykey|"
    r"accountkey|sharedaccesskey|password",
    re.IGNORECASE,
)


def _modules() -> list[Path]:
    return sorted(
        p for p in MODULES.rglob("*.bicep") if "network" not in p.relative_to(MODULES).parts
    )


def _params() -> list[Path]:
    return sorted(PARAMS.rglob("*.bicepparam"))


def _az(*args: str) -> str:
    assert AZ is not None
    proc = subprocess.run(
        [AZ, "bicep", *args], capture_output=True, text=True, check=False, timeout=300
    )
    assert proc.returncode == 0, f"az bicep {' '.join(args)} failed:\n{proc.stderr}"
    return proc.stdout


@pytest.fixture(scope="module")
def main_arm() -> dict[str, Any]:
    if AZ is None:
        pytest.skip("az CLI not on PATH; the CI bicep job is the backstop")
    return json.loads(_az("build", "--file", str(MAIN), "--stdout"))


@requires_az
@pytest.mark.parametrize("path", _modules(), ids=lambda p: p.name)
def test_module_builds(path: Path) -> None:
    assert json.loads(_az("build", "--file", str(path), "--stdout"))["resources"] is not None


@requires_az
@pytest.mark.parametrize("path", _params(), ids=lambda p: f"{p.parent.name}/{p.name}")
def test_params_build(path: Path) -> None:
    out = json.loads(_az("build-params", "--file", str(path), "--stdout"))
    assert "parameters" in json.dumps(out)


def _nested(main_arm: dict[str, Any]) -> dict[str, dict[str, Any]]:
    resources = main_arm["resources"]
    items = resources.values() if isinstance(resources, dict) else resources
    return {
        r["name"]: r["properties"] for r in items if r["type"] == "Microsoft.Resources/deployments"
    }


def test_all_service_modules_present() -> None:
    names = {p.stem for p in _modules()}
    assert set(SERVICE_MODULES) <= names
    assert "main" in names


@requires_az
@pytest.mark.parametrize("module", sorted(SERVICE_MODULES))
def test_reuse_skips_resource_declaration(main_arm: dict[str, Any], module: str) -> None:
    nested = _nested(main_arm)
    deployment = nested[f"ns-{module}"]
    template = deployment["template"]
    resources = template["resources"]
    resources = list(resources.values()) if isinstance(resources, dict) else resources
    typed = [r for r in resources if r["type"] == SERVICE_MODULES[module]]
    assert len(typed) == 1
    # A non-empty reuse id makes the condition false, so no resource is declared.
    assert typed[0]["condition"] == "[empty(parameters('reuse'))]"
    # The module's reuse input is wired to a main.bicep parameter, defaulting to empty.
    assert "reuse" in deployment["parameters"]
    assert re.fullmatch(r"\[parameters\('reuse\w+'\)\]", deployment["parameters"]["reuse"]["value"])
    # Output returns the reuse id when set, the new resource id otherwise.
    out = template["outputs"]["id"]["value"]
    assert out.startswith("[if(empty(parameters('reuse'))") and out.endswith(
        "parameters('reuse'))]"
    )


@requires_az
def test_reuse_params_default_to_empty(main_arm: dict[str, Any]) -> None:
    for name, spec in main_arm["parameters"].items():
        if name.startswith("reuse"):
            assert spec["defaultValue"] == "", name


@requires_az
def test_outputs_carry_no_secret_material(main_arm: dict[str, Any]) -> None:
    outputs: list[tuple[str, Any]] = list(main_arm.get("outputs", {}).items())
    for dep in _nested(main_arm).values():
        outputs.extend(dep["template"].get("outputs", {}).items())
    assert outputs
    for name, spec in outputs:
        assert not SECRET_MARKERS.search(name), name
        assert not SECRET_MARKERS.search(json.dumps(spec.get("value", ""))), name
        assert spec["type"] != "securestring", name
