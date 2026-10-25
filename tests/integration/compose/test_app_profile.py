"""The `app` profile brings api, workers and frontend up healthy; the default stays emulators-only.

Two kinds of test live here. The static ones read ``docker-compose.yml`` and the ``Makefile`` and
run everywhere (no Docker). The ``integration`` ones need a Docker daemon and build the images.

Entra ids are never committed: compose reads ``NS_ENTRA_TENANT_ID``/``NS_ENTRA_CLIENT_ID`` from
the environment. The integration fixture supplies obviously fake, runtime-built placeholders when
they are not exported (token validation against a fake tenant fails; readiness does not need it).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import urllib.request
import uuid
from collections.abc import Iterator
from typing import Any, Final

import pytest
import yaml

from .conftest import REPO_ROOT, compose

APP_SERVICES = {"api", "workers", "frontend"}
#: One-shot that creates the Cosmos database and containers before api and workers start.
APP_ONE_SHOTS = {"cosmos-init"}
EMULATOR_SERVICES = {"cosmos", "azurite", "eventhubs", "eventhubs-health"}
#: The synthetic, non-secret worker principal. The only GUID literal allowed in compose/Makefile.
WORKER_OBJECT_ID: Final = "7d2e3f40-5b6c-4d7e-9f80-a1b2c3d4e5f6"
GUID: Final = re.compile(r"\b[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}\b")
FRONTEND_PORT: Final = os.environ.get("NS_FRONTEND_PORT", "8080")


def _compose_doc() -> dict[str, Any]:
    text = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    doc = yaml.safe_load(text)
    assert isinstance(doc, dict)
    return doc


def _services() -> dict[str, dict[str, Any]]:
    return dict(_compose_doc()["services"])


# --- static ----------------------------------------------------------------------------------


def test_app_profile_services_are_exactly_api_workers_frontend_and_the_init_job() -> None:
    in_app = {name for name, svc in _services().items() if svc.get("profiles") == ["app"]}
    assert in_app == APP_SERVICES | APP_ONE_SHOTS


def test_cosmos_init_runs_to_completion_before_api_and_workers() -> None:
    """Concurrent first-time container creation collides on a fresh emulator (see compose)."""
    services = _services()
    assert services["cosmos-init"]["restart"] == "no"
    for name in ("api", "workers"):
        init = services[name]["depends_on"]["cosmos-init"]
        assert init == {"condition": "service_completed_successfully"}, name


def test_there_is_no_seed_service() -> None:
    """The seed runs from the host (`make stack-up`): sbx_guard accepts loopback hosts only."""
    assert not [name for name in _services() if "seed" in name]


def test_workers_are_isolated_and_api_also_reaches_the_internet_side() -> None:
    services = _services()
    assert services["workers"]["networks"] == ["isolated"]
    assert services["api"]["networks"] == ["default", "isolated"]
    assert services["frontend"]["networks"] == ["default"]


def test_api_and_workers_env_names() -> None:
    services = _services()
    api, workers = services["api"]["environment"], services["workers"]["environment"]
    for name in (
        "NS_ENV",
        "NS_AUTH_TENANT_ID",
        "NS_AUTH_AUDIENCES",
        "NS_AUTH_CUSTOMER_ID",
        "NS_STORE_DATABASE",
        "NS_COSMOS_ENDPOINT",
        "NS_ARCHIVE_CONTAINER",
        "NS_CORS_ALLOWED_ORIGINS",
        "NS_COPILOT_MODE",
    ):
        assert name in api, name
    assert api["NS_CORS_ALLOWED_ORIGINS"] == ""
    assert api["NS_COPILOT_MODE"] == "disabled"
    for name in (
        "NS_ENV",
        "NS_WORKER_ROLES",
        "NS_AUTH_TENANT_ID",
        "NS_WORKER_OBJECT_ID",
        "NS_STORE_DATABASE",
        "NS_COSMOS_ENDPOINT",
    ):
        assert name in workers, name
    assert workers["NS_WORKER_ROLES"] == "all"
    # One tenant and customer for the api, the workers and the host seed.
    assert api["NS_AUTH_TENANT_ID"] == workers["NS_AUTH_TENANT_ID"]
    assert api["NS_AUTH_CUSTOMER_ID"] == workers["NS_AUTH_CUSTOMER_ID"]
    assert api["NS_STORE_DATABASE"] == workers["NS_STORE_DATABASE"]


def test_frontend_service_is_the_same_origin_edge() -> None:
    frontend = _services()["frontend"]
    assert frontend["build"]["dockerfile"] == "frontend/Dockerfile"
    assert frontend["ports"] == ["${NS_FRONTEND_PORT:-8080}:8080"]
    env = frontend["environment"]
    assert env["NS_UI_CLOUD"] == "commercial"
    assert env["NS_UI_API_UPSTREAM"] == "http://api:8000"
    assert "NS_ENTRA_TENANT_ID" in env["NS_UI_TENANT_ID"]
    assert "NS_ENTRA_CLIENT_ID" in env["NS_UI_CLIENT_ID"]
    assert env["NS_UI_API_SCOPE"].endswith("/access_as_user}")
    assert "/config.json" in " ".join(frontend["healthcheck"]["test"])
    assert frontend["depends_on"] == {"api": {"condition": "service_healthy"}}


def test_no_tenant_or_app_guid_and_no_credential_literal_is_committed() -> None:
    text = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert set(GUID.findall(text)) == {WORKER_OBJECT_ID}
    # Entra ids are env-only and must not be `${VAR:?}`-required: Compose interpolates every
    # service even when its profile is inactive, so that would break emulator-only `up`.
    assert "NS_ENTRA_TENANT_ID:?" not in text
    assert "NS_ENTRA_CLIENT_ID:?" not in text
    assert not re.search(r"AccountKey=[A-Za-z0-9+/=]{20,}", text)
    assert not re.search(r"SharedAccessKey=(?!\s)[A-Za-z0-9+/=_]{8,}", text)
    assert "UseDevelopmentStorage=true" not in text  # assembled from parts at runtime


def test_makefile_stack_targets_match_compose_worker_identity() -> None:
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    assert re.search(r"^stack-up:", makefile, re.MULTILINE)
    assert re.search(r"^stack-down:", makefile, re.MULTILINE)
    match = re.search(r"^STACK_WORKER_OID \?= (\S+)$", makefile, re.MULTILINE)
    assert match is not None
    assert match.group(1) == WORKER_OBJECT_ID
    workers_env = _services()["workers"]["environment"]
    assert workers_env["NS_WORKER_OBJECT_ID"] == "${NS_WORKER_OBJECT_ID:-" + WORKER_OBJECT_ID + "}"
    # The precheck names the variable it needs, and the seed runs after `up --wait`.
    assert "export NS_ENTRA_TENANT_ID first" in makefile
    assert "export NS_ENTRA_CLIENT_ID first" in makefile
    up = makefile.index("docker compose --profile app up -d --wait")
    seed = makefile.index("seed-stack", up)
    assert seed > up


# --- Docker ----------------------------------------------------------------------------------


def _rows(*args: str) -> dict[str, dict[str, str]]:
    result = compose(*args, "ps", "--all", "--format", "json")
    assert result.returncode == 0, result.stderr
    rows = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    return {row["Service"]: row for row in rows}


@pytest.fixture(scope="module")
def app_stack() -> Iterator[None]:
    if shutil.which("docker") is None:
        pytest.skip("docker is not installed")
    with pytest.MonkeyPatch.context() as mp:
        # Obviously fake placeholders, built at runtime (no GUID is committed); a real operator
        # exports their own. Readiness does not contact Entra.
        mp.setenv("NS_ENTRA_TENANT_ID", os.environ.get("NS_ENTRA_TENANT_ID", str(uuid.UUID(int=1))))
        mp.setenv("NS_ENTRA_CLIENT_ID", os.environ.get("NS_ENTRA_CLIENT_ID", str(uuid.UUID(int=2))))
        result = compose("--profile", "app", "up", "-d", "--build", "--wait", timeout=1500)
        if result.returncode != 0:
            logs = compose("--profile", "app", "logs", "--no-color", "--tail", "50")
            compose("--profile", "app", "down", "--remove-orphans")
            pytest.fail(f"compose up failed:\n{result.stdout}\n{result.stderr}\n{logs.stdout}")
        try:
            yield
        finally:
            compose("--profile", "app", "down", "--remove-orphans")


@pytest.mark.integration
def test_api_workers_and_frontend_are_healthy(app_stack: None) -> None:
    rows = _rows("--profile", "app")
    for name in APP_SERVICES:
        assert rows[name]["State"] == "running", name
        assert rows[name]["Health"] == "healthy", name


@pytest.mark.integration
def test_api_readyz_is_200_from_host(app_stack: None) -> None:
    with urllib.request.urlopen("http://127.0.0.1:8000/readyz", timeout=10) as resp:
        assert resp.status == 200


@pytest.mark.integration
def test_readyz_and_config_json_are_served_through_the_edge(app_stack: None) -> None:
    base = f"http://127.0.0.1:{FRONTEND_PORT}"
    with urllib.request.urlopen(f"{base}/readyz", timeout=10) as resp:
        assert resp.status == 200
        assert json.loads(resp.read())["status"] == "ready"
    with urllib.request.urlopen(f"{base}/config.json", timeout=10) as resp:
        config = json.loads(resp.read())
    assert config["apiBaseUrl"] == "/"
    assert config["apiScope"] == f"api://{config['clientId']}/access_as_user"


@pytest.mark.integration
def test_default_profile_lists_only_emulators() -> None:
    result = compose("config", "--services")
    assert result.returncode == 0, result.stderr
    services = set(result.stdout.split())
    assert services == EMULATOR_SERVICES
    assert not services & APP_SERVICES


@pytest.mark.integration
def test_down_leaves_no_orphans() -> None:
    # Runs after the module fixture has been used; tear down explicitly and verify.
    result = compose("--profile", "app", "down")
    assert result.returncode == 0, result.stderr
    ps = compose("--profile", "app", "ps", "--all", "--format", "json")
    assert ps.returncode == 0, ps.stderr
    leftovers = [line for line in ps.stdout.splitlines() if line.strip()]
    assert leftovers == []
