"""CORS allow-list fallback: off by default, exact origins only, never credentials or ``*``."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from neurosphere_api import main
from neurosphere_api.runtime import CorsSettings, load_cors_settings
from neurosphere_api.runtime.cors import ALLOWED_METHODS
from neurosphere_core.errors import InvalidSchemaError
from starlette.middleware.cors import CORSMiddleware

ALLOWED = "http://localhost:5173"
PREFLIGHT = {
    "Access-Control-Request-Method": "GET",
    "Access-Control-Request-Headers": "authorization",
}


def _preflight(client: TestClient, origin: str) -> dict[str, str]:
    response = client.options("/api/v1/me/domains", headers={"Origin": origin, **PREFLIGHT})
    return {k.lower(): v for k, v in response.headers.items()}


def _has_cors(app: object) -> bool:
    return any(m.cls is CORSMiddleware for m in app.user_middleware)  # type: ignore[attr-defined]


def test_no_origins_means_no_cors_middleware() -> None:
    app = main.create()
    assert not _has_cors(app)
    with TestClient(app) as client:
        headers = _preflight(client, ALLOWED)
    assert "access-control-allow-origin" not in headers


def test_listed_origin_is_allowed_without_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_CORS_ALLOWED_ORIGINS", f"{ALLOWED}, http://localhost:8080")
    app = main.create()
    assert _has_cors(app)
    with TestClient(app) as client:
        headers = _preflight(client, ALLOWED)
        simple = client.get("/healthz", headers={"Origin": ALLOWED})
    assert headers["access-control-allow-origin"] == ALLOWED
    assert "access-control-allow-credentials" not in headers
    assert set(headers["access-control-allow-methods"].split(", ")) == set(ALLOWED_METHODS)
    assert simple.headers["access-control-allow-origin"] == ALLOWED


def test_unlisted_origin_preflight_gets_no_allow_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_CORS_ALLOWED_ORIGINS", ALLOWED)
    with TestClient(main.create()) as client:
        headers = _preflight(client, "https://evil.example")
        simple = client.get("/healthz", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in headers
    assert "access-control-allow-origin" not in {k.lower() for k in simple.headers}


@pytest.mark.parametrize(
    "value",
    [
        "*",
        "https://*.example.com",
        f"{ALLOWED},*",
        "localhost:5173",
        "ftp://files.example",
        "https://app.example/path",
        "https://user@app.example",
    ],
)
def test_wildcards_and_non_origins_refuse_startup(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("NS_CORS_ALLOWED_ORIGINS", value)
    with pytest.raises(InvalidSchemaError) as caught:
        main.create()
    assert caught.value.reason == "config"


def test_origins_are_normalised_and_deduplicated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_CORS_ALLOWED_ORIGINS", "HTTP://LocalHost:5173/, http://localhost:5173")
    assert load_cors_settings().allowed_origins == (ALLOWED,)
    assert CorsSettings(allowed_origins=()).allowed_origins == ()
