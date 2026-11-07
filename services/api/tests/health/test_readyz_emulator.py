"""Real ``main.create`` against the Cosmos emulator; skips cleanly when it is down."""

from __future__ import annotations

import socket

import pytest
from fastapi.testclient import TestClient
from neurosphere_api import main
from neurosphere_api.health import TcpProbe

pytestmark = pytest.mark.integration

COSMOS_HOSTPORT = ("127.0.0.1", 8081)


def _emulator_up() -> bool:
    try:
        with socket.create_connection(COSMOS_HOSTPORT, timeout=1.0):
            return True
    except OSError:
        return False


def test_real_create_readyz_sees_cosmos_emulator(monkeypatch: pytest.MonkeyPatch) -> None:
    if not _emulator_up():
        pytest.skip("Cosmos emulator not reachable at 127.0.0.1:8081")
    monkeypatch.setenv("NS_ENV", "local")
    app = main.create()
    app.state.health_probes = [TcpProbe("cosmos", "127.0.0.1:8081")]
    app.state.health_timeout = 2.0
    response = TestClient(app).get("/readyz")
    assert response.status_code == 200, response.text
    assert response.json() == {"status": "ready", "dependencies": {"cosmos": "ok"}}
