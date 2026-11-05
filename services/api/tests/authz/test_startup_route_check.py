"""``compose_app`` runs the route inventory at startup (PRP-06 audit 2026-11-04, D4).

An undeclared route, whether mounted by ``create_app`` or appended by a builder, fails app boot
with ``invalid_schema`` / ``route_without_permission``; the real composed app boots clean.
"""

from __future__ import annotations

import os

import pytest
from fastapi import APIRouter, FastAPI, WebSocket
from neurosphere_api import main
from neurosphere_api.app import create_app
from neurosphere_api.authz.routes import GATEWAY_AUTHENTICATED_WEBSOCKETS, route_inventory
from neurosphere_api.runtime import compose_app
from neurosphere_api.runtime.builders import BuildContext, BuilderSpec
from neurosphere_core.cloud import Settings
from neurosphere_core.errors import InvalidSchemaError
from runtime_api.runtime_helpers import (  # pyright: ignore[reportMissingImports]
    authz_only,
    builders_with_stubs,
    compose,
    configure_auth_env,
    configured_overrides,
)

from .authz_helpers import FakeClock

_PREFIXES = ("NS_AUTH_", "NS_STORE_", "NS_CORS_", "NS_COSMOS_", "NS_REVOCATION_", "NS_COPILOT_")
_NAMES = ("NS_CLOUD", "NS_INGEST_PRODUCERS_FILE", "NS_SCAN_ENABLED", "NS_MCP_RESOURCE_SERVER_URL")
REALTIME_WS = "/api/v1/realtime/ws"


@pytest.fixture(autouse=True)
def _clean_composition_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # Same isolation as ``runtime_api/conftest.py``: no emulator, no tenant, local env.
    for name in sorted(os.environ):
        if name.startswith(_PREFIXES) or name in _NAMES:
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NS_ENV", "local")


def _leaky_router() -> APIRouter:
    router = APIRouter()

    @router.get("/leak")
    async def leak() -> dict[str, str]:
        return {}

    return router


def _compose_raises(app: FastAPI, builders: tuple[BuilderSpec, ...]) -> InvalidSchemaError:
    with pytest.raises(InvalidSchemaError) as info:
        compose_app(app, app.state.settings, builders=builders, env_probes=())
    assert info.value.reason == "route_without_permission"
    return info.value


def test_undeclared_route_fails_composition() -> None:
    app = create_app(Settings(), extra_routers={"/x": _leaky_router()})
    error = _compose_raises(app, authz_only())
    assert "GET /x/leak" in str(error)


def test_route_appended_by_a_builder_is_checked() -> None:
    def build(ctx: BuildContext) -> None:
        ctx.app.include_router(_leaky_router(), prefix="/late")

    late = BuilderSpec("late", (), build)
    error = _compose_raises(create_app(Settings()), (*authz_only(), late))
    assert "GET /late/leak" in str(error)


def test_undeclared_websocket_fails_composition() -> None:
    router = APIRouter()

    @router.websocket("/ws")
    async def ws(websocket: WebSocket) -> None:
        await websocket.close()

    app = create_app(Settings(), extra_routers={"/x": router})
    error = _compose_raises(app, authz_only())
    assert "WEBSOCKET /x/ws" in str(error)


def test_main_create_boots_clean_with_the_check_on() -> None:
    app = main.create()  # unconfigured: every builder reports, none raises
    entries = {(e.path, e.methods): e for e in route_inventory(app)}
    assert all(e.compliant for e in entries.values())
    assert entries[(REALTIME_WS, ("WEBSOCKET",))].gateway_authenticated


def test_configured_composition_boots_clean(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_auth_env(monkeypatch)
    clock = FakeClock()
    composed = compose(configured_overrides(clock), builders=builders_with_stubs(), clock=clock)
    assert composed.registry.get("authz").state == "ok"
    websockets = {e.path for e in route_inventory(composed.app) if e.websocket}
    # Every WebSocket the real app mounts is a reasoned gateway entry, and nothing else is.
    assert websockets == set(GATEWAY_AUTHENTICATED_WEBSOCKETS) == {REALTIME_WS}
