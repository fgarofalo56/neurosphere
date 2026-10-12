"""Needs the compose emulators: ``docker compose up -d --wait``."""

from __future__ import annotations

import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from neurosphere_api.app import create_app
from neurosphere_api.health import probes_from_env
from neurosphere_core.cloud import Settings

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[4]


def _compose(*args: str) -> None:
    subprocess.run(  # noqa: S603 - fixed argv, no shell
        ["docker", "compose", *args],  # noqa: S607
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        timeout=180,
    )


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app(Settings())
    app.state.health_probes = probes_from_env({})
    app.state.health_timeout = 2.0
    yield TestClient(app)


@pytest.fixture
def restore_cosmos() -> Iterator[None]:
    try:
        yield
    finally:
        _compose("up", "-d", "--wait", "cosmos")


def test_readyz_follows_cosmos_state(client: TestClient, restore_cosmos: None) -> None:
    up = client.get("/readyz")
    assert up.status_code == 200, up.text
    assert up.json()["dependencies"]["cosmos"] == "ok"

    _compose("stop", "cosmos")
    deadline = time.monotonic() + 30
    down = client.get("/readyz")
    while down.status_code == 200 and time.monotonic() < deadline:
        time.sleep(1)
        down = client.get("/readyz")
    assert down.status_code == 503
    body = down.json()
    assert body["status"] == "not_ready"
    assert body["dependencies"]["cosmos"] in {"connection_refused", "timeout", "unavailable"}
    assert client.get("/healthz").status_code == 200
