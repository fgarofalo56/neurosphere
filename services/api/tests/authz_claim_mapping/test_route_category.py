"""PRP-138 item 4: the authenticated-self route category (``AUTHENTICATED_SELF_PATHS``).

A route is compliant in that category only when it is GET, its exact path is in the set and it
carries the ``require_authenticated`` marker. The marker elsewhere, a non-GET method, or the path
without the marker each fail ``verify_route_permissions``.
"""

from __future__ import annotations

from typing import Annotated

import pytest
from fastapi import APIRouter, Depends, FastAPI
from neurosphere_api.authz import (
    AUTHENTICATED_MARKER,
    AUTHENTICATED_SELF_PATHS,
    PERMISSION_MARKER,
    ROLE_MARKER,
    current_scope,
    require_authenticated,
    route_inventory,
    undeclared_routes,
    verify_route_permissions,
)
from neurosphere_core.auth.scope import ScopeDerivation
from neurosphere_core.errors import InvalidSchemaError
from neurosphere_core.scope import IdentityScope

ACCESS = "/api/v1/me/access"
NONE: frozenset[str] = frozenset()

Authenticated = Annotated[ScopeDerivation, Depends(require_authenticated())]


def _app(router: APIRouter) -> FastAPI:
    app = FastAPI(openapi_url=None)
    app.include_router(router)
    return app


def test_the_category_is_exactly_me_access() -> None:
    assert frozenset({ACCESS}) == AUTHENTICATED_SELF_PATHS


def test_marker_is_set_and_claims_no_permission() -> None:
    dependency = require_authenticated()
    assert getattr(dependency, AUTHENTICATED_MARKER, None) is True
    assert getattr(dependency, PERMISSION_MARKER, None) is None
    assert getattr(dependency, ROLE_MARKER, None) is None


def test_get_on_the_listed_path_with_the_marker_is_compliant() -> None:
    router = APIRouter()

    @router.get(ACCESS)
    async def access(derivation: Authenticated) -> dict[str, str]:
        return {}

    app = _app(router)
    verify_route_permissions(app, public_paths=NONE)
    [entry] = route_inventory(app, public_paths=NONE)
    assert (entry.path, entry.methods, entry.permissions) == (ACCESS, ("GET",), ())
    assert entry.authenticated_self is True
    assert entry.compliant is True


def test_marker_through_router_dependencies_is_seen() -> None:
    router = APIRouter(dependencies=[Depends(require_authenticated())])

    @router.get(ACCESS)
    async def access() -> dict[str, str]:
        return {}

    verify_route_permissions(_app(router), public_paths=NONE)


def test_marker_on_another_path_fails() -> None:
    router = APIRouter()

    @router.get("/api/v1/me/everything")
    async def everything(derivation: Authenticated) -> dict[str, str]:
        return {}

    app = _app(router)
    flagged = undeclared_routes(app, public_paths=NONE)
    assert [(e.path, e.authenticated_self) for e in flagged] == [("/api/v1/me/everything", False)]
    with pytest.raises(InvalidSchemaError) as caught:
        verify_route_permissions(app, public_paths=NONE)
    assert caught.value.reason == "route_without_permission"


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "HEAD"])
def test_marker_on_the_listed_path_with_a_non_get_method_fails(method: str) -> None:
    router = APIRouter()

    @router.api_route(ACCESS, methods=[method])
    async def access(derivation: Authenticated) -> dict[str, str]:
        return {}

    app = _app(router)
    with pytest.raises(InvalidSchemaError):
        verify_route_permissions(app, public_paths=NONE)
    [entry] = route_inventory(app, public_paths=NONE)
    assert entry.authenticated_self is False


def test_get_and_post_on_one_route_fails() -> None:
    router = APIRouter()

    @router.api_route(ACCESS, methods=["GET", "POST"])
    async def access(derivation: Authenticated) -> dict[str, str]:
        return {}

    with pytest.raises(InvalidSchemaError):
        verify_route_permissions(_app(router), public_paths=NONE)


def test_listed_path_without_the_marker_fails() -> None:
    router = APIRouter()

    @router.get(ACCESS)
    async def access(scope: Annotated[IdentityScope, Depends(current_scope)]) -> dict[str, str]:
        return {}  # authenticated, but not through require_authenticated: not enough

    app = _app(router)
    flagged = undeclared_routes(app, public_paths=NONE)
    assert [(e.path, e.authenticated_self) for e in flagged] == [(ACCESS, False)]
    with pytest.raises(InvalidSchemaError):
        verify_route_permissions(app, public_paths=NONE)


def test_a_forged_marker_value_is_not_the_marker() -> None:
    async def lookalike() -> None:
        return None

    setattr(lookalike, AUTHENTICATED_MARKER, "yes")  # only the exact True counts
    router = APIRouter()

    @router.get(ACCESS, dependencies=[Depends(lookalike)])
    async def access() -> dict[str, str]:
        return {}

    with pytest.raises(InvalidSchemaError):
        verify_route_permissions(_app(router), public_paths=NONE)
