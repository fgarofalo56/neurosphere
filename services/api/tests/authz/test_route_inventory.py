"""Route inventory: every non-public route declares a permission via ``require``; the public
allowlist is exact (probes, plus OpenAPI/docs only when configured)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

import pytest
from fastapi import APIRouter, Depends, FastAPI, WebSocket
from neurosphere_api.app import create_app
from neurosphere_api.authz import (
    PRODUCER_AUTHENTICATED_PATHS,
    PUBLIC_PATHS,
    configure_authz,
    current_scope,
    public_paths_for,
    require,
    route_inventory,
    undeclared_routes,
    verify_route_permissions,
)
from neurosphere_core.auth.scope import InMemoryPolicyRepository, Permission
from neurosphere_core.cloud import Settings
from neurosphere_core.errors import InvalidSchemaError
from neurosphere_core.scope import IdentityScope

from .authz_helpers import FakeClock, make_app, make_deriver, make_validator

DOCS = {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}


def test_factory_app_has_no_undeclared_routes() -> None:
    app = create_app(Settings(env="local"))
    assert undeclared_routes(app) == ()
    public = {e.path for e in route_inventory(app) if e.public}
    assert public == set(PUBLIC_PATHS) | DOCS
    producer = {e.path for e in route_inventory(app) if e.producer_authenticated}
    assert producer == set(PRODUCER_AUTHENTICATED_PATHS)
    assert not any(e.public for e in route_inventory(app) if e.producer_authenticated)
    verify_route_permissions(app)


def test_producer_authenticated_paths_are_exact() -> None:
    assert PRODUCER_AUTHENTICATED_PATHS == {
        "/v1/ingest/otlp/traces",
        "/v1/ingest/otlp/metrics",
        "/v1/ingest/events",
    }
    assert not PRODUCER_AUTHENTICATED_PATHS & public_paths_for(FastAPI())


def _ingest_router(*, extra_post: bool = False, get_on_listed: bool = False) -> APIRouter:
    router = APIRouter()

    @router.post("/otlp/traces")
    async def traces() -> dict[str, str]:
        return {}

    if extra_post:

        @router.post("/other")
        async def other() -> dict[str, str]:
            return {}

    if get_on_listed:

        @router.get("/events")
        async def events() -> dict[str, str]:
            return {}

    return router


def test_producer_authenticated_route_is_compliant_not_public() -> None:
    app = make_app(routers={"/v1/ingest": _ingest_router()})
    entry = next(e for e in route_inventory(app) if e.path == "/v1/ingest/otlp/traces")
    assert entry.producer_authenticated
    assert not entry.public
    assert entry.permissions == ()
    assert entry.compliant
    assert undeclared_routes(app) == ()


def test_unlisted_ingest_route_is_flagged() -> None:
    app = make_app(routers={"/v1/ingest": _ingest_router(extra_post=True)})
    assert {e.path for e in undeclared_routes(app)} == {"/v1/ingest/other"}


def test_get_on_listed_ingest_path_is_flagged() -> None:
    app = make_app(routers={"/v1/ingest": _ingest_router(get_on_listed=True)})
    flagged = undeclared_routes(app)
    assert [(e.path, e.methods) for e in flagged] == [("/v1/ingest/events", ("GET",))]


def test_mounted_app_on_producer_path_is_flagged() -> None:
    app = make_app()
    app.mount("/v1/ingest/events", FastAPI())
    assert "/v1/ingest/events" in {e.path for e in undeclared_routes(app)}


def test_test_routes_all_declare_permissions() -> None:
    app = make_app()
    assert undeclared_routes(app) == ()
    declared = {(e.path, e.methods): e.permissions for e in route_inventory(app) if not e.public}
    assert declared[("/t/config", ("POST",))] == ("config.manage",)
    assert declared[("/t/data", ("GET",))] == ("data.read",)


def _undeclared(router: APIRouter) -> None:
    @router.get("/leak")
    async def leak() -> dict[str, str]:
        return {}


def _authn_only(router: APIRouter) -> None:
    @router.get("/me")
    async def me(scope: Annotated[IdentityScope, Depends(current_scope)]) -> dict[str, str]:
        return {}


def _post_undeclared(router: APIRouter) -> None:
    @router.post("/write")
    async def write() -> dict[str, str]:
        return {}


def _websocket_undeclared(router: APIRouter) -> None:
    @router.websocket("/ws")
    async def ws(websocket: WebSocket) -> None:
        await websocket.close()


def _near_public(router: APIRouter) -> None:
    @router.get("/details")
    async def details() -> dict[str, str]:
        return {}


def _decorator_dep(router: APIRouter) -> None:
    @router.get("/a", dependencies=[Depends(require(Permission.DATA_READ))])
    async def a() -> dict[str, str]:
        return {}


def _param_dep(router: APIRouter) -> None:
    @router.get("/b")
    async def b(
        scope: Annotated[IdentityScope, Depends(require(Permission.DATA_EXPORT))],
    ) -> dict[str, str]:
        return {}


async def _curate_loader(
    scope: Annotated[IdentityScope, Depends(require(Permission.CATALOG_CURATE))],
) -> str:
    return "x"


def _nested_dep(router: APIRouter) -> None:
    @router.put("/c")
    async def c(value: Annotated[str, Depends(_curate_loader)]) -> dict[str, str]:
        return {}


# (name, router builder, router-level permission, expected undeclared paths)
CASES: list[tuple[str, Callable[[APIRouter], None], Permission | None, set[str]]] = [
    ("undeclared_get", _undeclared, None, {"/x/leak"}),
    ("authentication_is_not_a_permission", _authn_only, None, {"/x/me"}),
    ("undeclared_post", _post_undeclared, None, {"/x/write"}),
    ("undeclared_websocket", _websocket_undeclared, None, {"/x/ws"}),
    ("decorator_dependency", _decorator_dep, None, set()),
    ("parameter_dependency", _param_dep, None, set()),
    ("nested_dependency", _nested_dep, None, set()),
    ("router_level_dependency", _undeclared, Permission.DATA_READ, set()),
]


@pytest.mark.parametrize(
    ("builder", "router_permission", "expected"),
    [c[1:] for c in CASES],
    ids=[c[0] for c in CASES],
)
def test_inventory_flags_routes_without_permission(
    builder: Callable[[APIRouter], None],
    router_permission: Permission | None,
    expected: set[str],
) -> None:
    deps = [Depends(require(router_permission))] if router_permission else None
    router = APIRouter(dependencies=deps)
    builder(router)
    app = make_app(routers={"/x": router})
    assert {e.path for e in undeclared_routes(app)} == expected
    if expected:
        with pytest.raises(InvalidSchemaError) as info:
            verify_route_permissions(app)
        assert info.value.reason == "route_without_permission"
    else:
        verify_route_permissions(app)


def test_near_public_path_is_not_public() -> None:
    router = APIRouter()
    _near_public(router)
    app = make_app(routers={"/healthz": router})
    assert {e.path for e in undeclared_routes(app)} == {"/healthz/details"}


def test_include_time_dependency_counts() -> None:
    router = APIRouter()
    _undeclared(router)
    app = FastAPI()
    app.include_router(router, prefix="/inc", dependencies=[Depends(require(Permission.DATA_READ))])
    entries = {e.path: e for e in route_inventory(app)}
    assert entries["/inc/leak"].permissions == ("data.read",)
    assert undeclared_routes(app) == ()


def test_docs_are_public_only_when_configured() -> None:
    app = FastAPI(openapi_url=None)
    assert public_paths_for(app) == PUBLIC_PATHS

    @app.get("/openapi.json")
    async def fake_schema() -> dict[str, str]:
        return {}

    @app.get("/docs")
    async def fake_docs() -> dict[str, str]:
        return {}

    assert {e.path for e in undeclared_routes(app)} == {"/openapi.json", "/docs"}


def test_mounted_sub_application_is_never_public() -> None:
    app = make_app()
    app.mount("/healthz", FastAPI())
    app.mount("/static", FastAPI())
    undeclared = {e.path for e in undeclared_routes(app)}
    assert {"/healthz", "/static"} <= undeclared


def test_configured_extra_public_paths_are_used_by_default() -> None:
    router = APIRouter()

    @router.get("")
    async def metrics() -> dict[str, str]:
        return {}

    app = make_app(routers={"/metrics": router})
    assert {e.path for e in undeclared_routes(app)} == {"/metrics"}
    clock = FakeClock()
    configure_authz(
        app,
        authenticator=make_validator(clock),
        scope_source=make_deriver(InMemoryPolicyRepository(), clock),
        extra_public_paths=["/metrics"],
    )
    assert undeclared_routes(app) == ()


@pytest.mark.parametrize("bad", ["metrics", "/x/{id}", "/x*", "/a/{rest:path}"])
def test_extra_public_paths_must_be_exact(bad: str) -> None:
    with pytest.raises(InvalidSchemaError):
        public_paths_for(FastAPI(), extra=[bad])
