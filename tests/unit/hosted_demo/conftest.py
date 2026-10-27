"""Shared helpers for the hosted-demo Bicep tests (compile with ``az bicep``, walk the ARM)."""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
DEMO_MODULES = ROOT / "infra" / "demo" / "modules"
CORE_MODULES = ROOT / "infra" / "bicep" / "modules"
CONTAINERS_JSON = ROOT / "infra" / "compose" / "cosmos-containers.json"
GOLDEN = Path(__file__).resolve().parent / "core_main_resources.golden.json"

AZ = shutil.which("az")
requires_az = pytest.mark.skipif(
    AZ is None, reason="az CLI not on PATH; the CI bicep job is the backstop for these builds"
)


def compile_bicep(path: Path) -> dict[str, Any]:
    """The compiled ARM template of ``path`` (fails the test when the build fails)."""
    assert AZ is not None
    proc = subprocess.run(
        [AZ, "bicep", "build", "--file", str(path), "--stdout"],
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )
    assert proc.returncode == 0, f"az bicep build {path.name} failed:\n{proc.stderr}"
    return json.loads(proc.stdout)


def resource_list(template: dict[str, Any]) -> list[dict[str, Any]]:
    """Top-level resources of a template (language version 2 emits a dict, v1 a list)."""
    resources = template.get("resources", [])
    return list(resources.values()) if isinstance(resources, dict) else list(resources)


def walk_resources(template: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Every resource, descending into nested deployment templates."""
    for res in resource_list(template):
        yield res
        props = res.get("properties")
        inner = props.get("template") if isinstance(props, dict) else None
        if res.get("type") == "Microsoft.Resources/deployments" and isinstance(inner, dict):
            yield from walk_resources(inner)


@pytest.fixture(scope="session")
def demo_arm() -> dict[str, dict[str, Any]]:
    """Compiled ARM of every demo module, keyed by file stem."""
    if AZ is None:
        pytest.skip("az CLI not on PATH; the CI bicep job is the backstop")
    return {p.stem: compile_bicep(p) for p in sorted(DEMO_MODULES.glob("*.bicep"))}
