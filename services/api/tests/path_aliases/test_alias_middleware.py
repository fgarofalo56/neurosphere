"""PRP-51 item 1: alias headers on error responses, RFC 9745 form, route-kwarg parity, root_path,
and the alias expiry gate."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from neurosphere_api.deprecation import (
    ALIAS_SUCCESSORS,
    DEPRECATED_AT,
    DEPRECATION_HEADER,
    SUNSET,
    SUNSET_AT,
    alias_headers,
    deprecated_alias,
    install_alias_headers,
    register_with_alias,
)
from neurosphere_api.routers import RouterRegistry
from neurosphere_core.cloud import Settings

_HEADERS = ("deprecation", "sunset", "link")
REMOVAL_CHECKLIST = (
    "Alias removal checklist (docs/runbooks/api-path-aliases.md): drop the alias half of "
    "register_with_alias, delete deprecation.py users and tests, regenerate openapi.json."
)


@pytest.fixture
def alias_app(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr("neurosphere_api.deprecation.ALIAS_SUCCESSORS", {})
    router = APIRouter()

    @router.get("/denied/{code}")
    async def denied(code: int) -> dict[str, str]:
        raise HTTPException(status_code=code, detail="no")

    @router.get("/ok")
    async def ok() -> dict[str, str]:
        return {}

    app = FastAPI()
    registry = RouterRegistry()
    register_with_alias(registry, router, prefix="/api/v1/thing", alias_prefix="/thing")
    registry.attach(app)

    @app.get("/other/denied")
    async def other() -> None:
        raise HTTPException(status_code=401, detail="no")

    install_alias_headers(app)
    return TestClient(app)


def test_deprecation_value_is_rfc_9745_epoch() -> None:
    assert DEPRECATION_HEADER == f"@{int(DEPRECATED_AT.timestamp())}"
    assert DEPRECATION_HEADER.startswith("@")
    assert DEPRECATED_AT < SUNSET_AT


@pytest.mark.parametrize("code", [401, 403, 503])
def test_error_responses_on_an_alias_path_carry_the_headers(
    alias_app: TestClient, code: int
) -> None:
    response = alias_app.get(f"/thing/denied/{code}")
    assert response.status_code == code
    assert response.headers["deprecation"] == DEPRECATION_HEADER
    assert response.headers["sunset"] == SUNSET
    assert response.headers["link"] == f'</api/v1/thing/denied/{code}>; rel="successor-version"'


def test_validation_error_on_an_alias_path_carries_the_headers(alias_app: TestClient) -> None:
    response = alias_app.get("/thing/denied/notanumber")
    assert response.status_code == 422
    assert all(name in response.headers for name in _HEADERS)


def test_non_alias_paths_carry_no_headers(alias_app: TestClient) -> None:
    for path in ("/api/v1/thing/ok", "/other/denied", "/thingx/ok"):
        response = alias_app.get(path)
        assert not any(name in response.headers for name in _HEADERS), path


def test_headers_are_not_duplicated_with_the_dependency(alias_app: TestClient) -> None:
    response = alias_app.get("/thing/ok")
    assert response.status_code == 200
    assert response.headers.get_list("deprecation") == [DEPRECATION_HEADER]


def test_link_uses_the_path_under_a_nested_root_path() -> None:
    assert alias_headers("/audit/x", alias_prefix="/audit", successor_prefix="/api/v1/audit")[
        2
    ] == ("Link", '</api/v1/audit/x>; rel="successor-version"')
    router = APIRouter()

    @router.get("/x")
    async def x() -> dict[str, str]:
        return {}

    registry = RouterRegistry()
    register_with_alias(registry, router, prefix="/api/v1/rp", alias_prefix="/rp")
    try:
        app = FastAPI()
        registry.attach(app)
        install_alias_headers(app)
        client = TestClient(app, root_path="/edge/api")
        response = client.get("/rp/x")
        assert response.status_code == 200
        assert response.headers["link"] == '</api/v1/rp/x>; rel="successor-version"'
    finally:
        ALIAS_SUCCESSORS.pop("/rp", None)


def test_alias_copies_every_route_constructor_attribute(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fails with the attribute name when FastAPI adds or drops a route kwarg."""
    recorded: list[dict[str, Any]] = []
    original = APIRouter.add_api_route

    def spy(self: APIRouter, path: str, endpoint: Any, **kwargs: Any) -> None:
        recorded.append(kwargs)
        original(self, path, endpoint, **kwargs)

    router = APIRouter()

    @router.get("/x")
    async def x() -> dict[str, str]:
        return {}

    monkeypatch.setattr(APIRouter, "add_api_route", spy)
    deprecated_alias(router, alias_prefix="/old", successor_prefix="/api/v1/new")
    passed = set(recorded[0])
    accepted = set(inspect.signature(original).parameters) - {"self", "path", "endpoint"}
    assert accepted - passed == set(), f"alias drops add_api_route kwargs: {accepted - passed}"
    route_params = set(inspect.signature(APIRoute.__init__).parameters) - {
        "self",
        "path",
        "endpoint",
        "dependency_overrides_provider",  # injected by include_router
    }
    # ``route_class_override`` is the router-side name of the route class, not a route attribute.
    unhandled = route_params - passed
    assert unhandled == set(), f"APIRoute attributes the alias does not copy: {unhandled}"


def test_alias_removal_is_not_due_yet() -> None:
    now = datetime.now(UTC)
    assert now < SUNSET_AT, f"Sunset {SUNSET} reached. {REMOVAL_CHECKLIST}"


def test_composed_app_installs_the_middleware() -> None:
    from neurosphere_api.app import create_app
    from neurosphere_api.runtime import compose_app

    app = create_app(Settings(env="local"))
    compose_app(app, Settings(env="local"), builders=(), environ={}, env_probes=())
    response = TestClient(app).get("/audit/chains/x/records")
    assert response.status_code in (401, 403, 404, 503)
    assert response.headers["deprecation"] == DEPRECATION_HEADER
