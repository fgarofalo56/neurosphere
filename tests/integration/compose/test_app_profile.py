"""The `app` profile brings api and workers up healthy; the default profile stays emulators-only."""

from __future__ import annotations

import json
import shutil
import urllib.request
from collections.abc import Iterator

import pytest

from .conftest import compose

pytestmark = pytest.mark.integration

APP_SERVICES = {"api", "workers"}
EMULATOR_SERVICES = {"cosmos", "azurite", "eventhubs", "eventhubs-health"}


def _rows(*args: str) -> dict[str, dict[str, str]]:
    result = compose(*args, "ps", "--all", "--format", "json")
    assert result.returncode == 0, result.stderr
    rows = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    return {row["Service"]: row for row in rows}


@pytest.fixture(scope="module")
def app_stack() -> Iterator[None]:
    if shutil.which("docker") is None:
        pytest.skip("docker is not installed")
    result = compose("--profile", "app", "up", "-d", "--build", "--wait", timeout=1500)
    if result.returncode != 0:
        logs = compose("--profile", "app", "logs", "--no-color", "--tail", "50")
        compose("--profile", "app", "down", "--remove-orphans")
        pytest.fail(f"compose up failed:\n{result.stdout}\n{result.stderr}\n{logs.stdout}")
    try:
        yield
    finally:
        compose("--profile", "app", "down", "--remove-orphans")


def test_api_and_workers_are_healthy(app_stack: None) -> None:
    rows = _rows("--profile", "app")
    for name in APP_SERVICES:
        assert rows[name]["State"] == "running", name
        assert rows[name]["Health"] == "healthy", name


def test_api_readyz_is_200_from_host(app_stack: None) -> None:
    with urllib.request.urlopen("http://127.0.0.1:8000/readyz", timeout=10) as resp:
        assert resp.status == 200


def test_default_profile_lists_only_emulators() -> None:
    result = compose("config", "--services")
    assert result.returncode == 0, result.stderr
    services = set(result.stdout.split())
    assert services == EMULATOR_SERVICES
    assert not services & APP_SERVICES


def test_down_leaves_no_orphans() -> None:
    # Runs after the module fixture has been used; tear down explicitly and verify.
    result = compose("--profile", "app", "down")
    assert result.returncode == 0, result.stderr
    ps = compose("--profile", "app", "ps", "--all", "--format", "json")
    assert ps.returncode == 0, ps.stderr
    leftovers = [line for line in ps.stdout.splitlines() if line.strip()]
    assert leftovers == []
