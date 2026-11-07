"""``/readyz`` and error bodies through the real ``neurosphere_api.main.create`` entry point."""

from __future__ import annotations

import json
import socket

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from neurosphere_api import main
from neurosphere_api.health import TcpProbe

ENUMERATED = {"ok", "timeout", "connection_refused", "unavailable"}


def _closed_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _real_app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    monkeypatch.setenv("NS_ENV", "local")
    app = main.create()
    return app


def test_real_create_readyz_503_with_enumerated_reasons(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _real_app(monkeypatch)
    port = _closed_port()
    app.state.health_probes = [
        TcpProbe("cosmos", f"127.0.0.1:{port}"),
        TcpProbe("blob", f"127.0.0.1:{port}"),
    ]
    app.state.health_timeout = 1.0
    response = TestClient(app).get("/readyz")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert set(body["dependencies"]) == {"cosmos", "blob"}
    assert set(body["dependencies"].values()) <= ENUMERATED - {"ok"}
    text = json.dumps(body)
    for needle in ("127.0.0.1", str(port), "AccountKey", "https://"):
        assert needle not in text


def test_real_create_error_bodies_carry_correlation_and_no_leaks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TestClient(_real_app(monkeypatch), raise_server_exceptions=False)
    for response in (client.get("/definitely-not-a-route"), client.delete("/healthz")):
        assert response.status_code in {404, 405}
        assert response.headers["x-correlation-id"]
        assert response.json()["correlation_id"] == response.headers["x-correlation-id"]
        assert "Traceback" not in response.text
        assert "127.0.0.1" not in response.text
