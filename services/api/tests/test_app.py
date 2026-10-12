from __future__ import annotations

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from neurosphere_api.app import create_app
from neurosphere_api.main import create
from neurosphere_api.routers import RouterRegistry
from neurosphere_core.cloud import Settings
from neurosphere_core.errors import (
    CapabilityUnavailableError,
    DependencyTransientError,
    ForbiddenError,
    NeuroSphereError,
    RateLimitedError,
    StaleVersionError,
    UnauthorizedError,
)
from pydantic import BaseModel, ConfigDict


class Item(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str


def _app() -> FastAPI:
    router = APIRouter()
    errors: list[NeuroSphereError] = [
        UnauthorizedError(),
        ForbiddenError(),
        CapabilityUnavailableError("region_unsupported"),
        StaleVersionError(),
        RateLimitedError(7),
        DependencyTransientError(),
        DependencyTransientError(upstream_invalid=True),
    ]

    @router.get("/err/{idx}")
    def raise_err(idx: int) -> None:
        raise errors[idx]

    @router.get("/boom")
    def boom() -> None:
        raise RuntimeError("secret-host.internal.example password=hunter2")

    @router.post("/items")
    def make_item(item: Item) -> Item:
        return item

    return create_app(Settings(env="local"), extra_routers={"/t": router})


@pytest.fixture
def client() -> TestClient:
    return TestClient(_app(), raise_server_exceptions=False)


@pytest.mark.parametrize("idx", range(7))
def test_taxonomy_errors_render_contract_body(client: TestClient, idx: int) -> None:
    r = client.get(f"/t/err/{idx}")
    body = r.json()
    assert r.headers["content-type"].startswith("application/problem+json")
    assert body["status"] == r.status_code
    assert body["correlation_id"] == r.headers["x-correlation-id"]
    assert body["type"].endswith(body["code"])
    if body["code"] == "rate_limited":
        assert r.headers["retry-after"] == "7"


def test_validation_error_is_invalid_schema(client: TestClient) -> None:
    r = client.post("/t/items", json={"name": "x", "secret_value": "topsecret"})
    body = r.json()
    assert r.status_code == 422
    assert body["code"] == "invalid_schema"
    assert body["errors"]
    assert "topsecret" not in r.text


def test_not_found_and_method_not_allowed(client: TestClient) -> None:
    nf = client.get("/nope")
    assert nf.status_code == 404
    assert nf.json()["correlation_id"] == nf.headers["x-correlation-id"]
    na = client.delete("/t/items")
    assert na.status_code == 405


def test_unhandled_exception_has_no_trace_or_host(client: TestClient) -> None:
    r = client.get("/t/boom")
    assert r.status_code == 500
    assert "x-correlation-id" in r.headers
    assert "secret-host" not in r.text
    assert "hunter2" not in r.text
    assert "Traceback" not in r.text
    assert r.json()["correlation_id"] == r.headers["x-correlation-id"]


def test_registry_rejects_duplicate_prefix() -> None:
    registry = RouterRegistry()
    registry.register("/a", APIRouter())
    with pytest.raises(ValueError, match="already registered"):
        registry.register("/a/", APIRouter())
    assert registry.prefixes == ("/a",)


def test_create_app_rejects_duplicate_extra_prefix_with_default() -> None:
    with pytest.raises(ValueError, match="already registered"):
        create_app(Settings(env="local"), extra_routers={"/x": APIRouter(), "x": APIRouter()})


def test_factory_has_no_import_time_app_and_builds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_ENV", "local")
    assert isinstance(create(), FastAPI)
